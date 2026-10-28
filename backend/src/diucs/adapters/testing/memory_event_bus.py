"""Fake of Azure Service Bus with a manual clock (external provider only; DEC-004).

Times are compared as UTC instants. A naive time is refused, so a wall-clock comparison cannot
happen by accident on the London change days (lessons L4 and L52). Sequence numbers start at 1
and are never reused. A delivered or cancelled message is removed, so cancelling it does nothing.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.event_bus import QUEUES, TOPICS, BusMessage
from diucs.domain.errors import ValidationFailed

_SESSIONED_TOPICS = frozenset({"capacity.events"})


@dataclass(slots=True)
class _Pending:
    sequence_number: int
    queue: str
    message: BusMessage
    enqueue_at: datetime


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must be a timezone-aware datetime")
    return value.astimezone(UTC)


class ManualEventBus:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._published: list[BusMessage] = []
        self._pending: list[_Pending] = []
        self._enqueued: list[tuple[str, BusMessage]] = []
        self._next_number = 1

    @property
    def published(self) -> list[BusMessage]:
        return list(self._published)

    def published_to(self, topic: str) -> list[BusMessage]:
        return [message for message in self._published if message.topic == topic]

    async def publish(self, message: BusMessage) -> None:
        if message.topic not in TOPICS:
            raise ValidationFailed("topic", "not a known topic")
        if message.topic in _SESSIONED_TOPICS and message.session_id is None:
            raise ValidationFailed("session_id", "capacity events carry the service id")
        self._published.append(message)

    async def enqueue(self, queue: str, message: BusMessage) -> None:
        if queue not in QUEUES:
            raise ValidationFailed("queue", "not a known queue")
        self._enqueued.append((queue, message))

    def enqueued_to(self, queue: str) -> list[BusMessage]:
        """What was enqueued to a queue and not yet taken, oldest first. For tests: the port has
        no such call."""
        return [message for name, message in self._enqueued if name == queue]

    def take_enqueued(self) -> list[tuple[str, BusMessage]]:
        """Remove and return every enqueued message with its queue, oldest first, as a receiver
        would take them."""
        taken = list(self._enqueued)
        self._enqueued.clear()
        return taken

    async def schedule(self, queue: str, message: BusMessage, enqueue_at: datetime) -> int:
        if queue not in QUEUES:
            raise ValidationFailed("queue", "not a known queue")
        due = _aware_utc(enqueue_at, "enqueue_at")
        number = self._next_number
        self._next_number += 1
        self._pending.append(_Pending(number, queue, message, due))
        return number

    async def cancel(self, queue: str, sequence_number: int) -> None:
        self._pending = [
            item
            for item in self._pending
            if not (item.queue == queue and item.sequence_number == sequence_number)
        ]

    def due(self, now: datetime | None = None) -> list[tuple[str, BusMessage]]:
        instant = _aware_utc(self._clock.now() if now is None else now, "now")
        ready = sorted(
            (item for item in self._pending if item.enqueue_at <= instant),
            key=lambda item: (item.enqueue_at, item.sequence_number),
        )
        delivered = {id(item) for item in ready}
        self._pending = [item for item in self._pending if id(item) not in delivered]
        return [(item.queue, item.message) for item in ready]
