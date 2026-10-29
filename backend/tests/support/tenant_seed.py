"""The mirror seed and the snapshots of the generated two-tenant test (TEN-004, DEC-150).

`seed_tenant` writes one tenant's copy of a scenario's seed: the same nodes and keys for every
tenant, with every node stamped `tenantId` and `seedMarker`. This is test code, the one place that
creates nodes with raw Cypher; each statement carries `$tenant`. `snapshot` reads one tenant's
whole subgraph and `digest` reduces it to a hash, so "tenant B's graph is unchanged" is a
comparison of two strings. `invariant_breaks` is the audit's invariant query: no node without a
tenant, no relationship between two tenants.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Final

from neo4j import AsyncDriver, AsyncManagedTransaction, AsyncTransaction
from neo4j.time import Date, DateTime, Duration, Time

from diucs.adapters.outbound.graph_store.scenario import Slot, TenantSeed, render
from tests.support.neo4j import read_tx, write_tx

# Labels a node may carry without a tenantId: the migration record, and the registry nodes of the
# network design (DEC-132), which are the tenants' and the network's own.
UNSTAMPED_OK: Final = frozenset(
    {"Migration", "Tenant", "TenantNumber", "Network", "NetworkMembership", "Grant"}
)

_IDENTIFIER: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class Node:
    labels: tuple[str, ...]
    props: Mapping[str, Any] = field(default_factory=dict, hash=False)


@dataclass(frozen=True, slots=True)
class Rel:
    start: Node
    type: str
    end: Node
    props: Mapping[str, Any] = field(default_factory=dict, hash=False)


@dataclass(frozen=True, slots=True)
class Snapshot:
    nodes: tuple[Node, ...] = ()
    rels: tuple[Rel, ...] = ()


_TIME: Final = "<time>"


def _plain(value: Any, mask_times: bool) -> Any:
    """A JSON-ready value: Neo4j and Python times become ISO text (or a fixed word when masked);
    sequences become lists."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, DateTime | Date | Time | Duration | datetime | date | time):
        if mask_times:
            return _TIME
        if isinstance(value, Duration):
            return value.iso_format()
        if isinstance(value, DateTime | Date | Time):
            return value.to_native().isoformat()
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _plain(item, mask_times) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item, mask_times) for item in value]
    if isinstance(value, set | frozenset):
        return sorted(
            (_plain(item, mask_times) for item in value), key=lambda item: canonical(item)
        )
    raise TypeError(f"a value of type {type(value).__name__} cannot be written as canonical JSON")


def canonical(value: Any, *, mask_times: bool = False) -> str:
    """Compact JSON with sorted keys. A datetime, Python or Neo4j, is its ISO text with the offset,
    so the same instant in the same zone is the same text on both sides. With `mask_times` every
    time is the same word, for comparing two runs of a statement that stamps its own time."""
    return json.dumps(
        _plain(value, mask_times), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def seed_statement(seed: TenantSeed, slot: Slot) -> tuple[str, dict[str, Any]]:
    """One Cypher statement that creates the seed for one tenant, and its parameters (`marker` and
    one property map per node). The caller adds `tenant`. Every node gets `tenantId` and
    `seedMarker` after its properties, so nothing in the seed can set either. Labels and
    relationship types are checked as plain identifiers, because they are written into the text."""
    index = {node.ref: position for position, node in enumerate(seed.nodes)}
    lines: list[str] = []
    params: dict[str, Any] = {"marker": slot}
    for position, node in enumerate(seed.nodes):
        if not node.labels or any(_IDENTIFIER.fullmatch(label) is None for label in node.labels):
            raise ValueError("a seed node needs label names that are plain identifiers")
        lines.append(
            f"CREATE (n{position}:{':'.join(node.labels)}) SET n{position} = $p{position} "
            f"SET n{position}.tenantId = $tenant, n{position}.seedMarker = $marker"
        )
        params[f"p{position}"] = render(dict(node.props), slot)
    for rel in seed.rels:
        if _IDENTIFIER.fullmatch(rel.type) is None:
            raise ValueError("a seed relationship type name must be a plain identifier")
        if rel.start not in index or rel.end not in index:
            raise ValueError("a seed relationship names an unknown ref")
        lines.append(f"CREATE (n{index[rel.start]})-[:{rel.type}]->(n{index[rel.end]})")
    return " ".join(lines), params


async def seed_tenant(driver: AsyncDriver, tenant: str, slot: Slot, seed: TenantSeed) -> None:
    """Write one tenant's copy of the seed in one committed transaction, then check that no node in
    the graph is unstamped (the seed's own work, and anything it was written beside)."""
    cypher, params = seed_statement(seed, slot)

    async def write(tx: AsyncManagedTransaction) -> None:
        result = await tx.run(cypher, tenant=tenant, **params)
        await result.consume()

    await write_tx(driver, write)

    async def check(tx: AsyncManagedTransaction) -> list[str]:
        return (await invariant_breaks(tx))[0]

    unstamped = await read_tx(driver, check)
    if unstamped:
        raise AssertionError(f"the graph holds unstamped nodes after seeding: {unstamped}")


async def snapshot(tx: AsyncManagedTransaction | AsyncTransaction, tenant: str) -> Snapshot:
    """Every node that carries `tenant`, and every relationship among them."""
    node_rows = await (
        await tx.run(
            "MATCH (n {tenantId: $tenant}) "
            "RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props",
            tenant=tenant,
        )
    ).data()
    nodes = {
        str(row["id"]): Node(tuple(sorted(row["labels"])), dict(row["props"])) for row in node_rows
    }
    rel_rows = await (
        await tx.run(
            "MATCH (a {tenantId: $tenant})-[r]->(b {tenantId: $tenant}) "
            "RETURN elementId(a) AS start, type(r) AS type, properties(r) AS props, "
            "elementId(b) AS end",
            tenant=tenant,
        )
    ).data()
    rels = tuple(
        Rel(nodes[str(row["start"])], str(row["type"]), nodes[str(row["end"])], dict(row["props"]))
        for row in rel_rows
    )
    return Snapshot(tuple(nodes.values()), rels)


def _node_text(node: Node, mask_times: bool) -> str:
    return canonical([sorted(node.labels), node.props], mask_times=mask_times)


def digest(snapshot: Snapshot, *, mask_times: bool = False) -> str:
    """SHA-256 of the sorted nodes and the sorted relationships (each as its two end nodes, its
    type and its properties). The same data in any order is the same digest. With `mask_times`
    the times in it do not count (see `canonical`)."""
    nodes = sorted(_node_text(node, mask_times) for node in snapshot.nodes)
    rels = sorted(
        canonical(
            [
                _node_text(rel.start, mask_times),
                rel.type,
                rel.props,
                _node_text(rel.end, mask_times),
            ],
            mask_times=mask_times,
        )
        for rel in snapshot.rels
    )
    return hashlib.sha256(canonical([nodes, rels]).encode("utf-8")).hexdigest()


async def invariant_breaks(
    tx: AsyncManagedTransaction | AsyncTransaction,
) -> tuple[list[str], list[str]]:
    """The labels of nodes that have no tenantId (except the registry labels), and the types of
    relationships that join two nodes of different tenants. Both empty means the invariants hold."""
    unstamped = await (
        await tx.run(
            "MATCH (n) WHERE n.tenantId IS NULL AND NOT any(l IN labels(n) WHERE l IN $ok) "
            "RETURN DISTINCT labels(n) AS labels LIMIT 10",
            ok=sorted(UNSTAMPED_OK),
        )
    ).data()
    crossing = await (
        await tx.run(
            "MATCH (a)-[r]->(b) WHERE a.tenantId IS NOT NULL AND b.tenantId IS NOT NULL "
            "AND a.tenantId <> b.tenantId RETURN DISTINCT type(r) AS type LIMIT 10"
        )
    ).data()
    return (
        [":".join(sorted(row["labels"])) for row in unstamped],
        [str(row["type"]) for row in crossing],
    )
