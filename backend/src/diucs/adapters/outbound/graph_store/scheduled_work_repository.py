"""Neo4j repository for ScheduledWork records (P08). Stub for the red commit (DEC-010)."""

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.queries import REGISTRY, QueryRegistry
from diucs.application.work import ScheduledWork, WorkKind


class Neo4jScheduledWorkRepository:
    def __init__(self, tx: AsyncManagedTransaction, store: QueryRegistry = REGISTRY) -> None:
        raise NotImplementedError

    async def add(self, work: ScheduledWork) -> None:
        raise NotImplementedError

    async def get(self, id: str) -> ScheduledWork:
        raise NotImplementedError

    async def for_about(self, about_id: str, kind: WorkKind | None = None) -> list[ScheduledWork]:
        raise NotImplementedError

    async def save(self, work: ScheduledWork) -> None:
        raise NotImplementedError
