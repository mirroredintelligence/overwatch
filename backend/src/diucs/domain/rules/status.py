"""Service status from profile, latest report, confirmations and clock (D07).

Rules: docs/spec/domain-rules.md 1.2 and 1.3. The first matching rule wins, in this order:
1 suspended; 2 out of hours; 3 no report, or overdue (1.5); 4 occupied-patients figures;
5 free-count figures. Figures (available, used, over_by) are filled whenever a report exists, even
when the status is not-updated or out-of-hours, so the board can show the last known figure.

Pure: no I/O and no clock. `now` is an argument. Every comparison uses integer arithmetic (no
floats) and instants are compared as UTC (lesson L4). Decision DEC-033 fixes the figures for
occupied-patients: there is no free count for occupancy, so available is None and used is the
occupied count (including bookings confirmed since the report).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.domain.codes import Measure, Status
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from diucs.domain.rules.availability import effective_available, effective_occupied
from diucs.domain.rules.freshness import Freshness, assess_freshness
from diucs.domain.rules.opening_hours import is_in_hours

PERCENT: Final = 100


@dataclass(frozen=True, slots=True)
class ServiceState:
    status: Status
    effective_available: int | None
    used: int | None
    over_by: int | None
    freshness: Freshness


@dataclass(frozen=True, slots=True)
class _Figures:
    count: int  # occupied patients, or effective available for a free-count measure
    available: int | None  # None for occupied-patients
    used: int
    over_by: int | None


def _check_report_matches(profile: ServiceProfile, latest: CapacityReport | None) -> None:
    # A figure from another service, or for another measure, must never reach this profile.
    if latest is None:
        return
    if latest.service_id != profile.id:
        raise ValueError("the report belongs to another service")
    if latest.measure is not profile.measure:
        raise ValueError("the report measure does not match the service measure")


def _figures(
    profile: ServiceProfile, latest: CapacityReport, confirmed_at: Sequence[datetime]
) -> _Figures:
    established = profile.established_capacity
    if profile.measure is Measure.OCCUPIED_PATIENTS:
        occupied = effective_occupied(latest, confirmed_at)
        over_by = occupied - established if occupied > established else None
        return _Figures(count=occupied, available=None, used=occupied, over_by=over_by)
    available = effective_available(latest, confirmed_at)
    used = max(0, established - available)
    return _Figures(count=available, available=available, used=used, over_by=None)


def _at_limit(used: int, profile: ServiceProfile) -> bool:
    # used / established >= limited_level_percent / 100, without floats.
    return used * PERCENT >= profile.limited_level_percent * profile.established_capacity


def _occupancy_status(profile: ServiceProfile, occupied: int) -> Status:
    established = profile.established_capacity
    if occupied > established:
        return Status.OVER_CAPACITY
    if occupied == established:
        return Status.LIMITED if profile.can_exceed_established else Status.NOT_ACCEPTING
    if _at_limit(occupied, profile):
        return Status.LIMITED
    return Status.ACCEPTING


def _free_status(profile: ServiceProfile, available: int, used: int) -> Status:
    if available == 0:
        return Status.NOT_ACCEPTING
    if _at_limit(used, profile):
        return Status.LIMITED
    return Status.ACCEPTING


def _status(
    profile: ServiceProfile,
    freshness: Freshness,
    figures: _Figures | None,
    now: datetime,
) -> Status:
    if profile.suspended:
        return Status.NOT_UPDATED
    if not is_in_hours(profile.available_times, now):
        return Status.OUT_OF_HOURS
    if figures is None or freshness.overdue:
        return Status.NOT_UPDATED
    if profile.measure is Measure.OCCUPIED_PATIENTS:
        return _occupancy_status(profile, figures.count)
    return _free_status(profile, figures.count, figures.used)


def compute_status(
    profile: ServiceProfile,
    latest: CapacityReport | None,
    confirmed_at: Sequence[datetime],
    now: datetime,
    policy: TenantPolicy = DEFAULT_POLICY,
) -> ServiceState:
    """The status, figures and freshness of one service at instant now (domain-rules 1.2, 1.3).

    confirmed_at holds the instants of bookings confirmed for this service. Only those at or after
    the report's effective time are subtracted (1.6). A report later than now, or a naive now, is
    refused by assess_freshness.
    """
    _check_report_matches(profile, latest)
    freshness = assess_freshness(profile, None if latest is None else latest.effective_at, now)
    figures = None if latest is None else _figures(profile, latest, confirmed_at)
    status = _status(profile, freshness, figures, now)
    return ServiceState(
        status=status,
        effective_available=None if figures is None else figures.available,
        used=None if figures is None else figures.used,
        over_by=None if figures is None else figures.over_by,
        freshness=freshness,
    )
