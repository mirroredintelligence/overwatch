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
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery

EXPECTED_MIGRATION_COUNT = 10
EXPECTED_CONSTRAINTS = {"resource_id", "identifier_key", "concept_key"}
EXPECTED_INDEXES = {
    "obs_by_service",
    "task_by_status",
    "svc_active",
    "phone_hash",
    "location_position",
}

REGISTRY.register(NamedQuery(id="Q-TEST-ECHO", cypher="RETURN $x AS x", mode="read"))
# The label does not exist, so the server sends a warning; the driver used to log the query text.
REGISTRY.register(
    NamedQuery(
        id="Q-TEST-WARN",
        cypher="MATCH (zzmarkerlabel:NoSuchLabelForG01) RETURN zzmarkerlabel",
        mode="read",
    )
)


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
    assert first == [migration_id for migration_id, _ in MIGRATIONS]

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
    assert sorted(r["id"] for r in records) == sorted(mid for mid, _ in MIGRATIONS)
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
    # A missing IF NOT EXISTS fails the second run against an object the first run created.
    await apply_migrations(neo4j_driver)
    for _, statement in MIGRATIONS:
        for _ in range(2):
            async with neo4j_driver.session() as session:
                await session.run(statement)


@pytest.mark.asyncio(loop_scope="session")
async def test_reapplying_over_an_existing_schema_recreates_a_dropped_index(
    neo4j_driver: AsyncDriver,
) -> None:
    await apply_migrations(neo4j_driver)
    async with neo4j_driver.session() as session:
        await session.run("DROP INDEX obs_by_service IF EXISTS")
    await _reset_bookkeeping(neo4j_driver)

    reapplied = await apply_migrations(neo4j_driver)

    assert reapplied == [migration_id for migration_id, _ in MIGRATIONS]
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
        return await run_query(tx, "Q-TEST-ECHO", x=1)  # type: ignore[arg-type]

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
        return await run_query(tx, "Q-TEST-WARN")  # type: ignore[arg-type]

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
        return await run_query(tx, "Q-TEST-ECHO", x=1)  # type: ignore[arg-type]

    async with neo4j_driver.session() as session:
        await session.execute_read(work)
    assert "RETURN $x AS x" not in caplog.text
    assert "RETURN" not in caplog.text
