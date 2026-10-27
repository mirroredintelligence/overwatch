"""Redis-only cases of the cache adapter (I01). The shared cases run in tests/contract.

They need the Redis of infra/docker-compose.yml (REDIS_URL, default localhost:6379). They touch
only keys under a per-run prefix (diucs-integration-<uuid>:), so overlapping runs share nothing.
Subscriber counts come from PUBSUB NUMSUB on a second client, so the adapter's own connections
cannot hide a leak.
"""

import asyncio
import os
from datetime import timedelta
from urllib.parse import urlparse
from uuid import uuid4

from redis.asyncio import Redis

from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.application.ports.outbound.cache import BOARD_UPDATES_CHANNEL
from tests.contract.harness import next_message
from tests.support.redis import flush_prefix

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
PATIENCE = timedelta(seconds=2)
PROXY_DELAY = 0.3


def run_prefix() -> str:
    """This run's key prefix. Concurrent runs on one Redis share no keys or channels."""
    return f"diucs-integration-{uuid4().hex}:"


def channel_key(prefix: str) -> str:
    return f"{prefix}chan:{BOARD_UPDATES_CHANNEL}"


async def subscriber_count(counter: Redis, key: str) -> int:
    counts = dict(await counter.pubsub_numsub(key))
    return int(counts[key])


async def test_closing_a_subscription_unsubscribes_it() -> None:
    prefix = run_prefix()
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    cache = RedisCache.from_url(REDIS_URL, key_prefix=prefix)
    try:
        subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        await cache.publish(BOARD_UPDATES_CHANNEL, "ready")
        assert await next_message(subscription, PATIENCE) == "ready"
        assert await subscriber_count(counter, channel_key(prefix)) == 1

        await subscription.aclose()

        assert await subscriber_count(counter, channel_key(prefix)) == 0
    finally:
        await cache.aclose()
        await flush_prefix(counter, prefix)
        await counter.aclose()


async def test_closing_the_cache_drops_its_live_subscriptions() -> None:
    prefix = run_prefix()
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    cache = RedisCache.from_url(REDIS_URL, key_prefix=prefix)
    try:
        subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        await cache.publish(BOARD_UPDATES_CHANNEL, "ready")
        assert await next_message(subscription, PATIENCE) == "ready"
        assert await subscriber_count(counter, channel_key(prefix)) == 1

        await cache.aclose()

        assert await subscriber_count(counter, channel_key(prefix)) == 0
    finally:
        await flush_prefix(counter, prefix)
        await counter.aclose()


async def _relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, delay: float) -> None:
    try:
        while data := await reader.read(65536):
            if delay:
                await asyncio.sleep(delay)
            writer.write(data)
            await writer.drain()
    except ConnectionError:
        pass
    finally:
        writer.close()


async def _start_delaying_proxy(upstream_port: int, delay: float) -> tuple[asyncio.Server, int]:
    """A TCP proxy that holds each client-to-server chunk for `delay` seconds."""

    async def handle(
        client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        up_reader, up_writer = await asyncio.open_connection("127.0.0.1", upstream_port)
        await asyncio.gather(
            _relay(client_reader, up_writer, delay), _relay(up_reader, client_writer, 0.0)
        )

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def test_a_publish_sent_as_soon_as_subscribe_returns_is_delivered() -> None:
    # DEC-092, made deterministic. The adapter's connection goes through a proxy that holds the
    # SUBSCRIBE for PROXY_DELAY. The publish comes from a direct connection straight after
    # subscribe() returns. With the server confirmation awaited, subscribe() returns after the
    # delay and the message arrives. With the wait removed, the publish is sent before the
    # SUBSCRIBE reaches Redis and is lost.
    prefix = run_prefix()
    upstream = urlparse(REDIS_URL).port or 6379
    proxy, proxy_port = await _start_delaying_proxy(upstream, PROXY_DELAY)
    publisher = Redis.from_url(REDIS_URL, decode_responses=True)
    cache = RedisCache(
        Redis(host="127.0.0.1", port=proxy_port, decode_responses=True), key_prefix=prefix
    )
    try:
        subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        await publisher.publish(channel_key(prefix), "first")
        assert await next_message(subscription, PATIENCE) == "first"
        await subscription.aclose()
    finally:
        await cache.aclose()
        proxy.close()
        await proxy.wait_closed()
        await flush_prefix(publisher, prefix)
        await publisher.aclose()


async def test_a_token_after_the_counter_is_lost_is_greater_than_every_token_before_it() -> None:
    # DEC-091: a Redis data loss resets the INCR counter. The token must still grow, because it is
    # at least the host clock in microseconds. The loss is simulated by deleting the counter key.
    prefix = run_prefix()
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    cache = RedisCache.from_url(REDIS_URL, key_prefix=prefix)
    try:
        last = 0
        for _ in range(3):
            lock = await cache.acquire_lock("relay", PATIENCE)
            assert lock is not None
            last = lock.fencing_token
            await cache.release_lock(lock)

        await counter.delete(f"{prefix}fence:relay")

        lock = await cache.acquire_lock("relay", PATIENCE)
        assert lock is not None
        assert lock.fencing_token > last
    finally:
        await cache.aclose()
        await flush_prefix(counter, prefix)
        await counter.aclose()


async def test_each_lock_name_has_its_own_fencing_counter() -> None:
    # DEC-058 item 2: a counter per name. A shared counter would let one name's acquisitions move
    # another name's tokens, so both counters must exist after one acquisition each.
    prefix = run_prefix()
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    cache = RedisCache.from_url(REDIS_URL, key_prefix=prefix)
    try:
        for name in ("relay", "board"):
            lock = await cache.acquire_lock(name, PATIENCE)
            assert lock is not None
            await cache.release_lock(lock)
        assert await counter.exists(f"{prefix}fence:relay") == 1
        assert await counter.exists(f"{prefix}fence:board") == 1
    finally:
        await cache.aclose()
        await flush_prefix(counter, prefix)
        await counter.aclose()


async def test_a_subscriber_of_another_run_is_not_counted() -> None:
    # Two runs of this suite share one Redis, and pub/sub channel names are global across its
    # databases. A subscriber another run holds on the same channel must not appear in this run's
    # count (I01; the overlap failure: "assert 2 == 1" in two of five overlapping pairs).
    prefix = run_prefix()
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    other = RedisCache.from_url(REDIS_URL)
    cache = RedisCache.from_url(REDIS_URL, key_prefix=prefix)
    try:
        foreign = await other.subscribe(BOARD_UPDATES_CHANNEL)
        subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        assert await subscriber_count(counter, channel_key(prefix)) == 1
        await subscription.aclose()
        await foreign.aclose()
    finally:
        await cache.aclose()
        await other.aclose()
        await counter.aclose()
