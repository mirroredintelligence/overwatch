"""Idempotent Neo4j schema migrations, for Neo4j Community 5.

Every statement uses IF NOT EXISTS, and each applied migration is recorded as (:Migration {id,
appliedAt}) so it is skipped next time. Later tasks append migrations; never edit an applied one.

Enterprise-only features this file does not use, so they are not needed (and would change this
file if adopted): NODE KEY constraints (the composite uniqueness here is UNIQUE, which Community
supports), role-based access control (one user, no roles created here) and multiple databases
(everything lives in the default database). The production edition is an open decision; nothing
here depends on it.
"""

from datetime import UTC, datetime

from neo4j import AsyncDriver, AsyncManagedTransaction

MIGRATIONS: list[tuple[str, str]] = [
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
]

_APPLIED = "MATCH (m:Migration) RETURN m.id AS id"
_RECORD = "MERGE (m:Migration {id: $id}) ON CREATE SET m.appliedAt = $appliedAt"


async def _applied_ids(tx: AsyncManagedTransaction) -> set[str]:
    result = await tx.run(_APPLIED)
    return {row["id"] for row in await result.data()}


async def _run_statement(tx: AsyncManagedTransaction, statement: str) -> None:
    # Neo4j refuses a data write in the same transaction as a schema change, so the statement
    # and the bookkeeping node are two transactions. Both are idempotent: IF NOT EXISTS and MERGE.
    await tx.run(statement)


async def _record(tx: AsyncManagedTransaction, migration_id: str) -> None:
    await tx.run(_RECORD, id=migration_id, appliedAt=datetime.now(UTC))


async def apply_migrations(driver: AsyncDriver) -> list[str]:
    """Apply every migration not yet recorded, in order. Return the ids applied by this call.

    A crash between the statement and its record re-runs the statement on the next start, which
    is a no-op because of IF NOT EXISTS.
    """
    async with driver.session() as session:
        applied = await session.execute_read(_applied_ids)
    newly_applied: list[str] = []
    for migration_id, statement in MIGRATIONS:
        if migration_id in applied:
            continue
        async with driver.session() as session:
            await session.execute_write(_run_statement, statement)
        async with driver.session() as session:
            await session.execute_write(_record, migration_id)
        newly_applied.append(migration_id)
    return newly_applied
