"""Neo4j outbox (P06, DEC-012, DEC-001). Messages are platform nodes written by named queries.

Layout: (:OutboxMessage {id, topic, eventType, status, attempts, createdAt, publishedAt, sessionId,
lastError}). The payload is stored as typed properties, one per field, named payload_<field>, with
the fields that are null listed in payloadNulls (Neo4j stores no null property, lesson L74). A
payload text that is a canonical UTC instant is stored as a datetime and read back as the same text
(DEC-001: times are datetimes). No JSON text is stored. id is unique (migration 0028).
"""

import re
from datetime import UTC, datetime
from typing import Any, Literal

from neo4j import AsyncManagedTransaction
from neo4j.exceptions import ConstraintError
from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.application.ports.outbound.outbox import (
    DEAD,
    MAX_ATTEMPTS,
    PENDING,
    PUBLISHED,
    OutboxMessage,
)
from diucs.domain.errors import Conflict, NotFound, ValidationFailed

_PAYLOAD_PREFIX = "payload_"
_NULLS = "payloadNulls"
_FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
_CANONICAL_INSTANT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z"
)

_QUERIES: dict[str, tuple[str, Literal["read", "write"]]] = {
    "Q-OUTBOX-ADD": (
        "CREATE (m:OutboxMessage) SET m += $props RETURN count(m) AS written",
        "write",
    ),
    "Q-OUTBOX-PENDING": (
        "MATCH (m:OutboxMessage {status: 'pending'}) RETURN properties(m) AS props "
        "ORDER BY m.createdAt, m.id LIMIT $limit",
        "read",
    ),
    # Lock first (lesson L73): a self-SET takes the message's write lock, then the status is read.
    "Q-OUTBOX-LOCK": (
        "MATCH (m:OutboxMessage {id: $id}) SET m.id = m.id RETURN m.status AS status",
        "write",
    ),
    "Q-OUTBOX-PUBLISHED": (
        "MATCH (m:OutboxMessage {id: $id}) SET m.status = 'published', m.publishedAt = $at "
        "RETURN count(m) AS n",
        "write",
    ),
    "Q-OUTBOX-FAILED": (
        "MATCH (m:OutboxMessage {id: $id}) SET m.id = m.id "
        "WITH m SET m.attempts = m.attempts + 1, m.lastError = $error "
        "WITH m SET m.status = CASE WHEN m.status = 'pending' AND m.attempts >= $maxAttempts "
        "THEN 'dead' ELSE m.status END "
        "RETURN m.attempts AS attempts, m.status AS status",
        "write",
    ),
}

for _query_id, (_cypher, _mode) in _QUERIES.items():
    REGISTRY.register(NamedQuery(id=_query_id, cypher=_cypher, mode=_mode))


def _text_of(instant: datetime) -> str:
    return instant.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _instant_of_text(text: str) -> datetime | None:
    """The datetime a canonical UTC text stands for, or None when the text would not come back
    unchanged (so it stays text, and nothing is altered on the way out)."""
    if _CANONICAL_INSTANT.fullmatch(text) is None:
        return None
    instant = datetime.fromisoformat(text)
    return instant if _text_of(instant) == text else None


def _payload_properties(payload: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    nulls: list[str] = []
    for key, value in payload.items():
        if _FIELD.fullmatch(key) is None:
            raise ValidationFailed("payload", "has a field name that cannot be stored")
        if value is None:
            nulls.append(key)
        elif isinstance(value, str):
            instant = _instant_of_text(value)
            props[_PAYLOAD_PREFIX + key] = value if instant is None else instant
        elif isinstance(value, bool | int):
            props[_PAYLOAD_PREFIX + key] = value
        else:
            raise ValidationFailed("payload", "holds only text, whole numbers, flags and nothing")
    if nulls:
        props[_NULLS] = sorted(nulls)
    return props


def _payload_of(props: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for name, value in props.items():
        if name.startswith(_PAYLOAD_PREFIX):
            key = name[len(_PAYLOAD_PREFIX) :]
            payload[key] = _text_of(value.to_native()) if isinstance(value, DateTime) else value
    for key in props.get(_NULLS, []):
        payload[key] = None
    return payload


def _instant(value: Any) -> datetime:
    native: datetime = value.to_native()
    return native.astimezone(UTC)


def _message_of(props: dict[str, Any]) -> OutboxMessage:
    return OutboxMessage(
        id=str(props["id"]),
        topic=str(props["topic"]),
        event_type=str(props["eventType"]),
        payload=_payload_of(props),
        created_at=_instant(props["createdAt"]),
        status=str(props["status"]),
        attempts=int(props["attempts"]),
        session_id=props.get("sessionId"),
    )


class Neo4jOutbox:
    """The outbox on the caller's transaction. Built by the unit of work."""

    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def add(self, message: OutboxMessage) -> None:
        props: dict[str, Any] = {
            "id": message.id,
            "topic": message.topic,
            "eventType": message.event_type,
            "status": message.status,
            "attempts": message.attempts,
            "createdAt": message.created_at.astimezone(UTC),
            **_payload_properties(message.payload),
        }
        if message.session_id is not None:
            props["sessionId"] = message.session_id
        try:
            await run_query(self._tx, "Q-OUTBOX-ADD", props=props)
        except ConstraintError as error:
            raise Conflict("outbox message already exists") from error

    async def pending(self, limit: int = 100) -> list[OutboxMessage]:
        rows = await run_query(self._tx, "Q-OUTBOX-PENDING", limit=limit)
        return [_message_of(row["props"]) for row in rows]

    async def mark_published(self, id: str, at: datetime) -> None:
        rows = await run_query(self._tx, "Q-OUTBOX-LOCK", id=id)
        if not rows:
            raise NotFound(f"OutboxMessage/{id}")
        status = rows[0]["status"]
        if status == PUBLISHED:
            return
        if status == DEAD:
            raise Conflict("a dead outbox message cannot be published")
        if status != PENDING:
            raise ValidationFailed("status", "is not a known outbox status")
        await run_query(self._tx, "Q-OUTBOX-PUBLISHED", id=id, at=at.astimezone(UTC))

    async def mark_failed(self, id: str, error: str) -> None:
        rows = await run_query(
            self._tx, "Q-OUTBOX-FAILED", id=id, error=error, maxAttempts=MAX_ATTEMPTS
        )
        if not rows:
            raise NotFound(f"OutboxMessage/{id}")
