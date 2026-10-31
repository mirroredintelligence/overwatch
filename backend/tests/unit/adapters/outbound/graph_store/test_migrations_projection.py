"""The projection migration (TEN-053, DEC-542): expand only, one schema statement each, composite
with the scope, ids in the block 0110 to 0129 given to build wave 5 bundle W5E.
"""

import re

from diucs.adapters.outbound.graph_store.migrations_network import (
    NETWORK_MIGRATIONS,
    PROJECTION_CONSTRAINTS,
)
from diucs.domain.rules import projection as allowlist

EXPECTED = {
    "projection_source": ("ProjectionSource", ("tenantId", "sourceTenantId", "kind")),
    "projected_service": ("ProjectedService", ("tenantId", "sourceTenantId", "sourceServiceId")),
    "projected_location": ("ProjectedLocation", ("tenantId", "sourceTenantId", "sourceServiceId")),
    "projected_opening_hour": (
        "ProjectedOpeningHour",
        ("tenantId", "sourceTenantId", "sourceServiceId", "position"),
    ),
    "projected_capacity": ("ProjectedCapacity", ("tenantId", "sourceTenantId", "sourceServiceId")),
    "projected_criteria": ("ProjectedCriteria", ("tenantId", "sourceTenantId", "sourceServiceId")),
    "projection_cursor": ("ProjectionCursor", ("tenantId", "sourceTenantId", "kind")),
}


def _migration():  # type: ignore[no-untyped-def]
    found = [m for m in NETWORK_MIGRATIONS if m.id == "0111_projection_keys"]
    assert len(found) == 1
    return found[0]


def test_the_projection_migration_follows_the_registry_one_in_the_block() -> None:
    ids = [m.id for m in NETWORK_MIGRATIONS]
    assert ids[:2] == ["0110_network_registry", "0111_projection_keys"]
    assert all(110 <= int(i[:4]) <= 129 or 185 <= int(i[:4]) <= 189 for i in ids)


def test_every_key_is_composite_with_the_scope_and_one_statement() -> None:
    assert {c.name: (c.label, c.properties) for c in PROJECTION_CONSTRAINTS} == EXPECTED
    statements = _migration().statements
    for name, (label, properties) in EXPECTED.items():
        matching = [s for s in statements if f"CREATE CONSTRAINT {name} IF NOT EXISTS" in s]
        assert len(matching) == 1
        assert f"(n:{label})" in matching[0]
        for prop in properties:
            assert f"n.{prop}" in matching[0]
        assert matching[0].startswith("CREATE CONSTRAINT ")


def test_the_projected_labels_are_exactly_the_allowlists_and_the_two_bookkeeping_ones() -> None:
    labels = {label for label, _ in EXPECTED.values()}
    assert labels == set(allowlist.ALLOWLIST) | {"ProjectionSource", "ProjectionCursor"}


def test_the_migration_is_expand_only_idempotent_and_has_the_reads_it_needs() -> None:
    migration = _migration()
    assert migration.loops == ()
    for statement in migration.statements:
        assert " IF NOT EXISTS " in statement
        assert re.search(r"\b(DROP|DELETE|SET|REMOVE|MERGE|MATCH|DETACH)\b", statement) is None
    text = "\n".join(migration.statements)
    assert "FOR (n:ProjectedService) ON (n.tenantId, n.endedAt)" in text
    assert "FOR (n:ProjectedCapacity) ON (n.tenantId, n.endedAt)" in text
    assert "FOR (n:ProjectedCriteria) ON (n.tenantId, n.endedAt)" in text
