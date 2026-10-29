"""The network board and the status of a projected service at read time (TEN-052).

The projection stores the inputs of a status, never the status (DEC-134 item 6). This module
rebuilds the profile subset and the latest report from those inputs and calls the same
`compute_status` the tenant board calls, so a service that stops reporting reads "Not updated" on
the network with no new event (hazard H-N07). The result equals `compute_status` on the source
objects with the source tenant's policy, for every instant: a test holds that equality.

A network row is read-only and capacity-derived (DEC-134 item 8): an organisation, a service, a
status and figures. It holds no booking count, no comment, no next-due time, no reporter and no
source tenant id, grant or agreement (DEC-136 item 14: nothing supports a per-member breakdown).
The order is fixed and is not a ranking (design system section 13). Pure: no I/O, no clock.
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportSource,
    ReportType,
    ServiceCategory,
    Status,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.network import DirectorySource, GrantScope, ListingStatus
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from diucs.domain.rules.listing import ListingPresentation, listing_presentation
from diucs.domain.rules.pressure import Pressure, all_limited_or_worse, system_pressure
from diucs.domain.rules.projection import (
    NAME_MAX,
    CapacityProjection,
    OpeningHourProjection,
    ServiceProjection,
    check_projection_id,
    check_projection_text,
)
from diucs.domain.rules.status import ServiceState, compute_status

TYPE_MESSAGE: Final = "has the wrong type"
AWARE_MESSAGE: Final = "must be a timezone-aware datetime"
MISMATCH_MESSAGE: Final = "the capacity and the service are not the same service"

# Between the phone task and the escalation of a ladder the replica keeps the gaps of the default
# ladder; `compute_status` never reads the ladder, it only has to be a valid policy.
_PHONE_TASK_GAP: Final = timedelta(minutes=30)
_ESCALATE_GAP: Final = timedelta(minutes=60)

_CATEGORY_ORDER: Final = {category: index for index, category in enumerate(ServiceCategory)}


def _aware(field: str, value: object) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        raise ValidationFailed(field, AWARE_MESSAGE)
    return value.astimezone(UTC)


# ---------------------------------------------------------------- status at read time


@dataclass(frozen=True, slots=True)
class StatusInputs:
    """Everything `compute_status` needs, from the two projections of one service."""

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
    """The inputs for one service. A capacity and a directory projection of different services
    are refused: a figure must never reach another service's opening hours."""
    if type(capacity) is not CapacityProjection or type(service) is not ServiceProjection:
        raise ValidationFailed("projection", TYPE_MESSAGE)
    if capacity.source_service_id != service.source_service_id:
        raise ValidationFailed("capacity", MISMATCH_MESSAGE)
    return StatusInputs(
        source_service_id=service.source_service_id,
        service_name=service.service_name,
        category=service.category,
        measure=capacity.measure,
        unit_label=capacity.unit_label,
        established_capacity=capacity.established_capacity,
        can_exceed_established=capacity.can_exceed_established,
        limited_level_percent=capacity.limited_level_percent,
        cadence=capacity.cadence,
        suspended=capacity.suspended,
        opening_hours=service.opening_hours,
        report_id=capacity.report_id,
        reported_at=capacity.reported_at,
        value=capacity.value,
        confirmed_since=capacity.confirmed_since,
        reply_window_minutes=capacity.reply_window_minutes,
        stale_warning_hours=capacity.stale_warning_hours,
    )


def _replica_policy(inputs: StatusInputs) -> TenantPolicy:
    """The source tenant's policy as far as the status reads it: the reply window and the stale
    limit. The ladder must still be a valid policy (`reply_window <= reminder_after < phone_task <
    escalate`, TEN-006), so it is built from the reply window; `compute_status` never reads it."""
    reply = timedelta(minutes=inputs.reply_window_minutes)
    reminder = max(DEFAULT_POLICY.reminder_after, reply)
    return dataclasses.replace(
        DEFAULT_POLICY,
        reply_window=reply,
        stale_warning_after=timedelta(hours=inputs.stale_warning_hours),
        reminder_after=reminder,
        phone_task_after=reminder + _PHONE_TASK_GAP,
        escalate_after=reminder + _ESCALATE_GAP,
    )


def _profile(inputs: StatusInputs) -> ServiceProfile:
    # Placeholders stand in for what the allowlist does not carry; none of them is read by
    # `compute_status` (a test varies each on the source side).
    return ServiceProfile(
        id=inputs.source_service_id,
        name=inputs.service_name,
        category=inputs.category,
        measure=inputs.measure,
        unit_label=inputs.unit_label,
        established_capacity=inputs.established_capacity,
        can_exceed_established=inputs.can_exceed_established,
        usual_range=(0, inputs.established_capacity),
        cadence=inputs.cadence,
        available_times=tuple(
            AvailableTime(
                days=frozenset(hour.days),
                all_day=hour.all_day,
                start=hour.start,
                end=hour.end,
            )
            for hour in inputs.opening_hours
        ),
        channel=Channel.TEXT,
        limited_level_percent=inputs.limited_level_percent,
        active=True,
        suspended=inputs.suspended,
        comment="",
    )


def _report(inputs: StatusInputs) -> CapacityReport | None:
    if inputs.reported_at is None or inputs.report_id is None or inputs.value is None:
        return None
    return CapacityReport(
        id=inputs.report_id,
        service_id=inputs.source_service_id,
        value=inputs.value,
        measure=inputs.measure,
        effective_at=inputs.reported_at,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )


def compute_network_state(inputs: StatusInputs, now: datetime) -> ServiceState:
    """The status, figures and freshness of a projected service at instant `now`. Equal to
    `compute_status` on the source objects. Each confirmed booking counts as made at the report's
    own instant, which is exactly what the figures count (at or after the report)."""
    if type(inputs) is not StatusInputs:
        raise ValidationFailed("inputs", TYPE_MESSAGE)
    current = _aware("now", now)
    report = _report(inputs)
    confirmed_at = () if report is None else (report.effective_at,) * inputs.confirmed_since
    return compute_status(_profile(inputs), report, confirmed_at, current, _replica_policy(inputs))


# ---------------------------------------------------------------- the board


@dataclass(frozen=True, slots=True)
class NetworkServiceInput:
    """One member's service as the network read hands it over. `row_ref` is an opaque reference
    the read use case makes (never the source tenant id); `organisation_name` comes from the
    registry, not from the projection; `visible_scopes` is TEN-036's `visible_scopes` result."""

    row_ref: str
    organisation_name: str
    service: ServiceProjection
    capacity: CapacityProjection | None
    listing: ListingStatus
    visible_scopes: frozenset[GrantScope]

    def __post_init__(self) -> None:
        check_projection_id("row_ref", self.row_ref)
        check_projection_text("organisation_name", self.organisation_name, NAME_MAX)
        if type(self.service) is not ServiceProjection:
            raise ValidationFailed("service", TYPE_MESSAGE)
        if self.capacity is not None:
            if type(self.capacity) is not CapacityProjection:
                raise ValidationFailed("capacity", TYPE_MESSAGE)
            if self.capacity.source_service_id != self.service.source_service_id:
                raise ValidationFailed("capacity", MISMATCH_MESSAGE)
        if type(self.listing) is not ListingStatus:
            raise ValidationFailed("listing", TYPE_MESSAGE)
        if type(self.visible_scopes) is not frozenset or any(
            type(scope) is not GrantScope for scope in self.visible_scopes
        ):
            raise ValidationFailed("visible_scopes", TYPE_MESSAGE)


@dataclass(frozen=True, slots=True)
class NetworkBoardEntry:
    """A row of the network board. These fields and no others."""

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


def _name_only(item: NetworkServiceInput, presentation: ListingPresentation) -> NetworkBoardEntry:
    return NetworkBoardEntry(
        row_ref=item.row_ref,
        organisation_name=item.organisation_name,
        service_name=item.service.service_name,
        category=item.service.category,
        presentation=presentation,
        status=None,
        unit_label=None,
        effective_available=None,
        over_by=None,
        used=None,
        established=None,
        reported_at=None,
        stale_warning=False,
        was_due_at=None,
        source=item.service.source,
    )


def _shown(item: NetworkServiceInput, now: datetime) -> NetworkBoardEntry:
    name_only = _name_only(item, ListingPresentation.SHOWN)
    capacity = item.capacity
    if capacity is None:
        return dataclasses.replace(name_only, status=Status.NOT_UPDATED)
    try:
        state = compute_network_state(status_inputs(capacity, item.service), now)
    except ValueError:
        # A report dated after this read (clock skew between the member and the platform) is
        # never shown as a figure: the row reads Not updated.
        return dataclasses.replace(name_only, status=Status.NOT_UPDATED)
    return dataclasses.replace(
        name_only,
        status=state.status,
        unit_label=capacity.unit_label,
        effective_available=state.effective_available,
        over_by=state.over_by,
        used=state.used,
        established=capacity.established_capacity,
        reported_at=capacity.reported_at,
        stale_warning=state.freshness.stale_warning,
        was_due_at=state.freshness.was_due,
    )


def _entry(item: NetworkServiceInput, now: datetime) -> NetworkBoardEntry | None:
    """The entry for one input, or None when the input is left out (fail closed: no scope, no
    row). A suspended listing is unavailable: its name only, no figure (DEC-136 item 3)."""
    presentation = listing_presentation(item.listing)
    if presentation is ListingPresentation.HIDDEN:
        return None
    if presentation is ListingPresentation.UNAVAILABLE:
        return _name_only(item, presentation)
    if not {GrantScope.DIRECTORY, GrantScope.CAPACITY} <= item.visible_scopes:
        return None
    if not item.service.active:
        return None
    return _shown(item, now)


def _order(entry: NetworkBoardEntry) -> tuple[int, str, str, str]:
    return (
        _CATEGORY_ORDER[entry.category],
        entry.organisation_name.casefold(),
        entry.service_name.casefold(),
        entry.row_ref,
    )


def _pressure_policy(watch_from: int, high_from: int) -> TenantPolicy:
    return dataclasses.replace(
        DEFAULT_POLICY, pressure_watch_from=watch_from, pressure_high_from=high_from
    )


def network_pressure(
    entries: Sequence[NetworkBoardEntry], *, watch_from: int, high_from: int
) -> Pressure:
    """Pressure from the statuses of shown entries only, through the tenant board's own function
    with the network's thresholds. Unavailable entries are not counted."""
    return system_pressure(_shown_statuses(entries), _pressure_policy(watch_from, high_from))


def _shown_statuses(entries: Sequence[NetworkBoardEntry]) -> list[Status]:
    return [
        entry.status
        for entry in entries
        if entry.presentation is ListingPresentation.SHOWN and entry.status is not None
    ]


def assemble_network_board(
    inputs: Sequence[NetworkServiceInput],
    now: datetime,
    *,
    watch_from: int,
    high_from: int,
) -> NetworkBoard:
    """The board for a set of inputs at `now`. The data age of a row comes from its reported
    time, never from when it was projected; the order is by category, organisation and service
    name and is not a ranking."""
    current = _aware("now", now)
    policy = _pressure_policy(watch_from, high_from)
    entries: list[NetworkBoardEntry] = []
    for item in inputs:
        if type(item) is not NetworkServiceInput:
            raise ValidationFailed("inputs", TYPE_MESSAGE)
        entry = _entry(item, current)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=_order)
    statuses = _shown_statuses(entries)
    return NetworkBoard(
        entries=tuple(entries),
        pressure=system_pressure(statuses, policy),
        all_limited_or_worse=all_limited_or_worse(statuses),
        generated_at=current,
    )


__all__ = [
    "NetworkBoard",
    "NetworkBoardEntry",
    "NetworkServiceInput",
    "StatusInputs",
    "assemble_network_board",
    "compute_network_state",
    "network_pressure",
    "status_inputs",
]
