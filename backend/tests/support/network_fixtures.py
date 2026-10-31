"""The fixtures of the two-member network tests over HTTP (TEN-062): the network world, the real
app over it and a client, shared by the four test files so each builds the same thing.

A test module imports `connection`, `world` and `net_app` (pytest finds a fixture by the name it has
in the module), and builds requests with `bearer` and `wall_bearer`. The app is the real one: the
REST edge with the run's tenants as active, the real registry, units of work, Redis cache, the
screens reader, the sample recorder and the week summary. Nothing here asserts anything.
"""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.inbound.fhir_rest.routes_network import NetworkServices
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.unit_of_work import (
    neo4j_network_uow_factory,
    neo4j_uow_factory,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.network_access import NetworkAccess
from diucs.application.tenancy import bind_network
from diucs.application.use_cases.network_board_projector import (
    NETWORK_BOARD_CACHE_KEY,
    NetworkBoardProjector,
)
from diucs.application.use_cases.network_samples import RecordNetworkSample
from diucs.application.use_cases.network_week_summary import GetNetworkWeekSummary
from diucs.application.use_cases.query_network_board import QueryNetworkBoard
from diucs.application.use_cases.query_network_directory import (
    QueryNetworkCriteria,
    QueryNetworkDirectory,
)
from diucs.application.use_cases.wall_board_scope import UowScreens
from diucs.domain.codes import Role
from tests.support.edge import EdgeContainer, active_tenants
from tests.support.network_world import NOW, NetworkWorld, world_ids
from tests.support.tenancy import RunIdentity
from tests.support.uow import ensure_audit_heads

__all__ = [
    "NetApp",
    "bare_world",
    "bearer",
    "client_of",
    "connection",
    "net_app",
    "wall_bearer",
    "world",
]


class _Tenant:
    def __init__(self, display_name: str) -> None:
        self.display_name = display_name


class _Names:
    async def get(self, tenant_id: str) -> _Tenant | None:
        return _Tenant(f"Org {tenant_id.rsplit('-', 1)[-1]}")


@dataclass(frozen=True, slots=True)
class NetApp:
    app: FastAPI
    cache: RedisCache
    clock: FixedClock


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
async def bare_world(
    harness_driver: AsyncDriver,
    connection: Neo4jConnection,
    run_identity: RunIdentity,
    clean_graph: None,
) -> AsyncIterator[NetworkWorld]:
    """The world before the projector has run: the registry and the members' data, and an empty
    network scope."""
    built = await NetworkWorld.build(harness_driver, connection, world_ids(run_identity))
    await ensure_audit_heads(harness_driver, *built.ids.members, built.ids.outsider)
    yield built
    await built.cleanup()


@pytest_asyncio.fixture(loop_scope="session")
async def world(bare_world: NetworkWorld) -> NetworkWorld:
    """The world with the projector run for every member."""
    await bare_world.run_projector()
    return bare_world


@pytest_asyncio.fixture(loop_scope="session")
async def net_app(world: NetworkWorld) -> AsyncIterator[NetApp]:
    cache = RedisCache.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    with bind_network(world.ids.network):
        await cache.delete(NETWORK_BOARD_CACHE_KEY)
    clock = FixedClock(NOW + timedelta(minutes=2))
    container = EdgeContainer(
        tenants=active_tenants(*world.ids.members, world.ids.outsider, world.ids.owner),
        clock=clock,
        uow_factory=neo4j_uow_factory(world.driver),
    )
    built = create_app(container)  # type: ignore[arg-type]
    built.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    access = NetworkAccess(
        world.registry,
        _Names(),  # type: ignore[arg-type]
        UowScreens(container.uow_factory),
    )
    read_only = neo4j_network_uow_factory(world.driver, read_only=True)
    query = QueryNetworkBoard(read_only, access, clock)
    built.state.network_services = NetworkServices(
        access=access,
        projector=NetworkBoardProjector(
            query,
            access,
            cache,
            clock,
            RecordNetworkSample(neo4j_network_uow_factory(world.driver)),
        ),
        directory=QueryNetworkDirectory(read_only, access, clock),
        criteria=QueryNetworkCriteria(read_only, access, clock),
        weeks=GetNetworkWeekSummary(read_only, access),
    )
    built.state.cache = cache
    yield NetApp(built, cache, clock)
    with bind_network(world.ids.network):
        await cache.delete(NETWORK_BOARD_CACHE_KEY)
    await cache.aclose()


def client_of(net: NetApp) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=net.app, raise_app_exceptions=False), base_url="http://test"
    )


def bearer(
    tenant: str, role: Role = Role.LEAD, networks: tuple[str, ...] = (), sub: str = "prac-1"
) -> dict[str, str]:
    token = issue_test_token(
        role, [], sub, tenant=tenant, networks=networks, expires_at=NOW + timedelta(hours=1)
    )
    return {"Authorization": f"Bearer {token}"}


def wall_bearer(tenant: str, device_id: str = "screen-1") -> dict[str, str]:
    return bearer(tenant, Role.WALL, sub=device_id)
