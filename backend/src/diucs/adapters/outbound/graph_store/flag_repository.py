"""Report flags and service flags on Neo4j (P14). Stub only in the red commit (DEC-010).

Report flags are platform nodes (ReportFlag) on their Observation. Service flags are FHIR Basic
resources with the ServiceFlag profile, written through the G05 resource store (DEC-001).
"""

from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.model.flags import ReportFlag, ServiceFlag


def service_flag_id(service_id: str, code: str) -> str:
    raise NotImplementedError


def service_flag_to_fhir(flag: ServiceFlag) -> dict[str, Any]:
    raise NotImplementedError


def service_flag_from_fhir(resource: dict[str, Any]) -> ServiceFlag:
    raise NotImplementedError


class Neo4jFlagRepository:
    """Flags, built per transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def add_report_flag(self, flag: ReportFlag) -> None:
        raise NotImplementedError

    async def open_report_flags(self, service_id: str | None = None) -> list[ReportFlag]:
        raise NotImplementedError

    async def save_report_flag(self, flag: ReportFlag) -> None:
        raise NotImplementedError

    async def service_flags(self, service_id: str) -> list[ServiceFlag]:
        raise NotImplementedError

    async def set_service_flag(self, flag: ServiceFlag) -> None:
        raise NotImplementedError

    async def services_with_flag(self, code: str) -> set[str]:
        raise NotImplementedError
