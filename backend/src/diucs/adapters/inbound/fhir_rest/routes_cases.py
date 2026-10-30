"""Advisor cases over FHIR (R07).

POST /fhir/ServiceRequest                       open a case (OpenCase, U11, then UpdateCase, U11)
PUT  /fhir/ServiceRequest/{id}                  update needs, urgency and postcode (If-Match)
POST /fhir/ServiceRequest/{id}/$close           close with an outcome (RecordOutcome, U14)
POST /fhir/HealthcareService/$filter-options    the options for a case (FilterOptions, U12)
POST /fhir/HealthcareService/{id}/$advisor-phoned   "I phoned" (RecordAdvisorPhoned, U13)
POST /fhir/HealthcareService/{id}/$declined     declined despite capacity (RecordDecline, U13)

The routes hold no business rule: each one reads the request's shape, calls one use case and writes
its FHIR answer. Who may call is `require_role(advisor, clinical)`; any other role, and any id that
is not in the caller's tenant, answers the same 404 as an unknown id (NotAllowed and NotFound).

The only stored patient data is the postcode district and an age band (DEC-398). A Patient with a
name, identifier, birth date or telecom is refused with 400 invalid before anything is read or
written; the message never echoes the value.

Decisions: DEC-397 (the open is two use cases in two units; the priority mapping), DEC-398 (no case
version: If-Match is required but its value is not compared; the answers are the stored shape).
"""

import json
from dataclasses import replace
from typing import Annotated, Any, Final, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from diucs.adapters.inbound.fhir_rest import capability
from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.case_mapping import (
    CaseDetails,
    case_to_fhir,
    parse_case_details,
    refuse_patient_details,
)
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key, require_if_match
from diucs.adapters.inbound.fhir_rest.mapping import validate_outbound
from diucs.adapters.inbound.fhir_rest.routes_services import UnitOfWorkIdempotency
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.advisor_phoned import (
    PHONED_ANSWERS,
    PhonedAnswer,
    RecordAdvisorPhoned,
    RecordAdvisorPhonedCommand,
)
from diucs.application.use_cases.filter_options import (
    FilterOptions,
    FilterOptionsCommand,
    FilterOptionsResult,
)
from diucs.application.use_cases.open_case import (
    OpenCase,
    OpenCaseCommand,
    UpdateCase,
    UpdateCaseCommand,
)
from diucs.application.use_cases.query_board import QueryBoard
from diucs.application.use_cases.record_decline import RecordDecline, RecordDeclineCommand
from diucs.application.use_cases.record_outcome import RecordOutcome, RecordOutcomeCommand
from diucs.application.use_cases.report_capacity import ReportCapacity
from diucs.domain.codes import (
    BASE_URL,
    BestFitNotUsedReason,
    DeclineReason,
    Outcome,
    Role,
)
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.case import Case

CASE_ROLES: Final = (Role.ADVISOR, Role.CLINICAL)
NO_SUCH_CASE: Final = "no case with this id"
ETAG_OPEN: Final = 'W/"1"'

router = APIRouter(prefix="/fhir")
capability.register_resource(
    "ServiceRequest",
    ("create", "update"),
    (f"{BASE_URL}OperationDefinition/close",),
)


def _parameters(body: Any) -> dict[str, list[dict[str, Any]]]:
    """The parts of a Parameters body, grouped by name (a value list may repeat)."""
    if not isinstance(body, dict) or body.get("resourceType") != "Parameters":
        raise ValidationFailed("body", "must be a Parameters resource")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in body.get("parameter", []):
        grouped.setdefault(str(item.get("name")), []).append(item)
    return grouped


def _one(grouped: dict[str, list[dict[str, Any]]], name: str) -> dict[str, Any] | None:
    found = grouped.get(name, [])
    return found[0] if found else None


def _reference_id(item: dict[str, Any] | None, name: str, resource: str) -> str:
    reference = (item or {}).get("valueReference", {}).get("reference")
    prefix = f"{resource}/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise ValidationFailed(name, f"must be a reference to a {resource}")
    value = reference.removeprefix(prefix)
    if not value:
        raise ValidationFailed(name, f"must be a reference to a {resource}")
    return value


def _code(item: dict[str, Any] | None, name: str) -> str:
    code = (item or {}).get("valueCode")
    if not isinstance(code, str) or not code:
        raise ValidationFailed(name, "is required")
    return code


async def _json(request: Request) -> Any:
    try:
        return json.loads(await request.body())
    except ValueError:
        raise ValidationFailed("body", "is not valid JSON") from None


async def _case_or_404(factory: UnitOfWorkFactory, case_id: str) -> Case:
    async with factory() as uow:
        case = await uow.cases.get(case_id)
    if case is None:
        raise NotFound(NO_SUCH_CASE)
    return case


def _update_command(
    key: str, actor: Actor, case_id: str, details: CaseDetails
) -> UpdateCaseCommand:
    return UpdateCaseCommand(
        idempotency_key=key,
        actor=actor,
        case_id=case_id,
        referrer_type=details.referrer_type,
        age_band=details.age_band,
        postcode=details.postcode,
        needs=details.needs,
        urgency=details.urgency,
        scores=details.scores,
    )


async def _service_request(request: Request) -> tuple[dict[str, Any], CaseDetails]:
    """The body of an open or a PUT, checked before anything is read or written."""
    body = await _json(request)
    if not isinstance(body, dict) or body.get("resourceType") != "ServiceRequest":
        raise ValidationFailed("body", "must be a ServiceRequest resource")
    refuse_patient_details(body)
    return body, parse_case_details(body)


@router.post("/ServiceRequest")
async def open_case(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CASE_ROLES))],
) -> Response:
    """Open a case. The body may be empty of details: the call screen opens the case before
    anything is known (DEC-770), and every detail comes by a later PUT."""
    key = idempotency_key(request)
    _, details = await _service_request(request)
    container = get_container(request)
    opened = await OpenCase(
        container.uow_factory,
        container.clock,
        container.ids,
        UnitOfWorkIdempotency(container.uow_factory),
        container.rng,
    ).execute(OpenCaseCommand(key, actor, details.referrer_type))
    rest = replace(details, referrer_type=None)
    if not rest.is_empty:
        await UpdateCase(
            container.uow_factory, container.clock, UnitOfWorkIdempotency(container.uow_factory)
        ).execute(_update_command(f"{key}:details", actor, opened.case_id, rest))
    case = await _case_or_404(container.uow_factory, opened.case_id)
    return FhirJSONResponse(
        content=validate_outbound(case_to_fhir(case)),
        status_code=201,
        headers={"Location": f"/fhir/ServiceRequest/{case.id}", "ETag": ETAG_OPEN},
    )


@router.get("/ServiceRequest/{case_id}")
async def read_case(
    case_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CASE_ROLES))],
) -> Response:
    """One case, open or closed. Another tenant's id is the same 404 as an unknown id."""
    case = await _case_or_404(get_container(request).uow_factory, case_id)
    return FhirJSONResponse(
        content=validate_outbound(case_to_fhir(case)),
        headers={"ETag": ETAG_OPEN, "Cache-Control": "no-store"},
    )


@router.put("/ServiceRequest/{case_id}")
async def update_case(
    case_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CASE_ROLES))],
) -> Response:
    key = idempotency_key(request)
    require_if_match(request)
    _, details = await _service_request(request)
    container = get_container(request)
    await UpdateCase(
        container.uow_factory, container.clock, UnitOfWorkIdempotency(container.uow_factory)
    ).execute(_update_command(key, actor, case_id, details))
    case = await _case_or_404(container.uow_factory, case_id)
    return FhirJSONResponse(
        content=validate_outbound(case_to_fhir(case)),
        status_code=200,
        headers={"ETag": ETAG_OPEN},
    )


@router.post("/ServiceRequest/{case_id}/$close")
async def close_case(
    case_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CASE_ROLES))],
) -> Response:
    key = idempotency_key(request)
    grouped = _parameters(await _json(request))
    try:
        outcome = Outcome(_code(_one(grouped, "outcome"), "outcome"))
    except ValueError:
        raise ValidationFailed("outcome", "is not a known outcome") from None
    best = _one(grouped, "bestFitNotUsed")
    best_fit = None
    if best is not None:
        try:
            best_fit = BestFitNotUsedReason(_code(best, "bestFitNotUsed"))
        except ValueError:
            raise ValidationFailed("bestFitNotUsed", "is not a known reason") from None
    destination = _one(grouped, "destination")
    destination_id = (
        None
        if destination is None
        else _reference_id(destination, "destination", "HealthcareService")
    )
    container = get_container(request)
    await RecordOutcome(
        container.uow_factory, container.clock, UnitOfWorkIdempotency(container.uow_factory)
    ).execute(
        RecordOutcomeCommand(
            idempotency_key=key,
            actor=actor,
            case_id=case_id,
            outcome=outcome,
            destination_service_id=destination_id,
            best_fit_not_used=best_fit,
        )
    )
    case = await _case_or_404(container.uow_factory, case_id)
    return FhirJSONResponse(content=validate_outbound(case_to_fhir(case)), status_code=200)


def _option_to_part(option: Any) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [
        {"name": "serviceId", "valueString": option.service_id},
        {"name": "name", "valueString": option.name},
        {"name": "status", "valueCode": option.status.value},
        {"name": "criteriaVersion", "valueInteger": option.criteria_version},
    ]
    if option.effective_available is not None:
        parts.append({"name": "effectiveAvailable", "valueInteger": option.effective_available})
    if option.travel is not None:
        parts.append({"name": "travelLow", "valueInteger": option.travel.low_minutes})
        parts.append({"name": "travelHigh", "valueInteger": option.travel.high_minutes})
        parts.append({"name": "travelSource", "valueString": option.travel.source})
    if option.data_age is not None:
        parts.append(
            {"name": "dataAgeSeconds", "valueInteger": int(option.data_age.total_seconds())}
        )
    parts.extend({"name": "fits", "valueString": fit} for fit in option.fits)
    parts.extend({"name": "checks", "valueString": check} for check in option.warnings)
    return {"name": "option", "part": parts}


def _filter_to_fhir(result: FilterOptionsResult) -> dict[str, Any]:
    parameters: list[dict[str, Any]] = [_option_to_part(o) for o in result.options]
    parameters.extend(
        {
            "name": "notSuitable",
            "part": [
                {"name": "serviceId", "valueString": item.service_id},
                {"name": "name", "valueString": item.name},
                {"name": "reason", "valueString": item.reason},
            ],
        }
        for item in result.not_suitable
    )
    return {"resourceType": "Parameters", "parameter": parameters}


@router.post("/HealthcareService/$filter-options")
async def filter_options(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CASE_ROLES))],
) -> Response:
    key = idempotency_key(request)
    grouped = _parameters(await _json(request))
    case_id = _reference_id(_one(grouped, "case"), "case", "ServiceRequest")
    container = get_container(request)
    result = await FilterOptions(
        container.uow_factory,
        container.clock,
        QueryBoard(container.uow_factory, container.clock),
        container.postcodes,
        container.travel,
    ).execute(FilterOptionsCommand(key, actor, case_id))
    return FhirJSONResponse(content=_filter_to_fhir(result), status_code=200)


@router.post("/HealthcareService/{service_id}/$advisor-phoned")
async def advisor_phoned(
    service_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CASE_ROLES))],
) -> Response:
    key = idempotency_key(request)
    grouped = _parameters(await _json(request))
    value_item = _one(grouped, "value")
    value = None if value_item is None else value_item.get("valueInteger")
    told = _code(_one(grouped, "status"), "status")
    if told not in PHONED_ANSWERS:
        raise ValidationFailed("status", "must be accepting, limited or not-accepting")
    case_id = _reference_id(_one(grouped, "case"), "case", "ServiceRequest")
    container = get_container(request)
    use_case = RecordAdvisorPhoned(
        ReportCapacity(
            container.uow_factory,
            container.clock,
            container.ids,
            UnitOfWorkIdempotency(container.uow_factory),
        ),
        container.uow_factory,
    )
    result = await use_case.execute(
        RecordAdvisorPhonedCommand(
            idempotency_key=key,
            actor=actor,
            service_id=service_id,
            told=cast(PhonedAnswer, told),
            value=value,
            case_id=case_id,
        )
    )
    async with container.uow_factory() as uow:
        stored = await uow.capacity.get(result.report_id)
    if stored is None:
        raise RuntimeError("the report that was just stored cannot be read")
    return FhirJSONResponse(
        content={"resourceType": "Observation", "id": stored.id, "valueInteger": stored.value},
        status_code=201,
    )


@router.post("/HealthcareService/{service_id}/$declined")
async def declined(
    service_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CASE_ROLES))],
) -> Response:
    key = idempotency_key(request)
    grouped = _parameters(await _json(request))
    try:
        reason = DeclineReason(_code(_one(grouped, "reason"), "reason"))
    except ValueError:
        raise ValidationFailed("reason", "is not a known reason") from None
    case_id = _reference_id(_one(grouped, "case"), "case", "ServiceRequest")
    container = get_container(request)
    result = await RecordDecline(
        container.uow_factory,
        container.clock,
        container.ids,
        UnitOfWorkIdempotency(container.uow_factory),
        QueryBoard(container.uow_factory, container.clock),
    ).execute(
        RecordDeclineCommand(
            idempotency_key=key,
            actor=actor,
            case_id=case_id,
            service_id=service_id,
            reason=reason,
        )
    )
    return FhirJSONResponse(
        content={
            "resourceType": "Parameters",
            "parameter": [
                {"name": "reason", "valueCode": result.reason.value},
                {"name": "at", "valueInstant": result.at.isoformat()},
            ],
        },
        status_code=200,
    )


__all__ = ["router", "UnitOfWorkFactory"]
