"""Contract for the cache port (P09, DEC-058). Runs against every factory in factories.py.

Durations are seconds, so a real adapter can run the same test in real time.
"""

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from uuid import uuid4

import pytest

from diucs.application.ports.outbound.cache import (
    BOARD_UPDATES_CHANNEL,
    Cache,
    CacheScopeMismatch,
    Lock,
    scoped_names,
)
from diucs.application.tenancy import ScopeId, TenantNotBound, bind_scope, bind_tenant
from tests.contract.harness import Harness, next_message
from tests.support.redis import run_tenant

TTL = timedelta(seconds=2)
ONE_SECOND = timedelta(seconds=1)
LONG_TTL = timedelta(seconds=10)
PATIENCE = timedelta(seconds=2)
QUIET = timedelta(milliseconds=200)


def _fresh_tenant(label: str) -> str:
    """A tenant no other test or run uses (TEN-019): two tests never share a key."""
    return run_tenant(f"{label}-{uuid4().hex[:8]}")


@pytest.fixture(autouse=True)
def _bound_tenant(request: pytest.FixtureRequest) -> Iterator[None]:
    """Each contract test runs with its own tenant bound (TEN-019). A test marked `no_tenant`
    runs with nothing bound, for the refusal cases."""
    if request.node.get_closest_marker("no_tenant") is not None:
        yield
        return
    with bind_tenant(_fresh_tenant("a")):
        yield


# Get, set and delete


async def test_get_of_a_missing_key_is_none(cache_harness: Harness[Cache]) -> None:
    assert await cache_harness.subject.get("svc-1:status") is None


async def test_set_then_get_returns_the_stored_value(cache_harness: Harness[Cache]) -> None:
    await cache_harness.subject.set("svc-1:status", "accepting")
    assert await cache_harness.subject.get("svc-1:status") == "accepting"


async def test_set_overwrites_the_previous_value(cache_harness: Harness[Cache]) -> None:
    await cache_harness.subject.set("svc-1:status", "accepting")
    await cache_harness.subject.set("svc-1:status", "not-updated")
    assert await cache_harness.subject.get("svc-1:status") == "not-updated"


async def test_delete_removes_the_key(cache_harness: Harness[Cache]) -> None:
    await cache_harness.subject.set("svc-1:status", "accepting")
    await cache_harness.subject.delete("svc-1:status")
    assert await cache_harness.subject.get("svc-1:status") is None


async def test_deleting_a_missing_key_is_not_an_error(cache_harness: Harness[Cache]) -> None:
    await cache_harness.subject.delete("never-set")


async def test_a_key_without_a_ttl_is_still_there_after_time_passes(
    cache_harness: Harness[Cache],
) -> None:
    await cache_harness.subject.set("svc-1:status", "accepting")
    await cache_harness.advance(TTL + ONE_SECOND)
    assert await cache_harness.subject.get("svc-1:status") == "accepting"


# TTL


# The TTL cases leave at least ONE_SECOND between every check and the expiry they test. A check
# on the expiry instant itself races the Redis clock: the probe saw a key still present at the
# second check, with 12 ms of TTL left, in 2 of 60 runs (DEC-102 item 12).


async def test_a_key_is_present_before_its_ttl(cache_harness: Harness[Cache]) -> None:
    await cache_harness.subject.set("svc-1:status", "accepting", LONG_TTL)
    await cache_harness.advance(ONE_SECOND)
    assert await cache_harness.subject.get("svc-1:status") == "accepting"


async def test_a_key_is_missing_once_its_ttl_has_passed(cache_harness: Harness[Cache]) -> None:
    await cache_harness.subject.set("svc-1:status", "accepting", TTL)
    await cache_harness.advance(TTL + ONE_SECOND)
    assert await cache_harness.subject.get("svc-1:status") is None


async def test_an_expired_key_can_be_set_again(cache_harness: Harness[Cache]) -> None:
    await cache_harness.subject.set("svc-1:status", "accepting", TTL)
    await cache_harness.advance(TTL + ONE_SECOND)
    await cache_harness.subject.set("svc-1:status", "not-updated")
    assert await cache_harness.subject.get("svc-1:status") == "not-updated"


# Set if absent (I07: the replay marker of the SMS webhook)


async def test_set_if_absent_stores_a_missing_key(cache_harness: Harness[Cache]) -> None:
    cache = cache_harness.subject
    assert await cache.set_if_absent("idem:sms:one", "1", LONG_TTL) is True
    assert await cache.get("idem:sms:one") == "1"


async def test_set_if_absent_leaves_an_existing_value_and_says_so(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    await cache.set("idem:sms:one", "first")
    assert await cache.set_if_absent("idem:sms:one", "second", LONG_TTL) is False
    assert await cache.get("idem:sms:one") == "first"


async def test_the_second_set_if_absent_of_one_key_is_refused(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    assert await cache.set_if_absent("idem:sms:one", "1", LONG_TTL) is True
    assert await cache.set_if_absent("idem:sms:one", "2", LONG_TTL) is False
    assert await cache.get("idem:sms:one") == "1"


async def test_set_if_absent_keeps_keys_apart(cache_harness: Harness[Cache]) -> None:
    cache = cache_harness.subject
    assert await cache.set_if_absent("idem:sms:a:one", "1", LONG_TTL) is True
    assert await cache.set_if_absent("idem:sms:b:one", "1", LONG_TTL) is True


async def test_a_key_set_if_absent_is_free_again_once_its_ttl_has_passed(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    assert await cache.set_if_absent("idem:sms:one", "1", TTL) is True
    await cache_harness.advance(TTL + ONE_SECOND)
    assert await cache.set_if_absent("idem:sms:one", "2", LONG_TTL) is True
    assert await cache.get("idem:sms:one") == "2"


async def test_a_refused_set_if_absent_does_not_extend_the_ttl(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    assert await cache.set_if_absent("idem:sms:one", "1", TTL) is True
    await cache_harness.advance(ONE_SECOND)
    assert await cache.set_if_absent("idem:sms:one", "2", LONG_TTL) is False
    await cache_harness.advance(TTL)
    assert await cache.get("idem:sms:one") is None


async def test_a_deleted_key_can_be_set_if_absent_again(cache_harness: Harness[Cache]) -> None:
    cache = cache_harness.subject
    assert await cache.set_if_absent("idem:sms:one", "1", LONG_TTL) is True
    await cache.delete("idem:sms:one")
    assert await cache.set_if_absent("idem:sms:one", "1", LONG_TTL) is True


async def test_of_many_concurrent_set_if_absent_calls_exactly_one_wins(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    results = await asyncio.gather(
        *(cache.set_if_absent("idem:sms:race", str(n), LONG_TTL) for n in range(20))
    )
    assert results.count(True) == 1
    assert results.count(False) == 19


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1)])
async def test_set_if_absent_refuses_a_ttl_that_is_not_positive_and_stores_nothing(
    cache_harness: Harness[Cache], ttl: timedelta
) -> None:
    cache = cache_harness.subject
    with pytest.raises(ValueError, match="ttl"):
        await cache.set_if_absent("idem:sms:one", "1", ttl)
    assert await cache.get("idem:sms:one") is None


# Publish and subscribe


async def test_a_subscriber_receives_a_message_published_after_it_subscribed(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish(BOARD_UPDATES_CHANNEL, "svc-1")
    assert await next_message(subscription, PATIENCE) == "svc-1"


async def test_a_message_published_between_subscribing_and_the_first_read_is_received(
    cache_harness: Harness[Cache],
) -> None:
    # DEC-058 item 1: the subscription exists from the call, not from the first read.
    cache = cache_harness.subject
    subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish(BOARD_UPDATES_CHANNEL, "first")
    await cache.publish(BOARD_UPDATES_CHANNEL, "second")
    assert await next_message(subscription, PATIENCE) == "first"
    assert await next_message(subscription, PATIENCE) == "second"


async def test_a_message_published_before_subscribing_is_not_replayed(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    await cache.publish(BOARD_UPDATES_CHANNEL, "early")
    subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish(BOARD_UPDATES_CHANNEL, "late")
    assert await next_message(subscription, PATIENCE) == "late"


async def test_every_subscriber_to_a_channel_receives_the_message(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    first = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    second = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish(BOARD_UPDATES_CHANNEL, "svc-1")
    assert await next_message(first, PATIENCE) == "svc-1"
    assert await next_message(second, PATIENCE) == "svc-1"


async def test_a_subscriber_gets_only_its_own_channel(cache_harness: Harness[Cache]) -> None:
    cache = cache_harness.subject
    subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish("other.channel", "svc-1")
    assert await next_message(subscription, QUIET) is None


async def test_a_subscription_can_be_read_with_async_for(cache_harness: Harness[Cache]) -> None:
    # The port returns AsyncIterator[str], so async iteration is part of the contract.
    cache = cache_harness.subject
    subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish(BOARD_UPDATES_CHANNEL, "svc-1")

    async def first_by_async_for() -> str:
        async for message in subscription:
            return message
        raise AssertionError("the subscription ended without a message")

    assert await asyncio.wait_for(first_by_async_for(), PATIENCE.total_seconds()) == "svc-1"


async def test_publishing_stores_nothing_in_the_cache(cache_harness: Harness[Cache]) -> None:
    await cache_harness.subject.publish(BOARD_UPDATES_CHANNEL, "svc-1")
    assert await cache_harness.subject.get(BOARD_UPDATES_CHANNEL) is None


# Single-flight locks with fencing tokens


async def test_a_held_lock_is_not_granted_again(cache_harness: Harness[Cache]) -> None:
    cache = cache_harness.subject
    assert await cache.acquire_lock("relay", TTL) is not None
    assert await cache.acquire_lock("relay", TTL) is None


async def test_a_lock_name_gets_a_positive_first_token_of_its_own(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    relay = await cache.acquire_lock("relay", TTL)
    assert relay is not None
    await cache.release_lock(relay)
    other = await cache.acquire_lock("board", TTL)
    assert other is not None
    assert other.fencing_token > 0


async def test_fencing_tokens_increase_with_each_acquisition_of_one_name(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    first = await cache.acquire_lock("relay", TTL)
    assert first is not None
    await cache.release_lock(first)
    second = await cache.acquire_lock("relay", TTL)
    assert second is not None
    assert second.name == "relay"
    assert second.fencing_token > first.fencing_token


async def test_the_holder_can_release_and_the_lock_is_free_again(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    held = await cache.acquire_lock("relay", TTL)
    assert held is not None
    await cache.release_lock(held)
    assert await cache.acquire_lock("relay", TTL) is not None


async def test_a_lock_is_held_until_its_ttl_and_free_after(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    first = await cache.acquire_lock("relay", TTL)
    assert first is not None
    await cache_harness.advance(ONE_SECOND)
    assert await cache.acquire_lock("relay", TTL) is None
    await cache_harness.advance(TTL + ONE_SECOND)
    again = await cache.acquire_lock("relay", TTL)
    assert again is not None
    assert again.fencing_token > first.fencing_token


async def test_a_lock_is_free_once_its_ttl_has_passed(cache_harness: Harness[Cache]) -> None:
    # DEC-058 item 3 (held while now < expires_at, free from expires_at on). The exact instant is
    # checked on the in-memory fake's fixed clock (test_memory_cache.py). This case checks well
    # after the TTL on the store's own clock, with a second of slack.
    cache = cache_harness.subject
    assert await cache.acquire_lock("relay", TTL) is not None
    await cache_harness.advance(TTL + ONE_SECOND)
    assert await cache.acquire_lock("relay", TTL) is not None


async def test_a_stale_holder_cannot_release_a_newer_holders_lock(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    stale = await cache.acquire_lock("relay", TTL)
    assert stale is not None
    await cache_harness.advance(TTL + ONE_SECOND)
    current = await cache.acquire_lock("relay", TTL)
    assert current is not None
    await cache.release_lock(stale)
    assert await cache.acquire_lock("relay", TTL) is None


async def test_releasing_a_lock_nobody_holds_does_nothing(cache_harness: Harness[Cache]) -> None:
    cache = cache_harness.subject
    await cache.release_lock(Lock(name="never-held", fencing_token=1, scope=scoped_names().segment))
    lock = await cache.acquire_lock("never-held", TTL)
    assert lock is not None
    assert lock.fencing_token > 0


# Per tenant (TEN-019, DEC-130 item 6, DEC-132 items 1 and 4). Each test names the tenants it uses.


@pytest.fixture
def two_tenants() -> tuple[str, str]:
    """The tenant bound for the test, and a second one (the autouse fixture binds the first)."""
    return _fresh_tenant("a"), _fresh_tenant("b")


async def test_the_same_key_holds_one_value_per_tenant(
    cache_harness: Harness[Cache], two_tenants: tuple[str, str]
) -> None:
    cache = cache_harness.subject
    first, second = two_tenants
    await cache.set("svc-1:status", "accepting")
    with bind_tenant(second):
        assert await cache.get("svc-1:status") is None
        await cache.set("svc-1:status", "full")
        assert await cache.get("svc-1:status") == "full"
        await cache.delete("svc-1:status")
    assert await cache.get("svc-1:status") == "accepting"
    with bind_tenant(second):
        assert await cache.get("svc-1:status") is None


async def test_a_key_expires_in_one_tenant_and_not_in_another(
    cache_harness: Harness[Cache], two_tenants: tuple[str, str]
) -> None:
    cache = cache_harness.subject
    _, second = two_tenants
    await cache.set("svc-1:status", "short", TTL)
    with bind_tenant(second):
        await cache.set("svc-1:status", "long", LONG_TTL)
    await cache_harness.advance(TTL)
    assert await cache.get("svc-1:status") is None
    with bind_tenant(second):
        assert await cache.get("svc-1:status") == "long"


async def test_a_message_reaches_only_its_own_tenants_subscribers(
    cache_harness: Harness[Cache], two_tenants: tuple[str, str]
) -> None:
    cache = cache_harness.subject
    _, second = two_tenants
    in_first = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    with bind_tenant(second):
        in_second = await cache.subscribe(BOARD_UPDATES_CHANNEL)

    await cache.publish(BOARD_UPDATES_CHANNEL, "from-first")
    assert await next_message(in_first, PATIENCE) == "from-first"
    assert await next_message(in_second, QUIET) is None

    with bind_tenant(second):
        await cache.publish(BOARD_UPDATES_CHANNEL, "from-second")
        assert await next_message(in_second, PATIENCE) == "from-second"
    assert await next_message(in_first, QUIET) is None


async def test_a_message_published_before_subscribing_is_not_replayed_in_any_tenant(
    cache_harness: Harness[Cache], two_tenants: tuple[str, str]
) -> None:
    cache = cache_harness.subject
    _, second = two_tenants
    with bind_tenant(second):
        await cache.publish(BOARD_UPDATES_CHANNEL, "early-in-second")
    late = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    assert await next_message(late, QUIET) is None


async def test_a_lock_is_free_in_another_tenant_and_its_tokens_only_go_up_in_its_own(
    cache_harness: Harness[Cache], two_tenants: tuple[str, str]
) -> None:
    cache = cache_harness.subject
    _, second = two_tenants
    first_a = await cache.acquire_lock("relay", LONG_TTL)
    assert first_a is not None and first_a.fencing_token > 0
    assert await cache.acquire_lock("relay", LONG_TTL) is None
    with bind_tenant(second):
        first_b = await cache.acquire_lock("relay", LONG_TTL)
        assert first_b is not None and first_b.fencing_token > 0

    await cache.release_lock(first_a)
    second_a = await cache.acquire_lock("relay", LONG_TTL)
    assert second_a is not None and second_a.fencing_token > first_a.fencing_token
    await cache.release_lock(second_a)
    third_a = await cache.acquire_lock("relay", LONG_TTL)
    assert third_a is not None and third_a.fencing_token > second_a.fencing_token

    await cache.release_lock(third_a)
    with bind_tenant(second):
        assert await cache.acquire_lock("relay", LONG_TTL) is None


async def test_a_lock_released_while_another_tenant_is_bound_is_refused_and_the_other_lock_holds(
    cache_harness: Harness[Cache], two_tenants: tuple[str, str]
) -> None:
    cache = cache_harness.subject
    _, second = two_tenants
    issued_in_first = await cache.acquire_lock("relay", LONG_TTL)
    assert issued_in_first is not None
    with bind_tenant(second):
        held_in_second = await cache.acquire_lock("relay", LONG_TTL)
        assert held_in_second is not None
        with pytest.raises(CacheScopeMismatch):
            await cache.release_lock(issued_in_first)
        assert await cache.acquire_lock("relay", LONG_TTL) is None


@pytest.mark.no_tenant
async def test_with_no_tenant_bound_every_method_refuses(cache_harness: Harness[Cache]) -> None:
    cache = cache_harness.subject
    with pytest.raises(TenantNotBound, match="no tenant is bound for this work"):
        await cache.get("k")
    with pytest.raises(TenantNotBound):
        await cache.set("k", "v")
    with pytest.raises(TenantNotBound):
        await cache.set_if_absent("k", "v", TTL)
    with pytest.raises(TenantNotBound):
        await cache.delete("k")
    with pytest.raises(TenantNotBound):
        await cache.publish(BOARD_UPDATES_CHANNEL, "x")
    with pytest.raises(TenantNotBound):
        await cache.subscribe(BOARD_UPDATES_CHANNEL)
    with pytest.raises(TenantNotBound):
        await cache.acquire_lock("relay", TTL)
    with pytest.raises(TenantNotBound):
        await cache.release_lock(Lock("relay", 1, "acme-icb"))


async def test_the_board_cache_and_live_channel_do_not_cross_tenants(
    cache_harness: Harness[Cache], two_tenants: tuple[str, str]
) -> None:
    # Audit C 4.1 and hazard H-T05: the board's cache key and its channel were global, so a wall
    # screen of one tenant could show another tenant's board and receive its service ids.
    cache = cache_harness.subject
    first, second = two_tenants
    board_a = '{"services":["svc-a"]}'
    board_b = '{"services":["svc-b"]}'
    with bind_tenant(second):
        in_second = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    with bind_tenant(first):
        in_first = await cache.subscribe(BOARD_UPDATES_CHANNEL)
        await cache.set("board:v1", board_a, LONG_TTL)
        await cache.publish(BOARD_UPDATES_CHANNEL, "svc-a")
        assert await next_message(in_first, PATIENCE) == "svc-a"
    with bind_tenant(second):
        assert await cache.get("board:v1") is None
        assert await next_message(in_second, QUIET) is None
        await cache.set("board:v1", board_b, LONG_TTL)
        await cache.publish(BOARD_UPDATES_CHANNEL, "svc-b")
        assert await next_message(in_second, PATIENCE) == "svc-b"
    with bind_tenant(first):
        assert await cache.get("board:v1") == board_a
        assert await next_message(in_first, QUIET) is None


async def test_a_network_scope_and_a_tenant_hold_their_own_values_and_messages(
    cache_harness: Harness[Cache], two_tenants: tuple[str, str]
) -> None:
    cache = cache_harness.subject
    _, tenant = two_tenants
    network = ScopeId.network(f"net-{uuid4().hex[:12]}")
    with bind_scope(network):
        await cache.set("board:v1", "network-board", LONG_TTL)
        on_network = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    with bind_tenant(tenant):
        assert await cache.get("board:v1") is None
        await cache.set("board:v1", "tenant-board", LONG_TTL)
        await cache.publish(BOARD_UPDATES_CHANNEL, "tenant-message")
    assert await next_message(on_network, QUIET) is None
    with bind_scope(network):
        assert await cache.get("board:v1") == "network-board"
    with bind_tenant(tenant):
        assert await cache.get("board:v1") == "tenant-board"


# The platform namespace (TEN-040): markers that belong to no tenant, for the limiter of the routes
# with no token. Each test uses names of its own, which expire on their own (the harness removes
# only the keys of its run tenants).


def _platform_name(label: str) -> str:
    return f"rl:contract:{label}-{uuid4().hex[:12]}"


async def test_a_platform_marker_is_taken_once(cache_harness: Harness[Cache]) -> None:
    name = _platform_name("once")
    assert await cache_harness.subject.platform_take(name, LONG_TTL) is True  # type: ignore[attr-defined]
    assert await cache_harness.subject.platform_take(name, LONG_TTL) is False  # type: ignore[attr-defined]
    await cache_harness.subject.platform_release(name)  # type: ignore[attr-defined]


async def test_a_released_platform_marker_is_free_and_a_missing_one_is_no_error(
    cache_harness: Harness[Cache],
) -> None:
    name = _platform_name("release")
    await cache_harness.subject.platform_take(name, LONG_TTL)  # type: ignore[attr-defined]
    await cache_harness.subject.platform_release(name)  # type: ignore[attr-defined]
    await cache_harness.subject.platform_release(_platform_name("never"))  # type: ignore[attr-defined]
    assert await cache_harness.subject.platform_take(name, LONG_TTL) is True  # type: ignore[attr-defined]
    await cache_harness.subject.platform_release(name)  # type: ignore[attr-defined]


async def test_a_platform_marker_expires(cache_harness: Harness[Cache]) -> None:
    name = _platform_name("expiry")
    assert await cache_harness.subject.platform_take(name, ONE_SECOND) is True  # type: ignore[attr-defined]
    await cache_harness.advance(ONE_SECOND + ONE_SECOND)
    assert await cache_harness.subject.platform_take(name, ONE_SECOND) is True  # type: ignore[attr-defined]
    await cache_harness.subject.platform_release(name)  # type: ignore[attr-defined]


async def test_a_platform_marker_is_one_whichever_tenant_is_bound(
    cache_harness: Harness[Cache],
) -> None:
    name = _platform_name("shared")
    assert await cache_harness.subject.platform_take(name, LONG_TTL) is True  # type: ignore[attr-defined]
    with bind_tenant(_fresh_tenant("b")):
        assert await cache_harness.subject.platform_take(name, LONG_TTL) is False  # type: ignore[attr-defined]
    await cache_harness.subject.platform_release(name)  # type: ignore[attr-defined]


async def test_a_platform_marker_and_a_tenant_value_of_one_name_do_not_meet(
    cache_harness: Harness[Cache],
) -> None:
    name = _platform_name("apart")
    await cache_harness.subject.set(name, "tenant-value")
    assert await cache_harness.subject.platform_take(name, LONG_TTL) is True  # type: ignore[attr-defined]
    assert await cache_harness.subject.get(name) == "tenant-value"
    await cache_harness.subject.platform_release(name)  # type: ignore[attr-defined]
