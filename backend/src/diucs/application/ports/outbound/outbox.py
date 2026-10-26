"""The outbox port (P06, DEC-012, DEC-001).

A use case writes its change, its audit entry and its outgoing messages in one unit of work. The
messages are stored as OutboxMessage nodes in the same Neo4j transaction, and a relay (I03)
publishes them later. A crash can delay a message but never lose or duplicate one: delivery is at
least once, and consumers dedupe by message id (P15).

The payload is the event's to_payload() output. Stored graph-native (DEC-001): no JSON text.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from diucs.domain.errors import ValidationFailed
from diucs.domain.events import DomainEvent, session_id_for, topic_for

MAX_ATTEMPTS = 10
PENDING = "pending"
PUBLISHED = "published"
DEAD = "dead"
OUTBOX_STATUSES = frozenset({PENDING, PUBLISHED, DEAD})


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    id: str
    topic: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    status: str = PENDING
    attempts: int = 0
    session_id: str | None = None

    def __post_init__(self) -> None:
        if self.created_at.utcoffset() != timedelta(0):
            raise ValidationFailed("created_at", "must be a timezone-aware UTC datetime")
        if self.status not in OUTBOX_STATUSES:
            raise ValidationFailed("status", "must be pending, published or dead")
        if self.attempts < 0:
            raise ValidationFailed("attempts", "cannot be negative")


def outbox_message_for(event: DomainEvent, id: str, now: datetime) -> OutboxMessage:
    """The outbox message for one domain event: topic and session from the event, payload from
    to_payload(), status pending and no attempts."""
    return OutboxMessage(
        id=id,
        topic=topic_for(event),
        event_type=event.event_type,
        payload=event.to_payload(),
        created_at=now,
        session_id=session_id_for(event),
    )


class Outbox(Protocol):
    async def add(self, message: OutboxMessage) -> None:
        """Store a pending message. A message id that is already stored is refused (Conflict)."""
        ...

    async def pending(self, limit: int = 100) -> list[OutboxMessage]:
        """Up to limit pending messages, oldest first."""
        ...

    async def mark_published(self, id: str, at: datetime) -> None:
        """Set the message published at this instant. It leaves the pending list."""
        ...

    async def mark_failed(self, id: str, error: str) -> None:
        """Count one failed attempt and keep the error text. At MAX_ATTEMPTS the message is dead."""
        ...
