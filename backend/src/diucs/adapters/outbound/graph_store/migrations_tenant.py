"""The expand step of the tenant schema (TEN-005, DEC-130 item 7, DEC-134 items 10, 11 and 13).

Composite uniqueness: every key a tenant can hold is unique per tenant (`tenantId` plus the key),
created beside the single-property constraint it replaces, which stays until TEN-032 drops it (the
contract step). Nothing here is dropped, so the old and the new code both work. Then every node
that is not a registry node is stamped with the default tenant, in batches that can be repeated,
and an open case gets the property its per-tenant reference constraint is unique on.

All of it runs on the global path: migrations are raw transactions, outside `run_query`, outside
the registry and outside any bound tenant. The stamp names its own parameter, `$defaultTenant`,
and never `$tenant`: that name is only ever the bound tenant (DEC-134).

The statements are fixed text, written out in full (no Cypher is built from pieces, DEC-142 item
1); `tests/unit/adapters/outbound/graph_store/test_migrations_tenant.py` reads each one back and
compares it with its row.

Limit, stated: Neo4j Community has no existence constraint, and a composite constraint ignores a
node whose `tenantId` is null. A node written without a tenant is therefore not caught by the
constraint; `invariant_violations` is the query that finds it (TEN-031 runs it at start-up).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.migration_loop import run_loop
from diucs.adapters.outbound.graph_store.migration_types import MAX_LOOP_ITERATIONS, Migration
from diucs.application.tenancy import DEFAULT_TENANT_ID

# Labels of registry nodes: they carry no `tenantId` (the migration record, and the tenant and
# network registry of DEC-132). Everything else is a tenant's.
REGISTRY_LABELS: Final = (
    "Migration",
    "Tenant",
    "TenantNumber",
    "Network",
    "NetworkMembership",
    "Grant",
)


@dataclass(frozen=True, slots=True)
class CompositeConstraint:
    name: str
    label: str
    properties: tuple[str, ...]
    replaces: str | None


@dataclass(frozen=True, slots=True)
class CompositeIndex:
    name: str
    label: str
    properties: tuple[str, ...]
    replaces: str


COMPOSITE_CONSTRAINTS: Final = (
    CompositeConstraint("tenant_resource_id", "Resource", ("tenantId", "id"), "resource_id"),
    CompositeConstraint("tenant_resource_key", "Resource", ("tenantId", "key"), None),
    CompositeConstraint(
        "tenant_identifier_key", "Identifier", ("tenantId", "system", "value"), "identifier_key"
    ),
    CompositeConstraint(
        "tenant_concept_key", "Concept", ("tenantId", "system", "code"), "concept_key"
    ),
    CompositeConstraint("tenant_codesystem_url", "CodeSystem", ("tenantId", "url"), None),
    CompositeConstraint(
        "tenant_scheduled_work_id", "ScheduledWork", ("tenantId", "id"), "scheduled_work_id"
    ),
    CompositeConstraint(
        "tenant_communication_id", "Communication", ("tenantId", "id"), "communication_id"
    ),
    CompositeConstraint(
        "tenant_audit_event_id", "AuditEvent", ("tenantId", "id"), "audit_event_id"
    ),
    CompositeConstraint("tenant_audit_head_id", "AuditHead", ("tenantId", "id"), "audit_head_id"),
    CompositeConstraint("tenant_audit_ref_id", "AuditRef", ("tenantId", "id"), "audit_ref_id"),
    CompositeConstraint("tenant_provenance_id", "Provenance", ("tenantId", "id"), "provenance_id"),
    CompositeConstraint("tenant_chain_seq", "ChainLink", ("tenantId", "seq"), "chain_seq"),
    CompositeConstraint("tenant_device_id", "Device", ("tenantId", "id"), "device_id"),
    CompositeConstraint(
        "tenant_protected_contact_key",
        "ProtectedContact",
        ("tenantId", "key"),
        "protected_contact_key",
    ),
    CompositeConstraint(
        "tenant_credential_device_id",
        "Credential",
        ("tenantId", "deviceId"),
        "credential_device_id",
    ),
    CompositeConstraint(
        "tenant_report_flag_id", "ReportFlag", ("tenantId", "id"), "report_flag_id"
    ),
    CompositeConstraint(
        "tenant_outbox_message_id", "OutboxMessage", ("tenantId", "id"), "outbox_message_id"
    ),
    CompositeConstraint(
        "tenant_idempotency_record_key",
        "IdempotencyRecord",
        ("tenantId", "key"),
        "idempotency_record_key",
    ),
    CompositeConstraint("tenant_processed_key", "Processed", ("tenantId", "key"), "processed_key"),
    CompositeConstraint(
        "tenant_case_open_reference",
        "ServiceRequest",
        ("tenantId", "openReference"),
        "case_reference_id",
    ),
)
COMPOSITE_INDEXES: Final = (
    CompositeIndex(
        "tenant_obs_by_service", "Observation", ("tenantId", "effectiveDateTime"), "obs_by_service"
    ),
    CompositeIndex(
        "tenant_task_by_status", "Task", ("tenantId", "businessStatus"), "task_by_status"
    ),
    CompositeIndex("tenant_svc_active", "HealthcareService", ("tenantId", "active"), "svc_active"),
    CompositeIndex("tenant_phone_hash", "Practitioner", ("tenantId", "phoneHash"), "phone_hash"),
    CompositeIndex(
        "tenant_communication_provider_id",
        "Communication",
        ("tenantId", "providerMessageId"),
        "communication_provider_id",
    ),
    CompositeIndex(
        "tenant_protected_contact_role_id",
        "ProtectedContact",
        ("tenantId", "roleId"),
        "protected_contact_role_id",
    ),
)

# The names TEN-032 drops (data for the contract step, one source). `link_token_hash` stays: a
# token hash is looked up without a scope (DEC-131 item 5), so it is globally unique. The point
# index `location_position` stays: a point index is single-property.
SUPERSEDED_CONSTRAINTS: Final = frozenset(
    c.replaces for c in COMPOSITE_CONSTRAINTS if c.replaces is not None
)
SUPERSEDED_INDEXES: Final = frozenset(i.replaces for i in COMPOSITE_INDEXES)

# Migration 0031, in this order: the global constraint (registry nodes carry no tenant, so it is
# not composite), the composite constraints, the composite indexes. One statement each: a schema
# statement cannot share a transaction with another or with a data write (lesson L8).
_STATEMENTS_0031: Final = (
    "CREATE CONSTRAINT migration_id IF NOT EXISTS FOR (n:Migration) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT tenant_resource_id IF NOT EXISTS FOR (n:Resource) "
    "REQUIRE (n.tenantId, n.id) IS UNIQUE",
    "CREATE CONSTRAINT tenant_resource_key IF NOT EXISTS FOR (n:Resource) "
    "REQUIRE (n.tenantId, n.key) IS UNIQUE",
    "CREATE CONSTRAINT tenant_identifier_key IF NOT EXISTS FOR (n:Identifier) "
    "REQUIRE (n.tenantId, n.system, n.value) IS UNIQUE",
    "CREATE CONSTRAINT tenant_concept_key IF NOT EXISTS FOR (n:Concept) "
    "REQUIRE (n.tenantId, n.system, n.code) IS UNIQUE",
    "CREATE CONSTRAINT tenant_codesystem_url IF NOT EXISTS FOR (n:CodeSystem) "
    "REQUIRE (n.tenantId, n.url) IS UNIQUE",
    "CREATE CONSTRAINT tenant_scheduled_work_id IF NOT EXISTS FOR (n:ScheduledWork) "
    "REQUIRE (n.tenantId, n.id) IS UNIQUE",
    "CREATE CONSTRAINT tenant_communication_id IF NOT EXISTS FOR (n:Communication) "
    "REQUIRE (n.tenantId, n.id) IS UNIQUE",
    "CREATE CONSTRAINT tenant_audit_event_id IF NOT EXISTS FOR (n:AuditEvent) "
    "REQUIRE (n.tenantId, n.id) IS UNIQUE",
    "CREATE CONSTRAINT tenant_audit_head_id IF NOT EXISTS FOR (n:AuditHead) "
    "REQUIRE (n.tenantId, n.id) IS UNIQUE",
    "CREATE CONSTRAINT tenant_audit_ref_id IF NOT EXISTS FOR (n:AuditRef) "
    "REQUIRE (n.tenantId, n.id) IS UNIQUE",
    "CREATE CONSTRAINT tenant_provenance_id IF NOT EXISTS FOR (n:Provenance) "
    "REQUIRE (n.tenantId, n.id) IS UNIQUE",
    "CREATE CONSTRAINT tenant_chain_seq IF NOT EXISTS FOR (n:ChainLink) "
    "REQUIRE (n.tenantId, n.seq) IS UNIQUE",
    "CREATE CONSTRAINT tenant_device_id IF NOT EXISTS FOR (n:Device) "
    "REQUIRE (n.tenantId, n.id) IS UNIQUE",
    "CREATE CONSTRAINT tenant_protected_contact_key IF NOT EXISTS FOR (n:ProtectedContact) "
    "REQUIRE (n.tenantId, n.key) IS UNIQUE",
    "CREATE CONSTRAINT tenant_credential_device_id IF NOT EXISTS FOR (n:Credential) "
    "REQUIRE (n.tenantId, n.deviceId) IS UNIQUE",
    "CREATE CONSTRAINT tenant_report_flag_id IF NOT EXISTS FOR (n:ReportFlag) "
    "REQUIRE (n.tenantId, n.id) IS UNIQUE",
    "CREATE CONSTRAINT tenant_outbox_message_id IF NOT EXISTS FOR (n:OutboxMessage) "
    "REQUIRE (n.tenantId, n.id) IS UNIQUE",
    "CREATE CONSTRAINT tenant_idempotency_record_key IF NOT EXISTS FOR (n:IdempotencyRecord) "
    "REQUIRE (n.tenantId, n.key) IS UNIQUE",
    "CREATE CONSTRAINT tenant_processed_key IF NOT EXISTS FOR (n:Processed) "
    "REQUIRE (n.tenantId, n.key) IS UNIQUE",
    "CREATE CONSTRAINT tenant_case_open_reference IF NOT EXISTS FOR (n:ServiceRequest) "
    "REQUIRE (n.tenantId, n.openReference) IS UNIQUE",
    "CREATE INDEX tenant_obs_by_service IF NOT EXISTS FOR (n:Observation) "
    "ON (n.tenantId, n.effectiveDateTime)",
    "CREATE INDEX tenant_task_by_status IF NOT EXISTS FOR (n:Task) "
    "ON (n.tenantId, n.businessStatus)",
    "CREATE INDEX tenant_svc_active IF NOT EXISTS FOR (n:HealthcareService) "
    "ON (n.tenantId, n.active)",
    "CREATE INDEX tenant_phone_hash IF NOT EXISTS FOR (n:Practitioner) "
    "ON (n.tenantId, n.phoneHash)",
    "CREATE INDEX tenant_communication_provider_id IF NOT EXISTS FOR (n:Communication) "
    "ON (n.tenantId, n.providerMessageId)",
    "CREATE INDEX tenant_protected_contact_role_id IF NOT EXISTS FOR (n:ProtectedContact) "
    "ON (n.tenantId, n.roleId)",
)

STAMP_DEFAULT_TENANT: Final = (
    "MATCH (n) WHERE n.tenantId IS NULL AND none(l IN labels(n) WHERE l IN $registryLabels) "
    "WITH n LIMIT $batch SET n.tenantId = $defaultTenant RETURN count(n) AS changed"
)
OPEN_REFERENCE_BACKFILL: Final = (
    "MATCH (r:ServiceRequest) WHERE r.status = 'active' AND r.reference IS NOT NULL "
    "AND r.openReference IS NULL WITH r LIMIT $batch SET r.openReference = r.reference "
    "RETURN count(r) AS changed"
)

# The two invariants of audit A 3.3, for the start-up and daily check (TEN-031): no node outside the
# registry without a tenant, and no relationship between two tenants. Both empty means they hold.
UNSTAMPED_NODES_QUERY: Final = (
    "MATCH (n) WHERE n.tenantId IS NULL AND none(l IN labels(n) WHERE l IN $registryLabels) "
    "RETURN labels(n) AS labels, count(*) AS n"
)
CROSS_SCOPE_RELATIONSHIPS_QUERY: Final = (
    "MATCH (a)-[r]->(b) WHERE a.tenantId IS NOT NULL AND b.tenantId IS NOT NULL "
    "AND a.tenantId <> b.tenantId RETURN type(r) AS type, count(*) AS n"
)

# The manual inverse of 0031. The runner never runs it: the step is additive (old code ignores the
# new constraints), so reverting the application needs no schema change. It drops everything 0031
# creates and nothing the old schema owns.
ROLLBACK_0031: Final = (
    "DROP CONSTRAINT migration_id IF EXISTS",
    *(f"DROP CONSTRAINT {c.name} IF EXISTS" for c in COMPOSITE_CONSTRAINTS),
    *(f"DROP INDEX {i.name} IF EXISTS" for i in COMPOSITE_INDEXES),
)

# Order matters: the constraints first, then the stamp, then the open-reference copy, so the new
# constraints guard the data as it is stamped.
TENANT_MIGRATIONS: Final = (
    Migration("0031_tenant_composites", statements=_STATEMENTS_0031),
    Migration(
        "0032_backfill_default_tenant",
        loops=(STAMP_DEFAULT_TENANT,),
        params={"registryLabels": list(REGISTRY_LABELS), "defaultTenant": DEFAULT_TENANT_ID},
    ),
    Migration("0033_case_open_reference", loops=(OPEN_REFERENCE_BACKFILL,)),
)


async def backfill_default_tenant(driver: AsyncDriver, *, batch: int = 10_000) -> int:
    """Stamp every unstamped node outside the registry with the default tenant, in repeated
    transactions, and return how many were stamped. Migration 0032 runs the same statement; this
    is also the repair when old code overwrote a stamp (`SET n = props` erases `tenantId`, and the
    migration is recorded as applied, so it will not run again by itself)."""
    migration = TENANT_MIGRATIONS[1]
    return await run_loop(
        driver,
        STAMP_DEFAULT_TENANT,
        migration.params,
        batch=batch,
        max_iterations=MAX_LOOP_ITERATIONS,
    )


async def invariant_violations(driver: AsyncDriver) -> Mapping[str, list[dict[str, Any]]]:
    """The rows of each invariant query, in one read transaction. Both empty: it holds."""

    async def read(tx: AsyncManagedTransaction) -> dict[str, list[dict[str, Any]]]:
        unstamped = await tx.run(UNSTAMPED_NODES_QUERY, {"registryLabels": list(REGISTRY_LABELS)})
        crossing = await tx.run(CROSS_SCOPE_RELATIONSHIPS_QUERY)
        return {
            "unstamped_nodes": await unstamped.data(),
            "cross_scope_relationships": await crossing.data(),
        }

    async with driver.session() as session:
        return await session.execute_read(read)
