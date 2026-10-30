"""Idempotent Neo4j schema migrations, for Neo4j Community 5.

Every statement uses IF NOT EXISTS, and each applied migration is recorded as (:Migration {id,
appliedAt}) so it is skipped next time. Never edit an applied migration (a unit test pins a digest
of the core list). The list is assembled from per-area modules, so a later task adds its own ids to
its own module and never edits the core list: `migrations_tenant.py` (the tenant schema, TEN-005,
TEN-007, TEN-031, TEN-032), `migrations_tenant_config.py` (the tenant configuration records,
TEN-026) and `migrations_network.py` (the network registry and projections, TEN-051,
TEN-053). Ids stay unique and ascending across all areas.

Migrations run on the global path: raw transactions, outside `run_query`, the registry and any
bound tenant.

Enterprise-only features this file does not use, so they are not needed (and would change this
file if adopted): NODE KEY constraints (the composite uniqueness here is UNIQUE, which Community
supports), role-based access control (one user, no roles created here) and multiple databases
(everything lives in the default database). The production edition is an open decision; nothing
here depends on it.
"""

from collections.abc import Awaitable, Sequence
from datetime import UTC, datetime
from typing import Final

from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.migration_loop import run_loop
from diucs.adapters.outbound.graph_store.migration_types import (
    MAX_LOOP_ITERATIONS,
    Migration,
    MigrationFailed,
)
from diucs.adapters.outbound.graph_store.migrations_network import NETWORK_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_protected import PROTECTED_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_support import SUPPORT_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_tenant import TENANT_MIGRATIONS
from diucs.adapters.outbound.graph_store.migrations_tenant_config import TENANT_CONFIG_MIGRATIONS

_CORE_MIGRATIONS: list[tuple[str, str]] = [
    (
        "0001_resource_id",
        "CREATE CONSTRAINT resource_id IF NOT EXISTS FOR (n:Resource) REQUIRE n.id IS UNIQUE",
    ),
    (
        "0002_identifier_key",
        "CREATE CONSTRAINT identifier_key IF NOT EXISTS FOR (n:Identifier) "
        "REQUIRE (n.system, n.value) IS UNIQUE",
    ),
    (
        "0003_concept_key",
        "CREATE CONSTRAINT concept_key IF NOT EXISTS FOR (n:Concept) "
        "REQUIRE (n.system, n.code) IS UNIQUE",
    ),
    (
        "0004_obs_by_service",
        "CREATE INDEX obs_by_service IF NOT EXISTS FOR (o:Observation) ON (o.effectiveDateTime)",
    ),
    (
        "0005_task_by_status",
        "CREATE INDEX task_by_status IF NOT EXISTS FOR (t:Task) ON (t.status, t.businessStatus)",
    ),
    (
        "0006_svc_active",
        "CREATE INDEX svc_active IF NOT EXISTS FOR (s:HealthcareService) ON (s.active)",
    ),
    (
        "0007_phone_hash",
        "CREATE INDEX phone_hash IF NOT EXISTS FOR (p:Practitioner) ON (p.phoneHash)",
    ),
    (
        "0008_location_position",
        "CREATE POINT INDEX location_position IF NOT EXISTS FOR (l:Location) ON (l.position)",
    ),
    (
        "0009_scheduled_work_id",
        "CREATE CONSTRAINT scheduled_work_id IF NOT EXISTS "
        "FOR (n:ScheduledWork) REQUIRE n.id IS UNIQUE",
    ),
    (
        "0014_communication_id",
        "CREATE CONSTRAINT communication_id IF NOT EXISTS "
        "FOR (n:Communication) REQUIRE n.id IS UNIQUE",
    ),
    (
        "0015_communication_provider_id",
        "CREATE INDEX communication_provider_id IF NOT EXISTS FOR (n:Communication) "
        "ON (n.providerMessageId)",
    ),
    (
        "0016_audit_event_id",
        "CREATE CONSTRAINT audit_event_id IF NOT EXISTS FOR (n:AuditEvent) REQUIRE n.id IS UNIQUE",
    ),
    (
        "0017_audit_head_id",
        "CREATE CONSTRAINT audit_head_id IF NOT EXISTS FOR (n:AuditHead) REQUIRE n.id IS UNIQUE",
    ),
    (
        "0018_audit_ref_id",
        "CREATE CONSTRAINT audit_ref_id IF NOT EXISTS FOR (n:AuditRef) REQUIRE n.id IS UNIQUE",
    ),
    (
        "0019_provenance_id",
        "CREATE CONSTRAINT provenance_id IF NOT EXISTS FOR (n:Provenance) REQUIRE n.id IS UNIQUE",
    ),
    (
        "0020_chain_seq",
        "CREATE CONSTRAINT chain_seq IF NOT EXISTS FOR (n:ChainLink) REQUIRE n.seq IS UNIQUE",
    ),
    (
        "0021_link_token_hash",
        "CREATE CONSTRAINT link_token_hash IF NOT EXISTS "
        "FOR (n:LinkToken) REQUIRE n.tokenHash IS UNIQUE",
    ),
    (
        "0022_case_reference_id",
        "CREATE CONSTRAINT case_reference_id IF NOT EXISTS "
        "FOR (n:ServiceRequest) REQUIRE n.reference IS UNIQUE",
    ),
    (
        "0023_device_id",
        "CREATE CONSTRAINT device_id IF NOT EXISTS FOR (n:Device) REQUIRE n.id IS UNIQUE",
    ),
    (
        "0024_protected_contact_role_id",
        "CREATE INDEX protected_contact_role_id IF NOT EXISTS "
        "FOR (n:ProtectedContact) ON (n.roleId)",
    ),
    (
        "0025_protected_contact_key",
        "CREATE CONSTRAINT protected_contact_key IF NOT EXISTS "
        "FOR (n:ProtectedContact) REQUIRE n.key IS UNIQUE",
    ),
    (
        "0026_credential_device_id",
        "CREATE CONSTRAINT credential_device_id IF NOT EXISTS "
        "FOR (n:Credential) REQUIRE n.deviceId IS UNIQUE",
    ),
    (
        "0027_report_flag_id",
        "CREATE CONSTRAINT report_flag_id IF NOT EXISTS FOR (n:ReportFlag) REQUIRE n.id IS UNIQUE",
    ),
    (
        "0028_outbox_message_id",
        "CREATE CONSTRAINT outbox_message_id IF NOT EXISTS "
        "FOR (n:OutboxMessage) REQUIRE n.id IS UNIQUE",
    ),
    (
        "0029_idempotency_key",
        "CREATE CONSTRAINT idempotency_record_key IF NOT EXISTS "
        "FOR (n:IdempotencyRecord) REQUIRE n.key IS UNIQUE",
    ),
    (
        "0030_processed_key",
        "CREATE CONSTRAINT processed_key IF NOT EXISTS FOR (n:Processed) REQUIRE n.key IS UNIQUE",
    ),
]

CORE_MIGRATIONS: Final = tuple(
    Migration(migration_id, (statement,)) for migration_id, statement in _CORE_MIGRATIONS
)


def assemble_migrations(*areas: Sequence[Migration]) -> list[Migration]:
    """The migrations of every area, sorted by id. A duplicate id, across areas or inside one, is a
    ValueError at import: two migrations with one id would make one of them silently skipped."""
    combined = [migration for area in areas for migration in area]
    seen: set[str] = set()
    for migration in combined:
        if migration.id in seen:
            raise ValueError(f"the migration id {migration.id} is used twice")
        seen.add(migration.id)
    return sorted(combined, key=lambda migration: migration.id)


MIGRATIONS: Final[list[Migration]] = assemble_migrations(
    CORE_MIGRATIONS,
    TENANT_MIGRATIONS,
    TENANT_CONFIG_MIGRATIONS,
    NETWORK_MIGRATIONS,
    PROTECTED_MIGRATIONS,
    SUPPORT_MIGRATIONS,
)

_APPLIED = "MATCH (m:Migration) RETURN m.id AS id"
_RECORD = "MERGE (m:Migration {id: $id}) ON CREATE SET m.appliedAt = $appliedAt"


async def _applied_ids(tx: AsyncManagedTransaction) -> set[str]:
    result = await tx.run(_APPLIED)
    return {row["id"] for row in await result.data()}


async def _step[T](migration: Migration, step: str, call: Awaitable[T]) -> T:
    """Await one step. A failure is a MigrationFailed that names the migration, the step and the
    class of the cause, and never a statement or a value; the cause is chained."""
    try:
        return await call
    except Exception as error:
        raise MigrationFailed(
            f"migration {migration.id} failed at {step}: {type(error).__name__}"
        ) from error


async def _run_statement(driver: AsyncDriver, statement: str, params: dict[str, object]) -> None:
    # Neo4j refuses a data write in the same transaction as a schema change (lesson L8), so each
    # statement is its own transaction and the record is another. All are idempotent: IF NOT EXISTS,
    # a loop that selects only what is still to do, and MERGE.
    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(statement, params)

    async with driver.session() as session:
        await session.execute_write(work)


async def _record(driver: AsyncDriver, migration_id: str) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(_RECORD, id=migration_id, appliedAt=datetime.now(UTC))

    async with driver.session() as session:
        await session.execute_write(work)


async def _apply_one(driver: AsyncDriver, migration: Migration) -> None:
    params = dict(migration.params)
    for number, statement in enumerate(migration.statements, start=1):
        await _step(migration, f"statement {number}", _run_statement(driver, statement, params))
    for number, loop in enumerate(migration.loops, start=1):
        loop_step = run_loop(
            driver, loop, params, batch=migration.batch, max_iterations=MAX_LOOP_ITERATIONS
        )
        await _step(migration, f"loop {number}", loop_step)
    await _step(migration, "record", _record(driver, migration.id))


async def apply_migrations(
    driver: AsyncDriver, migrations: Sequence[Migration] | None = None
) -> list[str]:
    """Apply every migration not yet recorded, in order. Return the ids applied by this call.

    For each one: its schema statements, each in its own write transaction; then its loop steps,
    each repetition in its own session and transaction until the step reports no change; then the
    record, last, in a transaction of its own. A failure raises MigrationFailed and nothing after
    the failing step runs: the steps before it stay applied, the migration is not recorded, and
    the later migrations are not attempted. A crash between the last step and the record re-runs
    the steps on the next start, which is safe because every step is idempotent.

    `migrations` is for tests; the default is the assembled list.
    """
    plan = MIGRATIONS if migrations is None else list(migrations)
    async with driver.session() as session:
        applied = await session.execute_read(_applied_ids)
    newly_applied: list[str] = []
    for migration in plan:
        if migration.id in applied:
            continue
        await _apply_one(driver, migration)
        newly_applied.append(migration.id)
    return newly_applied
