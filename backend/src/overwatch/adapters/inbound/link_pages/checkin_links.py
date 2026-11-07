"""The check-in page's API for a service's printed QR code (DEC-1346, builds DEC-1341 item 3).

GET  /checkin/{token}          which service the code is for, and the CSRF token for the writes
POST /checkin/{token}/code     a six-digit code is texted to a number on the service's roster
POST /checkin/{token}/confirm  the code typed, and the person goes on or off shift

The page is open to anyone who scans the code, so the order of work is the security of the page, as
for the capacity link pages (capacity_links.py):

1. The tenant comes from the host the request was addressed to, through the tenant directory, and
   from nowhere else. A host the directory does not know, or a tenant that is not active, answers as
   an unknown code. The tenant is bound once, here, for the whole request.
2. A write must send back the CSRF token the page was given; it is checked before anything is read.
3. Whatever number is typed, the answer to "text me a code" is the same: the page never says who is
   on a roster. The limits count every number alike.
4. Every failure has one fixed body and no detail. A token, a number or a code is never in a
   response, a header, a log line or an error. Responses are `no-store` with
   `Referrer-Policy: no-referrer`, because the token is in the URL; the access log redacts it.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from overwatch.adapters.inbound.link_pages.capacity_links import (
    _client,
    _collaborators,
    _read_json,
    _tenant_of,
    failure_name,
)
from overwatch.application.ports.outbound.identity import HmacPhoneHasher
from overwatch.application.tenancy import bind_tenant
from overwatch.application.use_cases.duty_roster import CheckIn, SignOff
from overwatch.application.use_cases.link_access import CsrfRejected
from overwatch.application.use_cases.service_checkin import (
    CheckInCodeWrong,
    CheckInGone,
    CheckInRateLimited,
    ConfirmServiceCheckIn,
    SendCheckInCode,
    ViewServiceCheckIn,
)
from overwatch.domain.errors import NotAllowed, ValidationFailed
from overwatch.domain.rules.london_time import format_hhmm, zone_named

log = logging.getLogger(__name__)

CHECKIN_PATH_PREFIX: Final = "/checkin"
_NO_STORE: Final = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_CODE_FIELDS: Final = frozenset({"mobile"})
_CONFIRM_FIELDS: Final = frozenset({"mobile", "code", "action", "hours"})
_MAX_FIELD: Final = 64


def _json(status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> Response:
    return JSONResponse(body, status_code=status, headers={**_NO_STORE, **(headers or {})})


def _gone() -> Response:
    return _json(410, {"state": "gone"})


def _text_field(body: dict[str, Any], name: str) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value or len(value) > _MAX_FIELD:
        raise ValidationFailed(name, "is required")
    return value


def _hours_field(body: dict[str, Any]) -> int | None:
    value = body.get("hours")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationFailed("hours", "must be a whole number")
    return value


async def _guarded(run: Callable[[], Awaitable[Response]]) -> Response:
    """Run one request and map every answer the page can get to a fixed body."""
    try:
        return await run()
    except CheckInGone:
        return _gone()
    except CsrfRejected:
        return _json(403, {"state": "forbidden"})
    except CheckInCodeWrong:
        return _json(403, {"state": "code-wrong"})
    except ValidationFailed, NotAllowed:
        return _json(400, {"state": "invalid"})
    except CheckInRateLimited as error:
        return _json(
            429, {"state": "rate-limited"}, {"Retry-After": str(error.retry_after_seconds)}
        )
    except Exception as error:
        log.error("check-in request failed: %s", failure_name(error))
        return _json(500, {"state": "error"})


router = APIRouter(prefix=CHECKIN_PATH_PREFIX)


@router.get("/{token}")
async def view_checkin(token: str, request: Request) -> Response:
    async def run() -> Response:
        container, deps = _collaborators(request)
        tenant = await _tenant_of(request, container)
        if tenant is None:
            return _gone()
        with bind_tenant(tenant.id):
            page = await ViewServiceCheckIn(
                container.uow_factory,
                container.clock,
                container.secrets,
                deps.cache,
                HmacPhoneHasher(container.secrets),
            ).execute(token, _client(request))
        return _json(200, {"service": page.service_name, "csrfToken": page.csrf_token})

    return await _guarded(run)


@router.post("/{token}/code")
async def send_code(token: str, request: Request) -> Response:
    async def run() -> Response:
        container, deps = _collaborators(request)
        tenant = await _tenant_of(request, container)
        if tenant is None:
            raise CsrfRejected  # no code can be found on this host, so no token can be right
        body = await _read_json(request)
        if body is None or not set(body) <= _CODE_FIELDS:
            raise ValidationFailed("body", "must be a JSON object with a mobile number")
        mobile = _text_field(body, "mobile")
        with bind_tenant(tenant.id):
            await SendCheckInCode(
                container.uow_factory,
                container.clock,
                container.secrets,
                deps.cache,
                HmacPhoneHasher(container.secrets),
                container.ids,
                deps.sealer,
            ).execute(token, mobile, _client(request), request.headers.get("x-csrf-token"))
        return _json(202, {"state": "sent"})

    return await _guarded(run)


@router.post("/{token}/confirm")
async def confirm_checkin(token: str, request: Request) -> Response:
    async def run() -> Response:
        container, deps = _collaborators(request)
        tenant = await _tenant_of(request, container)
        if tenant is None:
            raise CsrfRejected
        body = await _read_json(request)
        if body is None or not set(body) <= _CONFIRM_FIELDS:
            raise ValidationFailed("body", "has a field this page does not take")
        mobile = _text_field(body, "mobile")
        code = _text_field(body, "code")
        action = _text_field(body, "action")
        hours = _hours_field(body)
        with bind_tenant(tenant.id):
            outcome = await ConfirmServiceCheckIn(
                container.uow_factory,
                container.clock,
                container.secrets,
                deps.cache,
                HmacPhoneHasher(container.secrets),
                CheckIn(container.uow_factory, container.clock, container.ids),
                SignOff(container.uow_factory, container.clock),
            ).execute(
                token,
                mobile,
                code,
                action,
                hours,
                _client(request),
                request.headers.get("x-csrf-token"),
            )
        if outcome.state == "on-shift":
            change = outcome.changes[0]
            until = change.shift_end
            return _json(
                200,
                {
                    "state": "on-shift",
                    "service": change.service_name,
                    "until": None
                    if until is None
                    else format_hhmm(until, zone=zone_named(tenant.time_zone)),
                },
            )
        return _json(200, {"state": "off-shift"})

    return await _guarded(run)
