"""The network board projector on a real Neo4j and Redis (TEN-058, DEC-547, DEC-132 item 4).

Written, not run, in build wave 5 (the owner's instruction: the whole integration suite runs once,
on the merged tip).

Three members of one network have granted capacity and directory and had a service admitted; the
projector has run for all three. The tests show: a rebuild caches the board under the network's own
key and announces it on the network's own channel, and neither is visible in a tenant's scope or in
another network's; a read after a rebuild is served from the cache; a member who left is refused
although the board is cached; and a grant that ended changes the board on the next rebuild.
"""

import os
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_network_uow_factory
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.actor import Actor
from diucs.application.network_access import NetworkAccess
from diucs.application.tenancy import bind_network, bind_tenant
from diucs.application.use_cases.network_board_projector import (
    NETWORK_BOARD_CACHE_KEY,
    NetworkBoardProjector,
)
from diucs.application.use_cases.query_network_board import QueryNetworkBoard
from diucs.domain.codes import Role
from diucs.domain.errors import NotFound
from diucs.domain.model.network import GrantScope
from tests.support.network_world import NOW, NetworkWorld, world_ids
from tests.support.tenancy import RunIdentity

pytestmark = pytest.mark.asyncio(loop_scope="session")


class _Tenant:
    def __init__(self, display_name: str) -> None:
        self.display_name = display_name


class _Names:
    async def get(self, tenant_id: str) -> _Tenant | None:
        return _Tenant(f"Org {tenant_id.rsplit('-', 1)[-1]}")


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
    harness_driver: AsyncDriver,
    connection: Neo4jConnection,
    run_identity: RunIdentity,
    clean_graph: None,
) -> AsyncIterator[NetworkWorld]:
    built = await NetworkWorld.build(harness_driver, connection, world_ids(run_identity))
    await built.run_projector()
    yield built
    await built.cleanup()


@pytest_asyncio.fixture(loop_scope="session")
async def cache(run_identity: RunIdentity) -> AsyncIterator[RedisCache]:
    """The cache, with no cached board of the run's network before or after a test: the board is
    cached for a minute, and the next test builds a different world under the same network id."""
    store = RedisCache.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    try:
        await _forget_boards(store, run_identity)
        yield store
    finally:
        await _forget_boards(store, run_identity)
        await store.aclose()


async def _forget_boards(store: RedisCache, identity: RunIdentity) -> None:
    for network in (identity.network_id, f"{identity.network_id}-b"):
        with bind_network(network):
            await store.delete(NETWORK_BOARD_CACHE_KEY)


def _staff(tenant: str) -> Actor:
    return Actor(Role.ADVISOR, "prac-1", None, "web", frozenset(), tenant)


def _projector(world: NetworkWorld, cache: RedisCache) -> NetworkBoardProjector:
    clock = FixedClock(NOW + timedelta(minutes=2))
    access = NetworkAccess(world.registry, _Names())  # type: ignore[arg-type]
    query = QueryNetworkBoard(
        neo4j_network_uow_factory(world.driver, read_only=True), access, clock
    )
    return NetworkBoardProjector(query, access, cache, clock)


async def test_a_rebuild_caches_the_board_in_the_networks_scope_only(
    world: NetworkWorld, cache: RedisCache
) -> None:
    projector = _projector(world, cache)
    assert await projector.handle("MemberAdded", {"network_id": world.ids.network}) is True
    with bind_network(world.ids.network):
        assert await cache.get(NETWORK_BOARD_CACHE_KEY) is not None
    with bind_network(world.ids.other_network):
        assert await cache.get(NETWORK_BOARD_CACHE_KEY) is None
    for member in world.ids.members:
        with bind_tenant(member):
            assert await cache.get(NETWORK_BOARD_CACHE_KEY) is None


async def test_a_read_after_a_rebuild_is_served_from_the_cache(
    world: NetworkWorld, cache: RedisCache
) -> None:
    projector = _projector(world, cache)
    await projector.handle("MemberAdded", {"network_id": world.ids.network})
    member = world.ids.members[0]
    first = await projector.get_board(_staff(member), world.ids.network)
    second = await projector.get_board(_staff(member), world.ids.network)
    assert first == second and len(first.board.entries) == 3


async def test_a_member_who_left_is_refused_although_the_board_is_cached(
    world: NetworkWorld, cache: RedisCache
) -> None:
    projector = _projector(world, cache)
    await projector.handle("MemberAdded", {"network_id": world.ids.network})
    leaver = world.ids.members[2]
    await world.leave(leaver)
    with pytest.raises(NotFound):
        await projector.get_board(_staff(leaver), world.ids.network)


async def test_a_grant_that_ended_changes_the_board_on_the_next_rebuild(
    world: NetworkWorld, cache: RedisCache
) -> None:
    projector = _projector(world, cache)
    member, other = world.ids.members[0], world.ids.members[1]
    await world.end_grant(other, GrantScope.CAPACITY)
    await projector.handle("GrantEnded", {"network_id": world.ids.network})
    board = await projector.get_board(_staff(member), world.ids.network)
    assert world.service_name(other) not in {e.service_name for e in board.board.entries}
