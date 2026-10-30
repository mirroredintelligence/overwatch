"""The count of a practitioner's active devices (W7C): the reporter's settings say how many other
phones are signed in, and "sign out of every phone" shows the count before it asks.

An active device is one that is registered, not revoked and not waiting for the lead's call-back.
The count is of one practitioner only. Samples only.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.credential_store import Neo4jDeviceRegistry
from diucs.adapters.outbound.graph_store.person_repository import Neo4jPersonRepository
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.model.people import Practitioner
from tests.support.neo4j import write_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

AT = datetime(2026, 10, 25, 11, 0, tzinfo=UTC)


async def _run(driver: AsyncDriver, step: Any) -> Any:
    async def work(tx: AsyncManagedTransaction) -> Any:
        return await step(Neo4jDeviceRegistry(tx))

    return await write_tx(driver, work)


@pytest_asyncio.fixture(loop_scope="session")
async def practitioners(neo4j_driver: AsyncDriver, clean_graph: None) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = Neo4jPersonRepository(tx, ResourceStore(tx))
        for person in ("p1", "p2"):
            await repo.save_practitioner(
                Practitioner(id=person, active=True, display_name="Sample", phone_hash=None)
            )

    await write_tx(neo4j_driver, work)


async def test_a_practitioner_with_no_device_has_none(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    assert await _run(neo4j_driver, lambda devices: devices.count_active("p1")) == 0


async def test_each_registered_device_is_counted(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda devices: devices.register("p1", "dev-1", AT))
    await _run(neo4j_driver, lambda devices: devices.register("p1", "dev-2", AT))

    assert await _run(neo4j_driver, lambda devices: devices.count_active("p1")) == 2


async def test_another_practitioners_devices_are_not_counted(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda devices: devices.register("p1", "dev-1", AT))
    await _run(neo4j_driver, lambda devices: devices.register("p2", "dev-2", AT))

    assert await _run(neo4j_driver, lambda devices: devices.count_active("p1")) == 1


async def test_a_revoked_device_and_one_waiting_for_the_callback_are_not_counted(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda devices: devices.register("p1", "dev-1", AT))
    await _run(neo4j_driver, lambda devices: devices.register("p1", "dev-2", AT))
    await _run(neo4j_driver, lambda devices: devices.revoke_all("p1"))
    await _run(neo4j_driver, lambda devices: devices.register_pending("p1", "dev-3", AT))
    await _run(neo4j_driver, lambda devices: devices.register("p1", "dev-4", AT))

    assert await _run(neo4j_driver, lambda devices: devices.count_active("p1")) == 1
