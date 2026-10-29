"""Pure tests of the service move store (P20): the statement shape and the scenarios. The Neo4j
behaviour (the open-move guard under a race) is in
tests/integration/graph_store/test_service_move_repository.py.
"""

import re

from diucs.adapters.outbound.graph_store import service_move_repository  # noqa: F401
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario
from diucs.adapters.outbound.graph_store.unconverted import UNCONVERTED


def _move_ids() -> list[str]:
    return [q for q in REGISTRY.ids() if q.startswith("Q-MOVE")]


def test_the_move_statements_are_registered() -> None:
    assert {
        "Q-MOVE-LOCK-SERVICE",
        "Q-MOVE-OPEN-FOR",
        "Q-MOVE-GET",
        "Q-MOVE-ADD",
        "Q-MOVE-SAVE",
    } <= set(_move_ids())


def test_every_move_statement_names_its_tenant_and_carries_a_valid_scenario() -> None:
    pattern = re.compile(r"\((?:\w+)?(?::\w+)+\s*(\{[^}]*\})?\)")
    for query_id in _move_ids():
        query = REGISTRY.get(query_id)
        for match in pattern.finditer(query.cypher):
            assert match.group(1) is not None and "tenantId: $tenant" in match.group(1), query_id
        assert query.scenario is not None, query_id
        assert validate_scenario(query_id, query.scenario) == [], query_id
        assert query_id not in UNCONVERTED


def test_the_add_statement_writes_the_phone_hash_and_no_number() -> None:
    cypher = REGISTRY.get("Q-MOVE-ADD").cypher
    assert "toPhoneHash" in cypher
    assert "phone:" not in cypher and "toPhone:" not in cypher


def test_the_open_move_guard_takes_the_service_lock_first() -> None:
    # The service is locked before the open moves are read, so two adds for one service serialise.
    assert "SET s.id = s.id" in REGISTRY.get("Q-MOVE-LOCK-SERVICE").cypher
