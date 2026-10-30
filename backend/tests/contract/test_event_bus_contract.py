"""Contract for the event bus port (P08). Runs against every factory in factories.py.

The bus is asked for the next message with `receive`. Durations are seconds, so a real adapter
can run the same test in real time.
"""

from datetime import timedelta

import pytest

from diucs.application.ports.outbound.event_bus import BusMessage, EventBus
from diucs.application.tenancy import bind_network, bind_tenant
from diucs.domain.errors import ValidationFailed
from tests.contract.harness import Harness
from tests.support.servicebus import run_tenant, unique_id

# Every test sends as tenants of this run (TEN-020): the emulator and its entities are shared with
# other runs, and a message carries the tenant it belongs to.
TENANT_A = run_tenant("contract-a")
TENANT_B = run_tenant("contract-b")
QUEUE = "scheduled.work"
OTHER_QUEUE = "inbound.receipts"
DELAY = timedelta(seconds=2)
PAST_DELAY = timedelta(seconds=3)
CANCEL_DELAY = timedelta(seconds=30)
QUIET = timedelta(milliseconds=200)
PATIENCE = timedelta(seconds=2)


def _work(message_id: str) -> BusMessage:
    return BusMessage(
        id=message_id, topic="messages.outbound", event_type="prompt-due", tenant_id=TENANT_A
    )


def _capacity(message_id: str) -> BusMessage:
    return BusMessage(
        id=message_id,
        topic="capacity.events",
        event_type="CapacityReported",
        session_id="svc-1",
        tenant_id=TENANT_A,
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
    # The emulator 2.0.1 ignores a cancel, and still delivers, for a message due under about
    # 16 s away (measured, DEC-102 item 3). This case uses CANCEL_DELAY so the emulator honours
    # the cancel. The assertion is unchanged. Production Azure behaviour at short delays is a
    # human-only check.
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    number = await harness.subject.schedule(QUEUE, _work("w-1"), harness.now() + CANCEL_DELAY)
    await harness.subject.cancel(QUEUE, number)
    await harness.advance(CANCEL_DELAY + PAST_DELAY)
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


@pytest.mark.emulator_limit(
    case="test_cancelling_an_unknown_or_delivered_number_does_nothing[servicebus]",
    emulator="Azure Service Bus emulator 2.0.1",
    error="ServiceBusError: SequenceNumber = N is already being cancelled (amqp:not-allowed, 400)",
    handled_by="ServiceBusEventBus.cancel via is_unscheduled_cancel (DEC-102 item 2)",
)
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
            BusMessage(id="x-1", topic="not.a.topic", event_type="Anything", tenant_id=TENANT_A)
        )


def _inbound(message_id: str) -> BusMessage:
    return BusMessage(
        id=message_id,
        topic=OTHER_QUEUE,
        event_type="SmsDeliveryReceived",
        payload={"provider_message_id": "SM1", "status": "delivered"},
        tenant_id=TENANT_A,
    )


async def test_an_enqueued_message_is_received_at_once_without_a_wait_for_a_time(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    await harness.subject.enqueue(OTHER_QUEUE, _inbound("e-1"))
    received = await harness.receive(OTHER_QUEUE, PATIENCE)
    assert received is not None
    assert received.id == "e-1"
    assert received.payload == {"provider_message_id": "SM1", "status": "delivered"}


async def test_an_enqueued_message_is_received_on_its_queue_only(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    await harness.subject.enqueue(OTHER_QUEUE, _inbound("e-1"))
    assert await harness.receive(QUEUE, QUIET) is None
    assert await harness.receive(OTHER_QUEUE, PATIENCE) is not None


async def test_an_enqueued_message_is_received_once(bus_harness: Harness[EventBus]) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    await harness.subject.enqueue(OTHER_QUEUE, _inbound("e-1"))
    assert await harness.receive(OTHER_QUEUE, PATIENCE) is not None
    assert await harness.receive(OTHER_QUEUE, QUIET) is None


@pytest.mark.parametrize("name", ["not.a.queue", "capacity.events"])
async def test_enqueueing_to_an_unknown_queue_or_to_a_topic_is_refused(
    bus_harness: Harness[EventBus], name: str
) -> None:
    with pytest.raises(ValidationFailed):
        await bus_harness.subject.enqueue(name, _inbound("e-1"))


@pytest.mark.parametrize("name", ["not.a.queue", "capacity.events"])
async def test_scheduling_to_an_unknown_queue_or_to_a_topic_is_refused(
    bus_harness: Harness[EventBus], name: str
) -> None:
    with pytest.raises(ValidationFailed):
        await bus_harness.subject.schedule(name, _work("w-1"), bus_harness.now() + DELAY)


# ---------------------------------------------------------------- TEN-020: the tenant on the wire


async def test_a_published_message_comes_back_with_its_tenant_id_and_session(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    local = unique_id("c")
    await harness.subject.publish(
        BusMessage(
            id=local,
            topic="capacity.events",
            event_type="CapacityReported",
            session_id="svc-1",
            tenant_id=TENANT_A,
        )
    )

    received = await harness.receive("capacity.events", PATIENCE)

    assert received is not None
    assert (received.tenant_id, received.id, received.session_id) == (TENANT_A, local, "svc-1")


async def test_a_scheduled_message_comes_back_with_its_tenant_and_local_id(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    local = unique_id("w")
    await harness.subject.schedule(
        QUEUE,
        BusMessage(id=local, topic=QUEUE, event_type="prompt-due", tenant_id=TENANT_B),
        harness.now() + DELAY,
    )
    await harness.advance(PAST_DELAY)

    received = await harness.receive(QUEUE, PATIENCE)

    assert received is not None
    assert (received.tenant_id, received.id, received.session_id) == (TENANT_B, local, None)


async def test_two_tenants_with_the_same_local_id_are_both_received_on_a_queue(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    local = unique_id("same")
    for tenant in (TENANT_A, TENANT_B):
        await harness.subject.schedule(
            QUEUE,
            BusMessage(id=local, topic=QUEUE, event_type="prompt-due", tenant_id=tenant),
            harness.now() + DELAY,
        )
    await harness.advance(PAST_DELAY)

    first = await harness.receive(QUEUE, PATIENCE)
    second = await harness.receive(QUEUE, PATIENCE)

    assert first is not None and second is not None
    assert {first.tenant_id, second.tenant_id} == {TENANT_A, TENANT_B}
    assert first.id == second.id == local


async def test_two_tenants_with_the_same_local_id_and_session_are_both_received_on_a_topic(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    local = unique_id("same")
    for tenant in (TENANT_A, TENANT_B):
        await harness.subject.publish(
            BusMessage(
                id=local,
                topic="capacity.events",
                event_type="CapacityReported",
                session_id="svc-1",
                tenant_id=tenant,
            )
        )

    first = await harness.receive("capacity.events", PATIENCE)
    second = await harness.receive("capacity.events", PATIENCE)

    assert first is not None and second is not None
    assert {first.tenant_id, second.tenant_id} == {TENANT_A, TENANT_B}
    assert first.session_id == second.session_id == "svc-1"


async def test_a_send_for_another_tenant_than_the_bound_one_is_refused(
    bus_harness: Harness[EventBus],
) -> None:
    bus = bus_harness.subject
    message = BusMessage(
        id=unique_id("x"), topic="messages.outbound", event_type="SendMessage", tenant_id=TENANT_A
    )

    with bind_tenant(TENANT_B), pytest.raises(ValidationFailed, match="tenant_id"):
        await bus.publish(message)


async def test_a_message_that_carries_a_live_link_is_refused(
    bus_harness: Harness[EventBus],
) -> None:
    with pytest.raises(ValidationFailed, match="payload"):
        await bus_harness.subject.publish(
            BusMessage(
                id=unique_id("x"),
                topic="messages.outbound",
                event_type="SendMessage",
                payload={"url": "https://example.test/l/abc"},
                tenant_id=TENANT_A,
            )
        )


async def test_an_id_too_long_for_the_wire_is_refused(bus_harness: Harness[EventBus]) -> None:
    with pytest.raises(ValidationFailed, match="id"):
        await bus_harness.subject.schedule(
            QUEUE,
            BusMessage(id="x" * 120, topic=QUEUE, event_type="prompt-due", tenant_id=TENANT_A),
            bus_harness.now() + DELAY,
        )


# ---------------------------------------------------------------- TEN-055: the projection queue


def _projection(message_id: str, tenant: str = TENANT_A) -> BusMessage:
    return BusMessage(
        id=message_id,
        topic="projection.work",
        event_type="ProjectionRequested",
        payload={
            "network_id": "net-contract",
            "source_tenant_id": tenant,
            "grant_id": "grant-1",
            "grant_version": 1,
            "kind": "capacity",
            "source_service_id": "svc-1",
            "source_version": 7,
            "allowlist_version": 1,
            "body": {"slots": 3, "tags": ["a", "b"]},
            "at": "2026-10-31T09:00:00Z",
        },
        tenant_id=tenant,
    )


async def test_a_projection_message_is_received_on_the_projection_queue_with_its_tenant(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    local = unique_id("proj")
    with bind_tenant(TENANT_A):
        await harness.subject.enqueue("projection.work", _projection(local))
    received = await harness.receive("projection.work", PATIENCE)
    assert received is not None
    assert (received.id, received.tenant_id, received.event_type) == (
        local,
        TENANT_A,
        "ProjectionRequested",
    )
    assert received.session_id is None
    assert received.payload["body"] == {"slots": 3, "tags": ["a", "b"]}


async def test_a_projection_message_is_received_on_its_queue_only(
    bus_harness: Harness[EventBus],
) -> None:
    harness = _receiver(bus_harness)
    assert harness.receive is not None
    with bind_tenant(TENANT_A):
        await harness.subject.enqueue("projection.work", _projection(unique_id("proj")))
    assert await harness.receive(QUEUE, QUIET) is None
    assert await harness.receive("projection.work", PATIENCE) is not None


async def test_a_projection_message_for_another_tenant_than_the_bound_one_is_refused(
    bus_harness: Harness[EventBus],
) -> None:
    with bind_tenant(TENANT_B), pytest.raises(ValidationFailed):
        await bus_harness.subject.enqueue("projection.work", _projection(unique_id("proj")))


async def test_a_projection_message_cannot_be_sent_from_a_network_binding(
    bus_harness: Harness[EventBus],
) -> None:
    with bind_network("net-contract"), pytest.raises(ValidationFailed):
        await bus_harness.subject.enqueue("projection.work", _projection(unique_id("proj")))
