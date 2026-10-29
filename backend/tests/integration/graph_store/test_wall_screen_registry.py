"""Integration tests for the wall screen side of the device registry (U10, DEC-160).

Run against the throwaway Neo4j of the F10 harness. Each write commits in its own transaction and
each read runs in a fresh session. The hashes are synthetic.
"""

import asyncio
from typing import Any, cast

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.credential_store import Neo4jDeviceRegistry
from diucs.domain.errors import Conflict
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.tenancy import as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

HASH = "c" * 64
OTHER_HASH = "d" * 64


def _unclaimed(device_id: str = "screen-1", **changes: Any) -> Device:
    values: dict[str, Any] = {
        "id": device_id,
        "status": DeviceStatus.PAIRED_UNCLAIMED,
        "name": "Ward 4 corridor",
        "location": "Level 2",
        "device_type": DeviceType.WALL_DISPLAY,
        "token_hash": None,
    }
    values.update(changes)
    return Device(**values)


def _active(device_id: str = "screen-1", token_hash: str = HASH, **changes: Any) -> Device:
    return _unclaimed(device_id, status=DeviceStatus.ACTIVE, token_hash=token_hash, **changes)


async def _save(driver: AsyncDriver, device: Device) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jDeviceRegistry(tx).save(device)

    await write_tx(driver, work)


async def _get(driver: AsyncDriver, device_id: str) -> Device | None:
    # `get` takes the write lock first (lesson L85), so it is a write: read it with write_tx.
    async def work(tx: AsyncManagedTransaction) -> Device | None:
        return await Neo4jDeviceRegistry(tx).get(device_id)

    return await write_tx(driver, work)


async def _find(driver: AsyncDriver, token_hash: str) -> Device | None:
    async def work(tx: AsyncManagedTransaction) -> Device | None:
        return await Neo4jDeviceRegistry(tx).find_by_token_hash(token_hash)

    return await read_tx(driver, work)


async def _cypher(driver: AsyncDriver, text: str, **params: Any) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(text, **params)

    await write_tx(driver, work)


async def test_an_unclaimed_screen_round_trips_and_stores_no_null(
    neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    device = _unclaimed(location=None)
    await _save(neo4j_driver, device)
    assert await _get(neo4j_driver, "screen-1") == device
    props = await node_props(neo4j_driver, "Device", id="screen-1")
    assert set(props) == {
        "id",
        "tenantId",
        "deviceType",
        "status",
        "deviceName",
        "boardScope",
        "updatedAt",
    }
    assert props["tenantId"] == tenant_id
    assert props["status"] == "paired-unclaimed"
    assert props["boardScope"] == "tenant"


async def test_an_active_screen_with_a_place_and_the_network_board_round_trips(
    neo4j_driver: AsyncDriver,
) -> None:
    device = _active(board_scope=BoardScope.NETWORK)
    await _save(neo4j_driver, device)
    assert await _get(neo4j_driver, "screen-1") == device
    props = await node_props(neo4j_driver, "Device", id="screen-1")
    assert props["tokenHash"] == HASH
    assert props["locationName"] == "Level 2"
    assert props["boardScope"] == "network"


async def test_saving_again_replaces_the_record_and_clears_what_is_no_longer_set(
    neo4j_driver: AsyncDriver,
) -> None:
    await _save(neo4j_driver, _active())
    replacement = _unclaimed(name="Ward 5 corridor", location=None)
    await _save(neo4j_driver, replacement)
    assert await _get(neo4j_driver, "screen-1") == replacement
    props = await node_props(neo4j_driver, "Device", id="screen-1")
    assert "tokenHash" not in props
    assert "locationName" not in props
    assert await count_nodes(neo4j_driver, "Device") == 1


async def test_a_screen_that_does_not_exist_is_none(neo4j_driver: AsyncDriver) -> None:
    assert await _get(neo4j_driver, "no-such-screen") is None


async def test_a_practitioners_device_is_never_read_or_overwritten_as_a_screen(
    neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _cypher(
        neo4j_driver,
        "CREATE (:Device {id: 'phone-1', tenantId: $tenant, status: 'active', "
        "tokenHash: $hash, deviceName: 'A phone'})",
        tenant=tenant_id,
        hash=HASH,
    )
    assert await _get(neo4j_driver, "phone-1") is None
    assert await _find(neo4j_driver, HASH) is None
    with pytest.raises(Conflict):
        await _save(neo4j_driver, _unclaimed("phone-1"))
    props = await node_props(neo4j_driver, "Device", id="phone-1")
    assert props["deviceName"] == "A phone"
    assert "deviceType" not in props


async def test_find_by_token_hash_finds_only_an_active_screen(neo4j_driver: AsyncDriver) -> None:
    await _save(neo4j_driver, _active("screen-1", HASH))
    await _save(neo4j_driver, _unclaimed("screen-2"))
    assert await _find(neo4j_driver, HASH) == _active("screen-1", HASH)
    assert await _find(neo4j_driver, OTHER_HASH) is None
    await _cypher(neo4j_driver, "MATCH (d:Device {id: 'screen-1'}) SET d.status = 'revoked'")
    assert await _find(neo4j_driver, HASH) is None


async def test_two_active_screens_with_one_hash_are_refused_not_read_as_one_of_them(
    neo4j_driver: AsyncDriver,
) -> None:
    await _save(neo4j_driver, _active("screen-1", HASH))
    await _save(neo4j_driver, _active("screen-2", HASH))
    with pytest.raises(Conflict):
        await _find(neo4j_driver, HASH)


async def test_get_waits_for_a_held_get_of_the_same_screen_and_then_proceeds(
    neo4j_driver: AsyncDriver,
) -> None:
    """The lock that lets a single-use change read, judge and save (lesson L85): a second get of
    the screen must still be waiting while the first holds the screen, and finish after it."""
    await _save(neo4j_driver, _unclaimed())
    async with neo4j_driver.session() as holder:
        held = await holder.begin_transaction()
        await Neo4jDeviceRegistry(cast(AsyncManagedTransaction, held)).get("screen-1")
        second = asyncio.create_task(_get(neo4j_driver, "screen-1"))
        done, _ = await asyncio.wait({second}, timeout=1.0)
        assert not done, "the second get did not wait for the first"
        await held.commit()
        assert await asyncio.wait_for(second, timeout=10) == _unclaimed()


async def test_a_screen_of_one_tenant_is_not_found_by_another(
    neo4j_driver: AsyncDriver, other_tenant_id: str
) -> None:
    await _save(neo4j_driver, _active("screen-a", HASH))
    with as_tenant(other_tenant_id):
        assert await _get(neo4j_driver, "screen-a") is None
        assert await _find(neo4j_driver, HASH) is None
        await _save(neo4j_driver, _active("screen-b", HASH, name="Ward 9 corridor"))
        assert await _find(neo4j_driver, HASH) == _active("screen-b", HASH, name="Ward 9 corridor")
    assert await _find(neo4j_driver, HASH) == _active("screen-a", HASH)
    assert (await node_props(neo4j_driver, "Device", id="screen-a"))[
        "deviceName"
    ] == "Ward 4 corridor"
