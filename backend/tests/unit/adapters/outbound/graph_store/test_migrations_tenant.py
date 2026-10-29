"""The expand step of the tenant schema, as data (TEN-005, rule 3). No database.

The twenty composite constraints and six composite indexes are written out literally here, so a
row dropped or a property changed in `migrations_tenant.py` fails a test. The statements are fixed
text in the module (no Cypher is built from pieces, the architecture test), and these tests read
each one back and compare it with its row.
"""

import re
from typing import Final

from diucs.adapters.outbound.graph_store import migrations_tenant as tenant
from diucs.adapters.outbound.graph_store.migrations import CORE_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_network import NETWORK_MIGRATIONS
from diucs.application.tenancy import DEFAULT_TENANT_ID
from tests.support.tenant_seed import (
    SUPERSEDED_CONSTRAINT_NAMES,
    SUPERSEDED_INDEX_NAMES,
    UNSTAMPED_OK,
)

CONSTRAINT_ROWS: Final = (
    ("tenant_resource_id", "Resource", ("tenantId", "id"), "resource_id"),
    ("tenant_resource_key", "Resource", ("tenantId", "key"), None),
    ("tenant_identifier_key", "Identifier", ("tenantId", "system", "value"), "identifier_key"),
    ("tenant_concept_key", "Concept", ("tenantId", "system", "code"), "concept_key"),
    ("tenant_codesystem_url", "CodeSystem", ("tenantId", "url"), None),
    ("tenant_scheduled_work_id", "ScheduledWork", ("tenantId", "id"), "scheduled_work_id"),
    ("tenant_communication_id", "Communication", ("tenantId", "id"), "communication_id"),
    ("tenant_audit_event_id", "AuditEvent", ("tenantId", "id"), "audit_event_id"),
    ("tenant_audit_head_id", "AuditHead", ("tenantId", "id"), "audit_head_id"),
    ("tenant_audit_ref_id", "AuditRef", ("tenantId", "id"), "audit_ref_id"),
    ("tenant_provenance_id", "Provenance", ("tenantId", "id"), "provenance_id"),
    ("tenant_chain_seq", "ChainLink", ("tenantId", "seq"), "chain_seq"),
    ("tenant_device_id", "Device", ("tenantId", "id"), "device_id"),
    (
        "tenant_protected_contact_key",
        "ProtectedContact",
        ("tenantId", "key"),
        "protected_contact_key",
    ),
    ("tenant_credential_device_id", "Credential", ("tenantId", "deviceId"), "credential_device_id"),
    ("tenant_report_flag_id", "ReportFlag", ("tenantId", "id"), "report_flag_id"),
    ("tenant_outbox_message_id", "OutboxMessage", ("tenantId", "id"), "outbox_message_id"),
    (
        "tenant_idempotency_record_key",
        "IdempotencyRecord",
        ("tenantId", "key"),
        "idempotency_record_key",
    ),
    ("tenant_processed_key", "Processed", ("tenantId", "key"), "processed_key"),
    (
        "tenant_case_open_reference",
        "ServiceRequest",
        ("tenantId", "openReference"),
        "case_reference_id",
    ),
)
INDEX_ROWS: Final = (
    ("tenant_obs_by_service", "Observation", ("tenantId", "effectiveDateTime"), "obs_by_service"),
    ("tenant_task_by_status", "Task", ("tenantId", "businessStatus"), "task_by_status"),
    ("tenant_svc_active", "HealthcareService", ("tenantId", "active"), "svc_active"),
    ("tenant_phone_hash", "Practitioner", ("tenantId", "phoneHash"), "phone_hash"),
    (
        "tenant_communication_provider_id",
        "Communication",
        ("tenantId", "providerMessageId"),
        "communication_provider_id",
    ),
    (
        "tenant_protected_contact_role_id",
        "ProtectedContact",
        ("tenantId", "roleId"),
        "protected_contact_role_id",
    ),
)
REGISTRY: Final = ("Migration", "Tenant", "TenantNumber", "Network", "NetworkMembership", "Grant")

_CONSTRAINT = re.compile(
    r"CREATE CONSTRAINT (\w+) IF NOT EXISTS FOR \(n:(\w+)\) REQUIRE \(?([\w., n]+?)\)? IS UNIQUE"
)
_INDEX = re.compile(r"CREATE INDEX (\w+) IF NOT EXISTS FOR \(n:(\w+)\) ON \(([\w., n]+)\)")


def _core_statements() -> list[str]:
    return [statement for migration in CORE_MIGRATIONS for statement in migration.statements]


def _core_names() -> dict[str, str]:
    """Name -> label of every constraint and index the core migrations create."""
    found: dict[str, str] = {}
    for statement in _core_statements():
        match = re.search(
            r"CREATE (?:CONSTRAINT|INDEX|POINT INDEX) (\w+) IF NOT EXISTS FOR \(\w+:(\w+)\)",
            statement,
        )
        assert match, statement
        found[match.group(1)] = match.group(2)
    return found


def _properties(text: str) -> tuple[str, ...]:
    return tuple(part.strip().removeprefix("n.") for part in text.split(","))


# The tables


def test_the_composite_constraints_are_the_twenty_rows_of_the_prompt() -> None:
    rows = tuple((c.name, c.label, c.properties, c.replaces) for c in tenant.COMPOSITE_CONSTRAINTS)
    assert rows == CONSTRAINT_ROWS
    assert len(rows) == 20


def test_the_composite_indexes_are_the_six_rows_of_the_prompt() -> None:
    rows = tuple((i.name, i.label, i.properties, i.replaces) for i in tenant.COMPOSITE_INDEXES)
    assert rows == INDEX_ROWS
    assert len(rows) == 6


def test_every_composite_key_starts_with_the_tenant() -> None:
    for row in (*tenant.COMPOSITE_CONSTRAINTS, *tenant.COMPOSITE_INDEXES):
        assert row.properties[0] == "tenantId", row.name


def test_every_replaced_name_is_a_core_constraint_or_index_on_the_same_label() -> None:
    core = _core_names()
    for row in (*tenant.COMPOSITE_CONSTRAINTS, *tenant.COMPOSITE_INDEXES):
        if row.replaces is None:
            continue
        assert row.replaces in core, row.name
        assert core[row.replaces] == row.label, row.name


def test_two_constraints_are_new_and_the_other_eighteen_replace_one() -> None:
    new = {c.name for c in tenant.COMPOSITE_CONSTRAINTS if c.replaces is None}
    assert new == {"tenant_resource_key", "tenant_codesystem_url"}


def test_the_superseded_lists_are_the_eighteen_constraints_and_the_six_indexes() -> None:
    assert len(tenant.SUPERSEDED_CONSTRAINTS) == 18
    assert len(tenant.SUPERSEDED_INDEXES) == 6
    assert {c.replaces for c in tenant.COMPOSITE_CONSTRAINTS} - {
        None
    } == tenant.SUPERSEDED_CONSTRAINTS
    assert {i.replaces for i in tenant.COMPOSITE_INDEXES} == tenant.SUPERSEDED_INDEXES


def test_the_link_token_hash_and_the_point_index_are_not_superseded() -> None:
    assert "link_token_hash" not in tenant.SUPERSEDED_CONSTRAINTS
    assert "location_position" not in tenant.SUPERSEDED_INDEXES
    assert all(row.label != "LinkToken" for row in tenant.COMPOSITE_CONSTRAINTS)
    assert all(row.label != "LinkToken" for row in tenant.COMPOSITE_INDEXES)


def test_the_superseded_lists_equal_the_literals_of_the_test_support() -> None:
    assert tenant.SUPERSEDED_CONSTRAINTS == SUPERSEDED_CONSTRAINT_NAMES
    assert tenant.SUPERSEDED_INDEXES == SUPERSEDED_INDEX_NAMES


def test_the_case_reference_is_open_only_so_there_is_no_composite_on_the_reference() -> None:
    assert not any("reference" in row.properties for row in tenant.COMPOSITE_CONSTRAINTS)
    assert not any("reference" in row.properties for row in tenant.COMPOSITE_INDEXES)


# Migration 0031


def _0031() -> tuple[str, ...]:
    found = [m for m in tenant.TENANT_MIGRATIONS if m.id == "0031_tenant_composites"]
    assert found, "migration 0031_tenant_composites is not in TENANT_MIGRATIONS"
    return found[0].statements


def test_0031_creates_the_global_constraint_then_twenty_constraints_then_six_indexes() -> None:
    statements = _0031()
    assert len(statements) == 1 + 20 + 6
    assert statements[0] == (
        "CREATE CONSTRAINT migration_id IF NOT EXISTS FOR (n:Migration) REQUIRE n.id IS UNIQUE"
    )
    assert [_CONSTRAINT.match(s).group(1) for s in statements[1:21]] == [  # type: ignore[union-attr]
        row[0] for row in CONSTRAINT_ROWS
    ]
    assert [_INDEX.match(s).group(1) for s in statements[21:]] == [row[0] for row in INDEX_ROWS]  # type: ignore[union-attr]


def test_each_statement_of_0031_says_what_its_row_says() -> None:
    statements = _0031()
    for statement, (name, label, properties, _) in zip(
        statements[1:21], CONSTRAINT_ROWS, strict=True
    ):
        match = _CONSTRAINT.fullmatch(statement)
        assert match, statement
        assert (match.group(1), match.group(2), _properties(match.group(3))) == (
            name,
            label,
            properties,
        )
    for statement, (name, label, properties, _) in zip(statements[21:], INDEX_ROWS, strict=True):
        match = _INDEX.fullmatch(statement)
        assert match, statement
        assert (match.group(1), match.group(2), _properties(match.group(3))) == (
            name,
            label,
            properties,
        )


def test_the_text_of_two_constraints_and_one_index_is_exactly_this() -> None:
    statements = _0031()
    assert statements[1] == (
        "CREATE CONSTRAINT tenant_resource_id IF NOT EXISTS FOR (n:Resource) "
        "REQUIRE (n.tenantId, n.id) IS UNIQUE"
    )
    assert statements[3] == (
        "CREATE CONSTRAINT tenant_identifier_key IF NOT EXISTS FOR (n:Identifier) "
        "REQUIRE (n.tenantId, n.system, n.value) IS UNIQUE"
    )
    assert statements[21] == (
        "CREATE INDEX tenant_obs_by_service IF NOT EXISTS FOR (n:Observation) "
        "ON (n.tenantId, n.effectiveDateTime)"
    )


def test_every_statement_of_0031_is_if_not_exists_and_none_drops_anything() -> None:
    for statement in _0031():
        assert "IF NOT EXISTS" in statement, statement
        assert "DROP" not in statement, statement


def test_0031_touches_no_name_the_core_migrations_own() -> None:
    created = {m.group(1) for s in _0031() if (m := re.match(r"CREATE \w+ (\w+) ", s))}
    assert created.isdisjoint(_core_names())


def test_the_rollback_drops_exactly_what_0031_creates_and_each_with_if_exists() -> None:
    created = {m.group(1) for s in _0031() if (m := re.match(r"CREATE \w+ (\w+) ", s))}
    dropped: set[str] = set()
    for statement in tenant.ROLLBACK_0031:
        match = re.fullmatch(r"DROP (?:CONSTRAINT|INDEX) (\w+) IF EXISTS", statement)
        assert match, statement
        dropped.add(match.group(1))
    assert dropped == created
    assert len(tenant.ROLLBACK_0031) == len(created) == 27
    assert dropped.isdisjoint(_core_names())
    assert sum(s.startswith("DROP CONSTRAINT") for s in tenant.ROLLBACK_0031) == 21


# The backfill and the open reference


def test_the_registry_labels_are_the_six_nodes_that_carry_no_tenant() -> None:
    assert set(tenant.REGISTRY_LABELS) == set(REGISTRY)
    assert len(tenant.REGISTRY_LABELS) == 6


def test_the_seeder_and_the_migration_agree_on_which_labels_carry_no_tenant() -> None:
    assert set(tenant.REGISTRY_LABELS) == UNSTAMPED_OK


def test_the_stamp_names_its_own_parameters_and_never_the_bound_tenant() -> None:
    text = tenant.STAMP_DEFAULT_TENANT
    assert "$defaultTenant" in text
    assert "$registryLabels" in text
    assert "$batch" in text
    assert re.search(r"\$tenant\b", text) is None
    assert "n.tenantId IS NULL" in text
    assert "changed" in text


def test_the_stamp_text_is_exactly_this() -> None:
    assert tenant.STAMP_DEFAULT_TENANT == (
        "MATCH (n) WHERE n.tenantId IS NULL AND none(l IN labels(n) WHERE l IN $registryLabels) "
        "WITH n LIMIT $batch SET n.tenantId = $defaultTenant RETURN count(n) AS changed"
    )


def test_the_open_reference_copy_text_is_exactly_this() -> None:
    assert tenant.OPEN_REFERENCE_BACKFILL == (
        "MATCH (r:ServiceRequest) WHERE r.status = 'active' AND r.reference IS NOT NULL "
        "AND r.openReference IS NULL WITH r LIMIT $batch SET r.openReference = r.reference "
        "RETURN count(r) AS changed"
    )


def test_the_invariant_queries_are_exactly_these() -> None:
    assert tenant.UNSTAMPED_NODES_QUERY == (
        "MATCH (n) WHERE n.tenantId IS NULL AND none(l IN labels(n) WHERE l IN $registryLabels) "
        "RETURN labels(n) AS labels, count(*) AS n"
    )
    assert tenant.CROSS_SCOPE_RELATIONSHIPS_QUERY == (
        "MATCH (a)-[r]->(b) WHERE a.tenantId IS NOT NULL AND b.tenantId IS NOT NULL "
        "AND a.tenantId <> b.tenantId RETURN type(r) AS type, count(*) AS n"
    )


def test_the_tenant_migrations_are_in_the_order_constraints_stamp_open_reference() -> None:
    ids = [m.id for m in tenant.TENANT_MIGRATIONS]
    assert ids[:3] == [
        "0031_tenant_composites",
        "0032_backfill_default_tenant",
        "0033_case_open_reference",
    ]
    composites, stamp, reference = tenant.TENANT_MIGRATIONS[:3]
    assert composites.loops == () and dict(composites.params) == {}
    assert stamp.statements == ()
    assert stamp.loops == (tenant.STAMP_DEFAULT_TENANT,)
    assert dict(stamp.params) == {
        "registryLabels": list(tenant.REGISTRY_LABELS),
        "defaultTenant": DEFAULT_TENANT_ID,
    }
    assert reference.statements == ()
    assert reference.loops == (tenant.OPEN_REFERENCE_BACKFILL,)


def test_the_network_list_is_empty_until_the_network_tasks() -> None:
    assert NETWORK_MIGRATIONS == ()
