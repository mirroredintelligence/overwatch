"""London local time helpers. Domain times are UTC; schedules are computed in Europe/London.

Clock changes (Europe/London):
- Spring gap, 2026-03-29 01:00 to 02:00 does not exist. A local time in the gap is shifted
  forward by the gap length (zoneinfo with fold=0 keeps the pre-change offset, which does this).
- Autumn fold, 2026-10-25 01:00 to 02:00 happens twice. The first occurrence (BST) is used,
  which is also zoneinfo with fold=0.
"""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def _require_aware(dt: datetime) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware (UTC)")


def to_london(dt: datetime) -> datetime:
    """Return the same instant as a London wall-clock datetime. Naive input is a bug."""
    _require_aware(dt)
    return dt.astimezone(LONDON)


def london_to_utc(d: date, t: time) -> datetime:
    """Return the UTC instant for a London local date and time of day.

    The local wall-clock value is kept across clock changes, so 10:00 London is 09:00Z in
    summer and 10:00Z in winter. Gap times are shifted forward; fold times take the first
    occurrence.
    """
    if t.tzinfo is not None:
        raise ValueError("time of day must be naive London local time")
    local = datetime.combine(d, t).replace(tzinfo=LONDON, fold=0)
    return local.astimezone(UTC)


def format_hhmm(dt: datetime) -> str:
    """Return the London wall-clock time as HH:MM, for messages and the wall board."""
    return to_london(dt).strftime("%H:%M")


def format_stamp(dt: datetime) -> str:
    raise NotImplementedError
