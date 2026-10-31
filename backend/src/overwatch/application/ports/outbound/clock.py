"""Outbound port: the current time. Domain functions never call this; use cases pass `now` in."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...
