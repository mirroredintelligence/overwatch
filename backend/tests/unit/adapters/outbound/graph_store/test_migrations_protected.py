"""The uniqueness migrations of the protected text and service move stores (P20, orchestrator
decision 2). Each is a composite constraint in its own area module, with the ids 0040 and 0041, and
each is one schema statement with IF NOT EXISTS, so a re-run changes nothing. A schema statement
runs in its own transaction (lesson L8). The verification stage runs them against Neo4j.
"""

from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_protected import PROTECTED_MIGRATIONS

HANDLE_ID = "0040_protected_text_handle"
MOVE_ID = "0041_service_move_id"
HANDLE_STATEMENT = (
    "CREATE CONSTRAINT protected_text_handle IF NOT EXISTS FOR (n:ProtectedText) "
    "REQUIRE (n.tenantId, n.handle) IS UNIQUE"
)
MOVE_STATEMENT = (
    "CREATE CONSTRAINT service_move_id IF NOT EXISTS FOR (n:ServiceMove) "
    "REQUIRE (n.tenantId, n.moveId) IS UNIQUE"
)


def test_the_protected_migrations_are_0040_and_0041() -> None:
    assert [migration.id for migration in PROTECTED_MIGRATIONS] == [HANDLE_ID, MOVE_ID]


def test_each_is_one_idempotent_composite_constraint_with_no_loop_or_parameter() -> None:
    expected = {HANDLE_ID: HANDLE_STATEMENT, MOVE_ID: MOVE_STATEMENT}
    for migration in PROTECTED_MIGRATIONS:
        assert migration.statements == (expected[migration.id],), migration.id
        assert migration.loops == (), migration.id
        assert dict(migration.params) == {}, migration.id
        assert "IF NOT EXISTS" in migration.statements[0], migration.id


def test_the_constraints_key_the_handle_and_the_move_id_by_tenant() -> None:
    assert "(n.tenantId, n.handle) IS UNIQUE" in HANDLE_STATEMENT
    assert "(n.tenantId, n.moveId) IS UNIQUE" in MOVE_STATEMENT


def test_they_are_assembled_after_the_tenant_migrations_and_in_order() -> None:
    ids = [migration.id for migration in MIGRATIONS]
    assert {HANDLE_ID, MOVE_ID} <= set(ids)
    assert ids.index(HANDLE_ID) > ids.index("0035_default_tenant_record")
    assert ids.index(MOVE_ID) == ids.index(HANDLE_ID) + 1


def test_no_other_id_in_the_range_is_taken_by_this_area() -> None:
    assert {migration.id[:4] for migration in PROTECTED_MIGRATIONS} <= {"0040", "0041"}
