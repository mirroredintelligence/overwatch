"""The platform limiter of the unauthenticated routes (TEN-040, audit C TEN-C25): a count of events
per source address in a window, kept in the platform namespace, so it can be taken before any
tenant is known. The address is hashed before it reaches the cache."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.rate_limits import (
    PUBLIC_REQUESTS_PER_ADDRESS,
    PUBLIC_WINDOW,
    PlatformRateLimiter,
)
from diucs.application.tenancy import bind_tenant, current_scope_or_none

START = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
WINDOW = timedelta(minutes=1)


def _limiter() -> tuple[PlatformRateLimiter, InMemoryCache, FixedClock]:
    clock = FixedClock(START)
    cache = InMemoryCache(clock)
    return PlatformRateLimiter(cache), cache, clock


def test_the_public_budget_is_sixty_a_minute_an_address() -> None:
    assert PUBLIC_REQUESTS_PER_ADDRESS == 60
    assert PUBLIC_WINDOW == WINDOW


async def test_events_up_to_the_limit_take_a_slot_and_the_next_does_not() -> None:
    limiter, _, _ = _limiter()
    slots = [await limiter.take("public", "203.0.113.9", 3, WINDOW) for _ in range(3)]
    assert all(slot is not None for slot in slots)
    assert len(set(slots)) == 3
    assert await limiter.take("public", "203.0.113.9", 3, WINDOW) is None


async def test_it_needs_no_tenant_bound() -> None:
    limiter, _, _ = _limiter()
    assert current_scope_or_none() is None
    assert await limiter.take("public", "203.0.113.9", 1, WINDOW) is not None


async def test_the_bound_tenant_makes_no_difference_to_the_count() -> None:
    limiter, _, _ = _limiter()
    with bind_tenant("acme-icb"):
        assert await limiter.take("public", "203.0.113.9", 1, WINDOW) is not None
    with bind_tenant("bridge-ccg"):
        assert await limiter.take("public", "203.0.113.9", 1, WINDOW) is None


async def test_two_addresses_and_two_kinds_count_apart() -> None:
    limiter, _, _ = _limiter()
    assert await limiter.take("public", "203.0.113.9", 1, WINDOW) is not None
    assert await limiter.take("public", "198.51.100.4", 1, WINDOW) is not None
    assert await limiter.take("other", "203.0.113.9", 1, WINDOW) is not None
    assert await limiter.take("public", "203.0.113.9", 1, WINDOW) is None


async def test_a_slot_comes_free_one_window_after_it_was_taken() -> None:
    limiter, _, clock = _limiter()
    await limiter.take("public", "203.0.113.9", 1, WINDOW)
    clock.advance(WINDOW)
    assert await limiter.take("public", "203.0.113.9", 1, WINDOW) is not None


async def test_a_released_slot_can_be_taken_again() -> None:
    limiter, _, _ = _limiter()
    slot = await limiter.take("public", "203.0.113.9", 1, WINDOW)
    assert slot is not None
    await limiter.release(slot)
    assert await limiter.take("public", "203.0.113.9", 1, WINDOW) is not None


async def test_the_cache_holds_the_hash_of_the_address_never_the_address() -> None:
    limiter, cache, _ = _limiter()
    slot = await limiter.take("public", "203.0.113.9", 1, WINDOW)
    assert slot is not None
    digest = hashlib.sha256(b"203.0.113.9").hexdigest()[:32]
    assert digest in slot
    assert "203.0.113.9" not in slot
    assert cache.platform_keys() == frozenset({f"_:cache:{slot}"})


@pytest.mark.parametrize("limit", [0, -1])
async def test_a_limit_below_one_is_refused(limit: int) -> None:
    limiter, _, _ = _limiter()
    with pytest.raises(ValueError):
        await limiter.take("public", "203.0.113.9", limit, WINDOW)


@pytest.mark.parametrize("kind", ["", "Public", "a b", "a#b", "a:b", "x" * 33])
async def test_a_kind_outside_the_pattern_is_refused(kind: str) -> None:
    limiter, _, _ = _limiter()
    with pytest.raises(ValueError):
        await limiter.take(kind, "203.0.113.9", 1, WINDOW)


async def test_an_unknown_address_is_counted_as_one_address_not_let_through() -> None:
    limiter, _, _ = _limiter()
    assert await limiter.take("public", "", 1, WINDOW) is not None
    assert await limiter.take("public", "", 1, WINDOW) is None
