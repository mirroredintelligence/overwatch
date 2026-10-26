"""The scope list on Neo4j (P13). Red-commit stub: every method raises NotImplementedError."""

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.model.registration import ScopeEntry


class Neo4jScopeListRepository:
    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def entries(self) -> list[ScopeEntry]:
        raise NotImplementedError

    async def get_entry(self, service_id: str) -> ScopeEntry | None:
        raise NotImplementedError

    async def save_entry(self, entry: ScopeEntry) -> None:
        raise NotImplementedError
