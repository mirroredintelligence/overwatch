"""Neo4j repository for ScheduledWork records (P08, DEC-054).

A ScheduledWork node (id, kind, dueAt, sequenceNumber, status) has one ABOUT relationship to its
subject. The subject is matched by its resource key (`Type/id`, DEC-053). A placeholder Resource is
created only when the subject is absent. The work runs in the caller's transaction (the unit of
work), through named queries in the registry. Every dueAt is stored in UTC.

add() is safe to retry (DEC-012): adding the same record again changes nothing, and adding a
different record under an existing id is refused with Conflict.
"""

from datetime import UTC, datetime
from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery, QueryRegistry
from diucs.application.work import ScheduledWork, WorkKind
from diucs.domain.errors import Conflict, NotFound

_FIELDS = (
    "w.id AS id, w.kind AS kind, w.dueAt AS dueAt, "
    "w.sequenceNumber AS sequenceNumber, w.status AS status, s.key AS aboutId"
)

REGISTRY.register(
    NamedQuery(
        id="Q-WORK-GET",
        cypher=f"MATCH (w:ScheduledWork {{id: $id}})-[:ABOUT]->(s:Resource) RETURN {_FIELDS}",
        mode="read",
    )
)
REGISTRY.register(
    NamedQuery(
        id="Q-WORK-ADD",
        cypher=(
            "MERGE (w:ScheduledWork {id: $id}) "
            "ON CREATE SET w.kind = $kind, w.dueAt = $dueAt, "
            "w.sequenceNumber = $sequenceNumber, w.status = $status "
            "MERGE (s:Resource {key: $aboutId}) ON CREATE SET s.placeholder = true "
            "MERGE (w)-[:ABOUT]->(s) "
            "RETURN count(w) AS added"
        ),
        mode="write",
    )
)
REGISTRY.register(
    NamedQuery(
        id="Q-WORK-SAVE",
        cypher=(
            "MATCH (w:ScheduledWork {id: $id}) "
            "SET w.kind = $kind, w.dueAt = $dueAt, "
            "w.sequenceNumber = $sequenceNumber, w.status = $status "
            "RETURN count(w) AS saved"
        ),
        mode="write",
    )
)
REGISTRY.register(
    NamedQuery(
        id="Q-WORK-FOR-ABOUT",
        cypher=(
            "MATCH (w:ScheduledWork)-[:ABOUT]->(s:Resource {key: $aboutId}) "
            "WHERE $kind IS NULL OR w.kind = $kind "
            f"WITH w, s ORDER BY w.dueAt, w.id RETURN {_FIELDS}"
        ),
        mode="read",
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
    def __init__(self, tx: AsyncManagedTransaction, store: QueryRegistry = REGISTRY) -> None:
        self._tx = tx
        self._store = store

    async def _rows(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        return await run_query(self._tx, query_id, registry=self._store, **params)

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
