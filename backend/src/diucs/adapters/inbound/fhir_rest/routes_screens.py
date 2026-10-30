"""Wall screen pairing over HTTP (R15, U10, DEC-160).

POST /screens/pairing                start: the wall display asks for a code. No token; the
                                     tenant is the one the host names, and nothing else.
GET  /screens/pairing/{pairingId}    claim: the display asks whether a lead has connected it and
                                     gets its device token once. No token; the secret comes only
                                     in the X-Screen-Secret header, never in the URL; the tenant is
                                     the host's.
POST /screens                        connect: a shift lead types the code and a screen name. Role
                                     lead, Idempotency-Key required. The tenant is the lead's: the
                                     role dependency binds it from the verified token (TEN-018,
                                     `auth.current_actor`) and the route never reads a tenant from
                                     the body, the query or a header.

Refusals: every wrong, expired, used or other-tenant code or secret answers 404 with one body (the
use case raises one NotAllowed, DEC-160 item 3). Pairing limits answer 429. A cache that cannot be
reached answers 503 and writes nothing. Responses are `no-store`: a claim holds a token.

Limits in front of the use cases (R15, the per-address throttle DEC-160 item 4 asks for): a
start counts against its address. A claim counts only the claims that are refused, so a display
that polls and gets `waiting` is never throttled by its own polling. The address is the socket
peer, hashed into the key; behind a proxy it is the proxy's address until the server trusts the
proxy (DEC-224 item 18).

The routes hold no business rule: they check the secrets, bind the host's tenant where the use case
needs one, run one use case and map the result.
"""

import hashlib
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Final, Literal, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key
from diucs.adapters.inbound.fhir_rest.errors import NOT_FOUND_TEXT, operation_outcome
from diucs.application.actor import Actor
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import DEVICE_TOKEN_SECRET, secret_is_configured
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tenants import TenantDirectory, TenantRecordInvalid
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.pair_wall_screen import (
    LIMIT_WINDOW,
    RATE_LIMITED_MESSAGE,
    AttemptLimiter,
    ClaimPairing,
    ClaimPairingCommand,
    ConfirmPairing,
    ConfirmPairingCommand,
    PairingRateLimited,
    StartPairing,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed
from diucs.domain.model.device import BoardScope
from diucs.domain.model.tenant import TenantStatus

log = logging.getLogger(__name__)

START_PATH: Final = "/screens/pairing"
SCREENS_PATH: Final = "/screens"
SECRET_HEADER: Final = "x-screen-secret"

REFUSED_TEXT: Final = "That code is not valid or has expired."
"""The one answer to a refused code or secret (DEC-160 item 3). The same text for a wrong, expired,
used or other-tenant code, so an answer cannot tell them apart."""
RATE_LIMITED_TEXT: Final = RATE_LIMITED_MESSAGE
UNAVAILABLE_TEXT: Final = "Pairing is not available right now. Try again shortly."
RETRY_AFTER_UNAVAILABLE_SECONDS: Final = 30

ADDRESS_STARTS: Final = 20
"""Starts from one address in LIMIT_WINDOW. Equal to the tenant's own allowance (START_LIMIT), so
one address cannot use up a tenant's codes alone, and a tenant's starts from many addresses are
still bounded by the tenant's allowance."""
ADDRESS_REFUSED_CLAIMS: Final = 20
"""Refused claims from one address in LIMIT_WINDOW. A claim that is refused holds its slot for the
window. A claim that is answered (`waiting`, `paired`, `expired`) gives its slot back."""

_NO_STORE: Final = {"Cache-Control": "no-store"}
_RETRY_AFTER_WINDOW: Final = {"Retry-After": str(int(LIMIT_WINDOW.total_seconds()))}


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

    @property
    def cache(self) -> Cache: ...

    @property
    def rng(self) -> random.Random: ...


class ConnectScreenBody(BaseModel):
    """The lead's request. The tenant is not a field: an unknown field (a tenant, for one) is
    refused by `extra="forbid"` as a bad request."""

    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    location: str | None = None
    boardScope: Literal["tenant", "network"] = "tenant"


router = APIRouter()


def _container(request: Request) -> _Container:
    return cast(_Container, get_container(request))


def _check_secrets(container: _Container) -> None:
    """Fail closed: a missing pairing secret is a configuration error (a 500), never an open route
    and never a refusal that looks like a wrong code."""
    if not (
        secret_is_configured(container.secrets, LINK_TOKEN_SECRET)
        and secret_is_configured(container.secrets, DEVICE_TOKEN_SECRET)
    ):
        raise RuntimeError("the pairing secrets are not configured")


async def _tenant_of(request: Request, container: _Container) -> str | None:
    """The id of the active tenant whose host this request was addressed to, or None. A host no
    tenant owns, a tenant that is not active, and a damaged tenant record all answer None."""
    try:
        tenant = await container.tenants.by_host(request.url.hostname or "")
    except TenantRecordInvalid:
        log.warning("pairing refused: reason=tenant-record")
        return None
    if tenant is None or tenant.status is not TenantStatus.ACTIVE:
        return None
    return tenant.id


def _address_key(tenant: str, kind: str, request: Request) -> str:
    """The per-address limit's key. The address is hashed, so no address is held in the cache, and
    the tenant is part of the key, so one tenant's counts never touch another's."""
    peer = request.client.host if request.client is not None else ""
    address = hashlib.sha256(peer.encode("utf-8")).hexdigest()[:32]
    return f"pairing-address:{tenant}:{kind}:{address}"


async def _take(cache: Cache, name: str, limit: int) -> str:
    """One slot of a limit, or PairingRateLimited when the limit is used up in the window. A cache
    that cannot be reached raises, and the request is refused."""
    slot = await AttemptLimiter(cache).take(name, limit, LIMIT_WINDOW)
    if slot is None:
        raise PairingRateLimited(RATE_LIMITED_MESSAGE)
    return slot


def _json(status: int, body: dict[str, Any]) -> Response:
    return JSONResponse(body, status_code=status, headers=_NO_STORE)


def _not_found() -> Response:
    return operation_outcome(404, "not-found", NOT_FOUND_TEXT, headers=_NO_STORE)


async def _answer(run: Callable[[], Awaitable[Response]]) -> Response:
    """Run one request and map what it can answer. Nothing the caller sent and no value of a screen
    reaches a body; a cache failure is a fixed 503 that names the cache by no detail."""
    try:
        return await run()
    except PairingRateLimited:
        return operation_outcome(
            429, "throttled", RATE_LIMITED_TEXT, headers={**_NO_STORE, **_RETRY_AFTER_WINDOW}
        )
    except NotAllowed:
        return operation_outcome(404, "not-found", REFUSED_TEXT, headers=_NO_STORE)
    except OSError as error:
        log.error("pairing cache unavailable: %s", type(error).__name__)
        return operation_outcome(
            503,
            "transient",
            UNAVAILABLE_TEXT,
            headers={**_NO_STORE, "Retry-After": str(RETRY_AFTER_UNAVAILABLE_SECONDS)},
        )


@router.post(START_PATH, status_code=201)
async def start_pairing(request: Request) -> Response:
    async def run() -> Response:
        container = _container(request)
        _check_secrets(container)
        tenant = await _tenant_of(request, container)
        if tenant is None:
            return _not_found()
        with bind_tenant(tenant):
            await _take(container.cache, _address_key(tenant, "start", request), ADDRESS_STARTS)
            result = await StartPairing(
                container.uow_factory,
                container.clock,
                container.ids,
                container.rng,
                container.secrets,
                container.cache,
            ).execute()
        return _json(
            201,
            {
                "pairingId": result.pairing_id,
                "code": result.code_display.replace(" ", ""),
                "expiresAt": result.expires_at.isoformat(),
                "screenSecret": result.screen_secret,
            },
        )

    return await _answer(run)


@router.get(f"{START_PATH}/{{pairing_id}}")
async def claim_pairing(pairing_id: str, request: Request) -> Response:
    async def run() -> Response:
        container = _container(request)
        _check_secrets(container)
        tenant = await _tenant_of(request, container)
        if tenant is None:
            raise NotAllowed(REFUSED_TEXT)
        with bind_tenant(tenant):
            refusals = _address_key(tenant, "claim-refused", request)
            slot = await _take(container.cache, refusals, ADDRESS_REFUSED_CLAIMS)
            result = await ClaimPairing(
                container.uow_factory, container.clock, container.rng, container.secrets
            ).execute(
                ClaimPairingCommand(
                    pairing_id=pairing_id,
                    screen_secret=request.headers.get(SECRET_HEADER, ""),
                )
            )
            # The claim is answered, so its slot goes back. A failure here must not lose the token:
            # the claim has already been stored, so the slot is left to expire with its window.
            try:
                await AttemptLimiter(container.cache).release(slot)
            except OSError as error:
                log.error("pairing slot not released: %s", type(error).__name__)
        body: dict[str, Any] = {"status": result.status}
        if result.device_token is not None:
            body["deviceToken"] = result.device_token
        return _json(200, body)

    return await _answer(run)


@router.post(SCREENS_PATH, status_code=201)
async def connect_screen(
    body: ConnectScreenBody,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    key = idempotency_key(request)

    async def run() -> Response:
        container = _container(request)
        _check_secrets(container)
        result = await ConfirmPairing(
            container.uow_factory, container.clock, container.secrets, container.cache
        ).execute(
            ConfirmPairingCommand(
                idempotency_key=key,
                actor=actor,
                code=body.code,
                screen_name=body.name,
                location=body.location,
                board_scope=BoardScope(body.boardScope),
            )
        )
        return _json(
            201,
            {"deviceId": result.device_id, "name": result.screen_name, "status": "online"},
        )

    return await _answer(run)
