"""Pure tests of the R03 concurrency rules: ETags, If-Match, Idempotency-Key and the replay cache.

The replay cache runs on InMemoryCache (a test fake for the Cache port, which is allowed) and a
FixedClock, so no Neo4j or network is needed. Synthetic values only.
"""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from diucs.adapters.inbound.fhir_rest.concurrency import (
    ReplayCache,
    StoredResponse,
    body_hash,
    check_idempotency_key,
    check_version,
    etag_for,
    parse_if_match,
    scoped_key,
    subject_of,
)
from diucs.adapters.inbound.fhir_rest.errors import (
    HeaderRefused,
    PreconditionFailed,
    PreconditionRequired,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import Actor
from diucs.domain.codes import Role

T0 = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
REQUEST_BODY = b'{"resourceType":"TestThing","note":"synthetic request body text"}'
STORED = StoredResponse(
    status_code=201,
    headers={"ETag": 'W/"1"', "Content-Type": "application/fhir+json"},
    body=b'{"resourceType":"TestThing","id":"t-1"}',
)


def test_an_etag_is_weak_and_quotes_the_version() -> None:
    assert etag_for(3) == 'W/"3"'


@pytest.mark.parametrize("value", ['W/"3"', 'W/"12"'])
def test_a_weak_if_match_gives_its_version(value: str) -> None:
    assert parse_if_match(value) == int(value.split('"')[1])


def test_a_write_with_no_if_match_is_refused_with_428() -> None:
    with pytest.raises(PreconditionRequired):
        parse_if_match(None)


@pytest.mark.parametrize("value", ['"3"', 'W/"x"', 'W/"-1"', 'W/"03"', "*", 'W/""', ""])
def test_a_malformed_if_match_cannot_match_so_it_is_412(value: str) -> None:
    with pytest.raises(PreconditionFailed):
        parse_if_match(value)


def test_the_current_version_passes_the_check() -> None:
    check_version(3, 3)


def test_a_stale_version_fails_the_check_with_412() -> None:
    with pytest.raises(PreconditionFailed):
        check_version(2, 3)


def test_a_missing_stored_version_fails_the_check() -> None:
    with pytest.raises(PreconditionFailed):
        check_version(3, None)


@pytest.mark.parametrize("value", ["a", "k" * 200, "!~", 'key-"1"/x=y'])
def test_a_visible_ascii_key_of_1_to_200_characters_is_kept(value: str) -> None:
    assert check_idempotency_key(value) == value


@pytest.mark.parametrize("value", [None, ""])
def test_a_missing_key_is_400_required(value: str | None) -> None:
    with pytest.raises(HeaderRefused) as refused:
        check_idempotency_key(value)
    assert (refused.value.status_code, refused.value.code) == (400, "required")


@pytest.mark.parametrize("value", ["k" * 201, "has space", "café", "tab\tkey", "ctl\x7f"])
def test_a_key_outside_the_rule_is_400_invalid(value: str) -> None:
    with pytest.raises(HeaderRefused) as refused:
        check_idempotency_key(value)
    assert (refused.value.status_code, refused.value.code) == (400, "invalid")


def test_the_body_hash_is_sha256_of_the_bytes() -> None:
    assert body_hash(REQUEST_BODY) == hashlib.sha256(REQUEST_BODY).hexdigest()


def test_different_bodies_have_different_hashes() -> None:
    assert body_hash(REQUEST_BODY) != body_hash(REQUEST_BODY + b" ")


def test_a_practitioner_is_its_own_subject() -> None:
    actor = Actor(Role.LEAD, "pr-1", None, "api", frozenset())
    assert subject_of(actor) == "pr-1"


def test_a_wall_device_is_its_own_subject() -> None:
    actor = Actor(Role.WALL, None, "dev-7", "api", frozenset())
    assert subject_of(actor) == "dev-7"


def test_an_actor_with_no_subject_is_refused() -> None:
    actor = Actor(Role.LEAD, None, None, "api", frozenset())
    with pytest.raises(ValueError):
        subject_of(actor)


def test_the_scoped_key_follows_the_cache_name_rule() -> None:
    assert scoped_key("pr-1", "key-1") == "idem:pr-1:key-1"


def test_a_subject_with_a_colon_cannot_make_two_keys_collide() -> None:
    with pytest.raises(ValueError):
        scoped_key("pr:1", "key")


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(T0)


@pytest.fixture
def replay(clock: FixedClock) -> tuple[ReplayCache, InMemoryCache]:
    cache = InMemoryCache(clock)
    return ReplayCache(cache), cache


async def test_a_saved_response_comes_back_for_the_same_key_and_body(
    replay: tuple[ReplayCache, InMemoryCache],
) -> None:
    cache, _ = replay
    digest = body_hash(REQUEST_BODY)
    await cache.save("pr-1", "key-1", digest, STORED)
    assert await cache.lookup("pr-1", "key-1", digest) == STORED


async def test_a_saved_response_is_kept_for_24_hours_and_no_longer(
    replay: tuple[ReplayCache, InMemoryCache], clock: FixedClock
) -> None:
    cache, _ = replay
    digest = body_hash(REQUEST_BODY)
    await cache.save("pr-1", "key-1", digest, STORED)
    clock.set(T0 + timedelta(hours=24) - timedelta(seconds=1))
    assert await cache.lookup("pr-1", "key-1", digest) == STORED
    clock.set(T0 + timedelta(hours=24))
    assert await cache.lookup("pr-1", "key-1", digest) is None


async def test_the_same_key_with_another_body_is_422_conflict(
    replay: tuple[ReplayCache, InMemoryCache],
) -> None:
    cache, _ = replay
    await cache.save("pr-1", "key-1", body_hash(REQUEST_BODY), STORED)
    with pytest.raises(HeaderRefused) as refused:
        await cache.lookup("pr-1", "key-1", body_hash(REQUEST_BODY + b" "))
    assert (refused.value.status_code, refused.value.code) == (422, "conflict")


async def test_another_subject_has_its_own_entry(
    replay: tuple[ReplayCache, InMemoryCache],
) -> None:
    cache, _ = replay
    digest = body_hash(REQUEST_BODY)
    await cache.save("pr-1", "key-1", digest, STORED)
    assert await cache.lookup("pr-1", "key-1", digest) == STORED
    assert await cache.lookup("pr-2", "key-1", digest) is None


async def test_the_request_body_is_not_stored_only_its_hash_is(
    replay: tuple[ReplayCache, InMemoryCache],
) -> None:
    cache, raw = replay
    await cache.save("pr-1", "key-1", body_hash(REQUEST_BODY), STORED)
    stored_text = await raw.get("idem:pr-1:key-1")
    assert stored_text is not None
    assert "synthetic request body text" not in stored_text


async def test_an_unreadable_cached_entry_is_a_miss_not_an_answer(
    replay: tuple[ReplayCache, InMemoryCache],
) -> None:
    cache, raw = replay
    await raw.set("idem:pr-1:key-1", "not json at all")
    assert await cache.lookup("pr-1", "key-1", body_hash(REQUEST_BODY)) is None
