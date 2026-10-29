"""The outbox relay against the Service Bus emulator and real Neo4j (I03). Needs the Docker stack in
infra/ for the emulator. Every id is unique, because the emulator keeps messages for an hour and
inbound.replies has duplicate detection (lessons L6, L101)."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from azure.servicebus import ServiceBusReceivedMessage
from neo4j import AsyncDriver

from diucs.adapters.inbound.workers.outbox_relay import OutboxRelay, RelayResult, StaticTenants
from diucs.adapters.outbound.bus_servicebus.service_bus import ServiceBusEventBus
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from tests.support.relay_rig import (
    NOW,
    add_messages,
    add_scheduled,
    outbox_message,
    outbox_node,
    work_node,
)
from tests.support.servicebus import client

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture
async def real_bus() -> AsyncIterator[ServiceBusEventBus]:
    sb = client()
    bus = ServiceBusEventBus(sb)
    try:
        yield bus
    finally:
        await bus.close()
        await sb.close()


def _relay(uow_factory: UnitOfWorkFactory, bus: ServiceBusEventBus, tenant_id: str) -> OutboxRelay:
    clock = FixedClock(NOW)
    return OutboxRelay(uow_factory, bus, InMemoryCache(clock), clock, StaticTenants([tenant_id]))


async def _receive_until(
    message_id: str,
    *,
    topic: str | None = None,
    subscription: str | None = None,
    queue: str | None = None,
    seconds: float = 30.0,
) -> ServiceBusReceivedMessage:
    """Receive and complete messages from a subscription or a queue until the one with this id."""
    sb = client()
    async with sb:
        if queue is not None:
            receiver = sb.get_queue_receiver(queue)
        else:
            assert topic is not None and subscription is not None
            receiver = sb.get_subscription_receiver(topic, subscription)
        async with receiver:
            deadline = datetime.now(UTC) + timedelta(seconds=seconds)
            while datetime.now(UTC) < deadline:
                for received in await receiver.receive_messages(
                    max_message_count=20, max_wait_time=3
                ):
                    await receiver.complete_message(received)
                    if received.message_id == message_id:
                        return received
    raise AssertionError("the message did not arrive")


async def test_a_pending_message_is_published_to_the_bus_and_marked_published(
    uow_factory: UnitOfWorkFactory,
    real_bus: ServiceBusEventBus,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    message_id = f"out-{uuid.uuid4()}"
    await add_messages(uow_factory, outbox_message(message_id, event_type="BookingRequested"))

    result = await _relay(uow_factory, real_bus, tenant_id).run_once()

    assert result == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert (await outbox_node(neo4j_driver, message_id))["status"] == "published"
    received = await _receive_until(message_id, topic="booking.events", subscription="notifier")
    assert received.subject == "BookingRequested"
    assert (received.application_properties or {}).get(b"tenantId") == tenant_id.encode()


async def test_scheduled_work_is_scheduled_on_the_bus_and_its_number_is_stored(
    uow_factory: UnitOfWorkFactory,
    real_bus: ServiceBusEventBus,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    work_id = f"w-{uuid.uuid4()}"
    message_id = f"out-{uuid.uuid4()}"
    due = datetime.now(UTC) + timedelta(seconds=3)
    await add_scheduled(uow_factory, work_id, message_id, due_at=due, now=NOW)

    result = await _relay(uow_factory, real_bus, tenant_id).run_once()

    assert result == RelayResult(published=1, failed=0, skipped_no_lock=False)
    stored = await work_node(neo4j_driver, work_id)
    assert isinstance(stored["sequenceNumber"], int)
    assert (await outbox_node(neo4j_driver, message_id))["status"] == "published"
    received = await _receive_until(message_id, queue="scheduled.work")
    assert received.subject == "ScheduledWorkDue"
    assert (received.application_properties or {}).get(b"tenantId") == tenant_id.encode()
