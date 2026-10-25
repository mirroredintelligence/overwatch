"""Neo4j communication records (P07). Stub for the red commit (DEC-010)."""

from collections.abc import Collection

from neo4j import AsyncManagedTransaction

from diucs.application.ports.outbound.messaging import Communication


class Neo4jCommunicationRepository:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        raise NotImplementedError

    async def add(self, communication: Communication) -> None:
        raise NotImplementedError

    async def get(self, communication_id: str) -> Communication | None:
        raise NotImplementedError

    async def by_provider_id(self, provider_message_id: str) -> Communication | None:
        raise NotImplementedError

    async def set_delivery_status(self, provider_message_id: str, status: str) -> bool:
        raise NotImplementedError

    async def latest_prompt_for_phone(
        self, role_ids: Collection[str], message_ids: Collection[str]
    ) -> Communication | None:
        raise NotImplementedError
