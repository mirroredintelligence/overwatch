"""Azure Service Bus adapter for the event bus port (I02, DEC-003, DEC-102).

Topics take publish. Queues take enqueue, schedule and cancel. The wire form of a message is
`to_wire` (the port module): the message id and the session id are qualified with the tenant
(`<tenant>:<local id>`), the event type is the subject and an application property, and the tenant
is the application property `tenantId` (TEN-020, DEC-130 item 7). `to_service_bus_message` is the
only place that writes it. A send is refused before the first network call if the message is for
another tenant than the bound one, is too long once qualified, or carries a live link or token.
Nothing from the body is copied into a property or a log line. A cancel is a no-op for a number
that is not pending (DEC-102 item 2).
"""

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from azure.servicebus import ServiceBusMessage
from azure.servicebus.aio import ServiceBusClient, ServiceBusSender
from azure.servicebus.exceptions import ServiceBusError
from opentelemetry import trace as otel_trace

from diucs.application.ports.outbound.event_bus import (
    QUEUES,
    TOPICS,
    BusMessage,
    check_publishable,
    to_wire,
)
from diucs.application.tracing import format_traceparent
from diucs.domain.errors import ValidationFailed

# DEC-102 item 2: the emulator refuses a cancel of a number that is unknown, already delivered or
# held by another queue, with this text. The number it names must be the one asked for.
_NOT_PENDING = re.compile(r"SequenceNumber = (\d+) is already being cancelled")


def stamped_with_current_span(message: BusMessage) -> BusMessage:
    """A message sent from inside a span carries that span's traceparent (O01), unless it already
    has one. Outside any span it is returned unchanged."""
    if message.traceparent is not None:
        return message
    current = otel_trace.get_current_span().get_span_context()
    if not current.is_valid:
        return message
    return replace(
        message,
        traceparent=format_traceparent(current.trace_id, current.span_id, int(current.trace_flags)),
    )


def to_service_bus_message(message: BusMessage) -> ServiceBusMessage:
    wire = to_wire(message)
    return ServiceBusMessage(
        body=json.dumps(message.payload).encode("utf-8"),
        message_id=wire.message_id,
        session_id=wire.session_id,
        subject=wire.subject,
        application_properties=cast(
            "dict[str | bytes, int | float | bytes | bool | str | UUID]",
            dict(wire.application_properties),
        ),
        content_type="application/json",
    )


def is_unscheduled_cancel(error: ServiceBusError, sequence_number: int) -> bool:
    """True only for the emulator's refusal of this exact number. The SDK gives no typed reason
    for it, so the check is the base class (a subclass is a different failure and is raised), the
    fixed text and the number. Anything else is not this case (DEC-102 item 2)."""
    if type(error) is not ServiceBusError:
        return False
    found = _NOT_PENDING.search(str(error))
    return found is not None and int(found.group(1)) == sequence_number


class ServiceBusEventBus:
    def __init__(self, client: ServiceBusClient) -> None:
        self._client = client
        self._senders: dict[str, ServiceBusSender] = {}

    def _sender(self, name: str) -> ServiceBusSender:
        sender = self._senders.get(name)
        if sender is None:
            if name in QUEUES:
                sender = self._client.get_queue_sender(name)
            else:
                sender = self._client.get_topic_sender(name)
            self._senders[name] = sender
        return sender

    async def publish(self, message: BusMessage) -> None:
        if message.topic not in TOPICS:
            raise ValidationFailed("topic", "not a known topic")
        check_publishable(message)
        await self._sender(message.topic).send_messages(
            to_service_bus_message(stamped_with_current_span(message))
        )

    async def enqueue(self, queue: str, message: BusMessage) -> None:
        if queue not in QUEUES:
            raise ValidationFailed("queue", "not a known queue")
        check_publishable(message)
        await self._sender(queue).send_messages(
            to_service_bus_message(stamped_with_current_span(message))
        )

    async def schedule(self, queue: str, message: BusMessage, enqueue_at: datetime) -> int:
        if queue not in QUEUES:
            raise ValidationFailed("queue", "not a known queue")
        if enqueue_at.tzinfo is None or enqueue_at.utcoffset() is None:
            raise ValidationFailed("enqueue_at", "must be a timezone-aware datetime")
        check_publishable(message)
        numbers = await self._sender(queue).schedule_messages(
            to_service_bus_message(stamped_with_current_span(message)), enqueue_at.astimezone(UTC)
        )
        return numbers[0]

    async def cancel(self, queue: str, sequence_number: int) -> None:
        if queue not in QUEUES:
            raise ValidationFailed("queue", "not a known queue")
        try:
            await self._sender(queue).cancel_scheduled_messages(sequence_number)
        except ServiceBusError as error:
            if not is_unscheduled_cancel(error, sequence_number):
                raise

    async def close(self) -> None:
        senders = list(self._senders.values())
        self._senders.clear()
        for sender in senders:
            await sender.close()
