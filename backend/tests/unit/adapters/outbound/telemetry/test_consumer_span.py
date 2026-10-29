"""The consumer span (O01): a bus message is handled under the span of the one that sent it."""

from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from diucs.adapters.outbound.telemetry.consumer import consumer_observer
from diucs.application.ports.outbound.event_bus import BusMessage

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT_SPAN_ID = "00f067aa0ba902b7"
TRACEPARENT = f"00-{TRACE_ID}-{PARENT_SPAN_ID}-01"


@pytest.fixture
def exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def provider(exporter: InMemorySpanExporter) -> Iterator[TracerProvider]:
    built = TracerProvider()
    built.add_span_processor(SimpleSpanProcessor(exporter))
    yield built
    built.shutdown()


def _message(traceparent: str | None) -> BusMessage:
    return BusMessage(
        id="m-1",
        topic="inbound.replies",
        event_type="SmsReceived",
        traceparent=traceparent,
    )


def _observe_once(provider: TracerProvider, message: BusMessage) -> None:
    observe: Any = consumer_observer(provider.get_tracer("diucs-test"))
    with observe(message):
        pass


def test_the_consumer_span_is_a_child_of_the_sending_span(
    provider: TracerProvider, exporter: InMemorySpanExporter
) -> None:
    _observe_once(provider, _message(TRACEPARENT))

    [span] = exporter.get_finished_spans()
    assert span.name == "servicebus.process inbound.replies"
    assert f"{span.context.trace_id:032x}" == TRACE_ID
    assert span.parent is not None
    assert f"{span.parent.span_id:016x}" == PARENT_SPAN_ID
    assert span.attributes["messaging.message.id"] == "m-1"
    assert span.attributes["messaging.destination.name"] == "inbound.replies"


def test_a_message_without_a_traceparent_starts_a_root_span(
    provider: TracerProvider, exporter: InMemorySpanExporter
) -> None:
    _observe_once(provider, _message(None))

    [span] = exporter.get_finished_spans()
    assert span.parent is None


@pytest.mark.parametrize(
    "traceparent",
    [
        "00-zz-00f067aa0ba902b7-01",
        "00-00000000000000000000000000000000-00f067aa0ba902b7-01",
        f"01-{TRACE_ID}-{PARENT_SPAN_ID}-01",
    ],
)
def test_a_malformed_or_invalid_traceparent_is_ignored(
    traceparent: str, provider: TracerProvider, exporter: InMemorySpanExporter
) -> None:
    _observe_once(provider, _message(traceparent))

    [span] = exporter.get_finished_spans()
    assert span.parent is None
