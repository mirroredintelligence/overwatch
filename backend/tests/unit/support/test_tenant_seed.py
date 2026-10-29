"""The mirror seed and the snapshot digest of the generated two-tenant test (TEN-004).

Pure parts only: the text and parameters of a seed statement, canonical JSON and the digest. The
seed on a real Neo4j is in tests/integration/graph_store/test_tenant_isolation.py.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store.scenario import (
    Marked,
    SeedNode,
    SeedRel,
    TenantSeed,
    Unique,
)
from tests.support.tenant_seed import Node, Rel, Snapshot, canonical, digest, seed_statement

SEED = TenantSeed(
    nodes=(
        SeedNode("t", ("Resource", "Thing"), {"id": Unique("thing-1", "resource_id"), "k": "K/1"}),
        SeedNode("d", ("Detail",), {"text": Marked("detail"), "n": 2}),
    ),
    rels=(SeedRel("d", "OF", "t"),),
)


def test_canonical_is_sorted_compact_json() -> None:
    assert canonical({"b": [1, None, True], "a": {"d": "x", "c": 2}}) == (
        '{"a":{"c":2,"d":"x"},"b":[1,null,true]}'
    )


def test_canonical_writes_python_and_neo4j_datetimes_the_same_way() -> None:
    at = datetime(2026, 10, 25, 11, 0, 5, 123456, tzinfo=UTC)
    neo = DateTime(2026, 10, 25, 11, 0, 5, 123456000, tzinfo=UTC)
    assert canonical(at) == canonical(neo) == '"2026-10-25T11:00:05.123456+00:00"'
    other_zone = at.astimezone(timezone(timedelta(hours=1)))
    assert canonical(other_zone) != canonical(at)


def test_canonical_refuses_a_value_it_cannot_write() -> None:
    with pytest.raises(TypeError, match="cannot be written"):
        canonical({"a": object()})


def test_canonical_keeps_a_tuple_as_a_list_and_a_set_as_a_sorted_list() -> None:
    assert canonical({"a": (1, 2), "b": {3, 1}}) == '{"a":[1,2],"b":[1,3]}'


def test_the_seed_statement_creates_every_node_and_relationship_and_stamps_them() -> None:
    cypher, params = seed_statement(SEED, "A")
    assert "$tenant" in cypher
    assert "$marker" in cypher
    assert cypher.count("CREATE (n0:Resource:Thing)") == 1
    assert cypher.count("CREATE (n1:Detail)") == 1
    assert cypher.count("CREATE (n1)-[:OF]->(n0)") == 1
    assert params["marker"] == "A"
    assert params["p0"] == {"id": "thing-1", "k": "K/1"}
    assert params["p1"] == {"text": "detail-A", "n": 2}
    assert "tenant" not in params  # the seeder passes the tenant itself, the seed never carries it


def test_the_seed_statement_for_b_differs_only_in_unique_and_marked_values() -> None:
    _, a = seed_statement(SEED, "A")
    cypher_b, b = seed_statement(SEED, "B")
    cypher_a, _ = seed_statement(SEED, "A")
    assert cypher_a == cypher_b
    assert b["marker"] == "B"
    assert b["p0"] == {"id": "thing-1-B", "k": "K/1"}
    assert b["p1"] == {"text": "detail-B", "n": 2}
    assert a["p0"]["k"] == b["p0"]["k"]  # the colliding key is the same


def test_the_seed_statement_refuses_a_ref_that_is_not_a_seed_node() -> None:
    seed = TenantSeed(nodes=SEED.nodes, rels=(SeedRel("d", "OF", "zz"),))
    with pytest.raises(ValueError, match="unknown ref"):
        seed_statement(seed, "A")


def test_the_seed_statement_refuses_a_name_that_is_not_an_identifier() -> None:
    bad_label = TenantSeed(nodes=(SeedNode("a", ("x`) DETACH DELETE (n",), {}),))
    with pytest.raises(ValueError, match="name"):
        seed_statement(bad_label, "A")
    bad_type = TenantSeed(nodes=SEED.nodes, rels=(SeedRel("d", "OF]->()//", "t"),))
    with pytest.raises(ValueError, match="name"):
        seed_statement(bad_type, "A")


def test_a_node_with_no_label_is_refused() -> None:
    with pytest.raises(ValueError, match="name"):
        seed_statement(TenantSeed(nodes=(SeedNode("a", (), {}),)), "A")


# The digest


def _node(**props: object) -> Node:
    return Node(("Thing",), props)


def test_the_digest_does_not_depend_on_the_order_of_nodes_or_relationships() -> None:
    a, b = _node(x=1), _node(x=2)
    one = Snapshot((a, b), (Rel(a, "R", b), Rel(b, "S", a, {"w": 1})))
    two = Snapshot((b, a), (Rel(b, "S", a, {"w": 1}), Rel(a, "R", b)))
    assert digest(one) == digest(two)


def test_the_digest_changes_with_a_property_a_label_a_node_or_a_relationship() -> None:
    a, b = _node(x=1), _node(x=2)
    base = Snapshot((a, b), (Rel(a, "R", b),))
    seen = {digest(base)}
    changed = [
        Snapshot((_node(x=9), b), (Rel(_node(x=9), "R", b),)),
        Snapshot((Node(("Other",), {"x": 1}), b), (Rel(Node(("Other",), {"x": 1}), "R", b),)),
        Snapshot((a,), ()),
        Snapshot((a, b), ()),
        Snapshot((a, b), (Rel(a, "R", b, {"w": 1}),)),
        Snapshot((a, b), (Rel(a, "T", b),)),
        Snapshot((a, b), (Rel(b, "R", a),)),
        Snapshot((a, b, b), (Rel(a, "R", b),)),
    ]
    for snapshot in changed:
        seen.add(digest(snapshot))
    assert len(seen) == 1 + len(changed)


def test_the_digest_is_a_sha256_hex_string_and_ignores_the_order_of_labels() -> None:
    one = Snapshot((Node(("A", "B"), {"x": 1}),))
    two = Snapshot((Node(("B", "A"), {"x": 1}),))
    assert digest(one) == digest(two)
    assert len(digest(one)) == 64
    assert int(digest(one), 16) >= 0
