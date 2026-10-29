"""Clinical advice requests on Neo4j (P18). Red stub: every function raises NotImplementedError."""

from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.model.clinical import ClinicalRequestRecord


def clinical_record_to_fhir(record: ClinicalRequestRecord) -> dict[str, Any]:
    raise NotImplementedError("P18: clinical_record_to_fhir")


def clinical_record_from_fhir(
    resource: dict[str, Any], props: dict[str, Any]
) -> ClinicalRequestRecord:
    raise NotImplementedError("P18: clinical_record_from_fhir")


def clinical_record_to_props(record: ClinicalRequestRecord) -> dict[str, Any]:
    raise NotImplementedError("P18: clinical_record_to_props")


class Neo4jClinicalRequestRepository:
    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def add(self, record: ClinicalRequestRecord) -> None:
        raise NotImplementedError("P18: add")

    async def get(self, request_id: str) -> ClinicalRequestRecord | None:
        raise NotImplementedError("P18: get")

    async def save(self, record: ClinicalRequestRecord) -> None:
        raise NotImplementedError("P18: save")

    async def waiting(self) -> list[ClinicalRequestRecord]:
        raise NotImplementedError("P18: waiting")

    async def taken_by(self, clinician_id: str) -> list[ClinicalRequestRecord]:
        raise NotImplementedError("P18: taken_by")
