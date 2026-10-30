"""The network read routes over HTTP on a real Neo4j (TEN-059, DEC-548, DEC-132 item 4).

Written, not run, in build wave 5 (the owner's instruction: the whole integration suite runs once,
on the merged tip).

Three members of one network have granted capacity, directory and criteria and had a service
admitted; the projector has run for all three. The app is the real one with the edge's fake tenant
directory (the tenants of the run) and the real registry, units of work and cache. The tests show:
a member reads the board, the directory and the criteria; a tenant that never joined, a network
outside the token's claim, and a member who left are all the same 404; a stale claim does not let a
member who left read; the board names no tenant and no grant; and the list of networks is the
registry's, not the token's.
"""

import os
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from neo4j import AsyncDriver

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.auth import BFF_SECRET_NAME
from diucs.adapters.inbound.fhir_rest.routes_network import NetworkServices
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_network_uow_factory
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.tokens import TEST_BFF_SECRET, issue_test_token
from diucs.application.network_access import NetworkAccess
from diucs.application.use_cases.network_board_projector import NetworkBoardProjector
from diucs.application.use_cases.query_network_board import QueryNetworkBoard
from diucs.application.use_cases.query_network_directory import (
    QueryNetworkCriteria,
    QueryNetworkDirectory,
)
from diucs.domain.codes import Role
from tests.support.edge import EdgeContainer, active_tenants
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
async def app(world: NetworkWorld) -> AsyncIterator[FastAPI]:
    cache = RedisCache.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    clock = FixedClock(NOW + timedelta(minutes=2))
    container = EdgeContainer(
        tenants=active_tenants(*world.ids.members, world.ids.outsider), clock=clock
    )
    built = create_app(container)  # type: ignore[arg-type]
    built.state.secrets = FixedSecretStore({BFF_SECRET_NAME: TEST_BFF_SECRET})
    access = NetworkAccess(world.registry, _Names())  # type: ignore[arg-type]
    factory = neo4j_network_uow_factory(world.driver, read_only=True)
    query = QueryNetworkBoard(factory, access, clock)
    built.state.network_services = NetworkServices(
        access=access,
        projector=NetworkBoardProjector(query, access, cache, clock),
        directory=QueryNetworkDirectory(factory, access, clock),
        criteria=QueryNetworkCriteria(factory, access, clock),
    )
    built.state.cache = cache
    yield built
    await cache.aclose()


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def _bearer(tenant: str, networks: tuple[str, ...], role: Role = Role.ADVISOR) -> dict[str, str]:
    # the app's clock is the network world's (late October 2026), past the default token's expiry
    token = issue_test_token(
        role,
        [],
        "prac-1",
        tenant=tenant,
        networks=networks,
        expires_at=NOW + timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


async def test_a_member_reads_the_board_the_directory_and_the_criteria(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    headers = _bearer(member, (world.ids.network,))
    async with _client(app) as client:
        board = await client.get(f"/network/{world.ids.network}/board", headers=headers)
        directory = await client.get(f"/network/{world.ids.network}/directory", headers=headers)
        criteria = await client.get(f"/network/{world.ids.network}/criteria", headers=headers)
    assert board.status_code == directory.status_code == criteria.status_code == 200
    assert len(board.json()["entries"]) == 3
    assert {e["service_name"] for e in directory.json()["entries"]} == {
        world.service_name(m) for m in world.ids.members
    }
    assert len(criteria.json()["entries"]) == 3
    for text in (board.text, directory.text, criteria.text):
        assert not any(t in text for t in (*world.ids.members, world.ids.owner))
        assert "grant-" not in text


async def test_a_tenant_that_never_joined_and_a_foreign_network_are_the_same_404(
    app: FastAPI, world: NetworkWorld
) -> None:
    async with _client(app) as client:
        outsider = await client.get(
            f"/network/{world.ids.network}/board",
            headers=_bearer(world.ids.outsider, (world.ids.network,)),
        )
        unclaimed = await client.get(
            f"/network/{world.ids.network}/board", headers=_bearer(world.ids.members[0], ())
        )
        unknown = await client.get(
            "/network/net-nowhere/board",
            headers=_bearer(world.ids.members[0], ("net-nowhere",)),
        )
    assert {outsider.status_code, unclaimed.status_code, unknown.status_code} == {404}
    assert outsider.text == unclaimed.text == unknown.text


async def test_a_stale_claim_does_not_let_a_member_who_left_read(
    app: FastAPI, world: NetworkWorld
) -> None:
    leaver = world.ids.members[2]
    headers = _bearer(leaver, (world.ids.network,))
    async with _client(app) as client:
        before = await client.get(f"/network/{world.ids.network}/board", headers=headers)
        await world.leave(leaver)
        after = await client.get(f"/network/{world.ids.network}/board", headers=headers)
        listed = await client.get("/networks", headers=headers)
    assert before.status_code == 200 and after.status_code == 404
    assert listed.json() == {"networks": []}


async def test_the_list_of_networks_is_the_registrys(app: FastAPI, world: NetworkWorld) -> None:
    async with _client(app) as client:
        response = await client.get(
            "/networks", headers=_bearer(world.ids.members[0], ())
        )  # no claim at all
    assert [n["id"] for n in response.json()["networks"]] == [world.ids.network]
