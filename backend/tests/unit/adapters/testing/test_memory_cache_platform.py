"""The in-memory cache's platform namespace (TEN-040): one marker per name, an expiry, a release,
nothing shared with a tenant's names, and no scope needed."""

from datetime import UTC, datetime, timedelta

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.tenancy import bind_tenant, current_scope_or_none

START = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
WINDOW = timedelta(minutes=1)


def _cache() -> tuple[InMemoryCache, FixedClock]:
    clock = FixedClock(START)
    return InMemoryCache(clock), clock


async def test_a_marker_is_taken_once_with_no_scope_bound() -> None:
    cache, _ = _cache()
    assert current_scope_or_none() is None
    assert await cache.platform_take("rl:a#0", WINDOW) is True
    assert await cache.platform_take("rl:a#0", WINDOW) is False


async def test_a_marker_comes_free_when_its_window_ends() -> None:
    cache, clock = _cache()
    await cache.platform_take("rl:a#0", WINDOW)
    clock.advance(WINDOW - timedelta(seconds=1))
    assert await cache.platform_take("rl:a#0", WINDOW) is False
    clock.advance(timedelta(seconds=1))
    assert await cache.platform_take("rl:a#0", WINDOW) is True


async def test_a_released_marker_can_be_taken_again_and_a_missing_one_is_no_error() -> None:
    cache, _ = _cache()
    await cache.platform_take("rl:a#0", WINDOW)
    await cache.platform_release("rl:a#0")
    await cache.platform_release("rl:never")
    assert await cache.platform_take("rl:a#0", WINDOW) is True


async def test_a_platform_marker_and_a_tenant_value_of_one_name_are_two_entries() -> None:
    cache, _ = _cache()
    with bind_tenant("acme-icb"):
        await cache.set("rl:a#0", "1", WINDOW)
        assert await cache.platform_take("rl:a#0", WINDOW) is True
        assert await cache.get("rl:a#0") == "1"
    assert await cache.platform_take("rl:a#0", WINDOW) is False


async def test_a_platform_marker_is_the_same_whichever_tenant_is_bound() -> None:
    cache, _ = _cache()
    with bind_tenant("acme-icb"):
        assert await cache.platform_take("rl:a#0", WINDOW) is True
    with bind_tenant("bridge-ccg"):
        assert await cache.platform_take("rl:a#0", WINDOW) is False


async def test_a_ttl_that_is_not_positive_is_refused() -> None:
    cache, _ = _cache()
    with pytest.raises(ValueError):
        await cache.platform_take("rl:a#0", timedelta(0))
