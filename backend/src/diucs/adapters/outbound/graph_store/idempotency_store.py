"""Neo4j idempotency store and processed-message markers (P15, DEC-012, DEC-090, DEC-001).

Stub for the red commit (DEC-010): constant returns only, no behaviour.
"""

from typing import Any

from neo4j import AsyncDriver, AsyncManagedTransaction

_STUB: Any = object()


class Neo4jIdempotencyStore:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def get(self, key: str) -> object | None:
        return _STUB

    async def put(self, key: str, result: object) -> None:
        return None


class Neo4jProcessedMessages:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def mark_if_new(self, message_id: str, consumer: str) -> bool:
        return False


class DriverIdempotencyStore:
    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    async def get(self, key: str) -> object | None:
        return _STUB

    async def put(self, key: str, result: object) -> None:
        return None
