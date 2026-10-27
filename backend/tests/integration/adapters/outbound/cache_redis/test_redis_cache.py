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


async def subscriber_count(counter: Redis) -> int:
    counts = dict(await counter.pubsub_numsub(CHANNEL_KEY))
    return int(counts[CHANNEL_KEY])


async def test_closing_a_subscription_unsubscribes_it() -> None:
    counter = Redis.from_url(REDIS_URL, decode_responses=True)
    await flush_diucs_keys(counter)
    cache = RedisCache.from_url(REDIS_URL)
    try:
        subscription = cache.subscribe(BOARD_UPDATES_CHANNEL)
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
        subscription = cache.subscribe(BOARD_UPDATES_CHANNEL)
        await cache.publish(BOARD_UPDATES_CHANNEL, "ready")
        assert await next_message(subscription, PATIENCE) == "ready"
        assert await subscriber_count(counter) == 1

        await cache.aclose()

        assert await subscriber_count(counter) == 0
    finally:
        await flush_diucs_keys(counter)
        await counter.aclose()
