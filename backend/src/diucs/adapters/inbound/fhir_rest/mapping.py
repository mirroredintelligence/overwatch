"""Pure mapping between application results and FHIR resources for the FHIR API (R05).

board_to_parameters turns a Board into an R4B Parameters resource (contracts.md, "HTTP surface"):
one `entry` parameter per service whose parts are the BoardEntry fields in camelCase, then
`pressure`, `allLimitedOrWorse` and `generatedAt`. A null field is left out, and so is an empty
comment, because FHIR has no empty string (DEC-145 item 3). Times are UTC with a Z suffix.

report_to_fhir turns a stored capacity report into an R4B Observation. The graph store keeps its
own form of the same report (`focus` as one reference), so the two are separate on purpose: this one
is valid R4B for a client.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, NoReturn

from fhir.resources.R4B import get_fhir_model_class
from pydantic import ValidationError

from diucs.application.actor import Actor
from diucs.application.idempotency import format_instant
from diucs.application.use_cases.query_board import Board, BoardEntry
from diucs.application.use_cases.report_capacity import ReportCapacityCommand
from diucs.domain.codes import (
    BASE_URL,
    CODE_SYSTEM_NAMES,
    Measure,
    ReportSource,
    code_system_url,
    coding_for,
    parse_code,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import AvailableTime, ServiceProfile

_UCUM_SYSTEM: Final = "http://unitsofmeasure.org"
_UCUM_UNITS: Final[dict[Measure, str]] = {
    Measure.REFERRALS_ACCEPTABLE: "{referral}",
    Measure.FREE_BEDS: "{bed}",
    Measure.FREE_SLOTS: "{slot}",
    Measure.OCCUPIED_PATIENTS: "{patient}",
    Measure.PACKAGES_FREE: "{package}",
}
_REPORT_TYPE_URL: Final = f"{BASE_URL}StructureDefinition/reportType"


def _string(name: str, value: str) -> dict[str, Any]:
    return {"name": name, "valueString": value}


def _code(name: str, value: str) -> dict[str, Any]:
    return {"name": name, "valueCode": value}


def _integer(name: str, value: int) -> dict[str, Any]:
    return {"name": name, "valueInteger": value}


def _date_time(name: str, value: datetime) -> dict[str, Any]:
    return {"name": name, "valueDateTime": format_instant(value)}


def _entry(entry: BoardEntry) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [
        _string("serviceId", entry.service_id),
        _string("name", entry.name),
        _code("category", entry.category.value),
        _code("status", entry.status.value),
    ]
    if entry.effective_available is not None:
        parts.append(_integer("effectiveAvailable", entry.effective_available))
    if entry.over_by is not None:
        parts.append(_integer("overBy", entry.over_by))
    if entry.used is not None:
        parts.append(_integer("used", entry.used))
    parts.append(_integer("established", entry.established))
    parts.append(_integer("pending", entry.pending))
    parts.append(_string("unitLabel", entry.unit_label))
    if entry.comment:
        parts.append(_string("comment", entry.comment))
    if entry.reported_at is not None:
        parts.append(_date_time("reportedAt", entry.reported_at))
    if entry.next_due_at is not None:
        parts.append(_date_time("nextDueAt", entry.next_due_at))
    if entry.was_due_at is not None:
        parts.append(_date_time("wasDueAt", entry.was_due_at))
    return {"name": "entry", "part": parts}


def board_to_parameters(board: Board) -> dict[str, Any]:
    parameters = [_entry(entry) for entry in board.entries]
    parameters.append(_code("pressure", board.pressure.value))
    parameters.append({"name": "allLimitedOrWorse", "valueBoolean": board.all_limited_or_worse})
    parameters.append(_date_time("generatedAt", board.generated_at))
    return {"resourceType": "Parameters", "parameter": parameters}


def report_to_fhir(report: CapacityReport) -> dict[str, Any]:
    """The Observation for a report: the figure as a whole-number quantity, the service as focus,
    and, for a confirmation, the report it confirms as derivedFrom."""
    unit = _UCUM_UNITS[report.measure]
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "id": report.id,
        "status": "final",
        "code": _codeable(report.measure),
        "focus": [{"reference": f"HealthcareService/{report.service_id}"}],
        "method": _codeable(report.source),
        "effectiveDateTime": format_instant(report.effective_at),
        "valueQuantity": {
            "value": report.value,
            "unit": unit,
            "system": _UCUM_SYSTEM,
            "code": unit,
        },
        "extension": [{"url": _REPORT_TYPE_URL, "valueString": report.report_type.value}],
    }
    if report.performer_role_id is not None:
        resource["performer"] = [{"reference": f"PractitionerRole/{report.performer_role_id}"}]
    if report.derived_from is not None:
        resource["derivedFrom"] = [{"reference": f"Observation/{report.derived_from}"}]
    return resource


def _codeable(member: StrEnum) -> dict[str, Any]:
    coding = coding_for(member)
    return {"coding": [{"system": coding.system, "code": coding.code, "display": coding.display}]}


# R04: HealthcareService, search bundles and the report request.

FHIR_ID_PATTERN: Final = r"[A-Za-z0-9.\-]{1,64}"
_FHIR_ID: Final = re.compile(FHIR_ID_PATTERN)
_SERVICE_PREFIX: Final = "HealthcareService/"
_INSTANT: Final = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,9})?(Z|[+-][0-9]{2}:[0-9]{2})"
)
_DAY_CODES: Final = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_TIME_FORMAT: Final = "%H:%M:%S"
API_SOURCES: Final[frozenset[ReportSource]] = frozenset(
    {ReportSource.APP, ReportSource.ADVISOR_PHONED}
)
"""The sources a report sent over this API may name. Text and link reports arrive on their own
channels, so an API caller cannot label a report as one of those (provenance, DEC-168 item 6)."""
_REPORT_ELEMENTS: Final = frozenset(
    {
        "resourceType",
        "id",
        "meta",
        "status",
        "code",
        "focus",
        "valueQuantity",
        "method",
        "effectiveDateTime",
    }
)
_QUANTITY_ELEMENTS: Final = frozenset({"value", "unit", "system", "code"})


def ucum_unit(measure: Measure) -> str:
    """The UCUM annotation of a measure: {referral}, {bed}, {slot}, {patient} or {package}."""
    return _UCUM_UNITS[measure]


def _extension(name: str, key: str, value: Any) -> dict[str, Any]:
    return {"url": f"{BASE_URL}StructureDefinition/{name}", key: value}


def _window(window: AvailableTime) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "daysOfWeek": [_DAY_CODES[day] for day in sorted(window.days)],
        "allDay": window.all_day,
    }
    if window.start is not None and window.end is not None:
        entry["availableStartTime"] = window.start.strftime(_TIME_FORMAT)
        entry["availableEndTime"] = window.end.strftime(_TIME_FORMAT)
    return entry


def service_to_fhir(profile: ServiceProfile) -> dict[str, Any]:
    """The R4B HealthcareService for a profile: category as a list of one concept (R4B), the
    profile values as the registered extensions, no meta (the route sets the version)."""
    resource: dict[str, Any] = {
        "resourceType": "HealthcareService",
        "id": profile.id,
        "active": profile.active,
        "name": profile.name,
        "category": [_codeable(profile.category)],
        "availableTime": [_window(window) for window in profile.available_times],
        "extension": [
            _extension("establishedCapacity", "valueInteger", profile.established_capacity),
            _extension("canExceedEstablished", "valueBoolean", profile.can_exceed_established),
            _extension("usualRangeMin", "valueInteger", profile.usual_range[0]),
            _extension("usualRangeMax", "valueInteger", profile.usual_range[1]),
            _extension("reportCadence", "valueString", profile.cadence.value),
            _extension("limitedLevelPercent", "valueInteger", profile.limited_level_percent),
            _extension("measure", "valueString", profile.measure.value),
            _extension("unitLabel", "valueString", profile.unit_label),
            _extension("channel", "valueString", profile.channel.value),
        ],
    }
    if profile.comment:
        resource["comment"] = profile.comment
    return resource


def search_bundle(
    resources: Sequence[dict[str, Any]],
    *,
    total: int,
    self_url: str,
    next_url: str | None = None,
) -> dict[str, Any]:
    """A searchset Bundle: every resource a match, the total of the whole search, a self link and,
    when there is another page, a next link. An empty result has no `entry` (FHIR has no empty
    list). The links are relative and built only from validated parameters."""
    links = [{"relation": "self", "url": self_url}]
    if next_url is not None:
        links.append({"relation": "next", "url": next_url})
    bundle: dict[str, Any] = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": total,
        "link": links,
    }
    if resources:
        bundle["entry"] = [{"resource": r, "search": {"mode": "match"}} for r in resources]
    return bundle


def validate_outbound(resource: dict[str, Any]) -> dict[str, Any]:
    """The resource, after it has been checked against its FHIR R4B model. A resource this API
    builds that is not valid is a programming error: it answers 500 and carries nothing of the
    resource (the pydantic message can quote values)."""
    try:
        get_fhir_model_class(resource["resourceType"]).model_validate(resource)
    except ValidationError, LookupError:
        raise RuntimeError("an outgoing resource is not valid FHIR R4B") from None
    return resource


@dataclass(frozen=True, slots=True)
class ReportRequest:
    """A parsed POST /fhir/Observation: the command for ReportCapacity, and what the sender said
    the report measures, so the route can check it against the service."""

    command: ReportCapacityCommand
    measure: Measure
    unit: str


def _refuse(field: str, message: str) -> NoReturn:
    # Fixed words and a fixed element name: nothing of the request is put in the refusal.
    raise ValidationFailed(f"Observation.{field}" if field else "Observation", message)


def _coded[E: StrEnum](concept: object, enum_cls: type[E], field: str) -> E:
    """The one code of a CodeableConcept, from the code system of `enum_cls`."""
    codings = concept.get("coding") if isinstance(concept, dict) else None
    if not isinstance(codings, list) or len(codings) != 1 or not isinstance(codings[0], dict):
        _refuse(field, "needs exactly one coding")
    coding = codings[0]
    if coding.get("system") != code_system_url(CODE_SYSTEM_NAMES[enum_cls]):
        _refuse(field, "is not from the expected code system")
    code = coding.get("code")
    if not isinstance(code, str):
        _refuse(field, "needs a code")
    try:
        return parse_code(enum_cls, code)
    except ValidationFailed:
        _refuse(field, "is not a known code")


def _focus(resource: dict[str, Any]) -> str:
    focus = resource.get("focus")
    if not isinstance(focus, list) or len(focus) != 1 or not isinstance(focus[0], dict):
        _refuse("focus", "must name the one service reported on")
    reference = focus[0].get("reference")
    if not isinstance(reference, str) or not reference.startswith(_SERVICE_PREFIX):
        _refuse("focus", "must be a HealthcareService reference")
    service_id = reference[len(_SERVICE_PREFIX) :]
    if _FHIR_ID.fullmatch(service_id) is None:
        _refuse("focus", "is not a valid service id")
    return service_id


def _quantity(resource: dict[str, Any]) -> tuple[int, str]:
    quantity = resource.get("valueQuantity")
    if not isinstance(quantity, dict):
        _refuse("valueQuantity", "is required")
    if not set(quantity) <= _QUANTITY_ELEMENTS:
        _refuse("valueQuantity", "has an element that is not accepted")
    value = quantity.get("value")
    if isinstance(value, bool) or not isinstance(value, int):
        _refuse("valueQuantity.value", "must be a whole number")
    if quantity.get("system") != _UCUM_SYSTEM:
        _refuse("valueQuantity.system", "must be the UCUM system")
    unit = quantity.get("code")
    if not isinstance(unit, str):
        _refuse("valueQuantity.code", "must be a UCUM annotation")
    return value, unit


def _effective(resource: dict[str, Any]) -> datetime:
    text = resource.get("effectiveDateTime")
    if not isinstance(text, str) or _INSTANT.fullmatch(text) is None:
        _refuse("effectiveDateTime", "must be a date and time with seconds and a time zone")
    try:
        return datetime.fromisoformat(text).astimezone(UTC)
    except ValueError:
        _refuse("effectiveDateTime", "is not a real date and time")


def report_request_from_fhir(resource: object, actor: Actor, key: str) -> ReportRequest:
    """The command for a POST /fhir/Observation body, or ValidationFailed naming the element.

    Only the elements a capacity report needs are accepted; any other (a performer, a derivedFrom,
    a component, a tenant) is refused rather than dropped, so a sender is never told a report was
    taken as sent when part of it was not. The server gives the report its id and its performer,
    so a client cannot name them. The actor and key come from the token and the header."""
    if not isinstance(resource, dict):
        _refuse("", "must be a JSON object")
    if resource.get("resourceType") != "Observation":
        _refuse("resourceType", "must be Observation")
    if not set(resource) <= _REPORT_ELEMENTS:
        _refuse("", "has an element that is not accepted")
    if resource.get("status") != "final":
        _refuse("status", "must be final")
    measure = _coded(resource.get("code"), Measure, "code")
    service_id = _focus(resource)
    value, unit = _quantity(resource)
    source = _coded(resource.get("method"), ReportSource, "method")
    if source not in API_SOURCES:
        _refuse("method", "is not a source this API carries")
    effective = _effective(resource)
    command = ReportCapacityCommand(
        idempotency_key=key,
        actor=actor,
        service_id=service_id,
        value=value,
        source=source,
        effective_at=effective,
    )
    return ReportRequest(command=command, measure=measure, unit=unit)
