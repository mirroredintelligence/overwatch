"""Neo4j idempotency store and processed-message markers (P15, DEC-012, DEC-089).

Stub for the red commit (DEC-010): the behaviour is not written yet.
"""

from neo4j import AsyncDriver, AsyncManagedTransaction


class Neo4jIdempotencyStore:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def get(self, key: str) -> object | None:
        raise NotImplementedError

    async def put(self, key: str, result: object) -> None:
        raise NotImplementedError


class Neo4jProcessedMessages:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def mark_if_new(self, message_id: str, consumer: str) -> bool:
        raise NotImplementedError


class DriverIdempotencyStore:
    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    async def get(self, key: str) -> object | None:
        raise NotImplementedError

    async def put(self, key: str, result: object) -> None:
        raise NotImplementedError
