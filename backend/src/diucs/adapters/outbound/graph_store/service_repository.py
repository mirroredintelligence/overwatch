"""Service profiles on Neo4j: ServiceProfile <-> FHIR HealthcareService (P01). STUB (red commit)."""

from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.model.service import ServiceProfile


def profile_to_fhir(profile: ServiceProfile) -> dict[str, Any]:
    raise NotImplementedError


def profile_from_fhir(resource: dict[str, Any]) -> ServiceProfile:
    raise NotImplementedError


class Neo4jServiceRepository:
    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def get(self, service_id: str) -> ServiceProfile | None:
        raise NotImplementedError

    async def list_active(self) -> list[ServiceProfile]:
        raise NotImplementedError

    async def save(self, profile: ServiceProfile) -> None:
        raise NotImplementedError
