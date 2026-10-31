"""Opening hours: is a service taking referrals at a given moment (domain-rules 1.3, rule 2).

Windows are local to the service's tenant (see AvailableTime), in the zone the caller passes (London
by default, TEN-065). Every window is turned into UTC instants before anything is compared, so clock
changes are handled by local_to_utc and never by comparing local wall-clock times (lesson L4: local
01:00 to 02:00 on 2026-03-29 does not exist and is not monotonic). A window with end earlier than
start is overnight and runs into the next morning. An all-day window covers each listed local day
from 00:00 to the next 00:00.

"Opening" means a window starts while the service was closed just before. An adjacent window
that picks up where another stops is not an opening, and an all-day window on every day never
opens, because it never closes.
"""

from collections.abc import Iterator, Sequence
from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from diucs.domain.model.service import AvailableTime
from diucs.domain.rules.london_time import LONDON, local_to_utc, require_zone, to_local

SEARCH_DAYS: Final = 8  # [ASSUMED] D03 prompt: next_opening searches the next 8 days
ONE_DAY: Final = timedelta(days=1)
ONE_TICK: Final = timedelta(microseconds=1)
MIDNIGHT: Final = time(0, 0)


def _intervals_on(
    window: AvailableTime, day: date, zone: ZoneInfo
) -> Iterator[tuple[datetime, datetime]]:
    """Yield the UTC (start, end) interval that this window opens on the given local date."""
    if day.weekday() not in window.days:
        return
    if window.all_day:
        yield local_to_utc(day, MIDNIGHT, zone), local_to_utc(day + ONE_DAY, MIDNIGHT, zone)
        return
    # AvailableTime guarantees both bounds on a timed window (D01).
    start, end = window.start, window.end
    assert start is not None and end is not None
    end_day = day if end > start else day + ONE_DAY
    yield local_to_utc(day, start, zone), local_to_utc(end_day, end, zone)


def _intervals(
    times: Sequence[AvailableTime], first_day: date, last_day: date, zone: ZoneInfo
) -> Iterator[tuple[datetime, datetime]]:
    """Yield every UTC (start, end) interval opened on local dates first_day to last_day."""
    day = first_day
    while day <= last_day:
        for window in times:
            yield from _intervals_on(window, day, zone)
        day += ONE_DAY


def is_in_hours(times: Sequence[AvailableTime], now: datetime, zone: ZoneInfo = LONDON) -> bool:
    """True when any window covers the instant now (start inclusive, end exclusive). The windows
    are read in `zone`."""
    zone = require_zone(zone)
    local_today = to_local(now, zone).date()
    # An interval that could cover now opens on yesterday (an overnight window) or today.
    return any(
        start <= now < end
        for start, end in _intervals(times, local_today - ONE_DAY, local_today, zone)
    )


def next_opening(
    times: Sequence[AvailableTime], now: datetime, zone: ZoneInfo = LONDON
) -> datetime | None:
    """The earliest UTC instant after now at which the service opens, within 8 days, or None. The
    windows are read in `zone`."""
    zone = require_zone(zone)
    local_today = to_local(now, zone).date()
    horizon = now + timedelta(days=SEARCH_DAYS)
    last_day = local_today + timedelta(days=SEARCH_DAYS)
    openings = [
        start
        for start, _ in _intervals(times, local_today - ONE_DAY, last_day, zone)
        if now < start < horizon and not is_in_hours(times, start - ONE_TICK, zone)
    ]
    return min(openings, default=None)


def next_hours_change(
    times: Sequence[AvailableTime], now: datetime, zone: ZoneInfo = LONDON
) -> datetime | None:
    """The earliest UTC instant after now at which `is_in_hours` changes its answer, within 8 days,
    or None (no window at all). An interval that ends where another begins is one stretch of hours:
    nothing changes at the join. The windows are read in `zone`."""
    zone = require_zone(zone)
    local_today = to_local(now, zone).date()
    horizon = now + timedelta(days=SEARCH_DAYS)
    last_day = local_today + timedelta(days=SEARCH_DAYS)
    edges = sorted(
        {
            edge
            for interval in _intervals(times, local_today - ONE_DAY, last_day, zone)
            for edge in interval
            if now < edge < horizon
        }
    )
    inside = is_in_hours(times, now, zone)
    return next(
        (edge for edge in edges if is_in_hours(times, edge, zone) != inside),
        None,
    )
