"""Neo4j store for protected contacts (P16). Stub for the red commit (DEC-010): no behaviour yet."""

from neo4j import AsyncManagedTransaction


class Neo4jContactStore:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def put_phone(self, role_id: str, number: str) -> None:
        raise NotImplementedError

    async def get_phone(self, role_id: str) -> str | None:
        raise NotImplementedError

    async def put_email(self, role_id: str, email: str) -> None:
        raise NotImplementedError

    async def get_email(self, role_id: str) -> str | None:
        raise NotImplementedError
