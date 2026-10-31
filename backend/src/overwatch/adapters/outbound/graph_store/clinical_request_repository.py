"""Clinical advice requests on Neo4j (P18).

A request is a Task with code `clinical-advice-request` (CodeSystem `task-code`), written through
the G05 resource store. Its focus is the case ServiceRequest, its requester the advisor who asked,
its owner the clinical advisor who took it (absent until taken). Priority is `stat` for urgency
`now` and `asap` for `within-15-min`.

Advice is stored on the same Task, but as node properties (adviceChoice, adviceReason, noteHandle,
advisedAt) written after each put, not as FHIR Task.output: the output backbone for a coded value is
not verified. The record holds a handle to the protected text store and never the text. The
business status is a property too (businessStatus), as in the registration store.

Presence is not stored here (it is in the cache). Queue order is queue_order (D23), applied in
Python.
"""

from datetime import UTC, datetime
from typing import Any, Final

from diucs.adapters.outbound.graph_store.driver import ScopedTx, run_query
from diucs.adapters.outbound.graph_store.extensions import by_short_name
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
)
from diucs.domain.codes import code_system_url
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.clinical import ClinicalAdvice, ClinicalRequestRecord
from diucs.domain.rules.clinical_queue import ClinicalRequest, queue_order

TASK: Final = "Task"
SERVICE_REQUEST: Final = "ServiceRequest"
PRACTITIONER: Final = "Practitioner"
CLINICAL_CODE: Final = "clinical-advice-request"
TASK_CODE_SYSTEM: Final = code_system_url("task-code")
STATUS_SYSTEM: Final = code_system_url("clinical-request-status")
WAITING: Final = "waiting"
TAKEN: Final = "taken"
ADVISED: Final = "advised"
_FHIR_STATUS: Final = {WAITING: "requested", TAKEN: "in-progress", ADVISED: "completed"}
_PRIORITY: Final = {"now": "stat", "within-15-min": "asap"}
_URGENCY: Final = {"stat": "now", "asap": "within-15-min"}
_ADVICE_PROPS: Final = ("adviceChoice", "adviceReason", "noteHandle", "advisedAt")
_STORED_PROPS: Final = ("businessStatus", *_ADVICE_PROPS)

# Scenarios (DEC-150). Both tenants hold the request `req-1`, the clinical code and the advisor
# `clin-1`: the keys are shared, so only the tenant stamp keeps the two apart.
_AT: Final = datetime(2026, 10, 25, 13, 16, tzinfo=UTC)
_NODE_CONCEPT: Final = SeedNode(
    "concept",
    ("Concept",),
    {
        "system": TASK_CODE_SYSTEM,
        "code": CLINICAL_CODE,
        "key": f"Concept|{TASK_CODE_SYSTEM}|{CLINICAL_CODE}",
        "display": Marked("Clinical advice request"),
    },
)
_NODE_CLIN: Final = SeedNode(
    "clin",
    ("Resource", "Practitioner"),
    {"id": "clin-1", "key": "Practitioner/clin-1", "active": True},
)
_NODE_WAITING: Final = SeedNode(
    "req",
    ("Resource", "Task"),
    {"id": "req-1", "key": "Task/req-1", "businessStatus": WAITING},
)
_NODE_TAKEN: Final = SeedNode(
    "req",
    ("Resource", "Task"),
    {"id": "req-1", "key": "Task/req-1", "businessStatus": TAKEN, "priority": "stat"},
)
_WAITING_SEED: Final = TenantSeed(
    nodes=(_NODE_CONCEPT, _NODE_WAITING),
    rels=(SeedRel("req", "CODE", "concept"),),
)
_TAKEN_SEED: Final = TenantSeed(
    nodes=(_NODE_CONCEPT, _NODE_CLIN, _NODE_TAKEN),
    rels=(SeedRel("req", "CODE", "concept"), SeedRel("req", "OWNER", "clin")),
)
_NODE_ADVISED: Final = SeedNode(
    "req",
    ("Resource", "Task"),
    {
        "id": "req-1",
        "key": "Task/req-1",
        "businessStatus": ADVISED,
        "priority": "stat",
        "adviceChoice": Marked("choice"),
        "advisedAt": _AT,
    },
)
_ADVISED_SEED: Final = TenantSeed(
    nodes=(_NODE_CONCEPT, _NODE_CLIN, _NODE_ADVISED),
    rels=(SeedRel("req", "CODE", "concept"), SeedRel("req", "OWNER", "clin")),
)
_CODE_PARAMS: Final = {"system": TASK_CODE_SYSTEM, "code": CLINICAL_CODE}
_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-CLIN-WAITING": Scenario(
        "list the clinical advice requests nobody has taken, for the clinical code",
        seed=_WAITING_SEED,
        params=_CODE_PARAMS,
        lookup=("system", "code"),
        expect=Expect(rows=({"id": "req-1"},)),
    ),
    "Q-CLIN-OPEN": Scenario(
        "list the clinical advice requests not yet advised, waiting or taken",
        seed=_WAITING_SEED,
        params=_CODE_PARAMS,
        lookup=("system", "code"),
        expect=Expect(rows=({"id": "req-1"},)),
    ),
    "Q-CLIN-TAKEN-BY": Scenario(
        "list the clinical advice requests a clinical advisor has taken",
        seed=_TAKEN_SEED,
        params={"clinicianId": "clin-1", **_CODE_PARAMS},
        lookup=("clinicianId", "system", "code"),
        expect=Expect(rows=({"id": "req-1"},)),
    ),
    "Q-CLIN-ADVISED-BY": Scenario(
        "list the clinical advice requests a clinical advisor advised on, latest first",
        seed=_ADVISED_SEED,
        params={"clinicianId": "clin-1", "limit": 50, **_CODE_PARAMS},
        lookup=("clinicianId", "system", "code"),
        new=("limit",),
        expect=Expect(rows=({"id": "req-1", "adviceChoice": Marked("choice")},)),
    ),
    "Q-CLIN-SET-PROPS": Scenario(
        "set the business status and the advice properties of a request",
        seed=_TAKEN_SEED,
        params={
            "key": "Task/req-1",
            "businessStatus": ADVISED,
            "adviceChoice": "go-ahead",
            "adviceReason": "within-criteria",
            "noteHandle": "h-123",
            "advisedAt": _AT,
        },
        lookup=("key",),
        new=("businessStatus", "adviceChoice", "adviceReason", "noteHandle", "advisedAt"),
        expect=Expect(
            rows=({"set": 1},),
            after=(NodeSpec(("Task",), {"id": "req-1", "businessStatus": ADVISED}),),
        ),
    ),
    "Q-CLIN-PROPS": Scenario(
        "read the business status and the advice properties of a request",
        seed=_TAKEN_SEED,
        params={"key": "Task/req-1"},
        lookup=("key",),
        expect=Expect(rows=({"businessStatus": TAKEN},)),
    ),
}

_QUERIES: Final[tuple[NamedQuery, ...]] = (
    NamedQuery(
        id="Q-CLIN-WAITING",
        cypher=(
            "MATCH (t:Task {businessStatus: 'waiting', tenantId: $tenant})"
            "-[:CODE]->(:Concept {system: $system, code: $code, tenantId: $tenant}) "
            "RETURN t.id AS id ORDER BY t.authoredOn, t.id"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-CLIN-WAITING"],
    ),
    NamedQuery(
        id="Q-CLIN-OPEN",
        cypher=(
            "MATCH (t:Task {tenantId: $tenant}) "
            "WHERE t.businessStatus IN ['waiting', 'taken'] "
            "MATCH (t)-[:CODE]->(:Concept {system: $system, code: $code, tenantId: $tenant}) "
            "RETURN t.id AS id ORDER BY t.authoredOn, t.id"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-CLIN-OPEN"],
    ),
    NamedQuery(
        id="Q-CLIN-TAKEN-BY",
        cypher=(
            "MATCH (t:Task {businessStatus: 'taken', tenantId: $tenant})"
            "-[:OWNER]->(:Practitioner {id: $clinicianId, tenantId: $tenant}), "
            "(t)-[:CODE]->(:Concept {system: $system, code: $code, tenantId: $tenant}) "
            "RETURN t.id AS id ORDER BY t.authoredOn, t.id"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-CLIN-TAKEN-BY"],
    ),
    NamedQuery(
        id="Q-CLIN-ADVISED-BY",
        cypher=(
            "MATCH (t:Task {businessStatus: 'advised', tenantId: $tenant})"
            "-[:OWNER]->(:Practitioner {id: $clinicianId, tenantId: $tenant}), "
            "(t)-[:CODE]->(:Concept {system: $system, code: $code, tenantId: $tenant}) "
            "RETURN t.id AS id, t.adviceChoice AS adviceChoice "
            "ORDER BY t.advisedAt DESC, t.id LIMIT $limit"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-CLIN-ADVISED-BY"],
    ),
    NamedQuery(
        id="Q-CLIN-SET-PROPS",
        cypher=(
            "MATCH (t:Task {key: $key, tenantId: $tenant}) "
            "SET t.businessStatus = $businessStatus, t.adviceChoice = $adviceChoice, "
            "t.adviceReason = $adviceReason, t.noteHandle = $noteHandle, "
            "t.advisedAt = $advisedAt "
            "RETURN count(t) AS set"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-CLIN-SET-PROPS"],
    ),
    NamedQuery(
        id="Q-CLIN-PROPS",
        cypher=(
            "MATCH (t:Task {key: $key, tenantId: $tenant}) "
            "RETURN t.businessStatus AS businessStatus, t.adviceChoice AS adviceChoice, "
            "t.adviceReason AS adviceReason, t.noteHandle AS noteHandle, "
            "t.advisedAt AS advisedAt"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-CLIN-PROPS"],
    ),
)


def _register(query: NamedQuery) -> None:
    if query.id not in REGISTRY.ids():
        REGISTRY.register(query)


for _query in _QUERIES:
    _register(_query)


def _iso(value: datetime) -> str:
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


def _utc(value: Any) -> datetime | None:
    """A stored instant as UTC; the driver returns its own datetime type, converted here."""
    if value is None:
        return None
    native: datetime = value.to_native() if hasattr(value, "to_native") else value
    return native.astimezone(UTC)


def _extension(short_name: str, value: Any) -> dict[str, Any]:
    defn = by_short_name(short_name)
    if defn is None:  # a programming error: the names are registered in extensions.py
        raise LookupError(short_name)
    return {"url": defn.url, defn.value_key: value}


def _extension_value(resource: dict[str, Any], short_name: str) -> Any:
    defn = by_short_name(short_name)
    if defn is None:
        raise LookupError(short_name)
    for entry in resource.get("extension", []):
        if entry.get("url") == defn.url:
            return entry.get(defn.value_key)
    return None


def _is_clinical(resource: dict[str, Any]) -> bool:
    codings = resource.get("code", {}).get("coding")
    return (
        isinstance(codings, list)
        and len(codings) == 1
        and codings[0].get("system") == TASK_CODE_SYSTEM
        and codings[0].get("code") == CLINICAL_CODE
    )


def _reference_id(reference: Any, resource_type: str, field: str) -> str:
    prefix = f"{resource_type}/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise ValidationFailed(field, f"must reference a {resource_type}")
    return reference[len(prefix) :]


def _state(record: ClinicalRequestRecord) -> str:
    if record.advice is not None:
        return ADVISED
    if record.request.taken_by is not None:
        return TAKEN
    return WAITING


def clinical_record_to_fhir(record: ClinicalRequestRecord) -> dict[str, Any]:
    """The Task for a request. The store sets meta; businessStatus and the advice properties are
    written by the repository (clinical_record_to_props)."""
    request = record.request
    state = _state(record)
    resource: dict[str, Any] = {
        "resourceType": TASK,
        "id": request.id,
        "status": _FHIR_STATUS[state],
        "businessStatus": {"coding": [{"system": STATUS_SYSTEM, "code": state}]},
        "intent": "order",
        "priority": _PRIORITY[request.urgency],
        "code": {"coding": [{"system": TASK_CODE_SYSTEM, "code": CLINICAL_CODE}]},
        "authoredOn": _iso(request.requested_at),
        "focus": {"reference": f"{SERVICE_REQUEST}/{request.case_id}"},
        "requester": {"reference": f"{PRACTITIONER}/{record.requester_id}"},
        "extension": [_extension("why", record.why)],
    }
    if record.snapshot_ref is not None:
        resource["extension"].append(_extension("snapshotRef", record.snapshot_ref))
    if record.service_id is not None:
        resource["extension"].append(_extension("consideredService", record.service_id))
    if request.taken_by is not None and request.taken_at is not None:
        resource["owner"] = {"reference": f"{PRACTITIONER}/{request.taken_by}"}
        resource["extension"].append(_extension("takenAt", _iso(request.taken_at)))
    return resource


def clinical_record_to_props(record: ClinicalRequestRecord) -> dict[str, Any]:
    """The node properties that hold the status and the advice. Absent advice is None, which the
    store does not keep (a missing key reads as None)."""
    advice = record.advice
    return {
        "businessStatus": _state(record),
        "adviceChoice": None if advice is None else advice.choice,
        "adviceReason": None if advice is None else advice.reason,
        "noteHandle": None if advice is None else advice.note_handle,
        "advisedAt": None if advice is None else advice.at.astimezone(UTC),
    }


def clinical_record_from_fhir(
    resource: dict[str, Any], props: dict[str, Any]
) -> ClinicalRequestRecord:
    """The record for a Task and its advice properties. Refuses a Task that is not a clinical
    advice request, and a priority it does not know."""
    if not _is_clinical(resource):
        raise ValidationFailed("code", "not a clinical advice request")
    priority = resource.get("priority")
    if priority not in _URGENCY:
        raise ValidationFailed("priority", "must be stat or asap")
    owner = resource.get("owner")
    taker = None if owner is None else _reference_id(owner.get("reference"), PRACTITIONER, "owner")
    taken = _extension_value(resource, "takenAt")
    taken_at = None if taken is None else _instant("takenAt", taken)
    advised_at = _utc(props.get("advisedAt"))
    request = ClinicalRequest(
        id=str(resource["id"]),
        case_id=_reference_id(resource["focus"].get("reference"), SERVICE_REQUEST, "focus"),
        urgency=_URGENCY[priority],
        requested_at=_instant("authoredOn", resource.get("authoredOn")),
        taken_by=taker,
        taken_at=taken_at,
        advised_at=advised_at,
    )
    advice = None
    if advised_at is not None:
        advice = ClinicalAdvice(
            choice=str(props.get("adviceChoice")),
            reason=props.get("adviceReason"),
            note_handle=props.get("noteHandle"),
            clinician_id=str(taker),
            at=advised_at,
        )
    snapshot = _extension_value(resource, "snapshotRef")
    considered = _extension_value(resource, "consideredService")
    return ClinicalRequestRecord(
        request=request,
        requester_id=_reference_id(
            resource["requester"].get("reference"), PRACTITIONER, "requester"
        ),
        why=str(_extension_value(resource, "why")),
        snapshot_ref=snapshot,
        advice=advice,
        service_id=considered,
    )


class Neo4jClinicalRequestRepository:
    """Clinical advice requests. Built per transaction (DEC-012)."""

    def __init__(self, tx: ScopedTx, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def add(self, record: ClinicalRequestRecord) -> None:
        # The store refuses an existing Task with Conflict (expected version None).
        await self._put(record, None)

    async def get(self, request_id: str) -> ClinicalRequestRecord | None:
        resource = await self._store.get(TASK, request_id)
        if resource is None or not _is_clinical(resource):
            return None
        for name in _STORED_PROPS:
            resource.pop(name, None)
        rows = await run_query(self._tx, REGISTRY.get("Q-CLIN-PROPS"), key=f"{TASK}/{request_id}")
        return clinical_record_from_fhir(resource, rows[0] if rows else {})

    async def save(self, record: ClinicalRequestRecord) -> None:
        current = await self._store.get(TASK, record.request.id)
        if current is None or not _is_clinical(current):
            raise NotFound("clinical request")
        await self._put(record, str(current["meta"]["versionId"]))

    async def waiting(self) -> list[ClinicalRequestRecord]:
        rows = await run_query(
            self._tx,
            REGISTRY.get("Q-CLIN-WAITING"),
            system=TASK_CODE_SYSTEM,
            code=CLINICAL_CODE,
        )
        found = await self._many(rows)
        by_id = {record.request.id: record for record in found}
        return [by_id[request.id] for request in queue_order(r.request for r in found)]

    async def open_requests(self) -> list[ClinicalRequestRecord]:
        rows = await run_query(
            self._tx,
            REGISTRY.get("Q-CLIN-OPEN"),
            system=TASK_CODE_SYSTEM,
            code=CLINICAL_CODE,
        )
        return await self._many(rows)

    async def taken_by(self, clinician_id: str) -> list[ClinicalRequestRecord]:
        rows = await run_query(
            self._tx,
            REGISTRY.get("Q-CLIN-TAKEN-BY"),
            clinicianId=clinician_id,
            system=TASK_CODE_SYSTEM,
            code=CLINICAL_CODE,
        )
        return await self._many(rows)

    async def advised_by(self, clinician_id: str, limit: int) -> list[ClinicalRequestRecord]:
        rows = await run_query(
            self._tx,
            REGISTRY.get("Q-CLIN-ADVISED-BY"),
            clinicianId=clinician_id,
            system=TASK_CODE_SYSTEM,
            code=CLINICAL_CODE,
            limit=limit,
        )
        return await self._many(rows)

    async def _many(self, rows: list[dict[str, Any]]) -> list[ClinicalRequestRecord]:
        found: list[ClinicalRequestRecord] = []
        for row in rows:
            record = await self.get(str(row["id"]))
            if record is not None:
                found.append(record)
        return found

    async def _put(self, record: ClinicalRequestRecord, expected_version: str | None) -> None:
        resource = clinical_record_to_fhir(record)
        resource.pop("businessStatus")
        await self._store.put(resource, expected_version)
        await run_query(
            self._tx,
            REGISTRY.get("Q-CLIN-SET-PROPS"),
            key=f"{TASK}/{record.request.id}",
            **clinical_record_to_props(record),
        )
