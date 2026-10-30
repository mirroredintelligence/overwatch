"""Seam step two (TEN-030, DEC-142, DEC-144 item 3): enforcement has no transitional path.

The registry refuses a tenant statement that has no `tenantId: $tenant` entry or no scenario, in
every case: there is no ratchet to excuse an id, no constructor argument that lists one, and no
module that holds one. Every statement the platform registers names its tenant on every node it
matches, merges or creates, except the few that are reached through a relationship from a node
that does (listed below with the reason, and proved by the generated two-tenant test).

These tests read the real registry; no database. The behaviour on a real Neo4j is the generated
test in tests/integration/graph_store/test_tenant_isolation.py.
"""

import importlib
import inspect
import re

import pytest

from diucs.adapters.outbound.graph_store.queries import (
    REGISTRY,
    NamedQuery,
    QueryRegistry,
    QueryTemplate,
    ScenarioMissing,
    TenantPredicateMissing,
)
from diucs.adapters.outbound.graph_store.scenario import Scenario
from tests.support.query_probes import production_statements

SCENARIO = Scenario("placeholder: the registration check does not look inside it")
SCOPED = "MATCH (n:Thing {id: $id, tenantId: $tenant}) RETURN n.id AS id"


# 1. No way round the registration check


def test_the_registry_has_no_ratchet_and_no_way_to_list_an_excused_id() -> None:
    assert "unconverted" not in inspect.signature(QueryRegistry).parameters
    for name in ("is_tenant_pending", "needs_conversion", "ratchet_ids"):
        assert not hasattr(QueryRegistry, name), name


def test_the_unconverted_module_is_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("diucs.adapters.outbound.graph_store.unconverted")


def test_a_registry_refuses_a_keyword_that_would_excuse_an_id() -> None:
    with pytest.raises(TypeError):
        QueryRegistry(unconverted=frozenset({"Q-X-Y"}))  # type: ignore[call-arg]


def test_a_statement_without_the_tenant_is_refused_whatever_its_id() -> None:
    registry = QueryRegistry()
    old = NamedQuery(
        id="Q-OLD-READ", cypher="MATCH (n:Thing {id: $id}) RETURN n", mode="read", scenario=SCENARIO
    )
    with pytest.raises(TenantPredicateMissing):
        registry.register(old)
    assert registry.ids() == []


def test_a_statement_with_no_scenario_is_refused_whatever_its_id() -> None:
    registry = QueryRegistry()
    with pytest.raises(ScenarioMissing):
        registry.register(NamedQuery(id="Q-NEW-READ", cypher=SCOPED, mode="read"))


def test_a_template_is_held_to_the_same_two_rules() -> None:
    registry = QueryRegistry()
    with pytest.raises(TenantPredicateMissing):
        registry.register_template(
            QueryTemplate(
                id="Q-TPL-OLD",
                cypher="MATCH (n{insert} {id: $id}) RETURN n",
                mode="read",
                scenario=SCENARIO,
            )
        )
    with pytest.raises(ScenarioMissing):
        registry.register_template(
            QueryTemplate(
                id="Q-TPL-NEW",
                cypher="MATCH (n{insert} {id: $id, tenantId: $tenant}) RETURN n",
                mode="read",
            )
        )


@pytest.mark.parametrize(
    "cypher",
    [
        # `$tenant` only in the result, or only in a comment, is not a predicate.
        "MATCH (n:Thing {id: $id}) RETURN n.id AS id, $tenant AS tenant",
        "MATCH (n:Thing {id: $id}) // tenantId: $tenant\nRETURN n.id AS id",
        "MATCH (n:Thing {id: $id}) WHERE n.id <> $tenant RETURN n.id AS id",
        # The wrong parameter, the wrong key, the negation of the predicate.
        "MATCH (n:Thing {id: $id, tenantId: $tenantId}) RETURN n.id AS id",
        "MATCH (n:Thing {id: $id, tenant: $tenant}) RETURN n.id AS id",
        "MATCH (n:Thing {id: $id}) WHERE n.tenantId <> $tenant RETURN n.id AS id",
    ],
)
def test_a_statement_that_only_mentions_the_tenant_is_refused(cypher: str) -> None:
    registry = QueryRegistry()
    with pytest.raises(TenantPredicateMissing):
        registry.register(NamedQuery(id="Q-MENTION-ONLY", cypher=cypher, mode="read"))
    with pytest.raises(TenantPredicateMissing):
        registry.register(
            NamedQuery(id="Q-MENTION-ONLY", cypher=cypher, mode="read", scenario=SCENARIO)
        )


@pytest.mark.parametrize(
    "cypher",
    [
        SCOPED,
        "MERGE (n:Thing {id: $id, tenantId: $tenant}) SET n.rank = $rank RETURN n.id AS id",
        "MATCH (n:Thing {id: $id,tenantId:$tenant}) RETURN n.id AS id",
        "MATCH (n:Thing {tenantId: $tenant}) RETURN n.id AS id",
    ],
)
def test_a_statement_with_the_predicate_entry_and_a_scenario_registers(cypher: str) -> None:
    registry = QueryRegistry()
    registry.register(NamedQuery(id="Q-GOOD-ONE", cypher=cypher, mode="read", scenario=SCENARIO))
    assert registry.ids() == ["Q-GOOD-ONE"]


def test_the_module_registry_registers_nothing_a_fresh_registry_would_refuse() -> None:
    """Every statement now in the registry would register in an empty one: the registry holds no
    id that only an excuse let in."""
    fresh = QueryRegistry()
    for query_id, query in production_statements(REGISTRY).items():
        fresh.register(
            NamedQuery(
                id=query_id,
                cypher=query.cypher,
                mode=query.mode,
                scope=query.scope,
                scenario=query.scenario,
                scope_kinds=query.scope_kinds,
            )
        )


# 2. Every node a statement matches, merges or creates names its tenant

# A node pattern the lint reads: `(var:Label:Label {map})`, every part optional. A paren group that
# follows a word is a function call and is skipped.
_NODE = re.compile(r"\s*(\w+)?((?::\w+)*)\s*(\{.*\})?\s*", re.DOTALL)
_PREDICATE = re.compile(r"tenantId:\s*\$tenant\b")

# The only node patterns without the predicate. Each is an end of a path that starts at a node that
# has it, or the far end of a relationship the statement only reads or deletes; the generated
# two-tenant test proves each one against the second tenant's identical keys, and the invariant
# check of TEN-031 reports a relationship that joins two scopes, which would be the only way such
# a pattern could reach another tenant's node. A new entry here is a reviewed, deliberate change.
UNANCHORED_ENDS: dict[str, int] = {
    # `MATCH (r {tenantId}) (()-[]->(c {tenantId, key STARTS WITH}))+ ()`: the unlabelled `()`
    # are the steps of a path that begins at the tenant's own root and ends at a tenant's `c`.
    "Q-RES-CLEAR-OWNED": 2,
    "Q-RES-LOAD-NODES": 2,
    # Also reads the relationships of the nodes it loaded (`o`, a node of that path).
    "Q-RES-LOAD-RELS": 3,
    # Deletes the relationships that leave the tenant's own root; the other end is not touched.
    "Q-RES-CLEAR-ROOT-RELS": 1,
}


def _paren_groups(text: str) -> list[str]:
    """The inner text of every parenthesis group that is not a function call, in order."""
    groups: list[tuple[int, str]] = []
    stack: list[int] = []
    for index, char in enumerate(text):
        if char == "(":
            stack.append(index)
        elif char == ")" and stack:
            start = stack.pop()
            if start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
                continue
            groups.append((start, text[start + 1 : index]))
    return [inner for _, inner in sorted(groups)]


def unnamed_nodes(cypher: str) -> list[str]:
    """The node patterns that name no tenant: not a reference to a variable an earlier pattern
    named with the predicate, and not carrying the predicate itself."""
    found: list[str] = []
    scoped: set[str] = set()
    for inner in _paren_groups(cypher):
        match = _NODE.fullmatch(inner)
        if match is None:
            continue
        variable, labels, properties = match.group(1), match.group(2), match.group(3) or ""
        if _PREDICATE.search(properties):
            if variable:
                scoped.add(variable)
            continue
        if variable and not labels and not properties and variable in scoped:
            continue
        found.append(f"({inner[:60]})")
    return found


@pytest.mark.parametrize(
    ("cypher", "count"),
    [
        ("MATCH (n:T {tenantId: $tenant}) RETURN n", 0),
        ("MATCH (n:T {tenantId: $tenant}) MATCH (n)-[:R]->(m:U) RETURN m", 1),
        ("MATCH (n:T {k: $k}) RETURN n", 1),
        ("MATCH (n:T {tenantId: $tenant})-[:R]->() RETURN n", 1),
        ("MERGE (n:T {tenantId: $tenant, k: datetime({timezone: 'UTC'})}) RETURN n", 0),
        ("MATCH (a:T {tenantId: $tenant}), (b:U) CREATE (a)-[:R]->(b)", 2),
        ("MATCH (n) RETURN n", 1),
    ],
)
def test_the_lint_finds_a_node_that_names_no_tenant(cypher: str, count: int) -> None:
    assert len(unnamed_nodes(cypher)) == count, cypher


def test_every_registered_statement_names_its_tenant_on_every_node() -> None:
    problems: dict[str, int] = {}
    for query_id, query in sorted(production_statements(REGISTRY).items()):
        count = len(unnamed_nodes(query.cypher))
        if count:
            problems[query_id] = count
    assert problems == UNANCHORED_ENDS


def test_every_registered_statement_has_the_predicate_entry() -> None:
    missing = [
        query_id
        for query_id, query in production_statements(REGISTRY).items()
        if _PREDICATE.search(query.cypher) is None
    ]
    assert missing == []


def test_the_unanchored_ends_are_reached_from_an_anchored_root() -> None:
    """Each statement of the table starts at a `Resource` node that carries the predicate."""
    statements = production_statements(REGISTRY)
    for query_id in UNANCHORED_ENDS:
        assert re.match(
            r"MATCH \(\w+:Resource \{key: \$\w+, tenantId: \$tenant\}\)",
            statements[query_id].cypher,
        ), query_id
