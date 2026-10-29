"""The Redis key path stores the TTL it was given (I01, TEN-019), read from the store's own clock.

The TTL contract cases check expiry on the wall clock, with a second of slack, so a cache that
stored half the TTL would still pass them. This test reads the TTL the store reports, with no
sleep, so a half-TTL store fails at once. The key sits under a run tenant only this test uses, and
the test removes it."""

from datetime import timedelta

import pytest
from redis.asyncio import Redis

from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.application.tenancy import bind_tenant
from diucs.bootstrap.settings import Settings
from tests.support.redis import flush_tenant, run_tenant

TTL = timedelta(seconds=10)
# Redis rounds to the millisecond and the reading happens a few ms after the write.
TOLERANCE_MS = 500


@pytest.mark.integration
async def test_a_key_is_stored_with_the_ttl_it_was_given() -> None:
    url = Settings().redis_url
    tenant = run_tenant("ttl-check")
    store = Redis.from_url(url, decode_responses=True)
    cache = RedisCache.from_url(url)
    try:
        with bind_tenant(tenant):
            await cache.set("svc-1:status", "accepting", TTL)
        remaining_ms = await store.pttl(f"diucs:{tenant}:cache:svc-1:status")
        requested_ms = int(TTL.total_seconds() * 1000)
        assert requested_ms - TOLERANCE_MS <= remaining_ms <= requested_ms
    finally:
        await cache.aclose()
        await flush_tenant(store, tenant)
        await store.aclose()
