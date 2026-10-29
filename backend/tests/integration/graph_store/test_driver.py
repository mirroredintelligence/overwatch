"""Integration tests for the Neo4j adapter base (G01): driver, named queries, migrations.

They run against a real Neo4j: the throwaway container that the F10 harness starts for the pytest
session (DEC-008), through the session-scoped `neo4j_driver` fixture in tests/conftest.py. The
harness never uses the shared diucs-local stack on port 7687.

Some tests remove (:Migration) bookkeeping nodes, and one drops an index, so that the migrations
run again over an existing schema. They run only against the isolated instance and touch no
data of record.
"""

import logging

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS, apply_migrations
from diucs.adapters.outbound.graph_store.queries import NamedQuery, QueryRegistry

# Derived from the list (TEN-005): a later task adds its migrations in its own area module and no
# number is edited. The unit test test_migration_ids.py pins it to 26 core + the tenant + network.
EXPECTED_MIGRATION_COUNT = len(MIGRATIONS)
EXPECTED_CONSTRAINTS = {"resource_id", "identifier_key", "concept_key"}
EXPECTED_INDEXES = {
    "obs_by_service",
    "task_by_status",
    "svc_active",
    "phone_hash",
    "location_position",
}

# A registry of this file's own (DEC-142): the test statements are not tenant-scoped, so they sit on
# its ratchet and run with no scope bound. They are never registered in the module registry.
_TEST_REGISTRY = QueryRegistry(unconverted=frozenset({"Q-TEST-ECHO", "Q-TEST-WARN"}))
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


async def _reset_bookkeeping(driver: AsyncDriver) -> None:
    async with driver.session() as session:
        await session.run("MATCH (m:Migration) DETACH DELETE m")


@pytest.mark.asyncio(loop_scope="session")
async def test_apply_migrations_applies_every_migration_then_none_on_the_second_call(
    neo4j_driver: AsyncDriver,
) -> None:
    await _reset_bookkeeping(neo4j_driver)

    first = await apply_migrations(neo4j_driver)
    assert len(first) == EXPECTED_MIGRATION_COUNT
    assert first == [migration.id for migration in MIGRATIONS]

    second = await apply_migrations(neo4j_driver)
    assert second == []


@pytest.mark.asyncio(loop_scope="session")
async def test_each_applied_migration_is_recorded_with_an_id_and_a_utc_time(
    neo4j_driver: AsyncDriver,
) -> None:
    await apply_migrations(neo4j_driver)
    async with neo4j_driver.session() as session:
        result = await session.run(
            "MATCH (m:Migration) RETURN m.id AS id, m.appliedAt AS appliedAt ORDER BY m.id"
        )
        records = [record.data() async for record in result]
    assert sorted(r["id"] for r in records) == sorted(m.id for m in MIGRATIONS)
    for record in records:
        assert record["appliedAt"].tzinfo is not None


@pytest.mark.asyncio(loop_scope="session")
async def test_schema_has_the_named_constraints_and_indexes(neo4j_driver: AsyncDriver) -> None:
    await apply_migrations(neo4j_driver)
    async with neo4j_driver.session() as session:
        constraints = {
            r["name"] async for r in await session.run("SHOW CONSTRAINTS YIELD name RETURN name")
        }
        indexes = {
            r["name"] async for r in await session.run("SHOW INDEXES YIELD name RETURN name")
        }
    assert constraints >= EXPECTED_CONSTRAINTS
    assert indexes >= EXPECTED_INDEXES


@pytest.mark.asyncio(loop_scope="session")
async def test_every_migration_statement_runs_twice_in_separate_sessions(
    neo4j_driver: AsyncDriver,
) -> None:
    # A missing IF NOT EXISTS fails the second run against an object the first run created, and a
    # loop that is not idempotent changes something on the second run.
    await apply_migrations(neo4j_driver)
    for migration in MIGRATIONS:
        for statement in migration.statements:
            for _ in range(2):
                async with neo4j_driver.session() as session:
                    await session.run(statement, dict(migration.params))
        for loop in migration.loops:
            for _ in range(2):
                async with neo4j_driver.session() as session:
                    result = await session.run(loop, {**migration.params, "batch": migration.batch})
                    assert [r["changed"] async for r in result] == [0]


@pytest.mark.asyncio(loop_scope="session")
async def test_reapplying_over_an_existing_schema_recreates_a_dropped_index(
    neo4j_driver: AsyncDriver,
) -> None:
    await apply_migrations(neo4j_driver)
    async with neo4j_driver.session() as session:
        await session.run("DROP INDEX obs_by_service IF EXISTS")
    await _reset_bookkeeping(neo4j_driver)

    reapplied = await apply_migrations(neo4j_driver)

    assert reapplied == [migration.id for migration in MIGRATIONS]
    async with neo4j_driver.session() as session:
        indexes = {
            r["name"] async for r in await session.run("SHOW INDEXES YIELD name RETURN name")
        }
    assert "obs_by_service" in indexes


@pytest.mark.asyncio(loop_scope="session")
async def test_a_registered_named_query_runs_in_a_read_transaction(
    neo4j_driver: AsyncDriver,
) -> None:
    async def work(tx: object) -> list[dict[str, object]]:
        return await run_query(tx, _ECHO, registry=_TEST_REGISTRY, x=1)  # type: ignore[arg-type]

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
        return await run_query(tx, _WARN, registry=_TEST_REGISTRY)  # type: ignore[arg-type]

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
        return await run_query(tx, _ECHO, registry=_TEST_REGISTRY, x=1)  # type: ignore[arg-type]

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
