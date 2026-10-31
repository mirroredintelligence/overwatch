"""Bookings on Neo4j: Booking <-> FHIR Task code booking-request (P02).

The mapping is pure (booking_to_fhir, booking_from_fhir). The status mapping is D13's to_fhir and
from_fhir; this module does not restate it. The repository stores the Task through the G05 store,
so the graph holds the decomposed properties and relationships and no json (DEC-001).

Two derived properties sit on the Task node, written after the store's put in the same
transaction: `businessStatus` (the status code, so Q-BOOK-PENDING can match it) and `reference`
(a copy of the identifier value). The store reads them back as plain properties, and
read_task_fhir turns them into the FHIR form again (DEC-063).

Booking reference: the Task identifier with system BOOKING_REFERENCE_SYSTEM. One open booking per
service is the use case's rule (U17), not this repository's.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

from diucs.adapters.fhir_shared.booking_task import (
    _CONFIRMED_AT,
    _OUTPUT_TYPE_SYSTEM,
    _REASON,
    _TASK,
    BOOKING_REFERENCE_SYSTEM,
    booking_to_fhir,
)
from diucs.adapters.outbound.graph_store.driver import ScopedTx, run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_repository import codeable_to_fhir
from diucs.adapters.outbound.graph_store.service_scenarios import SCENARIOS
from diucs.adapters.outbound.graph_store.week_scenarios import WEEK_SCENARIOS
from diucs.domain.codes import code_system_url
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.booking import Booking
from diucs.domain.rules.booking_state import from_fhir

_BUSINESS_STATUS: Final = "businessStatus"
_REFERENCE: Final = "reference"

_PENDING: Final = NamedQuery(
    id="Q-BOOK-PENDING",
    cypher=(
        "MATCH (t:Task {businessStatus: 'requested', tenantId: $tenant})"
        "-[:OWNER]->(:HealthcareService {id: $id, tenantId: $tenant}) "
        "RETURN count(t) AS pending"
    ),
    mode="read",
    scenario=SCENARIOS["Q-BOOK-PENDING"],
)
_OPEN_FOR: Final = NamedQuery(
    id="Q-BOOK-OPEN-FOR",
    cypher=(
        "MATCH (t:Task {businessStatus: 'requested', tenantId: $tenant})"
        "-[:OWNER]->(s:HealthcareService {tenantId: $tenant}) "
        "WHERE s.id IN $ids RETURN s.id AS serviceId, t.id AS id "
        "ORDER BY t.authoredOn, t.id"
    ),
    mode="read",
    scenario=SCENARIOS["Q-BOOK-OPEN-FOR"],
)
_CONFIRMED_FOR: Final = NamedQuery(
    id="Q-BOOK-CONFIRMED-SINCE",
    cypher=(
        "MATCH (t:Task {businessStatus: 'confirmed', tenantId: $tenant})"
        "-[:OWNER]->(:HealthcareService {id: $id, tenantId: $tenant}) "
        "RETURN t.id AS id ORDER BY t.id"
    ),
    mode="read",
    scenario=SCENARIOS["Q-BOOK-CONFIRMED-SINCE"],
)
_CONFIRMED_FOR_SERVICES: Final = NamedQuery(
    id="Q-BOOK-CONFIRMED-FOR",
    cypher=(
        "MATCH (t:Task {businessStatus: 'confirmed', tenantId: $tenant})"
        "-[:OWNER]->(s:HealthcareService {tenantId: $tenant}) "
        "WHERE s.id IN $ids "
        "MATCH (t)-[:HAS_OUTPUT]->(o:Task_Output {tenantId: $tenant})-[:TYPE]->"
        "(c:Concept {code: $code, system: $system, tenantId: $tenant}) "
        "RETURN s.id AS serviceId, o.valueDateTime AS confirmedAt "
        "ORDER BY s.id, o.valueDateTime"
    ),
    mode="read",
    scenario=SCENARIOS["Q-BOOK-CONFIRMED-FOR"],
)
# The most recent booking of each service, by its authored time. Booking Tasks are the ones that
# carry a reference; the order is kept by collect after an ORDER BY in the same WITH (U22).
_LATEST_FOR: Final = NamedQuery(
    id="Q-BOOK-LATEST-FOR",
    cypher=(
        "MATCH (t:Task {tenantId: $tenant})-[:OWNER]->(s:HealthcareService {tenantId: $tenant}) "
        "WHERE s.id IN $ids AND t.reference IS NOT NULL "
        "WITH s.id AS serviceId, t ORDER BY t.authoredOn DESC, t.id "
        "WITH serviceId, collect(t.id)[0] AS id "
        "RETURN serviceId, id ORDER BY serviceId"
    ),
    mode="read",
    scenario=SCENARIOS["Q-BOOK-LATEST-FOR"],
)
_FOR_CASE: Final = NamedQuery(
    id="Q-BOOK-FOR-CASE",
    cypher=(
        "MATCH (t:Task {tenantId: $tenant})-[:FOCUS]->(r:ServiceRequest {id: $case, "
        "tenantId: $tenant}) WHERE t.reference IS NOT NULL "
        "RETURN t.id AS id ORDER BY t.authoredOn DESC, t.id"
    ),
    mode="read",
    scenario=SCENARIOS["Q-BOOK-FOR-CASE"],
)
_BY_REF: Final = NamedQuery(
    id="Q-BOOK-BY-REF",
    cypher=(
        "MATCH (t:Task {reference: $reference, tenantId: $tenant}) RETURN t.id AS id "
        "ORDER BY t.authoredOn DESC, t.id LIMIT 1"
    ),
    mode="read",
    scenario=SCENARIOS["Q-BOOK-BY-REF"],
)
_SET_PROPS: Final = NamedQuery(
    id="Q-BOOK-SET-PROPS",
    cypher=(
        "MATCH (t:Task {key: $key, tenantId: $tenant}) "
        "SET t.businessStatus = $businessStatus, t.reference = $reference "
        "RETURN count(t) AS set"
    ),
    mode="write",
    scenario=SCENARIOS["Q-BOOK-SET-PROPS"],
)


def _register(query: NamedQuery) -> None:
    if query.id not in REGISTRY.ids():
        REGISTRY.register(query)


for _query in (
    _PENDING,
    _OPEN_FOR,
    _LATEST_FOR,
    _CONFIRMED_FOR,
    _CONFIRMED_FOR_SERVICES,
    _FOR_CASE,
    _BY_REF,
    _SET_PROPS,
):
    _register(_query)


def _as_utc_instant(value: Any) -> datetime:
    """A stored Neo4j datetime as an aware UTC datetime (the driver's own type, or text)."""
    if isinstance(value, str):
        return _instant("confirmedAt", value)
    native: datetime = value.to_native()
    return native.astimezone(UTC)


def _instant(field: str, text: Any) -> datetime:
    if not isinstance(text, str):
        raise ValidationFailed(field, "must be a FHIR datetime")
    try:
        return datetime.fromisoformat(text).astimezone(UTC)
    except ValueError:
        raise ValidationFailed(field, "not a FHIR datetime") from None


def _coded(member_codeable: dict[str, Any]) -> str:
    """The one code of a CodeableConcept from the booking business-status system."""
    codings = member_codeable.get("coding")
    if not isinstance(codings, list) or len(codings) != 1:
        raise ValidationFailed("businessStatus", "needs exactly one coding")
    coding = codings[0]
    if coding.get("system") != code_system_url("booking-business-status"):
        raise ValidationFailed("businessStatus", "not from the booking status code system")
    code = coding.get("code")
    if not isinstance(code, str):
        raise ValidationFailed("businessStatus", "code must be text")
    return code


def _target(resource: dict[str, Any], element: str, resource_type: str) -> str:
    reference = resource.get(element, {}).get("reference")
    prefix = f"{resource_type}/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise ValidationFailed(element, f"must reference a {resource_type}")
    return reference[len(prefix) :]


def _output_value(resource: dict[str, Any], code: str) -> dict[str, Any] | None:
    for entry in resource.get("output", []):
        codings = entry.get("type", {}).get("coding", [])
        if codings and codings[0].get("code") == code:
            return dict(entry)
    return None


def booking_from_fhir(resource: dict[str, Any]) -> Booking:
    """The booking for a Task. Refuses a Task it does not recognise."""
    identifiers = [item for item in resource.get("identifier", []) if isinstance(item, dict)]
    references = [
        item["value"]
        for item in identifiers
        if item.get("system") == BOOKING_REFERENCE_SYSTEM and isinstance(item.get("value"), str)
    ]
    if len(references) != 1:
        raise ValidationFailed("identifier", "needs one booking reference")

    period = resource.get("executionPeriod", {})
    responded_at = _instant("executionPeriod.end", period["end"]) if "end" in period else None
    reason_entry = _output_value(resource, _REASON)
    confirmed_entry = _output_value(resource, _CONFIRMED_AT)
    return Booking(
        id=str(resource["id"]),
        reference=references[0],
        service_id=_target(resource, "owner", "HealthcareService"),
        case_id=_target(resource, "focus", "ServiceRequest"),
        requester_id=_target(resource, "requester", "Practitioner"),
        status=from_fhir(_coded(resource["businessStatus"])),
        requested_at=_instant("authoredOn", resource.get("authoredOn")),
        reply_by=_instant("restriction.period.end", resource["restriction"]["period"]["end"]),
        confirmed_at=(
            _instant("output.valueDateTime", confirmed_entry["valueDateTime"])
            if confirmed_entry is not None
            else None
        ),
        responded_at=responded_at,
        reason=reason_entry["valueString"] if reason_entry is not None else None,
    )


async def read_task_fhir(store: ResourceStore, booking_id: str) -> dict[str, Any] | None:
    """The Task as stored, in the FHIR form, with meta. The derived properties are turned back
    into their FHIR elements: businessStatus becomes its CodeableConcept, reference is dropped
    (it is a copy of the identifier)."""
    resource = await store.get(_TASK, booking_id)
    if resource is None:
        return None
    stored_status = resource.pop(_BUSINESS_STATUS, None)
    resource.pop(_REFERENCE, None)
    if not isinstance(stored_status, str):
        raise ValidationFailed(_BUSINESS_STATUS, "missing on a stored booking")
    resource[_BUSINESS_STATUS] = codeable_to_fhir(from_fhir(stored_status))
    return resource


class Neo4jBookingRepository:
    """Bookings as Task resources. Built per transaction (DEC-012)."""

    def __init__(self, tx: ScopedTx, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def add(self, booking: Booking) -> None:
        # The store refuses an existing Task with Conflict (expected version None).
        await self._put(booking, None)

    async def get(self, booking_id: str) -> Booking | None:
        resource = await read_task_fhir(self._store, booking_id)
        return None if resource is None else booking_from_fhir(resource)

    async def get_by_reference(self, reference: str) -> Booking | None:
        rows = await run_query(self._tx, REGISTRY.get("Q-BOOK-BY-REF"), reference=reference)
        if not rows:
            return None
        return await self.get(str(rows[0]["id"]))

    async def save(self, booking: Booking) -> None:
        current = await self._store.get(_TASK, booking.id)
        if current is None:
            raise NotFound(f"{_TASK}/{booking.id}")
        await self._put(booking, str(current["meta"]["versionId"]))

    async def open_for_service(self, service_id: str) -> list[Booking]:
        grouped = await self.open_for_services([service_id])
        return grouped[service_id]

    async def open_for_services(self, service_ids: Sequence[str]) -> dict[str, list[Booking]]:
        grouped: dict[str, list[Booking]] = {service_id: [] for service_id in service_ids}
        rows = await run_query(self._tx, REGISTRY.get("Q-BOOK-OPEN-FOR"), ids=list(service_ids))
        for row in rows:
            booking = await self.get(str(row["id"]))
            if booking is not None:
                grouped[str(row["serviceId"])].append(booking)
        return grouped

    async def for_case(self, case_id: str) -> list[Booking]:
        rows = await run_query(self._tx, REGISTRY.get("Q-BOOK-FOR-CASE"), case=case_id)
        found: list[Booking] = []
        for row in rows:
            booking = await self.get(str(row["id"]))
            if booking is not None:
                found.append(booking)
        return found

    async def latest_for_services(self, service_ids: Sequence[str]) -> list[Booking]:
        """The most recent booking of each of these services that has one (U22)."""
        if not service_ids:
            return []
        rows = await run_query(self._tx, REGISTRY.get("Q-BOOK-LATEST-FOR"), ids=list(service_ids))
        found: list[Booking] = []
        for row in rows:
            booking = await self.get(str(row["id"]))
            if booking is not None:
                found.append(booking)
        return found

    async def confirmed_since(self, service_id: str, since: datetime) -> list[datetime]:
        rows = await run_query(self._tx, REGISTRY.get("Q-BOOK-CONFIRMED-SINCE"), id=service_id)
        times: list[datetime] = []
        for row in rows:
            booking = await self.get(str(row["id"]))
            confirmed = booking.confirmed_at if booking is not None else None
            if confirmed is not None and confirmed >= since:
                times.append(confirmed)
        return sorted(times)

    async def confirmed_between(self, start: datetime, end: datetime) -> list[Booking]:
        rows = await run_query(
            self._tx,
            REGISTRY.get("Q-BOOK-CONFIRMED-BETWEEN"),
            start=start.astimezone(UTC),
            end=end.astimezone(UTC),
            code=_CONFIRMED_AT,
            system=_OUTPUT_TYPE_SYSTEM,
        )
        found = [await self.get(str(row["id"])) for row in rows]
        return [booking for booking in found if booking is not None]

    async def confirmed_since_for_services(
        self, service_ids: Sequence[str], since: datetime
    ) -> dict[str, list[datetime]]:
        grouped: dict[str, list[datetime]] = {service_id: [] for service_id in service_ids}
        if not service_ids:
            return grouped
        # One query: the confirmed-at output of every confirmed Task of the listed services, with
        # its service. confirmed_at is kept only in the output entry (DEC-063 item 5), so the
        # instant is read from there, not from a second copy (DEC-001).
        rows = await run_query(
            self._tx,
            REGISTRY.get("Q-BOOK-CONFIRMED-FOR"),
            ids=list(service_ids),
            code=_CONFIRMED_AT,
            system=_OUTPUT_TYPE_SYSTEM,
        )
        for row in rows:
            confirmed = _as_utc_instant(row["confirmedAt"])
            if confirmed >= since:
                grouped[str(row["serviceId"])].append(confirmed)
        for times in grouped.values():
            times.sort()
        return grouped

    async def pending_count(self, service_id: str) -> int:
        rows = await run_query(self._tx, REGISTRY.get("Q-BOOK-PENDING"), id=service_id)
        return int(rows[0]["pending"])

    async def _put(self, booking: Booking, expected_version: str | None) -> None:
        resource = booking_to_fhir(booking)
        status = _coded(resource["businessStatus"])
        # The concept is not stored as a relationship: the businessStatus property holds it.
        stored = {name: value for name, value in resource.items() if name != _BUSINESS_STATUS}
        await self._store.put(stored, expected_version)
        await run_query(
            self._tx,
            REGISTRY.get("Q-BOOK-SET-PROPS"),
            key=f"{_TASK}/{booking.id}",
            businessStatus=status,
            reference=booking.reference,
        )


_CONFIRMED_BETWEEN: Final = NamedQuery(
    id="Q-BOOK-CONFIRMED-BETWEEN",
    cypher=(
        "MATCH (t:Task {businessStatus: 'confirmed', tenantId: $tenant})"
        "-[:HAS_OUTPUT]->(o:Task_Output {tenantId: $tenant})-[:TYPE]->"
        "(c:Concept {code: $code, system: $system, tenantId: $tenant}) "
        "WHERE o.valueDateTime >= $start AND o.valueDateTime < $end "
        "RETURN t.id AS id ORDER BY o.valueDateTime ASC, t.id ASC"
    ),
    mode="read",
    scenario=WEEK_SCENARIOS["Q-BOOK-CONFIRMED-BETWEEN"],
)
if _CONFIRMED_BETWEEN.id not in REGISTRY.ids():
    REGISTRY.register(_CONFIRMED_BETWEEN)
