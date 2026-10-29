"""The uniqueness migration of the safety counter (U41): one composite constraint, id 0070, one
idempotent schema statement, assembled after the protected store's migrations.
"""

from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_safety import SAFETY_MIGRATIONS

COUNTER_ID = "0070_safety_counter_id"
COUNTER_STATEMENT = (
    "CREATE CONSTRAINT safety_counter_id IF NOT EXISTS FOR (n:SafetyCounter) "
    "REQUIRE (n.tenantId, n.counterId) IS UNIQUE"
)


def test_the_safety_migrations_are_0070_only() -> None:
    assert [migration.id for migration in SAFETY_MIGRATIONS] == [COUNTER_ID]


def test_the_counter_migration_is_one_idempotent_composite_constraint() -> None:
    (migration,) = SAFETY_MIGRATIONS
    assert migration.statements == (COUNTER_STATEMENT,)
    assert migration.loops == ()
    assert dict(migration.params) == {}
    assert "IF NOT EXISTS" in migration.statements[0]


def test_it_is_assembled_after_the_protected_store_migrations() -> None:
    ids = [migration.id for migration in MIGRATIONS]
    assert COUNTER_ID in ids
    assert ids.index(COUNTER_ID) > ids.index("0041_service_move_id")
