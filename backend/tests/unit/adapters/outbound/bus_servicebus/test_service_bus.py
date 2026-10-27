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
    assert json.loads(bytes(sent.body)) == {"measure": 4}


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


def test_a_cancel_of_a_number_that_is_not_pending_is_recognised() -> None:
    error = ServiceBusError(
        "Service request failed. b'The scheduled message with SequenceNumber = 999999 "
        "is already being cancelled.'"
    )
    assert is_unscheduled_cancel(error)


def test_any_other_cancel_error_is_not_swallowed() -> None:
    assert not is_unscheduled_cancel(ServiceBusError("Service request failed. Unauthorized"))
