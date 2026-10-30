"""Reporter set-up behind a link or a device, before anyone is signed in (W7C, DEC-810 to DEC-813).

GET   /invitations/{token}                      one invitation: the service, the post, the masked
                                                number, the expiry. One 410 `{"state": "expired"}`
                                                for anything that cannot be used (an unknown,
                                                malformed, expired, used, another tenant's or
                                                another purpose's token, and a host no tenant owns).
POST  /identity/invitations/{token}/code        ask for the set-up text code of an invitation.
                                                Always 202 with the body of /identity/code.
POST  /identity/invitations/{token}/code/verify check it and record the device (as /identity/code/
                                                verify, for the number the invitation was sent to).
POST  /identity/device/code                     ask for the code of the 30-day check (`reverify`)
                                                or a PIN reset (`pin-reset`) for a device. Always
                                                202.
POST  /identity/device/code/verify              check it; a right code stamps the device.
POST  /identity/channel                         record how the reporter wants to be contacted, for
                                                a device that a text code verified in the last ten
                                                minutes (set-up, and the locked PIN's "text me").
GET   /public/push-key                          the platform's VAPID public key (not a secret).

The browser at set-up holds an invitation token and its own device id, never a number, so these
routes find the number server-side: through the invitation, or through the device's owner. They run
the same use cases as the number-based routes (U25, U32), with the keyed hash of that number. An
invitation or a device that is not usable gets a stand-in hash no practitioner holds, so the work
done and the answer are the same as for a real one (H-450, H-451); a wrong code names the tries
left, as for a number. Tenant, rate limit, no-store and the no-logging rules are those of
`routes_identity` (the host is the tenant, DEC-134 item 3). A token is hidden in the access log by
`RedactLinkTokens`.
"""

import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from diucs.adapters.inbound.fhir_rest.errors import operation_outcome
from diucs.adapters.inbound.fhir_rest.host_tenant import bind_host_tenant
from diucs.adapters.inbound.fhir_rest.routes_identity import (
    ACCEPTED_BODY,
    ADDRESS_CODE_CHECKS,
    ADDRESS_CODE_REQUESTS,
    ADDRESS_PIN_ATTEMPTS,
    DEVICE_ID_PATTERN,
    DEVICE_REFUSED_TEXT,
    NEEDS_CODE_FIRST_TEXT,
    NEW_CODE_TEXT,
    WRONG_CODE_TEXT,
    _answer,
    _Body,
    _check_secrets,
    _Container,
    _container,
    _count,
    _json,
    _not_found,
    _outcome,
    _tenant_of,
)
from diucs.adapters.inbound.fhir_rest.routes_public import _HEADERS, public_rate_limit
from diucs.application.ports.outbound.identity import (
    PHONE_HASH_SECRET,
    CodeResendRefused,
)
from diucs.application.ports.outbound.tokens import (
    LINK_TOKEN_SECRET,
    LinkTokenRepository,
    LinkTokenService,
)
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.pin import PIN_HMAC_SECRET, RecordTextCodeVerified
from diucs.application.use_cases.remove_person import StartNewPhone
from diucs.application.use_cases.reporter_identity import (
    ConfirmDeviceByTextCode,
    ConfirmDeviceCommand,
    ConfirmDeviceResult,
)
from diucs.application.use_cases.reporter_setup import (
    DeviceReader,
    InvitationReader,
    InvitationUnusable,
    KnownPhoneHash,
    SetDeviceChannel,
    SetDeviceChannelCommand,
)
from diucs.application.use_cases.text_code import (
    CODE_HMAC_SECRET,
    RequestTextCode,
    RequestTextCodeCommand,
    VerifyTextCode,
)
from diucs.domain.errors import NotFound
from diucs.domain.model.tenant import Tenant
from diucs.domain.rules.reporter_app import channel_for, channel_word

log = logging.getLogger(__name__)

VAPID_PUBLIC_KEY_SECRET: Final = "webpush-vapid-public-key"
"""The platform's VAPID public key, as the browser's `applicationServerKey` (base64url). The
private half is `webpush-vapid-private-key` (I14, DEC-340); one pair serves every tenant."""
ADDRESS_INVITATION_READS: Final = 60
"""[ASSUMED] Invitation reads from one address in 10 minutes: a page reload or two of a real
person, far below a guess at tokens (23 letters, 131 bits)."""
GONE_BODY: Final = {"state": "expired"}

router = APIRouter()


class EmptyBody(_Body):
    """The code of an invitation takes nothing from the body: not a number, not a tenant."""


class InvitationVerifyBody(_Body):
    code: str = Field(min_length=1, max_length=16)
    deviceId: str = Field(pattern=DEVICE_ID_PATTERN)


class DeviceCodeBody(_Body):
    deviceId: str = Field(pattern=DEVICE_ID_PATTERN)
    purpose: Literal["reverify", "pin-reset"]


class DeviceVerifyBody(DeviceCodeBody):
    code: str = Field(min_length=1, max_length=16)


class ChannelBody(_Body):
    deviceId: str = Field(pattern=DEVICE_ID_PATTERN)
    channel: str = Field(max_length=16)


def _gone() -> Response:
    return JSONResponse(GONE_BODY, status_code=410, headers=_NO_STORE_HEADERS)


_NO_STORE_HEADERS: Final = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _tokens(container: _Container) -> Callable[[LinkTokenRepository], LinkTokenService]:
    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, container.secrets, container.clock)

    return tokens


async def _host_edge(
    request: Request,
    kind: str,
    limit: int,
    work: Callable[[_Container], Awaitable[Response]],
    unknown_host: Callable[[], Response],
    *secrets: str,
) -> Response:
    """As `routes_identity._edge`, with the answer for a host no tenant owns chosen by the route:
    the invitation read answers its one 410, not a 404."""

    async def run() -> Response:
        container = _container(request)
        _check_secrets(container, *secrets)
        tenant = await _tenant_of(request, container)
        if tenant is None:
            return unknown_host()
        with bind_tenant(tenant):
            await _count(container, kind, request, limit)
            return await work(container)

    return await _answer(run)


def _confirm(container: _Container, phone_hash: str) -> ConfirmDeviceByTextCode:
    hasher = KnownPhoneHash(phone_hash)
    return ConfirmDeviceByTextCode(
        VerifyTextCode(
            container.codes, hasher, container.uow_factory, container.secrets, container.clock
        ),
        RecordTextCodeVerified(container.uow_factory, container.clock),
        StartNewPhone(container.uow_factory, container.clock, container.sessions),
        container.clock,
    )


async def _request_code(container: _Container, phone_hash: str, purpose: str) -> Response:
    with contextlib.suppress(CodeResendRefused):
        await RequestTextCode(
            container.codes,
            KnownPhoneHash(phone_hash),
            container.uow_factory,
            container.secrets,
            container.sealer,
            container.ids,
            container.clock,
            container.rng,
        ).execute(
            RequestTextCodeCommand(
                idempotency_key=container.ids.new_id(), phone="", purpose=purpose
            )
        )
    return _json(202, dict(ACCEPTED_BODY))


def _checked(result: ConfirmDeviceResult) -> Response:
    """The answer of a code check: a wrong code names the tries left, five or a lapsed code ask for
    a new one, and a right code that its device cannot take is a conflict."""
    if not result.verified:
        text = NEW_CODE_TEXT if result.needs_new_code else WRONG_CODE_TEXT
        return _outcome(400, "invalid", text, triesLeft=result.tries_left)
    if result.device_refused:
        return operation_outcome(409, "conflict", DEVICE_REFUSED_TEXT, headers=_NO_STORE_HEADERS)
    return _json(200, {"verified": True})


# ------------------------------------------------------------------------------- invitation


@router.get("/invitations/{token}")
async def read_invitation(token: str, request: Request) -> Response:
    async def work(container: _Container) -> Response:
        try:
            view = await InvitationReader(
                container.uow_factory, container.clock, _tokens(container)
            ).view(token)
        except InvitationUnusable:
            return _gone()
        return _json(
            200,
            {
                "state": "valid",
                "service": view.service,
                "role": view.role,
                "maskedPhone": view.masked_phone,
                "expiresAt": view.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )

    return await _host_edge(
        request, "invitation", ADDRESS_INVITATION_READS, work, _gone, LINK_TOKEN_SECRET
    )


@router.post("/identity/invitations/{token}/code", status_code=202)
async def request_invitation_code(token: str, body: EmptyBody, request: Request) -> Response:
    async def work(container: _Container) -> Response:
        reader = InvitationReader(container.uow_factory, container.clock, _tokens(container))
        return await _request_code(container, await reader.phone_hash(token), "setup")

    return await _host_edge(
        request,
        "invitation-code",
        ADDRESS_CODE_REQUESTS,
        work,
        _not_found,
        LINK_TOKEN_SECRET,
        PHONE_HASH_SECRET,
        CODE_HMAC_SECRET,
    )


@router.post("/identity/invitations/{token}/code/verify")
async def verify_invitation_code(
    token: str, body: InvitationVerifyBody, request: Request
) -> Response:
    async def work(container: _Container) -> Response:
        reader = InvitationReader(container.uow_factory, container.clock, _tokens(container))
        result = await _confirm(container, await reader.phone_hash(token)).execute(
            ConfirmDeviceCommand(phone="", code=body.code, purpose="setup", device_id=body.deviceId)
        )
        return _checked(result)

    return await _host_edge(
        request,
        "invitation-verify",
        ADDRESS_CODE_CHECKS,
        work,
        _not_found,
        LINK_TOKEN_SECRET,
        PHONE_HASH_SECRET,
        CODE_HMAC_SECRET,
    )


# ------------------------------------------------------------------------------- device


@router.post("/identity/device/code", status_code=202)
async def request_device_code(body: DeviceCodeBody, request: Request) -> Response:
    async def work(container: _Container) -> Response:
        phone_hash = await DeviceReader(container.uow_factory).phone_hash(body.deviceId)
        return await _request_code(container, phone_hash, body.purpose)

    return await _host_edge(
        request,
        "device-code",
        ADDRESS_CODE_REQUESTS,
        work,
        _not_found,
        PHONE_HASH_SECRET,
        CODE_HMAC_SECRET,
    )


@router.post("/identity/device/code/verify")
async def verify_device_code(body: DeviceVerifyBody, request: Request) -> Response:
    async def work(container: _Container) -> Response:
        phone_hash = await DeviceReader(container.uow_factory).phone_hash(body.deviceId)
        result = await _confirm(container, phone_hash).execute(
            ConfirmDeviceCommand(
                phone="", code=body.code, purpose=body.purpose, device_id=body.deviceId
            )
        )
        return _checked(result)

    return await _host_edge(
        request,
        "device-verify",
        ADDRESS_CODE_CHECKS,
        work,
        _not_found,
        PHONE_HASH_SECRET,
        CODE_HMAC_SECRET,
    )


@router.post("/identity/channel")
async def set_device_channel(body: ChannelBody, request: Request) -> Response:
    channel = channel_for(body.channel)

    async def work(container: _Container) -> Response:
        done = await SetDeviceChannel(container.uow_factory, container.clock).execute(
            SetDeviceChannelCommand(device_id=body.deviceId, channel=channel)
        )
        if not done:
            return operation_outcome(
                403, "forbidden", NEEDS_CODE_FIRST_TEXT, headers=_NO_STORE_HEADERS
            )
        return _json(200, {"channel": channel_word(channel)})

    return await _host_edge(
        request, "channel", ADDRESS_PIN_ATTEMPTS, work, _not_found, PIN_HMAC_SECRET
    )


# ------------------------------------------------------------------------------- push key


@router.get("/public/push-key", dependencies=[Depends(public_rate_limit)])
async def push_key(
    request: Request, tenant: Annotated[Tenant, Depends(bind_host_tenant)]
) -> Response:
    container = _container(request)
    try:
        key = container.secrets.get(VAPID_PUBLIC_KEY_SECRET)
    except NotFound:
        log.error("push key not configured")
        return JSONResponse({"code": "not-configured"}, status_code=503, headers=_HEADERS)
    return JSONResponse({"publicKey": key.decode("utf-8")}, headers=_HEADERS)
