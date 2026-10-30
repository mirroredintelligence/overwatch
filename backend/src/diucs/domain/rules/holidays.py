"""Bank holidays and service closures (TEN-066, H-T21).

Bank holidays are shared reference data, one checked-in list per nation: england-and-wales,
scotland and northern-ireland (the government's bank holiday data for 2026 and 2027; no runtime
fetch). A tenant names its region (holidayRegion); the region alone decides which holidays close it.
A service's own closures are inclusive local dates.

The dates are local calendar dates, in the zone the schedule reads the day in. Nothing here reads a
zone or the clock, so a closure is the same day in any zone the caller passes (TEN-065).

Lists are checked in the tests against the rules they follow (Easter, the first and last Monday
days, the substitute days for a weekend), so a mistyped date fails there.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from diucs.domain.errors import ValidationFailed

ENGLAND_AND_WALES: Final = "england-and-wales"
SCOTLAND: Final = "scotland"
NORTHERN_IRELAND: Final = "northern-ireland"
REGIONS: Final = frozenset({ENGLAND_AND_WALES, SCOTLAND, NORTHERN_IRELAND})

_BANK_HOLIDAYS: Final[Mapping[str, frozenset[date]]] = {
    ENGLAND_AND_WALES: frozenset(
        {
            date(2026, 1, 1),
            date(2026, 4, 3),
            date(2026, 4, 6),
            date(2026, 5, 4),
            date(2026, 5, 25),
            date(2026, 8, 31),
            date(2026, 12, 25),
            date(2026, 12, 28),
            date(2027, 1, 1),
            date(2027, 3, 26),
            date(2027, 3, 29),
            date(2027, 5, 3),
            date(2027, 5, 31),
            date(2027, 8, 30),
            date(2027, 12, 27),
            date(2027, 12, 28),
        }
    ),
    SCOTLAND: frozenset(
        {
            date(2026, 1, 1),
            date(2026, 1, 2),
            date(2026, 4, 3),
            date(2026, 5, 4),
            date(2026, 5, 25),
            date(2026, 8, 3),
            date(2026, 11, 30),
            date(2026, 12, 25),
            date(2026, 12, 28),
            date(2027, 1, 1),
            date(2027, 1, 4),
            date(2027, 3, 26),
            date(2027, 5, 3),
            date(2027, 5, 31),
            date(2027, 8, 2),
            date(2027, 11, 30),
            date(2027, 12, 27),
            date(2027, 12, 28),
        }
    ),
    NORTHERN_IRELAND: frozenset(
        {
            date(2026, 1, 1),
            date(2026, 3, 17),
            date(2026, 4, 3),
            date(2026, 4, 6),
            date(2026, 5, 4),
            date(2026, 5, 25),
            date(2026, 7, 13),
            date(2026, 8, 31),
            date(2026, 12, 25),
            date(2026, 12, 28),
            date(2027, 1, 1),
            date(2027, 3, 17),
            date(2027, 3, 26),
            date(2027, 3, 29),
            date(2027, 5, 3),
            date(2027, 5, 31),
            date(2027, 7, 12),
            date(2027, 8, 30),
            date(2027, 12, 27),
            date(2027, 12, 28),
        }
    ),
}


def bank_holidays(region: str) -> frozenset[date]:
    """The bank holidays of a nation. An unknown region is refused, never read as no holidays."""
    if region not in REGIONS:
        raise ValidationFailed("holidayRegion", "is not a bank holiday region")
    return _BANK_HOLIDAYS[region]


@dataclass(frozen=True, slots=True)
class ClosurePeriod:
    """A service's closure: the first and the last local day it is closed, both included."""

    first: date
    last: date

    def __post_init__(self) -> None:
        for field, value in (("first", self.first), ("last", self.last)):
            if not isinstance(value, date) or isinstance(value, datetime):
                raise ValidationFailed(field, "must be a local date")
        if self.last < self.first:
            raise ValidationFailed("last", "must not be before the first day")


def closed_on(region: str, closures: Sequence[ClosurePeriod] = ()) -> Callable[[date], bool]:
    """The predicate for a service in a tenant's region: a bank holiday of the region, or a day
    inside one of the service's closure periods, is closed."""
    holidays = bank_holidays(region)
    periods = tuple(closures)

    def closed(day: date) -> bool:
        return day in holidays or any(period.first <= day <= period.last for period in periods)

    return closed
