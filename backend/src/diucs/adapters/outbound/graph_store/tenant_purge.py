"""A tenant's data on Neo4j for its export and its purge (TEN-074, DEC-136 item 10, audit F 2.4,
H-T18).

Six statements of the bound tenant, each `tenantId: $tenant` on every node (no tenant is a
parameter), run on a scoped transaction outside a unit of work (`Neo4jConnection.run_scoped_*`: the
operator's use cases hold no unit of work while they loop):

- `Q-TENANT-DATA-COUNTS`, `Q-TENANT-DATA-NODES`, `Q-TENANT-DATA-RELS` read: counts by label set, a
  page of the nodes of one label set, a page of the relationships between the tenant's own nodes;
- `Q-TENANT-PURGE-DATA` deletes a batch of the tenant's nodes that are not the audit chain;
  `Q-TENANT-PURGE-AUDIT` deletes a batch of the audit chain, and only when nothing else of the
  tenant is left (the guard is in the statement, so a caller that asks too early deletes nothing);
- the audit head is the audit port's own `Q-AUDIT-HEAD`.

A purge deletes by `tenantId` and by nothing else, so another tenant's data and the network scope
are out of its reach (hazard H-T18), and the registry's records (the tenant, its numbers, the
networks and their memberships) have no `tenantId` and are not touched: they are the platform's
(`TenantRegistry`, `NetworkRegistry`). The audit labels are the scope-generic set of DEC-540, named
once, so a new label of a tenant is data and goes in the first batches whatever it is called.
"""

from collections.abc import Sequence
from typing import Any, Final

from neo4j.time import Date, DateTime, Duration, Time

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
)
from diucs.application.ports.outbound.tenant_export import (
    AuditHeadState,
    ExportedNode,
    ExportedRelationship,
    LabelCount,
)
from diucs.domain.errors import ValidationFailed

BATCH_MAX: Final = 5000
# The nodes that make up an audit chain: the head, the links and what they point at.
AUDIT_LABELS: Final = ("AuditEvent", "ChainLink", "AuditHead", "Snapshot", "AuditRef")
_NOT_AUDIT: Final = " AND ".join(f"NOT n:{label}" for label in AUDIT_LABELS)
_IS_AUDIT: Final = " OR ".join(f"n:{label}" for label in AUDIT_LABELS)
_PROPERTY_STRIPPED: Final = frozenset({"tenantId", "seedMarker"})

_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "service",
            ("Resource", "HealthcareService"),
            {"id": "svc-1", "key": "HealthcareService/svc-1", "name": Marked("Ward")},
        ),
        SeedNode(
            "service-2",
            ("Resource", "HealthcareService"),
            {"id": "svc-2", "key": "HealthcareService/svc-2", "name": Marked("Clinic")},
        ),
        SeedNode(
            "entry",
            ("AuditEvent", "ChainLink"),
            {"id": "aud-1", "action": "C", "useCase": Marked("Seed"), "seq": 1},
        ),
    ),
    rels=(SeedRel("service", "HAS_VERSION", "service-2"),),
)

_COUNTS = NamedQuery(
    id="Q-TENANT-DATA-COUNTS",
    cypher=(
        "MATCH (n {tenantId: $tenant}) UNWIND labels(n) AS label "
        "WITH n, label ORDER BY label WITH n, collect(label) AS labels "
        "RETURN labels, count(*) AS total ORDER BY labels"
    ),
    mode="read",
    scenario=Scenario(
        "count the tenant's nodes by label set, and nobody else's",
        seed=_SEED,
        expect=Expect(
            rows=(
                {"labels": ["HealthcareService", "Resource"], "total": 2},
                {"labels": ["AuditEvent", "ChainLink"], "total": 1},
            )
        ),
    ),
)
_NODES = NamedQuery(
    id="Q-TENANT-DATA-NODES",
    cypher=(
        "MATCH (n {tenantId: $tenant}) "
        "WHERE size(labels(n)) = size($labels) AND all(l IN $labels WHERE l IN labels(n)) "
        "AND ($after IS NULL OR elementId(n) > $after) "
        "RETURN elementId(n) AS ref, properties(n) AS props ORDER BY ref LIMIT $limit"
    ),
    mode="read",
    scenario=Scenario(
        "read a page of the tenant's nodes of one label set",
        seed=_SEED,
        params={"labels": ["Resource", "HealthcareService"], "after": None, "limit": 10},
        new=("labels", "after", "limit"),
        expect=Expect(
            rows=({"props": {"name": Marked("Ward")}}, {"props": {"name": Marked("Clinic")}})
        ),
    ),
)
_RELS = NamedQuery(
    id="Q-TENANT-DATA-RELS",
    cypher=(
        "MATCH (a {tenantId: $tenant})-[r]->(b {tenantId: $tenant}) "
        "WHERE $after IS NULL OR elementId(r) > $after "
        "RETURN elementId(r) AS ref, type(r) AS type, elementId(a) AS start, elementId(b) AS end, "
        "properties(r) AS props ORDER BY ref LIMIT $limit"
    ),
    mode="read",
    scenario=Scenario(
        "read a page of the relationships between the tenant's own nodes",
        seed=_SEED,
        params={"after": None, "limit": 10},
        new=("after", "limit"),
        expect=Expect(rows=({"type": "HAS_VERSION"},)),
    ),
)
_PURGE_DATA = NamedQuery(
    id="Q-TENANT-PURGE-DATA",
    cypher=(
        f"MATCH (n {{tenantId: $tenant}}) WHERE {_NOT_AUDIT} "
        "WITH n LIMIT $limit DETACH DELETE n RETURN count(*) AS deleted"
    ),
    mode="write",
    scenario=Scenario(
        "delete a batch of the tenant's data nodes and leave its audit chain",
        seed=_SEED,
        params={"limit": 10},
        new=("limit",),
        expect=Expect(rows=({"deleted": 2},), nodes={"HealthcareService": -2, "Resource": -2}),
    ),
)
_PURGE_AUDIT = NamedQuery(
    id="Q-TENANT-PURGE-AUDIT",
    cypher=(
        f"MATCH (m {{tenantId: $tenant}}) WHERE {_NOT_AUDIT.replace('n:', 'm:')} "
        "WITH count(m) AS others WHERE others = 0 "
        f"MATCH (n {{tenantId: $tenant}}) WHERE {_IS_AUDIT} "
        "WITH n LIMIT $limit DETACH DELETE n RETURN count(*) AS deleted"
    ),
    mode="write",
    scenario=Scenario(
        "delete a batch of the tenant's audit chain only when nothing else of the tenant is left",
        seed=TenantSeed(
            nodes=(
                SeedNode(
                    "entry",
                    ("AuditEvent", "ChainLink"),
                    {"id": "aud-1", "action": "C", "useCase": Marked("Seed"), "seq": 1},
                ),
                SeedNode(
                    "entry-2",
                    ("AuditEvent", "ChainLink"),
                    {"id": "aud-2", "action": "C", "useCase": Marked("Seed"), "seq": 2},
                ),
            )
        ),
        params={"limit": 10},
        new=("limit",),
        expect=Expect(rows=({"deleted": 2},), nodes={"AuditEvent": -2, "ChainLink": -2}),
    ),
)
for _query in (_COUNTS, _NODES, _RELS, _PURGE_DATA, _PURGE_AUDIT):
    REGISTRY.register(_query)


def _batch(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= BATCH_MAX:
        raise ValidationFailed("limit", f"must be a whole number from 1 to {BATCH_MAX}")
    return limit


def _plain(value: Any) -> Any:
    """A driver value as plain data: Neo4j's own temporal types as ISO 8601 text (a date time keeps
    its zone), lists and maps walked."""
    if isinstance(value, DateTime | Date | Time):
        return str(value.iso_format())
    if isinstance(value, Duration):
        return str(value)
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    return value


def _clean(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _plain(value) for key, value in properties.items() if key not in _PROPERTY_STRIPPED
    }


class Neo4jTenantData:
    """The reader and the purger of the tenant bound now, over the process's one connection."""

    def __init__(self, connection: Neo4jConnection) -> None:
        self._connection = connection

    # ---- TenantDataReader

    async def node_counts(self) -> Sequence[LabelCount]:
        async def work(tx: Any) -> list[dict[str, Any]]:
            return await run_query(tx, _COUNTS)

        grouped: dict[tuple[str, ...], int] = {}
        for row in await self._connection.run_scoped_read(work):
            key = tuple(sorted(str(label) for label in row["labels"]))
            grouped[key] = grouped.get(key, 0) + int(row["total"])
        return [LabelCount(labels, count) for labels, count in sorted(grouped.items())]

    async def nodes(
        self, labels: tuple[str, ...], *, after: str | None, limit: int
    ) -> Sequence[ExportedNode]:
        size = _batch(limit)

        async def work(tx: Any) -> list[dict[str, Any]]:
            return await run_query(tx, _NODES, labels=list(labels), after=after, limit=size)

        return [
            ExportedNode(str(row["ref"]), _clean(dict(row["props"])))
            for row in await self._connection.run_scoped_read(work)
        ]

    async def relationships(
        self, *, after: str | None, limit: int
    ) -> Sequence[ExportedRelationship]:
        size = _batch(limit)

        async def work(tx: Any) -> list[dict[str, Any]]:
            return await run_query(tx, _RELS, after=after, limit=size)

        return [
            ExportedRelationship(
                str(row["ref"]),
                str(row["type"]),
                str(row["start"]),
                str(row["end"]),
                _clean(dict(row["props"])),
            )
            for row in await self._connection.run_scoped_read(work)
        ]

    async def audit_head(self) -> AuditHeadState | None:
        async def work(tx: Any) -> list[dict[str, Any]]:
            return await run_query(tx, REGISTRY.get("Q-AUDIT-HEAD"))

        rows = await self._connection.run_scoped_read(work)
        if not rows:
            return None
        return AuditHeadState(str(rows[0]["lastHash"]), int(rows[0]["lastSeq"]))

    # ---- TenantPurger

    async def delete_data_batch(self, limit: int) -> int:
        size = _batch(limit)

        async def work(tx: Any) -> int:
            rows = await run_query(tx, _PURGE_DATA, limit=size)
            return int(rows[0]["deleted"]) if rows else 0

        return await self._connection.run_scoped_write(work)

    async def delete_audit_batch(self, limit: int) -> int:
        size = _batch(limit)

        async def work(tx: Any) -> int:
            rows = await run_query(tx, _PURGE_AUDIT, limit=size)
            return int(rows[0]["deleted"]) if rows else 0

        return await self._connection.run_scoped_write(work)
