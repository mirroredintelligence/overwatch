"""Contract for the event bus port (P08). Runs against every factory in factories.py.

The bus is asked for the next message with `receive`. Durations are seconds, so a real adapter
can run the same test in real time.
"""

from datetime import timedelta

import pytest

from diucs.application.ports.outbound.event_bus import BusMessage, EventBus
from diucs.domain.errors import ValidationFailed
from tests.contract.harness import Harness

QUEUE = "scheduled.work"
OTHER_QUEUE = "inbound.receipts"
DELAY = timedelta(seconds=2)
PAST_DELAY = timedelta(seconds=3)
QUIET = timedelta(milliseconds=200)
PATIENCE = timedelta(seconds=2)


def _work(message_id: str) -> BusMessage:
    return BusMessage(id=message_id, topic="messages.outbound", event_type="prompt-due")


def _capacity(message_id: str) -> BusMessage:
    return BusMessage(
        id=message_id,
        topic="capacity.events",
        event_type="CapacityReported",
        session_id="svc-1",
    )


def _receiver(harness: Harness[EventBus]) -> Harness[EventBus]:
    assert harness.receive is not None, "every event bus harness must implement receive"
    return harness


async def test_schedule_returns_increasing_sequence_numbers(bus_harness: Harness[EventBus]) -> None:
    bus = bus_harness.subject
    due = bus_harness.now() + DELAY
    first = await bus.schedule(QUEUE, _work("w-1"), due)
    second = await bus.schedule(QUEUE, _work("w-2"), due)
    assert isinstance(first, int)
    assert isinstance(second, int)
    assert second > first


async def test_a_scheduled_message_is_not_received_before_its_enqueue_time(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    await harness.subject.schedule(QUEUE, _work("w-1"), harness.now() + DELAY)
    assert await harness.receive(QUEUE, QUIET) is None


async def test_a_scheduled_message_is_receivable_at_exactly_its_enqueue_time(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    await harness.subject.schedule(QUEUE, _work("w-1"), harness.now() + DELAY)
    await harness.advance(DELAY)
    received = await harness.receive(QUEUE, PATIENCE)
    assert received is not None
    assert received.id == "w-1"


async def test_a_scheduled_message_is_received_once_its_enqueue_time_has_passed(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    await harness.subject.schedule(QUEUE, _work("w-1"), harness.now() + DELAY)
    await harness.advance(PAST_DELAY)
    received = await harness.receive(QUEUE, PATIENCE)
    assert received is not None
    assert received.id == "w-1"
    assert await harness.receive(QUEUE, QUIET) is None


async def test_a_scheduled_message_is_received_only_from_its_own_queue(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    await harness.subject.schedule(QUEUE, _work("w-1"), harness.now() + DELAY)
    await harness.advance(PAST_DELAY)
    assert await harness.receive(OTHER_QUEUE, QUIET) is None
    received = await harness.receive(QUEUE, PATIENCE)
    assert received is not None
    assert received.id == "w-1"


async def test_a_cancelled_message_is_never_received(bus_harness: Harness[EventBus]) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    number = await harness.subject.schedule(QUEUE, _work("w-1"), harness.now() + DELAY)
    await harness.subject.cancel(QUEUE, number)
    await harness.advance(PAST_DELAY)
    assert await harness.receive(QUEUE, QUIET) is None


async def test_cancelling_a_number_on_another_queue_leaves_the_message(
    bus_harness: Harness[EventBus],
) -> None:
    # The message is identified by its queue and its number, so a cancel on the wrong queue
    # must not remove it (DEC-078 item 4).
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    number = await harness.subject.schedule(QUEUE, _work("w-1"), harness.now() + DELAY)
    await harness.subject.cancel(OTHER_QUEUE, number)
    await harness.advance(PAST_DELAY)
    received = await harness.receive(QUEUE, PATIENCE)
    assert received is not None
    assert received.id == "w-1"


async def test_cancelling_an_unknown_or_delivered_number_does_nothing(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    bus = harness.subject
    await bus.cancel(QUEUE, 999_999)
    delivered = await bus.schedule(QUEUE, _work("w-1"), harness.now() + DELAY)
    await harness.advance(PAST_DELAY)
    received = await harness.receive(QUEUE, PATIENCE)
    assert received is not None
    assert received.id == "w-1"
    await bus.cancel(QUEUE, delivered)
    later = await bus.schedule(QUEUE, _work("w-2"), harness.now() + DELAY)
    assert later > delivered
    await harness.advance(PAST_DELAY)
    after = await harness.receive(QUEUE, PATIENCE)
    assert after is not None
    assert after.id == "w-2"


async def test_a_published_message_is_received_on_its_topic(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    await harness.subject.publish(_capacity("c-1"))
    received = await harness.receive("capacity.events", PATIENCE)
    assert received is not None
    assert received.id == "c-1"


async def test_publishing_to_an_unknown_topic_is_refused(bus_harness: Harness[EventBus]) -> None:
    with pytest.raises(ValidationFailed):
        await bus_harness.subject.publish(
            BusMessage(id="x-1", topic="not.a.topic", event_type="Anything")
        )


@pytest.mark.parametrize("name", ["not.a.queue", "capacity.events"])
async def test_scheduling_to_an_unknown_queue_or_to_a_topic_is_refused(
    bus_harness: Harness[EventBus], name: str
) -> None:
    with pytest.raises(ValidationFailed):
        await bus_harness.subject.schedule(name, _work("w-1"), bus_harness.now() + DELAY)
