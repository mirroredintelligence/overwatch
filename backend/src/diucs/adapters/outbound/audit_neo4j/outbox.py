"""Neo4j outbox (P06, DEC-012, DEC-001). Messages are platform nodes written by named queries.

Layout: (:OutboxMessage {id, topic, eventType, status, attempts, createdAt, publishedAt, sessionId,
lastError}), with the payload as typed properties (payload_<name>) and the null keys listed in
payloadNulls. No JSON text is stored (DEC-001). id is unique (migration 0028).
"""

from datetime import datetime

from neo4j import AsyncManagedTransaction

from diucs.application.ports.outbound.outbox import OutboxMessage


class Neo4jOutbox:
    """The outbox on the caller's transaction. Constructed by the unit of work."""

    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def add(self, message: OutboxMessage) -> None:
        raise NotImplementedError("Neo4jOutbox.add is not built yet (P06)")

    async def pending(self, limit: int = 100) -> list[OutboxMessage]:
        raise NotImplementedError("Neo4jOutbox.pending is not built yet (P06)")

    async def mark_published(self, id: str, at: datetime) -> None:
        raise NotImplementedError("Neo4jOutbox.mark_published is not built yet (P06)")

    async def mark_failed(self, id: str, error: str) -> None:
        raise NotImplementedError("Neo4jOutbox.mark_failed is not built yet (P06)")
