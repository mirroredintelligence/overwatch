"""Clock that reads the operating system's time."""

from datetime import datetime


class SystemClock:
    def now(self) -> datetime:
        raise NotImplementedError
