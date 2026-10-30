"""The statement that finds the district Locations a visiting service can reuse (U27): registered,
a read, tenant-scoped on every node, and given a scenario for the generated two-tenant test."""

import re

from diucs.adapters.outbound.graph_store import registration_repository  # registers the queries
from diucs.adapters.outbound.graph_store.queries import REGISTRY

QUERY_ID = "Q-REG-DISTRICT-LOCATIONS"


def test_the_statement_is_a_registered_read_with_a_scenario() -> None:
    assert registration_repository is not None
    query = REGISTRY.get(QUERY_ID)
    assert query.mode == "read"
    assert query.scenario is not None


def test_every_node_it_matches_names_the_tenant() -> None:
    cypher = REGISTRY.get(QUERY_ID).cypher
    nodes = re.findall(r"\(\w*:\w+[^)]*\)", cypher)
    assert len(nodes) == 2
    assert all("tenantId: $tenant" in node for node in nodes), cypher


def test_it_finds_kind_locations_of_the_district_type_by_name_and_never_by_label_alone() -> None:
    cypher = REGISTRY.get(QUERY_ID).cypher
    assert "mode: 'kind'" in cypher
    assert "$names" in cypher
    assert "$system" in cypher and "$code" in cypher
