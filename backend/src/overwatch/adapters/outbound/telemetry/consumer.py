"""The consumer span for a bus message (O01).

The handling of a message runs under a span named `servicebus.process {topic}`. The span is a child
of the span that sent the message, read from the message's traceparent, so a trace runs from a
request through the bus to the worker. A missing, malformed or all-zero traceparent starts a root
span; it never fails the message.
"""

import re
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Final

from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from diucs.adapters.outbound.telemetry import attributes as names
from diucs.application.ports.outbound.event_bus import BusMessage

Observe = Callable[[BusMessage], AbstractContextManager[object]]

_TRACEPARENT: Final = re.compile(r"00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})")


def parent_context(traceparent: str | None) -> otel_context.Context | None:
    """The context a span from this traceparent is a child of, or None when there is none."""
    if traceparent is None:
        return None
    match = _TRACEPARENT.fullmatch(traceparent)
    if match is None:
        return None
    trace_id = int(match.group(1), 16)
    span_id = int(match.group(2), 16)
    if trace_id == 0 or span_id == 0:
        return None
    remote = SpanContext(
        trace_id=trace_id,
        span_id=span_id,
        is_remote=True,
        trace_flags=TraceFlags(int(match.group(3), 16)),
    )
    return otel_trace.set_span_in_context(NonRecordingSpan(remote))


def consumer_observer(tracer: otel_trace.Tracer) -> Observe:
    """The trace hook of TenantBoundConsumer: each message is handled inside its own span."""

    @contextmanager
    def observe(message: BusMessage) -> Iterator[None]:
        attributes = {
            names.MESSAGING_SYSTEM: names.SERVICEBUS_SYSTEM,
            names.MESSAGING_DESTINATION_NAME: message.topic,
            names.MESSAGING_MESSAGE_ID: message.id,
        }
        with tracer.start_as_current_span(
            names.SPAN_SERVICEBUS_PROCESS.format(topic=message.topic),
            context=parent_context(message.traceparent),
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ):
            yield

    return observe
