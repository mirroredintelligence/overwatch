"""Outbound port for the postcode download requests (DEC-1329): a confirmed district waits here
until the workers download its points. A request is keyed by its prefix, so asking twice is one.

A request goes queued, then running when a worker claims it, then done with its postcode count or
failed. Only a worker moves it past queued.
"""

from datetime import datetime
from typing import Protocol


class PostcodeDownloadQueue(Protocol):
    async def request(self, prefix: str, now: datetime) -> None:
        """Queue the prefix, or queue it again if it is already done or failed."""
        ...

    async def claim_next(self, now: datetime) -> str | None:
        """Mark the oldest queued request as running; return its prefix, or None if none waits."""
        ...

    async def finish(self, prefix: str, postcodes: int, now: datetime) -> None: ...

    async def fail(self, prefix: str, now: datetime) -> None: ...
