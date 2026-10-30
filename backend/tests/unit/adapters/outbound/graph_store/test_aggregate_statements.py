"""The O08 statements are registered, tenant-scoped and carry scenarios that validate (no Neo4j
needed).

The generated two-tenant test (tests/integration/graph_store/test_tenant_isolation.py) runs each
one on a
real Neo4j; this file checks the parts that can be checked without it.
"""

import re

import pytest

import diucs.adapters.outbound.graph_store.aggregate_repository  # noqa: F401  (registers the statements)
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario
from diucs.adapters.outbound.graph_store.unconverted import UNCONVERTED

AGG_IDS = sorted(
    [
        "Q-AGG-CLEAR-FUNNEL",
        "Q-AGG-CLEAR-FRICTION",
        "Q-AGG-CLEAR-USAGE",
        "Q-AGG-CLEAR-ROUTE",
        "Q-AGG-CLEAR-QUERY",
        "Q-AGG-WRITE-FUNNEL",
        "Q-AGG-WRITE-FRICTION",
        "Q-AGG-WRITE-USAGE",
        "Q-AGG-WRITE-ROUTE",
        "Q-AGG-WRITE-QUERY",
        "Q-AGG-READ-FUNNEL",
        "Q-AGG-READ-FRICTION",
        "Q-AGG-READ-USAGE",
        "Q-AGG-READ-ROUTE",
        "Q-AGG-READ-QUERY",
    ]
)
_NODE = re.compile(r"\(\w*:\w+\s*\{([^{}]*)\}\)")


@pytest.mark.parametrize("query_id", AGG_IDS)
def test_the_statement_is_registered_with_a_tenant_predicate_and_a_valid_scenario(
    query_id: str,
) -> None:
    query = REGISTRY.get(query_id)

    assert "$tenant" in query.cypher
    assert validate_scenario(query_id, query.scenario) == []


@pytest.mark.parametrize("query_id", AGG_IDS)
def test_every_node_the_statement_names_carries_the_tenant(query_id: str) -> None:
    query = REGISTRY.get(query_id)
    nodes = _NODE.findall(query.cypher)

    assert nodes, "the statement names no node with properties"
    for properties in nodes:
        assert "tenantId: $tenant" in properties, query_id


@pytest.mark.parametrize("query_id", AGG_IDS)
def test_the_aggregate_statements_are_not_on_the_ratchet(query_id: str) -> None:
    assert query_id not in UNCONVERTED


def test_the_write_and_clear_statements_are_writes_and_the_reads_are_reads() -> None:
    for query_id in AGG_IDS:
        expected = "read" if "-READ-" in query_id else "write"
        assert REGISTRY.get(query_id).mode == expected, query_id
