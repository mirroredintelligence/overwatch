"""Pure tests of the Service Bus adapter (I02): message mapping and refusals made before any
network call, so they run without Docker."""

import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.exceptions import ServiceBusError

from diucs.adapters.outbound.bus_servicebus.service_bus import (
    ServiceBusEventBus,
    is_unscheduled_cancel,
    to_service_bus_message,
)
from diucs.application.ports.outbound.event_bus import (
    REASON_TENANT_MISSING,
    BusMessage,
    MessageTenantError,
    from_wire,
)
from diucs.application.tenancy import ScopeId, bind_scope, bind_tenant
from diucs.domain.errors import ValidationFailed
from tests.support.servicebus import EMULATOR_CONNECTION


def _capacity(payload: dict[str, object] | None = None) -> BusMessage:
    return BusMessage(
        id="cap-1",
        topic="capacity.events",
        event_type="CapacityReported",
        payload=payload if payload is not None else {"measure": 4},
        session_id="svc-1",
        tenant_id="tenant-a",
    )


def test_the_message_carries_its_id_session_subject_and_json_body() -> None:
    sent = to_service_bus_message(_capacity({"measure": 4}))
    assert sent.message_id == "tenant-a:cap-1"
    assert sent.session_id == "tenant-a:svc-1"
    assert sent.subject == "CapacityReported"
    assert sent.content_type == "application/json"
    # The SDK holds a sent body as a generator of chunks, so it is joined, not converted.
    assert json.loads(b"".join(sent.body)) == {"measure": 4}


def test_the_event_type_is_an_application_property() -> None:
    sent = to_service_bus_message(_capacity())
    assert sent.application_properties == {
        "event_type": "CapacityReported",
        "tenantId": "tenant-a",
    }


def test_a_channel_in_the_payload_becomes_an_application_property() -> None:
    sent = to_service_bus_message(_capacity({"channel": "text", "measure": 4}))
    assert sent.application_properties == {
        "event_type": "CapacityReported",
        "tenantId": "tenant-a",
        "channel": "text",
    }


def test_a_message_without_a_session_has_no_session_id() -> None:
    sent = to_service_bus_message(
        BusMessage(
            id="m-1", topic="messages.outbound", event_type="PromptDue", tenant_id="tenant-a"
        )
    )
    assert sent.session_id is None


def test_a_tenant_becomes_the_tenant_id_application_property() -> None:
    sent = to_service_bus_message(
        BusMessage(
            id="m-1", topic="inbound.replies", event_type="SmsReceived", tenant_id="tenant-a"
        )
    )
    assert sent.application_properties == {"event_type": "SmsReceived", "tenantId": "tenant-a"}


@pytest.mark.parametrize("name", ["not.a.queue", "capacity.events"])
async def test_enqueueing_to_an_unknown_queue_or_a_topic_is_refused_before_any_send(
    name: str,
) -> None:
    client: ServiceBusClient = ServiceBusClient.from_connection_string(EMULATOR_CONNECTION)
    try:
        bus = ServiceBusEventBus(client)
        with pytest.raises(ValidationFailed, match="queue"):
            await bus.enqueue(name, _capacity())
    finally:
        await client.close()


async def test_publishing_to_an_unknown_topic_is_refused_before_any_send() -> None:
    client: ServiceBusClient = ServiceBusClient.from_connection_string(EMULATOR_CONNECTION)
    try:
        bus = ServiceBusEventBus(client)
        with pytest.raises(ValidationFailed, match="topic"):
            await bus.publish(
                BusMessage(
                    id="x-1", topic="no.such.topic", event_type="Anything", tenant_id="tenant-a"
                )
            )
    finally:
        await client.close()


async def test_scheduling_at_a_naive_time_is_refused_before_any_send() -> None:
    client: ServiceBusClient = ServiceBusClient.from_connection_string(EMULATOR_CONNECTION)
    try:
        bus = ServiceBusEventBus(client)
        naive = datetime(2026, 10, 25, 12, 0)
        with pytest.raises(ValidationFailed, match="enqueue_at"):
            await bus.schedule("scheduled.work", _capacity(), naive)
    finally:
        await client.close()


EMULATOR_NOT_PENDING_TEXT = (
    "Service request failed. b'The scheduled message with SequenceNumber = 999999 "
    "is already being cancelled. TrackingId:abc_G0, Timestamp:2026-10-27T17:19:32'. "
    "Error condition: amqp:not-allowed. Status Code: 400."
)


def test_a_cancel_of_a_number_that_is_not_pending_is_recognised() -> None:
    assert is_unscheduled_cancel(ServiceBusError(EMULATOR_NOT_PENDING_TEXT), 999_999)


def test_a_refusal_that_names_another_number_is_not_recognised() -> None:
    assert not is_unscheduled_cancel(ServiceBusError(EMULATOR_NOT_PENDING_TEXT), 7)


def test_any_other_cancel_error_is_not_swallowed() -> None:
    error = ServiceBusError("Service request failed. Unauthorized")
    assert not is_unscheduled_cancel(error, 999_999)


class _RefusalSubclass(ServiceBusError):
    """The emulator refusal text, from a subclass: a different failure (DEC-102 item 2)."""


def test_a_subclass_with_the_refusal_text_is_not_recognised() -> None:
    error = _RefusalSubclass(EMULATOR_NOT_PENDING_TEXT)
    assert not is_unscheduled_cancel(error, 999_999)


async def test_a_subclass_with_the_refusal_text_is_raised_from_cancel() -> None:
    sender = _FakeSender(refusal=_RefusalSubclass(EMULATOR_NOT_PENDING_TEXT))
    bus = ServiceBusEventBus(_FakeClient(sender))  # type: ignore[arg-type]
    with pytest.raises(_RefusalSubclass):
        await bus.cancel("scheduled.work", 999_999)


class _FakeSender:
    """A stand-in for the SDK sender (an external provider): records a cancel, or raises."""

    def __init__(self, refusal: ServiceBusError | None = None) -> None:
        self.refusal = refusal
        self.cancelled: list[int] = []

    async def cancel_scheduled_messages(self, sequence_number: int) -> None:
        if self.refusal is not None:
            raise self.refusal
        self.cancelled.append(sequence_number)

    async def close(self) -> None:
        return None


class _FakeClient:
    def __init__(self, sender: _FakeSender) -> None:
        self.sender = sender

    def get_queue_sender(self, name: str) -> _FakeSender:
        return self.sender


async def test_a_cancel_of_a_pending_number_is_sent_to_the_queue() -> None:
    sender = _FakeSender()
    bus = ServiceBusEventBus(_FakeClient(sender))  # type: ignore[arg-type]
    await bus.cancel("scheduled.work", 42)
    assert sender.cancelled == [42]


async def test_a_cancel_refused_as_not_pending_is_a_no_op() -> None:
    sender = _FakeSender(ServiceBusError(EMULATOR_NOT_PENDING_TEXT))
    bus = ServiceBusEventBus(_FakeClient(sender))  # type: ignore[arg-type]
    await bus.cancel("scheduled.work", 999_999)


async def test_a_refusal_naming_another_number_propagates() -> None:
    sender = _FakeSender(ServiceBusError(EMULATOR_NOT_PENDING_TEXT))
    bus = ServiceBusEventBus(_FakeClient(sender))  # type: ignore[arg-type]
    with pytest.raises(ServiceBusError):
        await bus.cancel("scheduled.work", 7)


async def test_an_unrelated_service_bus_error_still_propagates_from_cancel() -> None:
    sender = _FakeSender(ServiceBusError("Service request failed. Unauthorized"))
    bus = ServiceBusEventBus(_FakeClient(sender))  # type: ignore[arg-type]
    with pytest.raises(ServiceBusError, match="Unauthorized"):
        await bus.cancel("scheduled.work", 999_999)


# ---------------------------------------------------------------- TEN-020: the tenant on the wire


class _SendingSender:
    """A stand-in for the SDK sender that records what it was asked to send (an external
    provider)."""

    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.scheduled: list[tuple[Any, datetime]] = []

    async def send_messages(self, message: Any) -> None:
        self.sent.append(message)

    async def schedule_messages(self, message: Any, at: datetime) -> list[int]:
        self.scheduled.append((message, at))
        return [7]

    async def close(self) -> None:
        return None


class _SendingClient:
    def __init__(self) -> None:
        self.sender = _SendingSender()

    def get_queue_sender(self, name: str) -> _SendingSender:
        return self.sender

    def get_topic_sender(self, name: str) -> _SendingSender:
        return self.sender


def _bus() -> tuple[ServiceBusEventBus, _SendingSender]:
    client = _SendingClient()
    return ServiceBusEventBus(client), client.sender  # type: ignore[arg-type]


def test_a_payload_value_reaches_the_body_and_nothing_else() -> None:
    canary = "CANARY-token-123"
    sent = to_service_bus_message(
        BusMessage(
            id="m-1",
            topic="messages.outbound",
            event_type="SendMessage",
            payload={"note": canary},
            session_id="svc-1",
            tenant_id="tenant-a",
        )
    )

    assert canary in b"".join(sent.body).decode()
    assert canary not in str(sent.subject)
    assert canary not in str(sent.message_id)
    assert canary not in str(sent.session_id)
    assert canary not in repr(sent.application_properties)


async def test_no_log_line_while_publishing_holds_a_payload_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = "CANARY-token-123"
    bus, _ = _bus()

    with caplog.at_level(logging.DEBUG):
        await bus.publish(
            BusMessage(
                id="m-1",
                topic="messages.outbound",
                event_type="SendMessage",
                payload={"note": canary},
                tenant_id="tenant-a",
            )
        )

    assert canary not in " ".join(record.getMessage() for record in caplog.records)


def _message(**changes: Any) -> BusMessage:
    fields: dict[str, Any] = {
        "id": "m-1",
        "topic": "messages.outbound",
        "event_type": "SendMessage",
        "tenant_id": "tenant-a",
    }
    fields.update(changes)
    return BusMessage(**fields)


_LATER = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


async def _publish(bus: ServiceBusEventBus, message: BusMessage) -> None:
    await bus.publish(message)


async def _enqueue(bus: ServiceBusEventBus, message: BusMessage) -> None:
    await bus.enqueue("inbound.replies", message)


async def _schedule(bus: ServiceBusEventBus, message: BusMessage) -> None:
    await bus.schedule("scheduled.work", message, _LATER)


_SENDS = [
    pytest.param(_publish, id="publish"),
    pytest.param(_enqueue, id="enqueue"),
    pytest.param(_schedule, id="schedule"),
]


@pytest.mark.parametrize("send", _SENDS)
async def test_a_send_refuses_a_bound_tenant_that_differs_before_calling_the_client(
    send: Any,
) -> None:
    bus, sender = _bus()

    with bind_tenant("tenant-b"), pytest.raises(ValidationFailed, match="tenant_id"):
        await send(bus, _message())

    assert sender.sent == [] and sender.scheduled == []


@pytest.mark.parametrize("send", _SENDS)
async def test_a_send_refuses_a_bound_network_scope_before_calling_the_client(send: Any) -> None:
    bus, sender = _bus()

    with bind_scope(ScopeId.network("net-region")), pytest.raises(ValidationFailed):
        await send(bus, _message())

    assert sender.sent == [] and sender.scheduled == []


@pytest.mark.parametrize("send", _SENDS)
async def test_a_send_refuses_an_over_long_id_before_calling_the_client(send: Any) -> None:
    bus, sender = _bus()

    with pytest.raises(ValidationFailed, match="id"):
        await send(bus, _message(id="x" * 120))

    assert sender.sent == [] and sender.scheduled == []


@pytest.mark.parametrize("send", _SENDS)
@pytest.mark.parametrize("key", ["link", "link_token", "token", "url"])
async def test_a_send_refuses_a_payload_with_a_live_link_before_calling_the_client(
    send: Any, key: str
) -> None:
    bus, sender = _bus()

    with pytest.raises(ValidationFailed, match="payload"):
        await send(bus, _message(payload={key: "https://example.test/x"}))

    assert sender.sent == [] and sender.scheduled == []


@pytest.mark.parametrize("send", _SENDS)
async def test_a_send_with_the_matching_bound_tenant_goes_through(send: Any) -> None:
    bus, sender = _bus()

    with bind_tenant("tenant-a"):
        await send(bus, _message(topic="messages.outbound"))

    assert len(sender.sent) + len(sender.scheduled) == 1


async def test_the_message_sent_is_the_one_to_service_bus_message_builds() -> None:
    bus, sender = _bus()

    await bus.publish(_message())

    (sent,) = sender.sent
    assert sent.message_id == "tenant-a:m-1"
    assert sent.application_properties["tenantId"] == "tenant-a"


async def test_a_naive_enqueue_time_is_still_refused_with_a_valid_message() -> None:
    bus, sender = _bus()

    with pytest.raises(ValidationFailed, match="enqueue_at"):
        await bus.schedule("scheduled.work", _message(), datetime(2026, 10, 25, 12, 0))

    assert sender.scheduled == []


def _received(**changes: Any) -> Any:
    fields: dict[str, Any] = {
        "message_id": "tenant-a:cap-1",
        "session_id": "tenant-a:svc-1",
        "subject": "CapacityReported",
        "application_properties": {"event_type": "CapacityReported", "tenantId": "tenant-a"},
        "body": iter([b'{"measure": 4}']),
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


@pytest.mark.parametrize(
    "properties",
    [
        {"event_type": "CapacityReported", "tenantId": "tenant-a"},
        {b"event_type": b"CapacityReported", b"tenantId": b"tenant-a"},
    ],
    ids=["text-keys", "bytes-keys"],
)
def test_a_received_message_is_read_back_through_from_wire(properties: Any) -> None:
    raw = _received(application_properties=properties)

    message = from_wire(
        "capacity.events",
        message_id=raw.message_id,
        session_id=raw.session_id,
        subject=raw.subject,
        properties=raw.application_properties,
        payload=json.loads(b"".join(raw.body)),
    )

    assert message == BusMessage(
        id="cap-1",
        topic="capacity.events",
        event_type="CapacityReported",
        payload={"measure": 4},
        session_id="svc-1",
        tenant_id="tenant-a",
    )


def test_a_received_message_with_no_tenant_property_is_tenant_missing() -> None:
    raw = _received(application_properties={"event_type": "CapacityReported"})

    with pytest.raises(MessageTenantError) as refused:
        from_wire(
            "capacity.events",
            message_id=raw.message_id,
            session_id=raw.session_id,
            subject=raw.subject,
            properties=raw.application_properties,
            payload={},
        )

    assert refused.value.reason == REASON_TENANT_MISSING


def test_what_the_adapter_builds_is_what_from_wire_accepts() -> None:
    sent = to_service_bus_message(_capacity({"measure": 4}))

    message = from_wire(
        "capacity.events",
        message_id=sent.message_id,
        session_id=sent.session_id,
        subject=sent.subject,
        properties=sent.application_properties,
        payload=json.loads(b"".join(sent.body)),
    )

    assert message == _capacity({"measure": 4})
