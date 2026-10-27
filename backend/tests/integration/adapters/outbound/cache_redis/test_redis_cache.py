"""Redis-only cases of the cache adapter (I01). The shared cases run in tests/contract.

They need the Redis of infra/docker-compose.yml (REDIS_URL, default localhost:6379). They touch
only keys under the diucs: prefix. Subscriber counts come from PUBSUB NUMSUB on a second client, so
the adapter's own connections cannot hide a leak.
"""

import os
from datetime import timedelta

from redis.asyncio import Redis

from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.application.ports.outbound.cache import BOARD_UPDATES_CHANNEL
from tests.contract.harness import next_message
from tests.support.redis import flush_diucs_keys

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CHANNEL_KEY = f"diucs:chan:{BOARD_UPDATES_CHANNEL}"
PATIENCE = timedelta(seconds=2)
SUBSCRIBE_ROUNDS = 400


async def subscriber_count(counter: Redis) -> int:
    counts = dict(await counter.pubsub_numsub(CHANNEL_KEY))
    return int(counts[CHANNEL_KEY])


async def test_closing_a_subscription_unsubscribes_it() -> None:
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    await flush_diucs_keys(counter)
    cache = RedisCache.from_url(REDIS_URL)
    try:
        subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        await cache.publish(BOARD_UPDATES_CHANNEL, "ready")
        assert await next_message(subscription, PATIENCE) == "ready"
        assert await subscriber_count(counter) == 1

        await subscription.aclose()

        assert await subscriber_count(counter) == 0
    finally:
        await cache.aclose()
        await flush_diucs_keys(counter)
        await counter.aclose()


async def test_closing_the_cache_drops_its_live_subscriptions() -> None:
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    await flush_diucs_keys(counter)
    cache = RedisCache.from_url(REDIS_URL)
    try:
        subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        await cache.publish(BOARD_UPDATES_CHANNEL, "ready")
        assert await next_message(subscription, PATIENCE) == "ready"
        assert await subscriber_count(counter) == 1

        await cache.aclose()

        assert await subscriber_count(counter) == 0
    finally:
        await flush_diucs_keys(counter)
        await counter.aclose()


async def test_a_publish_from_another_connection_right_after_subscribe_is_delivered() -> None:
    # DEC-092: subscribe() returns only once the server has the subscription, so a publish sent
    # from another connection straight after it cannot be lost. The publisher is a raw client,
    # so the adapter's own publish() cannot be the reason the message arrives.
    publisher = Redis.from_url(REDIS_URL, decode_responses=True)
    await flush_diucs_keys(publisher)
    cache = RedisCache.from_url(REDIS_URL)
    try:
        for number in range(SUBSCRIBE_ROUNDS):
            subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
            await publisher.publish(CHANNEL_KEY, f"round-{number}")
            assert await next_message(subscription, PATIENCE) == f"round-{number}"
            await subscription.aclose()
    finally:
        await cache.aclose()
        await flush_diucs_keys(publisher)
        await publisher.aclose()


async def test_a_token_after_the_counter_is_lost_is_greater_than_every_token_before_it() -> None:
    # DEC-091: a Redis data loss resets the INCR counter. The token must still grow, because it is
    # at least the host clock in microseconds. The loss is simulated by deleting the counter key.
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    await flush_diucs_keys(counter)
    cache = RedisCache.from_url(REDIS_URL)
    try:
        last = 0
        for _ in range(3):
            lock = await cache.acquire_lock("relay", PATIENCE)
            assert lock is not None
            last = lock.fencing_token
            await cache.release_lock(lock)

        await counter.delete("diucs:fence:relay")

        lock = await cache.acquire_lock("relay", PATIENCE)
        assert lock is not None
        assert lock.fencing_token > last
    finally:
        await cache.aclose()
        await flush_diucs_keys(counter)
        await counter.aclose()
