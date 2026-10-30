"""Integration tests for the Neo4j adapter base (G01): driver, named queries, migrations.

They run against a real Neo4j. The five schema tests remove the (:Migration) bookkeeping nodes,
drop an index and assert the exact schema, so they run on a private container (`own_neo4j`, marker
`schema`, TEN-034) that no other run uses; on the shared database they would break every other
run's schema. The three `run_query` tests are ordinary tests on the harness database. The harness
never uses the compose stack on port 7687.
"""

import logging

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS, apply_migrations
from diucs.adapters.outbound.graph_store.queries import NamedQuery
from tests.support.leaky_registry import LeakyRegistry
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.scoped import scoped

# Derived from the list (TEN-005): a later task adds its migrations in its own area module and no
# number is edited. The unit test test_migration_ids.py pins it to 26 core + the tenant + network.
EXPECTED_MIGRATION_COUNT = len(MIGRATIONS)
EXPECTED_CONSTRAINTS = {"tenant_resource_id", "tenant_identifier_key", "tenant_concept_key"}
# The single-property keys they replaced went with TEN-032.
DROPPED_CONSTRAINTS = {"resource_id", "identifier_key", "concept_key"}
EXPECTED_INDEXES = {
    "obs_by_service",
    "task_by_status",
    "svc_active",
    "phone_hash",
    "location_position",
}

# A registry of this file's own (DEC-142): the test statements are not tenant-scoped, so they sit in
# a LeakyRegistry (tests/support), which the production registry would refuse. They run on a scoped
# transaction with the run tenant bound by the conftest, and are never registered in the module
# registry.
_TEST_REGISTRY = LeakyRegistry()
_TEST_REGISTRY.register(NamedQuery(id="Q-TEST-ECHO", cypher="RETURN $x AS x", mode="read"))
# The label does not exist, so the server sends a warning; the driver used to log the query text.
_TEST_REGISTRY.register(
    NamedQuery(
        id="Q-TEST-WARN",
        cypher="MATCH (zzmarkerlabel:NoSuchLabelForG01) RETURN zzmarkerlabel",
        mode="read",
    )
)
_ECHO = _TEST_REGISTRY.get("Q-TEST-ECHO")
_WARN = _TEST_REGISTRY.get("Q-TEST-WARN")


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def schema_driver(own_neo4j: tuple[ThrowawayNeo4j, AsyncDriver]) -> AsyncDriver:
    """The private container of this module, migrated by the harness."""
    return own_neo4j[1]


async def _reset_bookkeeping(driver: AsyncDriver) -> None:
    async with driver.session() as session:
        await session.run("MATCH (m:Migration) DETACH DELETE m")


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.schema
async def test_apply_migrations_applies_every_migration_then_none_on_the_second_call(
    schema_driver: AsyncDriver,
) -> None:
    await _reset_bookkeeping(schema_driver)

    first = await apply_migrations(schema_driver)
    assert len(first) == EXPECTED_MIGRATION_COUNT
    assert first == [migration.id for migration in MIGRATIONS]

    second = await apply_migrations(schema_driver)
    assert second == []


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.schema
async def test_each_applied_migration_is_recorded_with_an_id_and_a_utc_time(
    schema_driver: AsyncDriver,
) -> None:
    await apply_migrations(schema_driver)
    async with schema_driver.session() as session:
        result = await session.run(
            "MATCH (m:Migration) RETURN m.id AS id, m.appliedAt AS appliedAt ORDER BY m.id"
        )
        records = [record.data() async for record in result]
    assert sorted(r["id"] for r in records) == sorted(m.id for m in MIGRATIONS)
    for record in records:
        assert record["appliedAt"].tzinfo is not None


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.schema
async def test_schema_has_the_named_constraints_and_indexes(schema_driver: AsyncDriver) -> None:
    await apply_migrations(schema_driver)
    async with schema_driver.session() as session:
        constraints = {
            r["name"] async for r in await session.run("SHOW CONSTRAINTS YIELD name RETURN name")
        }
        indexes = {
            r["name"] async for r in await session.run("SHOW INDEXES YIELD name RETURN name")
        }
    assert constraints >= EXPECTED_CONSTRAINTS
    assert constraints.isdisjoint(DROPPED_CONSTRAINTS)
    assert indexes >= EXPECTED_INDEXES


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.schema
async def test_every_migration_statement_runs_twice_in_separate_sessions(
    schema_driver: AsyncDriver,
) -> None:
    # A missing IF NOT EXISTS fails the second run against an object the first run created, and a
    # loop that is not idempotent changes something on the second run.
    await apply_migrations(schema_driver)
    for migration in MIGRATIONS:
        for statement in migration.statements:
            for _ in range(2):
                async with schema_driver.session() as session:
                    await session.run(statement, dict(migration.params))
        for loop in migration.loops:
            for _ in range(2):
                async with schema_driver.session() as session:
                    result = await session.run(loop, {**migration.params, "batch": migration.batch})
                    assert [r["changed"] async for r in result] == [0]


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.schema
async def test_reapplying_over_an_existing_schema_recreates_a_dropped_index(
    schema_driver: AsyncDriver,
) -> None:
    await apply_migrations(schema_driver)
    async with schema_driver.session() as session:
        await session.run("DROP INDEX obs_by_service IF EXISTS")
    await _reset_bookkeeping(schema_driver)

    reapplied = await apply_migrations(schema_driver)

    assert reapplied == [migration.id for migration in MIGRATIONS]
    async with schema_driver.session() as session:
        indexes = {
            r["name"] async for r in await session.run("SHOW INDEXES YIELD name RETURN name")
        }
    assert "obs_by_service" in indexes


@pytest.mark.asyncio(loop_scope="session")
async def test_a_registered_named_query_runs_in_a_read_transaction(
    neo4j_driver: AsyncDriver,
) -> None:
    async def work(tx: object) -> list[dict[str, object]]:
        return await run_query(scoped(tx), _ECHO, registry=_TEST_REGISTRY, x=1)

    async with neo4j_driver.session() as session:
        rows = await session.execute_read(work)
    assert rows == [{"x": 1}]


@pytest.mark.asyncio(loop_scope="session")
async def test_run_query_logs_no_cypher_text_even_when_the_server_warns(
    neo4j_driver: AsyncDriver, caplog: pytest.LogCaptureFixture
) -> None:
    # WARNING is the level a service logs at. The neo4j.io logger also writes Cypher at DEBUG,
    # so the logging configuration must keep the neo4j loggers above DEBUG (see the evidence file).
    caplog.set_level(logging.WARNING)

    async def work(tx: object) -> list[dict[str, object]]:
        return await run_query(scoped(tx), _WARN, registry=_TEST_REGISTRY)

    async with neo4j_driver.session() as session:
        await session.execute_read(work)
    assert "zzmarkerlabel" not in caplog.text


@pytest.mark.asyncio(loop_scope="session")
async def test_run_query_logs_no_cypher_text_even_at_debug(
    neo4j_driver: AsyncDriver, caplog: pytest.LogCaptureFixture
) -> None:
    # The Bolt logger (neo4j.io) writes RUN messages with the Cypher text at DEBUG. The driver must
    # keep it off the log even when the root logger asks for DEBUG.
    caplog.set_level(logging.DEBUG)

    async def work(tx: object) -> list[dict[str, object]]:
        return await run_query(scoped(tx), _ECHO, registry=_TEST_REGISTRY, x=1)

    async with neo4j_driver.session() as session:
        await session.execute_read(work)
    assert "RETURN $x AS x" not in caplog.text
    assert "RETURN" not in caplog.text


def test_migration_ids_are_unique_and_run_in_ascending_order() -> None:
    # P05, P07 and P08 each chose ids (lesson L68); a duplicate or out-of-order id would make one
    # migration silently skipped or applied before the one it follows.
    ids = [migration.id for migration in MIGRATIONS]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids)
    assert "0009_scheduled_work_id" in ids
