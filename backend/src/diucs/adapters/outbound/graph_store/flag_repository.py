"""Report flags and service flags on Neo4j (P14).

Report flags are platform nodes (`ReportFlag`) on their Observation, written with named queries.
The Observation itself is never changed. Service flags are FHIR Basic resources with the
ServiceFlag profile, written through the G05 resource store (DEC-001: no json), then labelled
ServiceFlag. The FHIR form keeps the flag's fields as scalars, as the criteria mapping does.

Writes take a lock on the parent first (a SET of its id to itself, lesson L73), then check, then
write, so a racing writer waits and then sees the committed state (lesson L99):
- add_report_flag locks the Observation, so one flag id cannot be stored twice;
- save_report_flag locks the flag, so a flag is resolved once;
- set_service_flag locks the service, so one flag per service and code is kept.
Every refusal is decided before the first change.
"""

from datetime import UTC, datetime
from typing import Any, Final

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.codes import ReportFlagReason, parse_code
from diucs.domain.errors import Conflict, InvalidTransition, NotFound, ValidationFailed
from diucs.domain.model.flags import (
    REPORT_FLAG_OPEN,
    SERVICE_FLAG_CODES,
    ReportFlag,
    ServiceFlag,
)

_BASIC: Final = "Basic"
_SERVICE: Final = "HealthcareService"
_OBSERVATION: Final = "Observation"
_ACTIVE: Final = "active"
_INACTIVE: Final = "inactive"

# The elements a service flag Basic holds. Anything else is refused, never dropped (DEC-053).
_KEYS: Final = frozenset(
    {"resourceType", "id", "meta", "subject", "code", "status", "reason", "actor", "at"}
)

_QUERIES: Final = (
    NamedQuery(
        id="Q-FLAG-OBS-LOCK",
        cypher=("MATCH (o:Observation {key: $key}) SET o.id = o.id RETURN count(o) AS locked"),
        mode="write",
    ),
    NamedQuery(
        id="Q-FLAG-OBS-SERVICE",
        cypher=(
            "MATCH (:Observation {key: $key})-[:FOCUS]->(s:HealthcareService) "
            "RETURN s.id AS serviceId"
        ),
        mode="read",
    ),
    NamedQuery(
        id="Q-FLAG-REPORT-EXISTS",
        cypher="MATCH (f:ReportFlag {id: $id}) RETURN count(f) AS found",
        mode="read",
    ),
    NamedQuery(
        id="Q-FLAG-REPORT-ADD",
        cypher=(
            "MATCH (o:Observation {key: $key}) CREATE (f:ReportFlag) SET f = $props "
            "CREATE (f)-[:ON]->(o) RETURN count(f) AS created"
        ),
        mode="write",
    ),
    NamedQuery(
        id="Q-FLAG-REPORT-LOCK",
        cypher=("MATCH (f:ReportFlag {id: $id}) RETURN count(f) AS locked"),
        mode="write",
    ),
    NamedQuery(
        id="Q-FLAG-REPORT-GET",
        cypher=(
            "MATCH (f:ReportFlag {id: $id})-[:ON]->(o:Observation) "
            "RETURN properties(f) AS props, o.id AS reportId"
        ),
        mode="read",
    ),
    NamedQuery(
        id="Q-FLAG-REPORT-SAVE",
        cypher=(
            "MATCH (f:ReportFlag {id: $id}) SET f.status = $status, f.outcome = $outcome, "
            "f.resolvedAt = $resolvedAt RETURN count(f) AS saved"
        ),
        mode="write",
    ),
    NamedQuery(
        id="Q-FLAG-REPORT-OPEN",
        cypher=(
            "MATCH (f:ReportFlag {status: $status})-[:ON]->(o:Observation) "
            "WHERE $serviceId IS NULL OR f.serviceId = $serviceId "
            "RETURN properties(f) AS props, o.id AS reportId "
            "ORDER BY f.createdAt ASC, f.id ASC"
        ),
        mode="read",
    ),
    NamedQuery(
        id="Q-FLAG-SERVICE-LOCK",
        cypher=(
            "MATCH (s:HealthcareService {id: $serviceId}) SET s.id = s.id RETURN count(s) AS locked"
        ),
        mode="write",
    ),
    NamedQuery(
        id="Q-FLAG-BASIC-STATE",
        cypher=("MATCH (b:Basic {key: $key}) RETURN 'ServiceFlag' IN labels(b) AS flagged"),
        mode="read",
    ),
    NamedQuery(
        id="Q-FLAG-LABEL",
        cypher="MATCH (b:Basic {key: $key}) SET b:ServiceFlag RETURN count(b) AS labelled",
        mode="write",
    ),
    NamedQuery(
        id="Q-FLAG-SERVICE-ACTIVE",
        cypher=(
            "MATCH (f:ServiceFlag {status: $active})-[:SUBJECT]->"
            "(:HealthcareService {id: $serviceId}) "
            "RETURN f.key AS key ORDER BY f.code, f.key"
        ),
        mode="read",
    ),
    NamedQuery(
        id="Q-FLAG-SERVICES-WITH",
        cypher=(
            "MATCH (f:ServiceFlag {status: $active, code: $code})-[:SUBJECT]->"
            "(s:HealthcareService) "
            "RETURN DISTINCT s.id AS serviceId"
        ),
        mode="read",
    ),
)
for _query in _QUERIES:
    if _query.id not in REGISTRY.ids():
        REGISTRY.register(_query)


def _instant_text(instant: datetime) -> str:
    """FHIR instant text in UTC with a Z. Fractions are kept without trailing zeros, because the
    store refuses a fraction that would not read back identically (DEC-053 item 2)."""
    utc = instant.astimezone(UTC)
    text = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if utc.microsecond:
        text += f".{utc.microsecond:06d}".rstrip("0")
    return f"{text}Z"


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    native: datetime = value.to_native()
    return native.astimezone(UTC)


def service_flag_id(service_id: str, code: str) -> str:
    """The Basic id of the flag for one service and code: one per pair (the codes are a fixed set
    with no dots, so the id is unambiguous)."""
    return f"{service_id}.{code}"


def _reference_id(resource: dict[str, Any], element: str, target: str) -> str:
    ref = resource.get(element)
    text = ref.get("reference") if isinstance(ref, dict) else None
    prefix = f"{target}/"
    if not isinstance(text, str) or not text.startswith(prefix) or len(text) == len(prefix):
        raise ValidationFailed(element, f"must refer to a {target}")
    return text[len(prefix) :]


def service_flag_to_fhir(flag: ServiceFlag) -> dict[str, Any]:
    """The Basic for a service flag. No meta: the store sets it."""
    return {
        "resourceType": _BASIC,
        "id": service_flag_id(flag.service_id, flag.code),
        "subject": {"reference": f"{_SERVICE}/{flag.service_id}"},
        "code": flag.code,
        "status": _ACTIVE if flag.active else _INACTIVE,
        "reason": flag.reason,
        "actor": flag.actor_id,
        "at": _instant_text(flag.at),
    }


def service_flag_from_fhir(resource: dict[str, Any]) -> ServiceFlag:
    """The service flag for a Basic. Refuses an element it does not hold and a value it does not
    recognise, naming the field only."""
    unknown = set(resource) - _KEYS
    if unknown:
        raise ValidationFailed(
            "resource", "holds an element the service flag profile does not have"
        )
    status = resource.get("status")
    if status not in (_ACTIVE, _INACTIVE):
        raise ValidationFailed("status", "must be active or inactive")
    code = resource.get("code")
    if not isinstance(code, str) or code not in SERVICE_FLAG_CODES:
        raise ValidationFailed("code", "not a known service flag code")
    at = resource.get("at")
    if not isinstance(at, str):
        raise ValidationFailed("at", "must be a time")
    try:
        instant = datetime.fromisoformat(at)
    except ValueError:
        raise ValidationFailed("at", "must be a time") from None
    return ServiceFlag(
        service_id=_reference_id(resource, "subject", _SERVICE),
        code=code,
        active=status == _ACTIVE,
        reason=str(resource.get("reason", "")),
        actor_id=str(resource.get("actor", "")),
        at=instant,
    )


def _report_props(flag: ReportFlag) -> dict[str, Any]:
    """The stored properties of a report flag. A value that is not set is left out: Neo4j keeps
    no null property (lesson L74)."""
    props: dict[str, Any] = {
        "id": flag.id,
        "reason": flag.reason.value,
        "status": flag.status,
        "createdAt": flag.created_at,
        "serviceId": flag.service_id,
    }
    if flag.resolved_at is not None:
        props["resolvedAt"] = flag.resolved_at
    if flag.outcome is not None:
        props["outcome"] = flag.outcome
    return props


def _report_flag(props: dict[str, Any], report_id: str) -> ReportFlag:
    resolved = _as_utc(props.get("resolvedAt"))
    created = _as_utc(props.get("createdAt"))
    if created is None:
        raise ValidationFailed("createdAt", "is missing")
    return ReportFlag(
        id=str(props["id"]),
        report_id=report_id,
        service_id=str(props["serviceId"]),
        reason=parse_code(ReportFlagReason, str(props["reason"])),
        status=str(props["status"]),
        created_at=created,
        resolved_at=resolved,
        outcome=props.get("outcome"),
    )


class Neo4jFlagRepository:
    """Flags, built per transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    # --- report flags ---------------------------------------------------------------------------

    async def add_report_flag(self, flag: ReportFlag) -> None:
        key = f"{_OBSERVATION}/{flag.report_id}"
        locked = await run_query(self._tx, "Q-FLAG-OBS-LOCK", key=key)
        if not locked or int(locked[0]["locked"]) == 0:
            raise NotFound("report")
        service = await run_query(self._tx, "Q-FLAG-OBS-SERVICE", key=key)
        if not service or str(service[0]["serviceId"]) != flag.service_id:
            raise ValidationFailed("service_id", "is not the service the report is about")
        existing = await run_query(self._tx, "Q-FLAG-REPORT-EXISTS", id=flag.id)
        if int(existing[0]["found"]) > 0:
            raise Conflict("a report flag with this id already exists")
        await run_query(self._tx, "Q-FLAG-REPORT-ADD", key=key, props=_report_props(flag))

    async def open_report_flags(self, service_id: str | None = None) -> list[ReportFlag]:
        rows = await run_query(
            self._tx, "Q-FLAG-REPORT-OPEN", status=REPORT_FLAG_OPEN, serviceId=service_id
        )
        return [_report_flag(row["props"], str(row["reportId"])) for row in rows]

    async def save_report_flag(self, flag: ReportFlag) -> None:
        locked = await run_query(self._tx, "Q-FLAG-REPORT-LOCK", id=flag.id)
        if not locked or int(locked[0]["locked"]) == 0:
            raise NotFound("report flag")
        rows = await run_query(self._tx, "Q-FLAG-REPORT-GET", id=flag.id)
        stored = _report_flag(rows[0]["props"], str(rows[0]["reportId"]))
        if (stored.report_id, stored.service_id, stored.reason, stored.created_at) != (
            flag.report_id,
            flag.service_id,
            flag.reason,
            flag.created_at,
        ):
            raise ValidationFailed("flag", "report, service, reason and creation time are fixed")
        if stored.status != REPORT_FLAG_OPEN:
            raise InvalidTransition("this flag is already resolved")
        await run_query(
            self._tx,
            "Q-FLAG-REPORT-SAVE",
            id=flag.id,
            status=flag.status,
            outcome=flag.outcome,
            resolvedAt=flag.resolved_at,
        )

    # --- service flags --------------------------------------------------------------------------

    async def service_flags(self, service_id: str) -> list[ServiceFlag]:
        rows = await run_query(
            self._tx, "Q-FLAG-SERVICE-ACTIVE", active=_ACTIVE, serviceId=service_id
        )
        found: list[ServiceFlag] = []
        for row in rows:
            flag_id = str(row["key"]).removeprefix(f"{_BASIC}/")
            resource = await self._store.get(_BASIC, flag_id)
            if resource is None:
                raise NotFound("service flag")
            found.append(service_flag_from_fhir(resource))
        return found

    async def set_service_flag(self, flag: ServiceFlag) -> None:
        locked = await run_query(self._tx, "Q-FLAG-SERVICE-LOCK", serviceId=flag.service_id)
        if not locked or int(locked[0]["locked"]) == 0:
            raise NotFound("service")
        resource = service_flag_to_fhir(flag)
        flag_id = str(resource["id"])
        key = f"{_BASIC}/{flag_id}"
        if await self._store.exists(_BASIC, flag_id):
            state = await run_query(self._tx, "Q-FLAG-BASIC-STATE", key=key)
            if not state or not state[0]["flagged"]:
                raise Conflict("a resource with this id is not a service flag")
            current = await self._store.get(_BASIC, flag_id)
            if current is None:
                raise NotFound("service flag")
            await self._store.put(resource, str(current["meta"]["versionId"]))
        else:
            await self._store.put(resource, None)
        await run_query(self._tx, "Q-FLAG-LABEL", key=key)

    async def services_with_flag(self, code: str) -> set[str]:
        rows = await run_query(self._tx, "Q-FLAG-SERVICES-WITH", active=_ACTIVE, code=code)
        return {str(row["serviceId"]) for row in rows}
