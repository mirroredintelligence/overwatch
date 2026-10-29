"""The support statements (O06) are registered named statements, each tenant-bound and each with a
scenario that the registry validated at import. Pure: no Neo4j is started."""

import re

import pytest

from diucs.adapters.outbound.graph_store import support_repository  # noqa: F401  (registers)
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario

SUPPORT_IDS = (
    "Q-SUPPORT-SESSION-ENSURE",
    "Q-SUPPORT-SESSION-EXISTS",
    "Q-SUPPORT-SESSION-SHARED-BY",
    "Q-SUPPORT-CODE-ADD",
    "Q-SUPPORT-CODE-GET",
    "Q-SUPPORT-CODES-STOP",
    "Q-SUPPORT-ACCESSES-END",
    "Q-SUPPORT-ACCESS-ADD",
    "Q-SUPPORT-ACCESS-LIST",
)

_NODE = re.compile(r"\((?:\w+)?:(\w+)\s*(\{[^}]*\})?\)")


@pytest.mark.parametrize("query_id", SUPPORT_IDS)
def test_the_statement_is_registered(query_id: str) -> None:
    assert REGISTRY.get(query_id).id == query_id


@pytest.mark.parametrize("query_id", SUPPORT_IDS)
def test_every_node_the_statement_matches_or_writes_is_tenant_bound(query_id: str) -> None:
    cypher = REGISTRY.get(query_id).cypher
    nodes = [(label, props or "") for label, props in _NODE.findall(cypher)]

    assert nodes, "the statement names no node"
    for label, props in nodes:
        assert "tenantId: $tenant" in props, f"{query_id}: {label} is not tenant-bound"


@pytest.mark.parametrize("query_id", SUPPORT_IDS)
def test_the_statement_has_a_scenario_the_registry_accepts(query_id: str) -> None:
    query = REGISTRY.get(query_id)

    assert query.scenario is not None
    assert validate_scenario(query_id, query.scenario) == []


@pytest.mark.parametrize("query_id", SUPPORT_IDS)
def test_no_support_statement_is_global(query_id: str) -> None:
    assert REGISTRY.get(query_id).scope != "global"


def test_the_statements_never_return_the_practitioner_name() -> None:
    for query_id in SUPPORT_IDS:
        assert "displayName" not in REGISTRY.get(query_id).cypher
