"""Which board a wall screen shows, over HTTP on a real Neo4j and Redis (TEN-067, DEC-132 item 5).

Three members of one network have granted capacity, directory and criteria (the network world). A
screen of the first member is paired to its own board. The tests show:

- a lead (or a tenant administrator) lists the screens and the networks to choose, and changes one
  screen's board with If-Match and an Idempotency-Key; a stale version is 412, none is 428, a repeat
  with the same key changes nothing twice;
- a network the tenant is not an active member of, an unknown one and an unknown or revoked screen
  are the same 404, and nothing is stored;
- a screen reads its own setting, and its network board only while its record names a network its
  tenant belongs to: a screen on its own board asks and gets the 404 of every refusal, and a screen
  whose tenant left is told to show its own board, with a flag, while the network board is closed;
- a wall token cannot read a network by asking (`/network/{id}/board` stays closed to it), and the
  token holds nothing of the setting;
- the role matrix of every route (13 roles), and a second tenant's screen with the same id is
  never found.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
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
from diucs.application.actor import Actor
from diucs.application.network_access import NetworkAccess
from diucs.application.tenancy import bind_network, bind_tenant
from diucs.application.use_cases.network_board_projector import (
    NETWORK_BOARD_CACHE_KEY,
    NetworkBoardProjector,
)
from diucs.application.use_cases.query_network_board import QueryNetworkBoard
from diucs.application.use_cases.query_network_directory import (
    QueryNetworkCriteria,
    QueryNetworkDirectory,
)
from diucs.application.use_cases.wall_board_scope import (
    ScreenSettingChanged,
    SetBoardScopeCommand,
    SetScreenBoardScope,
    UowScreens,
)
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from tests.support.edge import EdgeContainer, active_tenants
from tests.support.neo4j import node_props
from tests.support.network_world import NOW, NetworkWorld, world_ids
from tests.support.tenancy import RunIdentity
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

SCREEN = "screen-1"
HASH = "c" * 64
JSON = {"Content-Type": "application/json"}
NOT_FOUND = "The requested resource was not found."


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
    await ensure_audit_heads(harness_driver, *built.ids.members, built.ids.outsider)
    yield built
    await built.cleanup()


@pytest_asyncio.fixture(loop_scope="session")
async def app(world: NetworkWorld) -> AsyncIterator[FastAPI]:
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
    with bind_network(world.ids.network):
        await cache.delete(NETWORK_BOARD_CACHE_KEY)
    await cache.aclose()


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


def _token(tenant: str, role: Role, sub: str = "prac-1") -> str:
    return issue_test_token(role, [], sub, tenant=tenant, expires_at=NOW + timedelta(hours=1))


def _staff(tenant: str, role: Role = Role.LEAD) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(tenant, role)}"}


def _wall(tenant: str, device: str = SCREEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(tenant, Role.WALL, device)}"}


def _put_headers(tenant: str, version: int, role: Role = Role.LEAD) -> dict[str, str]:
    return {
        **_staff(tenant, role),
        "If-Match": f'W/"{version}"',
        "Idempotency-Key": f"key-{uuid.uuid4().hex}",
        **JSON,
    }


async def _seed_screen(
    world: NetworkWorld,
    tenant: str,
    device_id: str = SCREEN,
    *,
    status: DeviceStatus = DeviceStatus.ACTIVE,
    name: str = "Ward 4 corridor",
) -> None:
    device = Device(
        id=device_id,
        status=status,
        name=name,
        location="Level 2",
        device_type=DeviceType.WALL_DISPLAY,
        token_hash=HASH if status is DeviceStatus.ACTIVE else None,
    )
    with bind_tenant(tenant):
        async with neo4j_uow_factory(world.driver)() as uow:
            await uow.devices.save(device)
            await uow.commit()


async def _stored(world: NetworkWorld, tenant: str, device_id: str = SCREEN) -> dict[str, Any]:
    return await node_props(world.driver, "Device", scope=tenant, id=device_id)


async def _set(
    client: AsyncClient,
    tenant: str,
    board: str,
    network: str | None,
    version: int = 1,
    device: str = SCREEN,
    role: Role = Role.LEAD,
) -> Response:
    body: dict[str, Any] = {"boardScope": board}
    if network is not None:
        body["networkId"] = network
    return await client.put(
        f"/screens/{device}/board-scope",
        json=body,
        headers=_put_headers(tenant, version, role),
    )


# ------------------------------------------------------------------ the administrator


async def test_a_lead_lists_the_screens_and_the_networks_to_choose(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        response = await client.get("/screens", headers=_staff(member))
    assert response.status_code == 200
    body = response.json()
    assert body["screens"] == [
        {
            "deviceId": SCREEN,
            "name": "Ward 4 corridor",
            "location": "Level 2",
            "status": "active",
            "boardScope": "tenant",
            "networkId": None,
            "networkName": None,
            "networkAvailable": True,
            "scopeVersion": 1,
            # The screen's life (W9I): a screen nobody has read through yet is offline.
            "state": "offline",
            "pairedAt": None,
            "lastSeenAt": None,
            "revokedAt": None,
        }
    ]
    assert body["scope"] == "tenant"
    assert body["networks"] == [{"id": world.ids.network, "name": "Sample network"}]
    assert response.headers["cache-control"] == "no-store"
    assert not any(t in response.text for t in (*world.ids.members, world.ids.owner))


async def test_the_list_holds_only_the_callers_screens(app: FastAPI, world: NetworkWorld) -> None:
    first, second = world.ids.members[:2]
    await _seed_screen(world, first, name="First tenant wall")
    await _seed_screen(world, second, name="Second tenant wall")
    async with _client(app) as client:
        one = await client.get("/screens", headers=_staff(first))
        two = await client.get("/screens", headers=_staff(second))
    assert [s["name"] for s in one.json()["screens"]] == ["First tenant wall"]
    assert [s["name"] for s in two.json()["screens"]] == ["Second tenant wall"]


async def test_an_outsider_has_no_networks_to_choose(app: FastAPI, world: NetworkWorld) -> None:
    await _seed_screen(world, world.ids.outsider)
    async with _client(app) as client:
        response = await client.get("/screens", headers=_staff(world.ids.outsider))
    assert response.status_code == 200
    assert response.json()["networks"] == []


async def test_a_lead_sets_a_network_board_with_the_version_it_read(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        response = await _set(client, member, "network", world.ids.network)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "deviceId": SCREEN,
        "name": "Ward 4 corridor",
        "location": "Level 2",
        "status": "active",
        "boardScope": "network",
        "networkId": world.ids.network,
        "networkName": "Sample network",
        "networkAvailable": True,
        "scopeVersion": 2,
    }
    assert response.headers["etag"] == 'W/"2"'
    stored = await _stored(world, member)
    assert (stored["boardScope"], stored["networkId"], stored["boardScopeVersion"]) == (
        "network",
        world.ids.network,
        2,
    )


async def test_a_tenant_administrator_may_set_it_too(app: FastAPI, world: NetworkWorld) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        response = await _set(client, member, "network", world.ids.network, role=Role.TENANT_ADMIN)
    assert response.status_code == 200


async def test_the_change_is_audited_in_the_tenants_chain_without_a_person(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        await _set(client, member, "network", world.ids.network)
    async with world.driver.session() as session:
        result = await session.run(
            "MATCH (e:AuditEvent {tenantId: $tenant}) WHERE e.useCase = 'SetScreenBoardScope' "
            "RETURN e.action AS action, count(e) AS n",
            tenant=member,
        )
        rows = [dict(r) async for r in result]
    assert rows == [{"action": "wall-screen-board-set", "n": 1}]


async def test_setting_the_board_back_to_the_tenant_clears_the_network(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        await _set(client, member, "network", world.ids.network)
        back = await _set(client, member, "tenant", None, version=2)
    assert back.status_code == 200
    assert back.json()["boardScope"] == "tenant" and back.json()["networkId"] is None
    assert back.json()["scopeVersion"] == 3
    stored = await _stored(world, member)
    assert stored.get("networkId") is None


async def test_setting_what_is_set_changes_nothing(app: FastAPI, world: NetworkWorld) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        await _set(client, member, "network", world.ids.network)
        again = await _set(client, member, "network", world.ids.network, version=2)
    assert again.status_code == 200 and again.json()["scopeVersion"] == 2


async def test_a_stale_version_is_412_and_none_is_428_and_nothing_changes(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        stale = await _set(client, member, "network", world.ids.network, version=7)
        headers = _put_headers(member, 1)
        del headers["If-Match"]
        missing = await client.put(
            f"/screens/{SCREEN}/board-scope",
            json={"boardScope": "network", "networkId": world.ids.network},
            headers=headers,
        )
    assert (stale.status_code, missing.status_code) == (412, 428)
    assert (await _stored(world, member))["boardScope"] == "tenant"


async def test_a_put_without_an_idempotency_key_is_refused(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    headers = _put_headers(member, 1)
    del headers["Idempotency-Key"]
    async with _client(app) as client:
        response = await client.put(
            f"/screens/{SCREEN}/board-scope",
            json={"boardScope": "network", "networkId": world.ids.network},
            headers=headers,
        )
    assert response.status_code == 400
    assert (await _stored(world, member))["boardScope"] == "tenant"


async def test_the_same_key_and_body_replays_and_changes_nothing_twice(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    headers = _put_headers(member, 1)
    body = {"boardScope": "network", "networkId": world.ids.network}
    async with _client(app) as client:
        first = await client.put(f"/screens/{SCREEN}/board-scope", json=body, headers=headers)
        second = await client.put(f"/screens/{SCREEN}/board-scope", json=body, headers=headers)
    assert first.status_code == second.status_code == 200
    assert second.headers.get("idempotent-replay") == "true"
    assert second.json() == first.json()
    assert (await _stored(world, member))["boardScopeVersion"] == 2


async def test_a_network_the_tenant_does_not_belong_to_is_the_same_404_as_an_unknown_one(
    app: FastAPI, world: NetworkWorld
) -> None:
    outsider = world.ids.outsider
    await _seed_screen(world, outsider)
    async with _client(app) as client:
        joined_elsewhere = await _set(client, outsider, "network", world.ids.network)
        unknown = await _set(client, outsider, "network", "net-nowhere")
    assert joined_elsewhere.status_code == unknown.status_code == 404
    assert joined_elsewhere.text == unknown.text
    assert world.ids.network not in joined_elsewhere.text
    assert (await _stored(world, outsider))["boardScope"] == "tenant"


async def test_a_member_who_left_cannot_choose_the_network(
    app: FastAPI, world: NetworkWorld
) -> None:
    leaver = world.ids.members[2]
    await _seed_screen(world, leaver)
    await world.leave(leaver)
    async with _client(app) as client:
        response = await _set(client, leaver, "network", world.ids.network)
    assert response.status_code == 404
    assert (await _stored(world, leaver))["boardScope"] == "tenant"


@pytest.mark.parametrize(
    "body",
    [
        {"boardScope": "network"},
        {"boardScope": "tenant", "networkId": "net-x"},
        {"boardScope": "everyone"},
        {"boardScope": "network", "networkId": "NOT A NETWORK"},
        {"boardScope": "network", "networkId": "tenant-1"},
        {"boardScope": "tenant", "tenant": "tenant-b"},
        {},
    ],
)
async def test_a_body_that_is_not_a_setting_is_refused_and_stores_nothing(
    app: FastAPI, world: NetworkWorld, body: dict[str, Any]
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        response = await client.put(
            f"/screens/{SCREEN}/board-scope", json=body, headers=_put_headers(member, 1)
        )
    assert response.status_code == 400
    stored = await _stored(world, member)
    assert (stored["boardScope"], stored["boardScopeVersion"]) == ("tenant", 1)


async def test_an_unknown_and_a_revoked_screen_are_the_same_404(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member, "screen-revoked", status=DeviceStatus.REVOKED)
    async with _client(app) as client:
        unknown = await _set(client, member, "network", world.ids.network, device="screen-9")
        revoked = await _set(client, member, "network", world.ids.network, device="screen-revoked")
    assert unknown.status_code == revoked.status_code == 404
    assert unknown.text == revoked.text


async def test_a_screen_of_another_tenant_with_the_same_id_is_never_found(
    app: FastAPI, world: NetworkWorld
) -> None:
    first, second = world.ids.members[:2]
    await _seed_screen(world, first, name="First tenant wall")
    async with _client(app) as client:
        foreign = await _set(client, second, "network", world.ids.network)
    assert foreign.status_code == 404
    assert (await _stored(world, first))["boardScope"] == "tenant"


async def test_two_tenants_with_one_screen_id_change_independently(
    app: FastAPI, world: NetworkWorld
) -> None:
    first, second = world.ids.members[:2]
    await _seed_screen(world, first)
    await _seed_screen(world, second)
    async with _client(app) as client:
        await _set(client, first, "network", world.ids.network)
    assert (await _stored(world, first))["boardScope"] == "network"
    assert (await _stored(world, second))["boardScope"] == "tenant"
    assert (await _stored(world, second))["boardScopeVersion"] == 1


async def test_the_durable_replay_answers_a_repeat_after_the_cache_has_forgotten_it(
    world: NetworkWorld,
) -> None:
    """The route's cache is only the fast guard: the use case's own record in the tenant's
    idempotency store answers a repeat of the same command, and refuses the key for another one."""
    member = world.ids.members[0]
    await _seed_screen(world, member)
    clock = FixedClock(NOW + timedelta(minutes=2))
    case = SetScreenBoardScope(
        neo4j_uow_factory(world.driver),
        NetworkAccess(world.registry, _Names(), None),  # type: ignore[arg-type]
        clock,
    )

    def command(board: BoardScope, network: str | None, key: str = "key-1") -> SetBoardScopeCommand:
        return SetBoardScopeCommand(
            actor=Actor(Role.LEAD, "prac-1", None, "api", frozenset(), member),
            device_id=SCREEN,
            board_scope=board,
            network_id=network,
            expected_version=1,
            idempotency_key=key,
        )

    with bind_tenant(member):
        first = await case.execute(command(BoardScope.NETWORK, world.ids.network))
        again = await case.execute(command(BoardScope.NETWORK, world.ids.network))
        with pytest.raises(Conflict):
            await case.execute(command(BoardScope.TENANT, None))
        stale = command(BoardScope.NETWORK, world.ids.network, "key-2")
        with pytest.raises(ScreenSettingChanged):
            await case.execute(stale)
    assert again == first and first.scope_version == 2
    assert (await _stored(world, member))["boardScopeVersion"] == 2


# ------------------------------------------------------------------ the screen


async def test_a_screen_on_its_own_board_reads_that_and_has_no_network_board(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        scope = await client.get("/screens/me/board-scope", headers=_wall(member))
        board = await client.get("/screens/me/network-board", headers=_wall(member))
    assert scope.json() == {"boardScope": "tenant", "fallback": False, "scopeVersion": 1}
    assert board.status_code == 404 and NOT_FOUND in board.text


async def test_a_screen_set_to_a_network_reads_its_name_and_its_board(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        await _set(client, member, "network", world.ids.network)
        scope = await client.get("/screens/me/board-scope", headers=_wall(member))
        board = await client.get("/screens/me/network-board", headers=_wall(member))
    assert scope.json() == {
        "boardScope": "network",
        "networkName": "Sample network",
        "fallback": False,
        "scopeVersion": 2,
    }
    assert board.status_code == 200
    assert len(board.json()["entries"]) == 3
    assert board.headers["cache-control"] == "no-store"
    for text in (scope.text, board.text):
        assert not any(t in text for t in (*world.ids.members, world.ids.owner))
        assert "grant-" not in text and world.ids.network not in text


async def test_the_screen_follows_the_setting_back_to_its_own_board(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        await _set(client, member, "network", world.ids.network)
        assert (
            await client.get("/screens/me/network-board", headers=_wall(member))
        ).status_code == 200
        await _set(client, member, "tenant", None, version=2)
        board = await client.get("/screens/me/network-board", headers=_wall(member))
        scope = await client.get("/screens/me/board-scope", headers=_wall(member))
    assert board.status_code == 404
    assert scope.json() == {"boardScope": "tenant", "fallback": False, "scopeVersion": 3}


async def test_a_screen_whose_tenant_left_falls_back_to_its_own_board_with_the_flag(
    app: FastAPI, world: NetworkWorld
) -> None:
    leaver = world.ids.members[2]
    await _seed_screen(world, leaver)
    async with _client(app) as client:
        await _set(client, leaver, "network", world.ids.network)
        assert (
            await client.get("/screens/me/network-board", headers=_wall(leaver))
        ).status_code == 200
        await world.leave(leaver)
        board = await client.get("/screens/me/network-board", headers=_wall(leaver))
        scope = await client.get("/screens/me/board-scope", headers=_wall(leaver))
    assert board.status_code == 404
    assert scope.json() == {
        "boardScope": "tenant",
        "fallback": True,
        "fallbackReason": "network-unavailable",
        "scopeVersion": 2,
    }
    assert world.ids.network not in scope.text


async def test_the_wall_token_cannot_read_a_network_by_asking(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        await _set(client, member, "network", world.ids.network)
        paths = [
            f"/network/{world.ids.network}/board",
            f"/network/{world.ids.network}/directory",
            f"/network/{world.ids.network}/criteria",
            f"/network/{world.ids.network}/events",
            "/networks",
        ]
        answers = [await client.get(p, headers=_wall(member)) for p in paths]
    assert {a.status_code for a in answers} == {404}


async def test_a_revoked_screen_reads_nothing_even_with_a_valid_token(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        await _set(client, member, "network", world.ids.network)
        async with world.driver.session() as session:
            await session.run(
                "MATCH (d:Device {id: $id, tenantId: $tenant}) SET d.status = 'revoked'",
                id=SCREEN,
                tenant=member,
            )
        scope = await client.get("/screens/me/board-scope", headers=_wall(member))
        board = await client.get("/screens/me/network-board", headers=_wall(member))
    # The edge refuses it with the 401 of a lapsed token (W9I): the wall's session ends.
    assert scope.status_code == board.status_code == 401


async def test_a_screen_of_another_tenant_with_the_same_id_reads_its_own_setting_only(
    app: FastAPI, world: NetworkWorld
) -> None:
    first, second = world.ids.members[:2]
    await _seed_screen(world, first)
    await _seed_screen(world, second)
    async with _client(app) as client:
        await _set(client, first, "network", world.ids.network)
        first_board = await client.get("/screens/me/network-board", headers=_wall(first))
        second_board = await client.get("/screens/me/network-board", headers=_wall(second))
    assert first_board.status_code == 200
    assert second_board.status_code == 404


async def test_a_token_for_a_screen_that_does_not_exist_reads_nothing(
    app: FastAPI, world: NetworkWorld
) -> None:
    async with _client(app) as client:
        scope = await client.get(
            "/screens/me/board-scope", headers=_wall(world.ids.members[0], "screen-9")
        )
    assert scope.status_code == 401


# ------------------------------------------------------------------ the role matrix

ALL_ROLES = tuple(role for role in Role if role is not Role.PLATFORM_OPERATOR)
ADMIN_ROLES = (Role.LEAD, Role.TENANT_ADMIN)


@pytest.mark.parametrize("role", ALL_ROLES)
async def test_role_matrix_of_the_administration_routes(
    app: FastAPI, world: NetworkWorld, role: Role
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        listed = await client.get("/screens", headers=_staff(member, role))
        changed = await _set(client, member, "network", world.ids.network, role=role)
    expected = 200 if role in ADMIN_ROLES else 404
    assert (listed.status_code, changed.status_code) == (expected, expected)
    stored = await _stored(world, member)
    assert stored["boardScope"] == ("network" if role in ADMIN_ROLES else "tenant")


@pytest.mark.parametrize("role", ALL_ROLES)
async def test_role_matrix_of_the_screens_own_routes(
    app: FastAPI, world: NetworkWorld, role: Role
) -> None:
    member = world.ids.members[0]
    await _seed_screen(world, member)
    async with _client(app) as client:
        await _set(client, member, "network", world.ids.network)
        token = {"Authorization": f"Bearer {_token(member, role, SCREEN)}"}
        scope = await client.get("/screens/me/board-scope", headers=token)
        board = await client.get("/screens/me/network-board", headers=token)
    expected = 200 if role is Role.WALL else 404
    assert (scope.status_code, board.status_code) == (expected, expected)


async def test_the_operator_token_and_no_token_are_refused_at_the_edge(
    app: FastAPI, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    operator = {"Authorization": f"Bearer {_token(member, Role.PLATFORM_OPERATOR)}"}
    async with _client(app) as client:
        for path in ("/screens", "/screens/me/board-scope", "/screens/me/network-board"):
            assert (await client.get(path, headers=operator)).status_code == 401
            assert (await client.get(path)).status_code == 401
