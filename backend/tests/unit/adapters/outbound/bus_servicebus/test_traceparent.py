"""Trace context over the bus (O01). The publisher stamps the traceparent of the span that sends
the message, and the adapter carries it as the `traceparent` application property. No network:
a recording sender stands in for the Service Bus sender."""

from typing import Any

from opentelemetry.sdk.trace import TracerProvider

from diucs.adapters.outbound.bus_servicebus.service_bus import (
    ServiceBusEventBus,
    to_service_bus_message,
)
from diucs.application.ports.outbound.event_bus import BusMessage

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


class _RecordingSender:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send_messages(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self.sent.append(message)


class _RecordingBus(ServiceBusEventBus):
    def __init__(self) -> None:
        super().__init__(client=None)  # type: ignore[arg-type]
        self.sender = _RecordingSender()

    def _sender(self, name: str) -> Any:
        return self.sender


def _message(**overrides: Any) -> BusMessage:
    fields: dict[str, Any] = {
        "id": "cap-1",
        "topic": "capacity.events",
        "event_type": "CapacityReported",
        "tenant_id": "tenant-a",
    }
    fields.update(overrides)
    return BusMessage(**fields)


def test_a_traceparent_becomes_an_application_property() -> None:
    sent = to_service_bus_message(_message(traceparent=TRACEPARENT))

    assert sent.application_properties is not None
    assert sent.application_properties["traceparent"] == TRACEPARENT


def test_a_message_without_a_traceparent_has_no_such_property() -> None:
    sent = to_service_bus_message(_message())

    assert "traceparent" not in (sent.application_properties or {})


async def test_publish_stamps_the_span_that_sends_the_message() -> None:
    provider = TracerProvider()
    tracer = provider.get_tracer("diucs-test")
    bus = _RecordingBus()

    with tracer.start_as_current_span("usecase.ReportCapacity") as span:
        await bus.publish(_message())
        context = span.get_span_context()

    expected = f"00-{context.trace_id:032x}-{context.span_id:016x}-{int(context.trace_flags):02x}"
    [sent] = bus.sender.sent
    assert sent.application_properties["traceparent"] == expected


async def test_publish_keeps_a_traceparent_the_message_already_has() -> None:
    provider = TracerProvider()
    bus = _RecordingBus()

    with provider.get_tracer("diucs-test").start_as_current_span("usecase.Relay"):
        await bus.publish(_message(traceparent=TRACEPARENT))

    [sent] = bus.sender.sent
    assert sent.application_properties["traceparent"] == TRACEPARENT


async def test_publish_outside_any_span_sends_no_traceparent() -> None:
    bus = _RecordingBus()

    await bus.publish(_message())

    [sent] = bus.sender.sent
    assert "traceparent" not in (sent.application_properties or {})
