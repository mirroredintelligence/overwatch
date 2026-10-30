"""The generated test over three scopes (TEN-060): the universe of statements by kind of scope, the
mutant that keeps its kinds, the ids of the network world and the invariants of a network scope.
All pure: the runs on a real Neo4j are `tests/integration/graph_store/test_tenant_isolation.py` and
`test_network_scope_isolation.py` (written, not run, in build wave 5).
"""

import inspect
import re

import pytest

from diucs.adapters.outbound.graph_store.queries import (
    BOTH_KINDS,
    NETWORK_KINDS,
    REGISTRY,
    TENANT_KINDS,
)
from diucs.application.tenancy import ScopeKind, is_valid_tenant_id
from diucs.domain.model.network import check_network_id
from tests.support import query_probes
from tests.support.network_world import (
    NETWORK_INVARIANTS,
    WorldIds,
    world_ids,
)
from tests.support.predicate_removal import mutant_of
from tests.support.query_probes import (
    production_statements,
    run_isolation,
    scenario_gaps,
    universe_problems,
)
from tests.support.tenancy import new_run_identity


def _kinds(statements: dict[str, object]) -> set[frozenset[str]]:
    return {query.scope_kinds for query in statements.values()}  # type: ignore[attr-defined]


def test_the_tenant_universe_holds_tenant_and_both_kinds_and_no_network_statement() -> None:
    statements = production_statements(REGISTRY)
    assert _kinds(statements) == {TENANT_KINDS, BOTH_KINDS}
    assert "Q-AUDIT-APPEND" in statements and "Q-PROCESSED-MARK" in statements
    assert not {i for i in statements if i.startswith(("Q-PROJ-", "Q-NETVIEW-"))}


def test_the_network_universe_holds_network_and_both_kinds_and_no_tenant_statement() -> None:
    statements = production_statements(REGISTRY, kind=ScopeKind.NETWORK)
    assert _kinds(statements) == {NETWORK_KINDS, BOTH_KINDS}
    assert {"Q-PROJ-SERVICE-UPSERT", "Q-NETVIEW-SERVICES", "Q-AUDIT-APPEND"} <= set(statements)
    assert len(statements) >= 19 + 16


@pytest.mark.parametrize("kind", list(ScopeKind))
def test_every_statement_of_either_universe_has_a_scenario_and_is_in_it(kind: ScopeKind) -> None:
    statements = production_statements(REGISTRY, kind=kind)
    assert scenario_gaps(statements) == []
    assert universe_problems(REGISTRY, statements, kind=kind) == []


def test_a_registered_network_statement_missing_from_its_universe_is_named() -> None:
    statements = production_statements(REGISTRY, kind=ScopeKind.NETWORK)
    del statements["Q-PROJ-SERVICE-UPSERT"]
    problems = universe_problems(REGISTRY, statements, kind=ScopeKind.NETWORK)
    assert [p for p in problems if "Q-PROJ-SERVICE-UPSERT" in p]


def test_the_runner_takes_the_kind_of_scope_to_run_in() -> None:
    assert "kind" in inspect.signature(run_isolation).parameters
    assert "kind" in inspect.signature(production_statements).parameters
    assert query_probes.ScopeKind is ScopeKind


def test_a_mutant_of_a_network_statement_keeps_its_kinds_and_loses_its_predicate() -> None:
    original = REGISTRY.get("Q-PROJ-MARK-SERVICE")
    registry, mutant = mutant_of(original)
    assert mutant.scope_kinds == NETWORK_KINDS
    assert "tenantId: $tenant" not in mutant.cypher
    assert registry.is_registered(mutant)


def test_the_ids_of_the_world_are_valid_distinct_and_of_the_right_kind() -> None:
    ids = world_ids(new_run_identity(pid=4242, now=1_800_000_000, nonce="ab12"))
    assert isinstance(ids, WorldIds)
    tenants = [ids.owner, *ids.members, ids.outsider]
    assert len(tenants) == 5 and len(set(tenants)) == 5
    assert all(is_valid_tenant_id(t) for t in tenants)
    assert len(ids.members) == 3
    for network in (ids.network, ids.other_network):
        check_network_id(network)
    assert ids.network != ids.other_network
    assert ids.owner not in ids.members and ids.outsider not in ids.members


def test_the_invariants_of_a_network_scope_are_read_only_and_named() -> None:
    assert set(NETWORK_INVARIANTS) == {
        "projection-outside-a-network-scope",
        "source-tenant-on-a-tenant-node",
        "tenant-data-in-a-network-scope",
        "relationship-between-scopes",
        "source-tenant-is-not-a-tenant-id",
    }
    for name, text in NETWORK_INVARIANTS.items():
        assert re.search(r"\b(CREATE|MERGE|SET|DELETE|REMOVE|CALL)\b", text, re.IGNORECASE) is None
        assert "RETURN" in text, name
