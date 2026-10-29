"""The predicate-removal helper of the generated two-tenant test (TEN-004, DEC-142 item 9).

It makes a scratch copy of a statement with `tenantId: $tenant` taken out, in a private registry
that lets the copy register although it no longer carries the predicate. The integration test then
shows that the generated test fails for the copy. Only the helper is tested here.
"""

import pytest

from diucs.adapters.outbound.graph_store.queries import NamedQuery
from diucs.adapters.outbound.graph_store.scenario import Scenario
from tests.support.predicate_removal import mutant_of, predicate_count, without_predicate

TWO = "MATCH (a:X {k: $k, tenantId: $tenant}) MATCH (b:Y {tenantId: $tenant, j: 1}) RETURN a"


@pytest.mark.parametrize(
    ("cypher", "count"),
    [
        ("RETURN 1", 0),
        ("MATCH (n:X {tenantId: $tenant}) RETURN n", 1),
        (TWO, 2),
        ("MATCH (n:X {tenantId: $tenantX}) RETURN n", 0),
        ("MATCH (n:X {tenantId: $tenant_x}) RETURN n", 0),
        ("MATCH (n:X) WHERE n.tenantId = $tenant RETURN n", 0),
        ("MATCH (n:X {tenantId:   $tenant}) RETURN n", 1),
    ],
)
def test_the_predicate_is_counted_where_it_is_a_map_entry(cypher: str, count: int) -> None:
    assert predicate_count(cypher) == count


def test_removing_every_occurrence_takes_out_the_comma_that_goes_with_it() -> None:
    assert without_predicate(TWO) == "MATCH (a:X {k: $k}) MATCH (b:Y {j: 1}) RETURN a"


def test_removing_the_only_entry_leaves_an_empty_map() -> None:
    assert without_predicate("MATCH (n:X {tenantId: $tenant}) RETURN n") == (
        "MATCH (n:X {}) RETURN n"
    )


def test_removing_one_occurrence_leaves_the_others() -> None:
    assert without_predicate(TWO, 0) == (
        "MATCH (a:X {k: $k}) MATCH (b:Y {tenantId: $tenant, j: 1}) RETURN a"
    )
    assert without_predicate(TWO, 1) == (
        "MATCH (a:X {k: $k, tenantId: $tenant}) MATCH (b:Y {j: 1}) RETURN a"
    )


def test_a_statement_with_no_predicate_or_a_missing_occurrence_is_refused() -> None:
    with pytest.raises(ValueError, match="no tenantId: \\$tenant"):
        without_predicate("RETURN 1")
    with pytest.raises(ValueError, match="no occurrence 2"):
        without_predicate(TWO, 2)
    with pytest.raises(ValueError, match="no occurrence -1"):
        without_predicate(TWO, -1)


def _query() -> NamedQuery:
    return NamedQuery(
        id="Q-X-GET",
        cypher=TWO,
        mode="read",
        scenario=Scenario("a read"),
    )


def test_the_mutant_is_the_same_statement_without_its_predicate_in_a_private_registry() -> None:
    original = _query()
    registry, mutant = mutant_of(original)
    assert mutant.id == original.id
    assert mutant.mode == original.mode
    assert mutant.scope == original.scope
    assert mutant.scenario == original.scenario
    assert mutant.cypher == without_predicate(original.cypher)
    assert registry.is_registered(mutant)
    assert registry.get(original.id) is mutant


def test_the_mutant_can_drop_one_occurrence_only() -> None:
    _, mutant = mutant_of(_query(), 1)
    assert mutant.cypher == without_predicate(TWO, 1)


def test_the_mutant_registers_although_it_no_longer_carries_the_predicate() -> None:
    """The registry would refuse it (TenantPredicateMissing); the mutant exists to be run anyway,
    so its id goes on the private registry's ratchet."""
    registry, mutant = mutant_of(_query())
    assert "$tenant" not in mutant.cypher
    assert registry.is_tenant_pending(mutant) is True


def test_the_original_statement_is_not_touched() -> None:
    original = _query()
    mutant_of(original)
    assert original.cypher == TWO
