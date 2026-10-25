"""Fake for tests only. Redis is the production cache; P12 and I01 keep the two behaving the same."""

from collections.abc import AsyncIterator
from datetime import timedelta

from diucs.application.ports.outbound.cache import Lock
from diucs.application.ports.outbound.clock import Clock


class InMemoryCache:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def get(self, key: str) -> str | None:
        raise NotImplementedError

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError

    async def publish(self, channel: str, message: str) -> None:
        raise NotImplementedError

    def subscribe(self, channel: str) -> AsyncIterator[str]:
        raise NotImplementedError

    async def acquire_lock(self, name: str, ttl: timedelta) -> Lock | None:
        raise NotImplementedError

    async def release_lock(self, lock: Lock) -> None:
        raise NotImplementedError
