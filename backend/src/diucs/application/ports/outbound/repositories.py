"""Outbound ports: service profiles and capacity reports (P01).

Adapters: Neo4jServiceRepository and Neo4jCapacityRepository in adapters/outbound/graph_store/.
Reports are never updated or deleted: a correction is a new report.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from diucs.domain.model.booking import Booking
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.people import Practitioner, PractitionerRole
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


class PersonRepository(Protocol):
    """Practitioners and their posts (P03). Adapter: Neo4jPersonRepository (graph_store/).

    A role's period and cover are read at the `now` the caller passes. Services are returned sorted
    by service id, with the service's name. Saves refuse an unknown practitioner, service or cover
    practitioner with NotFound, before anything is written.
    """

    async def get_practitioner(self, practitioner_id: str) -> Practitioner | None:
        """The stored practitioner, or None."""
        ...

    async def find_by_phone_hash(self, phone_hash: str) -> Practitioner | None:
        """The active practitioner holding this phone hash, or None. Inactive people are never
        returned."""
        ...

    async def roles_for_practitioner(self, practitioner_id: str) -> list[PractitionerRole]:
        """The active roles this practitioner owns, whatever their code."""
        ...

    async def services_for_phone_hash(
        self, phone_hash: str, now: datetime
    ) -> list[tuple[PractitionerRole, str]]:
        """Every active reporter role this phone holds and is not covered out of at `now`, plus
        every active reporter role it covers until after `now`. Each comes with its service name.
        Sorted by service id."""
        ...

    async def reporter_roles_for_service(
        self, service_id: str, now: datetime
    ) -> list[PractitionerRole]:
        """The active reporter roles of this service in effect at `now`. A covered role is included
        as stored; the caller resolves the holder with role_holder."""
        ...

    async def save_practitioner(self, practitioner: Practitioner) -> None:
        """Insert the practitioner, or replace the stored one."""
        ...

    async def save_role(self, role: PractitionerRole) -> None:
        """Insert the role, or replace the stored one, with its channel and cover links. Replacing
        without a cover removes the cover link."""
        ...
