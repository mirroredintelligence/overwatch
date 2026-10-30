"""The R18 ticket statements are registered, tenant-scoped and carry scenarios that validate.

No Neo4j is needed for these checks.
"""

import re

import pytest

import diucs.adapters.outbound.graph_store.support_ticket_repository  # noqa: F401
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario

TICKET_IDS = ("Q-TICKET-ADD", "Q-TICKET-GET", "Q-TICKET-APPROVE")
_NODE = re.compile(r"\(\w*:\w+\s*\{([^{}]*)\}\)")


@pytest.mark.parametrize("query_id", TICKET_IDS)
def test_a_ticket_statement_has_a_valid_scenario(query_id: str) -> None:
    query = REGISTRY.get(query_id)

    assert "$tenant" in query.cypher
    assert validate_scenario(query_id, query.scenario) == []


@pytest.mark.parametrize("query_id", TICKET_IDS)
def test_every_node_a_ticket_statement_names_carries_the_tenant(query_id: str) -> None:
    for properties in _NODE.findall(REGISTRY.get(query_id).cypher):
        assert "tenantId: $tenant" in properties, query_id


def test_the_ticket_modes_are_right() -> None:
    assert REGISTRY.get("Q-TICKET-GET").mode == "read"
    assert REGISTRY.get("Q-TICKET-ADD").mode == "write"
    assert REGISTRY.get("Q-TICKET-APPROVE").mode == "write"
