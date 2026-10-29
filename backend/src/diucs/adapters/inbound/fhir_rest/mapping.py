"""Pure mapping between application results and FHIR resources for the FHIR API (R05).

board_to_parameters turns a Board into an R4B Parameters resource (contracts.md, "HTTP surface"):
one `entry` parameter per service whose parts are the BoardEntry fields in camelCase, then
`pressure`, `allLimitedOrWorse` and `generatedAt`. A null field is left out, and so is an empty
comment, because FHIR has no empty string (DEC-145 item 3). Times are UTC with a Z suffix.

report_to_fhir turns a stored capacity report into an R4B Observation. The graph store keeps its
own form of the same report (`focus` as one reference), so the two are separate on purpose: this one
is valid R4B for a client.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.idempotency import format_instant
from diucs.application.use_cases.query_board import Board, BoardEntry
from diucs.application.use_cases.report_capacity import ReportCapacityCommand
from diucs.domain.codes import BASE_URL, Measure, ReportSource, coding_for
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile

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


# R04 stubs (red commit): the names exist and answer wrongly, so the tests fail on their assertions.
API_SOURCES: Final[frozenset[ReportSource]] = frozenset()


@dataclass(frozen=True, slots=True)
class ReportRequest:
    command: ReportCapacityCommand
    measure: Measure
    unit: str


def ucum_unit(measure: Measure) -> str:
    return ""


def service_to_fhir(profile: ServiceProfile) -> dict[str, Any]:
    return {}


def search_bundle(
    resources: Sequence[dict[str, Any]],
    *,
    total: int,
    self_url: str,
    next_url: str | None = None,
) -> dict[str, Any]:
    return {}


def report_request_from_fhir(resource: object, actor: Actor, key: str) -> ReportRequest:
    raise NotImplementedError


def validate_outbound(resource: dict[str, Any]) -> dict[str, Any]:
    return dict(resource)
