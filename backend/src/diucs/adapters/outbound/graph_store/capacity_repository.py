"""Capacity reports on Neo4j: CapacityReport <-> FHIR Observation (P01).

A report is an Observation with status final, focus on its service, the measure as its code, the
report source as its method, and the figure as a whole-number valueQuantity with a UCUM unit.
A confirmation has derivedFrom (the report it confirms). Reports are never updated: a second add
with the same id is a Conflict (the store would refuse an existing Observation as NotAllowed, so
the check runs first and a race that reaches the store is mapped to Conflict too).

"Latest" is the greatest effectiveDateTime. The FHIR `issued` instant is not on CapacityReport, so
ties on effectiveDateTime fall back to the store's lastUpdated (the write time, whole seconds).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_repository import (
    codeable_from_fhir,
    codeable_to_fhir,
)
from diucs.domain.codes import (
    BASE_URL,
    Measure,
    ReportSource,
    ReportType,
    parse_code,
)
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.capacity import CapacityReport

_UCUM_SYSTEM: Final = "http://unitsofmeasure.org"
_UCUM_UNITS: Final[dict[Measure, str]] = {
    Measure.REFERRALS_ACCEPTABLE: "{referral}",
    Measure.FREE_BEDS: "{bed}",
    Measure.FREE_SLOTS: "{slot}",
    Measure.OCCUPIED_PATIENTS: "{patient}",
    Measure.PACKAGES_FREE: "{package}",
}
_REPORT_TYPE_URL: Final = f"{BASE_URL}StructureDefinition/reportType"
_OBSERVATION: Final = "Observation"
_SERVICE: Final = "HealthcareService"
_PRACTITIONER_ROLE: Final = "PractitionerRole"

# The latest observation of one service: greatest effectiveDateTime, ties by write time.
_LATEST_OF_SERVICE: Final = (
    "CALL { WITH s MATCH (o:Observation)-[:FOCUS]->(s) "
    "RETURN o.id AS obs ORDER BY o.effectiveDateTime DESC, o.lastUpdated DESC LIMIT 1 }"
)

_QUERIES: Final = (
    NamedQuery(
        id="Q-CAP-LATEST",
        cypher=(f"MATCH (s:HealthcareService {{key: $key}}) {_LATEST_OF_SERVICE} RETURN obs"),
        mode="read",
    ),
    NamedQuery(
        id="Q-CAP-LATEST-FOR",
        cypher=(
            "UNWIND $keys AS k MATCH (s:HealthcareService {key: k}) "
            f"{_LATEST_OF_SERVICE} RETURN s.id AS service, obs"
        ),
        mode="read",
    ),
    NamedQuery(
        id="Q-CAP-SINCE",
        cypher=(
            "MATCH (o:Observation)-[:FOCUS]->(s:HealthcareService {key: $key}) "
            "WHERE o.effectiveDateTime >= $since "
            "RETURN o.id AS obs ORDER BY o.effectiveDateTime ASC, o.lastUpdated ASC"
        ),
        mode="read",
    ),
    NamedQuery(
        id="Q-SVC-LAST-REPORT",
        cypher=(
            "MATCH (s:HealthcareService {active: true}) "
            "OPTIONAL MATCH (o:Observation)-[:FOCUS]->(s) "
            "WITH s, max(o.effectiveDateTime) AS last "
            "RETURN s.id AS id, last ORDER BY s.name"
        ),
        mode="read",
    ),
)
for _query in _QUERIES:
    if _query.id not in REGISTRY.ids():
        REGISTRY.register(_query)


def _utc_text(instant: datetime) -> str:
    """FHIR instant text in UTC with a Z. Fractions are kept, without trailing zeros, because the
    store refuses a fraction that would not read back identically (DEC-053 item 2)."""
    utc = instant.astimezone(UTC)
    text = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if utc.microsecond:
        text += f".{utc.microsecond:06d}".rstrip("0")
    return f"{text}Z"


def _reference_id(reference: Any, resource_type: str, field: str) -> str:
    prefix = f"{resource_type}/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise ValidationFailed(field, f"must reference a {resource_type}")
    return reference[len(prefix) :]


def _single(entries: Any, field: str) -> Any:
    """The one entry of a single-valued list element, or None if the element is absent."""
    if entries is None:
        return None
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValidationFailed(field, "one entry is allowed")
    return entries[0]


def report_to_fhir(report: CapacityReport) -> dict[str, Any]:
    """The Observation for a report. No meta: the store sets it."""
    unit = _UCUM_UNITS[report.measure]
    resource: dict[str, Any] = {
        "resourceType": _OBSERVATION,
        "id": report.id,
        "status": "final",
        "code": codeable_to_fhir(report.measure),
        "focus": {"reference": f"{_SERVICE}/{report.service_id}"},
        "method": codeable_to_fhir(report.source),
        "effectiveDateTime": _utc_text(report.effective_at),
        "valueQuantity": {
            "value": report.value,
            "unit": unit,
            "system": _UCUM_SYSTEM,
            "code": unit,
        },
        "extension": [{"url": _REPORT_TYPE_URL, "valueString": report.report_type.value}],
    }
    if report.performer_role_id is not None:
        resource["performer"] = [{"reference": f"{_PRACTITIONER_ROLE}/{report.performer_role_id}"}]
    if report.derived_from is not None:
        resource["derivedFrom"] = [{"reference": f"{_OBSERVATION}/{report.derived_from}"}]
    return resource


def report_from_fhir(resource: dict[str, Any]) -> CapacityReport:
    """The report for an Observation. Refuses a value it does not recognise."""
    extensions = [
        entry["valueString"]
        for entry in resource.get("extension", [])
        if entry.get("url") == _REPORT_TYPE_URL
    ]
    if len(extensions) != 1:
        raise ValidationFailed("reportType", "required, once")
    performer = _single(resource.get("performer"), "performer")
    derived = _single(resource.get("derivedFrom"), "derivedFrom")
    quantity = resource["valueQuantity"]
    return CapacityReport(
        id=resource["id"],
        service_id=_reference_id(resource["focus"]["reference"], _SERVICE, "focus"),
        value=quantity["value"],
        measure=codeable_from_fhir(resource["code"], Measure, "code"),
        effective_at=datetime.fromisoformat(resource["effectiveDateTime"]).astimezone(UTC),
        source=codeable_from_fhir(resource["method"], ReportSource, "method"),
        report_type=parse_code(ReportType, extensions[0]),
        performer_role_id=(
            None
            if performer is None
            else _reference_id(performer["reference"], _PRACTITIONER_ROLE, "performer")
        ),
        derived_from=(
            None
            if derived is None
            else _reference_id(derived["reference"], _OBSERVATION, "derivedFrom")
        ),
    )


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    native: datetime = value.to_native()
    return native.astimezone(UTC)


class Neo4jCapacityRepository:
    """Capacity reports as Observation resources. Built per transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def add(self, report: CapacityReport) -> None:
        if not await self._store.exists(_SERVICE, report.service_id):
            raise NotFound(f"{_SERVICE}/{report.service_id}")
        if await self._store.exists(_OBSERVATION, report.id):
            raise Conflict(f"{_OBSERVATION}/{report.id} already exists: reports are not updated")
        try:
            await self._store.put(report_to_fhir(report), None)
        except NotAllowed as error:  # a racing add won between the check and the write
            raise Conflict(f"{_OBSERVATION}/{report.id} already exists") from error

    async def _load(self, observation_id: str) -> CapacityReport:
        resource = await self._store.get(_OBSERVATION, observation_id)
        if resource is None:
            raise NotFound(f"{_OBSERVATION}/{observation_id}")
        return report_from_fhir(resource)

    async def latest(self, service_id: str) -> CapacityReport | None:
        rows = await run_query(self._tx, "Q-CAP-LATEST", key=f"{_SERVICE}/{service_id}")
        if not rows:
            return None
        return await self._load(str(rows[0]["obs"]))

    async def latest_for_services(self, service_ids: Sequence[str]) -> dict[str, CapacityReport]:
        keys = [f"{_SERVICE}/{service_id}" for service_id in service_ids]
        rows = await run_query(self._tx, "Q-CAP-LATEST-FOR", keys=keys)
        return {str(row["service"]): await self._load(str(row["obs"])) for row in rows}

    async def reports_since(self, service_id: str, since: datetime) -> list[CapacityReport]:
        rows = await run_query(
            self._tx, "Q-CAP-SINCE", key=f"{_SERVICE}/{service_id}", since=since.astimezone(UTC)
        )
        return [await self._load(str(row["obs"])) for row in rows]

    async def last_report_times(self) -> dict[str, datetime | None]:
        rows = await run_query(self._tx, "Q-SVC-LAST-REPORT")
        return {str(row["id"]): _as_utc(row["last"]) for row in rows}

    async def trailing_confirmations(self, service_id: str) -> int:
        return -1  # RED STUB (U02)
