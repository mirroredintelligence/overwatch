"""Shift lead, sign-out, lost-phone confirmation and audit routes over HTTP (R13). Thin: each route
reads its body, checks its shape, runs one use case and maps the result. No rule lives here.

POST   /fhir/HealthcareService/{id}/$suspend          lead; Idempotency-Key; Parameters reason
                                                      (SuspendService, U36)
POST   /fhir/HealthcareService/{id}/$resume           lead; Idempotency-Key; Parameters calledBack
                                                      and reasonResolved, both true (ResumeService,
                                                      U36); anything else is a 400 naming the part
POST   /fhir/PractitionerRole/{id}/$remove            lead; Idempotency-Key; Parameters reason
                                                      (RemovePerson, U37)
POST   /fhir/HealthcareService/{id}/$move             lead; Idempotency-Key; Parameters toMobile,
                                                      until (StartServiceMove, U38)
GET    /admin/report-flags?status=open                lead; the open report flags (ListReportFlags,
                                                      U39)
POST   /admin/report-flags/{id}/$resolve              lead; Idempotency-Key; Parameters outcome
                                                      (checked, accepted or phoned), phoned
                                                      (ResolveReportFlag, U39). A suspension is made
                                                      with $suspend, not here
POST   /identity/sign-out-everywhere                  reporter (self) or lead; Idempotency-Key
                                                      (SignOutEverywhere, U37)
POST   /fhir/Practitioner/{id}/$confirm-new-phone     lead; Idempotency-Key (ConfirmNewPhone, U37)
GET    /admin/audit/{caseReference}                   audit or lead; the replay of what the advisor
                                                      saw; each call is itself audited (U42)

The lost-phone start and check are /identity/new-phone and /identity/new-phone/verify, on the
identity routes (routes_identity.py), because they share the unauthenticated edge of R11.

A refused role is a non-revealing 404 (require_role). Every POST needs an Idempotency-Key, checked
before the body. An error names the part, never its value. No patient data is in any response.

Tenancy: the tenant is bound at the REST edge from the verified token (TEN-018), by current_actor.
Nothing here reads a tenant from the body, the query or a header.
"""

import json
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from diucs.adapters.inbound.fhir_rest.parameters import (
    PARAMETERS,
    enum_value,
    index_parameters,
    single,
    whole,
)
from diucs.application.actor import Actor
from diucs.application.idempotency import format_instant
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import (
    HmacPhoneHasher,
    SessionStore,
    normalise_uk_mobile,
)
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenant_settings import DirectoryZones
from diucs.application.uow_idempotency import UnitOfWorkIdempotency
from diucs.application.use_cases.advisor_phoned import RecordAdvisorPhoned
from diucs.application.use_cases.audit_replay import (
    ExportAuditReplay,
    GetAuditReplay,
    GetAuditReplayCommand,
)
from diucs.application.use_cases.invite_reporter import MOBILE_MESSAGE
from diucs.application.use_cases.move_service import StartServiceMove, StartServiceMoveCommand
from diucs.application.use_cases.remove_person import (
    ConfirmNewPhone,
    ConfirmNewPhoneCommand,
    RemovalReason,
    RemovePerson,
    RemovePersonCommand,
    SignOutEverywhere,
    SignOutEverywhereCommand,
)
from diucs.application.use_cases.report_capacity import ReportCapacity
from diucs.application.use_cases.resolve_report_flag import (
    ListReportFlags,
    ListReportFlagsQuery,
    ResolveReportFlag,
    ResolveReportFlagCommand,
)
from diucs.application.use_cases.suspend_service import (
    ResumeService,
    ResumeServiceCommand,
    SuspendReason,
    SuspendService,
    SuspendServiceCommand,
)
from diucs.application.use_cases.tenant_config import ReadTenantConfig
from diucs.domain.codes import Role
from diucs.domain.errors import NotFound, ValidationFailed

router = APIRouter()

LEAD: Final = (Role.LEAD,)
AUDIT_OR_LEAD: Final = (Role.AUDIT, Role.LEAD)
SIGN_OUT: Final = (Role.REPORTER, Role.LEAD)
NO_STORE: Final = {"Cache-Control": "no-store"}
OPEN: Final = "open"
CLOSED: Final = "closed"
SUSPENDED_OUTCOME: Final = "suspended"
FLAG_OUTCOMES: Final[dict[str, Literal["checked", "accepted", "phoned"]]] = {
    "checked": "checked",
    "accepted": "accepted",
    "phoned": "phoned",
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
    def sessions(self) -> SessionStore: ...
    @property
    def sealer(self) -> ContentSealer: ...


def _container(request: Request) -> _Container:
    return cast(_Container, get_container(request))


async def _body(request: Request) -> object:
    try:
        return json.loads(await request.body())
    except ValueError:
        raise ValidationFailed(PARAMETERS, "the body is not valid JSON") from None


def _confirmed(index: dict[str, list[dict[str, Any]]], name: str) -> None:
    """A confirmation a resume needs: the part must be given and must be true (U36)."""
    if single(index, name, required=True) is not True:
        raise ValidationFailed(name, "must be confirmed before the service is resumed")


def _mobile(value: object) -> str:
    """The national form of a UK mobile, or the use case's refusal. The input is never repeated."""
    try:
        if not isinstance(value, str):
            raise ValidationFailed("toMobile", MOBILE_MESSAGE)
        return normalise_uk_mobile(value)
    except ValidationFailed:
        raise ValidationFailed("toMobile", MOBILE_MESSAGE) from None


def _until(index: dict[str, list[dict[str, Any]]]) -> datetime | None:
    raw = single(index, "until", required=False)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValidationFailed("until", "must be a date and time")
    try:
        instant = datetime.fromisoformat(raw)
    except ValueError:
        raise ValidationFailed("until", "must be a date and time") from None
    if instant.tzinfo is None:
        raise ValidationFailed("until", "must carry a UTC offset")
    return instant.astimezone(UTC)


# ------------------------------------------------------------------ the service (U36, U38)


@router.post("/fhir/HealthcareService/{service_id}/$suspend")
async def suspend_service(
    service_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*LEAD))],
) -> Response:
    key = idempotency_key(request)
    reason = enum_value(
        SuspendReason,
        single(index_parameters(await _body(request)), "reason", required=True),
        "reason",
    )
    container = _container(request)

    async def run() -> Response:
        reader = ReadTenantConfig(container.uow_factory)
        policy = await reader.policy()
        # Read before SuspendService opens its unit: it asks for the wording inside that unit, and
        # a reader that opened a unit there would be a second one (UnitOfWorkAlreadyOpen, a 500).
        wording = await reader.wording()

        async def wording_for(_scope: object) -> Any:
            return wording

        result = await SuspendService(
            container.uow_factory,
            UnitOfWorkIdempotency(container.uow_factory),
            container.clock,
            container.ids,
            container.sealer,
            wording_for,
            policy,
        ).execute(
            SuspendServiceCommand(
                idempotency_key=key,
                actor=actor,
                service_id=service_id,
                reason=reason.value,
            )
        )
        return FhirJSONResponse(
            content={
                "resourceType": PARAMETERS,
                "parameter": [
                    {"name": "expiredRequests", "valueInteger": result.expired_requests},
                    {"name": "notified", "valueBoolean": result.notified},
                ],
            },
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"suspend:{service_id}:{key}", run)


@router.post("/fhir/HealthcareService/{service_id}/$resume")
async def resume_service(
    service_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*LEAD))],
) -> Response:
    key = idempotency_key(request)
    index = index_parameters(await _body(request))
    _confirmed(index, "calledBack")
    _confirmed(index, "reasonResolved")
    container = _container(request)

    async def run() -> Response:
        policy = await ReadTenantConfig(container.uow_factory).policy()
        result = await ResumeService(
            container.uow_factory,
            UnitOfWorkIdempotency(container.uow_factory),
            container.clock,
            container.ids,
            policy,
        ).execute(
            ResumeServiceCommand(
                idempotency_key=key,
                actor=actor,
                service_id=service_id,
                phoned_register_number=True,
                reason_resolved=True,
            )
        )
        return FhirJSONResponse(
            content={
                "resourceType": PARAMETERS,
                "parameter": [
                    {"name": "status", "valueCode": result.status.value},
                    {"name": "nextDueAt", "valueDateTime": format_instant(result.next_due_at)},
                ],
            },
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"resume:{service_id}:{key}", run)


@router.post("/fhir/HealthcareService/{service_id}/$move")
async def move_service(
    service_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*LEAD))],
) -> Response:
    key = idempotency_key(request)
    index = index_parameters(await _body(request))
    to_mobile = _mobile(single(index, "toMobile", required=True))
    until = _until(index)
    container = _container(request)

    async def run() -> Response:
        result = await StartServiceMove(
            container.uow_factory,
            container.ids,
            container.clock,
            HmacPhoneHasher(container.secrets),
        ).execute(
            StartServiceMoveCommand(
                actor=actor, service_id=service_id, to_mobile=to_mobile, until=until
            )
        )
        return FhirJSONResponse(
            content={
                "resourceType": PARAMETERS,
                "parameter": [{"name": "moveId", "valueString": result.move_id}],
            },
            status_code=201,
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"move:{service_id}:{key}", run)


# -------------------------------------------------------------- the people and the phones (U37)


@router.post("/fhir/PractitionerRole/{role_id}/$remove")
async def remove_person(
    role_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*LEAD))],
) -> Response:
    key = idempotency_key(request)
    reason = enum_value(
        RemovalReason,
        single(index_parameters(await _body(request)), "reason", required=True),
        "reason",
    )
    container = _container(request)

    async def run() -> Response:
        async with container.uow_factory() as uow:
            role = await uow.people.get_role(role_id)
        if role is None:
            raise NotFound("no reporter role with this id")
        result = await RemovePerson(
            container.uow_factory, container.clock, container.ids, container.sessions
        ).execute(
            RemovePersonCommand(
                idempotency_key=key,
                actor=actor,
                practitioner_id=role.practitioner_id,
                reason=reason,
            )
        )
        return FhirJSONResponse(
            content={
                "resourceType": PARAMETERS,
                "parameter": [
                    {"name": "rolesEnded", "valueInteger": result.roles_ended},
                    {"name": "devicesRevoked", "valueInteger": result.devices_revoked},
                    {
                        "name": "servicesWithoutReporter",
                        "valueInteger": len(result.services_without_reporter),
                    },
                ],
            },
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"remove:{role_id}:{key}", run)


@router.post("/identity/sign-out-everywhere")
async def sign_out_everywhere(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*SIGN_OUT))],
) -> Response:
    key = idempotency_key(request)
    container = _container(request)

    async def run() -> Response:
        result = await SignOutEverywhere(
            container.uow_factory, container.clock, container.sessions
        ).execute(SignOutEverywhereCommand(idempotency_key=key, actor=actor))
        return FhirJSONResponse(content={"signedOut": result.devices_signed_out}, headers=NO_STORE)

    return await replay_or_run(request, actor, f"sign-out:{key}", run)


@router.post("/fhir/Practitioner/{practitioner_id}/$confirm-new-phone")
async def confirm_new_phone(
    practitioner_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*LEAD))],
) -> Response:
    key = idempotency_key(request)
    container = _container(request)

    async def run() -> Response:
        result = await ConfirmNewPhone(container.uow_factory, container.clock).execute(
            ConfirmNewPhoneCommand(
                idempotency_key=key, actor=actor, practitioner_id=practitioner_id
            )
        )
        return FhirJSONResponse(content={"confirmed": result.confirmed}, headers=NO_STORE)

    return await replay_or_run(request, actor, f"confirm-phone:{practitioner_id}:{key}", run)


# --------------------------------------------------------------------- the report flags (U39)


def _flag_resource(flag: Any) -> dict[str, Any]:
    """One flag as a FHIR Flag: active while open; inactive once checked or accepted, with how it
    was closed and when. The person who closed it is not shown."""
    period = {"start": format_instant(flag.raised_at)}
    resource: dict[str, Any] = {
        "resourceType": "Flag",
        "id": flag.flag_id,
        "status": "active" if flag.resolved_at is None else "inactive",
        "code": {"coding": [{"code": flag.reason.value}]},
        "subject": {
            "reference": f"HealthcareService/{flag.service_id}",
            "display": flag.service_name,
        },
        "period": period,
    }
    if flag.resolved_at is not None:
        period["end"] = format_instant(flag.resolved_at)
        resource["outcome"] = flag.outcome
    return resource


@router.get("/admin/report-flags")
async def read_report_flags(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*LEAD))],
) -> Response:
    status = request.query_params.get("status")
    if status not in (OPEN, CLOSED):
        raise ValidationFailed("status", "must be open or closed")
    flags = await ListReportFlags(_container(request).uow_factory).execute(
        ListReportFlagsQuery(actor=actor, closed=status == CLOSED)
    )
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(flags),
        "entry": [{"resource": _flag_resource(flag)} for flag in flags],
    }
    return FhirJSONResponse(content=bundle, headers=NO_STORE)


@router.post("/admin/report-flags/{flag_id}/$resolve")
async def resolve_report_flag(
    flag_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*LEAD))],
) -> Response:
    key = idempotency_key(request)
    index = index_parameters(await _body(request))
    raw = single(index, "outcome", required=True)
    if raw == SUSPENDED_OUTCOME:
        raise ValidationFailed("outcome", "a suspension is made with $suspend")
    if not isinstance(raw, str) or raw not in FLAG_OUTCOMES:
        raise ValidationFailed("outcome", "must be checked, accepted or phoned")
    phoned_value = single(index, "phoned", required=False)
    phoned = None if phoned_value is None else whole(phoned_value, "phoned")
    outcome = FLAG_OUTCOMES[raw]
    container = _container(request)

    async def run() -> Response:
        result = await ResolveReportFlag(
            container.uow_factory,
            RecordAdvisorPhoned(
                ReportCapacity(
                    container.uow_factory,
                    container.clock,
                    container.ids,
                    UnitOfWorkIdempotency(container.uow_factory),
                    zones=DirectoryZones(container.tenants),
                ),
                container.uow_factory,
            ),
            container.clock,
        ).execute(
            ResolveReportFlagCommand(
                idempotency_key=key,
                actor=actor,
                flag_id=flag_id,
                outcome=outcome,
                phoned_value=phoned,
            )
        )
        return FhirJSONResponse(
            content={
                "resourceType": PARAMETERS,
                "parameter": [
                    {"name": "flagId", "valueString": result.flag_id},
                    {"name": "status", "valueString": result.status},
                    {"name": "outcome", "valueString": result.outcome},
                ],
            },
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"resolve-flag:{flag_id}:{key}", run)


# ------------------------------------------------------------------------- the audit (U42)


@router.get("/admin/audit/{case_reference}")
async def audit_replay(
    case_reference: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*AUDIT_OR_LEAD))],
) -> Response:
    container = _container(request)
    replay = await ExportAuditReplay(
        GetAuditReplay(container.uow_factory, container.clock)
    ).execute(GetAuditReplayCommand(actor=actor, reference=case_reference))
    return FhirJSONResponse(content=replay, headers=NO_STORE)


__all__ = ["router"]
