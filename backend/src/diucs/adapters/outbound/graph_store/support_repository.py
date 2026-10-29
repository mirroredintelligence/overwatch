"""Neo4j store for support access (O06). Stub for the red commit."""

from typing import Any

from neo4j import AsyncManagedTransaction


class Neo4jSupportRepository:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def ensure_session(
        self, session_id: str, device_type: str, app_mode: str, release: str, started_at: Any
    ) -> None:
        raise NotImplementedError
