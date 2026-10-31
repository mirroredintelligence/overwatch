"""Criteria versions over HTTP (R10): the owner's change, its approval, the review period and the
history. Thin: each route reads its body, checks its shape, runs one use case and maps the result.

POST   /fhir/Basic                                  owner; Idempotency-Key; Parameters service,
                                                    ageMin, ageMax, accepts, excludes, district,
                                                    changeReason, reviewMonths (3, 6 or 12); 201
                                                    Basic in pending-approval (ChangeCriteria, U30)
POST   /fhir/Basic/{id}/$submit-for-approval        owner; Idempotency-Key; the version as it stands
                                                    if it is waiting for approval, else 409
POST   /fhir/Basic/{id}/$approve                    lead; Idempotency-Key; an optional note; the
                                                    author cannot approve their own change, which is
                                                    a 404 (ApproveCriteria, U30)
POST   /fhir/Basic/{id}/$send-back                  lead; Idempotency-Key; an optional note
POST   /fhir/HealthcareService/{id}/$confirm-criteria  owner or lead; Idempotency-Key; Parameters
                                                    reviewInMonths 3, 6 or 12 (ConfirmCriteria, U30)
GET    /fhir/Basic?subject=HealthcareService/{id}   owner, advisor, clinical or lead; every version,
                                                    newest first, with what it accepts and
                                                    excludes; an advisor reads the current
                                                    version only (CriteriaHistory, U30, DEC-771)

A note is at most 280 characters and carries no patient information. A refused role is a
non-revealing 404 (require_role). An error names the part, never its value.

Design note. ChangeCriteria writes the new version straight into pending-approval (U30 has no draft
state), so `$submit-for-approval` confirms a version that is already waiting for approval rather
than moving it. The prompt's draft step has no use case to expose; this is recorded in the fragment.
"""

import json
from typing import Annotated, Any, Final, Protocol, cast

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
    optional_text,
    reference_id,
    reference_part,
    repeated,
    single,
    text,
    whole,
)
from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.criteria import (
    ApproveCriteria,
    ApproveCriteriaCommand,
    ChangeCriteria,
    ChangeCriteriaCommand,
    ConfirmCriteria,
    ConfirmCriteriaCommand,
    CriteriaHistory,
    CriteriaHistoryQuery,
    CriteriaValues,
    CriteriaVersionView,
)
from diucs.domain.codes import CriteriaStatus, NeedCategory, Role
from diucs.domain.errors import InvalidTransition, NotFound, ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria

router = APIRouter(prefix="/fhir")

NOTE_LIMIT: Final = 280
REVIEW_PERIODS: Final = frozenset({3, 6, 12})
"""The review periods the owner may choose, in months (U30, domain-rules section 6)."""
NO_STORE: Final = {"Cache-Control": "no-store"}
CRITERIA_CODE_SYSTEM: Final = "service-criteria"
HISTORY_ROLES: Final = (Role.OWNER, Role.ADVISOR, Role.CLINICAL, Role.LEAD)
OWNER_ROLES: Final = (Role.OWNER,)
CONFIRM_ROLES: Final = (Role.OWNER, Role.LEAD)


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...
    @property
    def ids(self) -> IdGenerator: ...
    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...


def _container(request: Request) -> _Container:
    return cast(_Container, get_container(request))


async def _optional_body(request: Request) -> object | None:
    """A body that may be absent: an empty one is no body at all."""
    raw = await request.body()
    if not raw:
        return None
    try:
        parsed: object = json.loads(raw)
    except ValueError:
        raise ValidationFailed(PARAMETERS, "the body is not valid JSON") from None
    return parsed


def _basic(record: ServiceCriteria) -> dict[str, Any]:
    """One version as a Basic resource. The values are sorted so the same version always reads the
    same."""
    body: dict[str, Any] = {
        "resourceType": "Basic",
        "id": record.id,
        "meta": {"versionId": str(record.version)},
        "code": {"coding": [{"code": CRITERIA_CODE_SYSTEM}]},
        "subject": {"reference": f"HealthcareService/{record.service_id}"},
        "status": record.status.value,
        "reviewBy": record.review_by.isoformat(),
        "ageMin": record.age_min,
        "accepts": sorted(need.value for need in record.accepts),
        "excludes": sorted(need.value for need in record.excludes),
        "districts": sorted(record.districts),
    }
    if record.age_max is not None:
        body["ageMax"] = record.age_max
    if record.change_reason:
        body["changeReason"] = record.change_reason
    return body


def _view_basic(view: CriteriaVersionView, service_id: str) -> dict[str, Any]:
    """One version as the history shows it: its status, review date and what it accepts and
    excludes (the criteria dialog reads these), and the age range. Not the districts or the change
    reason. The day of the change and the author's post in words (never a person) are there for
    the roles that read the history of changes; an advisor reads neither (W7B B)."""
    body: dict[str, Any] = {
        "resourceType": "Basic",
        "id": view.criteria_id,
        "meta": {"versionId": str(view.version)},
        "code": {"coding": [{"code": CRITERIA_CODE_SYSTEM}]},
        "subject": {"reference": f"HealthcareService/{service_id}"},
        "status": view.status.value,
        "reviewBy": view.review_by.isoformat(),
        "ageMin": view.age_min,
        "accepts": sorted(need.value for need in view.accepts),
        "excludes": sorted(need.value for need in view.excludes),
    }
    if view.age_max is not None:
        body["ageMax"] = view.age_max
    if view.author_role is not None or view.changed_on is not None:
        body["changedOn"] = None if view.changed_on is None else view.changed_on.isoformat()
        body["authorRole"] = view.author_role
    return body


# ----------------------------------------------------------------------------- command parsing


def change_command(body: object, actor: Actor, key: str) -> ChangeCriteriaCommand:
    """The command of one criteria change. The review period must be one the owner may choose, and
    the values are checked before the store is touched."""
    index = index_parameters(body)
    parts = index.get("service") or []
    if len(parts) != 1:
        raise ValidationFailed("service", "is required" if not parts else "is given once")
    service_id = reference_part(parts[0], "service", "HealthcareService")
    age_min = whole(single(index, "ageMin", required=True), "ageMin")
    age_max_value = single(index, "ageMax", required=False)
    age_max = None if age_max_value is None else whole(age_max_value, "ageMax")
    accepts = frozenset(enum_value(NeedCategory, v, "accepts") for v in repeated(index, "accepts"))
    excludes = frozenset(
        enum_value(NeedCategory, v, "excludes") for v in repeated(index, "excludes")
    )
    districts = frozenset(text(v, "district") for v in repeated(index, "district"))
    change_reason = text(
        single(index, "changeReason", required=True), "changeReason", limit=NOTE_LIMIT
    )
    months = whole(single(index, "reviewMonths", required=True), "reviewMonths")
    if months not in REVIEW_PERIODS:
        raise ValidationFailed("reviewMonths", "must be 3, 6 or 12 months")
    return ChangeCriteriaCommand(
        idempotency_key=key,
        actor=actor,
        service_id=service_id,
        values=CriteriaValues(
            age_min=age_min,
            age_max=age_max,
            accepts=accepts,
            excludes=excludes,
            districts=districts,
        ),
        change_reason=change_reason,
        review_months=months,
    )


def confirm_command(
    service_id: str, body: object, actor: Actor, key: str
) -> ConfirmCriteriaCommand:
    """The command of one review-period confirmation for a service: 3, 6 or 12 months only."""
    index = index_parameters(body)
    months = whole(single(index, "reviewInMonths", required=True), "reviewInMonths")
    if months not in REVIEW_PERIODS:
        raise ValidationFailed("reviewInMonths", "must be 3, 6 or 12 months")
    return ConfirmCriteriaCommand(
        idempotency_key=key,
        actor=actor,
        service_id=service_id,
        review_months=months,
    )


def history_subject(value: str | None) -> str:
    """The service id a history query names: `subject=HealthcareService/<id>`. Anything else is
    refused, naming the parameter."""
    if value is None:
        raise ValidationFailed("subject", "is required")
    return reference_id(value, "subject", "HealthcareService")


def _note(body: object | None) -> str:
    if body is None:
        return ""
    index = index_parameters(body)
    return optional_text(single(index, "note", required=False), "note", limit=NOTE_LIMIT)


# ----------------------------------------------------------------------------------------- routes


@router.post("/Basic", status_code=201)
async def create_criteria_version(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*OWNER_ROLES))],
) -> Response:
    key = idempotency_key(request)
    command = change_command(await _optional_body(request), actor, key)
    container = _container(request)

    async def run() -> Response:
        result = await ChangeCriteria(
            container.uow_factory, container.ids, container.clock
        ).execute(command)
        async with container.uow_factory() as uow:
            record = await uow.criteria.get(result.criteria_id)
        if record is None:
            raise RuntimeError("the criteria version that was just stored cannot be read")
        return FhirJSONResponse(content=_basic(record), status_code=201, headers=NO_STORE)

    return await replay_or_run(request, actor, f"criteria-change:{key}", run)


@router.post("/Basic/{criteria_id}/$submit-for-approval")
async def submit_for_approval(
    criteria_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*OWNER_ROLES))],
) -> Response:
    key = idempotency_key(request)
    container = _container(request)

    async def run() -> Response:
        async with container.uow_factory() as uow:
            record = await uow.criteria.get(criteria_id)
            roles = await uow.people.roles_for_practitioner(actor.practitioner_id or "")
        # A version this owner cannot see is the same answer as a version that is not there.
        if record is None or record.owner_role_id not in {role.id for role in roles}:
            raise NotFound("no criteria version with this id")
        if record.status is not CriteriaStatus.PENDING_APPROVAL:
            raise InvalidTransition("this version is not waiting for approval")
        return FhirJSONResponse(content=_basic(record), headers=NO_STORE)

    return await replay_or_run(request, actor, f"criteria-submit:{criteria_id}:{key}", run)


async def _decide(criteria_id: str, request: Request, actor: Actor, decision: str) -> Response:
    key = idempotency_key(request)
    note = _note(await _optional_body(request))
    container = _container(request)

    async def run() -> Response:
        result = await ApproveCriteria(
            container.uow_factory, container.ids, container.clock
        ).execute(
            ApproveCriteriaCommand(
                idempotency_key=key,
                actor=actor,
                criteria_id=criteria_id,
                decision="approve" if decision == "approve" else "send-back",
                note=note,
            )
        )
        async with container.uow_factory() as uow:
            record = await uow.criteria.get(result.criteria_id)
        if record is None:
            raise RuntimeError("the criteria version cannot be read after its decision")
        return FhirJSONResponse(content=_basic(record), headers=NO_STORE)

    return await replay_or_run(request, actor, f"criteria-{decision}:{criteria_id}:{key}", run)


@router.post("/Basic/{criteria_id}/$approve")
async def approve_criteria(
    criteria_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    return await _decide(criteria_id, request, actor, "approve")


@router.post("/Basic/{criteria_id}/$send-back")
async def send_back_criteria(
    criteria_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(Role.LEAD))],
) -> Response:
    return await _decide(criteria_id, request, actor, "send-back")


@router.post("/HealthcareService/{service_id}/$confirm-criteria")
async def confirm_criteria(
    service_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CONFIRM_ROLES))],
) -> Response:
    key = idempotency_key(request)
    command = confirm_command(service_id, await _optional_body(request), actor, key)
    container = _container(request)

    async def run() -> Response:
        result = await ConfirmCriteria(container.uow_factory, container.clock).execute(command)
        return FhirJSONResponse(
            content={
                "resourceType": PARAMETERS,
                "parameter": [
                    {"name": "criteriaId", "valueString": result.criteria_id},
                    {"name": "reviewBy", "valueDate": result.review_by.isoformat()},
                ],
            },
            headers=NO_STORE,
        )

    return await replay_or_run(request, actor, f"criteria-confirm:{service_id}:{key}", run)


@router.get("/Basic")
async def read_criteria_history(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*HISTORY_ROLES))],
) -> Response:
    service_id = history_subject(request.query_params.get("subject"))
    versions = await CriteriaHistory(_container(request).uow_factory).execute(
        CriteriaHistoryQuery(actor=actor, service_id=service_id)
    )
    newest_first = sorted(versions, key=lambda view: view.version, reverse=True)
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(newest_first),
        "entry": [{"resource": _view_basic(view, service_id)} for view in newest_first],
    }
    return FhirJSONResponse(content=bundle, headers=NO_STORE)


__all__ = [
    "change_command",
    "confirm_command",
    "history_subject",
    "router",
]
