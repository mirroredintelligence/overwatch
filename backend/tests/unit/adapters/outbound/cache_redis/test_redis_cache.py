"""Pure tests of the Redis cache adapter (I01): a recording stub stands in for the Redis client.

No Docker is needed. The stub records every key or channel name the adapter passes to it, so a
test can check the key families (DEC-058, architecture.md) without a server.
"""

import asyncio
from datetime import timedelta
from typing import Any

from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.application.ports.outbound.cache import BOARD_UPDATES_CHANNEL

TTL = timedelta(seconds=5)


class RecordingPubSub:
    """Answers subscribe and unsubscribe with the server's confirmation messages, in order."""

    def __init__(self, names: list[str]) -> None:
        self._names = names
        self._replies: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def subscribe(self, *channels: str) -> None:
        self._names.extend(channels)
        self._replies.put_nowait({"type": "subscribe", "channel": channels[0], "data": 1})

    async def unsubscribe(self, *channels: str) -> None:
        self._names.extend(channels)
        self._replies.put_nowait({"type": "unsubscribe", "channel": channels[0], "data": 0})

    async def get_message(
        self, ignore_subscribe_messages: bool = False, timeout: float | None = 0.0
    ) -> dict[str, Any] | None:
        del ignore_subscribe_messages, timeout
        return await self._replies.get()

    async def aclose(self) -> None:
        return None


class RecordingClient:
    """Records the key, channel and script arguments of every call."""

    def __init__(self) -> None:
        self.names: list[str] = []

    async def get(self, key: str) -> None:
        self.names.append(key)

    async def set(self, key: str, value: str, px: int | None = None, nx: bool = False) -> bool:
        self.names.append(key)
        return True

    async def delete(self, *keys: str) -> int:
        self.names.extend(keys)
        return len(keys)

    async def incr(self, key: str) -> int:
        self.names.append(key)
        return 1

    async def eval(self, script: str, numkeys: int, *args: str) -> int:
        self.names.extend(args[:numkeys])
        return 1

    async def publish(self, channel: str, message: str) -> int:
        self.names.append(channel)
        return 0

    def pubsub(self, **kwargs: Any) -> RecordingPubSub:
        return RecordingPubSub(self.names)

    async def aclose(self) -> None:
        return None


async def test_every_name_the_adapter_passes_to_the_client_starts_with_diucs() -> None:
    client = RecordingClient()
    cache = RedisCache(client)  # type: ignore[arg-type]

    await cache.set("svc-1:status", "accepting", TTL)
    await cache.get("svc-1:status")
    await cache.delete("svc-1:status")
    await cache.publish(BOARD_UPDATES_CHANNEL, "svc-1")
    lock = await cache.acquire_lock("outbox-relay", TTL)
    assert lock is not None
    await cache.release_lock(lock)
    subscription = cache.subscribe(BOARD_UPDATES_CHANNEL)
    await subscription.aclose()

    assert client.names
    assert all(name.startswith("diucs:") for name in client.names)


async def test_each_key_family_is_used_under_its_own_prefix() -> None:
    client = RecordingClient()
    cache = RedisCache(client)  # type: ignore[arg-type]

    await cache.set("svc-1:status", "accepting", TTL)
    lock = await cache.acquire_lock("outbox-relay", TTL)
    assert lock is not None
    await cache.release_lock(lock)
    await cache.publish(BOARD_UPDATES_CHANNEL, "svc-1")

    families = {name.split(":")[1] for name in client.names}
    assert families == {"cache", "lock", "fence", "chan"}


async def test_a_closed_subscription_ends_a_reader_that_is_waiting() -> None:
    cache = RedisCache(RecordingClient())  # type: ignore[arg-type]
    subscription = cache.subscribe(BOARD_UPDATES_CHANNEL)

    async def next_or_none() -> str | None:
        try:
            return await subscription.__anext__()
        except StopAsyncIteration:
            return None

    waiting = asyncio.ensure_future(next_or_none())
    await subscription.aclose()

    assert await asyncio.wait_for(waiting, timeout=1.0) is None
