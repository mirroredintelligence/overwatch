"""Bookings on Neo4j: Booking <-> FHIR Task code booking-request (P02). Red stub."""

from datetime import datetime
from typing import Any

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.model.booking import Booking


def booking_to_fhir(booking: Booking) -> dict[str, Any]:
    raise NotImplementedError("P02: booking_to_fhir")


def booking_from_fhir(resource: dict[str, Any]) -> Booking:
    raise NotImplementedError("P02: booking_from_fhir")


async def read_task_fhir(store: ResourceStore, booking_id: str) -> dict[str, Any] | None:
    raise NotImplementedError("P02: read_task_fhir")


class Neo4jBookingRepository:
    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def add(self, booking: Booking) -> None:
        raise NotImplementedError("P02: add")

    async def get(self, booking_id: str) -> Booking | None:
        raise NotImplementedError("P02: get")

    async def get_by_reference(self, reference: str) -> Booking | None:
        raise NotImplementedError("P02: get_by_reference")

    async def save(self, booking: Booking) -> None:
        raise NotImplementedError("P02: save")

    async def open_for_service(self, service_id: str) -> list[Booking]:
        raise NotImplementedError("P02: open_for_service")

    async def open_for_services(self, service_ids: list[str]) -> dict[str, list[Booking]]:
        raise NotImplementedError("P02: open_for_services")

    async def confirmed_since(self, service_id: str, since: datetime) -> list[datetime]:
        raise NotImplementedError("P02: confirmed_since")

    async def pending_count(self, service_id: str) -> int:
        raise NotImplementedError("P02: pending_count")
