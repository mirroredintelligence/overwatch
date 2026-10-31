"""Coverage by time of day, and the rules for a service's coverage area (DEC-1305).

A visiting service covers postcode districts. The planning view asks which services cover each
district in one part of the day; the shift lead sets the districts, the response target and the days
a service goes out. Pure: no I/O and no clock.

A service counts in a part of the day when, on at least one of the days it goes out, it takes
referrals during some part of that window. The days it goes out are the coverage days the lead set,
or, until the lead sets any, the days of its available times. The hours are the available times of
the service profile (the lead does not set hours here), an overnight window being split at midnight.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import time
from typing import Final

from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.service import AvailableTime
from overwatch.domain.rules.postcode import normalise_district

DAY_CODES: Final = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_RESPONSE_HOURS: Final = 72
MIN_RESPONSE_HOURS: Final = 1
MAX_DISTRICTS: Final = 60
_MINUTES_PER_DAY: Final = 24 * 60

WINDOWS: Final[dict[str, tuple[int, int]]] = {
    "all": (0, 24),
    "night": (0, 6),
    "morning": (6, 12),
    "afternoon": (12, 18),
    "evening": (18, 24),
}
"""The parts of the day, as hours from midnight to midnight (London local), the end exclusive."""


def check_window(window: str) -> str:
    if window not in WINDOWS:
        raise ValidationFailed("window", "must be all, night, morning, afternoon or evening")
    return window


@dataclass(frozen=True, slots=True)
class CoverageSetting:
    """What the lead sets for a service: where, how fast, and on which days."""

    districts: tuple[str, ...]
    response_hours: int
    days: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoredCoverage:
    """What is stored for a service: its districts, and the target and days once the lead set
    them (None before)."""

    districts: tuple[str, ...]
    response_hours: int | None
    days: tuple[str, ...] | None


def check_setting(districts: object, response_hours: object, days: object) -> CoverageSetting:
    """The setting, with districts in canonical form (sorted, once each) and days in week order, or
    a ValidationFailed that names the element and never repeats its value."""
    if not isinstance(districts, list) or not districts:
        raise ValidationFailed("districts", "at least one district is required")
    if len(districts) > MAX_DISTRICTS:
        raise ValidationFailed("districts", f"at most {MAX_DISTRICTS} districts")
    found: set[str] = set()
    for item in districts:
        district = normalise_district(item) if isinstance(item, str) else None
        if district is None:
            raise ValidationFailed("districts", "each must be a postcode district such as DT4")
        found.add(district)
    if (
        type(response_hours) is not int
        or not MIN_RESPONSE_HOURS <= response_hours <= MAX_RESPONSE_HOURS
    ):
        raise ValidationFailed(
            "responseHours",
            f"must be a whole number from {MIN_RESPONSE_HOURS} to {MAX_RESPONSE_HOURS}",
        )
    if not isinstance(days, list) or not days:
        raise ValidationFailed("days", "at least one day is required")
    if not all(isinstance(day, str) and day in DAY_CODES for day in days):
        raise ValidationFailed("days", "each must be mon, tue, wed, thu, fri, sat or sun")
    return CoverageSetting(
        districts=tuple(sorted(found)),
        response_hours=response_hours,
        days=tuple(day for day in DAY_CODES if day in days),
    )


def _minute(value: time) -> int:
    return value.hour * 60 + value.minute


def _intervals(window: AvailableTime) -> list[tuple[int, int]]:
    """The minutes of the day a window of the profile takes referrals, [start, end)."""
    if window.all_day or window.start is None or window.end is None:
        return [(0, _MINUTES_PER_DAY)]
    start, end = _minute(window.start), _minute(window.end)
    if start < end:
        return [(start, end)]
    return [(start, _MINUTES_PER_DAY), (0, end)]  # overnight: split at midnight


def serves_window(
    available: Iterable[AvailableTime], coverage_days: Iterable[str] | None, window: str
) -> bool:
    """Whether a service counts in this part of the day (DEC-1305). `coverage_days` is None until
    the lead has set the service's days."""
    first, last = WINDOWS[check_window(window)]
    low, high = first * 60, last * 60
    chosen = None if coverage_days is None else {DAY_CODES.index(day) for day in coverage_days}
    for item in available:
        days = item.days if chosen is None else item.days & chosen
        if not days:
            continue
        if any(start < high and low < end for start, end in _intervals(item)):
            return True
    return False


@dataclass(frozen=True, slots=True)
class DistrictCover:
    district: str
    services: tuple[str, ...]


def cover_by_district(
    districts: Iterable[str], served: Sequence[tuple[str, Iterable[str]]]
) -> list[DistrictCover]:
    """Each district, in order, with the names of the services that cover it (name order, once
    each). `served` is (service name, districts it covers in this window). A district nobody
    covers has no services: it is still listed."""
    covers = [(name, set(covered)) for name, covered in served]
    return [
        DistrictCover(
            district, tuple(sorted({name for name, covered in covers if district in covered}))
        )
        for district in sorted(set(districts))
    ]
