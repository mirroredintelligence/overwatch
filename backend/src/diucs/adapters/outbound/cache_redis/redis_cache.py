"""Redis adapter for the cache port (I01, DEC-003, DEC-058).

Red commit: every method is a stub that raises NotImplementedError (DEC-010).
"""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Self

from redis.asyncio import Redis

from diucs.application.ports.outbound.cache import Lock


class RedisSubscription(AsyncIterator[str]):
    """Messages published to one channel after the subscription was made."""

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> str:
        raise NotImplementedError

    async def aclose(self) -> None:
        raise NotImplementedError


class RedisCache:
    def __init__(self, client: Redis) -> None:
        self._client = client

    @classmethod
    def from_url(cls, url: str) -> "RedisCache":
        raise NotImplementedError

    async def get(self, key: str) -> str | None:
        raise NotImplementedError

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError

    async def publish(self, channel: str, message: str) -> None:
        raise NotImplementedError

    def subscribe(self, channel: str) -> RedisSubscription:
        raise NotImplementedError

    async def acquire_lock(self, name: str, ttl: timedelta) -> Lock | None:
        raise NotImplementedError

    async def release_lock(self, lock: Lock) -> None:
        raise NotImplementedError

    async def aclose(self) -> None:
        raise NotImplementedError
