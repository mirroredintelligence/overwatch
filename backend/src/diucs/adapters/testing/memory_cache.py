"""Fake for tests only. Redis is the production cache; P12 and I01 keep the two behaving
the same.

Every name is qualified by the bound scope through the port's `scoped_names()`, exactly as the Redis
adapter does (TEN-019): a value, a channel, a lock and a fencing counter of one tenant are never
seen by another. A missing scope is refused before anything is stored.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Self

from diucs.application.ports.outbound.cache import (
    CacheScopeMismatch,
    Lock,
    scoped_names,
)
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
        # Every dictionary is keyed by the scoped name (`<segment>:<family>:<name>`), so two
        # scopes never share an entry.
        self._values: dict[str, _Value] = {}
        self._subscribers: dict[str, list[asyncio.Queue[str | None]]] = {}
        self._holders: dict[str, _Holder] = {}
        self._last_token: dict[str, int] = {}

    def _now(self) -> datetime:
        # Compare instants in UTC only (lesson L52); the clock is already UTC by contract.
        return self._clock.now().astimezone(UTC)

    def keys(self) -> frozenset[str]:
        """The unexpired value keys of the bound scope, as scoped names. For tests."""
        names = scoped_names()
        now = self._now()
        return frozenset(
            name
            for name, stored in self._values.items()
            if name.startswith(f"{names.segment}:cache:")
            and (stored.expires_at is None or now < stored.expires_at)
        )

    async def get(self, key: str) -> str | None:
        names = scoped_names()
        full = names.key(key)
        stored = self._values.get(full)
        if stored is None:
            return None
        if stored.expires_at is not None and self._now() >= stored.expires_at:
            del self._values[full]
            return None
        return stored.text

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        names = scoped_names()
        expires_at = None if ttl is None else self._now() + ttl
        self._values[names.key(key)] = _Value(text=value, expires_at=expires_at)

    async def set_if_absent(self, key: str, value: str, ttl: timedelta) -> bool:
        names = scoped_names()
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        full = names.key(key)
        # No await between the check and the store, so two tasks cannot both see the key absent.
        stored = self._values.get(full)
        if stored is not None and (stored.expires_at is None or self._now() < stored.expires_at):
            return False
        self._values[full] = _Value(text=value, expires_at=self._now() + ttl)
        return True

    async def delete(self, key: str) -> None:
        names = scoped_names()
        self._values.pop(names.key(key), None)

    async def publish(self, channel: str, message: str) -> None:
        names = scoped_names()
        for queue in self._subscribers.get(names.channel(channel), []):
            queue.put_nowait(message)

    async def subscribe(self, channel: str) -> AsyncIterator[str]:
        # The channel is the one of the scope bound now, and the subscription keeps it. It is
        # registered now, not on the first read, so a publish after this call is never missed.
        names = scoped_names()
        full = names.channel(channel)
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._subscribers.setdefault(full, []).append(queue)
        return _Subscription(queue, lambda: self._remove(full, queue))

    def _remove(self, full: str, queue: asyncio.Queue[str | None]) -> None:
        queues = self._subscribers.get(full, [])
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._subscribers.pop(full, None)

    def subscriber_count(self, channel: str) -> int:
        """How many subscriptions are open on the channel of the bound scope. For tests: the port
        has no such call."""
        names = scoped_names()
        return len(self._subscribers.get(names.channel(channel), []))

    async def acquire_lock(self, name: str, ttl: timedelta) -> Lock | None:
        names = scoped_names()
        now = self._now()
        lock_name = names.lock(name)
        fence_name = names.fence(name)
        holder = self._holders.get(lock_name)
        if holder is not None and now < holder.expires_at:
            return None
        token = self._last_token.get(fence_name, 0) + 1
        self._last_token[fence_name] = token
        self._holders[lock_name] = _Holder(token=token, expires_at=now + ttl)
        return Lock(name=name, fencing_token=token, scope=names.segment)

    async def release_lock(self, lock: Lock) -> None:
        names = scoped_names()
        if lock.scope != names.segment:
            # A bug, not a stale holder: nothing is released (DEC-058 item 4 holds within a scope).
            raise CacheScopeMismatch()
        lock_name = names.lock(lock.name)
        holder = self._holders.get(lock_name)
        if holder is not None and holder.token == lock.fencing_token:
            del self._holders[lock_name]
