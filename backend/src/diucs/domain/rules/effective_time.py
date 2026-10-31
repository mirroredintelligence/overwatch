"""The effective time of a new report against the figures already on record (KI-7, KI-8, KI-9).

The board shows the latest figure, so a figure is current only when it is later than every figure
on record. Two rules follow, both pure and both on instants (never wall-clock times):

- An explicit effective time (a lead recording a figure that was true earlier) must be later than
  the latest figure's time. One that is earlier would be hidden behind the latest figure, and one
  that is equal ties with it, and a tie is ordered by a whole-second write time, which is
  undefined. Either is refused (DEC-1100 Q8, KI-7, KI-9).
- A figure with no explicit time is taken at the clock, but never at or before the latest figure's
  time. A host whose clock is behind the host that wrote the latest figure would otherwise time the
  new figure before an older one (KI-8). The smallest step after it is one microsecond.
"""

from datetime import UTC, datetime, timedelta
from typing import Final

ONE_MICROSECOND: Final = timedelta(microseconds=1)


def _utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("a time must be timezone-aware")
    return value.astimezone(UTC)


def is_later_than_latest(explicit: datetime, latest_at: datetime | None) -> bool:
    """True when `explicit` may be the effective time of a new figure: it is strictly later than
    the latest figure's time, or there is no figure."""
    instant = _utc(explicit)
    return latest_at is None or instant > _utc(latest_at)


def default_effective_at(now: datetime, latest_at: datetime | None) -> datetime:
    """The effective time of a figure with none given: `now`, or one microsecond after the latest
    figure when `now` is not later than it. In UTC."""
    clock = _utc(now)
    if latest_at is None:
        return clock
    latest = _utc(latest_at)
    return clock if clock > latest else latest + ONE_MICROSECOND
