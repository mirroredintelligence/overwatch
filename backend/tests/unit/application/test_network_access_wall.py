"""What a wall screen may read of a network (TEN-067, DEC-132 item 5, DEC-546 item 1).

The screen's own record in its tenant is the authority, read on every call: set to a network, a
screen reads that network while its tenant is an active member; set to its own board, a revoked
screen, a screen that is not found and a screen whose tenant left are the one NotFound. A role that
is not a wall screen is refused with no read of any kind, and the staff gate still refuses a wall.
"""

from dataclasses import replace

import pytest

from diucs.application.actor import Actor, wall_actor
from diucs.application.network_access import NETWORK_NOT_FOUND, NetworkAccess
from diucs.application.use_cases.wall_board_scope import ReadWallScope
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from diucs.domain.model.network import MembershipStatus, NetworkStatus
from tests.support.network_samples import MEMBER_B, NETWORK_ID, make_member
from tests.unit.application.test_network_access import Names, Registry

HASH = "a" * 64
OTHER_NETWORK = "net-other"


class Screens:
    """The screens of the tenant, and every id asked about."""

    def __init__(self, *devices: Device) -> None:
        self._devices = {d.id: d for d in devices}
        self.asked: list[str] = []

    async def screen(self, device_id: str) -> Device | None:
        self.asked.append(device_id)
        return self._devices.get(device_id)


def screen(**changes: object) -> Device:
    values: dict[str, object] = {
        "id": "screen-1",
        "status": DeviceStatus.ACTIVE,
        "name": "Ward 4 corridor",
        "location": None,
        "device_type": DeviceType.WALL_DISPLAY,
        "token_hash": HASH,
        "board_scope": BoardScope.NETWORK,
        "network_id": NETWORK_ID,
        "scope_version": 3,
    }
    values.update(changes)
    return Device(**values)  # type: ignore[arg-type]


def wall(tenant: str = MEMBER_B, device_id: str | None = "screen-1") -> Actor:
    return wall_actor(tenant, device_id)


def access(registry: Registry, screens: Screens | None) -> NetworkAccess:
    return NetworkAccess(registry, Names({MEMBER_B: "B Trust"}), screens)  # type: ignore[arg-type]


async def test_a_screen_set_to_a_network_its_tenant_belongs_to_reads_it() -> None:
    found = await access(Registry([make_member(MEMBER_B)]), Screens(screen())).require_wall(wall())
    assert found.network.id == NETWORK_ID
    assert found.membership.member_tenant_id == MEMBER_B


async def test_the_screen_is_read_by_the_id_of_its_token_and_the_registry_by_its_tenant() -> None:
    registry = Registry([make_member(MEMBER_B)])
    screens = Screens(screen())
    await access(registry, screens).require_wall(wall())
    assert screens.asked == ["screen-1"]
    assert registry.calls == ["active_membership", "get_network"]


async def test_a_screen_set_to_its_own_board_has_no_network() -> None:
    registry = Registry([make_member(MEMBER_B)])
    own = screen(board_scope=BoardScope.TENANT, network_id=None)
    with pytest.raises(NotFound, match=NETWORK_NOT_FOUND):
        await access(registry, Screens(own)).require_wall(wall())
    assert registry.calls == []


@pytest.mark.parametrize("status", [DeviceStatus.REVOKED, DeviceStatus.PAIRED_UNCLAIMED])
async def test_a_screen_that_is_not_active_reads_nothing(status: DeviceStatus) -> None:
    registry = Registry([make_member(MEMBER_B)])
    device = screen(status=status, token_hash=None)
    with pytest.raises(NotFound, match=NETWORK_NOT_FOUND):
        await access(registry, Screens(device)).require_wall(wall())
    assert registry.calls == []


async def test_a_screen_that_is_not_found_reads_nothing() -> None:
    registry = Registry([make_member(MEMBER_B)])
    with pytest.raises(NotFound, match=NETWORK_NOT_FOUND):
        await access(registry, Screens()).require_wall(wall())
    assert registry.calls == []


@pytest.mark.parametrize("status", [MembershipStatus.LEFT, MembershipStatus.REMOVED])
async def test_a_screen_of_a_tenant_that_left_reads_nothing(status: MembershipStatus) -> None:
    registry = Registry([make_member(MEMBER_B, status=status)])
    with pytest.raises(NotFound, match=NETWORK_NOT_FOUND):
        await access(registry, Screens(screen())).require_wall(wall())


@pytest.mark.parametrize("status", [NetworkStatus.SUSPENDED, NetworkStatus.CLOSED])
async def test_a_screen_set_to_a_network_that_is_not_active_reads_nothing(
    status: NetworkStatus,
) -> None:
    registry = Registry([make_member(MEMBER_B)], status=status)
    with pytest.raises(NotFound, match=NETWORK_NOT_FOUND):
        await access(registry, Screens(screen())).require_wall(wall())


async def test_a_screen_set_to_another_network_than_its_tenants_reads_nothing() -> None:
    registry = Registry([make_member(MEMBER_B)])
    other = screen(network_id=OTHER_NETWORK)
    with pytest.raises(NotFound, match=NETWORK_NOT_FOUND):
        await access(registry, Screens(other)).require_wall(wall())


@pytest.mark.parametrize(
    "role",
    [r for r in Role if r is not Role.WALL],
)
async def test_no_other_role_reads_a_network_as_a_wall_screen(role: Role) -> None:
    registry = Registry([make_member(MEMBER_B)])
    screens = Screens(screen())
    staff = replace(wall(), role=role, practitioner_id="prac-1")
    with pytest.raises(NotAllowed):
        await access(registry, screens).require_wall(staff)
    assert registry.calls == [] and screens.asked == []


async def test_a_wall_token_with_no_device_and_a_missing_screen_reader_are_refused() -> None:
    registry = Registry([make_member(MEMBER_B)])
    with pytest.raises(NotAllowed):
        await access(registry, Screens(screen())).require_wall(wall(device_id=None))
    with pytest.raises(NotAllowed):
        await access(registry, None).require_wall(wall())
    assert registry.calls == []


async def test_the_staff_gate_still_refuses_a_wall_screen() -> None:
    registry = Registry([make_member(MEMBER_B)])
    with pytest.raises(NotAllowed):
        await access(registry, Screens(screen())).require_member(wall(), NETWORK_ID)
    assert registry.calls == []


# what a screen reads of its own setting


async def test_a_screen_on_a_network_is_told_the_network_and_its_version() -> None:
    reader = ReadWallScope(access(Registry([make_member(MEMBER_B)]), Screens(screen())))
    scope = await reader.execute(wall())
    assert (scope.shows, scope.fallback, scope.scope_version) == (BoardScope.NETWORK, False, 3)
    assert scope.network_name is not None


async def test_a_screen_on_its_own_board_is_told_so_with_no_flag() -> None:
    own = screen(board_scope=BoardScope.TENANT, network_id=None)
    scope = await ReadWallScope(access(Registry(), Screens(own))).execute(wall())
    assert (scope.shows, scope.network_name, scope.fallback) == (BoardScope.TENANT, None, False)


async def test_a_screen_whose_network_is_gone_falls_back_to_its_own_board_with_the_flag() -> None:
    registry = Registry([make_member(MEMBER_B, status=MembershipStatus.LEFT)])
    scope = await ReadWallScope(access(registry, Screens(screen()))).execute(wall())
    assert (scope.shows, scope.network_name, scope.fallback) == (BoardScope.TENANT, None, True)
    assert scope.scope_version == 3


async def test_the_setting_of_a_revoked_screen_is_not_found() -> None:
    revoked = screen(status=DeviceStatus.REVOKED)
    with pytest.raises(NotFound):
        await ReadWallScope(access(Registry(), Screens(revoked))).execute(wall())


async def test_the_setting_is_for_a_wall_screen_only() -> None:
    staff = replace(wall(), role=Role.LEAD, practitioner_id="prac-1")
    with pytest.raises(NotAllowed):
        await ReadWallScope(access(Registry(), Screens(screen()))).execute(staff)
