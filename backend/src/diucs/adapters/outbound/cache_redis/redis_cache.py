"""Redis adapter for the cache port (I01, DEC-003, DEC-058, DEC-092, TEN-019).

Redis holds only transient data: losing every key loses no fact (DEC-001). Every key, lock holder,
fencing counter and pub/sub channel is `diucs:<scope>:<family>:<name>`, where the scope is the
tenant or the network the unit of work is bound to (`diucs:_net-<id>:...` for a network). The names
come from the port's `scoped_names()` only. It is read once, first, in every method, so a call uses
the scope it began with even if the binding moves during it. Values are text. The client must decode
responses (from_url does), so replies are str.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from typing import Final, Self, cast

from redis.asyncio import Redis

from diucs.application.ports.outbound.cache import (
    CacheScopeMismatch,
    Lock,
    scoped_names,
)

# Every name the cache holds sits under this root. Isolation between test runs is by a unique tenant
# per run, not by a second root (TEN-019, audit C 4.4).
ROOT: Final = "diucs:"

# DEC-091: the token is the larger of the next INCR value and the host clock in microseconds, and
# the counter is set to it. A lost counter restarts above every token issued before the loss.
_NEXT_TOKEN = """
local issued = math.max(redis.call('INCR', KEYS[1]), tonumber(ARGV[1]))
redis.call('SET', KEYS[1], issued)
return issued
"""

# Compare-and-delete: the lock goes only while it still holds this holder's token (DEC-058 item 4).
_RELEASE_IF_HOLDER = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def _millis(ttl: timedelta) -> int:
    return round(ttl / timedelta(milliseconds=1))


class RedisSubscription(AsyncIterator[str]):
    """Messages published to one channel, from the moment subscribe() returns (DEC-092)."""

    def __init__(
        self,
        client: Redis,
        key: str,
        on_close: Callable[[RedisSubscription], None],
    ) -> None:
        self._pubsub = client.pubsub()
        self._key = key
        self._on_close = on_close
        self._messages: asyncio.Queue[str | None] = asyncio.Queue()
        self._closed = False
        self._reader: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._pubsub.subscribe(self._key)
        while True:
            # The first reply on a fresh connection is the server's confirmation of SUBSCRIBE.
            reply = await self._pubsub.get_message(ignore_subscribe_messages=False, timeout=None)
            if reply is not None and reply["type"] == "subscribe":
                break
        self._reader = asyncio.get_running_loop().create_task(self._pump())

    async def _pump(self) -> None:
        while True:
            reply = await self._pubsub.get_message(ignore_subscribe_messages=False, timeout=None)
            if reply is None:
                continue
            if reply["type"] == "unsubscribe":
                return
            if reply["type"] == "message":
                self._messages.put_nowait(str(reply["data"]))

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> str:
        if self._closed:
            raise StopAsyncIteration
        item = await self._messages.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def aclose(self) -> None:
        """Unsubscribe and wait for the server to confirm it, then release the connection."""
        if self._closed:
            return
        self._closed = True
        self._on_close(self)
        if self._reader is not None:
            await self._pubsub.unsubscribe(self._key)
            await self._reader  # the pump returns on the unsubscribe reply
        self._messages.put_nowait(None)
        await self._pubsub.aclose()  # type: ignore[no-untyped-call]  # redis-py leaves it unannotated


class RedisCache:
    """The Cache port on Redis. The client must decode responses (see from_url)."""

    def __init__(self, client: Redis) -> None:
        self._client = client
        self._subscriptions: set[RedisSubscription] = set()

    @classmethod
    def from_url(cls, url: str) -> RedisCache:
        return cls(Redis.from_url(url, decode_responses=True))

    async def get(self, key: str) -> str | None:
        names = scoped_names()
        # from_url sets decode_responses=True, so a reply is text; the stubs also allow bytes.
        value = await self._client.get(ROOT + names.key(key))
        return cast("str | None", value)

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        names = scoped_names()
        px = None if ttl is None else _millis(ttl)
        await self._client.set(ROOT + names.key(key), value, px=px)

    async def set_if_absent(self, key: str, value: str, ttl: timedelta) -> bool:
        names = scoped_names()
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        # One SET NX PX: Redis decides which of two concurrent callers stores the key.
        stored = await self._client.set(ROOT + names.key(key), value, nx=True, px=_millis(ttl))
        return bool(stored)

    async def delete(self, key: str) -> None:
        names = scoped_names()
        await self._client.delete(ROOT + names.key(key))

    async def publish(self, channel: str, message: str) -> None:
        names = scoped_names()
        await self._client.publish(ROOT + names.channel(channel), message)

    async def subscribe(self, channel: str) -> RedisSubscription:
        # The channel of the scope bound now is computed here, and the subscription keeps it.
        names = scoped_names()
        subscription = RedisSubscription(
            self._client,
            ROOT + names.channel(channel),
            on_close=self._subscriptions.discard,
        )
        self._subscriptions.add(subscription)
        await subscription.start()
        return subscription

    async def acquire_lock(self, name: str, ttl: timedelta) -> Lock | None:
        names = scoped_names()
        # The counter never expires, so tokens keep increasing across restarts (DEC-058 item 2).
        # After a data loss the clock term keeps them increasing (DEC-091).
        now_us = time.time_ns() // 1_000
        token: int = await self._client.eval(_NEXT_TOKEN, 1, ROOT + names.fence(name), str(now_us))
        acquired = await self._client.set(
            ROOT + names.lock(name), str(token), nx=True, px=_millis(ttl)
        )
        if not acquired:
            return None
        return Lock(name=name, fencing_token=token, scope=names.segment)

    async def release_lock(self, lock: Lock) -> None:
        names = scoped_names()
        if lock.scope != names.segment:
            # A bug, not a stale holder: nothing is released (DEC-058 item 4 holds within a scope).
            raise CacheScopeMismatch()
        await self._client.eval(
            _RELEASE_IF_HOLDER, 1, ROOT + names.lock(lock.name), str(lock.fencing_token)
        )

    async def aclose(self) -> None:
        """Close every subscription this cache made, then the client."""
        for subscription in list(self._subscriptions):
            await subscription.aclose()
        await self._client.aclose()
