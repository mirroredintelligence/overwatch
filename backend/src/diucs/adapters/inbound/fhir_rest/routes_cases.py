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
from typing import Annotated, Any, Final, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from diucs.adapters.inbound.fhir_rest import capability
from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
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
    AgeBand,
    BestFitNotUsedReason,
    DeclineReason,
    NeedCategory,
    Outcome,
    ReferrerType,
    Role,
    Urgency,
    code_system_url,
)
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.case import Case, priority_for

CASE_ROLES: Final = (Role.ADVISOR, Role.CLINICAL)
AGE_BAND_EXTENSION: Final = f"{BASE_URL}StructureDefinition/age-band"
REFERRER_EXTENSION: Final = f"{BASE_URL}StructureDefinition/referrer-type"
REFUSED_PATIENT_ELEMENTS: Final = ("name", "identifier", "birthDate", "telecom")
PATIENT_REFUSED: Final = "No patient names or identifiers are stored."
NO_SUCH_CASE: Final = "no case with this id"
URGENT: Final = "urgent"
ROUTINE: Final = "routine"
ETAG_OPEN: Final = 'W/"case"'

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


def _refuse_patient_details(service_request: dict[str, Any]) -> None:
    """A stub Patient carries an age band and a postcode only (R07)."""
    for contained in service_request.get("contained", []):
        if contained.get("resourceType") != "Patient":
            continue
        for element in REFUSED_PATIENT_ELEMENTS:
            if element in contained:
                raise ValidationFailed(element, PATIENT_REFUSED)


def _postcode(service_request: dict[str, Any]) -> str | None:
    for contained in service_request.get("contained", []):
        if contained.get("resourceType") == "Patient":
            for address in contained.get("address", []):
                postal = address.get("postalCode")
                if isinstance(postal, str):
                    return postal
    return None


def _age_band(service_request: dict[str, Any]) -> AgeBand | None:
    for contained in service_request.get("contained", []):
        if contained.get("resourceType") != "Patient":
            continue
        for extension in contained.get("extension", []):
            if extension.get("url") == AGE_BAND_EXTENSION:
                return AgeBand(extension["valueCode"])
    return None


def _referrer(service_request: dict[str, Any]) -> ReferrerType:
    for extension in service_request.get("extension", []):
        if extension.get("url") == REFERRER_EXTENSION:
            return ReferrerType(extension["valueCode"])
    raise ValidationFailed("referrer-type", "is required")


def _needs(service_request: dict[str, Any]) -> tuple[NeedCategory, ...]:
    needs: list[NeedCategory] = []
    system = code_system_url("need-category")
    for concept in service_request.get("reasonCode", []):
        for coding in concept.get("coding", []):
            if coding.get("system") == system:
                needs.append(NeedCategory(coding["code"]))
    return tuple(needs)


def _urgency(service_request: dict[str, Any]) -> Urgency | None:
    priority = service_request.get("priority")
    if priority is None:
        return None
    if priority == URGENT:
        return Urgency.WITHIN_2_HRS
    if priority == ROUTINE:
        return Urgency.TODAY
    raise ValidationFailed("priority", "must be urgent or routine")


def _case_to_fhir(case: Case) -> dict[str, Any]:
    """The ServiceRequest of a case. Open: the district and age band and needs are shown. Closed:
    the stored case holds none of them, so none are shown (DEC-398)."""
    patient: dict[str, Any] = {"resourceType": "Patient", "id": "p"}
    if case.postcode is not None:
        patient["address"] = [{"postalCode": case.postcode}]
    if case.age_band is not None:
        patient["extension"] = [{"url": AGE_BAND_EXTENSION, "valueCode": case.age_band.value}]
    request: dict[str, Any] = {
        "resourceType": "ServiceRequest",
        "id": case.id,
        "status": "active" if case.closed_at is None else "completed",
        "intent": "plan",
        "subject": {"reference": "#p"},
        "contained": [patient],
        "extension": [{"url": REFERRER_EXTENSION, "valueCode": case.referrer_type.value}],
    }
    if case.urgency is not None:
        request["priority"] = priority_for(case.urgency)
    if case.needs:
        system = code_system_url("need-category")
        request["reasonCode"] = [
            {"coding": [{"system": system, "code": need.value}]} for need in case.needs
        ]
    if case.outcome is not None:
        request["outcome"] = {"valueCode": case.outcome.value}
    return request


async def _case_or_404(factory: UnitOfWorkFactory, case_id: str) -> Case:
    async with factory() as uow:
        case = await uow.cases.get(case_id)
    if case is None:
        raise NotFound(NO_SUCH_CASE)
    return case


@router.post("/ServiceRequest")
async def open_case(
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CASE_ROLES))],
) -> Response:
    key = idempotency_key(request)
    body = await _json(request)
    if not isinstance(body, dict) or body.get("resourceType") != "ServiceRequest":
        raise ValidationFailed("body", "must be a ServiceRequest resource")
    _refuse_patient_details(body)
    container = get_container(request)
    opened = await OpenCase(
        container.uow_factory,
        container.clock,
        container.ids,
        UnitOfWorkIdempotency(container.uow_factory),
        container.rng,
    ).execute(OpenCaseCommand(key, actor, _referrer(body)))
    await UpdateCase(
        container.uow_factory, container.clock, UnitOfWorkIdempotency(container.uow_factory)
    ).execute(
        UpdateCaseCommand(
            idempotency_key=f"{key}:details",
            actor=actor,
            case_id=opened.case_id,
            age_band=_age_band(body),
            postcode=_postcode(body),
            needs=_needs(body),
            urgency=_urgency(body),
        )
    )
    case = await _case_or_404(container.uow_factory, opened.case_id)
    return FhirJSONResponse(
        content=validate_outbound(_case_to_fhir(case)),
        status_code=201,
        headers={"Location": f"/fhir/ServiceRequest/{case.id}", "ETag": ETAG_OPEN},
    )


@router.put("/ServiceRequest/{case_id}")
async def update_case(
    case_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*CASE_ROLES))],
) -> Response:
    key = idempotency_key(request)
    require_if_match(request)
    body = await _json(request)
    if not isinstance(body, dict) or body.get("resourceType") != "ServiceRequest":
        raise ValidationFailed("body", "must be a ServiceRequest resource")
    _refuse_patient_details(body)
    container = get_container(request)
    await UpdateCase(
        container.uow_factory, container.clock, UnitOfWorkIdempotency(container.uow_factory)
    ).execute(
        UpdateCaseCommand(
            idempotency_key=key,
            actor=actor,
            case_id=case_id,
            postcode=_postcode(body),
            needs=_needs(body),
            urgency=_urgency(body),
        )
    )
    case = await _case_or_404(container.uow_factory, case_id)
    return FhirJSONResponse(
        content=validate_outbound(_case_to_fhir(case)),
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
    return FhirJSONResponse(content=validate_outbound(_case_to_fhir(case)), status_code=200)


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
