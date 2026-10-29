"""Redis adapter for the cache port (I01, DEC-003, DEC-058, DEC-092).

Redis holds only transient data: losing every key loses no fact (DEC-001). Key families, all under
the diucs: prefix: cache values, lock holders, fencing counters and pub/sub channels. Values are
text. The client must decode responses (from_url does), so replies are str.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from typing import Self, cast

from redis.asyncio import Redis

from diucs.application.ports.outbound.cache import Lock

# The key families below sit under a prefix, "diucs:" by default. A test run may use its own prefix
# so that concurrent runs on one Redis share no keys (I01, lesson on the shared stack).
DEFAULT_KEY_PREFIX = "diucs:"
_CACHE_KEY = "cache:{}"
_LOCK_KEY = "lock:{}"
_FENCE_KEY = "fence:{}"
_CHANNEL_KEY = "chan:{}"

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

    def __init__(self, client: Redis, key_prefix: str = DEFAULT_KEY_PREFIX) -> None:
        self._client = client
        self._prefix = key_prefix
        self._subscriptions: set[RedisSubscription] = set()

    @classmethod
    def from_url(cls, url: str, key_prefix: str = DEFAULT_KEY_PREFIX) -> RedisCache:
        return cls(Redis.from_url(url, decode_responses=True), key_prefix)

    def _key(self, family: str, name: str) -> str:
        return self._prefix + family.format(name)

    async def get(self, key: str) -> str | None:
        # from_url sets decode_responses=True, so a reply is text; the stubs also allow bytes.
        value = await self._client.get(self._key(_CACHE_KEY, key))
        return cast("str | None", value)

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        px = None if ttl is None else _millis(ttl)
        await self._client.set(self._key(_CACHE_KEY, key), value, px=px)

    async def set_if_absent(self, key: str, value: str, ttl: timedelta) -> bool:
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        # One SET NX PX: Redis decides which of two concurrent callers stores the key.
        stored = await self._client.set(self._key(_CACHE_KEY, key), value, nx=True, px=_millis(ttl))
        return bool(stored)

    async def delete(self, key: str) -> None:
        await self._client.delete(self._key(_CACHE_KEY, key))

    async def publish(self, channel: str, message: str) -> None:
        await self._client.publish(self._key(_CHANNEL_KEY, channel), message)

    async def subscribe(self, channel: str) -> RedisSubscription:
        subscription = RedisSubscription(
            self._client,
            self._key(_CHANNEL_KEY, channel),
            on_close=self._subscriptions.discard,
        )
        self._subscriptions.add(subscription)
        await subscription.start()
        return subscription

    async def acquire_lock(self, name: str, ttl: timedelta) -> Lock | None:
        # The counter never expires, so tokens keep increasing across restarts (DEC-058 item 2).
        # After a data loss the clock term keeps them increasing (DEC-091).
        now_us = time.time_ns() // 1_000
        token: int = await self._client.eval(
            _NEXT_TOKEN, 1, self._key(_FENCE_KEY, name), str(now_us)
        )
        acquired = await self._client.set(
            self._key(_LOCK_KEY, name), str(token), nx=True, px=_millis(ttl)
        )
        if not acquired:
            return None
        return Lock(name=name, fencing_token=token, scope="")

    async def release_lock(self, lock: Lock) -> None:
        await self._client.eval(
            _RELEASE_IF_HOLDER, 1, self._key(_LOCK_KEY, lock.name), str(lock.fencing_token)
        )

    async def aclose(self) -> None:
        """Close every subscription this cache made, then the client."""
        for subscription in list(self._subscriptions):
            await subscription.aclose()
        await self._client.aclose()
