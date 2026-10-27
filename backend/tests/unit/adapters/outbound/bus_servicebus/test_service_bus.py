"""Pure tests of the Service Bus adapter (I02): message mapping and refusals made before any
network call, so they run without Docker."""

import json
from datetime import datetime

import pytest
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.exceptions import ServiceBusError

from diucs.adapters.outbound.bus_servicebus.service_bus import (
    ServiceBusEventBus,
    is_unscheduled_cancel,
    to_service_bus_message,
)
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.domain.errors import ValidationFailed
from tests.support.servicebus import EMULATOR_CONNECTION


def _capacity(payload: dict[str, object] | None = None) -> BusMessage:
    return BusMessage(
        id="cap-1",
        topic="capacity.events",
        event_type="CapacityReported",
        payload=payload if payload is not None else {"measure": 4},
        session_id="svc-1",
    )


def test_the_message_carries_its_id_session_subject_and_json_body() -> None:
    sent = to_service_bus_message(_capacity({"measure": 4}))
    assert sent.message_id == "cap-1"
    assert sent.session_id == "svc-1"
    assert sent.subject == "CapacityReported"
    assert sent.content_type == "application/json"
    # The SDK holds a sent body as a generator of chunks, so it is joined, not converted.
    assert json.loads(b"".join(sent.body)) == {"measure": 4}


def test_the_event_type_is_an_application_property() -> None:
    sent = to_service_bus_message(_capacity())
    assert sent.application_properties == {"event_type": "CapacityReported"}


def test_a_channel_in_the_payload_becomes_an_application_property() -> None:
    sent = to_service_bus_message(_capacity({"channel": "text", "measure": 4}))
    assert sent.application_properties == {"event_type": "CapacityReported", "channel": "text"}


def test_a_message_without_a_session_has_no_session_id() -> None:
    sent = to_service_bus_message(
        BusMessage(id="m-1", topic="messages.outbound", event_type="PromptDue")
    )
    assert sent.session_id is None


async def test_publishing_to_an_unknown_topic_is_refused_before_any_send() -> None:
    client: ServiceBusClient = ServiceBusClient.from_connection_string(EMULATOR_CONNECTION)
    try:
        bus = ServiceBusEventBus(client)
        with pytest.raises(ValidationFailed, match="topic"):
            await bus.publish(BusMessage(id="x-1", topic="no.such.topic", event_type="Anything"))
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
