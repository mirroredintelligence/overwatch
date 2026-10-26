"""Cases on Neo4j: Patient stub, ServiceRequest and referrer score Observations (P21).

Red-run stub (DEC-010): every function raises NotImplementedError until the green commit.
"""

from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.model.case import Case


def case_to_fhir(case: Case) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    raise NotImplementedError


def case_from_fhir(
    patient: dict[str, Any], service_request: dict[str, Any], scores: list[dict[str, Any]]
) -> Case:
    raise NotImplementedError


class Neo4jCaseRepository:
    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def add(self, case: Case) -> None:
        raise NotImplementedError

    async def get(self, case_id: str) -> Case | None:
        raise NotImplementedError

    async def get_by_reference(self, reference: str) -> Case | None:
        raise NotImplementedError

    async def save(self, case: Case) -> None:
        raise NotImplementedError
