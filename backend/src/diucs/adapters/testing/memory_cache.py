"""Fake for tests only. Redis is the production cache; P12 and I01 keep the two behaving
the same.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Self

from diucs.application.ports.outbound.cache import Lock
from diucs.application.ports.outbound.clock import Clock


@dataclass(frozen=True, slots=True)
class _Value:
    text: str
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class _Holder:
    token: int
    expires_at: datetime


class _Subscription:
    """Messages published to one channel after the subscription was created. Closing it ends a
    reader that is waiting, and removes the subscription from the channel."""

    def __init__(self, queue: asyncio.Queue[str | None], on_close: Callable[[], None]) -> None:
        self._queue = queue
        self._on_close = on_close
        self._closed = False

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> str:
        if self._closed:
            raise StopAsyncIteration
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.put_nowait(None)
        self._on_close()


class InMemoryCache:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._values: dict[str, _Value] = {}
        self._subscribers: dict[str, list[asyncio.Queue[str | None]]] = {}
        self._holders: dict[str, _Holder] = {}
        self._last_token: dict[str, int] = {}

    def _now(self) -> datetime:
        # Compare instants in UTC only (lesson L52); the clock is already UTC by contract.
        return self._clock.now().astimezone(UTC)

    async def get(self, key: str) -> str | None:
        stored = self._values.get(key)
        if stored is None:
            return None
        if stored.expires_at is not None and self._now() >= stored.expires_at:
            del self._values[key]
            return None
        return stored.text

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        expires_at = None if ttl is None else self._now() + ttl
        self._values[key] = _Value(text=value, expires_at=expires_at)

    async def set_if_absent(self, key: str, value: str, ttl: timedelta) -> bool:
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        # No await between the check and the store, so two tasks cannot both see the key absent.
        stored = self._values.get(key)
        if stored is not None and (stored.expires_at is None or self._now() < stored.expires_at):
            return False
        self._values[key] = _Value(text=value, expires_at=self._now() + ttl)
        return True

    async def delete(self, key: str) -> None:
        self._values.pop(key, None)

    async def publish(self, channel: str, message: str) -> None:
        for queue in self._subscribers.get(channel, []):
            queue.put_nowait(message)

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        # Registered now, not on the first read, so a publish after this call is never missed.
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._subscribers.setdefault(channel, []).append(queue)
        return _Subscription(queue, lambda: self._remove(channel, queue))

    def _remove(self, channel: str, queue: asyncio.Queue[str | None]) -> None:
        queues = self._subscribers.get(channel, [])
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._subscribers.pop(channel, None)

    def subscriber_count(self, channel: str) -> int:
        """How many subscriptions are open on the channel. For tests: the port has no such call."""
        return len(self._subscribers.get(channel, []))

    async def acquire_lock(self, name: str, ttl: timedelta) -> Lock | None:
        now = self._now()
        holder = self._holders.get(name)
        if holder is not None and now < holder.expires_at:
            return None
        token = self._last_token.get(name, 0) + 1
        self._last_token[name] = token
        self._holders[name] = _Holder(token=token, expires_at=now + ttl)
        return Lock(name=name, fencing_token=token)

    async def release_lock(self, lock: Lock) -> None:
        holder = self._holders.get(lock.name)
        if holder is not None and holder.token == lock.fencing_token:
            del self._holders[lock.name]
