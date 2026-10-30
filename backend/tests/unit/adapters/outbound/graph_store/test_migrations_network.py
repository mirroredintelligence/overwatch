"""The network registry's migration (TEN-051, DEC-541): expand only, one schema statement each,
idempotent, registry labels only, ids in the block 0110 to 0129 given to build wave 5 bundle W5E.
"""

import re

from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_network import (
    NETWORK_MIGRATIONS,
    NETWORK_REGISTRY_CONSTRAINTS,
)
from diucs.adapters.outbound.graph_store.migrations_tenant import REGISTRY_LABELS

IDS = ["0110_network_registry"]
BLOCK = range(110, 130)
WEEK_BLOCK = range(185, 190)  # build wave 9, bundle W9B (TEN-082)


def test_the_network_migrations_are_these_ids_in_this_block() -> None:
    assert [m.id for m in NETWORK_MIGRATIONS][: len(IDS)] == IDS
    for migration in NETWORK_MIGRATIONS:
        assert int(migration.id[:4]) in BLOCK or int(migration.id[:4]) in WEEK_BLOCK
    positions = [MIGRATIONS.index(m) for m in NETWORK_MIGRATIONS]
    assert positions == sorted(positions)


def test_the_sample_migration_makes_one_key_composite_with_the_scope() -> None:
    sample = [m for m in NETWORK_MIGRATIONS if m.id == "0185_network_samples"]
    assert len(sample) == 1 and sample[0].loops == ()
    assert sample[0].statements == (
        "CREATE CONSTRAINT network_sample_hour IF NOT EXISTS FOR (n:NetworkSample) "
        "REQUIRE (n.tenantId, n.hour) IS UNIQUE",
    )


def test_every_statement_is_a_single_idempotent_expand_step() -> None:
    migration = NETWORK_MIGRATIONS[0]
    assert migration.loops == ()
    assert len(migration.statements) >= 5
    for statement in migration.statements:
        assert statement.startswith(("CREATE CONSTRAINT ", "CREATE INDEX "))
        assert " IF NOT EXISTS " in statement
        assert re.search(r"\b(DROP|DELETE|SET|REMOVE|MERGE|MATCH|DETACH)\b", statement) is None
        assert ";" not in statement


def test_every_statement_is_on_a_registry_label_with_no_tenant_in_the_key() -> None:
    for statement in NETWORK_MIGRATIONS[0].statements:
        labels = set(re.findall(r"\(\w+:(\w+)\)", statement))
        assert labels
        assert labels <= set(REGISTRY_LABELS)
        assert "tenantId" not in statement


def test_the_registry_keys_are_those_of_the_design() -> None:
    names = {c.name: (c.label, c.properties) for c in NETWORK_REGISTRY_CONSTRAINTS}
    assert names == {
        "network_id": ("Network", ("id",)),
        "network_membership_id": ("NetworkMembership", ("id",)),
        "network_grant_id": ("Grant", ("id",)),
        "network_grant_version": (
            "Grant",
            ("networkId", "grantorTenantId", "scope", "version"),
        ),
        "network_listing_id": ("Listing", ("id",)),
    }
    statements = NETWORK_MIGRATIONS[0].statements
    for name in names:
        assert sum(f" {name} " in statement for statement in statements) == 1


def test_the_lookups_the_gate_and_the_membership_check_make_have_an_index() -> None:
    text = "\n".join(NETWORK_MIGRATIONS[0].statements)
    for needle in (
        "FOR (n:NetworkMembership) ON (n.memberTenantId, n.status)",
        "FOR (n:NetworkMembership) ON (n.networkId, n.memberTenantId)",
        "FOR (n:Grant) ON (n.grantorTenantId, n.scope, n.status)",
        "FOR (n:Grant) ON (n.networkId)",
        "FOR (n:Listing) ON (n.networkId, n.sourceTenantId, n.serviceId)",
    ):
        assert needle in text, needle


def test_the_registry_labels_hold_the_listing() -> None:
    assert {"Network", "NetworkMembership", "Grant", "Listing"} <= set(REGISTRY_LABELS)
