"""Limits on the unauthenticated routes, counted in the platform namespace (TEN-040). Stub."""

from datetime import timedelta
from typing import Final

from diucs.application.ports.outbound.cache import PlatformSlots

PUBLIC_REQUESTS_PER_ADDRESS: Final = 0
PUBLIC_WINDOW: Final = timedelta(seconds=1)


class PlatformRateLimiter:
    def __init__(self, slots: PlatformSlots) -> None:
        raise NotImplementedError

    async def take(self, kind: str, address: str, limit: int, window: timedelta) -> str | None:
        raise NotImplementedError

    async def release(self, slot: str) -> None:
        raise NotImplementedError
