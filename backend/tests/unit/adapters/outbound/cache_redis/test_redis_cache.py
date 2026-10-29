"""Pure tests of the Redis cache adapter (I01): a recording stub stands in for the Redis client.

No Docker is needed. The stub records every key or channel name the adapter passes to it, so a
test can check the key families (DEC-058, architecture.md) without a server.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest

from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.application.ports.outbound.cache import (
    BOARD_UPDATES_CHANNEL,
    CacheScopeMismatch,
    Lock,
)
from diucs.application.tenancy import TenantNotBound, bind_tenant

TTL = timedelta(seconds=5)
TENANT = "acme-icb"
OTHER = "bridge-ccg"
FAMILIES = {"cache", "lock", "fence", "chan"}


@pytest.fixture(autouse=True)
def _bound_tenant(request: pytest.FixtureRequest) -> Iterator[None]:
    """Every test here runs with one tenant bound (TEN-019). A test marked `no_tenant` does not."""
    if request.node.get_closest_marker("no_tenant") is not None:
        yield
        return
    with bind_tenant(TENANT):
        yield


class RecordingPubSub:
    """Answers subscribe and unsubscribe with the server's confirmation messages, in order."""

    def __init__(self, names: list[str]) -> None:
        self._names = names
        self._replies: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def subscribe(self, *channels: str) -> None:
        self._names.extend(channels)
        self._replies.put_nowait({"type": "subscribe", "channel": channels[0], "data": 1})

    async def unsubscribe(self, *channels: str) -> None:
        self._names.extend(channels)
        self._replies.put_nowait({"type": "unsubscribe", "channel": channels[0], "data": 0})

    async def get_message(
        self, ignore_subscribe_messages: bool = False, timeout: float | None = 0.0
    ) -> dict[str, Any] | None:
        del ignore_subscribe_messages, timeout
        return await self._replies.get()

    async def aclose(self) -> None:
        return None


class RecordingClient:
    """Records the key, channel and script arguments of every call."""

    def __init__(self) -> None:
        self.names: list[str] = []

    async def get(self, key: str) -> None:
        self.names.append(key)

    async def set(self, key: str, value: str, px: int | None = None, nx: bool = False) -> bool:
        self.names.append(key)
        return True

    async def delete(self, *keys: str) -> int:
        self.names.extend(keys)
        return len(keys)

    async def incr(self, key: str) -> int:
        self.names.append(key)
        return 1

    async def eval(self, script: str, numkeys: int, *args: str) -> int:
        self.names.extend(args[:numkeys])
        return 1

    async def publish(self, channel: str, message: str) -> int:
        self.names.append(channel)
        return 0

    def pubsub(self, **kwargs: Any) -> RecordingPubSub:
        return RecordingPubSub(self.names)

    async def aclose(self) -> None:
        return None


async def _every_method(cache: RedisCache) -> None:
    await cache.set("svc-1:status", "accepting", TTL)
    await cache.get("svc-1:status")
    await cache.set_if_absent("idem:sms:one", "1", TTL)
    await cache.delete("svc-1:status")
    await cache.publish(BOARD_UPDATES_CHANNEL, "svc-1")
    lock = await cache.acquire_lock("outbox-relay", TTL)
    assert lock is not None
    await cache.release_lock(lock)
    subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    await subscription.aclose()


async def test_every_name_the_adapter_passes_to_the_client_is_under_the_bound_tenant() -> None:
    client = RecordingClient()
    await _every_method(RedisCache(client))  # type: ignore[arg-type]

    assert client.names
    assert all(name.startswith(f"diucs:{TENANT}:") for name in client.names)


async def test_each_key_family_is_used_under_its_own_family_part_and_nothing_else() -> None:
    client = RecordingClient()
    await _every_method(RedisCache(client))  # type: ignore[arg-type]

    families = {name.split(":")[2] for name in client.names}
    assert families == FAMILIES
    assert {name.split(":")[1] for name in client.names} == {TENANT}
    assert not [name for name in client.names if name.startswith("diucs:cache:")]
    assert not [name for name in client.names if name.startswith("diucs:chan:")]


async def test_a_closed_subscription_ends_a_reader_that_is_waiting() -> None:
    cache = RedisCache(RecordingClient())  # type: ignore[arg-type]
    subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)

    async def next_or_none() -> str | None:
        try:
            return await subscription.__anext__()
        except StopAsyncIteration:
            return None

    waiting = asyncio.ensure_future(next_or_none())
    await asyncio.sleep(0)  # the reader now blocks on the empty queue
    await subscription.aclose()

    assert await asyncio.wait_for(waiting, timeout=1.0) is None


async def read_or_none(subscription: AsyncIterator[str]) -> str | None:
    try:
        return await subscription.__anext__()
    except StopAsyncIteration:
        return None


async def test_a_read_after_a_closed_subscription_has_ended_also_ends_at_once() -> None:
    cache = RedisCache(RecordingClient())  # type: ignore[arg-type]
    subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    await subscription.aclose()

    assert await asyncio.wait_for(read_or_none(subscription), timeout=1.0) is None
    assert await asyncio.wait_for(read_or_none(subscription), timeout=1.0) is None


class HeldConfirmationPubSub(RecordingPubSub):
    """The server's subscribe reply is withheld until the test releases it."""

    def __init__(self, names: list[str], release: asyncio.Event) -> None:
        super().__init__(names)
        self._release = release

    async def get_message(
        self, ignore_subscribe_messages: bool = False, timeout: float | None = 0.0
    ) -> dict[str, Any] | None:
        await self._release.wait()
        return await super().get_message(ignore_subscribe_messages, timeout)


class HeldConfirmationClient(RecordingClient):
    def __init__(self, release: asyncio.Event) -> None:
        super().__init__()
        self._release = release

    def pubsub(self, **kwargs: Any) -> HeldConfirmationPubSub:
        return HeldConfirmationPubSub(self.names, self._release)


async def test_subscribe_returns_only_after_the_server_confirms_the_subscription() -> None:
    # DEC-092: the subscription is live when subscribe() returns, so it must wait for the reply.
    release = asyncio.Event()
    cache = RedisCache(HeldConfirmationClient(release))  # type: ignore[arg-type]

    pending = asyncio.ensure_future(cache.subscribe(BOARD_UPDATES_CHANNEL))
    for _ in range(5):
        await asyncio.sleep(0)
    assert not pending.done()

    release.set()
    subscription = await asyncio.wait_for(pending, timeout=1.0)
    await subscription.aclose()


# Per tenant (TEN-019, DEC-130 item 6, audit C section 4.1): the old global names never appear.


@pytest.mark.no_tenant
@pytest.mark.parametrize(
    "call",
    ["get", "set", "set_if_absent", "delete", "publish", "subscribe", "acquire_lock", "release"],
)
async def test_with_no_tenant_bound_no_call_reaches_the_client(call: str) -> None:
    client = RecordingClient()
    cache = RedisCache(client)  # type: ignore[arg-type]
    lock = Lock("relay", 1, TENANT)
    attempts: dict[str, Callable[[], Any]] = {
        "get": lambda: cache.get("k"),
        "set": lambda: cache.set("k", "v", TTL),
        "set_if_absent": lambda: cache.set_if_absent("k", "v", TTL),
        "delete": lambda: cache.delete("k"),
        "publish": lambda: cache.publish(BOARD_UPDATES_CHANNEL, "x"),
        "subscribe": lambda: cache.subscribe(BOARD_UPDATES_CHANNEL),
        "acquire_lock": lambda: cache.acquire_lock("relay", TTL),
        "release": lambda: cache.release_lock(lock),
    }
    with pytest.raises(TenantNotBound, match="no tenant is bound for this work"):
        await attempts[call]()
    assert client.names == []


class RebindingClient(RecordingClient):
    """Binds another tenant, inside the named method, the first time that method reaches the client,
    and leaves it bound: the adapter must still use the scope it captured when its call began."""

    def __init__(self, on: str) -> None:
        super().__init__()
        self._on = on
        self._context: Any = None

    def _rebind(self, method: str) -> None:
        if method == self._on and self._context is None:
            self._context = bind_tenant(OTHER)
            self._context.__enter__()

    def release(self) -> None:
        if self._context is not None:
            self._context.__exit__(None, None, None)
            self._context = None

    async def eval(self, script: str, numkeys: int, *args: str) -> int:
        self._rebind("eval")
        return await super().eval(script, numkeys, *args)

    async def get(self, key: str) -> None:
        self._rebind("get")
        await super().get(key)

    async def publish(self, channel: str, message: str) -> int:
        self._rebind("publish")
        return await super().publish(channel, message)


async def test_acquire_lock_keeps_the_tenant_it_began_with_when_the_scope_moves() -> None:
    # The fence script rebinds the scope to the other tenant inside the call. The holder key is
    # still written under the tenant the call began with, and the lock is issued in that tenant.
    client = RebindingClient(on="eval")
    cache = RedisCache(client)  # type: ignore[arg-type]
    try:
        lock = await cache.acquire_lock("relay", TTL)
    finally:
        client.release()
    assert lock == Lock("relay", 1, TENANT)
    assert f"diucs:{TENANT}:lock:relay" in client.names
    assert not [name for name in client.names if OTHER in name]


async def test_a_get_keeps_the_tenant_it_began_with_when_the_scope_moves() -> None:
    client = RebindingClient(on="get")
    cache = RedisCache(client)  # type: ignore[arg-type]
    try:
        await cache.get("svc-1:status")
    finally:
        client.release()
    assert client.names == [f"diucs:{TENANT}:cache:svc-1:status"]


async def test_a_publish_keeps_the_tenant_it_began_with_when_the_scope_moves() -> None:
    client = RebindingClient(on="publish")
    cache = RedisCache(client)  # type: ignore[arg-type]
    try:
        await cache.publish(BOARD_UPDATES_CHANNEL, "svc-1")
    finally:
        client.release()
    assert client.names == [f"diucs:{TENANT}:chan:board.updates"]


async def test_releasing_a_lock_issued_in_another_tenant_is_refused_and_sends_nothing() -> None:
    client = RecordingClient()
    cache = RedisCache(client)  # type: ignore[arg-type]
    issued_in_a = Lock("relay", 1, TENANT)
    client.names.clear()
    with bind_tenant(OTHER), pytest.raises(CacheScopeMismatch, match="another scope"):
        await cache.release_lock(issued_in_a)
    assert client.names == []


def test_the_key_prefix_parameter_is_gone() -> None:
    with pytest.raises(TypeError):
        RedisCache(RecordingClient(), key_prefix="x")  # type: ignore[call-arg, arg-type]


async def test_a_subscription_is_removed_under_its_own_tenant_when_closed_in_another() -> None:
    client = RecordingClient()
    cache = RedisCache(client)  # type: ignore[arg-type]
    subscription = await cache.subscribe(BOARD_UPDATES_CHANNEL)
    client.names.clear()
    with bind_tenant(OTHER):
        await subscription.aclose()
    assert f"diucs:{TENANT}:chan:board.updates" in client.names
    assert not [name for name in client.names if OTHER in name]
