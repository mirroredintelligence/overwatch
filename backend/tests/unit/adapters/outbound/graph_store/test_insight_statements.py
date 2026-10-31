"""The browser-insight statements (W9F) are registered, tenant-scoped and carry scenarios that
validate (no Neo4j needed), and the schema they lean on is in the insight migrations.

The generated two-tenant test (tests/integration/graph_store/test_tenant_isolation.py) runs each
one on a real Neo4j; this file checks the parts that can be checked without it.
"""

import re

import pytest

import diucs.adapters.outbound.graph_store.insight_repository  # noqa: F401  (registers them)
from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_insight import INSIGHT_MIGRATIONS
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario

WRITE_IDS = [
    "Q-INSIGHT-SEEN",
    "Q-INSIGHT-FUNNEL-ADVANCE",
    "Q-INSIGHT-ADD-USAGE",
    "Q-INSIGHT-ADD-FRICTION",
    "Q-INSIGHT-ADD-ROUTE",
    "Q-INSIGHT-ADD-FUNNEL",
    "Q-INSIGHT-ADD-MEASURE",
    "Q-INSIGHT-ADD-RELEASE",
    "Q-INSIGHT-PURGE-SEEN",
]
READ_IDS = ["Q-INSIGHT-READ-MEASURE", "Q-INSIGHT-READ-RELEASE", "Q-INSIGHT-READ-PIPELINE"]
IDS = sorted([*WRITE_IDS, *READ_IDS])
_NODE = re.compile(r"\(\w*:\w+\s*\{([^{}]*)\}\)")


@pytest.mark.parametrize("query_id", IDS)
def test_the_statement_is_registered_with_a_tenant_predicate_and_a_valid_scenario(
    query_id: str,
) -> None:
    query = REGISTRY.get(query_id)

    assert "$tenant" in query.cypher
    assert validate_scenario(query_id, query.scenario) == []


@pytest.mark.parametrize("query_id", IDS)
def test_every_node_the_statement_names_carries_the_tenant(query_id: str) -> None:
    nodes = _NODE.findall(REGISTRY.get(query_id).cypher)

    assert nodes, "the statement names no node with properties"
    for properties in nodes:
        assert "tenantId: $tenant" in properties, query_id


def test_the_writes_are_writes_and_the_reads_are_reads() -> None:
    for query_id in WRITE_IDS:
        assert REGISTRY.get(query_id).mode == "write", query_id
    for query_id in READ_IDS:
        assert REGISTRY.get(query_id).mode == "read", query_id


def test_a_statement_takes_the_nodes_lock_before_it_reads_a_count_it_adds_to() -> None:
    for query_id in WRITE_IDS:
        cypher = REGISTRY.get(query_id).cypher
        if "ADD" in query_id or query_id in {"Q-INSIGHT-SEEN", "Q-INSIGHT-FUNNEL-ADVANCE"}:
            assert re.search(r"SET (\w+)\.date = \1\.date", cypher), query_id


def test_no_statement_takes_text_it_could_store_beyond_the_fixed_fields() -> None:
    for query_id in IDS:
        cypher = REGISTRY.get(query_id).cypher.lower()
        for word in ("sessionid", "session.id", "properties(", "+= "):
            assert word not in cypher, (query_id, word)


def test_the_insight_migrations_are_the_block_0195_to_0196() -> None:
    assert [m.id for m in INSIGHT_MIGRATIONS] == ["0195_insight_keys", "0196_insight_indexes"]
    assert {m.id for m in INSIGHT_MIGRATIONS} <= {m.id for m in MIGRATIONS}


def test_every_label_the_counters_write_has_a_composite_key_with_the_tenant() -> None:
    text = " ".join(
        statement for migration in INSIGHT_MIGRATIONS for statement in migration.statements
    )
    for label in (
        "FunnelDaily",
        "FrictionDaily",
        "ElementUsageDaily",
        "RouteDaily",
        "QueryStatDaily",
        "MeasureDaily",
        "ReleaseDaily",
        "TallySeen",
    ):
        match = re.search(rf"\(n:{label}\) REQUIRE \(([^)]*)\) IS UNIQUE", text)
        assert match is not None, label
        assert match.group(1).split(", ")[0] == "n.tenantId", label


def test_the_friction_key_holds_the_route_and_each_migration_is_one_schema_statement() -> None:
    text = " ".join(s for m in INSIGHT_MIGRATIONS for s in m.statements)
    friction = re.search(r"\(n:FrictionDaily\) REQUIRE \(([^)]*)\)", text)

    assert friction is not None and "n.route" in friction.group(1)
    for migration in INSIGHT_MIGRATIONS:
        for statement in migration.statements:
            assert statement.startswith(("CREATE CONSTRAINT", "CREATE INDEX"))
            assert "IF NOT EXISTS" in statement
