"""The four date-range statements of the week summary (U35) are tenant statements: every node
pattern they match names the tenant, each carries a scenario that validates, and each is
registered. Checked on the text, without Neo4j; the generated two-tenant test runs them on a real
database in verification."""

import re

import pytest

from diucs.adapters.outbound.graph_store import (
    booking_repository,
    capacity_repository,
    case_repository,
    communication_repository,
)
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario
from diucs.adapters.outbound.graph_store.week_scenarios import WEEK_SCENARIOS

_IDS = (
    "Q-CASE-OPENED-BETWEEN",
    "Q-CAP-BETWEEN",
    "Q-BOOK-CONFIRMED-BETWEEN",
    "Q-COMM-PROMPTS-DUE-BETWEEN",
)
_NODE = re.compile(r"\((\w*):(\w+)([^)]*)\)")


def test_the_four_statements_are_registered_by_their_repositories() -> None:
    # Importing the modules registers the statements; a missing one would fail here.
    assert case_repository and capacity_repository and booking_repository
    assert communication_repository
    assert set(_IDS) <= set(REGISTRY.ids())


@pytest.mark.parametrize("query_id", _IDS)
def test_every_node_the_statement_matches_names_the_tenant(query_id: str) -> None:
    cypher = REGISTRY.get(query_id).cypher
    nodes = _NODE.findall(cypher)
    assert nodes, "the statement matches at least one node"
    for _variable, label, props in nodes:
        assert "tenantId: $tenant" in props, f"{query_id}: a {label} node is not tenant-scoped"


@pytest.mark.parametrize("query_id", _IDS)
def test_each_statement_reads_only_and_takes_no_tenant_parameter(query_id: str) -> None:
    query = REGISTRY.get(query_id)
    assert query.mode == "read"
    assert "tenant:" not in query.cypher.replace("tenantId: $tenant", "")
    assert "$tenant" in query.cypher


@pytest.mark.parametrize("query_id", _IDS)
def test_each_statement_has_a_scenario_that_validates(query_id: str) -> None:
    query = REGISTRY.get(query_id)
    assert query.scenario is WEEK_SCENARIOS[query_id]
    assert validate_scenario(query_id, query.scenario) == []
