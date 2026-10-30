"""Signing in to the registration flow and the reporter token (W7B A2, DEC-790 to DEC-793).

POST /identity/invitation           {"invitation"}: what an invitation link says. 200
                                    {"state": "open", "serviceName", "numberEnding" (the last
                                    three digits), "expiresAt"}, or {"state": "expired"} or
                                    {"state": "used"}. An unknown or malformed link is the one 404.
POST /identity/registration/code    {"invitation"}: a code to the number the invitation holds. 202
                                    with the code route's body (nothing says whether a code was
                                    sent). A link that is not open is the one 404.
POST /identity/registration/session {"invitation" | "mobile", "code", "deviceId"}: the code is
                                    checked and recorded on the device, as /identity/code/verify
                                    does, and a right one answers 200 {"token", "expiresAt",
                                    "role": "reporter", "tenant"} (the host's tenant id; with
                                    "registrationId", "serviceId" and
                                    "serviceName" for an invitation). A wrong or lapsed code is
                                    that route's own 400, a device that is refused is 409.
POST /identity/session-token        {"sessionId"}: a live PIN session, exchanged for a 30-minute
                                    reporter token. A session that is unknown, ended or signed out
                                    is the one 404.

None of these has a signed token: the tenant is the HOST's (the one binder, TEN-040) and nothing the
caller sends (a body that names a tenant, a role, a person or a service is a 400 and is never
read). The back end issues the token and the BFF holds no signing secret (TEN-043, DEC-134 item 2).
Every answer is no-store. A host no tenant owns, and a tenant that is not active, answer 404 before
the credential is looked at, and the attempts are counted against the caller's address first.
"""

import contextlib
from datetime import datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from diucs.adapters.inbound.fhir_rest.errors import operation_outcome
from diucs.adapters.inbound.fhir_rest.host_tenant import bind_host_tenant
from diucs.adapters.inbound.fhir_rest.routes_identity import (
    ACCEPTED_BODY,
    ADDRESS_CODE_CHECKS,
    ADDRESS_CODE_REQUESTS,
    DEVICE_ID_PATTERN,
    DEVICE_REFUSED_TEXT,
    NEW_CODE_TEXT,
    WRONG_CODE_TEXT,
    _answer,
    _check_secrets,
    _Container,
    _container,
    _count,
    _json,
    _not_found,
)
from diucs.application.ports.outbound.identity import (
    PHONE_HASH_SECRET,
    CodeResendRefused,
    HmacPhoneHasher,
)
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.tenant_resolution import EntryRefused, PreSessionResolver
from diucs.application.use_cases.pin import RecordTextCodeVerified
from diucs.application.use_cases.registration_session import (
    ExchangeReporterSession,
    ReadInvitation,
    RegistrationSignIn,
    RegistrationSignInCommand,
    RequestRegistrationCode,
    SignInKind,
)
from diucs.application.use_cases.remove_person import StartNewPhone
from diucs.application.use_cases.reporter_identity import ConfirmDeviceByTextCode
from diucs.application.use_cases.text_code import (
    CODE_HMAC_SECRET,
    RequestTextCode,
    VerifyTextCode,
)
from diucs.domain.model.tenant import Tenant
from diucs.domain.rules.tokens import LinkCheck

router = APIRouter(prefix="/identity")

TOKEN_FIELD: Final = Field(min_length=1, max_length=256)
"""A link token is at most 64 characters; a longer one is not refused by shape here, so a token that
cannot be one reads as an unknown one (the one 404)."""
_NO_STORE: Final = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


class _Body(BaseModel):
    """A body that names anything it does not take is a bad request and is never read."""

    model_config = ConfigDict(extra="forbid")


class InvitationBody(_Body):
    invitation: str = TOKEN_FIELD


class SessionBody(_Body):
    invitation: str | None = Field(default=None, min_length=1, max_length=256)
    mobile: str | None = Field(default=None, min_length=1, max_length=32)
    code: str = Field(min_length=1, max_length=16)
    deviceId: str = Field(pattern=DEVICE_ID_PATTERN)


class SessionTokenBody(_Body):
    sessionId: str = Field(min_length=1, max_length=128)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


async def _in_host_tenant(
    request: Request, tenant: Tenant, kind: str, limit: int, work: Any, *secrets: str
) -> Response:
    """The shape of every route here, after the edge has bound the host's active tenant (the one
    binder, `bind_host_tenant`): the attempt is counted, one use case runs, one answer is mapped.
    `work` is given the container and the tenant."""

    async def run() -> Response:
        container = _container(request)
        _check_secrets(container, *secrets)
        await _count(container, kind, request, limit)
        try:
            return await work(container, tenant)  # type: ignore[no-any-return]
        except EntryRefused:
            return _not_found()

    return await _answer(run)


def _read_invitation(container: _Container) -> ReadInvitation:
    return ReadInvitation(
        container.uow_factory,
        PreSessionResolver(container.uow_factory, container.clock, container.secrets),
    )


def _confirm(container: _Container) -> ConfirmDeviceByTextCode:
    return ConfirmDeviceByTextCode(
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
    )


@router.post("/invitation")
async def read_invitation(
    body: InvitationBody, request: Request, tenant: Annotated[Tenant, Depends(bind_host_tenant)]
) -> Response:
    async def work(container: _Container, resolved: Tenant) -> Response:
        facts = await _read_invitation(container).execute(body.invitation)
        if facts.state is not LinkCheck.OK:
            return _json(200, {"state": facts.state.value})
        return _json(
            200,
            {
                "state": "open",
                "serviceName": facts.service_name,
                "numberEnding": facts.number_ending,
                "expiresAt": _iso(facts.invitation.expires_at),
            },
        )

    return await _in_host_tenant(
        request, tenant, "invitation", ADDRESS_CODE_CHECKS, work, LINK_TOKEN_SECRET
    )


@router.post("/registration/code", status_code=202)
async def request_registration_code(
    body: InvitationBody, request: Request, tenant: Annotated[Tenant, Depends(bind_host_tenant)]
) -> Response:
    async def work(container: _Container, resolved: Tenant) -> Response:
        request_code = RequestTextCode(
            container.codes,
            HmacPhoneHasher(container.secrets),
            container.uow_factory,
            container.secrets,
            container.sealer,
            container.ids,
            container.clock,
            container.rng,
        )
        with contextlib.suppress(CodeResendRefused):
            await RequestRegistrationCode(_read_invitation(container), request_code).execute(
                body.invitation, container.ids.new_id()
            )
        return _json(202, dict(ACCEPTED_BODY))

    return await _in_host_tenant(
        request,
        tenant,
        "registration-code",
        ADDRESS_CODE_REQUESTS,
        work,
        LINK_TOKEN_SECRET,
        PHONE_HASH_SECRET,
        CODE_HMAC_SECRET,
    )


@router.post("/registration/session")
async def sign_in_to_registration(
    body: SessionBody, request: Request, tenant: Annotated[Tenant, Depends(bind_host_tenant)]
) -> Response:
    async def work(container: _Container, resolved: Tenant) -> Response:
        result = await RegistrationSignIn(
            container.uow_factory,
            _read_invitation(container),
            _confirm(container),
            HmacPhoneHasher(container.secrets),
            container.secrets,
            container.clock,
        ).execute(
            RegistrationSignInCommand(
                tenant=resolved,
                code=body.code,
                device_id=body.deviceId,
                invitation=body.invitation,
                mobile=body.mobile,
            )
        )
        if result.kind is SignInKind.DEVICE_REFUSED:
            return operation_outcome(409, "conflict", DEVICE_REFUSED_TEXT, headers=_NO_STORE)
        if result.token is None:
            text = NEW_CODE_TEXT if result.kind is SignInKind.NEEDS_NEW_CODE else WRONG_CODE_TEXT
            return operation_outcome(400, "invalid", text, headers=_NO_STORE)
        answer: dict[str, Any] = {
            "token": result.token.token,
            "expiresAt": _iso(result.token.expires_at),
            "role": result.token.role.value,
            # The host's tenant. The BFF keeps it in its sealed session; a browser never gets it.
            "tenant": resolved.id,
        }
        if result.registration_id is not None:
            answer["registrationId"] = result.registration_id
            answer["serviceId"] = result.service_id
            answer["serviceName"] = result.service_name
        return _json(200, answer)

    return await _in_host_tenant(
        request,
        tenant,
        "registration-session",
        ADDRESS_CODE_CHECKS,
        work,
        LINK_TOKEN_SECRET,
        PHONE_HASH_SECRET,
        CODE_HMAC_SECRET,
    )


@router.post("/session-token")
async def exchange_session(
    body: SessionTokenBody, request: Request, tenant: Annotated[Tenant, Depends(bind_host_tenant)]
) -> Response:
    async def work(container: _Container, resolved: Tenant) -> Response:
        issued = await ExchangeReporterSession(
            container.sessions, container.secrets, container.clock
        ).execute(resolved, body.sessionId)
        return _json(
            200,
            {
                "token": issued.token,
                "expiresAt": _iso(issued.expires_at),
                "role": issued.role.value,
            },
        )

    return await _in_host_tenant(request, tenant, "session-token", ADDRESS_CODE_CHECKS, work)


__all__ = ["router"]
