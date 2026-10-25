"""Capacity reports on Neo4j: CapacityReport <-> FHIR Observation (P01). STUB (red commit)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.model.capacity import CapacityReport


def report_to_fhir(report: CapacityReport) -> dict[str, Any]:
    raise NotImplementedError


def report_from_fhir(resource: dict[str, Any]) -> CapacityReport:
    raise NotImplementedError


class Neo4jCapacityRepository:
    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def add(self, report: CapacityReport) -> None:
        raise NotImplementedError

    async def latest(self, service_id: str) -> CapacityReport | None:
        raise NotImplementedError

    async def latest_for_services(self, service_ids: Sequence[str]) -> dict[str, CapacityReport]:
        raise NotImplementedError

    async def reports_since(self, service_id: str, since: datetime) -> list[CapacityReport]:
        raise NotImplementedError

    async def last_report_times(self) -> dict[str, datetime | None]:
        raise NotImplementedError
