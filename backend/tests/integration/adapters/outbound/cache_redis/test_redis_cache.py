"""Redis-only cases of the cache adapter (I01, TEN-019). The shared cases run in tests/contract.

They need the Redis of infra/docker-compose.yml (REDIS_URL, default localhost:6379). Each test binds
its own run tenant (`ct<run>-<label>`, tests/support/redis.py), so the keys a test writes are
`diucs:<that tenant>:...` and overlapping runs share nothing. Subscriber counts come from PUBSUB
NUMSUB on a second client, so the adapter's own connections cannot hide a leak.
"""

import asyncio
import os
from collections.abc import Iterator
from datetime import timedelta
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.application.ports.outbound.cache import BOARD_UPDATES_CHANNEL
from diucs.application.tenancy import bind_tenant
from tests.contract.harness import next_message
from tests.support.redis import flush_tenant, run_tenant

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
PATIENCE = timedelta(seconds=2)
PROXY_DELAY = 0.3


def new_run_tenant() -> str:
    """A tenant for one test of this run: no other test or run uses it."""
    return run_tenant(f"i-{uuid4().hex[:8]}")


@pytest.fixture
def tenant() -> Iterator[str]:
    """This test's tenant, bound for the test (the integration conftest binds its own first)."""
    run = new_run_tenant()
    with bind_tenant(run):
        yield run


def channel_key(tenant: str) -> str:
    return f"diucs:{tenant}:chan:{BOARD_UPDATES_CHANNEL}"


async def subscriber_count(counter: Redis, key: str) -> int:
    counts = dict(await counter.pubsub_numsub(key))
    return int(counts[key])


async def test_closing_a_subscription_unsubscribes_it(tenant: str) -> None:
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    cache = RedisCache.from_url(REDIS_URL)
    try:
        subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        await cache.publish(BOARD_UPDATES_CHANNEL, "ready")
        assert await next_message(subscription, PATIENCE) == "ready"
        assert await subscriber_count(counter, channel_key(tenant)) == 1

        await subscription.aclose()

        assert await subscriber_count(counter, channel_key(tenant)) == 0
    finally:
        await cache.aclose()
        await flush_tenant(counter, tenant)
        await counter.aclose()


async def test_closing_the_cache_drops_its_live_subscriptions(tenant: str) -> None:
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    cache = RedisCache.from_url(REDIS_URL)
    try:
        subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        await cache.publish(BOARD_UPDATES_CHANNEL, "ready")
        assert await next_message(subscription, PATIENCE) == "ready"
        assert await subscriber_count(counter, channel_key(tenant)) == 1

        await cache.aclose()

        assert await subscriber_count(counter, channel_key(tenant)) == 0
    finally:
        await flush_tenant(counter, tenant)
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


async def test_a_publish_sent_as_soon_as_subscribe_returns_is_delivered(tenant: str) -> None:
    # DEC-092, made deterministic. The adapter's connection goes through a proxy that holds the
    # SUBSCRIBE for PROXY_DELAY. The publish comes from a direct connection straight after
    # subscribe() returns. With the server confirmation awaited, subscribe() returns after the
    # delay and the message arrives. With the wait removed, the publish is sent before the
    # SUBSCRIBE reaches Redis and is lost.
    upstream = urlparse(REDIS_URL).port or 6379
    proxy, proxy_port = await _start_delaying_proxy(upstream, PROXY_DELAY)
    publisher = Redis.from_url(REDIS_URL, decode_responses=True)
    cache = RedisCache(Redis(host="127.0.0.1", port=proxy_port, decode_responses=True))
    try:
        subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        await publisher.publish(channel_key(tenant), "first")
        assert await next_message(subscription, PATIENCE) == "first"
        await subscription.aclose()
    finally:
        await cache.aclose()
        proxy.close()
        await proxy.wait_closed()
        await flush_tenant(publisher, tenant)
        await publisher.aclose()


async def test_the_key_shapes_are_tenant_scoped_and_the_old_global_names_are_never_made(
    tenant: str,
) -> None:
    store = Redis.from_url(REDIS_URL, decode_responses=True)
    cache = RedisCache.from_url(REDIS_URL)
    try:
        await cache.set("svc-1:status", "accepting", PATIENCE)
        assert await store.get(f"diucs:{tenant}:cache:svc-1:status") == "accepting"

        lock = await cache.acquire_lock("relay", PATIENCE)
        assert lock is not None
        assert 0 < await store.pttl(f"diucs:{tenant}:lock:relay") <= 2000
        assert await store.pttl(f"diucs:{tenant}:fence:relay") == -1
        await cache.release_lock(lock)

        subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        assert await subscriber_count(store, channel_key(tenant)) == 1
        await subscription.aclose()

        assert await store.exists("diucs:chan:board.updates") == 0
        assert await store.exists("diucs:cache:board:v1") == 0
    finally:
        await cache.aclose()
        await flush_tenant(store, tenant)
        await store.aclose()


async def test_flushing_one_tenant_leaves_the_tenant_whose_id_it_prefixes(tenant: str) -> None:
    store = Redis.from_url(REDIS_URL, decode_responses=True)
    shorter, longer = tenant, f"{tenant}b"
    try:
        await store.set(f"diucs:{shorter}:cache:k", "1")
        await store.set(f"diucs:{longer}:cache:k", "2")
        await flush_tenant(store, shorter)
        assert await store.get(f"diucs:{shorter}:cache:k") is None
        assert await store.get(f"diucs:{longer}:cache:k") == "2"
    finally:
        await flush_tenant(store, longer)
        await store.aclose()


async def test_a_flush_refuses_a_tenant_that_is_not_this_runs(tenant: str) -> None:
    store = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await store.set("diucs:acme-icb:cache:k", "real")
        with pytest.raises(ValueError, match="not this run's"):
            await flush_tenant(store, "acme-icb")
        assert await store.get("diucs:acme-icb:cache:k") == "real"
    finally:
        await store.delete("diucs:acme-icb:cache:k")
        await store.aclose()


async def test_a_token_after_the_counter_is_lost_is_greater_than_every_token_before_it(
    tenant: str,
) -> None:
    # DEC-091: a Redis data loss resets the INCR counter. The token must still grow, because it is
    # at least the host clock in microseconds. The loss is simulated by deleting the counter key.
    # The other tenant's counter is not touched by it (TEN-019).
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    cache = RedisCache.from_url(REDIS_URL)
    other = run_tenant(f"i-{uuid4().hex[:8]}")
    try:
        last = 0
        for _ in range(3):
            lock = await cache.acquire_lock("relay", PATIENCE)
            assert lock is not None
            last = lock.fencing_token
            await cache.release_lock(lock)
        with bind_tenant(other):
            other_lock = await cache.acquire_lock("relay", PATIENCE)
            assert other_lock is not None
            await cache.release_lock(other_lock)
        other_before = await counter.get(f"diucs:{other}:fence:relay")

        await counter.delete(f"diucs:{tenant}:fence:relay")

        lock = await cache.acquire_lock("relay", PATIENCE)
        assert lock is not None
        assert lock.fencing_token > last
        assert await counter.get(f"diucs:{other}:fence:relay") == other_before
    finally:
        await cache.aclose()
        await flush_tenant(counter, tenant)
        await flush_tenant(counter, other)
        await counter.aclose()


async def test_each_lock_name_has_its_own_fencing_counter(tenant: str) -> None:
    # DEC-058 item 2: a counter per name. A shared counter would let one name's acquisitions move
    # another name's tokens, so both counters must exist after one acquisition each.
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    cache = RedisCache.from_url(REDIS_URL)
    try:
        for name in ("relay", "board"):
            lock = await cache.acquire_lock(name, PATIENCE)
            assert lock is not None
            await cache.release_lock(lock)
        assert await counter.exists(f"diucs:{tenant}:fence:relay") == 1
        assert await counter.exists(f"diucs:{tenant}:fence:board") == 1
    finally:
        await cache.aclose()
        await flush_tenant(counter, tenant)
        await counter.aclose()


async def test_a_subscriber_of_another_tenant_is_not_counted(tenant: str) -> None:
    # Two runs of this suite share one Redis, and the pub/sub channel names are global across its
    # databases. A subscriber another tenant holds on the same channel name must not appear in this
    # tenant's count (I01, TEN-019: the channel is the tenant's own).
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    other_tenant = run_tenant(f"i-{uuid4().hex[:8]}")
    cache = RedisCache.from_url(REDIS_URL)
    other = RedisCache.from_url(REDIS_URL)
    try:
        with bind_tenant(other_tenant):
            foreign = await other.subscribe(BOARD_UPDATES_CHANNEL)
        subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        assert await subscriber_count(counter, channel_key(tenant)) == 1
        assert await subscriber_count(counter, channel_key(other_tenant)) == 1
        await subscription.aclose()
        await foreign.aclose()
    finally:
        await cache.aclose()
        await other.aclose()
        await flush_tenant(counter, tenant)
        await flush_tenant(counter, other_tenant)
        await counter.aclose()
