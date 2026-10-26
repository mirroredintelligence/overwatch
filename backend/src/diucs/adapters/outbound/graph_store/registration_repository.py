"""Registrations on Neo4j (P13). Red-commit stub: every function raises NotImplementedError."""

from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.codes import RegistrationStatus
from diucs.domain.model.registration import Registration


def registration_to_fhir(registration: Registration) -> dict[str, Any]:
    raise NotImplementedError


def registration_from_fhir(resource: dict[str, Any], draft: dict[str, dict[str, Any]]) -> Registration:
    raise NotImplementedError


def draft_to_rows(draft: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    raise NotImplementedError


def draft_from_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    raise NotImplementedError


class Neo4jRegistrationRepository:
    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def add(self, registration: Registration) -> None:
        raise NotImplementedError

    async def get(self, registration_id: str) -> Registration | None:
        raise NotImplementedError

    async def save(self, registration: Registration) -> None:
        raise NotImplementedError

    async def list_by_status(self, status: RegistrationStatus) -> list[Registration]:
        raise NotImplementedError

    async def for_service(self, service_id: str) -> list[Registration]:
        raise NotImplementedError
