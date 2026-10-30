"""The lead's list of wall screens and the revoke (W9I, TEN-072), on recording stand-ins.

Rules each test keeps: only a shift lead lists or revokes (any other role is refused before a read);
the list never carries a token, a token hash or a pairing secret; a revoked screen has no token
hash left and the revoke is audited once, by the lead; revoking again changes and audits nothing; a
screen that is not in the tenant is NotFound. Synthetic values only.
"""

from datetime import timedelta

import pytest

from diucs.application.actor import Actor
from diucs.application.use_cases.screen_admin import (
    ListWallScreens,
    RevokeWallScreen,
    RevokeWallScreenCommand,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.device import (
    REVOKED_LISTED_FOR,
    BoardScope,
    Device,
    DeviceStatus,
    DeviceType,
    ScreenState,
)
from tests.support.screen_stubs import ScreenDevices
from tests.support.w7b_rig import LEAD, NOW, TENANT, Rig

HASH = "b" * 64
pytestmark = pytest.mark.asyncio(loop_scope="session")


def _lead() -> Actor:
    return Actor(
        role=Role.LEAD,
        practitioner_id=LEAD,
        device_id=None,
        channel="api",
        service_ids=frozenset(),
        tenant_id=TENANT,
    )


def _other(role: Role) -> Actor:
    return Actor(
        role=role,
        practitioner_id=None if role is Role.WALL else "prac-x",
        device_id="screen-1" if role is Role.WALL else None,
        channel="api",
        service_ids=frozenset(),
        tenant_id=TENANT,
    )


def _screen(device_id: str, name: str, **changes: object) -> Device:
    values: dict[str, object] = {
        "id": device_id,
        "status": DeviceStatus.ACTIVE,
        "name": name,
        "location": "Level 2",
        "device_type": DeviceType.WALL_DISPLAY,
        "token_hash": HASH,
        "board_scope": BoardScope.TENANT,
        "paired_at": NOW - timedelta(days=3),
        "last_seen_at": NOW - timedelta(seconds=40),
    }
    values.update(changes)
    return Device(**values)  # type: ignore[arg-type]


def _rig() -> tuple[Rig, ScreenDevices]:
    rig = Rig()
    devices = ScreenDevices(rig.units.writes, rig.units.calls)
    rig.units.devices = devices
    return rig, devices


async def test_the_list_gives_each_screen_with_its_state_and_times_and_nothing_secret() -> None:
    rig, devices = _rig()
    devices.screens["s-1"] = _screen("s-1", "Ward 4 corridor")
    views = await ListWallScreens(rig.uow_factory, rig.clock).execute(_lead())

    assert [(v.device_id, v.name, v.location, v.state) for v in views] == [
        ("s-1", "Ward 4 corridor", "Level 2", ScreenState.ONLINE)
    ]
    assert views[0].paired_at == NOW - timedelta(days=3)
    assert views[0].last_seen_at == NOW - timedelta(seconds=40)
    assert views[0].board_scope is BoardScope.TENANT
    assert HASH not in repr(views)
    assert not hasattr(views[0], "token_hash")


async def test_the_list_puts_live_screens_first_by_name_and_revoked_ones_last() -> None:
    rig, devices = _rig()
    devices.screens["s-1"] = _screen("s-1", "Zebra ward")
    devices.screens["s-2"] = _screen("s-2", "alpha ward", last_seen_at=None)
    devices.screens["s-3"] = _screen(
        "s-3",
        "Aardvark ward",
        status=DeviceStatus.REVOKED,
        token_hash=None,
        revoked_at=NOW - timedelta(days=1),
    )
    views = await ListWallScreens(rig.uow_factory, rig.clock).execute(_lead())
    assert [v.device_id for v in views] == ["s-2", "s-1", "s-3"]


async def test_a_screen_revoked_long_ago_is_not_listed_any_more() -> None:
    rig, devices = _rig()
    for device_id, age in (("s-1", REVOKED_LISTED_FOR - timedelta(seconds=1)), ("s-2", REVOKED_LISTED_FOR)):
        devices.screens[device_id] = _screen(
            device_id,
            device_id,
            status=DeviceStatus.REVOKED,
            token_hash=None,
            revoked_at=NOW - age,
        )
    views = await ListWallScreens(rig.uow_factory, rig.clock).execute(_lead())
    assert [v.device_id for v in views] == ["s-1"]


async def test_a_revoked_screen_with_no_revoke_time_is_still_listed() -> None:
    rig, devices = _rig()
    devices.screens["s-1"] = _screen("s-1", "Old", status=DeviceStatus.REVOKED, token_hash=None)
    views = await ListWallScreens(rig.uow_factory, rig.clock).execute(_lead())
    assert [v.device_id for v in views] == ["s-1"]


@pytest.mark.parametrize("role", [role for role in Role if role is not Role.LEAD])
async def test_every_other_role_is_refused_before_anything_is_read(role: Role) -> None:
    rig, devices = _rig()
    devices.screens["s-1"] = _screen("s-1", "Ward")
    with pytest.raises(NotAllowed):
        await ListWallScreens(rig.uow_factory, rig.clock).execute(_other(role))
    with pytest.raises(NotAllowed):
        await RevokeWallScreen(rig.uow_factory, rig.clock).execute(
            RevokeWallScreenCommand(actor=_other(role), device_id="s-1")
        )
    assert "devices.list_screens" not in rig.units.calls
    assert devices.screens["s-1"].status is DeviceStatus.ACTIVE
    assert rig.units.writes.names == []


async def test_revoking_ends_the_screen_drops_its_token_hash_and_is_audited_once() -> None:
    rig, devices = _rig()
    devices.screens["s-1"] = _screen("s-1", "Ward 4 corridor")
    result = await RevokeWallScreen(rig.uow_factory, rig.clock).execute(
        RevokeWallScreenCommand(actor=_lead(), device_id="s-1")
    )

    stored = devices.screens["s-1"]
    assert stored.status is DeviceStatus.REVOKED
    assert stored.token_hash is None
    assert stored.revoked_at == NOW
    assert result.device_id == "s-1"
    assert result.revoked_at == NOW
    assert result.already_revoked is False
    [entry] = rig.units.audit.entries
    assert entry.action == "wall-screen-revoked"
    assert entry.use_case == "RevokeWallScreen"
    assert entry.actor.practitioner_id == LEAD
    assert entry.entity_ids == ("s-1",)
    assert entry.snapshot == {"screen_name": "Ward 4 corridor", "was": "active"}
    assert HASH not in repr(entry)
    assert rig.units.commits == 1


async def test_revoking_a_screen_that_never_collected_its_token_works() -> None:
    rig, devices = _rig()
    devices.screens["s-1"] = _screen(
        "s-1", "New", status=DeviceStatus.PAIRED_UNCLAIMED, token_hash=None, last_seen_at=None
    )
    await RevokeWallScreen(rig.uow_factory, rig.clock).execute(
        RevokeWallScreenCommand(actor=_lead(), device_id="s-1")
    )
    assert devices.screens["s-1"].status is DeviceStatus.REVOKED
    assert rig.units.audit.entries[0].snapshot == {"screen_name": "New", "was": "paired-unclaimed"}


async def test_revoking_again_changes_nothing_and_audits_nothing() -> None:
    rig, devices = _rig()
    devices.screens["s-1"] = _screen(
        "s-1", "Ward", status=DeviceStatus.REVOKED, token_hash=None, revoked_at=NOW - timedelta(hours=2)
    )
    result = await RevokeWallScreen(rig.uow_factory, rig.clock).execute(
        RevokeWallScreenCommand(actor=_lead(), device_id="s-1")
    )
    assert result.already_revoked is True
    assert result.revoked_at == NOW - timedelta(hours=2)
    assert rig.units.audit.entries == []
    assert "devices.save" not in rig.units.writes.names


async def test_a_screen_that_is_not_the_tenants_is_not_found_and_nothing_is_written() -> None:
    rig, _devices = _rig()
    with pytest.raises(NotFound):
        await RevokeWallScreen(rig.uow_factory, rig.clock).execute(
            RevokeWallScreenCommand(actor=_lead(), device_id="elsewhere")
        )
    assert rig.units.writes.names == []
    assert rig.units.audit.entries == []
