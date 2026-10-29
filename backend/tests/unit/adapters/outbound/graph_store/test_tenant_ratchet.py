"""The registry of statements against the ratchet and the scenarios (TEN-004, DEC-142 item 5).

Every registered tenant statement either carries a scenario (and `$tenant`) or is on the ratchet;
the ratchet may only shrink; every scenario is valid. These tests read the real registry, with no
database. The behaviour of each scenario on a real Neo4j is the generated test in
tests/integration/graph_store/test_tenant_isolation.py.
"""

import re

import pytest

from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.scenario import (
    collision_blocked,
    constraints_used,
    validate_scenario,
)
from diucs.adapters.outbound.graph_store.unconverted import UNCONVERTED
from tests.support.query_probes import (
    INITIAL_UNCONVERTED,
    production_statements,
    ratchet_problems,
    scenario_gaps,
)

# The statements TEN-004 converted to prove the mechanism on real code (DEC-150). A later
# conversion bundle adds its own ids to the registry and leaves this list alone.
STARTER = frozenset(
    {
        "Q-CRED-CLEAR",
        "Q-CRED-GET",
        "Q-CRED-PRACTITIONER-EXISTS",
        "Q-CRED-SAVE-STATE",
        "Q-CRED-SET",
        "Q-OUTBOX-ADD",
        "Q-OUTBOX-PENDING",
        "Q-PROCESSED-MARK",
    }
)

# The seventeen ids of the resource store (TEN-009, DEC-164): fifteen templates converted, and the
# two of the dead idempotency pair removed. A sixteenth template, `Q-RES-LINK-SHARED`, is new and
# never had a place on the ratchet. None of the seventeen may be on the ratchet again.
RESOURCE_STORE = frozenset(
    {
        "Q-RES-CLEAR-OWNED",
        "Q-RES-CLEAR-ROOT-RELS",
        "Q-RES-GET",
        "Q-RES-HISTORY",
        "Q-RES-IDEM-GET",
        "Q-RES-IDEM-RECORD",
        "Q-RES-LOAD-NODES",
        "Q-RES-LOAD-RELS",
        "Q-RES-LOCK",
        "Q-RES-MERGE-NODES",
        "Q-RES-MERGE-RELS",
        "Q-RES-SET-POSITION",
        "Q-RES-SHARED-CREATE",
        "Q-RES-SHARED-FILL",
        "Q-RES-SHARED-READ",
        "Q-RES-UPSERT-NODE",
        "Q-RES-UPSERT-ROOT",
    }
)

# The single-property unique constraints each starter scenario leans on. TEN-005 replaced them with
# composite keys (tenantId plus the key), so the two tenants share every key a scenario uses and no
# scenario leans on one: the table is empty, and it may not grow. A value only a global key could
# hold (`link_token_hash`) would be a `Unique` again, and its statement is listed here.
CONSTRAINTS_LEANED_ON: dict[str, frozenset[str]] = {}
# The statements whose every lookup value is covered by such a constraint: the two tenants cannot
# share the key the statement is called with. None.
COLLISION_BLOCKED: frozenset[str] = frozenset()


@pytest.fixture(scope="module")
def statements() -> dict[str, NamedQuery]:
    return production_statements(REGISTRY)


def test_the_universe_holds_the_starter_statements(statements: dict[str, NamedQuery]) -> None:
    assert set(statements) >= STARTER


def test_every_tenant_statement_has_a_scenario_or_is_on_the_ratchet(
    statements: dict[str, NamedQuery],
) -> None:
    assert scenario_gaps(statements, UNCONVERTED) == []


def test_the_real_ratchet_has_no_problem(statements: dict[str, NamedQuery]) -> None:
    assert ratchet_problems(statements, UNCONVERTED, INITIAL_UNCONVERTED) == []


def test_the_ratchet_may_only_shrink() -> None:
    """The initial list is the 126 ids TEN-001 put on the ratchet. The live ratchet holds only ids
    from it, so a statement cannot be added to the unconverted side later."""
    assert len(INITIAL_UNCONVERTED) == 126
    assert UNCONVERTED <= INITIAL_UNCONVERTED
    assert len(UNCONVERTED) <= 126 - len(STARTER) - len(RESOURCE_STORE)


def test_no_resource_store_id_is_on_the_ratchet_and_the_dead_pair_is_not_registered() -> None:
    assert not UNCONVERTED & RESOURCE_STORE
    assert RESOURCE_STORE <= INITIAL_UNCONVERTED
    registered = set(REGISTRY.ids()) | set(REGISTRY.template_ids())
    assert not registered & {"Q-RES-IDEM-GET", "Q-RES-IDEM-RECORD"}


def test_a_new_unconverted_id_is_a_problem_even_when_the_registry_agrees(
    statements: dict[str, NamedQuery],
) -> None:
    """The registry test (the ratchet equals what needs conversion) cannot see an id that was added
    to the list and registered together; only the pinned initial list refuses it."""
    added = {
        **statements,
        "Q-NEW-ONE": NamedQuery(id="Q-NEW-ONE", cypher="MATCH (n:X) RETURN n", mode="read"),
    }
    problems = ratchet_problems(added, UNCONVERTED | {"Q-NEW-ONE"}, INITIAL_UNCONVERTED)
    assert any("Q-NEW-ONE" in p and "not on the initial list" in p for p in problems)


def test_a_statement_with_no_scenario_is_not_skipped_by_the_generated_test(
    statements: dict[str, NamedQuery],
) -> None:
    bare = {
        **statements,
        "Q-NEW-TWO": NamedQuery(id="Q-NEW-TWO", cypher="MATCH (n:X) RETURN n", mode="read"),
    }
    assert any("Q-NEW-TWO" in gap for gap in scenario_gaps(bare, UNCONVERTED))


def test_the_starter_statements_are_converted(statements: dict[str, NamedQuery]) -> None:
    for query_id in sorted(STARTER):
        query = statements[query_id]
        assert re.search(r"\$tenant\b", query.cypher), query_id
        assert "tenantId: $tenant" in query.cypher, query_id
        assert query.scenario is not None, query_id
        assert query_id not in UNCONVERTED, query_id
        assert query_id in INITIAL_UNCONVERTED, query_id


def test_every_registered_scenario_is_valid(statements: dict[str, NamedQuery]) -> None:
    with_scenario = {i: q for i, q in statements.items() if q.scenario is not None}
    assert set(with_scenario) >= STARTER
    for query_id, query in sorted(with_scenario.items()):
        assert query.scenario is not None
        assert validate_scenario(query_id, query.scenario) == [], query_id


def test_a_scenario_leans_only_on_the_constraints_pinned_for_it(
    statements: dict[str, NamedQuery],
) -> None:
    for query_id, query in sorted(statements.items()):
        if query.scenario is None:
            continue
        pinned = CONSTRAINTS_LEANED_ON.get(query_id, frozenset())
        assert constraints_used(query.scenario) <= pinned, query_id


def test_no_starter_scenario_holds_a_value_the_tenants_cannot_share(
    statements: dict[str, NamedQuery],
) -> None:
    """After TEN-005 every key of every starter scenario is shared by both tenants: no `Unique`
    anywhere in a scenario (its seed, parameters or expectations)."""
    assert CONSTRAINTS_LEANED_ON == {}
    for query_id in sorted(STARTER):
        scenario = statements[query_id].scenario
        assert scenario is not None
        assert constraints_used(scenario) == frozenset(), query_id


def test_the_pinned_constraints_are_what_the_starter_scenarios_use(
    statements: dict[str, NamedQuery],
) -> None:
    """The table may only shrink: a pin that nothing uses any more is a stale pin."""
    for query_id, pinned in CONSTRAINTS_LEANED_ON.items():
        scenario = statements[query_id].scenario
        assert scenario is not None
        assert constraints_used(scenario) == pinned, query_id


def test_a_scenario_whose_keys_cannot_collide_is_pinned(
    statements: dict[str, NamedQuery],
) -> None:
    blocked = {
        i for i, q in statements.items() if q.scenario is not None and collision_blocked(q.scenario)
    }
    assert blocked <= COLLISION_BLOCKED
    assert blocked >= COLLISION_BLOCKED  # a stale pin


def test_a_converted_statement_names_its_tenant_on_every_node_it_matches_or_creates(
    statements: dict[str, NamedQuery],
) -> None:
    """Each node pattern of a converted statement carries `tenantId: $tenant`. A cheap look at the
    text, not the proof (the generated test is); it catches the one-line omission early."""
    pattern = re.compile(r"\((?:\w+)?(?::\w+)+\s*(\{[^}]*\})?\)")
    for query_id in sorted(STARTER):
        text = statements[query_id].cypher
        for match in pattern.finditer(text):
            assert match.group(1) is not None and "tenantId: $tenant" in match.group(1), (
                query_id,
                match.group(0),
            )
