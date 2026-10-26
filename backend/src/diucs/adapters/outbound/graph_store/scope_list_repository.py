"""The scope list on Neo4j (P13).

The scope list is one List node, whose id is the fixed `scope-list`, with an ENTRY relationship to
each service it names (fhir-data-model.md, Scope list). It is not written through the generic
mapper: the entry facts (flag, date, reason) are relationship properties, which the mapper does not
hold (DEC-082). A service that is not written yet is created as a minimal inactive HealthcareService
through the resource store, and an existing service is never changed.

The List node is a Resource so that the Resource.id uniqueness constraint covers it: two racing
first writes cannot make two lists (lesson L90). A racing loser of that first creation is refused
with Conflict. Every save takes the list's write lock first (lesson L99), then checks, then writes,
so two saves for one service serialise and leave one entry.
"""

from datetime import date
from typing import Any, Final

from neo4j import AsyncManagedTransaction
from neo4j.exceptions import ClientError

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_repository import (
    codeable_from_fhir,
    codeable_to_fhir,
)
from diucs.domain.codes import ScopeFlag, ServiceCategory, parse_code
from diucs.domain.errors import Conflict, NotFound
from diucs.domain.model.registration import ScopeEntry

LIST_ID: Final = "scope-list"
_LIST_TITLE: Final = "Scope list"
_LIST_STATUS: Final = "current"
_SERVICE: Final = "HealthcareService"
_CONSTRAINT_VALIDATION: Final = "ConstraintValidationFailed"

_ENSURE_LIST: Final = NamedQuery(
    id="Q-SCOPE-ENSURE-LIST",
    cypher=(
        "MERGE (l:Resource:List {id: $id}) "
        "ON CREATE SET l.status = $status, l.title = $title "
        "RETURN count(l) AS lists"
    ),
    mode="write",
)
_LOCK_LIST: Final = NamedQuery(
    id="Q-SCOPE-LOCK-LIST",
    cypher="MATCH (l:List {id: $id}) SET l.id = l.id RETURN count(l) AS locked",
    mode="write",
)
_UPSERT_ENTRY: Final = NamedQuery(
    id="Q-SCOPE-UPSERT-ENTRY",
    cypher=(
        "MATCH (l:List {id: $id}), (s:HealthcareService {id: $serviceId}) "
        "MERGE (l)-[e:ENTRY]->(s) "
        "SET e.flag = $flag, e.date = $date, e.reason = $reason "
        "RETURN count(e) AS entries"
    ),
    mode="write",
)
_ENTRIES: Final = NamedQuery(
    id="Q-SCOPE-ENTRIES",
    cypher=(
        "MATCH (:List {id: $id})-[e:ENTRY]->(s:HealthcareService) "
        "RETURN s.id AS id, e.flag AS flag, e.date AS date, e.reason AS reason"
    ),
    mode="read",
)
_ENTRY_FOR: Final = NamedQuery(
    id="Q-SCOPE-ENTRY-FOR",
    cypher=(
        "MATCH (:List {id: $id})-[e:ENTRY]->(s:HealthcareService {id: $serviceId}) "
        "RETURN s.id AS id, e.flag AS flag, e.date AS date, e.reason AS reason"
    ),
    mode="read",
)


def _register(query: NamedQuery) -> None:
    if query.id not in REGISTRY.ids():
        REGISTRY.register(query)


for _query in (_ENSURE_LIST, _LOCK_LIST, _UPSERT_ENTRY, _ENTRIES, _ENTRY_FOR):
    _register(_query)


def _as_date(value: Any) -> date:
    """The driver returns Neo4j dates as its own type. ScopeEntry refuses anything that is not a
    calendar date, so a stored instant is refused there, once."""
    native: date = value.to_native() if hasattr(value, "to_native") else value
    return native


class Neo4jScopeListRepository:
    """The scope list. Built per transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def entries(self) -> list[ScopeEntry]:
        rows = await run_query(self._tx, "Q-SCOPE-ENTRIES", id=LIST_ID)
        found = [await self._entry(row) for row in rows]
        return sorted(found, key=lambda entry: (entry.name, entry.service_id))

    async def get_entry(self, service_id: str) -> ScopeEntry | None:
        rows = await run_query(self._tx, "Q-SCOPE-ENTRY-FOR", id=LIST_ID, serviceId=service_id)
        if not rows:
            return None
        return await self._entry(rows[0])

    async def save_entry(self, entry: ScopeEntry) -> None:
        await self._ensure_list()
        await self._lock_list()
        if await self._store.get(_SERVICE, entry.service_id) is None:
            await self._store.put(_minimal_service(entry), None)
        await run_query(
            self._tx,
            "Q-SCOPE-UPSERT-ENTRY",
            id=LIST_ID,
            serviceId=entry.service_id,
            flag=entry.flag.value,
            date=entry.date,
            reason=entry.reason or None,
        )

    async def _ensure_list(self) -> None:
        try:
            await run_query(
                self._tx,
                "Q-SCOPE-ENSURE-LIST",
                id=LIST_ID,
                status=_LIST_STATUS,
                title=_LIST_TITLE,
            )
        except ClientError as error:
            if str(getattr(error, "code", "")).endswith(_CONSTRAINT_VALIDATION):
                raise Conflict("the scope list was created by another request") from error
            raise

    async def _lock_list(self) -> None:
        rows = await run_query(self._tx, "Q-SCOPE-LOCK-LIST", id=LIST_ID)
        if not rows or int(rows[0]["locked"]) == 0:
            raise NotFound("scope list")

    async def _entry(self, row: dict[str, Any]) -> ScopeEntry:
        service = await self._store.get(_SERVICE, str(row["id"]))
        if service is None:
            raise NotFound("service")
        return ScopeEntry(
            service_id=str(row["id"]),
            name=str(service["name"]),
            category=codeable_from_fhir(service["category"], ServiceCategory, "category"),
            flag=parse_code(ScopeFlag, str(row["flag"])),
            date=_as_date(row["date"]),
            reason=row["reason"] or "",
        )


def _minimal_service(entry: ScopeEntry) -> dict[str, Any]:
    """The HealthcareService for a service the list names before it registers. It is inactive and
    has no profile yet; registration writes the full profile."""
    return {
        "resourceType": _SERVICE,
        "id": entry.service_id,
        "active": False,
        "name": entry.name,
        "category": codeable_to_fhir(entry.category),
    }
