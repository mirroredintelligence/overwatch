"""People on Neo4j (P03). Red stub: names only, behaviour not yet written."""

from datetime import datetime
from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.model.people import Practitioner, PractitionerRole


def practitioner_to_fhir(practitioner: Practitioner) -> dict[str, Any]:
    raise NotImplementedError


def practitioner_from_fhir(
    resource: dict[str, Any], phone_hash: str | None = None, email_domain: str | None = None
) -> Practitioner:
    raise NotImplementedError


def role_to_fhir(role: PractitionerRole) -> dict[str, Any]:
    raise NotImplementedError


def role_from_fhir(resource: dict[str, Any]) -> PractitionerRole:
    raise NotImplementedError


class Neo4jPersonRepository:
    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def get_practitioner(self, practitioner_id: str) -> Practitioner | None:
        raise NotImplementedError

    async def find_by_phone_hash(self, phone_hash: str) -> Practitioner | None:
        raise NotImplementedError

    async def roles_for_practitioner(self, practitioner_id: str) -> list[PractitionerRole]:
        raise NotImplementedError

    async def services_for_phone_hash(
        self, phone_hash: str, now: datetime
    ) -> list[tuple[PractitionerRole, str]]:
        raise NotImplementedError

    async def reporter_roles_for_service(
        self, service_id: str, now: datetime
    ) -> list[PractitionerRole]:
        raise NotImplementedError

    async def save_practitioner(self, practitioner: Practitioner) -> None:
        raise NotImplementedError

    async def save_role(self, role: PractitionerRole) -> None:
        raise NotImplementedError
