"""The whole-database invariants after the network projector ran (TEN-060, DEC-544, TEN-031).

The check behind the start-up refusal reads every node of the database: a node with no `tenantId`
(outside the registry labels) and a relationship that joins two scopes. On the Neo4j that runs
share it would count other runs' nodes, so this module runs on a private container (`own_neo4j`,
marker `schema`, TEN-034), builds the three-scope world on it, runs the projector for every member,
ends one member's membership and asserts the whole database is sound at each step. The scope-wise
invariants (which a shared database can answer) are in `test_network_scope_isolation.py`.
"""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.network_world import NetworkWorld, world_ids
from tests.support.tenancy import RunIdentity

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.schema]


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def harness_driver(own_neo4j: tuple[ThrowawayNeo4j, AsyncDriver]) -> AsyncDriver:
    """This module's database is its own container, whatever the session's mode."""
    return own_neo4j[1]


@pytest_asyncio.fixture(loop_scope="session")
async def connection(harness_driver: AsyncDriver) -> AsyncIterator[Neo4jConnection]:
    conn = Neo4jConnection(
        os.environ["NEO4J_URI"], os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]
    )
    await conn.open()
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture(loop_scope="session")
async def world(
    harness_driver: AsyncDriver, connection: Neo4jConnection, run_identity: RunIdentity
) -> AsyncIterator[NetworkWorld]:
    built = await NetworkWorld.build(harness_driver, connection, world_ids(run_identity))
    yield built
    await built.cleanup()


async def test_no_node_lacks_a_scope_and_no_relationship_joins_two_after_the_projector_ran(
    world: NetworkWorld,
) -> None:
    before = await world.global_invariants()
    assert before.unstamped == () and before.cross_scope == ()
    await world.run_projector()
    report = await world.global_invariants()
    assert report.ok
    assert report.unstamped == () and report.cross_scope == ()
    assert (report.unstamped_total, report.cross_scope_total) == (0, 0)


async def test_the_database_stays_sound_when_a_member_leaves(world: NetworkWorld) -> None:
    await world.run_projector()
    assert await world.leave(world.ids.members[2]) > 0
    report = await world.global_invariants()
    assert report.ok
    assert (report.unstamped_total, report.cross_scope_total) == (0, 0)
