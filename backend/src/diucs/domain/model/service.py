"""Service reporting profile: validated value objects (D01).

Every capacity rule reads from a ServiceProfile. Validation runs once, when a profile is built, so
a rule never sees an impossible profile. Every failure raises ValidationFailed naming the field.

Days are integers, 0 = Monday to 6 = Sunday. Times are London local (naive) times of day. An end
earlier than the start is an overnight window (20:00 to 08:00). The end is exclusive.
"""

from dataclasses import dataclass
from datetime import time
from typing import Final

from diucs.domain.codes import Cadence, Channel, Measure, ServiceCategory
from diucs.domain.errors import ValidationFailed

ALL_DAYS: Final[frozenset[int]] = frozenset(range(7))
MONDAY_TO_FRIDAY: Final[frozenset[int]] = frozenset({0, 1, 2, 3, 4})

LIMITED_LEVEL_PERCENT_DEFAULT: Final = 80  # [ASSUMED] domain-rules.md 1.1
LIMITED_LEVEL_PERCENT_MIN: Final = 1
LIMITED_LEVEL_PERCENT_MAX: Final = 100
ESTABLISHED_CAPACITY_MIN: Final = 1


def _check_days(days: object) -> None:
    # A frozenset, not a set: the value must stay hashable.
    if not isinstance(days, frozenset):
        raise ValidationFailed("days", "must be a set of day numbers")
    if not days:
        raise ValidationFailed("days", "at least one day is required")
    for day in days:
        if isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6:
            raise ValidationFailed("days", "day numbers run from 0 (Monday) to 6 (Sunday)")


def _check_time(field: str, value: object) -> None:
    # Window times are London local: naive, so they can be compared with each other.
    if not isinstance(value, time) or value.tzinfo is not None:
        raise ValidationFailed(field, "must be a local time of day without a timezone")


def _check_text(field: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(field, "must not be blank")


def _check_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationFailed(field, "must be a whole number")
    return value


@dataclass(frozen=True, slots=True)
class AvailableTime:
    """Days and hours a service accepts referrals. All day means no start and no end."""

    days: frozenset[int]
    all_day: bool
    start: time | None
    end: time | None

    def __post_init__(self) -> None:
        _check_days(self.days)
        if self.all_day:
            if self.start is not None:
                raise ValidationFailed("start", "an all-day window has no start time")
            if self.end is not None:
                raise ValidationFailed("end", "an all-day window has no end time")
            return
        if self.start is None:
            raise ValidationFailed("start", "a timed window needs a start time")
        _check_time("start", self.start)
        if self.end is None:
            raise ValidationFailed("end", "a timed window needs an end time")
        _check_time("end", self.end)
        if self.end == self.start:
            raise ValidationFailed("end", "the end must differ from the start")

    @classmethod
    def weekdays(cls, start: time, end: time) -> AvailableTime:
        return cls(days=MONDAY_TO_FRIDAY, all_day=False, start=start, end=end)

    @classmethod
    def every_day(cls, start: time, end: time) -> AvailableTime:
        return cls(days=ALL_DAYS, all_day=False, start=start, end=end)

    @classmethod
    def every_day_all_day(cls) -> AvailableTime:
        return cls(days=ALL_DAYS, all_day=True, start=None, end=None)


@dataclass(frozen=True, slots=True)
class ServiceProfile:
    """How a service reports its capacity and when it takes referrals. Set at registration."""

    id: str
    name: str
    category: ServiceCategory
    measure: Measure
    unit_label: str
    established_capacity: int
    can_exceed_established: bool
    usual_range: tuple[int, int]
    cadence: Cadence
    available_times: tuple[AvailableTime, ...]
    channel: Channel
    limited_level_percent: int = LIMITED_LEVEL_PERCENT_DEFAULT
    active: bool = True
    suspended: bool = False
    comment: str = ""

    def __post_init__(self) -> None:
        _check_text("id", self.id)
        _check_text("name", self.name)
        _check_text("unit_label", self.unit_label)

        capacity = _check_int("established_capacity", self.established_capacity)
        if capacity < ESTABLISHED_CAPACITY_MIN:
            raise ValidationFailed("established_capacity", "must be at least 1")

        if not isinstance(self.usual_range, tuple) or len(self.usual_range) != 2:
            raise ValidationFailed("usual_range", "must be a (minimum, maximum) pair")
        low = _check_int("usual_range", self.usual_range[0])
        high = _check_int("usual_range", self.usual_range[1])
        if not 0 <= low <= high:
            raise ValidationFailed("usual_range", "must run from 0 or more, minimum first")

        if not isinstance(self.available_times, tuple) or not self.available_times:
            raise ValidationFailed("available_times", "at least one available time is required")
        if not all(isinstance(window, AvailableTime) for window in self.available_times):
            raise ValidationFailed("available_times", "each entry must be an AvailableTime")

        percent = _check_int("limited_level_percent", self.limited_level_percent)
        if not LIMITED_LEVEL_PERCENT_MIN <= percent <= LIMITED_LEVEL_PERCENT_MAX:
            raise ValidationFailed("limited_level_percent", "must run from 1 to 100")
