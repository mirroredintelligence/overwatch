"""Service moves on Neo4j (P20). Red stub: every method raises NotImplementedError."""

from neo4j import AsyncManagedTransaction

from diucs.domain.model.service_move import ServiceMove


class Neo4jServiceMoveRepository:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def add(self, move: ServiceMove) -> None:
        raise NotImplementedError("P20: add")

    async def get(self, move_id: str) -> ServiceMove | None:
        raise NotImplementedError("P20: get")

    async def save(self, move: ServiceMove) -> None:
        raise NotImplementedError("P20: save")

    async def open_for_service(self, service_id: str) -> list[ServiceMove]:
        raise NotImplementedError("P20: open_for_service")
