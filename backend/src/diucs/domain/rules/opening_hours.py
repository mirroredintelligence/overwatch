"""Opening hours: is a service taking referrals at a given moment (domain-rules 1.3, rule 2).

Windows are London local (see AvailableTime). Every window is turned into UTC instants before
anything is compared, so clock changes are handled by london_to_utc and never by comparing local
wall-clock times (lesson L4: local 01:00 to 02:00 on 2026-03-29 does not exist and is not
monotonic). A window with end earlier than start is overnight and runs into the next morning.
An all-day window covers each listed London day from 00:00 to the next 00:00.

"Opening" means a window starts while the service was closed just before. An adjacent window
that picks up where another stops is not an opening, and an all-day window on every day never
opens, because it never closes.
"""

from collections.abc import Iterator, Sequence
from datetime import date, datetime, time, timedelta
from typing import Final

from diucs.domain.model.service import AvailableTime
from diucs.domain.rules.london_time import london_to_utc, to_london

SEARCH_DAYS: Final = 8  # [ASSUMED] D03 prompt: next_opening searches the next 8 days
ONE_DAY: Final = timedelta(days=1)
ONE_TICK: Final = timedelta(microseconds=1)
MIDNIGHT: Final = time(0, 0)


def _intervals_on(window: AvailableTime, day: date) -> Iterator[tuple[datetime, datetime]]:
    """Yield the UTC (start, end) interval that this window opens on the given London date."""
    if day.weekday() not in window.days:
        return
    if window.all_day:
        yield london_to_utc(day, MIDNIGHT), london_to_utc(day + ONE_DAY, MIDNIGHT)
        return
    # AvailableTime guarantees both bounds on a timed window (D01).
    start, end = window.start, window.end
    assert start is not None and end is not None
    end_day = day if end > start else day + ONE_DAY
    yield london_to_utc(day, start), london_to_utc(end_day, end)


def _intervals(
    times: Sequence[AvailableTime], first_day: date, last_day: date
) -> Iterator[tuple[datetime, datetime]]:
    """Yield every UTC (start, end) interval opened on London dates first_day to last_day."""
    day = first_day
    while day <= last_day:
        for window in times:
            yield from _intervals_on(window, day)
        day += ONE_DAY


def is_in_hours(times: Sequence[AvailableTime], now: datetime) -> bool:
    """True when any window covers the instant now (start inclusive, end exclusive)."""
    local_today = to_london(now).date()
    # An interval that could cover now opens on yesterday (an overnight window) or today.
    return any(
        start <= now < end for start, end in _intervals(times, local_today - ONE_DAY, local_today)
    )


def next_opening(times: Sequence[AvailableTime], now: datetime) -> datetime | None:
    """The earliest UTC instant after now at which the service opens, within 8 days, or None."""
    local_today = to_london(now).date()
    horizon = now + timedelta(days=SEARCH_DAYS)
    last_day = local_today + timedelta(days=SEARCH_DAYS)
    openings = [
        start
        for start, _ in _intervals(times, local_today - ONE_DAY, last_day)
        if now < start < horizon and not is_in_hours(times, start - ONE_TICK)
    ]
    return min(openings, default=None)
