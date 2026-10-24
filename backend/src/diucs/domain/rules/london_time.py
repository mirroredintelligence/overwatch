"""London local time helpers. Domain times are UTC; schedules are computed in Europe/London."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def to_london(dt: datetime) -> datetime:
    raise NotImplementedError


def london_to_utc(d: date, t: time) -> datetime:
    raise NotImplementedError


def format_hhmm(dt: datetime) -> str:
    raise NotImplementedError
