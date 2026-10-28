"""The Redis key path stores the TTL it was given (I01), read from the store's own clock.

The TTL contract cases check expiry on the wall clock, with a second of slack, so a cache that
stored half the TTL would still pass them. This test reads the TTL the store reports, with no
sleep, so a half-TTL store fails at once. The keys sit under a prefix only this test uses, and
the test removes them."""

import uuid
from datetime import timedelta

import pytest
from redis.asyncio import Redis

from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.bootstrap.settings import Settings
from tests.support.redis import flush_prefix

TTL = timedelta(seconds=10)
# Redis rounds to the millisecond and the reading happens a few ms after the write.
TOLERANCE_MS = 500


@pytest.mark.integration
async def test_a_key_is_stored_with_the_ttl_it_was_given() -> None:
    url = Settings().redis_url
    prefix = f"diucs-ttl-check-{uuid.uuid4().hex}:"
    store = Redis.from_url(url, decode_responses=True)
    cache = RedisCache.from_url(url, key_prefix=prefix)
    try:
        await cache.set("svc-1:status", "accepting", TTL)
        remaining_ms = await store.pttl(f"{prefix}cache:svc-1:status")
        requested_ms = int(TTL.total_seconds() * 1000)
        assert requested_ms - TOLERANCE_MS <= remaining_ms <= requested_ms
    finally:
        await cache.aclose()
        await flush_prefix(store, prefix)
        await store.aclose()
