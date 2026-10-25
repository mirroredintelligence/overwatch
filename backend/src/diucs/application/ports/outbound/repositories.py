"""Outbound ports: service profiles and capacity reports (P01).

Adapters: Neo4jServiceRepository and Neo4jCapacityRepository in adapters/outbound/graph_store/.
Reports are never updated or deleted: a correction is a new report.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile


class ServiceRepository(Protocol):
    async def get(self, service_id: str) -> ServiceProfile | None:
        """The stored profile, or None if there is no such service."""
        ...

    async def list_active(self) -> list[ServiceProfile]:
        """Every active service, sorted by name."""
        ...

    async def save(self, profile: ServiceProfile) -> None:
        """Insert the profile, or replace the stored one."""
        ...


class CapacityRepository(Protocol):
    async def add(self, report: CapacityReport) -> None:
        """Store a new report. A report id that already exists raises Conflict."""
        ...

    async def latest(self, service_id: str) -> CapacityReport | None:
        """The report with the greatest effective time, or None."""
        ...

    async def latest_for_services(self, service_ids: Sequence[str]) -> dict[str, CapacityReport]:
        """The latest report per service. Services with no report are left out."""
        ...

    async def reports_since(self, service_id: str, since: datetime) -> list[CapacityReport]:
        """Reports effective at or after `since`, oldest first."""
        ...

    async def last_report_times(self) -> dict[str, datetime | None]:
        """For every active service, the effective time of its latest report, or None."""
        ...
