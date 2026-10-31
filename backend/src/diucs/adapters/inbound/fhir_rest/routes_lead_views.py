"""The shift lead's reads and actions over HTTP (W7B C, DEC-802 to DEC-809). Thin: each route runs
one use case and maps the result to camelCase JSON. Only the shift lead reaches them (require_role:
any other role is the non-revealing 404).

GET  /lead/overview                    chasing (with the ladder), gettingOld, covering, counts,
                                       reportingToday
POST /lead/services/{id}/remind        Idempotency-Key; 200 {reminded: true}; 409 when no reminder
                                       is waiting
POST /lead/services/{id}/test-prompt   Idempotency-Key; optional {"channel"}; 200
                                       {channel, numberEnding}; 409 inside a minute
GET  /lead/services/{id}/suspension    suspended, since, reason, expiredRequests, registerNumber
GET  /lead/reporters[?service=]        the reporter posts with roleId (for change-number, remove)
GET  /lead/phones                      the phones and the services each holds now
GET  /lead/invitations                 each invitation with the steps of the set-up
POST /lead/services/{id}/phoned        Idempotency-Key; {"told", "value"}; what the service said by
                                       phone, with no case (RecordAdvisorPhoned, U13, DEC-920); 201
                                       {reportId, value}
POST /lead/invitations/{id}/resend     Idempotency-Key; the invitation text again (U24)
POST /lead/invitations/{id}/switch-to-text   Idempotency-Key; 200 {channel: "text"}

A mobile number is never in a body: the last three or four digits stand for it. Every answer is
no-store. Tenancy: bound at the edge from the verified token (TEN-018); nothing is read from the
body or the query for it.
"""

import json
from typing import Annotated, Any, Final, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from diucs.adapters.inbound.fhir_rest.routes_registration import NO_STORE
from diucs.application.actor import Actor
from diucs.application.idempotency import format_instant
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.tokens import LinkTokenService, SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId
from diucs.application.tenant_settings import DirectoryZones, resolve_link_base
from diucs.application.uow_idempotency import UnitOfWorkIdempotency
from diucs.application.use_cases.advisor_phoned import (
    PHONED_ANSWERS,
    PhonedAnswer,
    RecordAdvisorPhoned,
    RecordAdvisorPhonedCommand,
)
from diucs.application.use_cases.invite_reporter import (
    LinkBaseUrlFor,
    ResendInvitation,
    ResendInvitationCommand,
)
from diucs.application.use_cases.lead_actions import (
    RemindService,
    SendLeadTestPrompt,
    SwitchReporterToText,
)
from diucs.application.use_cases.lead_views import (
    GetLeadOverview,
    GetSuspension,
    ListInvitations,
    ListPhones,
    ListReporters,
)
from diucs.application.use_cases.missed_report_ladder import MissedReportLadder
from diucs.application.use_cases.report_capacity import ReportCapacity
from diucs.domain.codes import Channel, Role, Status
from diucs.domain.errors import ValidationFailed

router = APIRouter(prefix="/lead")

LEAD: Final = (Role.LEAD,)
_COUNT_KEYS: Final = {
    Status.ACCEPTING: "accepting",
    Status.LIMITED: "limited",
    Status.NOT_ACCEPTING: "notAccepting",
    Status.OVER_CAPACITY: "overCapacity",
    Status.NOT_UPDATED: "notUpdated",
}


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...
    @property
    def tenants(self) -> TenantDirectory: ...
    @property
    def ids(self) -> IdGenerator: ...
    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...
    @property
    def secrets(self) -> SecretStore: ...
    @property
    def sealer(self) -> ContentSealer: ...
    @property
    def link_base_url_for(self) -> LinkBaseUrlFor: ...


class _Bases:
    """The link base of the bound tenant, for the ladder: the container's per-tenant source."""

    def __init__(self, source: LinkBaseUrlFor) -> None:
        self._source = source

    async def link_base_url(self, scope: ScopeId) -> str:
        return await resolve_link_base(self._source, scope)


def build_ladder(container: _Container) -> MissedReportLadder:
    """The ladder the reminder runs: the same use case the scheduled step runs, with the tenant's
    link base and the container's clock, ids, sealer and secrets."""

    def tokens(repo: Any) -> LinkTokenService:
        return LinkTokenService(repo, container.secrets, container.clock)

    return MissedReportLadder(
        container.uow_factory,
        container.clock,
        container.ids,
        tokens,
        _Bases(container.link_base_url_for),
        container.sealer,
    )


def _container(request: Request) -> _Container:
    return cast(_Container, get_container(request))


def _answer(body: dict[str, Any]) -> Response:
    return FhirJSONResponse(content=body, headers=NO_STORE)


def _at(value: Any) -> str | None:
    return None if value is None else format_instant(value)


async def _optional_json(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    try:
        body = json.loads(raw)
    except ValueError:
        raise ValidationFailed("body", "is not valid JSON") from None
    if not isinstance(body, dict):
        raise ValidationFailed("body", "must be a JSON object")
    return body


# ------------------------------------------------------------------------------------- reads


@router.get("/overview")
async def read_overview(
    request: Request, actor: Annotated[Actor, Depends(require_role(*LEAD))]
) -> Response:
    container = _container(request)
    view = await GetLeadOverview(container.uow_factory, container.clock).execute(actor)
    return _answer(
        {
            "chasing": [
                {
                    "serviceId": item.service_id,
                    "name": item.name,
                    "dueAt": format_instant(item.due_at),
                    "overdueMinutes": item.overdue_minutes,
                    "lastValueText": item.last_value_text,
                    "ladder": [
                        {"step": row.step, "at": format_instant(row.at), "done": row.done}
                        for row in item.ladder
                    ],
                }
                for item in view.chasing
            ],
            "gettingOld": [
                {
                    "serviceId": item.service_id,
                    "name": item.name,
                    "reportedAt": format_instant(item.reported_at),
                    "nextDueAt": format_instant(item.next_due_at),
                    "status": item.status.value,
                }
                for item in view.getting_old
            ],
            "covering": [
                {
                    "serviceId": item.service_id,
                    "name": item.name,
                    "numberEnding": item.number_ending,
                    "until": format_instant(item.until),
                }
                for item in view.covering
            ],
            "counts": {key: view.counts[status] for status, key in _COUNT_KEYS.items()},
            "reportingToday": view.reporting_today,
        }
    )


@router.get("/reporters")
async def read_reporters(
    request: Request, actor: Annotated[Actor, Depends(require_role(*LEAD))]
) -> Response:
    container = _container(request)
    rows = await ListReporters(container.uow_factory, container.clock).execute(
        actor, request.query_params.get("service")
    )
    return _answer(
        {
            "reporters": [
                {
                    "serviceId": row.service_id,
                    "serviceName": row.service_name,
                    "roleId": row.role_id,
                    "role": row.role,
                    "channel": row.channel,
                    "numberEnding": row.number_ending,
                    "coveredUntil": _at(row.covered_until),
                }
                for row in rows
            ]
        }
    )


@router.get("/services/{service_id}/suspension")
async def read_suspension(
    service_id: str, request: Request, actor: Annotated[Actor, Depends(require_role(*LEAD))]
) -> Response:
    view = await GetSuspension(_container(request).uow_factory).execute(actor, service_id)
    return _answer(
        {
            "suspended": view.suspended,
            "since": _at(view.since),
            "reason": view.reason,
            "expiredRequests": view.expired_requests,
            "registerNumber": view.register_number,
        }
    )


@router.get("/phones")
async def read_phones(
    request: Request, actor: Annotated[Actor, Depends(require_role(*LEAD))]
) -> Response:
    container = _container(request)
    rows = await ListPhones(container.uow_factory, container.clock).execute(actor)
    return _answer(
        {
            "phones": [
                {
                    "phoneEnding": row.phone_ending,
                    "role": row.role,
                    "services": [{"id": sid, "name": name} for sid, name in row.services],
                    "channel": row.channel,
                    "lastSeen": _at(row.last_seen),
                }
                for row in rows
            ]
        }
    )


@router.get("/invitations")
async def read_invitations(
    request: Request, actor: Annotated[Actor, Depends(require_role(*LEAD))]
) -> Response:
    rows = await ListInvitations(_container(request).uow_factory).execute(actor)
    return _answer(
        {
            "items": [
                {
                    "id": row.invitation_id,
                    "serviceId": row.service_id,
                    "serviceName": row.service_name,
                    "role": row.role,
                    "steps": row.steps,
                    "invitedAt": format_instant(row.invited_at),
                    "lastSeen": format_instant(row.last_seen),
                    "firstReportAt": _at(row.first_report_at),
                }
                for row in rows
            ]
        }
    )


# ---------------------------------------------------------------------------------- actions


_PHONED_KEYS: Final = frozenset({"told", "value"})


@router.post("/services/{service_id}/remind")
async def remind(
    service_id: str, request: Request, actor: Annotated[Actor, Depends(require_role(*LEAD))]
) -> Response:
    key = idempotency_key(request)
    container = _container(request)

    async def run() -> Response:
        await RemindService(container.uow_factory, build_ladder(container)).execute(
            actor, service_id, key
        )
        return _answer({"reminded": True})

    return await replay_or_run(request, actor, f"lead-remind:{service_id}:{key}", run)


@router.post("/services/{service_id}/test-prompt")
async def test_prompt(
    service_id: str, request: Request, actor: Annotated[Actor, Depends(require_role(*LEAD))]
) -> Response:
    key = idempotency_key(request)
    body = await _optional_json(request)
    if set(body) - {"channel"}:
        raise ValidationFailed("body", "names a value this route does not take")
    raw = body.get("channel")
    channel: Channel | None = None
    if raw is not None:
        if not isinstance(raw, str) or raw not in {item.value for item in Channel}:
            raise ValidationFailed("channel", "must be text, email or push")
        channel = Channel(raw)
    container = _container(request)

    async def run() -> Response:
        sent = await SendLeadTestPrompt(
            container.uow_factory, container.ids, container.clock, container.sealer
        ).execute(actor, service_id, channel, key)
        return _answer({"channel": sent.channel.value, "numberEnding": sent.number_ending})

    return await replay_or_run(request, actor, f"lead-test-prompt:{service_id}:{key}", run)


@router.post("/services/{service_id}/phoned", status_code=201)
async def record_phoned(
    service_id: str, request: Request, actor: Annotated[Actor, Depends(require_role(*LEAD))]
) -> Response:
    key = idempotency_key(request)
    body = await _optional_json(request)
    if set(body) - _PHONED_KEYS:
        raise ValidationFailed("body", "names a value this route does not take")
    told = body.get("told")
    if not isinstance(told, str) or told not in PHONED_ANSWERS:
        raise ValidationFailed("told", "must be accepting, limited or not-accepting")
    value = body.get("value")
    container = _container(request)

    async def run() -> Response:
        # The lead's answer has no case, so the report carries no case id (DEC-920). The use case
        # refuses a value that does not match the answer, before anything is written.
        result = await RecordAdvisorPhoned(
            ReportCapacity(
                container.uow_factory,
                container.clock,
                container.ids,
                UnitOfWorkIdempotency(container.uow_factory),
                zones=DirectoryZones(container.tenants),
            ),
            container.uow_factory,
        ).execute(
            RecordAdvisorPhonedCommand(
                idempotency_key=key,
                actor=actor,
                service_id=service_id,
                told=cast(PhonedAnswer, told),
                value=value if isinstance(value, int) and not isinstance(value, bool) else None,
            )
        )
        async with container.uow_factory() as uow:
            stored = await uow.capacity.get(result.report_id)
        if stored is None:
            raise RuntimeError("the report that was just stored cannot be read")
        return FhirJSONResponse(
            content={"reportId": stored.id, "value": stored.value},
            status_code=201,
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"lead-phoned:{service_id}:{key}", run)


@router.post("/invitations/{invitation_id}/resend")
async def resend_invitation(
    invitation_id: str, request: Request, actor: Annotated[Actor, Depends(require_role(*LEAD))]
) -> Response:
    key = idempotency_key(request)
    container = _container(request)

    async def run() -> Response:
        result = await ResendInvitation(
            container.uow_factory,
            lambda repo: LinkTokenService(repo, container.secrets, container.clock),
            container.clock,
            container.ids,
            link_base_url_for=container.link_base_url_for,
        ).execute(
            ResendInvitationCommand(idempotency_key=key, actor=actor, invitation_id=invitation_id)
        )
        return _answer(
            {
                "invitationId": result.invitation_id,
                "registrationId": result.registration_id,
                "expiresAt": format_instant(result.expires_at),
            }
        )

    return await replay_or_run(request, actor, f"lead-resend:{invitation_id}:{key}", run)


@router.post("/invitations/{invitation_id}/switch-to-text")
async def switch_to_text(
    invitation_id: str, request: Request, actor: Annotated[Actor, Depends(require_role(*LEAD))]
) -> Response:
    key = idempotency_key(request)
    container = _container(request)

    async def run() -> Response:
        channel = await SwitchReporterToText(container.uow_factory, container.clock).execute(
            actor, invitation_id, key
        )
        return _answer({"channel": channel.value})

    return await replay_or_run(request, actor, f"lead-switch-text:{invitation_id}:{key}", run)


__all__ = ["build_ladder", "router"]
