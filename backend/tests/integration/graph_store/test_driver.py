"""Integration tests for the Neo4j adapter base (G01): driver, named queries, migrations.

They run against a real Neo4j. NEO4J_URI selects the instance; point it at an isolated stack
(never the shared diucs-local stack) and start that stack with `up -d --wait neo4j`. The F10
harness will own these fixtures later; until then this module holds its own driver (DEC-012:
one AsyncDriver per module, closed at the end).

The migration test removes only (:Migration) bookkeeping nodes first, so it can be re-run on the
same database. It does not touch other data.
"""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.driver import create_driver, run_query
from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS, apply_migrations
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "diucs-test-password")

EXPECTED_MIGRATION_COUNT = 8
EXPECTED_CONSTRAINTS = {"resource_id", "identifier_key", "concept_key"}
EXPECTED_INDEXES = {
    "obs_by_service",
    "task_by_status",
    "svc_active",
    "phone_hash",
    "location_position",
}

REGISTRY.register(NamedQuery(id="Q-TEST-ECHO", cypher="RETURN $x AS x", mode="read"))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def neo4j_driver() -> AsyncIterator[AsyncDriver]:
    driver = create_driver(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    try:
        yield driver
    finally:
        await driver.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_apply_migrations_applies_every_migration_then_none_on_the_second_call(
    neo4j_driver: AsyncDriver,
) -> None:
    async with neo4j_driver.session() as session:
        await session.run("MATCH (m:Migration) DETACH DELETE m")

    first = await apply_migrations(neo4j_driver)
    assert len(first) == EXPECTED_MIGRATION_COUNT
    assert first == [migration_id for migration_id, _ in MIGRATIONS]

    second = await apply_migrations(neo4j_driver)
    assert second == []


@pytest.mark.asyncio(loop_scope="module")
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


@pytest.mark.asyncio(loop_scope="module")
async def test_schema_has_the_named_constraints_and_indexes(neo4j_driver: AsyncDriver) -> None:
    await apply_migrations(neo4j_driver)
    async with neo4j_driver.session() as session:
        constraints = {
            r["name"] async for r in await session.run("SHOW CONSTRAINTS YIELD name RETURN name")
        }
        indexes = {r["name"] async for r in await session.run("SHOW INDEXES YIELD name RETURN name")}
    assert EXPECTED_CONSTRAINTS <= constraints
    assert EXPECTED_INDEXES <= indexes


@pytest.mark.asyncio(loop_scope="module")
async def test_a_registered_named_query_runs_in_a_read_transaction(
    neo4j_driver: AsyncDriver,
) -> None:
    async def work(tx: object) -> list[dict[str, object]]:
        return await run_query(tx, "Q-TEST-ECHO", x=1)  # type: ignore[arg-type]

    async with neo4j_driver.session() as session:
        rows = await session.execute_read(work)
    assert rows == [{"x": 1}]
