"""Outbound port: the message bus and its scheduler, and the ScheduledWork records (P08).

Topic and queue names are the ones in docs/spec/architecture.md. The Azure Service Bus adapter
(I02) and the in-memory fake with a manual clock (adapters/testing/memory_event_bus.py) both
implement EventBus. A use case never calls schedule or cancel: it writes a ScheduledWork row, and
the outbox relay (I03) makes the bus call.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from diucs.application.work import ScheduledWork, WorkKind

QUEUES: frozenset[str] = frozenset({"inbound.replies", "inbound.receipts", "scheduled.work"})
TOPICS: frozenset[str] = frozenset(
    {
        "capacity.events",
        "booking.events",
        "registration.events",
        "criteria.events",
        "alerts.events",
        "messages.outbound",
    }
)


@dataclass(frozen=True, slots=True)
class BusMessage:
    id: str
    topic: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    # The scope the message belongs to (DEC-130 item 7). The adapter sends it as the Service Bus
    # application property `tenantId`; a consumer binds it before it opens a unit of work. None
    # until every producer sets it (the outbound-adapters bundle makes it mandatory).
    tenant_id: str | None = None
    # The W3C trace context of the span that sent the message (O01). The publisher stamps it; the
    # adapter sends it as the `traceparent` application property; a consumer opens its span under
    # it. None when there is no trace.
    traceparent: str | None = None


class EventBus(Protocol):
    async def publish(self, message: BusMessage) -> None:
        """Send to a topic. Refuses an unknown topic (ValidationFailed)."""
        ...

    async def enqueue(self, queue: str, message: BusMessage) -> None:
        """Send to a queue now, so it can be received at once (I07). Refuses a name that is not
        a queue (ValidationFailed): a topic takes publish, a later time takes schedule."""
        ...

    async def schedule(self, queue: str, message: BusMessage, enqueue_at: datetime) -> int:
        """Enqueue at a UTC instant and return the sequence number. Refuses an unknown queue."""
        ...

    async def cancel(self, queue: str, sequence_number: int) -> None:
        """Cancel a scheduled message. An unknown or already delivered number does nothing."""
        ...


class ScheduledWorkRepository(Protocol):
    async def add(self, work: ScheduledWork) -> None: ...

    async def get(self, id: str) -> ScheduledWork: ...

    async def for_about(
        self, about_id: str, kind: WorkKind | None = None
    ) -> list[ScheduledWork]: ...

    async def save(self, work: ScheduledWork) -> None: ...
