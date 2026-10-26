"""Contract for the cache port (P09, DEC-058). Runs against every factory in factories.py.

Durations are seconds, so a real adapter can run the same test in real time.
"""

import asyncio
from datetime import timedelta

from diucs.application.ports.outbound.cache import BOARD_UPDATES_CHANNEL, Cache, Lock
from tests.contract.harness import Harness, next_message

TTL = timedelta(seconds=2)
ONE_SECOND = timedelta(seconds=1)
PATIENCE = timedelta(seconds=2)
QUIET = timedelta(milliseconds=200)


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


async def test_a_key_is_present_before_its_ttl_and_missing_once_it_has_passed(
    cache_harness: Harness[Cache],
) -> None:
    await cache_harness.subject.set("svc-1:status", "accepting", TTL)
    await cache_harness.advance(ONE_SECOND)
    assert await cache_harness.subject.get("svc-1:status") == "accepting"
    await cache_harness.advance(ONE_SECOND)
    assert await cache_harness.subject.get("svc-1:status") is None


async def test_an_expired_key_can_be_set_again(cache_harness: Harness[Cache]) -> None:
    await cache_harness.subject.set("svc-1:status", "accepting", TTL)
    await cache_harness.advance(TTL + ONE_SECOND)
    await cache_harness.subject.set("svc-1:status", "not-updated")
    assert await cache_harness.subject.get("svc-1:status") == "not-updated"


# Publish and subscribe


async def test_a_subscriber_receives_a_message_published_after_it_subscribed(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    subscription = cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish(BOARD_UPDATES_CHANNEL, "svc-1")
    assert await next_message(subscription, PATIENCE) == "svc-1"


async def test_a_message_published_between_subscribing_and_the_first_read_is_received(
    cache_harness: Harness[Cache],
) -> None:
    # DEC-058 item 1: the subscription exists from the call, not from the first read.
    cache = cache_harness.subject
    subscription = cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish(BOARD_UPDATES_CHANNEL, "first")
    await cache.publish(BOARD_UPDATES_CHANNEL, "second")
    assert await next_message(subscription, PATIENCE) == "first"
    assert await next_message(subscription, PATIENCE) == "second"


async def test_a_message_published_before_subscribing_is_not_replayed(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    await cache.publish(BOARD_UPDATES_CHANNEL, "early")
    subscription = cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish(BOARD_UPDATES_CHANNEL, "late")
    assert await next_message(subscription, PATIENCE) == "late"


async def test_every_subscriber_to_a_channel_receives_the_message(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    first = cache.subscribe(BOARD_UPDATES_CHANNEL)
    second = cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish(BOARD_UPDATES_CHANNEL, "svc-1")
    assert await next_message(first, PATIENCE) == "svc-1"
    assert await next_message(second, PATIENCE) == "svc-1"


async def test_a_subscriber_gets_only_its_own_channel(cache_harness: Harness[Cache]) -> None:
    cache = cache_harness.subject
    subscription = cache.subscribe(BOARD_UPDATES_CHANNEL)
    await cache.publish("other.channel", "svc-1")
    assert await next_message(subscription, QUIET) is None


async def test_a_subscription_can_be_read_with_async_for(cache_harness: Harness[Cache]) -> None:
    # The port returns AsyncIterator[str], so async iteration is part of the contract.
    cache = cache_harness.subject
    subscription = cache.subscribe(BOARD_UPDATES_CHANNEL)
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


async def test_a_lock_name_starts_its_own_token_count_at_one(
    cache_harness: Harness[Cache],
) -> None:
    cache = cache_harness.subject
    relay = await cache.acquire_lock("relay", TTL)
    assert relay is not None
    await cache.release_lock(relay)
    other = await cache.acquire_lock("board", TTL)
    assert other is not None
    assert other.fencing_token == 1


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


async def test_a_lock_is_free_at_the_instant_its_ttl_ends(cache_harness: Harness[Cache]) -> None:
    # DEC-058 item 3: held while now < expires_at, free from expires_at on.
    cache = cache_harness.subject
    assert await cache.acquire_lock("relay", TTL) is not None
    await cache_harness.advance(TTL)
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
    await cache.release_lock(Lock(name="never-held", fencing_token=1))
    lock = await cache.acquire_lock("never-held", TTL)
    assert lock is not None
    assert lock.fencing_token == 1
