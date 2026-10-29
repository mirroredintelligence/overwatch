"""Unit tests for the Service Bus fake with a manual clock (P08).

Times are UTC unless a test says otherwise. Europe/London is exercised on 2026-10-25, the day the
clocks go back (lessons L4 and L52): due times are compared as instants, never as wall-clock times.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.event_bus import BusMessage, WireView
from diucs.application.tenancy import bind_tenant
from diucs.domain.errors import ValidationFailed

LONDON = ZoneInfo("Europe/London")
NOW = datetime(2026, 10, 24, 14, 0, tzinfo=UTC)
QUEUE = "scheduled.work"


def _at(hour: int, minute: int) -> datetime:
    return datetime(2026, 10, 24, hour, minute, tzinfo=UTC)


def _message(id_: str, topic: str = "scheduled.work") -> BusMessage:
    return BusMessage(
        id=id_, topic=topic, event_type="ScheduleWork", payload={"n": 1}, tenant_id="tenant-a"
    )


def _bus() -> ManualEventBus:
    return ManualEventBus(FixedClock(NOW))


async def test_three_schedules_get_sequence_numbers_one_two_three() -> None:
    bus = _bus()
    numbers = [await bus.schedule(QUEUE, _message(f"m{i}"), _at(15, i)) for i in range(1, 4)]
    assert numbers == [1, 2, 3]


async def test_messages_are_due_only_once_their_enqueue_time_has_passed() -> None:
    bus = _bus()
    a = _message("a")
    b = _message("b")
    await bus.schedule(QUEUE, a, _at(14, 21))
    await bus.schedule(QUEUE, b, _at(14, 26))

    assert bus.due(_at(14, 20)) == []
    assert bus.due(_at(14, 21)) == [(QUEUE, a)]
    assert bus.due(_at(14, 30)) == [(QUEUE, b)]
    assert bus.due(_at(14, 30)) == []


async def test_a_cancelled_message_is_never_delivered_and_unknown_numbers_do_nothing() -> None:
    bus = _bus()
    await bus.schedule(QUEUE, _message("a"), _at(14, 21))
    b_number = await bus.schedule(QUEUE, _message("b"), _at(14, 26))

    await bus.cancel(QUEUE, b_number)
    assert bus.due(_at(14, 30)) == [(QUEUE, _message("a"))]

    await bus.cancel(QUEUE, 99)
    await bus.cancel(QUEUE, 1)  # already delivered above
    assert bus.due(_at(15, 0)) == []


async def test_a_message_published_to_a_topic_appears_only_under_that_topic() -> None:
    bus = _bus()
    booking = _message("booking-1", topic="booking.events")
    await bus.publish(booking)

    assert bus.published_to("booking.events") == [booking]
    assert bus.published_to("capacity.events") == []
    assert bus.published == [booking]


async def test_scheduling_to_a_topic_or_an_unknown_name_is_refused() -> None:
    bus = _bus()
    with pytest.raises(ValidationFailed, match="queue"):
        await bus.schedule("booking.events", _message("x"), _at(14, 21))
    with pytest.raises(ValidationFailed, match="queue"):
        await bus.schedule("nowhere", _message("y"), _at(14, 21))


async def test_publishing_to_an_unknown_topic_is_refused() -> None:
    bus = _bus()
    with pytest.raises(ValidationFailed, match="topic"):
        await bus.publish(_message("x", topic="nowhere.events"))


async def test_capacity_events_must_carry_the_service_id_as_session_id() -> None:
    bus = _bus()
    unsessioned = _message("cap-1", topic="capacity.events")
    with pytest.raises(ValidationFailed, match="session"):
        await bus.publish(unsessioned)

    sessioned = BusMessage(
        id="cap-2",
        topic="capacity.events",
        event_type="CapacityReported",
        payload={},
        session_id="service-1",
        tenant_id="tenant-a",
    )
    await bus.publish(sessioned)
    assert bus.published_to("capacity.events") == [sessioned]


async def test_a_naive_enqueue_time_is_refused() -> None:
    bus = _bus()
    with pytest.raises(ValidationFailed, match="enqueue_at"):
        await bus.schedule(QUEUE, _message("x"), datetime(2026, 10, 24, 14, 21))


async def test_due_compares_instants_across_the_london_clock_change() -> None:
    # 2026-10-25 01:30 London is ambiguous. Fold 0 is BST, which is 00:30 UTC. Fold 1 is GMT.
    bst_0130 = datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=0)
    bus = ManualEventBus(FixedClock(datetime(2026, 10, 25, 1, 0, tzinfo=UTC)))
    message = _message("london")
    await bus.schedule(QUEUE, message, bst_0130)

    # 00:30 UTC has passed at 01:00 UTC, so the message is due. Comparing wall-clock times
    # (01:30 against 01:00) would wrongly keep it back.
    assert bus.due() == [(QUEUE, message)]


async def test_due_defaults_to_the_clock_when_no_time_is_given() -> None:
    clock = FixedClock(_at(14, 0))
    bus = ManualEventBus(clock)
    message = _message("a")
    await bus.schedule(QUEUE, message, _at(14, 21))

    assert bus.due() == []
    clock.advance(_at(14, 21) - _at(14, 0))
    assert bus.due() == [(QUEUE, message)]


async def test_an_enqueued_message_is_listed_for_its_queue_with_its_tenant() -> None:
    bus = _bus()
    message = BusMessage(
        id="r-1", topic="inbound.replies", event_type="SmsReceived", tenant_id="tenant-a"
    )
    await bus.enqueue("inbound.replies", message)
    assert bus.enqueued_to("inbound.replies") == [message]
    assert bus.enqueued_to("inbound.replies")[0].tenant_id == "tenant-a"
    assert bus.enqueued_to("inbound.receipts") == []


async def test_enqueued_messages_keep_their_order_and_are_not_published_or_scheduled() -> None:
    bus = _bus()
    first = _message("e-1", "inbound.replies")
    second = _message("e-2", "inbound.replies")
    await bus.enqueue("inbound.replies", first)
    await bus.enqueue("inbound.replies", second)
    assert bus.enqueued_to("inbound.replies") == [first, second]
    assert bus.published == []
    assert bus.due(_at(23, 0)) == []


async def test_take_enqueued_returns_each_message_once_with_its_queue() -> None:
    bus = _bus()
    message = _message("e-1", "inbound.receipts")
    await bus.enqueue("inbound.receipts", message)
    assert bus.take_enqueued() == [("inbound.receipts", message)]
    assert bus.take_enqueued() == []
    assert bus.enqueued_to("inbound.receipts") == []


@pytest.mark.parametrize("name", ["not.a.queue", "capacity.events"])
async def test_enqueueing_to_an_unknown_queue_or_a_topic_is_refused_and_records_nothing(
    name: str,
) -> None:
    bus = _bus()
    with pytest.raises(ValidationFailed):
        await bus.enqueue(name, _message("e-1"))
    assert bus.enqueued_to(name) == []


# -------------------------------------------------------------- TEN-020: the tenant


def _capacity(id_: str, tenant: str, session: str = "svc-1") -> BusMessage:
    return BusMessage(
        id=id_,
        topic="capacity.events",
        event_type="CapacityReported",
        session_id=session,
        tenant_id=tenant,
    )


async def test_two_tenants_may_publish_the_same_local_id_and_session_and_both_are_kept() -> None:
    bus = _bus()
    first, second = _capacity("c-1", "tenant-a"), _capacity("c-1", "tenant-b")
    await bus.publish(first)
    await bus.publish(second)

    assert bus.published_to("capacity.events") == [first, second]
    assert bus.published_to("capacity.events", "tenant-a") == [first]
    assert bus.published_to("capacity.events", "tenant-b") == [second]
    assert bus.published_to("capacity.events", "tenant-c") == []


async def test_the_wire_form_of_two_tenants_messages_differs_in_both_ids() -> None:
    bus = _bus()
    first, second = _capacity("c-1", "tenant-a"), _capacity("c-1", "tenant-b")

    wire_a, wire_b = bus.wire(first), bus.wire(second)

    assert isinstance(wire_a, WireView)
    assert wire_a.message_id == "tenant-a:c-1" and wire_b.message_id == "tenant-b:c-1"
    assert wire_a.session_id == "tenant-a:svc-1" and wire_b.session_id == "tenant-b:svc-1"
    assert wire_a.application_properties["tenantId"] == "tenant-a"


async def test_due_returns_each_message_with_its_own_tenant() -> None:
    bus = _bus()
    await bus.schedule(QUEUE, _capacity("w-1", "tenant-a"), _at(14, 21))
    await bus.schedule(QUEUE, _capacity("w-1", "tenant-b"), _at(14, 21))

    due = bus.due(_at(15, 0))

    assert [(queue, message.tenant_id) for queue, message in due] == [
        (QUEUE, "tenant-a"),
        (QUEUE, "tenant-b"),
    ]


async def test_an_enqueued_message_keeps_its_tenant() -> None:
    bus = _bus()
    await bus.enqueue("inbound.replies", _capacity("e-1", "tenant-b"))

    assert [m.tenant_id for m in bus.enqueued_to("inbound.replies")] == ["tenant-b"]


async def _publish(bus: ManualEventBus, message: BusMessage) -> None:
    await bus.publish(message)


async def _enqueue(bus: ManualEventBus, message: BusMessage) -> None:
    await bus.enqueue("inbound.replies", message)


async def _schedule(bus: ManualEventBus, message: BusMessage) -> None:
    await bus.schedule(QUEUE, message, _at(15, 0))


_SENDS = [
    pytest.param(_publish, id="publish"),
    pytest.param(_enqueue, id="enqueue"),
    pytest.param(_schedule, id="schedule"),
]


def _plain(**changes: object) -> BusMessage:
    fields: dict[str, object] = {
        "id": "m-1",
        "topic": "messages.outbound",
        "event_type": "SendMessage",
        "session_id": "svc-1",
        "tenant_id": "tenant-a",
    }
    fields.update(changes)
    return BusMessage(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("send", _SENDS)
async def test_a_message_the_adapter_refuses_for_length_is_refused_by_the_fake(
    send: object,
) -> None:
    bus = _bus()

    with pytest.raises(ValidationFailed, match="id"):
        await send(bus, _plain(id="x" * 120))  # type: ignore[operator]

    assert (
        bus.published == []
        and bus.enqueued_to("inbound.replies") == []
        and bus.due(_at(23, 0)) == []
    )


@pytest.mark.parametrize("send", _SENDS)
async def test_a_message_the_adapter_refuses_for_the_bound_tenant_is_refused_by_the_fake(
    send: object,
) -> None:
    bus = _bus()

    with bind_tenant("tenant-b"), pytest.raises(ValidationFailed, match="tenant_id"):
        await send(bus, _plain())  # type: ignore[operator]

    assert (
        bus.published == []
        and bus.enqueued_to("inbound.replies") == []
        and bus.due(_at(23, 0)) == []
    )


@pytest.mark.parametrize("send", _SENDS)
async def test_a_message_the_adapter_refuses_for_a_live_link_is_refused_by_the_fake(
    send: object,
) -> None:
    bus = _bus()

    with pytest.raises(ValidationFailed, match="payload"):
        await send(bus, _plain(payload={"token": "x"}))  # type: ignore[operator]

    assert (
        bus.published == []
        and bus.enqueued_to("inbound.replies") == []
        and bus.due(_at(23, 0)) == []
    )


async def test_a_message_for_the_bound_tenant_is_accepted() -> None:
    bus = _bus()

    with bind_tenant("tenant-a"):
        await bus.publish(_plain())

    assert len(bus.published) == 1
