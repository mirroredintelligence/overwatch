"""Reporter identity and push endpoints over HTTP (R11, U25, U32, U37, I14), DEC-410 to DEC-415.

POST   /identity/code                   ask for a text code. Always 202 with one body, whether or
                                        not the number is known or a code was sent (a resend inside
                                        the cooldown included): nothing is said about numbers.
POST   /identity/code/verify            check a code. 200 {"verified": true}; a wrong code is a 400
                                        "That code is not right"; five wrong tries or a lapsed
                                        code is a 400 "Ask for a new code". A right code is recorded
                                        on the device in the same call (RecordTextCodeVerified).
POST   /identity/pin                    set the six-digit PIN of a device that was verified in the
                                        last 10 minutes.
POST   /identity/pin/verify             sign in with the PIN. 200 with the session; 403 for a wrong
                                        PIN (with the tries left) or when a text code is needed;
                                        423 `lock-error` when five wrong tries have locked it.
GET    /identity/status                 {"reverifyDue", "daysLeft"} for the 30-day text-code check.
POST   /identity/push-subscription      role reporter or exec: store a Web Push subscription with
                                        its consent. DELETE removes it.

Who is who. A route names a DEVICE, never a person: the person is read from the device's record, so
no person id is ever shown to a client that has not signed in. A device id is a random secret the
phone holds (at least 128 bits, `^[A-Za-z0-9_-]{22,56}$`), so it travels in the body or a header,
never in a URL (the server's access log would hold it). The tenant is the host the request was
addressed to, through the tenant directory, and nothing the caller sends (a body that names a tenant
is refused as an unknown field); the push routes take it from the verified token like every other
route (TEN-018).

Fail closed, one answer. An unknown device, a revoked one, one waiting for a lead's call-back, a
person who has left, a stale verification: each gets the answer of the others (DEC-323). A cache or
session store that cannot be reached answers 503 and does nothing. Every attempt is counted against
the caller's address before anything is read (the per-address throttle U32 and U25 leave to the
edge); behind a proxy the address is the proxy's until the server trusts the proxy (DEC-224
item 18). Responses are `no-store`. No mobile number, code, PIN, device id, session id or push
subscription is in a log line, an error or an audit entry: refusals log a reason word only.

The routes hold no business rule: they bind the tenant, count the attempt, run one use case and map
its result.
"""

import contextlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Final, Literal, Protocol, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from diucs.adapters.inbound.fhir_rest.errors import NOT_FOUND_TEXT, operation_outcome
from diucs.adapters.inbound.fhir_rest.routes_services import UnitOfWorkIdempotency
from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import (
    PHONE_HASH_SECRET,
    CodeResendRefused,
    CodeStore,
    HmacPhoneHasher,
    RateLimiter,
    SessionStore,
)
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.tenants import TenantDirectory, TenantRecordInvalid
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.pin import (
    PIN_HMAC_SECRET,
    RATE_WINDOW,
    PinRateLimited,
    PinSignIn,
    RecordTextCodeVerified,
    SetPin,
    limiter_key,
)
from diucs.application.use_cases.push_subscription import (
    RemovePushSubscription,
    RemovePushSubscriptionCommand,
    SavePushSubscription,
    SavePushSubscriptionCommand,
)
from diucs.application.use_cases.remove_person import StartNewPhone
from diucs.application.use_cases.reporter_identity import (
    CheckReporterAccess,
    ConfirmDeviceByTextCode,
    ConfirmDeviceCommand,
    ReporterSignIn,
    ReporterSignInCommand,
    ReverifyStatus,
    SetDevicePin,
    SetDevicePinCommand,
    SignInKind,
)
from diucs.application.use_cases.text_code import (
    CODE_HMAC_SECRET,
    RESEND_AFTER_SECONDS,
    RequestTextCode,
    RequestTextCodeCommand,
    VerifyTextCode,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.tenant import TenantStatus

log = logging.getLogger(__name__)

DEVICE_ID_PATTERN: Final = r"^[A-Za-z0-9_-]{22,56}$"
"""At least 128 bits when the id is 22 base64url characters: a device id is a secret the phone holds
(U32 known issue: a person's id and device id must never be guessable). At most 56, so the push
device id built from it (`app-` and the id) stays inside the 64 the push store allows."""
DEVICE_HEADER: Final = "x-device-id"
PUSH_DEVICE_PREFIX: Final = "app-"
"""A push subscription is a device record of its own kind (P19), and device ids are unique in a
tenant across kinds, so the app's push device is named from the signed-in device, not the same."""

ADDRESS_CODE_REQUESTS: Final = 10
ADDRESS_CODE_CHECKS: Final = 30
ADDRESS_PIN_ATTEMPTS: Final = 30
ADDRESS_STATUS_READS: Final = 60
"""[ASSUMED] attempts from one address in RATE_WINDOW (10 minutes), per kind. A code request is
already held to one per minute per number and purpose by the code store; these bound a flood of
distinct numbers, wrong codes and PINs from one address. The per-person and per-device limits of
U32 and the five-tries locks are separate and stricter."""

ACCEPTED_BODY: Final = {"accepted": True, "resendAfterSeconds": RESEND_AFTER_SECONDS}
WRONG_CODE_TEXT: Final = "That code is not right"
NEW_CODE_TEXT: Final = "Ask for a new code"
DEVICE_REFUSED_TEXT: Final = (
    "This phone cannot be set up with this code. Start again on this phone."
)
NEEDS_CODE_FIRST_TEXT: Final = "Get a code by text first."
WRONG_PIN_TEXT: Final = "That PIN is not right"
NEEDS_TEXT_CODE_TEXT: Final = "Get a code by text to sign in."
LOCKED_TEXT: Final = "Your PIN is locked. Get a code by text to set a new PIN."
RATE_LIMITED_TEXT: Final = "Too many attempts. Try again later."
UNAVAILABLE_TEXT: Final = "Sign-in is not available right now. Try again shortly."
RETRY_AFTER_UNAVAILABLE_SECONDS: Final = 30

_NO_STORE: Final = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_RETRY_AFTER_WINDOW: Final = {"Retry-After": str(int(RATE_WINDOW.total_seconds()))}
_Purpose = Literal["setup", "reverify", "pin-reset", "new-device"]


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...

    @property
    def ids(self) -> IdGenerator: ...

    @property
    def rng(self) -> Any: ...

    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...

    @property
    def tenants(self) -> TenantDirectory: ...

    @property
    def secrets(self) -> SecretStore: ...

    @property
    def codes(self) -> CodeStore: ...

    @property
    def sessions(self) -> SessionStore: ...

    @property
    def rate_limiter(self) -> RateLimiter: ...

    @property
    def sealer(self) -> ContentSealer: ...


class _Body(BaseModel):
    """Every body refuses a field it does not name: a tenant, a person id or a role in a body is a
    bad request, never read."""

    model_config = ConfigDict(extra="forbid")


class CodeBody(_Body):
    mobile: str = Field(min_length=1, max_length=32)
    purpose: _Purpose = "setup"


class VerifyBody(_Body):
    mobile: str = Field(min_length=1, max_length=32)
    code: str = Field(min_length=1, max_length=16)
    deviceId: str = Field(pattern=DEVICE_ID_PATTERN)
    purpose: _Purpose = "setup"


class PinBody(_Body):
    deviceId: str = Field(pattern=DEVICE_ID_PATTERN)
    pin: str = Field(min_length=1, max_length=16)


class PushKeys(_Body):
    p256dh: str = Field(min_length=1, max_length=256)
    auth: str = Field(min_length=1, max_length=256)


class PushSubscriptionBody(_Body):
    """What a browser's `PushSubscription.toJSON()` holds."""

    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushKeys
    expirationTime: float | None = None


class PushBody(_Body):
    subscription: PushSubscriptionBody
    wordingVersion: str = Field(min_length=1, max_length=32)
    deviceId: str = Field(pattern=DEVICE_ID_PATTERN)


router = APIRouter(prefix="/identity")


class _AddressLimited(Exception):
    """This address has used up its attempts for this kind of request in the window."""


def _container(request: Request) -> _Container:
    return cast(_Container, get_container(request))


def _check_secrets(container: _Container, *names: str) -> None:
    """Fail closed: a missing secret is a configuration error (a 500), never an open route and
    never a refusal that looks like a wrong code or PIN."""
    try:
        for name in names:
            container.secrets.get(name)
    except NotFound:
        raise RuntimeError("the identity secrets are not configured") from None


async def _tenant_of(request: Request, container: _Container) -> str | None:
    """The id of the active tenant whose host this request was addressed to, or None. A host no
    tenant owns, a tenant that is not active and a damaged record all answer None."""
    try:
        tenant = await container.tenants.by_host(request.url.hostname or "")
    except TenantRecordInvalid:
        log.warning("identity refused: reason=tenant-record")
        return None
    if tenant is None or tenant.status is not TenantStatus.ACTIVE:
        return None
    return tenant.id


async def _count(container: _Container, kind: str, request: Request, limit: int) -> None:
    """Count one attempt of this kind against the caller's address (inside the tenant's binding, so
    the key carries the tenant). The key holds a digest, never the address."""
    peer = request.client.host if request.client is not None else ""
    if not await container.rate_limiter.allow(
        limiter_key(f"identity-{kind}", peer), limit, RATE_WINDOW
    ):
        raise _AddressLimited


def _json(status: int, body: dict[str, Any]) -> Response:
    return JSONResponse(body, status_code=status, headers=_NO_STORE)


def _outcome(status: int, code: str, text: str, **extra: Any) -> Response:
    """An OperationOutcome that may carry one extra top-level field (tries left, needs a code)."""
    response = operation_outcome(status, code, text, headers=_NO_STORE)
    if extra:
        body = json.loads(bytes(response.body))
        body.update(extra)
        return JSONResponse(
            body, status_code=status, headers=_NO_STORE, media_type="application/fhir+json"
        )
    return response


def _not_found() -> Response:
    return operation_outcome(404, "not-found", NOT_FOUND_TEXT, headers=_NO_STORE)


def _device_header(request: Request) -> str:
    """The device id of a request with no body: a header, never the URL."""
    value = request.headers.get(DEVICE_HEADER, "")
    if re.fullmatch(DEVICE_ID_PATTERN, value) is None:
        raise ValidationFailed("X-Device-Id", "is required and must be a device id")
    return value


async def _answer(run: Callable[[], Awaitable[Response]]) -> Response:
    """Run one request and map what it can answer. Nothing the caller sent reaches a body; a cache
    or session store that cannot be reached is a fixed 503 that names no detail."""
    try:
        return await run()
    except _AddressLimited, PinRateLimited:
        return operation_outcome(
            429, "throttled", RATE_LIMITED_TEXT, headers={**_NO_STORE, **_RETRY_AFTER_WINDOW}
        )
    except OSError as error:
        log.error("identity store unavailable: %s", type(error).__name__)
        return operation_outcome(
            503,
            "transient",
            UNAVAILABLE_TEXT,
            headers={**_NO_STORE, "Retry-After": str(RETRY_AFTER_UNAVAILABLE_SECONDS)},
        )


async def _edge(
    request: Request,
    kind: str,
    limit: int,
    work: Callable[[_Container], Awaitable[Response]],
    *secrets: str,
) -> Response:
    """The shape of every unauthenticated identity route: the host's tenant, bound once; the
    attempt counted; one use case; one mapped answer."""

    async def run() -> Response:
        container = _container(request)
        _check_secrets(container, *secrets)
        tenant = await _tenant_of(request, container)
        if tenant is None:
            return _not_found()
        with bind_tenant(tenant):
            await _count(container, kind, request, limit)
            return await work(container)

    return await _answer(run)


@router.post("/code", status_code=202)
async def request_code(body: CodeBody, request: Request) -> Response:
    async def work(container: _Container) -> Response:
        with contextlib.suppress(CodeResendRefused):
            await RequestTextCode(
                container.codes,
                HmacPhoneHasher(container.secrets),
                container.uow_factory,
                container.secrets,
                container.sealer,
                container.ids,
                container.clock,
                container.rng,
            ).execute(
                RequestTextCodeCommand(
                    idempotency_key=container.ids.new_id(), phone=body.mobile, purpose=body.purpose
                )
            )
        # A CodeResendRefused is two requests racing inside the cooldown: the first one's code
        # stands, and the answer is the same one every other request gets.
        return _json(202, dict(ACCEPTED_BODY))

    return await _edge(
        request, "code", ADDRESS_CODE_REQUESTS, work, PHONE_HASH_SECRET, CODE_HMAC_SECRET
    )


@router.post("/code/verify")
async def verify_code(body: VerifyBody, request: Request) -> Response:
    async def work(container: _Container) -> Response:
        # The code check and the record on the device are one call (ConfirmDeviceByTextCode): the
        # edge never verifies a code without recording it (U32, DEC-321).
        result = await ConfirmDeviceByTextCode(
            VerifyTextCode(
                container.codes,
                HmacPhoneHasher(container.secrets),
                container.uow_factory,
                container.secrets,
                container.clock,
            ),
            RecordTextCodeVerified(container.uow_factory, container.clock),
            StartNewPhone(container.uow_factory, container.clock, container.sessions),
            container.clock,
        ).execute(
            ConfirmDeviceCommand(
                phone=body.mobile, code=body.code, purpose=body.purpose, device_id=body.deviceId
            )
        )
        if not result.verified:
            text = NEW_CODE_TEXT if result.needs_new_code else WRONG_CODE_TEXT
            return operation_outcome(400, "invalid", text, headers=_NO_STORE)
        if result.device_refused:
            return operation_outcome(409, "conflict", DEVICE_REFUSED_TEXT, headers=_NO_STORE)
        verified: dict[str, Any] = {"verified": True}
        if result.awaiting_callback:
            verified["callbackRequired"] = True
        return _json(200, verified)

    return await _edge(
        request,
        "verify",
        ADDRESS_CODE_CHECKS,
        work,
        PHONE_HASH_SECRET,
        CODE_HMAC_SECRET,
    )


@router.post("/pin")
async def set_pin(body: PinBody, request: Request) -> Response:
    async def work(container: _Container) -> Response:
        limiter = container.rate_limiter
        done = await SetDevicePin(
            container.uow_factory,
            SetPin(container.uow_factory, container.secrets, container.clock, limiter),
        ).execute(SetDevicePinCommand(device_id=body.deviceId, pin=body.pin))
        if not done:
            return operation_outcome(403, "forbidden", NEEDS_CODE_FIRST_TEXT, headers=_NO_STORE)
        return _json(200, {"pinSet": True})

    return await _edge(request, "pin", ADDRESS_PIN_ATTEMPTS, work, PIN_HMAC_SECRET)


@router.post("/pin/verify")
async def sign_in(body: PinBody, request: Request) -> Response:
    async def work(container: _Container) -> Response:
        pin_sign_in = PinSignIn(
            container.uow_factory, container.secrets, container.clock, container.rate_limiter
        )
        result = await ReporterSignIn(
            container.uow_factory, pin_sign_in, container.sessions, container.clock
        ).execute(ReporterSignInCommand(device_id=body.deviceId, pin=body.pin))
        if result.kind is SignInKind.SIGNED_IN:
            return _json(
                200,
                {
                    "signedIn": True,
                    "sessionId": result.session_id,
                    "role": Role.REPORTER.value,
                    "services": list(result.service_ids),
                },
            )
        if result.kind is SignInKind.LOCKED:
            return _outcome(423, "lock-error", LOCKED_TEXT)
        if result.kind is SignInKind.WRONG_PIN:
            return _outcome(403, "forbidden", WRONG_PIN_TEXT, triesLeft=result.tries_left)
        return _outcome(403, "forbidden", NEEDS_TEXT_CODE_TEXT, needsTextCode=True)

    return await _edge(request, "pin", ADDRESS_PIN_ATTEMPTS, work, PIN_HMAC_SECRET)


@router.get("/status")
async def status(request: Request) -> Response:
    async def work(container: _Container) -> Response:
        result = await ReverifyStatus(container.uow_factory, container.clock).execute(
            _device_header(request)
        )
        return _json(200, {"reverifyDue": result.reverify_due, "daysLeft": result.days_left})

    return await _edge(request, "status", ADDRESS_STATUS_READS, work)


def _unauthorised() -> HTTPException:
    return HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})


async def _signed_in(container: _Container, actor: Actor) -> None:
    """A token is a signed claim that cannot be recalled, so the person and the device it names are
    checked on every use: signing out and removal take effect at once, not at token expiry. A
    refusal is the 401 of any bad token."""
    if not await CheckReporterAccess(container.uow_factory).execute(actor):
        raise _unauthorised()


def _push_device(actor: Actor, device_id: str) -> str:
    """The device of the installed app. A reporter's is the device the token was made for."""
    if actor.role is Role.REPORTER and device_id != actor.device_id:
        raise ValidationFailed("deviceId", "is not the device you are signed in on")
    return f"{PUSH_DEVICE_PREFIX}{device_id}"


@router.post("/push-subscription")
async def save_push_subscription(
    body: PushBody,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.REPORTER, Role.EXEC))],
) -> Response:
    key = idempotency_key(request)
    container = _container(request)
    await _signed_in(container, actor)
    device = _push_device(actor, body.deviceId)

    async def run() -> Response:
        saved = await SavePushSubscription(
            container.uow_factory,
            container.clock,
            container.ids,
            UnitOfWorkIdempotency(container.uow_factory),
        ).execute(
            SavePushSubscriptionCommand(
                idempotency_key=key,
                actor=actor,
                device_id=device,
                subscription=body.subscription.model_dump(exclude_none=True),
                wording_version=body.wordingVersion,
            )
        )
        return _json(200, {"saved": True, "consentAt": saved.consent_at.isoformat()})

    return await _answer(lambda: replay_or_run(request, actor, key, run))


@router.delete("/push-subscription")
async def remove_push_subscription(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.REPORTER, Role.EXEC))],
) -> Response:
    key = idempotency_key(request)
    container = _container(request)
    await _signed_in(container, actor)
    header = request.headers.get(DEVICE_HEADER)
    device = _push_device(actor, header if header is not None else actor.device_id or "")

    async def run() -> Response:
        await RemovePushSubscription(
            container.uow_factory,
            container.clock,
            container.ids,
            UnitOfWorkIdempotency(container.uow_factory),
        ).execute(RemovePushSubscriptionCommand(idempotency_key=key, actor=actor, device_id=device))
        return _json(200, {"removed": True})

    return await _answer(lambda: replay_or_run(request, actor, key, run))
