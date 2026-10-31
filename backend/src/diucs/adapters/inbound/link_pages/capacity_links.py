"""The one-tap capacity link pages' API (L01, DEC-167, DEC-134 item 3).

GET  /links/{token}        what is on record, changing nothing
POST /links/{token}        a confirm, a new number or "closed" (X-CSRF-Token required)
POST /links/{token}/renew  a fresh prompt when the link has expired (always 202)

A link is a bearer token sent by text, and these routes are open to anyone who can reach them, so
the order of work is the security of the page:

1. The tenant comes from the host the request was addressed to, through the tenant directory, and
   from nowhere else: not the path, the query string, the body or any header but the host (a body
   that names a tenant is refused as an unknown field). A host the directory does not know, or a
   tenant that is not active, answers as an unknown link. The tenant is bound once, here, for the
   whole request.
2. Everything after that runs in that tenant: the link-token statements are scoped to it, so another
   tenant's link is not found and answers exactly as an expired one does.
3. Every failure has one fixed body and no detail: `{state}` and, where the page needs them, the
   usual range of the service whose link it is. A token, a hash, a value or an address is never in
   a response, a header, a log line or an error. Responses are `no-store` with
   `Referrer-Policy: no-referrer`, because the token is in the URL. The access log of the server
   would hold the URL, so `RedactLinkTokens` is installed on it.

The routes hold no business rule: they bind the tenant, run one use case and map the result.
"""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from diucs.adapters.inbound.link_pages.booking_links import booking_purposes
from diucs.application.edge_tenant import resolve_active_tenant
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.tokens import (
    LinkTokenRepository,
    LinkTokenService,
    SecretStore,
)
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity
from diucs.application.use_cases.link_access import (
    CAPACITY_PURPOSE,
    CapacityLinkHandler,
    ClosedDetail,
    CsrfRejected,
    LinkAction,
    LinkConflict,
    LinkGone,
    LinkOutOfRange,
    LinkPurposes,
    LinkRateLimited,
    RenewLink,
    RenewLinkCommand,
    RespondViaLink,
    RespondViaLinkCommand,
    SendTheNumber,
    UnitOfWorkIdempotency,
    ViewLink,
    ViewLinkQuery,
    closed_body,
)
from diucs.application.use_cases.report_capacity import ReportCapacity
from diucs.application.use_cases.respond_to_booking import RespondToBooking
from diucs.application.use_cases.withdraw_booking import ReportNotReached, WithdrawBooking
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant import Tenant
from diucs.domain.rules.london_time import zone_named

log = logging.getLogger(__name__)

LINKS_PATH_PREFIX: Final = "/links"
LINK_PAGE_PATH: Final = "/l"
"""Where the page that a link opens lives on the tenant's host (the Next.js route `app/l/[token]`).
A renewed link is `https://<host>/l/<token>`."""
LINK_SCHEME: Final = "https"
MAX_BODY_BYTES: Final = 1024
SEND_THE_NUMBER_TEXT: Final = "Please send the number"

_FIELDS: Final = frozenset({"action", "value", "confirmOutOfRange", "reason"})
_NO_STORE: Final = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_ACCESS_LOGGER: Final = "uvicorn.access"
_LINK_IN_TEXT: Final = re.compile(r"(/(?:links|invitations)/)[^/?#\s\"']+")


class RedactLinkTokens(logging.Filter):
    """Hides the token of a link wherever a log record shows a request path (the server's access
    log writes the URL). Install it on the access logger of the serving process; importing this
    module installs it on `uvicorn.access`."""

    @staticmethod
    def _redact(value: object) -> object:
        return _LINK_IN_TEXT.sub(r"\1[token]", value) if isinstance(value, str) else value

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self._redact(arg) for arg in record.args)
        return True


def install_log_redaction(logger_name: str = _ACCESS_LOGGER) -> None:
    logger = logging.getLogger(logger_name)
    if not any(isinstance(f, RedactLinkTokens) for f in logger.filters):
        logger.addFilter(RedactLinkTokens())


install_log_redaction()


@dataclass(frozen=True, slots=True)
class LinkPagesDeps:
    """What the link routes need besides the container. Set on `app.state.link_pages` by the
    process that serves the app (as for the SMS webhook, I07); a missing one is a 500, never an
    open route."""

    cache: Cache
    sealer: ContentSealer


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...

    @property
    def ids(self) -> IdGenerator: ...

    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...

    @property
    def tenants(self) -> TenantDirectory: ...

    @property
    def secrets(self) -> SecretStore: ...


def _json(status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> Response:
    return JSONResponse(body, status_code=status, headers={**_NO_STORE, **(headers or {})})


def _gone(state: str = "expired", detail: ClosedDetail | None = None) -> Response:
    return _json(410, closed_body(state, detail))


def _refused(reason: str) -> None:
    # A reason word only: never the token, a hash, a value, the host or an address.
    log.warning("link request refused: reason=%s", reason)


def _collaborators(request: Request) -> tuple[_Container, LinkPagesDeps]:
    # Fail closed: a missing collaborator is a configuration error (a 500), never an open route.
    container: _Container | None = getattr(request.app.state, "container", None)
    deps: LinkPagesDeps | None = getattr(request.app.state, "link_pages", None)
    if container is None or deps is None:
        raise RuntimeError("the link pages are not configured")
    return container, deps


async def _tenant_of(request: Request, container: _Container) -> Tenant | None:
    """The active tenant whose host this request was addressed to, or None."""
    return await resolve_active_tenant(container.tenants, request.url.hostname)


def _tokens(container: _Container) -> Callable[[LinkTokenRepository], LinkTokenService]:
    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, container.secrets, container.clock)

    return tokens


def _purposes(container: _Container, deps: LinkPagesDeps, tenant: Tenant) -> LinkPurposes:
    tokens = _tokens(container)
    idempotency = UnitOfWorkIdempotency(container.uow_factory)
    return {
        CAPACITY_PURPOSE: CapacityLinkHandler(
            container.uow_factory,
            container.clock,
            container.ids,
            tokens,
            deps.sealer,
            ReportCapacity(container.uow_factory, container.clock, container.ids, idempotency),
            ConfirmCapacity(container.uow_factory, container.clock, container.ids, idempotency),
            zone=zone_named(tenant.time_zone),
        ),
        **booking_purposes(
            container.uow_factory,
            container.clock,
            tokens,
            RespondToBooking(
                container.uow_factory, idempotency, container.clock, container.ids, deps.sealer
            ),
            WithdrawBooking(container.uow_factory, idempotency, container.clock, container.ids),
            ReportNotReached(container.uow_factory, idempotency, container.clock),
        ),
    }


def _client(request: Request) -> str:
    return request.client.host if request.client is not None else ""


async def _read_json(request: Request) -> dict[str, Any] | None:
    """The request body as a JSON object of at most MAX_BODY_BYTES, or None. The body is read in
    pieces and abandoned at the limit, so a large body is never held."""
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
        return None
    received = bytearray()
    async for chunk in request.stream():
        received.extend(chunk)
        if len(received) > MAX_BODY_BYTES:
            return None
    try:
        parsed = json.loads(bytes(received))
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _action_of(body: dict[str, Any] | None) -> LinkAction:
    """The answer in the body. An unknown field (a tenant, for one), a missing action or a wrong
    type is a `ValidationFailed` that names the field only."""
    if body is None:
        raise ValidationFailed("body", "must be a JSON object")
    if not set(body) <= _FIELDS:
        raise ValidationFailed("body", "has a field this link does not take")
    action = body.get("action")
    if not isinstance(action, str):
        raise ValidationFailed("action", "is required")
    return LinkAction(
        action=action,
        value=body.get("value"),
        confirm_out_of_range=body.get("confirmOutOfRange", False),
        reason=body.get("reason"),
    )


async def _guarded(run: Callable[[], Awaitable[Response]]) -> Response:
    """Run one request and map every answer a link can give. Nothing that is not a state word or a
    number of the service's own record reaches a body; any other failure is a fixed 500."""
    try:
        return await run()
    except LinkGone as error:
        return _gone(error.state, error.detail)
    except CsrfRejected:
        return _json(403, {"state": "forbidden"})
    except LinkConflict as error:
        return _json(409, closed_body(error.state, error.detail))
    except LinkOutOfRange as error:
        return _json(
            422,
            {"state": "out-of-range", "usualMin": error.usual_min, "usualMax": error.usual_max},
        )
    except SendTheNumber as error:
        return _json(
            409,
            {"state": "send-number", "reason": error.reason, "message": SEND_THE_NUMBER_TEXT},
        )
    except ValidationFailed:
        return _json(400, {"state": "invalid"})
    except LinkRateLimited as error:
        return _json(
            429,
            {"state": "rate-limited"},
            {"Retry-After": str(error.retry_after_seconds)},
        )
    except Exception as error:
        log.error("link request failed: %s", type(error).__name__)
        return _json(500, {"state": "error"})


router = APIRouter(prefix=LINKS_PATH_PREFIX)


@router.get("/{token}")
async def view_link(token: str, request: Request) -> Response:
    async def run() -> Response:
        container, deps = _collaborators(request)
        tenant = await _tenant_of(request, container)
        if tenant is None:
            _refused("host")
            return _gone()
        with bind_tenant(tenant.id):
            result = await ViewLink(
                container.uow_factory,
                container.clock,
                container.secrets,
                deps.cache,
                _tokens(container),
                _purposes(container, deps, tenant),
            ).execute(ViewLinkQuery(token=token, client=_client(request)))
        return _json(200, dict(result.body))

    return await _guarded(run)


@router.post("/{token}")
async def respond_via_link(token: str, request: Request) -> Response:
    async def run() -> Response:
        container, deps = _collaborators(request)
        tenant = await _tenant_of(request, container)
        if tenant is None:
            _refused("host")
            raise CsrfRejected  # no link can be found on this host, so no token can be right
        action = _action_of(await _read_json(request))
        with bind_tenant(tenant.id):
            result = await RespondViaLink(
                container.uow_factory,
                container.clock,
                container.secrets,
                deps.cache,
                _tokens(container),
                _purposes(container, deps, tenant),
            ).execute(
                RespondViaLinkCommand(
                    token=token,
                    csrf_token=request.headers.get("x-csrf-token"),
                    action=action,
                    client=_client(request),
                )
            )
        return _json(200, dict(result.body))

    return await _guarded(run)


@router.post("/{token}/renew")
async def renew_link(token: str, request: Request) -> Response:
    async def run() -> Response:
        container, deps = _collaborators(request)
        tenant = await _tenant_of(request, container)
        if tenant is not None:
            with bind_tenant(tenant.id):
                await RenewLink(
                    container.uow_factory,
                    container.clock,
                    container.secrets,
                    deps.cache,
                    _tokens(container),
                    _purposes(container, deps, tenant),
                ).execute(
                    RenewLinkCommand(
                        token=token,
                        client=_client(request),
                        link_base_url=(f"{LINK_SCHEME}://{request.url.hostname}{LINK_PAGE_PATH}"),
                    )
                )
        return _json(202, {"state": "accepted"})

    return await _guarded(run)
