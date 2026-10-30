"""The migration of the platform's own records (TEN-075, block 0190 to 0194): expand only, one
schema statement per key, idempotent, and no key with a tenant (these nodes are the platform's)."""

import re

from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_platform import PLATFORM_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_tenant import REGISTRY_LABELS
from diucs.adapters.outbound.graph_store.queries import PLATFORM_RECORD_LABELS


def test_the_platform_records_have_one_migration_in_the_block_of_wave_9_bundle_c() -> None:
    assert [m.id for m in PLATFORM_MIGRATIONS] == ["0190_platform_records"]
    assert all(190 <= int(m.id.split("_", 1)[0]) <= 194 for m in PLATFORM_MIGRATIONS)
    assert PLATFORM_MIGRATIONS[0] in MIGRATIONS


def test_each_statement_is_one_idempotent_schema_statement_and_nothing_is_dropped() -> None:
    (migration,) = PLATFORM_MIGRATIONS
    assert migration.loops == () and dict(migration.params) == {}
    assert len(migration.statements) == 5
    for statement in migration.statements:
        assert re.match(r"CREATE (CONSTRAINT|INDEX) \w+ IF NOT EXISTS FOR \(n:\w+\)", statement)
        assert not re.search(r"\b(DROP|DELETE|DETACH|SET|MERGE|REMOVE)\b", statement)


def test_the_keys_are_the_ones_the_adapters_lean_on() -> None:
    text = " ".join(PLATFORM_MIGRATIONS[0].statements)
    assert "PlatformAuditHead) REQUIRE n.id IS UNIQUE" in text
    assert "PlatformAuditEntry) REQUIRE n.seq IS UNIQUE" in text
    assert "SupportAccessTicket) REQUIRE n.id IS UNIQUE" in text
    assert "ON (n.forTenant, n.requestedAt)" in text
    assert "ON (n.requestedBy, n.requestedAt)" in text


def test_no_key_names_a_tenant_because_the_platforms_records_carry_none() -> None:
    assert "tenantId" not in " ".join(PLATFORM_MIGRATIONS[0].statements)
    assert set(REGISTRY_LABELS) >= PLATFORM_RECORD_LABELS
    labels = set(re.findall(r"\(n:(\w+)\)", " ".join(PLATFORM_MIGRATIONS[0].statements)))
    assert labels == PLATFORM_RECORD_LABELS
