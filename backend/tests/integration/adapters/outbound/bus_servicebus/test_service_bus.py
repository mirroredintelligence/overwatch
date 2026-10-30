"""The Service Bus adapter against the emulator (I02, TEN-020). Needs the Docker stack in infra/.

Every test uses a unique message id, because inbound.replies has duplicate detection on a 20 s
window (lesson L6, L101), and sends as tenants of this run only: the emulator is shared with other
runs. Nothing here retries a send. The wire carries the tenant as the application property
`tenantId`, and the message id and the session id are `<tenant>:<local id>`.
"""

from datetime import UTC, datetime, timedelta

import pytest
from azure.servicebus import ServiceBusReceivedMessage

from diucs.adapters.outbound.bus_servicebus.service_bus import (
    ServiceBusEventBus,
    to_service_bus_message,
)
from diucs.application.ports.outbound.event_bus import BusMessage, from_wire
from tests.support.servicebus import client, run_tenant, unique_id

# These suites send as tenants of their own on the shared emulator, with nothing bound: the way the
# outbox relay publishes, where the message's own tenant is the declaration (`check_publishable`).
# A bound tenant that is not the message's is refused, which the unit tests pin.
pytestmark = pytest.mark.no_tenant

TENANT_A = run_tenant("integ-a")
TENANT_B = run_tenant("integ-b")


def _unique_id(prefix: str) -> str:
    return unique_id(prefix)


async def _receive_one(receiver_name: str, wait: timedelta) -> ServiceBusReceivedMessage | None:
    async with client() as sb, sb.get_queue_receiver(receiver_name) as receiver:
        messages = await receiver.receive_messages(
            max_message_count=1, max_wait_time=wait.total_seconds()
        )
        if not messages:
            return None
        await receiver.complete_message(messages[0])
        return messages[0]


def _work(local_id: str, tenant: str = TENANT_A) -> BusMessage:
    return BusMessage(
        id=local_id, topic="messages.outbound", event_type="PromptDue", tenant_id=tenant
    )


async def test_a_queue_message_keeps_its_qualified_message_id_and_the_tenant_property() -> None:
    # publish() takes topics only (the port). This sends a queue message through the mapping the
    # adapter uses, so the id and the property the receiver sees are the ones the adapter sets.
    # It also finds out whether the emulator keeps a colon in a message id (TEN-020 rule 1).
    local = _unique_id("replies")
    async with client() as sb, sb.get_queue_sender("inbound.replies") as sender:
        await sender.send_messages(
            to_service_bus_message(
                BusMessage(
                    id=local,
                    topic="inbound.replies",
                    event_type="ReplyReceived",
                    tenant_id=TENANT_A,
                )
            )
        )
    received = await _receive_one("inbound.replies", timedelta(seconds=10))
    assert received is not None
    assert received.message_id == f"{TENANT_A}:{local}"
    assert received.application_properties is not None
    assert received.application_properties[b"tenantId"] == TENANT_A.encode()


async def test_a_session_id_keeps_its_tenant_qualification_on_the_emulator() -> None:
    # The emulator must keep `<tenant>:<service>` as a session id: a session orders one tenant's
    # one service (TEN-020 rule 1). The topic subscription is read by the contract suite; this
    # case checks the mapping the adapter builds and what a receiver reads back through from_wire.
    local = _unique_id("cap")
    sent = to_service_bus_message(
        BusMessage(
            id=local,
            topic="capacity.events",
            event_type="CapacityReported",
            session_id="svc-1",
            tenant_id=TENANT_A,
        )
    )
    assert sent.session_id == f"{TENANT_A}:svc-1"
    message = from_wire(
        "capacity.events",
        message_id=sent.message_id,
        session_id=sent.session_id,
        subject=sent.subject,
        properties=sent.application_properties,
        payload={},
    )
    assert (message.id, message.session_id, message.tenant_id) == (local, "svc-1", TENANT_A)


async def test_the_same_local_id_for_two_tenants_arrives_twice_on_the_detected_queue() -> None:
    # inbound.replies drops a repeated message id inside its window. The wire id is qualified, so
    # one tenant's id can no longer drop another tenant's message (TEN-020; audit C 5.2).
    local = _unique_id("dup")
    async with client() as sb, sb.get_queue_sender("inbound.replies") as sender:
        for tenant in (TENANT_A, TENANT_B):
            await sender.send_messages(
                to_service_bus_message(
                    BusMessage(
                        id=local,
                        topic="inbound.replies",
                        event_type="SmsReceived",
                        tenant_id=tenant,
                    )
                )
            )
    first = await _receive_one("inbound.replies", timedelta(seconds=10))
    second = await _receive_one("inbound.replies", timedelta(seconds=10))

    assert first is not None and second is not None
    assert {first.message_id, second.message_id} == {f"{TENANT_A}:{local}", f"{TENANT_B}:{local}"}


async def test_the_same_tenant_and_id_sent_twice_arrives_once() -> None:
    # Recorded as the emulator's one duplicate-detection window (20 s): the second send is dropped.
    local = _unique_id("once")
    message = BusMessage(
        id=local, topic="inbound.replies", event_type="SmsReceived", tenant_id=TENANT_A
    )
    async with client() as sb, sb.get_queue_sender("inbound.replies") as sender:
        await sender.send_messages(to_service_bus_message(message))
        await sender.send_messages(to_service_bus_message(message))
    first = await _receive_one("inbound.replies", timedelta(seconds=10))
    second = await _receive_one("inbound.replies", timedelta(seconds=3))

    assert first is not None
    assert first.message_id == f"{TENANT_A}:{local}"
    assert second is None


async def test_a_message_scheduled_three_seconds_ahead_arrives_after_its_time() -> None:
    sb = client()
    bus = ServiceBusEventBus(sb)
    try:
        due = datetime.now(UTC) + timedelta(seconds=3)
        number = await bus.schedule("scheduled.work", _work(_unique_id("due")), due)
        assert isinstance(number, int)
        assert await _receive_one("scheduled.work", timedelta(seconds=1)) is None
        received = await _receive_one("scheduled.work", timedelta(seconds=5))
        assert received is not None
        assert received.message_id.startswith(f"{TENANT_A}:due-")
    finally:
        await bus.close()
        await sb.close()


async def test_a_scheduled_message_that_is_cancelled_never_arrives() -> None:
    # A 3 s schedule is not enough: the emulator delivers a cancelled message due under about
    # 16 s away (DEC-102 item 3). The wait runs past the 30 s due time, so a delivery would show.
    sb = client()
    bus = ServiceBusEventBus(sb)
    try:
        number = await bus.schedule(
            "scheduled.work",
            _work(_unique_id("gone")),
            datetime.now(UTC) + timedelta(seconds=30),
        )
        await bus.cancel("scheduled.work", number)
        assert await _receive_one("scheduled.work", timedelta(seconds=33)) is None
    finally:
        await bus.close()
        await sb.close()


async def test_cancelling_a_pending_message_succeeds() -> None:
    sb = client()
    bus = ServiceBusEventBus(sb)
    try:
        number = await bus.schedule(
            "scheduled.work",
            _work(_unique_id("pending")),
            datetime.now(UTC) + timedelta(seconds=30),
        )
        await bus.cancel("scheduled.work", number)
    finally:
        await bus.close()
        await sb.close()


async def test_cancelling_an_unknown_number_is_a_no_op() -> None:
    sb = client()
    bus = ServiceBusEventBus(sb)
    try:
        await bus.cancel("scheduled.work", 999_999)
    finally:
        await bus.close()
        await sb.close()


async def test_cancelling_a_delivered_number_is_a_no_op() -> None:
    sb = client()
    bus = ServiceBusEventBus(sb)
    try:
        number = await bus.schedule(
            "scheduled.work",
            _work(_unique_id("sent")),
            datetime.now(UTC) + timedelta(seconds=1),
        )
        delivered = await _receive_one("scheduled.work", timedelta(seconds=5))
        assert delivered is not None
        await bus.cancel("scheduled.work", number)
    finally:
        await bus.close()
        await sb.close()


async def test_cancelling_another_queues_number_is_a_no_op_and_leaves_the_message() -> None:
    sb = client()
    bus = ServiceBusEventBus(sb)
    try:
        local = _unique_id("elsewhere")
        number = await bus.schedule(
            "scheduled.work", _work(local), datetime.now(UTC) + timedelta(seconds=2)
        )
        await bus.cancel("inbound.receipts", number)
        received = await _receive_one("scheduled.work", timedelta(seconds=6))
        assert received is not None
        assert received.message_id == f"{TENANT_A}:{local}"
    finally:
        await bus.close()
        await sb.close()


async def test_an_enqueued_message_arrives_at_once_with_its_id_and_tenant_property() -> None:
    # I07: the webhook sends to inbound.replies now, not at a time, and the message carries the
    # tenant as the application property `tenantId` (DEC-130 item 7).
    sb = client()
    bus = ServiceBusEventBus(sb)
    local = _unique_id("enqueued")
    try:
        await bus.enqueue(
            "inbound.replies",
            BusMessage(
                id=local,
                topic="inbound.replies",
                event_type="SmsReceived",
                payload={"provider_message_id": "SM1"},
                tenant_id=TENANT_A,
            ),
        )
        received = await _receive_one("inbound.replies", timedelta(seconds=10))
        assert received is not None
        assert received.message_id == f"{TENANT_A}:{local}"
        assert received.subject == "SmsReceived"
        assert received.application_properties is not None
        assert received.application_properties[b"tenantId"] == TENANT_A.encode()
    finally:
        await bus.close()
        await sb.close()
