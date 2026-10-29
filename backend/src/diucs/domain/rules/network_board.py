"""The network board and the status of a projected service at read time (TEN-052). Stub."""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Final

from diucs.domain.codes import Cadence, Measure, ServiceCategory, Status
from diucs.domain.model.network import DirectorySource, GrantScope, ListingStatus
from diucs.domain.rules.listing import ListingPresentation
from diucs.domain.rules.pressure import Pressure
from diucs.domain.rules.projection import (
    CapacityProjection,
    OpeningHourProjection,
    ServiceProjection,
)
from diucs.domain.rules.status import ServiceState

__all__ = ["StatusInputs"]


@dataclass(frozen=True, slots=True)
class StatusInputs:
    source_service_id: str
    service_name: str
    category: ServiceCategory
    measure: Measure
    unit_label: str
    established_capacity: int
    can_exceed_established: bool
    limited_level_percent: int
    cadence: Cadence
    suspended: bool
    opening_hours: tuple[OpeningHourProjection, ...]
    report_id: str | None
    reported_at: datetime | None
    value: int | None
    confirmed_since: int
    reply_window_minutes: int
    stale_warning_hours: int


def status_inputs(capacity: CapacityProjection, service: ServiceProjection) -> StatusInputs:
    raise NotImplementedError


def compute_network_state(inputs: StatusInputs, now: datetime) -> ServiceState:
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class NetworkServiceInput:
    row_ref: str
    organisation_name: str
    service: ServiceProjection
    capacity: CapacityProjection | None
    listing: ListingStatus
    visible_scopes: frozenset[GrantScope]


@dataclass(frozen=True, slots=True)
class NetworkBoardEntry:
    row_ref: str
    organisation_name: str
    service_name: str
    category: ServiceCategory
    presentation: ListingPresentation
    status: Status | None
    unit_label: str | None
    effective_available: int | None
    over_by: int | None
    used: int | None
    established: int | None
    reported_at: datetime | None
    stale_warning: bool
    was_due_at: datetime | None
    source: DirectorySource


@dataclass(frozen=True, slots=True)
class NetworkBoard:
    entries: tuple[NetworkBoardEntry, ...]
    pressure: Pressure
    all_limited_or_worse: bool
    generated_at: datetime


_UNUSED: Final = time(0, 0)


def assemble_network_board(
    inputs: list[NetworkServiceInput], now: datetime, *, watch_from: int, high_from: int
) -> NetworkBoard:
    raise NotImplementedError


def network_pressure(
    entries: tuple[NetworkBoardEntry, ...], *, watch_from: int, high_from: int
) -> Pressure:
    raise NotImplementedError
