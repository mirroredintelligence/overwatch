"""The names a network scope holds in Redis, and who can see them (TEN-062, DEC-130 item 7,
DEC-132 item 4, DEC-547 item 1, TEN-019).

Every key, lock and channel is `diucs:<scope>:<family>:<name>`, and a network's scope segment is
`_net-<id>`, which no tenant id can begin with. The tests show on a real Redis: the network board is
cached under its network's own segment and no other; the same logical name in a tenant scope and in
a network scope, or in two networks, is three keys and three channels; a message published in one
network's scope reaches that network's subscribers and no other's, and not a tenant's with the same
text for an id; deleting a key in one scope leaves the others; a lock of one scope is not the lock
of another; the board's cache entry names no tenant, grant or service; and the stream's event
carries a time and nothing else.
"""

import json
import os
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from diucs.adapters.inbound.fhir_rest.routes_network_events import to_network_sse
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.application.ports.outbound.cache import (
    BOARD_UPDATES_CHANNEL,
    NETWORK_BOARD_UPDATES_CHANNEL,
    CacheScopeMismatch,
)
from diucs.application.tenancy import bind_network, bind_tenant
from diucs.application.use_cases.network_board_projector import (
    NETWORK_BOARD_CACHE_KEY,
    NETWORK_BOARD_CACHE_TTL,
    NETWORK_BOARD_CHANGED,
)
from tests.contract.harness import next_message
from tests.support.redis import flush_tenant, run_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
PATIENCE = timedelta(seconds=2)
SILENCE = timedelta(seconds=0.4)
BOARD = "board:v1:all"


@pytest.fixture
def net_a(network_id: str) -> str:
    return network_id


@pytest.fixture
def net_b(network_id: str) -> str:
    return f"{network_id}-b"


@pytest.fixture
def tenant() -> str:
    return run_tenant("k-net")


@pytest_asyncio.fixture(loop_scope="session")
async def redis(net_a: str, net_b: str, tenant: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    await _wipe(client, net_a, net_b, tenant)
    yield client
    await _wipe(client, net_a, net_b, tenant)
    await client.aclose()


@pytest_asyncio.fixture(loop_scope="session")
async def cache() -> AsyncIterator[RedisCache]:
    store = RedisCache.from_url(REDIS_URL)
    yield store
    await store.aclose()


async def _wipe(client: Redis, net_a: str, net_b: str, tenant: str) -> None:
    for network in (net_a, net_b):
        keys = [k async for k in client.scan_iter(match=f"diucs:_{network}:*")]
        if keys:
            await client.delete(*keys)
    await flush_tenant(client, tenant)


async def _keys(client: Redis, segment: str) -> list[str]:
    return sorted([k async for k in client.scan_iter(match=f"diucs:{segment}:*")])


# ------------------------------------------------------------------ keys


async def test_a_network_key_sits_under_the_networks_own_segment_and_no_other(
    cache: RedisCache, redis: Redis, net_a: str, net_b: str, tenant: str
) -> None:
    with bind_network(net_a):
        await cache.set(NETWORK_BOARD_CACHE_KEY, "board-a", NETWORK_BOARD_CACHE_TTL)
    assert await _keys(redis, f"_{net_a}") == [f"diucs:_{net_a}:cache:{NETWORK_BOARD_CACHE_KEY}"]
    assert await _keys(redis, f"_{net_b}") == []
    assert await _keys(redis, tenant) == []
    ttl = await redis.pttl(f"diucs:_{net_a}:cache:{NETWORK_BOARD_CACHE_KEY}")
    assert 0 < ttl <= NETWORK_BOARD_CACHE_TTL / timedelta(milliseconds=1)


async def test_one_logical_name_in_a_tenant_and_two_networks_is_three_keys(
    cache: RedisCache, redis: Redis, net_a: str, net_b: str, tenant: str
) -> None:
    with bind_tenant(tenant):
        await cache.set(BOARD, "tenant", timedelta(seconds=30))
    with bind_network(net_a):
        await cache.set(BOARD, "network-a", timedelta(seconds=30))
    with bind_network(net_b):
        await cache.set(BOARD, "network-b", timedelta(seconds=30))
    with bind_tenant(tenant):
        assert await cache.get(BOARD) == "tenant"
    with bind_network(net_a):
        assert await cache.get(BOARD) == "network-a"
    with bind_network(net_b):
        assert await cache.get(BOARD) == "network-b"
    assert len(await _keys(redis, tenant)) == len(await _keys(redis, f"_{net_a}")) == 1


async def test_a_network_id_used_as_a_tenant_id_is_a_different_segment(
    cache: RedisCache, redis: Redis, net_a: str
) -> None:
    """`_net-x` can never be a tenant's segment: a tenant id cannot begin with an underscore, and
    the network's own id (`net-x`) is not a tenant id either."""
    with bind_network(net_a):
        await cache.set(BOARD, "network", timedelta(seconds=30))
    assert await _keys(redis, net_a) == []
    assert await _keys(redis, f"_{net_a}") != []


async def test_a_delete_in_one_scope_leaves_the_others(
    cache: RedisCache, net_a: str, net_b: str, tenant: str
) -> None:
    for scope in (bind_network(net_a), bind_network(net_b), bind_tenant(tenant)):
        with scope:
            await cache.set(BOARD, "v", timedelta(seconds=30))
    with bind_network(net_a):
        await cache.delete(BOARD)
        assert await cache.get(BOARD) is None
    with bind_network(net_b):
        assert await cache.get(BOARD) == "v"
    with bind_tenant(tenant):
        assert await cache.get(BOARD) == "v"


async def test_the_cached_board_holds_no_tenant_grant_or_source_service(
    cache: RedisCache, redis: Redis, net_a: str
) -> None:
    from datetime import UTC, datetime

    from diucs.application.use_cases.network_board_projector import network_board_to_dict
    from diucs.application.use_cases.query_network_board import NetworkBoardView
    from diucs.domain.codes import Status
    from tests.support.network_board_samples import board_entry, board_of

    view = NetworkBoardView(
        board_of(
            board_entry("lst-1", "North", Status.ACCEPTING),
            at=datetime(2026, 10, 26, 9, 40, tzinfo=UTC),
        ),
        "Capacity board",
        "Urgent pathway",
        "Europe/London",
    )
    with bind_network(net_a):
        await cache.set(NETWORK_BOARD_CACHE_KEY, json.dumps(network_board_to_dict(view)))
    stored = await redis.get(f"diucs:_{net_a}:cache:{NETWORK_BOARD_CACHE_KEY}")
    assert stored is not None
    for forbidden in ("tenant", "grant", "sourceService", "source_service", net_a):
        assert forbidden not in stored


# ------------------------------------------------------------------ locks


async def test_a_lock_of_one_scope_is_not_the_lock_of_another(
    cache: RedisCache, net_a: str, net_b: str, tenant: str
) -> None:
    with bind_network(net_a):
        lock_a = await cache.acquire_lock("rebuild", timedelta(seconds=5))
    with bind_network(net_b):
        lock_b = await cache.acquire_lock("rebuild", timedelta(seconds=5))
    with bind_tenant(tenant):
        lock_t = await cache.acquire_lock("rebuild", timedelta(seconds=5))
        with pytest.raises(CacheScopeMismatch):
            assert lock_a is not None
            await cache.release_lock(lock_a)
    assert lock_a is not None and lock_b is not None and lock_t is not None
    assert len({lock_a.scope, lock_b.scope, lock_t.scope}) == 3
    with bind_network(net_a):
        assert await cache.acquire_lock("rebuild", timedelta(seconds=5)) is None
        await cache.release_lock(lock_a)
    with bind_network(net_b):
        await cache.release_lock(lock_b)
    with bind_tenant(tenant):
        await cache.release_lock(lock_t)


# ------------------------------------------------------------------ channels


async def test_a_message_in_one_network_reaches_that_network_and_no_other(
    cache: RedisCache, net_a: str, net_b: str, tenant: str
) -> None:
    with bind_network(net_a):
        in_a = await cache.subscribe(NETWORK_BOARD_UPDATES_CHANNEL)
    with bind_network(net_b):
        in_b = await cache.subscribe(NETWORK_BOARD_UPDATES_CHANNEL)
    with bind_tenant(tenant):
        in_tenant = await cache.subscribe(NETWORK_BOARD_UPDATES_CHANNEL)
        in_board = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    try:
        with bind_network(net_a):
            await cache.publish(NETWORK_BOARD_UPDATES_CHANNEL, "changed-a")
        assert await next_message(in_a, PATIENCE) == "changed-a"
        for other in (in_b, in_tenant, in_board):
            assert await next_message(other, SILENCE) is None
    finally:
        for subscription in (in_a, in_b, in_tenant, in_board):
            await subscription.aclose()  # type: ignore[attr-defined]


async def test_a_tenants_board_message_never_reaches_a_network_stream(
    cache: RedisCache, net_a: str, tenant: str
) -> None:
    with bind_network(net_a):
        stream = await cache.subscribe(NETWORK_BOARD_UPDATES_CHANNEL)
    try:
        with bind_tenant(tenant):
            await cache.publish(BOARD_UPDATES_CHANNEL, "tenant-board-changed")
            await cache.publish(NETWORK_BOARD_UPDATES_CHANNEL, "same-name-in-a-tenant")
        assert await next_message(stream, SILENCE) is None
    finally:
        await stream.aclose()  # type: ignore[attr-defined]


async def test_a_network_message_never_reaches_a_tenants_board_stream(
    cache: RedisCache, net_a: str, tenant: str
) -> None:
    with bind_tenant(tenant):
        board = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    try:
        with bind_network(net_a):
            await cache.publish(BOARD_UPDATES_CHANNEL, "x")
            await cache.publish(NETWORK_BOARD_UPDATES_CHANNEL, "y")
        assert await next_message(board, SILENCE) is None
    finally:
        await board.aclose()  # type: ignore[attr-defined]


async def test_a_subscription_keeps_the_scope_it_was_opened_in(
    cache: RedisCache, net_a: str, net_b: str
) -> None:
    with bind_network(net_a):
        stream = await cache.subscribe(NETWORK_BOARD_UPDATES_CHANNEL)
    try:
        with bind_network(net_b):
            await cache.publish(NETWORK_BOARD_UPDATES_CHANNEL, "b")
        with bind_network(net_a):
            await cache.publish(NETWORK_BOARD_UPDATES_CHANNEL, "a")
        assert await next_message(stream, PATIENCE) == "a"
    finally:
        await stream.aclose()  # type: ignore[attr-defined]


# ------------------------------------------------------------------ what the stream says


async def test_the_stream_event_carries_a_time_and_nothing_else() -> None:
    message = {
        "type": NETWORK_BOARD_CHANGED,
        "at": "2026-10-26T09:40:00+00:00",
        "tenant_id": "tenant-b",
        "network_id": "net-pilot",
        "service": "UCR West",
    }
    event = to_network_sse(message)
    assert event is not None
    assert event == 'event: network-board\ndata: {"changedAt":"2026-10-26T09:40:00Z"}\n\n'
    for forbidden in ("tenant", "net-pilot", "UCR West"):
        assert forbidden not in event


@pytest.mark.parametrize(
    "message",
    [{"type": "board-changed", "at": "2026-10-26T09:40:00Z"}, {"type": NETWORK_BOARD_CHANGED}, "x"],
)
async def test_a_message_that_is_not_a_network_board_change_is_not_an_event(
    message: object,
) -> None:
    assert to_network_sse(message) is None
