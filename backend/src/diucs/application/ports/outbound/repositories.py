"""Outbound ports: service profiles and capacity reports (P01).

Adapters: Neo4jServiceRepository and Neo4jCapacityRepository in adapters/outbound/graph_store/.
Reports are never updated or deleted: a correction is a new report.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from diucs.domain.model.booking import Booking
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


class BookingRepository(Protocol):
    async def add(self, booking: Booking) -> None:
        """Store a new booking. A booking id that already exists raises Conflict."""
        ...

    async def get(self, booking_id: str) -> Booking | None:
        """The stored booking, or None."""
        ...

    async def get_by_reference(self, reference: str) -> Booking | None:
        """The most recently requested booking with this reference, or None."""
        ...

    async def save(self, booking: Booking) -> None:
        """Replace the stored booking. An unknown id raises NotFound."""
        ...

    async def open_for_service(self, service_id: str) -> list[Booking]:
        """The bookings for this service that are still requested."""
        ...

    async def open_for_services(self, service_ids: Sequence[str]) -> dict[str, list[Booking]]:
        """The open bookings per service. Every requested service id is a key, with [] if none."""
        ...

    async def confirmed_since(self, service_id: str, since: datetime) -> list[datetime]:
        """confirmed_at of bookings whose status is exactly confirmed, at or after `since`."""
        ...

    async def pending_count(self, service_id: str) -> int:
        """How many bookings for this service are requested (Q-BOOK-PENDING)."""
        ...
