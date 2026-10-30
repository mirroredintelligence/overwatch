"""Integration tests for the wall screen list, last seen and revoke fields of the device registry
(W9I, TEN-072), on the harness Neo4j. Two tenants hold screens with the same id, and every read and
write is shown to touch the caller's own only. The hashes are synthetic."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.credential_store import Neo4jDeviceRegistry
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from tests.support.neo4j import node_props, read_tx, write_tx
from tests.support.tenancy import as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

HASH = "c" * 64
NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
WINDOW = timedelta(seconds=30)


def _screen(device_id: str = "screen-1", **changes: Any) -> Device:
    values: dict[str, Any] = {
        "id": device_id,
        "status": DeviceStatus.ACTIVE,
        "name": "Ward 4 corridor",
        "location": "Level 2",
        "device_type": DeviceType.WALL_DISPLAY,
        "token_hash": HASH,
        "board_scope": BoardScope.TENANT,
        "paired_at": NOW - timedelta(days=2),
        "last_seen_at": None,
        "revoked_at": None,
    }
    values.update(changes)
    return Device(**values)


async def _save(driver: AsyncDriver, device: Device) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jDeviceRegistry(tx).save(device)

    await write_tx(driver, work)


async def _get(driver: AsyncDriver, device_id: str) -> Device | None:
    async def work(tx: AsyncManagedTransaction) -> Device | None:
        return await Neo4jDeviceRegistry(tx).get(device_id)

    return await write_tx(driver, work)


async def _list(driver: AsyncDriver) -> list[Device]:
    async def work(tx: AsyncManagedTransaction) -> list[Device]:
        return await Neo4jDeviceRegistry(tx).list_screens()

    return await read_tx(driver, work)


async def _seen(driver: AsyncDriver, device_id: str, at: datetime) -> bool:
    async def work(tx: AsyncManagedTransaction) -> bool:
        return await Neo4jDeviceRegistry(tx).confirm_active(device_id, at, WINDOW)

    return await write_tx(driver, work)


async def test_the_times_of_a_screen_round_trip_and_an_unset_one_is_absent(
    neo4j_driver: AsyncDriver,
) -> None:
    full = _screen(
        status=DeviceStatus.REVOKED,
        token_hash=None,
        last_seen_at=NOW - timedelta(hours=1),
        revoked_at=NOW,
    )
    await _save(neo4j_driver, full)
    assert await _get(neo4j_driver, "screen-1") == full

    await _save(neo4j_driver, _screen(paired_at=None))
    props = await node_props(neo4j_driver, "Device", id="screen-1")
    assert "pairedAt" not in props
    assert "lastSeenAt" not in props
    assert "revokedAt" not in props


async def test_the_list_gives_the_tenants_wall_screens_in_name_order_and_no_other_device(
    neo4j_driver: AsyncDriver, other_tenant_id: str
) -> None:
    await _save(neo4j_driver, _screen("screen-2", name="Zebra"))
    await _save(neo4j_driver, _screen("screen-1", name="Alpha"))

    async def a_phone(tx: AsyncManagedTransaction) -> None:
        # A practitioner's device: no deviceType, so it is never a screen.
        await tx.run("CREATE (:Device {id: 'phone-1', tenantId: $tenant, status: 'active'})")

    await write_tx(neo4j_driver, a_phone)
    with as_tenant(other_tenant_id):
        await _save(neo4j_driver, _screen("screen-1", name="Other tenant screen"))
        assert [d.name for d in await _list(neo4j_driver)] == ["Other tenant screen"]
    assert [d.id for d in await _list(neo4j_driver)] == ["screen-1", "screen-2"]


async def test_the_list_is_empty_for_a_tenant_with_no_screen(
    neo4j_driver: AsyncDriver, other_tenant_id: str
) -> None:
    await _save(neo4j_driver, _screen())
    with as_tenant(other_tenant_id):
        assert await _list(neo4j_driver) == []


async def test_an_active_screen_is_confirmed_and_marked_seen_once_in_the_window(
    neo4j_driver: AsyncDriver,
) -> None:
    await _save(neo4j_driver, _screen())
    assert await _seen(neo4j_driver, "screen-1", NOW) is True
    first = await _get(neo4j_driver, "screen-1")
    assert first is not None and first.last_seen_at == NOW

    assert await _seen(neo4j_driver, "screen-1", NOW + WINDOW - timedelta(seconds=1)) is True
    again = await _get(neo4j_driver, "screen-1")
    assert again is not None and again.last_seen_at == NOW

    assert await _seen(neo4j_driver, "screen-1", NOW + WINDOW + timedelta(seconds=1)) is True
    later = await _get(neo4j_driver, "screen-1")
    assert later is not None and later.last_seen_at == NOW + WINDOW + timedelta(seconds=1)


@pytest.mark.parametrize(
    "changes",
    [
        {"status": DeviceStatus.REVOKED, "token_hash": None},
        {"status": DeviceStatus.PAIRED_UNCLAIMED, "token_hash": None},
    ],
)
async def test_a_screen_that_is_not_active_is_not_confirmed_and_is_not_marked_seen(
    neo4j_driver: AsyncDriver, changes: dict[str, Any]
) -> None:
    await _save(neo4j_driver, _screen(**changes))
    assert await _seen(neo4j_driver, "screen-1", NOW) is False
    assert "lastSeenAt" not in await node_props(neo4j_driver, "Device", id="screen-1")


async def test_an_unknown_screen_and_a_practitioners_device_are_not_confirmed(
    neo4j_driver: AsyncDriver,
) -> None:
    async def a_phone(tx: AsyncManagedTransaction) -> None:
        await tx.run("CREATE (:Device {id: 'phone-1', tenantId: $tenant, status: 'active'})")

    await write_tx(neo4j_driver, a_phone)
    assert await _seen(neo4j_driver, "nowhere", NOW) is False
    assert await _seen(neo4j_driver, "phone-1", NOW) is False
    assert "lastSeenAt" not in await node_props(neo4j_driver, "Device", id="phone-1")


async def test_another_tenants_screen_is_not_confirmed_and_not_touched(
    neo4j_driver: AsyncDriver, other_tenant_id: str
) -> None:
    await _save(neo4j_driver, _screen("screen-1", name="Mine"))
    with as_tenant(other_tenant_id):
        await _save(neo4j_driver, _screen("screen-2", name="Theirs"))
        assert await _seen(neo4j_driver, "screen-1", NOW) is False
        assert await _seen(neo4j_driver, "screen-2", NOW) is True
    mine = await _get(neo4j_driver, "screen-1")
    assert mine is not None and mine.last_seen_at is None
    assert await _get(neo4j_driver, "screen-2") is None
