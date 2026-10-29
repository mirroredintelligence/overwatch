"""The registry migrations of TEN-007, as data: the keys of the tenant and number nodes, and the
default tenant record that the stamped development data belongs to. No database.

Migration ids 0034 and 0035 were checked against every local and remote ref and every worktree
(none used 0034 or above) before this file was written (lesson L68).
"""

import re

from diucs.adapters.outbound.graph_store import migrations_tenant as tenant
from diucs.adapters.outbound.graph_store.migrations import CORE_MIGRATIONS, MIGRATIONS
from diucs.application.tenancy import DEFAULT_TENANT_ID

EXPECTED_0034 = (
    "CREATE CONSTRAINT tenant_id IF NOT EXISTS FOR (n:Tenant) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT tenant_host IF NOT EXISTS FOR (n:Tenant) REQUIRE n.host IS UNIQUE",
    "CREATE CONSTRAINT tenant_entra_directory IF NOT EXISTS FOR (n:Tenant) "
    "REQUIRE n.entraDirectoryId IS UNIQUE",
    "CREATE CONSTRAINT tenant_number_e164 IF NOT EXISTS FOR (n:TenantNumber) "
    "REQUIRE n.e164 IS UNIQUE",
    "CREATE INDEX tenant_number_account IF NOT EXISTS FOR (n:TenantNumber) ON (n.accountSid)",
)
EXPECTED_0035 = (
    "MATCH (d) WHERE d.tenantId = $defaultTenant WITH d LIMIT 1 "
    "MERGE (t:Tenant {id: $defaultTenant}) "
    "ON CREATE SET t.displayName = $displayName, t.legalName = $displayName, "
    "t.organisationType = 'other', t.countryCode = 'GB', t.timeZone = 'Europe/London', "
    "t.status = 'active', t.createdAt = datetime(), t.activatedAt = datetime(), "
    "t.epoch = 1, t.hashKeyVersion = 0"
)


def _by_id(migration_id: str) -> tenant.Migration:
    found = [m for m in tenant.TENANT_MIGRATIONS if m.id == migration_id]
    assert found, f"migration {migration_id} is not in TENANT_MIGRATIONS"
    return found[0]


def test_the_registry_migrations_follow_the_three_of_ten_005_in_order() -> None:
    ids = [m.id for m in tenant.TENANT_MIGRATIONS]
    assert ids == [
        "0031_tenant_composites",
        "0032_backfill_default_tenant",
        "0033_case_open_reference",
        "0034_tenant_registry",
        "0035_default_tenant_record",
    ]
    assert [m.id for m in MIGRATIONS][-2:] == ids[-2:]


def test_0034_is_the_four_unique_keys_and_the_account_index_in_this_order() -> None:
    migration = _by_id("0034_tenant_registry")
    assert migration.statements == EXPECTED_0034
    assert migration.loops == () and dict(migration.params) == {}


def test_every_statement_of_0034_is_if_not_exists_and_none_drops_anything() -> None:
    for statement in _by_id("0034_tenant_registry").statements:
        assert " IF NOT EXISTS " in statement, statement
        assert re.search(r"\bDROP\b", statement) is None, statement


def test_the_keys_are_on_registry_labels_only_and_none_is_composite() -> None:
    for statement in _by_id("0034_tenant_registry").statements:
        label = re.search(r"\(n:(\w+)\)", statement)
        assert label is not None and label.group(1) in tenant.REGISTRY_LABELS, statement
        assert "tenantId" not in statement, statement


def test_the_names_of_0034_are_new_and_the_rollback_is_the_exact_inverse() -> None:
    created = {m.group(1) for s in EXPECTED_0034 if (m := re.match(r"CREATE \w+ (\w+) ", s))}
    assert created == {
        "tenant_id",
        "tenant_host",
        "tenant_entra_directory",
        "tenant_number_e164",
        "tenant_number_account",
    }
    taken = {c.name for c in tenant.COMPOSITE_CONSTRAINTS} | {
        i.name for i in tenant.COMPOSITE_INDEXES
    }
    for core in CORE_MIGRATIONS:
        taken |= {m.group(1) for s in core.statements if (m := re.match(r"CREATE \w+ (\w+) ", s))}
    taken.add("migration_id")
    assert created.isdisjoint(taken)
    dropped = set()
    for statement in tenant.ROLLBACK_0034:
        match = re.fullmatch(r"DROP (?:CONSTRAINT|INDEX) (\w+) IF EXISTS", statement)
        assert match, statement
        dropped.add(match.group(1))
    assert dropped == created and len(tenant.ROLLBACK_0034) == 5


def test_0035_creates_the_default_tenant_for_stamped_data_only_and_never_rewrites() -> None:
    migration = _by_id("0035_default_tenant_record")
    assert migration.statements == (EXPECTED_0035,)
    assert migration.loops == ()
    assert dict(migration.params) == {
        "defaultTenant": DEFAULT_TENANT_ID,
        "displayName": tenant.DEFAULT_TENANT_NAME,
    }
    text = migration.statements[0]
    assert "ON CREATE SET" in text and "ON MATCH" not in text
    assert text.count("SET") == 1  # every property is set on create, none otherwise
    assert re.search(r"\$tenant\b", text) is None  # the stamp's own parameter, never the bound one


def test_the_default_tenant_has_legacy_hash_keys_and_a_name_that_names_no_place() -> None:
    assert tenant.DEFAULT_TENANT_NAME == "Default tenant"
    assert "hashKeyVersion = 0" in EXPECTED_0035  # the legacy global keys (audit F 2.3)


def test_a_fresh_database_gets_no_default_tenant_from_the_statement_alone() -> None:
    """The statement starts from a matched node, so it creates nothing in an empty graph."""
    text = _by_id("0035_default_tenant_record").statements[0]
    assert text.startswith("MATCH (d) WHERE d.tenantId = $defaultTenant")
