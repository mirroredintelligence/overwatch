"""The Service Bus adapter against the emulator (I02). Needs the Docker stack in infra/.

Every test uses a unique message id, because inbound.replies has duplicate detection on a 20 s
window (lesson L6, L101). Nothing here retries a send."""

import uuid
from datetime import UTC, datetime, timedelta

from azure.servicebus import ServiceBusReceivedMessage

from diucs.adapters.outbound.bus_servicebus.service_bus import (
    ServiceBusEventBus,
    to_service_bus_message,
)
from diucs.application.ports.outbound.event_bus import BusMessage
from tests.support.servicebus import client


def _unique_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


async def _receive_one(receiver_name: str, wait: timedelta) -> ServiceBusReceivedMessage | None:
    async with client() as sb, sb.get_queue_receiver(receiver_name) as receiver:
        messages = await receiver.receive_messages(
            max_message_count=1, max_wait_time=wait.total_seconds()
        )
        if not messages:
            return None
        await receiver.complete_message(messages[0])
        return messages[0]


async def test_a_queue_message_keeps_its_message_id() -> None:
    # publish() takes topics only (the port). This sends a queue message through the mapping
    # the adapter uses, so the id the receiver sees is the one the adapter sets.
    message_id = _unique_id("replies")
    async with client() as sb, sb.get_queue_sender("inbound.replies") as sender:
        await sender.send_messages(
            to_service_bus_message(
                BusMessage(id=message_id, topic="messages.outbound", event_type="ReplyReceived")
            )
        )
    received = await _receive_one("inbound.replies", timedelta(seconds=10))
    assert received is not None
    assert received.message_id == message_id


async def test_a_message_scheduled_three_seconds_ahead_arrives_after_its_time() -> None:
    sb = client()
    bus = ServiceBusEventBus(sb)
    try:
        due = datetime.now(UTC) + timedelta(seconds=3)
        number = await bus.schedule(
            "scheduled.work",
            BusMessage(id=_unique_id("due"), topic="messages.outbound", event_type="PromptDue"),
            due,
        )
        assert isinstance(number, int)
        assert await _receive_one("scheduled.work", timedelta(seconds=1)) is None
        received = await _receive_one("scheduled.work", timedelta(seconds=5))
        assert received is not None
        assert received.message_id.startswith("due-")
    finally:
        await bus.close()
        await sb.close()


async def test_a_scheduled_message_that_is_cancelled_never_arrives() -> None:
    sb = client()
    bus = ServiceBusEventBus(sb)
    try:
        number = await bus.schedule(
            "scheduled.work",
            BusMessage(id=_unique_id("gone"), topic="messages.outbound", event_type="PromptDue"),
            datetime.now(UTC) + timedelta(seconds=3),
        )
        await bus.cancel("scheduled.work", number)
        assert await _receive_one("scheduled.work", timedelta(seconds=5)) is None
    finally:
        await bus.close()
        await sb.close()
