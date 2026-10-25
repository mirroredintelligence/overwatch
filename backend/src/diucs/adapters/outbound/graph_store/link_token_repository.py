"""Neo4j store for link tokens (P10, DEC-004). Only the token hash is stored, never the token.

Stub for the red commit (DEC-010): every method raises NotImplementedError until the green commit.
"""

from datetime import datetime

from neo4j import AsyncManagedTransaction

from diucs.domain.rules.tokens import LinkTokenRecord


class Neo4jLinkTokenRepository:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def add(self, record: LinkTokenRecord) -> None:
        raise NotImplementedError

    async def get_by_hash(self, token_hash: str) -> LinkTokenRecord | None:
        raise NotImplementedError

    async def mark_used(self, token_hash: str, at: datetime) -> bool:
        raise NotImplementedError
