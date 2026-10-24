"""Test clock fixed at a time that the test controls."""

from datetime import datetime, timedelta


class FixedClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        raise NotImplementedError

    def set(self, at: datetime) -> None:
        raise NotImplementedError

    def advance(self, delta: timedelta) -> None:
        raise NotImplementedError
