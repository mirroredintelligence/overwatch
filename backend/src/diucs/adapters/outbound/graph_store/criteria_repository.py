"""Service criteria on Neo4j: ServiceCriteria <-> FHIR Basic with the ServiceCriteria profile (P04).

Red stub. The behaviour is written in the green commit.
"""

from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.model.criteria import ServiceCriteria


def criteria_to_fhir(criteria: ServiceCriteria) -> dict[str, Any]:
    """The Basic for a criteria version. No meta: the store sets it."""
    raise NotImplementedError


def criteria_from_fhir(resource: dict[str, Any]) -> ServiceCriteria:
    """The criteria version for a Basic. Refuses a value it does not recognise."""
    raise NotImplementedError


class Neo4jCriteriaRepository:
    """Criteria versions as Basic resources. Built per transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def current_for_service(self, service_id: str) -> ServiceCriteria | None:
        raise NotImplementedError

    async def current_for_services(self, service_ids: list[str]) -> dict[str, ServiceCriteria]:
        raise NotImplementedError

    async def get(self, criteria_id: str) -> ServiceCriteria | None:
        raise NotImplementedError

    async def add(self, criteria: ServiceCriteria) -> None:
        raise NotImplementedError

    async def save(self, criteria: ServiceCriteria) -> None:
        raise NotImplementedError

    async def history(self, service_id: str) -> list[ServiceCriteria]:
        raise NotImplementedError
