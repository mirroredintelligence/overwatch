"""The tenant configuration migration (TEN-026): composite uniqueness for each record, expand only.

One id from the block this task was given (0055 to 0059), one schema statement per record (a
schema statement runs in its own transaction, lesson L8), each idempotent, and nothing dropped
(DEC-134 item 16: expand only). The statements are fixed text written out in full, read back here.
"""

import re

from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_tenant_config import (
    TENANT_CONFIG_MIGRATIONS,
)

EXPECTED = {
    "tenant_config_version": ("TenantConfigVersion", ("tenantId", "version")),
    "tenant_setting_key": ("TenantSetting", ("tenantId", "configVersion", "key")),
    "tenant_contact_kind": ("TenantContact", ("tenantId", "kind")),
    "tenant_channel_id": ("TenantChannel", ("tenantId", "id")),
    "tenant_retention_class": ("TenantRetention", ("tenantId", "dataClass")),
    "tenant_entra_binding": ("TenantEntraBinding", ("tenantId", "directoryId")),
    "tenant_role_mapping": ("TenantRoleMapping", ("tenantId", "groupObjectId")),
}
STATEMENT = re.compile(
    r"CREATE CONSTRAINT (?P<name>\w+) IF NOT EXISTS FOR \(n:(?P<label>\w+)\) "
    r"REQUIRE \((?P<props>[^)]*)\) IS UNIQUE"
)


def test_the_migration_has_one_id_in_the_block_this_task_was_given() -> None:
    assert [m.id for m in TENANT_CONFIG_MIGRATIONS] == ["0055_tenant_config_records"]
    number = int(TENANT_CONFIG_MIGRATIONS[0].id[:4])
    assert 55 <= number <= 59  # noqa: PLR2004


def test_the_migration_is_part_of_the_assembled_list_after_the_support_ones() -> None:
    ids = [m.id for m in MIGRATIONS]

    assert "0055_tenant_config_records" in ids
    assert ids.index("0055_tenant_config_records") > ids.index("0046_support_code_hash")


def test_each_record_has_a_composite_unique_key_that_starts_with_the_tenant() -> None:
    found: dict[str, tuple[str, tuple[str, ...]]] = {}
    for statement in TENANT_CONFIG_MIGRATIONS[0].statements:
        match = STATEMENT.fullmatch(statement)
        assert match is not None, statement
        props = tuple(part.strip().removeprefix("n.") for part in match["props"].split(","))
        found[match["name"]] = (match["label"], props)

    assert found == EXPECTED
    for _, props in found.values():
        assert props[0] == "tenantId"


def test_the_migration_only_adds_and_runs_no_data_statement() -> None:
    migration = TENANT_CONFIG_MIGRATIONS[0]

    assert migration.loops == ()
    assert len(migration.statements) == len(EXPECTED)
    for statement in migration.statements:
        assert "DROP" not in statement.upper()
        assert "SET " not in statement.upper()
        assert statement.startswith("CREATE CONSTRAINT")
