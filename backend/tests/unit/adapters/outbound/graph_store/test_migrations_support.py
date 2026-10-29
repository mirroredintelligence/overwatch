"""The support-access migrations of O06, as data: two composite uniqueness constraints, each one
idempotent schema statement. No database is needed; the statements are read back and compared."""

import re

from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_support import SUPPORT_MIGRATIONS

EXPECTED = {
    "0045_support_session_id": (
        "CREATE CONSTRAINT support_session_id IF NOT EXISTS FOR (n:UiSession) "
        "REQUIRE (n.tenantId, n.id) IS UNIQUE",
    ),
    "0046_support_code_hash": (
        "CREATE CONSTRAINT support_code_hash IF NOT EXISTS FOR (n:SupportCode) "
        "REQUIRE (n.tenantId, n.codeHash) IS UNIQUE",
    ),
}
_CONSTRAINT_NAME = re.compile(r"CREATE (?:CONSTRAINT|INDEX) (\w+)")


def test_the_support_migrations_are_0045_and_0046_in_order() -> None:
    assert [m.id for m in SUPPORT_MIGRATIONS] == list(EXPECTED)


def test_each_support_migration_is_the_one_pinned_statement_with_no_loop_or_parameter() -> None:
    for migration in SUPPORT_MIGRATIONS:
        assert migration.statements == EXPECTED[migration.id]
        assert migration.loops == ()
        assert dict(migration.params) == {}


def test_every_support_statement_is_idempotent_and_drops_nothing() -> None:
    for migration in SUPPORT_MIGRATIONS:
        for statement in migration.statements:
            assert "IF NOT EXISTS" in statement
            assert "DROP" not in statement.upper()


def test_each_support_constraint_is_unique_on_the_tenant_and_the_key() -> None:
    for migration in SUPPORT_MIGRATIONS:
        [statement] = migration.statements
        assert re.search(r"REQUIRE \(n\.tenantId, n\.\w+\) IS UNIQUE$", statement)


def test_the_support_migrations_are_assembled_into_the_list_once_each() -> None:
    ids = [m.id for m in MIGRATIONS]
    for migration in SUPPORT_MIGRATIONS:
        assert ids.count(migration.id) == 1


def test_the_support_constraint_names_are_not_used_by_any_other_migration() -> None:
    names = [
        name
        for migration in MIGRATIONS
        for statement in migration.statements
        for name in _CONSTRAINT_NAME.findall(statement)
    ]
    assert len(names) == len(set(names))
    assert "support_session_id" in names and "support_code_hash" in names


def test_the_ids_stay_in_the_range_the_build_wave_reserved() -> None:
    for migration in SUPPORT_MIGRATIONS:
        number = int(migration.id.split("_", 1)[0])
        assert 45 <= number <= 49
