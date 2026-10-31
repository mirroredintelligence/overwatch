"""Test clock fixed at a time that the test controls."""

from datetime import UTC, datetime, timedelta


def _as_utc(at: datetime) -> datetime:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("FixedClock needs a timezone-aware datetime")
    return at.astimezone(UTC)


class FixedClock:
    def __init__(self, at: datetime) -> None:
        self._at = _as_utc(at)

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        self._at = _as_utc(at)

    def advance(self, delta: timedelta) -> None:
        self._at = self._at + delta
