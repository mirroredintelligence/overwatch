"""Pure tests of the in-memory cache fake (P09). Time is controlled by FixedClock."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from diucs.adapters.testing import memory_cache
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.ports.outbound.cache import (
    BOARD_UPDATES_CHANNEL,
    CacheScopeMismatch,
    Lock,
)
from diucs.application.tenancy import TenantNotBound, bind_tenant

START = datetime(2026, 10, 24, 10, 0, 0, tzinfo=UTC)
LONDON = ZoneInfo("Europe/London")
DELIVERY_WAIT = 1.0
TENANT = "acme-icb"
OTHER = "bridge-ccg"


@pytest.fixture(autouse=True)
def _bound_tenant(request: pytest.FixtureRequest) -> Iterator[None]:
    """Every test here runs with one tenant bound (TEN-019): the fake keys every value, lock,
    counter and channel by the bound scope. A test marked `no_tenant` runs with nothing bound."""
    if request.node.get_closest_marker("no_tenant") is not None:
        yield
        return
    with bind_tenant(TENANT):
        yield


def make_cache(at: datetime = START) -> tuple[InMemoryCache, FixedClock]:
    clock = FixedClock(at)
    return InMemoryCache(clock), clock


async def next_message(messages: AsyncIterator[str]) -> str:
    return await asyncio.wait_for(messages.__anext__(), timeout=DELIVERY_WAIT)


async def test_set_then_get_returns_the_value_and_delete_removes_it() -> None:
    cache, _ = make_cache()
    await cache.set("k", "v")
    assert await cache.get("k") == "v"
    await cache.delete("k")
    assert await cache.get("k") is None


async def test_get_of_a_missing_key_is_none_and_delete_of_a_missing_key_is_not_an_error() -> None:
    cache, _ = make_cache()
    assert await cache.get("absent") is None
    await cache.delete("absent")


async def test_set_overwrites_the_previous_value() -> None:
    cache, _ = make_cache()
    await cache.set("k", "first")
    await cache.set("k", "second")
    assert await cache.get("k") == "second"


async def test_a_key_without_ttl_does_not_expire() -> None:
    cache, clock = make_cache()
    await cache.set("k", "v")
    clock.advance(timedelta(days=365))
    assert await cache.get("k") == "v"


async def test_ttl_5_seconds_set_at_10_00_00_is_present_at_04_and_missing_at_05() -> None:
    cache, clock = make_cache(START)
    await cache.set("k", "v", ttl=timedelta(seconds=5))

    clock.set(datetime(2026, 10, 24, 10, 0, 4, tzinfo=UTC))
    assert await cache.get("k") == "v"

    clock.set(datetime(2026, 10, 24, 10, 0, 5, tzinfo=UTC))
    assert await cache.get("k") is None


async def test_an_expired_key_can_be_set_again() -> None:
    cache, clock = make_cache()
    await cache.set("k", "old", ttl=timedelta(seconds=5))
    clock.advance(timedelta(seconds=10))
    assert await cache.get("k") is None
    await cache.set("k", "new")
    assert await cache.get("k") == "new"


async def test_ttl_is_judged_on_the_real_instant_across_the_london_clock_change() -> None:
    # 2026-10-25 01:50 BST is 00:50 UTC. Ten minutes later is 01:00 UTC, which reads as
    # 01:00 GMT on the wall clock, so a wall-clock subtraction would get this wrong.
    clock = FixedClock(datetime(2026, 10, 25, 1, 50, tzinfo=LONDON))
    cache = InMemoryCache(clock)
    await cache.set("k", "v", ttl=timedelta(minutes=10))

    clock.set(datetime(2026, 10, 25, 0, 59, tzinfo=UTC))
    assert await cache.get("k") == "v"

    clock.set(datetime(2026, 10, 25, 1, 0, tzinfo=UTC))
    assert await cache.get("k") is None


async def test_two_subscribers_both_receive_a_message_published_after_they_subscribed() -> None:
    cache, _ = make_cache()
    first = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    second = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish(BOARD_UPDATES_CHANNEL, "x")
    assert await next_message(first) == "x"
    assert await next_message(second) == "x"


async def test_a_message_published_before_subscribing_is_not_received() -> None:
    cache, _ = make_cache()
    await cache.publish(BOARD_UPDATES_CHANNEL, "early")
    messages = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish(BOARD_UPDATES_CHANNEL, "late")
    assert await next_message(messages) == "late"


async def test_a_subscription_is_live_from_the_call_even_before_its_first_read() -> None:
    cache, _ = make_cache()
    messages = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish(BOARD_UPDATES_CHANNEL, "x")
    assert await next_message(messages) == "x"


async def test_a_subscriber_gets_only_its_own_channel() -> None:
    cache, _ = make_cache()
    messages = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish("other.channel", "wrong")
    await cache.publish(BOARD_UPDATES_CHANNEL, "right")
    assert await next_message(messages) == "right"


async def test_relay_lock_tokens_follow_the_holder_and_stale_releases_do_nothing() -> None:
    cache, clock = make_cache()

    first = await cache.acquire_lock("relay", timedelta(seconds=30))
    assert first == Lock("relay", 1, "acme-icb")
    assert await cache.acquire_lock("relay", timedelta(seconds=30)) is None

    clock.advance(timedelta(seconds=30))
    second = await cache.acquire_lock("relay", timedelta(seconds=30))
    assert second == Lock("relay", 2, "acme-icb")

    await cache.release_lock(Lock("relay", 1, "acme-icb"))
    assert await cache.acquire_lock("relay", timedelta(seconds=30)) is None

    await cache.release_lock(Lock("relay", 2, "acme-icb"))
    third = await cache.acquire_lock("relay", timedelta(seconds=30))
    assert third == Lock("relay", 3, "acme-icb")


async def test_a_lock_is_still_held_one_second_before_its_ttl_ends() -> None:
    cache, clock = make_cache()
    await cache.acquire_lock("relay", timedelta(seconds=30))
    clock.advance(timedelta(seconds=29))
    assert await cache.acquire_lock("relay", timedelta(seconds=30)) is None


async def test_lock_names_have_independent_tokens() -> None:
    cache, _ = make_cache()
    await cache.acquire_lock("relay", timedelta(seconds=30))
    assert await cache.acquire_lock("scheduler", timedelta(seconds=30)) == Lock(
        "scheduler", 1, "acme-icb"
    )


async def test_releasing_a_lock_for_a_name_that_was_never_held_does_nothing() -> None:
    cache, _ = make_cache()
    await cache.release_lock(Lock("nobody", 1, "acme-icb"))
    assert await cache.acquire_lock("nobody", timedelta(seconds=30)) == Lock(
        "nobody", 1, "acme-icb"
    )


def test_the_fake_is_documented_as_a_test_only_stand_in_for_redis() -> None:
    assert memory_cache.__doc__ is not None
    assert "Fake for tests only. Redis is the production cache" in memory_cache.__doc__


async def test_closing_a_subscription_removes_it_and_later_publishes_do_not_reach_it() -> None:
    cache, _ = make_cache()
    messages = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    assert cache.subscriber_count(BOARD_UPDATES_CHANNEL) == 1

    await messages.aclose()  # type: ignore[attr-defined]

    assert cache.subscriber_count(BOARD_UPDATES_CHANNEL) == 0
    await cache.publish(BOARD_UPDATES_CHANNEL, "after the close")


async def test_closing_one_subscription_leaves_the_other_subscribers_live() -> None:
    cache, _ = make_cache()
    closed = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    kept = await cache.subscribe(BOARD_UPDATES_CHANNEL)

    await closed.aclose()  # type: ignore[attr-defined]
    await cache.publish(BOARD_UPDATES_CHANNEL, "still here")

    assert cache.subscriber_count(BOARD_UPDATES_CHANNEL) == 1
    assert await next_message(kept) == "still here"


async def test_a_lock_is_held_one_millisecond_before_its_ttl_ends_and_free_at_the_instant() -> None:
    # DEC-058 item 3, at the exact instant: the contract checks this after the TTL on a real store.
    cache, clock = make_cache(START)
    ttl = timedelta(seconds=2)
    assert await cache.acquire_lock("relay", ttl) is not None

    clock.set(START + ttl - timedelta(milliseconds=1))
    assert await cache.acquire_lock("relay", ttl) is None

    clock.set(START + ttl)
    assert await cache.acquire_lock("relay", ttl) is not None


async def test_set_if_absent_stores_once_and_a_later_one_fails_until_the_ttl_passes() -> None:
    cache, clock = make_cache()
    ttl = timedelta(hours=24)
    assert await cache.set_if_absent("idem:sms:one", "1", ttl) is True
    assert await cache.set_if_absent("idem:sms:one", "2", ttl) is False
    clock.advance(ttl - timedelta(seconds=1))
    assert await cache.set_if_absent("idem:sms:one", "3", ttl) is False
    assert await cache.get("idem:sms:one") == "1"
    clock.advance(timedelta(seconds=1))
    assert await cache.set_if_absent("idem:sms:one", "4", ttl) is True
    assert await cache.get("idem:sms:one") == "4"


# Per tenant (TEN-019, DEC-130 item 6). Each test binds the tenant it names.


async def test_a_value_is_one_tenants_and_another_tenant_reads_none() -> None:
    cache, _ = make_cache()
    await cache.set("svc-1:status", "accepting")
    with bind_tenant(OTHER):
        assert await cache.get("svc-1:status") is None
        await cache.delete("svc-1:status")  # deletes nothing of the other tenant
    assert await cache.get("svc-1:status") == "accepting"


async def test_the_keys_are_the_scoped_names_without_the_root() -> None:
    cache, _ = make_cache()
    await cache.set("svc-1:status", "accepting")
    assert cache.keys() == frozenset({"acme-icb:cache:svc-1:status"})


async def test_ttl_is_per_key_and_per_scope() -> None:
    cache, clock = make_cache()
    await cache.set("svc-1:status", "a", ttl=timedelta(seconds=5))
    with bind_tenant(OTHER):
        await cache.set("svc-1:status", "b")
    clock.advance(timedelta(seconds=5))
    assert await cache.get("svc-1:status") is None
    with bind_tenant(OTHER):
        assert await cache.get("svc-1:status") == "b"


async def test_locks_and_fencing_counters_are_per_tenant() -> None:
    cache, _ = make_cache()
    first_a = await cache.acquire_lock("relay", timedelta(seconds=30))
    assert first_a == Lock("relay", 1, "acme-icb")
    with bind_tenant(OTHER):
        first_b = await cache.acquire_lock("relay", timedelta(seconds=30))
        assert first_b == Lock("relay", 1, "bridge-ccg")
    assert await cache.acquire_lock("relay", timedelta(seconds=30)) is None

    await cache.release_lock(first_a)
    second_a = await cache.acquire_lock("relay", timedelta(seconds=30))
    assert second_a == Lock("relay", 2, "acme-icb")
    with bind_tenant(OTHER):
        assert await cache.acquire_lock("relay", timedelta(seconds=30)) is None


async def test_a_lock_issued_in_one_tenant_released_in_another_is_refused_and_keeps_its_own() -> (
    None
):
    cache, _ = make_cache()
    issued_in_a = await cache.acquire_lock("relay", timedelta(seconds=30))
    assert issued_in_a is not None
    with bind_tenant(OTHER):
        held_in_b = await cache.acquire_lock("relay", timedelta(seconds=30))
        assert held_in_b == Lock("relay", 1, "bridge-ccg")
        with pytest.raises(CacheScopeMismatch, match="lock belongs to another scope"):
            await cache.release_lock(issued_in_a)
        assert await cache.acquire_lock("relay", timedelta(seconds=30)) is None


async def test_publish_and_subscribe_are_per_tenant_and_counted_per_tenant() -> None:
    cache, _ = make_cache()
    in_a = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    with bind_tenant(OTHER):
        in_b = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        assert cache.subscriber_count(BOARD_UPDATES_CHANNEL) == 1
    assert cache.subscriber_count(BOARD_UPDATES_CHANNEL) == 1

    await cache.publish(BOARD_UPDATES_CHANNEL, "a-message")
    with bind_tenant(OTHER):
        await cache.publish(BOARD_UPDATES_CHANNEL, "b-message")
    assert await next_message(in_a) == "a-message"
    assert await next_message(in_b) == "b-message"

    await in_a.aclose()  # type: ignore[attr-defined]
    assert cache.subscriber_count(BOARD_UPDATES_CHANNEL) == 0
    with bind_tenant(OTHER):
        assert cache.subscriber_count(BOARD_UPDATES_CHANNEL) == 1
        await cache.publish(BOARD_UPDATES_CHANNEL, "still-live")
        assert await next_message(in_b) == "still-live"


async def test_a_subscription_keeps_the_channel_it_was_made_in() -> None:
    cache, _ = make_cache()
    messages = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    with bind_tenant(OTHER):
        await cache.publish(BOARD_UPDATES_CHANNEL, "b-message")
        # Read under another binding: the subscription still belongs to the tenant it was made in.
        await cache.publish(BOARD_UPDATES_CHANNEL, "b-again")
    await cache.publish(BOARD_UPDATES_CHANNEL, "a-message")
    assert await next_message(messages) == "a-message"


@pytest.mark.no_tenant
@pytest.mark.parametrize(
    "call",
    [
        "get",
        "set",
        "set_if_absent",
        "delete",
        "publish",
        "subscribe",
        "acquire_lock",
        "release_lock",
    ],
)
async def test_with_no_tenant_bound_every_method_refuses_and_stores_nothing(call: str) -> None:
    cache, _ = make_cache()
    ttl = timedelta(seconds=30)
    lock = Lock("relay", 1, "acme-icb")
    attempts = {
        "get": lambda: cache.get("k"),
        "set": lambda: cache.set("k", "v"),
        "set_if_absent": lambda: cache.set_if_absent("k", "v", ttl),
        "delete": lambda: cache.delete("k"),
        "publish": lambda: cache.publish(BOARD_UPDATES_CHANNEL, "x"),
        "subscribe": lambda: cache.subscribe(BOARD_UPDATES_CHANNEL),
        "acquire_lock": lambda: cache.acquire_lock("relay", ttl),
        "release_lock": lambda: cache.release_lock(lock),
    }
    with pytest.raises(TenantNotBound, match="no tenant is bound for this work"):
        await attempts[call]()
    with bind_tenant(TENANT):
        assert cache.keys() == frozenset()
        assert cache.subscriber_count(BOARD_UPDATES_CHANNEL) == 0
        assert await cache.acquire_lock("relay", ttl) == Lock("relay", 1, "acme-icb")
