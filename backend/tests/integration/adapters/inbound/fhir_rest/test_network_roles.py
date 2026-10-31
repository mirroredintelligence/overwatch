"""The roles of every network route, the wall screen's device checks, and the owner's lack of any
read of a member's private data (TEN-062, DEC-132 items 2 and 5, DEC-546 item 1, DEC-548).

The routes are the table of `tests/support/network_routes.py`, which the completeness test holds
equal to what the app serves. For every route and every role (13 roles; the operator's token is for
the operator door and is refused at the edge) the answer is the route's own: 200 for its roles, the
one 404 for any other, and nothing is stored. The three wall checks: a screen set to its own board,
revoked, or of another tenant reads nothing, and a wall cannot ask for a network by its id. The
network owner is a tenant like the others: it reads the network board and nothing of a member's
tenant, whichever id it asks for.
"""

import uuid
from typing import Any

import pytest

from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_uow_factory
from diucs.application.tenancy import bind_tenant
from diucs.domain.codes import Role
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from tests.support.network_fixtures import (
    NetApp,
    bearer,
    client_of,
    wall_bearer,
)
from tests.support.network_routes import ROUTES, NetworkRoute, discovered, url
from tests.support.network_world import NetworkWorld

pytestmark = pytest.mark.asyncio(loop_scope="session")

ALL_ROLES = tuple(role for role in Role if role is not Role.PLATFORM_OPERATOR)
WEEK = {"weekStart": "2026-10-26"}
SCREEN = "screen-1"


async def _screen(
    world: NetworkWorld,
    tenant: str,
    *,
    network: str | None,
    status: DeviceStatus = DeviceStatus.ACTIVE,
    device_id: str = SCREEN,
) -> None:
    device = Device(
        id=device_id,
        status=status,
        name="Ward 4 corridor",
        location=None,
        device_type=DeviceType.WALL_DISPLAY,
        token_hash="d" * 64 if status is DeviceStatus.ACTIVE else None,
        board_scope=BoardScope.NETWORK if network else BoardScope.TENANT,
        network_id=network,
    )
    with bind_tenant(tenant):
        async with neo4j_uow_factory(world.driver)() as uow:
            await uow.devices.save(device)
            await uow.commit()


def _params(route: NetworkRoute) -> dict[str, str]:
    return WEEK if route.needs_week else {}


async def test_every_network_route_the_app_serves_is_in_the_table(net_app: NetApp) -> None:
    assert discovered(net_app.app) == {(r.method, r.template) for r in ROUTES}


async def test_every_route_answers_each_role_with_its_own_status_and_nothing_else(
    net_app: NetApp, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    network = world.ids.network
    await _screen(world, member, network=network)
    wrong: list[str] = []
    refusals: dict[str, set[str]] = {}
    async with client_of(net_app) as client:
        for route in ROUTES:
            for role in ALL_ROLES:
                if role in route.roles and route.streams:
                    continue  # a stream does not end in a test client: see test_network_stream
                headers = (
                    wall_bearer(member) if role is Role.WALL else bearer(member, role, (network,))
                )
                response = await client.get(
                    url(route, network), params=_params(route), headers=headers
                )
                expected = 200 if role in route.roles else 404
                if response.status_code != expected:
                    wrong.append(f"{route.template} {role.value}: {response.status_code}")
                if expected == 404:
                    refusals.setdefault(route.template, set()).add(response.text)
    assert wrong == []
    # every refusal of one route is one body, and the bodies name no network
    for template, bodies in refusals.items():
        assert len(bodies) == 1, template
        assert network not in next(iter(bodies))


async def test_every_network_route_is_isolated_between_networks_and_between_members_and_outsiders(
    net_app: NetApp, world: NetworkWorld
) -> None:
    """The generated isolation test over the routes: for each route that names a network, a viewer
    who may use the route asks for a network it is not in (another network, one outside its claim,
    one it never joined) and gets the one 404, the same body as an unknown network, and nothing of
    either network in it."""
    member = world.ids.members[0]
    network, other = world.ids.network, world.ids.other_network
    refused: list[str] = []
    async with client_of(net_app) as client:
        for route in ROUTES:
            if "{network_id}" not in route.template:
                continue
            role = next(iter(sorted(route.roles)))
            asked = [
                # a member asks for a network it is not a member of, with that network in its claim
                (member, other, (other,)),
                # a member asks for its own network with no claim at all
                (member, network, ()),
                # a tenant that never joined asks, with the network in its claim
                (world.ids.outsider, network, (network,)),
                # nobody asks for a network that does not exist
                (member, "net-nowhere", ("net-nowhere",)),
            ]
            bodies = set()
            for tenant, target, claim in asked:
                response = await client.get(
                    url(route, target),
                    params=_params(route),
                    headers=bearer(tenant, role, claim),
                )
                if response.status_code != 404:
                    refused.append(f"{route.template} {tenant} {target}: {response.status_code}")
                bodies.add(response.text)
            assert len(bodies) == 1, route.template
            body = next(iter(bodies))
            assert network not in body and other not in body
    assert refused == []


async def test_the_operator_token_and_no_token_are_refused_at_the_edge_on_every_route(
    net_app: NetApp, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    network = world.ids.network
    operator = bearer(member, Role.PLATFORM_OPERATOR, (network,))
    async with client_of(net_app) as client:
        for route in ROUTES:
            target = url(route, network)
            assert (
                await client.get(target, params=_params(route), headers=operator)
            ).status_code == 401, route.template
            assert (await client.get(target, params=_params(route))).status_code == 401


async def test_a_post_or_put_or_delete_on_a_network_route_is_never_a_write(
    net_app: NetApp, world: NetworkWorld
) -> None:
    network = world.ids.network
    headers = bearer(world.ids.members[0], Role.LEAD, (network,))
    async with client_of(net_app) as client:
        for route in ROUTES:
            if route.template.startswith("/screens"):
                continue
            target = url(route, network)
            for send in (client.post, client.put, client.delete, client.patch):
                # 415: the body-type check answers a POST, PUT or PATCH with no JSON body first
                assert (await send(target, headers=headers)).status_code in {404, 405, 415}


# ------------------------------------------------------------------ the wall screen


async def test_a_wall_reads_a_network_only_through_its_own_route_and_only_when_it_is_set(
    net_app: NetApp, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    network = world.ids.network
    async with client_of(net_app) as client:
        await _screen(world, member, network=None)
        unset = await client.get("/screens/me/network-board", headers=wall_bearer(member))
        await _screen(world, member, network=network)
        set_to_network = await client.get("/screens/me/network-board", headers=wall_bearer(member))
        by_id = [
            await client.get(f"/network/{network}/{leaf}", headers=wall_bearer(member))
            for leaf in ("board", "directory", "criteria", "system-now", "phones", "events")
        ]
    assert unset.status_code == 404 and set_to_network.status_code == 200
    assert {a.status_code for a in by_id} == {404}


async def test_a_revoked_screen_and_a_screen_that_does_not_exist_read_nothing(
    net_app: NetApp, world: NetworkWorld
) -> None:
    member = world.ids.members[0]
    network = world.ids.network
    await _screen(world, member, network=network, status=DeviceStatus.REVOKED, device_id="gone-1")
    await _screen(world, member, network=network, device_id="live-1")
    async with client_of(net_app) as client:
        live = await client.get("/screens/me/network-board", headers=wall_bearer(member, "live-1"))
        revoked = await client.get(
            "/screens/me/network-board", headers=wall_bearer(member, "gone-1")
        )
        unknown = await client.get(
            "/screens/me/network-board", headers=wall_bearer(member, "nowhere-1")
        )
    assert live.status_code == 200
    assert revoked.status_code == unknown.status_code == 404
    assert revoked.text == unknown.text


async def test_a_screen_id_of_another_tenant_reads_nothing_in_this_one(
    net_app: NetApp, world: NetworkWorld
) -> None:
    first, second = world.ids.members[:2]
    network = world.ids.network
    await _screen(world, first, network=network, device_id="only-first")
    async with client_of(net_app) as client:
        own = await client.get(
            "/screens/me/network-board", headers=wall_bearer(first, "only-first")
        )
        foreign = await client.get(
            "/screens/me/network-board", headers=wall_bearer(second, "only-first")
        )
    assert (own.status_code, foreign.status_code) == (200, 404)


async def test_a_screen_of_a_tenant_outside_the_network_cannot_be_set_to_it_and_reads_nothing(
    net_app: NetApp, world: NetworkWorld
) -> None:
    outsider = world.ids.outsider
    network = world.ids.network
    await _screen(world, outsider, network=None)
    async with client_of(net_app) as client:
        headers = {
            **bearer(outsider, Role.LEAD),
            "If-Match": 'W/"1"',
            "Idempotency-Key": f"key-{uuid.uuid4().hex}",
        }
        refused = await client.put(
            f"/screens/{SCREEN}/board-scope",
            json={"boardScope": "network", "networkId": network},
            headers=headers,
        )
        read = await client.get("/screens/me/network-board", headers=wall_bearer(outsider))
    assert refused.status_code == 404 and read.status_code == 404


async def test_a_wall_token_carries_nothing_of_the_setting(
    net_app: NetApp, world: NetworkWorld
) -> None:
    """The setting is the screen's record: a token minted before the change reads the new setting
    with no new token, and a token cannot name a network of its own."""
    member = world.ids.members[0]
    network = world.ids.network
    token = wall_bearer(member)
    await _screen(world, member, network=None)
    async with client_of(net_app) as client:
        before = await client.get("/screens/me/network-board", headers=token)
        await _screen(world, member, network=network)
        after = await client.get("/screens/me/network-board", headers=token)
        await _screen(world, member, network=None)
        back = await client.get("/screens/me/network-board", headers=token)
    assert (before.status_code, after.status_code, back.status_code) == (404, 200, 404)


# ------------------------------------------------------------------ the owner and the members


async def test_the_owner_reads_the_network_board_and_nothing_of_a_members_tenant(
    net_app: NetApp, world: NetworkWorld
) -> None:
    owner = world.ids.owner
    network = world.ids.network
    async with client_of(net_app) as client:
        board = await client.get(
            f"/network/{network}/board", headers=bearer(owner, Role.LEAD, (network,))
        )
        asked: list[Any] = []
        for member in world.ids.members:
            async with world.reader(owner) as uow:
                asked.append(await uow.services.get("svc-1"))
            own = await client.get(
                "/fhir/HealthcareService/svc-1", headers=bearer(member, Role.ADVISOR)
            )
            as_owner = await client.get(
                "/fhir/HealthcareService/svc-1", headers=bearer(owner, Role.ADVISOR)
            )
            assert own.status_code == 200, member
            assert world.service_name(member) in own.text
            assert as_owner.status_code == 404, member
            for private in world.poison[member]:
                assert private not in as_owner.text
    assert board.status_code == 200 and len(board.json()["entries"]) == 3
    assert asked == [None, None, None]


async def test_a_member_sees_the_network_board_and_only_its_own_tenants_services(
    net_app: NetApp, world: NetworkWorld
) -> None:
    first, second = world.ids.members[:2]
    network = world.ids.network
    async with client_of(net_app) as client:
        board = await client.get(
            f"/network/{network}/board", headers=bearer(first, Role.ADVISOR, (network,))
        )
        own = await client.get("/fhir/HealthcareService/svc-1", headers=bearer(first, Role.ADVISOR))
    assert len(board.json()["entries"]) == 3
    assert world.service_name(first) in own.text
    assert world.service_name(second) not in own.text
    for private in world.poison[second]:
        assert private not in own.text and private not in board.text


async def test_the_owner_cannot_change_a_members_screens_by_being_the_owner(
    net_app: NetApp, world: NetworkWorld
) -> None:
    owner = world.ids.owner
    first = world.ids.members[0]
    network = world.ids.network
    await _screen(world, first, network=None)
    async with client_of(net_app) as client:
        headers = {
            **bearer(owner, Role.LEAD, (network,)),
            "If-Match": 'W/"1"',
            "Idempotency-Key": f"key-{uuid.uuid4().hex}",
        }
        refused = await client.put(
            f"/screens/{SCREEN}/board-scope",
            json={"boardScope": "network", "networkId": network},
            headers=headers,
        )
    assert refused.status_code == 404
    with bind_tenant(first):
        async with neo4j_uow_factory(world.driver)() as uow:
            stored = await uow.devices.peek(SCREEN)
    assert stored is not None and stored.board_scope is BoardScope.TENANT
