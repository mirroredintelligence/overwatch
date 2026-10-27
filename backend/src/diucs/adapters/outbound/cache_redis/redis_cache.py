"""Redis adapter for the cache port (I01, DEC-003, DEC-058).

Redis holds only transient data: losing every key loses no fact (DEC-001). Key families, all under
the diucs: prefix: cache values, lock holders, fencing counters and pub/sub channels. Values are
text. The client must decode responses (from_url does), so replies are str.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from typing import Self, cast

from redis.asyncio import Redis

from diucs.application.ports.outbound.cache import Lock

_CACHE_KEY = "diucs:cache:{}"
_LOCK_KEY = "diucs:lock:{}"
_FENCE_KEY = "diucs:fence:{}"
_CHANNEL_KEY = "diucs:chan:{}"

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
    """Messages published to one channel, from the moment the subscription is made (DEC-058 item 1).

    The SUBSCRIBE runs in a task started by the constructor. `opened` finishes once the server has
    confirmed it. RedisCache.publish waits for every open subscription before it sends, so a
    publish made by the same cache after subscribe() is never missed.
    """

    def __init__(
        self,
        client: Redis,
        key: str,
        on_close: Callable[[RedisSubscription], None],
    ) -> None:
        self._pubsub = client.pubsub()
        self._key = key
        self._on_close = on_close
        self._messages: asyncio.Queue[str] = asyncio.Queue()
        self._closed = False
        self.opened: asyncio.Task[None] = asyncio.get_running_loop().create_task(self._open())
        self._reader: asyncio.Task[None] | None = None

    async def _open(self) -> None:
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
        await self.opened
        return await self._messages.get()

    async def aclose(self) -> None:
        """Unsubscribe and wait for the server to confirm it, then release the connection."""
        if self._closed:
            return
        self._closed = True
        self._on_close(self)
        with contextlib.suppress(Exception):
            # A subscription that never opened has nothing to unsubscribe.
            await self.opened
        if self._reader is not None:
            await self._pubsub.unsubscribe(self._key)
            await self._reader  # the pump returns on the unsubscribe reply
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
        # from_url sets decode_responses=True, so a reply is text; the stubs also allow bytes.
        value = await self._client.get(_CACHE_KEY.format(key))
        return cast("str | None", value)

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        px = None if ttl is None else _millis(ttl)
        await self._client.set(_CACHE_KEY.format(key), value, px=px)

    async def delete(self, key: str) -> None:
        await self._client.delete(_CACHE_KEY.format(key))

    async def publish(self, channel: str, message: str) -> None:
        # Wait until every subscription this cache made has been confirmed by the server. A
        # subscription that failed to open is reported to its own reader, not to this publisher.
        await asyncio.gather(*(s.opened for s in self._subscriptions), return_exceptions=True)
        await self._client.publish(_CHANNEL_KEY.format(channel), message)

    def subscribe(self, channel: str) -> RedisSubscription:
        subscription = RedisSubscription(
            self._client,
            _CHANNEL_KEY.format(channel),
            on_close=self._subscriptions.discard,
        )
        self._subscriptions.add(subscription)
        return subscription

    async def acquire_lock(self, name: str, ttl: timedelta) -> Lock | None:
        # The counter never expires, so tokens keep increasing across restarts (DEC-058 item 2).
        token: int = await self._client.incr(_FENCE_KEY.format(name))
        acquired = await self._client.set(
            _LOCK_KEY.format(name), str(token), nx=True, px=_millis(ttl)
        )
        if not acquired:
            return None
        return Lock(name=name, fencing_token=token)

    async def release_lock(self, lock: Lock) -> None:
        await self._client.eval(
            _RELEASE_IF_HOLDER, 1, _LOCK_KEY.format(lock.name), str(lock.fencing_token)
        )

    async def aclose(self) -> None:
        """Close every subscription this cache made, then the client."""
        for subscription in list(self._subscriptions):
            await subscription.aclose()
        await self._client.aclose()
