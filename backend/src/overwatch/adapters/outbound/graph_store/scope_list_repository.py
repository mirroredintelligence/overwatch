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

from neo4j.exceptions import ClientError

from diucs.adapters.outbound.graph_store.driver import ScopedTx, run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
)
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

# Scenarios of the converted statements (DEC-142 item 5, DEC-150, TEN-011). Both tenants hold the
# scope list `scope-list` and the service `svc-1`, with an entry from the list to the service: the
# keys are composite with the tenant (TEN-005), so both tenants share them.
_NODE_LIST: Final = SeedNode(
    "list",
    ("Resource", "List"),
    {"id": LIST_ID, "status": _LIST_STATUS, "title": _LIST_TITLE},
)
_NODE_PILOT: Final = SeedNode(
    "pilot",
    ("Resource", "HealthcareService"),
    {"id": "svc-1", "key": "HealthcareService/svc-1", "active": True, "name": Marked("Pilot")},
)
_DAY: Final = date(2026, 10, 25)
_LIST_SEED: Final = TenantSeed(nodes=(_NODE_LIST, _NODE_PILOT))
_ENTRY_SEED: Final = TenantSeed(
    nodes=(_NODE_LIST, _NODE_PILOT),
    rels=(SeedRel("list", "ENTRY", "pilot", {"flag": "in-pilot"}),),
)
_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-SCOPE-ENSURE-LIST": Scenario(
        "ensure the scope list of the tenant exists, once",
        seed=_LIST_SEED,
        params={"id": LIST_ID, "status": _LIST_STATUS, "title": _LIST_TITLE},
        lookup=("id",),
        expect=Expect(rows=({"lists": 1},)),
    ),
    "Q-SCOPE-LOCK-LIST": Scenario(
        "lock the scope list of the tenant",
        seed=_LIST_SEED,
        params={"id": LIST_ID},
        lookup=("id",),
        expect=Expect(rows=({"locked": 1},)),
    ),
    "Q-SCOPE-UPSERT-ENTRY": Scenario(
        "record the scope entry of a service in the tenant's list",
        seed=_LIST_SEED,
        params={
            "id": LIST_ID,
            "serviceId": "svc-1",
            "flag": "in-pilot",
            "date": _DAY,
            "reason": "Pilot",
        },
        lookup=("id", "serviceId"),
        new=("flag", "date", "reason"),
        expect=Expect(rows=({"entries": 1},), rels={"ENTRY": 1}),
    ),
    "Q-SCOPE-ENTRIES": Scenario(
        "list the scope entries of the tenant's list",
        seed=_ENTRY_SEED,
        params={"id": LIST_ID},
        lookup=("id",),
        expect=Expect(rows=({"id": "svc-1", "flag": "in-pilot"},)),
    ),
    "Q-SCOPE-ENTRY-FOR": Scenario(
        "read the scope entry of a service in the tenant's list",
        seed=_ENTRY_SEED,
        params={"id": LIST_ID, "serviceId": "svc-1"},
        lookup=("id", "serviceId"),
        expect=Expect(rows=({"id": "svc-1", "flag": "in-pilot"},)),
    ),
}

_ENSURE_LIST: Final = NamedQuery(
    id="Q-SCOPE-ENSURE-LIST",
    cypher=(
        "MERGE (l:Resource:List {id: $id, tenantId: $tenant}) "
        "ON CREATE SET l.status = $status, l.title = $title "
        "RETURN count(l) AS lists"
    ),
    mode="write",
    scenario=_SCENARIOS["Q-SCOPE-ENSURE-LIST"],
)
_LOCK_LIST: Final = NamedQuery(
    id="Q-SCOPE-LOCK-LIST",
    cypher=(
        "MATCH (l:List {id: $id, tenantId: $tenant}) SET l.id = l.id RETURN count(l) AS locked"
    ),
    mode="write",
    scenario=_SCENARIOS["Q-SCOPE-LOCK-LIST"],
)
_UPSERT_ENTRY: Final = NamedQuery(
    id="Q-SCOPE-UPSERT-ENTRY",
    cypher=(
        "MATCH (l:List {id: $id, tenantId: $tenant}), "
        "(s:HealthcareService {id: $serviceId, tenantId: $tenant}) "
        "MERGE (l)-[e:ENTRY]->(s) "
        "SET e.flag = $flag, e.date = $date, e.reason = $reason "
        "RETURN count(e) AS entries"
    ),
    mode="write",
    scenario=_SCENARIOS["Q-SCOPE-UPSERT-ENTRY"],
)
_ENTRIES: Final = NamedQuery(
    id="Q-SCOPE-ENTRIES",
    cypher=(
        "MATCH (:List {id: $id, tenantId: $tenant})-[e:ENTRY]->"
        "(s:HealthcareService {tenantId: $tenant}) "
        "RETURN s.id AS id, e.flag AS flag, e.date AS date, e.reason AS reason"
    ),
    mode="read",
    scenario=_SCENARIOS["Q-SCOPE-ENTRIES"],
)
_ENTRY_FOR: Final = NamedQuery(
    id="Q-SCOPE-ENTRY-FOR",
    cypher=(
        "MATCH (:List {id: $id, tenantId: $tenant})-[e:ENTRY]->"
        "(s:HealthcareService {id: $serviceId, tenantId: $tenant}) "
        "RETURN s.id AS id, e.flag AS flag, e.date AS date, e.reason AS reason"
    ),
    mode="read",
    scenario=_SCENARIOS["Q-SCOPE-ENTRY-FOR"],
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

    def __init__(self, tx: ScopedTx, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def entries(self) -> list[ScopeEntry]:
        rows = await run_query(self._tx, REGISTRY.get("Q-SCOPE-ENTRIES"), id=LIST_ID)
        found = [await self._entry(row) for row in rows]
        return sorted(found, key=lambda entry: (entry.name, entry.service_id))

    async def get_entry(self, service_id: str) -> ScopeEntry | None:
        rows = await run_query(
            self._tx, REGISTRY.get("Q-SCOPE-ENTRY-FOR"), id=LIST_ID, serviceId=service_id
        )
        if not rows:
            return None
        return await self._entry(rows[0])

    async def ensure_list(self) -> None:
        await self._ensure_list()

    async def save_entry(self, entry: ScopeEntry) -> None:
        await self._ensure_list()
        await self._lock_list()
        if await self._store.get(_SERVICE, entry.service_id) is None:
            await self._store.put(_minimal_service(entry), None)
        await run_query(
            self._tx,
            REGISTRY.get("Q-SCOPE-UPSERT-ENTRY"),
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
                REGISTRY.get("Q-SCOPE-ENSURE-LIST"),
                id=LIST_ID,
                status=_LIST_STATUS,
                title=_LIST_TITLE,
            )
        except ClientError as error:
            if str(getattr(error, "code", "")).endswith(_CONSTRAINT_VALIDATION):
                raise Conflict("the scope list was created by another request") from error
            raise

    async def _lock_list(self) -> None:
        rows = await run_query(self._tx, REGISTRY.get("Q-SCOPE-LOCK-LIST"), id=LIST_ID)
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
