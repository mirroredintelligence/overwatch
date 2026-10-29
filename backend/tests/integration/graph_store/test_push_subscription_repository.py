"""Integration tests for the push subscription repository (P19), against the F10 harness Neo4j.

Values are synthetic: the endpoint and keys are sample text, and none of them is logged.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.push_subscription_repository import (
    Neo4jPushSubscriptionRepository,
)
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.application.ports.outbound.messaging import PushSubscription
from diucs.domain.errors import NotFound
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip

pytestmark = pytest.mark.asyncio(loop_scope="session")

SUB_DEV_1 = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k1", "auth": "a1"}}
SAVED = datetime(2026, 10, 25, 13, 12, tzinfo=UTC)


def _sub(
    device: str, practitioner: str, subscription: dict[str, Any], saved: datetime
) -> PushSubscription:
    return PushSubscription(
        device_id=device, practitioner_id=practitioner, subscription=subscription, saved_at=saved
    )


async def _seed_practitioner(driver: AsyncDriver, practitioner_id: str) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await ResourceStore(tx).put(
            {"resourceType": "Practitioner", "id": practitioner_id, "active": True}, None
        )

    await write_tx(driver, work)


async def _save(driver: AsyncDriver, *subscriptions: PushSubscription) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = Neo4jPushSubscriptionRepository(tx)
        for subscription in subscriptions:
            await repo.save(subscription)

    await write_tx(driver, work)


@pytest.fixture
async def p1(neo4j_driver: AsyncDriver) -> None:
    await _seed_practitioner(neo4j_driver, "p1")


async def test_a_subscription_round_trips(neo4j_driver: AsyncDriver, p1: None) -> None:
    subscription = _sub("dev-1", "p1", SUB_DEV_1, SAVED)

    await assert_round_trip(
        neo4j_driver,
        lambda tx: Neo4jPushSubscriptionRepository(tx).save(subscription),
        lambda tx: Neo4jPushSubscriptionRepository(tx).for_practitioner("p1"),
        [subscription],
    )


async def test_saving_again_for_a_device_replaces_its_endpoint(
    neo4j_driver: AsyncDriver, p1: None
) -> None:
    await _save(neo4j_driver, _sub("dev-1", "p1", SUB_DEV_1, SAVED))
    renewed = {"endpoint": "https://push.example/new", "keys": {"p256dh": "k1", "auth": "a1"}}
    await _save(neo4j_driver, _sub("dev-1", "p1", renewed, SAVED))

    assert await count_nodes(neo4j_driver, "Device") == 1
    props = await node_props(neo4j_driver, "Device", id="dev-1")
    assert "https://push.example/new" in props["pushSubscriptionJson"]


async def test_two_devices_come_back_newest_first(neo4j_driver: AsyncDriver, p1: None) -> None:
    older = _sub("dev-1", "p1", SUB_DEV_1, SAVED)
    newer = _sub(
        "dev-2",
        "p1",
        {"endpoint": "https://push.example/two", "keys": {"p256dh": "k2", "auth": "a2"}},
        datetime(2026, 10, 25, 13, 20, tzinfo=UTC),
    )
    await _save(neo4j_driver, older, newer)

    found = await read_tx(
        neo4j_driver, lambda tx: Neo4jPushSubscriptionRepository(tx).for_practitioner("p1")
    )
    assert [s.device_id for s in found] == ["dev-2", "dev-1"]


async def test_deleting_removes_the_subscription_and_keeps_the_device(
    neo4j_driver: AsyncDriver, p1: None
) -> None:
    await _save(neo4j_driver, _sub("dev-1", "p1", SUB_DEV_1, SAVED))

    await write_tx(neo4j_driver, lambda tx: Neo4jPushSubscriptionRepository(tx).delete("dev-1"))

    found = await read_tx(
        neo4j_driver, lambda tx: Neo4jPushSubscriptionRepository(tx).for_practitioner("p1")
    )
    assert found == []
    assert await count_nodes(neo4j_driver, "Device") == 1
    props = await node_props(neo4j_driver, "Device", id="dev-1")
    assert props.get("pushSubscriptionJson") is None


async def test_an_unknown_practitioner_has_no_subscriptions(neo4j_driver: AsyncDriver) -> None:
    found = await read_tx(
        neo4j_driver, lambda tx: Neo4jPushSubscriptionRepository(tx).for_practitioner("nobody")
    )
    assert found == []


async def test_a_subscription_for_an_unknown_practitioner_is_refused(
    neo4j_driver: AsyncDriver,
) -> None:
    with pytest.raises(NotFound):
        await _save(neo4j_driver, _sub("dev-9", "nobody", SUB_DEV_1, SAVED))
    assert await count_nodes(neo4j_driver, "Device") == 0
