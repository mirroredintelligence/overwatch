"""Registrations on Neo4j: Registration <-> FHIR Task code register-service (P13).

The mapping is pure (registration_to_fhir, registration_from_fhir, draft_to_rows, draft_from_rows).
The Task is written through the G05 resource store, so the graph holds the decomposed properties
and relationships and no json (DEC-001). Three things sit beside the store's copy, written in the
same transaction (DEC-080):

- `businessStatus` and `submittedAt` on the Task node. businessStatus is the registration status
  code (the store does not hold it as a concept, as the booking mapper does not). submittedAt is a
  Neo4j datetime, so submissions can be ordered in the graph. Both are copies of values the Task
  holds in FHIR form, written by the same put.
- the draft: one RegistrationDraftField node per step and field, joined to the Task by DRAFT_OF.
  The draft is replaced as a whole on every save, after the store's write lock, so a refused save
  writes nothing.

Decisions: DEC-080 (the draft and the derived copies), DEC-081 (the Task status and the checks).
"""

from datetime import UTC, datetime
from typing import Any, Final

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.extensions import EXTENSIONS, by_short_name
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_repository import (
    codeable_from_fhir,
    codeable_to_fhir,
)
from diucs.domain.codes import (
    RegistrationStatus,
    ScopeFlag,
    code_system_url,
    parse_code,
)
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.registration import Registration
from diucs.domain.rules.registration import ApprovalChecks

TASK: Final = "Task"
SERVICE: Final = "HealthcareService"
ROLE: Final = "PractitionerRole"
REGISTER_SERVICE: Final = "register-service"
TASK_CODE_SYSTEM: Final = code_system_url("task-code")
_CHECK_NAMES: Final = ("checkAutomatic", "checkCallback", "checkScope", "checkCriteria")

# The Task status for each registration state (DEC-081).
TASK_STATUS: Final[dict[RegistrationStatus, str]] = {
    RegistrationStatus.INVITED: "draft",
    RegistrationStatus.DRAFT: "draft",
    RegistrationStatus.SUBMITTED: "requested",
    RegistrationStatus.IN_REVIEW: "requested",
    RegistrationStatus.NEEDS_CHANGES: "requested",
    RegistrationStatus.APPROVED: "accepted",
    RegistrationStatus.LIVE: "in-progress",
    RegistrationStatus.REVERIFY: "in-progress",
    RegistrationStatus.PAUSED: "on-hold",
    RegistrationStatus.NOT_APPROVED: "rejected",
}

_BY_STATUS: Final = NamedQuery(
    id="Q-REG-BY-STATUS",
    cypher=(
        "MATCH (t:Task {businessStatus: $status})-[:CODE]->"
        "(:Concept {system: $system, code: $code}) "
        "RETURN t.id AS id ORDER BY t.submittedAt, t.id DESC"
    ),
    mode="read",
)
_FOR_SERVICE: Final = NamedQuery(
    id="Q-REG-FOR-SERVICE",
    cypher=(
        "MATCH (t:Task)-[:FOCUS]->(:HealthcareService {id: $serviceId}), "
        "(t)-[:CODE]->(:Concept {system: $system, code: $code}) "
        "RETURN t.id AS id ORDER BY t.authoredOn DESC, t.id DESC"
    ),
    mode="read",
)
_SET_PROPS: Final = NamedQuery(
    id="Q-REG-SET-PROPS",
    cypher=(
        "MATCH (t:Task {key: $key}) "
        "SET t.businessStatus = $businessStatus, t.submittedAt = $submittedAt "
        "RETURN count(t) AS set"
    ),
    mode="write",
)
_DRAFT_CLEAR: Final = NamedQuery(
    id="Q-REG-DRAFT-CLEAR",
    cypher=("MATCH (d:RegistrationDraftField)-[:DRAFT_OF]->(:Task {key: $key}) DETACH DELETE d"),
    mode="write",
)
_DRAFT_ADD: Final = NamedQuery(
    id="Q-REG-DRAFT-ADD",
    cypher=(
        "MATCH (t:Task {key: $key}) UNWIND $rows AS row "
        "CREATE (:RegistrationDraftField {step: row.step, field: row.field, value: row.value})"
        "-[:DRAFT_OF]->(t)"
    ),
    mode="write",
)
_DRAFT_FOR: Final = NamedQuery(
    id="Q-REG-DRAFT-FOR",
    cypher=(
        "MATCH (d:RegistrationDraftField)-[:DRAFT_OF]->(:Task {key: $key}) "
        "RETURN d.step AS step, d.field AS field, d.value AS value"
    ),
    mode="read",
)


def _register(query: NamedQuery) -> None:
    if query.id not in REGISTRY.ids():
        REGISTRY.register(query)


for _query in (_BY_STATUS, _FOR_SERVICE, _SET_PROPS, _DRAFT_CLEAR, _DRAFT_ADD, _DRAFT_FOR):
    _register(_query)


def _iso(value: datetime) -> str:
    """UTC, with Z. Microseconds are kept only when present."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _instant(field: str, text: Any) -> datetime:
    if not isinstance(text, str):
        raise ValidationFailed(field, "must be a FHIR datetime")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValidationFailed(field, "not a FHIR datetime") from None
    if parsed.tzinfo is None:
        raise ValidationFailed(field, "must carry a UTC offset")
    return parsed.astimezone(UTC)


def _extension(short_name: str, value: Any) -> dict[str, Any]:
    defn = by_short_name(short_name)
    if defn is None:  # a programming error: the names are registered in extensions.py
        raise LookupError(short_name)
    return {"url": defn.url, defn.value_key: value}


def _check_extensions(checks: ApprovalChecks) -> list[dict[str, Any]]:
    items = [
        _extension("checkAutomatic", checks.automatic_ok),
        _extension("checkCallback", checks.callback_confirmed),
    ]
    if checks.scope is not None:
        items.append(_extension("checkScope", checks.scope.value))
    items.append(_extension("checkCriteria", checks.criteria_approved))
    return items


def _check_values(resource: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for entry in resource.get("extension", []):
        defn = EXTENSIONS.get(entry.get("url"))
        if defn is None or defn.short_name not in _CHECK_NAMES:
            raise ValidationFailed("extension", "not a registration check")
        values[defn.short_name] = entry[defn.value_key]
    return values


def _flag(values: dict[str, Any], name: str) -> bool:
    value = values.get(name)
    if not isinstance(value, bool):
        raise ValidationFailed(name, "must be a flag")
    return value


def _checks_from_fhir(resource: dict[str, Any]) -> ApprovalChecks:
    values = _check_values(resource)
    scope_text = values.get("checkScope")
    scope = None if scope_text is None else parse_code(ScopeFlag, scope_text)
    return ApprovalChecks(
        automatic_ok=_flag(values, "checkAutomatic"),
        callback_confirmed=_flag(values, "checkCallback"),
        scope=scope,
        criteria_approved=_flag(values, "checkCriteria"),
    )


def _is_registration(resource: dict[str, Any]) -> bool:
    code = resource.get("code")
    codings = code.get("coding") if isinstance(code, dict) else None
    if not isinstance(codings, list) or len(codings) != 1 or not isinstance(codings[0], dict):
        return False
    return codings[0].get("system") == TASK_CODE_SYSTEM and (
        codings[0].get("code") == REGISTER_SERVICE
    )


def _target(resource: dict[str, Any], element: str, resource_type: str) -> str:
    reference = resource.get(element, {}).get("reference")
    prefix = f"{resource_type}/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise ValidationFailed(element, f"must reference a {resource_type}")
    return reference[len(prefix) :]


def _optional_target(resource: dict[str, Any], element: str, resource_type: str) -> str | None:
    if element not in resource:
        return None
    return _target(resource, element, resource_type)


def registration_to_fhir(registration: Registration) -> dict[str, Any]:
    """The Task for a registration, without the draft (it is stored as draft rows). The store
    sets meta. businessStatus is included here; the repository holds it as a property instead."""
    resource: dict[str, Any] = {
        "resourceType": TASK,
        "id": registration.id,
        "status": TASK_STATUS[registration.status],
        "businessStatus": codeable_to_fhir(registration.status),
        "code": {"coding": [{"system": TASK_CODE_SYSTEM, "code": REGISTER_SERVICE}]},
        "intent": "order",
        "authoredOn": _iso(registration.created_at),
        "lastModified": _iso(registration.last_modified),
        "focus": {"reference": f"{SERVICE}/{registration.service_id}"},
        "extension": _check_extensions(registration.checks),
    }
    if registration.requester_role_id is not None:
        resource["requester"] = {"reference": f"{ROLE}/{registration.requester_role_id}"}
    if registration.owner_role_id is not None:
        resource["owner"] = {"reference": f"{ROLE}/{registration.owner_role_id}"}
    if registration.submitted_at is not None:
        resource["executionPeriod"] = {"start": _iso(registration.submitted_at)}
    if registration.note:
        resource["description"] = registration.note
    return resource


def registration_from_fhir(
    resource: dict[str, Any], draft: dict[str, dict[str, Any]]
) -> Registration:
    """The registration for a Task and its draft rows. Refuses a Task that is not a registration,
    and a status or check it does not recognise."""
    if not _is_registration(resource):
        raise ValidationFailed("code", "not a registration task")
    status = codeable_from_fhir(
        resource.get("businessStatus"), RegistrationStatus, "businessStatus"
    )
    period = resource.get("executionPeriod", {})
    submitted = _instant("executionPeriod.start", period["start"]) if "start" in period else None
    return Registration(
        id=str(resource["id"]),
        service_id=_target(resource, "focus", SERVICE),
        status=status,
        requester_role_id=_optional_target(resource, "requester", ROLE),
        owner_role_id=_optional_target(resource, "owner", ROLE),
        created_at=_instant("authoredOn", resource.get("authoredOn")),
        last_modified=_instant("lastModified", resource.get("lastModified")),
        submitted_at=submitted,
        draft=dict(draft),
        checks=_checks_from_fhir(resource),
        note=resource.get("description", ""),
    )


def draft_to_rows(draft: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per step and field, in step and field order, with the value's own type."""
    return [
        {"step": step, "field": name, "value": value}
        for step, fields in sorted(draft.items())
        for name, value in sorted(fields.items())
    ]


def draft_from_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The draft for its rows. A field stored twice is refused: the draft would be ambiguous."""
    draft: dict[str, dict[str, Any]] = {}
    for row in rows:
        fields = draft.setdefault(row["step"], {})
        if row["field"] in fields:
            raise ValidationFailed("draft", "a field is stored twice")
        fields[row["field"]] = row["value"]
    return draft


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)


class Neo4jRegistrationRepository:
    """Registrations as Task resources. Built per transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def add(self, registration: Registration) -> None:
        await self._require_service(registration.service_id)
        # The store refuses an existing Task with Conflict (expected version None).
        await self._put(registration, None)

    async def get(self, registration_id: str) -> Registration | None:
        resource = await self._store.get(TASK, registration_id)
        if resource is None:
            return None
        return await self._from_store(resource)

    async def save(self, registration: Registration) -> None:
        current = await self._store.get(TASK, registration.id)
        if current is None or not _is_registration(current):
            raise NotFound("registration")
        await self._put(registration, str(current["meta"]["versionId"]))

    async def list_by_status(self, status: RegistrationStatus) -> list[Registration]:
        # Lesson L38: the enum type is checked before the value is used in a match.
        if not isinstance(status, RegistrationStatus):
            raise ValidationFailed("status", "must be a registration status")
        rows = await run_query(
            self._tx,
            "Q-REG-BY-STATUS",
            status=status.value,
            system=TASK_CODE_SYSTEM,
            code=REGISTER_SERVICE,
        )
        return await self._many(rows)

    async def for_service(self, service_id: str) -> list[Registration]:
        rows = await run_query(
            self._tx,
            "Q-REG-FOR-SERVICE",
            serviceId=service_id,
            system=TASK_CODE_SYSTEM,
            code=REGISTER_SERVICE,
        )
        return await self._many(rows)

    async def _many(self, rows: list[dict[str, Any]]) -> list[Registration]:
        found: list[Registration] = []
        for row in rows:
            registration = await self.get(str(row["id"]))
            if registration is not None:
                found.append(registration)
        return found

    async def _from_store(self, resource: dict[str, Any]) -> Registration:
        # The derived copies are not FHIR elements: the status is read back as its CodeableConcept
        # and the submission time is already the executionPeriod start (DEC-080).
        stored_status = resource.pop("businessStatus", None)
        resource.pop("submittedAt", None)
        if not isinstance(stored_status, str):
            raise ValidationFailed("businessStatus", "missing on a stored registration")
        resource["businessStatus"] = codeable_to_fhir(parse_code(RegistrationStatus, stored_status))
        rows = await run_query(self._tx, "Q-REG-DRAFT-FOR", key=f"{TASK}/{resource['id']}")
        return registration_from_fhir(resource, draft_from_rows(rows))

    async def _require_service(self, service_id: str) -> None:
        if await self._store.get(SERVICE, service_id) is None:
            raise NotFound("service")

    async def _put(self, registration: Registration, expected_version: str | None) -> None:
        resource = registration_to_fhir(registration)
        status = resource.pop("businessStatus")["coding"][0]["code"]
        await self._store.put(resource, expected_version)
        key = f"{TASK}/{registration.id}"
        await run_query(
            self._tx,
            "Q-REG-SET-PROPS",
            key=key,
            businessStatus=status,
            submittedAt=_utc(registration.submitted_at),
        )
        await run_query(self._tx, "Q-REG-DRAFT-CLEAR", key=key)
        rows = draft_to_rows(registration.draft)
        if rows:
            await run_query(self._tx, "Q-REG-DRAFT-ADD", key=key, rows=rows)
