"""The tenant invariant check on Neo4j (TEN-031, DEC-134 item 11, audit A 3.3).

Neo4j Community cannot require `tenantId`, and a composite constraint ignores a node that has none.
A node written without one is invisible to every tenant statement, so two global statements count
what the database cannot refuse: the nodes that carry no tenant (outside the registry labels,
which carry none by design) and the relationships that join two scopes. They read the whole graph,
so they are on the allowlist with a digest pin (DEC-163), name no label, and return a label set or
a relationship type and a count and nothing else (`GLOBAL_WHOLE_GRAPH_IDS`).

Both run through `run_global_query` in one read transaction, with no scope bound and none sent:
the check is the platform's, not a tenant's. The registry labels it leaves out come in as the one
parameter `registryLabels`, from the same list the tenant migrations use (`REGISTRY_LABELS`), so
there is one list. The text of each statement is the text of the migration helper's queries, so the
two cannot drift apart.
"""

from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.driver import run_global_query
from diucs.adapters.outbound.graph_store.migrations_tenant import (
    CROSS_SCOPE_RELATIONSHIPS_QUERY,
    REGISTRY_LABELS,
    UNSTAMPED_NODES_QUERY,
)
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.application.ports.outbound.invariants import (
    CrossScope,
    InvariantReport,
    UnstampedNodes,
)

UNSTAMPED_QUERY_ID = "Q-INVARIANT-UNSTAMPED"
CROSS_SCOPE_QUERY_ID = "Q-INVARIANT-CROSS-SCOPE"

_UNSTAMPED = NamedQuery(
    id=UNSTAMPED_QUERY_ID, cypher=UNSTAMPED_NODES_QUERY, mode="read", scope="global"
)
_CROSS_SCOPE = NamedQuery(
    id=CROSS_SCOPE_QUERY_ID, cypher=CROSS_SCOPE_RELATIONSHIPS_QUERY, mode="read", scope="global"
)
REGISTRY.register(_UNSTAMPED)
REGISTRY.register(_CROSS_SCOPE)


def _unstamped(rows: list[dict[str, Any]]) -> tuple[UnstampedNodes, ...]:
    groups = [UnstampedNodes(tuple(sorted(row["labels"])), int(row["n"])) for row in rows]
    return tuple(sorted(groups, key=lambda group: group.labels))


def _cross_scope(rows: list[dict[str, Any]]) -> tuple[CrossScope, ...]:
    groups = [CrossScope(str(row["type"]), int(row["n"])) for row in rows]
    return tuple(sorted(groups, key=lambda group: group.relationship_type))


class Neo4jTenantInvariants:
    """`TenantInvariants` over the process's one connection."""

    def __init__(self, connection: Neo4jConnection) -> None:
        self._connection = connection

    async def check(self) -> InvariantReport:
        """Count both invariants in one read transaction. Raises what the driver raises when Neo4j
        does not answer; it never reports a clean graph it did not read."""

        async def read_invariants(tx: AsyncManagedTransaction) -> InvariantReport:
            unstamped = await run_global_query(tx, _UNSTAMPED, registryLabels=list(REGISTRY_LABELS))
            crossing = await run_global_query(tx, _CROSS_SCOPE)
            return InvariantReport(_unstamped(unstamped), _cross_scope(crossing))

        return await self._connection.run_read(read_invariants)
