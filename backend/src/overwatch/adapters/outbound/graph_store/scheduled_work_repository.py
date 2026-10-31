"""Neo4j repository for ScheduledWork records (P08, DEC-057).

A ScheduledWork node (id, kind, dueAt, sequenceNumber, status) has one ABOUT relationship to its
subject. The subject is matched by its resource key (`Type/id`, DEC-053). A placeholder Resource is
created only when the subject is absent. The work runs in the caller's transaction (the unit of
work), through named queries in the registry. Every dueAt is stored in UTC.

save() moves the status only forward from `scheduled`: a work that is done or cancelled keeps its
status whatever the copy the caller read says, so a cancel committed between a read and a save is
not undone (KI-89). The record's lock is taken first, then the status is read.

add() is safe to retry (DEC-012): adding the same record again changes nothing, and adding a
different record under an existing id is refused with Conflict.
"""

from datetime import UTC, datetime
from typing import Any, Final

from diucs.adapters.outbound.graph_store.driver import ScopedTx, run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
)
from diucs.application.work import ScheduledWork, WorkKind
from diucs.domain.errors import Conflict, NotFound

_FIELDS = (
    "w.id AS id, w.kind AS kind, w.dueAt AS dueAt, "
    "w.sequenceNumber AS sequenceNumber, w.status AS status, s.key AS aboutId"
)

# Scenarios (TEN-015, DEC-142 item 5, DEC-150). Both tenants hold the same work id, the same
# subject key and the same due time; the subject's name is `Marked`, so a row of the other tenant
# is visible. The composite keys (tenantId plus the key) let the two tenants share them.
_DUE: Final = datetime(2026, 10, 24, 14, 21, tzinfo=UTC)
_SUBJECT: Final = SeedNode(
    "subject",
    ("Resource", "HealthcareService"),
    {"id": "svc-1", "key": "HealthcareService/svc-1", "name": Marked("UCR West")},
)
_WORK_ONE: Final = SeedNode(
    "one",
    ("ScheduledWork",),
    {
        "id": "work-1",
        "kind": "reminder",
        "dueAt": _DUE,
        "sequenceNumber": 1,
        "status": "scheduled",
    },
)
_WORK_TWO: Final = SeedNode(
    "two",
    ("ScheduledWork",),
    {
        "id": "work-2",
        "kind": "phone-task",
        "dueAt": _DUE,
        "sequenceNumber": 2,
        "status": "scheduled",
    },
)
_WORK_SEED: Final = TenantSeed(
    nodes=(_SUBJECT, _WORK_ONE, _WORK_TWO),
    rels=(SeedRel("one", "ABOUT", "subject"), SeedRel("two", "ABOUT", "subject")),
)
_ROW_OF_ONE: Final = {
    "id": "work-1",
    "kind": "reminder",
    "aboutId": "HealthcareService/svc-1",
    "sequenceNumber": 1,
    "status": "scheduled",
}

_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-WORK-GET": Scenario(
        "read a scheduled work item and its subject",
        seed=_WORK_SEED,
        params={"id": "work-1"},
        lookup=("id",),
        expect=Expect(rows=(_ROW_OF_ONE,)),
    ),
    "Q-WORK-ADD": Scenario(
        "store a new work item about a subject the tenant already holds",
        seed=TenantSeed(nodes=(_SUBJECT,)),
        params={
            "id": "work-new",
            "kind": "reminder",
            "dueAt": _DUE,
            "sequenceNumber": 3,
            "status": "scheduled",
            "aboutId": "HealthcareService/svc-1",
        },
        new=("id", "kind", "dueAt", "sequenceNumber", "status"),
        expect=Expect(
            rows=({"added": 1},),
            nodes={"ScheduledWork": 1},
            rels={"ABOUT": 1},
            after=(NodeSpec(("ScheduledWork",), {"id": "work-new", "kind": "reminder"}),),
        ),
    ),
    "Q-WORK-SAVE": Scenario(
        "save the status of a scheduled work item",
        seed=_WORK_SEED,
        params={
            "id": "work-1",
            "kind": "reminder",
            "dueAt": _DUE,
            "sequenceNumber": 1,
            "status": "done",
        },
        lookup=("id",),
        new=("status",),
        expect=Expect(
            rows=({"saved": 1},),
            after=(NodeSpec(("ScheduledWork",), {"id": "work-1", "status": "done"}),),
        ),
    ),
    "Q-WORK-FOR-ABOUT": Scenario(
        "list the work items about a subject, in due order",
        seed=_WORK_SEED,
        params={"aboutId": "HealthcareService/svc-1", "kind": None},
        lookup=("aboutId",),
        expect=Expect(
            rows=(
                _ROW_OF_ONE,
                {
                    "id": "work-2",
                    "kind": "phone-task",
                    "aboutId": "HealthcareService/svc-1",
                    "sequenceNumber": 2,
                    "status": "scheduled",
                },
            ),
        ),
    ),
}

REGISTRY.register(
    NamedQuery(
        id="Q-WORK-GET",
        cypher=(
            f"MATCH (w:ScheduledWork {{id: $id, tenantId: $tenant}})-[:ABOUT]->"
            f"(s:Resource {{tenantId: $tenant}}) RETURN {_FIELDS}"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-WORK-GET"],
    )
)
REGISTRY.register(
    NamedQuery(
        id="Q-WORK-ADD",
        cypher=(
            "MERGE (w:ScheduledWork {id: $id, tenantId: $tenant}) "
            "ON CREATE SET w.kind = $kind, w.dueAt = $dueAt, "
            "w.sequenceNumber = $sequenceNumber, w.status = $status "
            "MERGE (s:Resource {key: $aboutId, tenantId: $tenant}) "
            "ON CREATE SET s.placeholder = true "
            "MERGE (w)-[:ABOUT]->(s) "
            "RETURN count(w) AS added"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-WORK-ADD"],
    )
)
REGISTRY.register(
    NamedQuery(
        id="Q-WORK-SAVE",
        cypher=(
            "MATCH (w:ScheduledWork {id: $id, tenantId: $tenant}) "
            "SET w.id = w.id "
            "WITH w "
            "SET w.kind = $kind, w.dueAt = $dueAt, w.sequenceNumber = $sequenceNumber, "
            "w.status = CASE WHEN w.status = 'scheduled' THEN $status ELSE w.status END "
            "RETURN count(w) AS saved"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-WORK-SAVE"],
    )
)
REGISTRY.register(
    NamedQuery(
        id="Q-WORK-FOR-ABOUT",
        cypher=(
            "MATCH (w:ScheduledWork {tenantId: $tenant})-[:ABOUT]->"
            "(s:Resource {key: $aboutId, tenantId: $tenant}) "
            "WHERE $kind IS NULL OR w.kind = $kind "
            f"WITH w, s ORDER BY w.dueAt, w.id RETURN {_FIELDS}"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-WORK-FOR-ABOUT"],
    )
)


def _as_utc(stored: Any) -> datetime:
    """A stored dueAt as a UTC datetime. The driver returns a Neo4j DateTime with its offset."""
    native: datetime = stored.to_native() if hasattr(stored, "to_native") else stored
    return native.astimezone(UTC)


def _from_row(row: dict[str, Any]) -> ScheduledWork:
    return ScheduledWork(
        id=row["id"],
        kind=WorkKind(row["kind"]),
        due_at=_as_utc(row["dueAt"]),
        about_id=row["aboutId"],
        sequence_number=row["sequenceNumber"],
        status=row["status"],
    )


def _params(work: ScheduledWork) -> dict[str, Any]:
    return {
        "id": work.id,
        "kind": work.kind.value,
        "dueAt": work.due_at.astimezone(UTC),
        "sequenceNumber": work.sequence_number,
        "status": work.status,
        "aboutId": work.about_id,
    }


class Neo4jScheduledWorkRepository:
    def __init__(self, tx: ScopedTx) -> None:
        self._tx = tx

    async def _rows(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        return await run_query(self._tx, REGISTRY.get(query_id), **params)

    async def add(self, work: ScheduledWork) -> None:
        existing = await self._rows("Q-WORK-GET", id=work.id)
        if existing:
            if _from_row(existing[0]) != work:
                raise Conflict(f"scheduled work {work.id} is already stored with other values")
            return
        await self._rows("Q-WORK-ADD", **_params(work))

    async def get(self, id: str) -> ScheduledWork:
        rows = await self._rows("Q-WORK-GET", id=id)
        if not rows:
            raise NotFound(f"scheduled work {id} is not stored")
        return _from_row(rows[0])

    async def for_about(self, about_id: str, kind: WorkKind | None = None) -> list[ScheduledWork]:
        rows = await self._rows(
            "Q-WORK-FOR-ABOUT", aboutId=about_id, kind=None if kind is None else kind.value
        )
        return [_from_row(row) for row in rows]

    async def save(self, work: ScheduledWork) -> None:
        rows = await self._rows("Q-WORK-SAVE", **_params(work))
        if not rows or rows[0]["saved"] == 0:
            raise NotFound(f"scheduled work {work.id} is not stored")
