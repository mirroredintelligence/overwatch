"""Adapter factories for the contract suites (P12).

Each list holds one `pytest.param(factory, id=...)` per adapter of its port. The memory fakes are
in every normal run. A real adapter is added later with its own factory and a marker:

    pytest.param(make_redis_cache, id="redis", marks=pytest.mark.integration)

A factory is an async function that returns a Harness over a fresh adapter that starts empty.
Real factories must delete what the test wrote when the harness is closed, so one test cannot
change another test's result.
"""

import asyncio
import json
from collections import defaultdict, deque
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from azure.servicebus import ServiceBusReceivedMessage, ServiceBusSessionFilter
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.exceptions import OperationTimeoutError
from redis.asyncio import Redis

from diucs.adapters.outbound.bus_servicebus.service_bus import ServiceBusEventBus
from diucs.adapters.outbound.cache_redis.code_store import RedisCodeStore
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_code_store import InMemoryCodeStore
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.event_bus import QUEUES, TOPICS, BusMessage, EventBus
from diucs.application.ports.outbound.identity import CodeStore
from diucs.application.tenancy import bind_tenant
from diucs.bootstrap.settings import Settings
from diucs.domain.rules.identity_policy import CodeState
from tests.contract.harness import Harness
from tests.support.redis import flush_prefix
from tests.support.servicebus import client as servicebus_client

# Every fake starts on 2026-10-25, the day of the London clock change, in UTC (the only zone a
# contract may depend on). Durations are relative, so no test depends on the start instant.
START = datetime(2026, 10, 25, 0, 0, tzinfo=UTC)


async def _nothing_to_close() -> None:
    return None


async def make_memory_cache() -> Harness[Cache]:
    clock = FixedClock(START)
    cache = InMemoryCache(clock)

    async def advance(delta: timedelta) -> None:
        clock.advance(delta)

    return Harness(subject=cache, now=clock.now, advance=advance, close=_nothing_to_close)


async def make_memory_event_bus() -> Harness[EventBus]:
    clock = FixedClock(START)
    bus = ManualEventBus(clock)
    inbox: dict[str, deque[BusMessage]] = defaultdict(deque)
    topic_read_up_to: dict[str, int] = defaultdict(int)

    async def advance(delta: timedelta) -> None:
        clock.advance(delta)

    async def receive(name: str, timeout: timedelta) -> BusMessage | None:
        # The fake answers at once; a real adapter waits up to timeout.
        del timeout
        if name in QUEUES:
            # due() and take_enqueued() remove what they return, so keep it until the queue
            # asks for it.
            for queue, message in [*bus.take_enqueued(), *bus.due()]:
                inbox[queue].append(message)
            return inbox[name].popleft() if inbox[name] else None
        if name in TOPICS:
            published = bus.published_to(name)
            position = topic_read_up_to[name]
            if position >= len(published):
                return None
            topic_read_up_to[name] = position + 1
            return published[position]
        raise AssertionError(f"{name} is neither a queue nor a topic")

    return Harness(
        subject=bus,
        now=clock.now,
        advance=advance,
        close=_nothing_to_close,
        receive=receive,
    )


async def make_redis_cache() -> Harness[Cache]:
    """A RedisCache on the Redis of infra/docker-compose.yml, under a prefix this harness alone
    uses. Concurrent runs on the same Redis share no keys, so one run's flush cannot delete
    another run's keys (I01: the overlap failure in test_redis_isolation.py)."""
    url = Settings().redis_url
    prefix = f"diucs-contract-{uuid4().hex}:"
    cleaner = Redis.from_url(url, decode_responses=True)
    cache = RedisCache.from_url(url, key_prefix=prefix)

    async def advance(delta: timedelta) -> None:
        # A real adapter waits in real time; the suites use seconds only (DEC-075 item 4).
        await asyncio.sleep(delta.total_seconds())

    async def close() -> None:
        try:
            await flush_prefix(cleaner, prefix)
        finally:
            await cache.aclose()
            await cleaner.aclose()

    return Harness(
        subject=cache,
        now=lambda: datetime.now(UTC),
        advance=advance,
        close=close,
    )


# The tenant every code-store contract run binds around each call (I13: the tenant comes from the
# bound unit of work, never from an argument).
CONTRACT_TENANT = "contract-tenant"


class _OffsetClock:
    """Real time moved forward by advance(). The Redis code store reads this clock for validity, so
    a 10-minute code expires in the contract without a 10-minute wait (DEC-075 item 4)."""

    def __init__(self) -> None:
        self._offset = timedelta(0)

    def now(self) -> datetime:
        return datetime.now(UTC) + self._offset

    def advance(self, delta: timedelta) -> None:
        self._offset += delta


class _TenantBoundCodeStore:
    """The contract's view of the Redis code store: each call runs with CONTRACT_TENANT bound."""

    def __init__(self, inner: CodeStore, tenant: str) -> None:
        self._inner = inner
        self._tenant = tenant

    async def save(self, purpose: str, phone_hash: str, code_hash: str, state: CodeState) -> None:
        with bind_tenant(self._tenant):
            await self._inner.save(purpose, phone_hash, code_hash, state)

    async def get(self, purpose: str, phone_hash: str) -> tuple[str, CodeState] | None:
        with bind_tenant(self._tenant):
            return await self._inner.get(purpose, phone_hash)

    async def clear(self, purpose: str, phone_hash: str) -> None:
        with bind_tenant(self._tenant):
            await self._inner.clear(purpose, phone_hash)


async def make_memory_code_store() -> Harness[CodeStore]:
    clock = FixedClock(START)
    store = InMemoryCodeStore(clock)

    async def advance(delta: timedelta) -> None:
        clock.advance(delta)

    return Harness(subject=store, now=clock.now, advance=advance, close=_nothing_to_close)


async def make_redis_code_store() -> Harness[CodeStore]:
    """A RedisCodeStore on the Redis of infra/docker-compose.yml, under a prefix this harness alone
    uses, and bound to CONTRACT_TENANT for each call. The store reads an offset clock, so advance()
    moves the validity window without a real wait; Redis's own key expiry is real time."""
    url = Settings().redis_url
    prefix = f"diucs-contract-{uuid4().hex}:"
    cleaner = Redis.from_url(url, decode_responses=True)
    client = Redis.from_url(url, decode_responses=True)
    clock = _OffsetClock()
    store = RedisCodeStore(client, clock, key_prefix=prefix)

    async def advance(delta: timedelta) -> None:
        clock.advance(delta)

    async def close() -> None:
        try:
            await flush_prefix(cleaner, prefix)
        finally:
            await client.aclose()
            await cleaner.aclose()

    return Harness(
        subject=_TenantBoundCodeStore(store, CONTRACT_TENANT),
        now=clock.now,
        advance=advance,
        close=close,
    )


# A topic is read through a subscription. The emulator declares this one with sessions, so a
# receiver takes the next available session (DEC-075 item 3, I02).
_TOPIC_SUBSCRIPTIONS = {"capacity.events": "board-projector"}
# Queues the contract drains at start and close. Nothing else reads them.
_CONTRACT_QUEUES = ("scheduled.work", "inbound.receipts")
_DRAIN_WAIT = timedelta(milliseconds=300)
# A session receive opens its link with this window, not the short wait (DEC-102 item 4).
_SESSION_OPEN_WAIT = 5.0
# The budget for one session open, however long the caller asked to wait (I02).
SESSION_OPEN_LIMIT = timedelta(seconds=10)


def session_open_window(wait: timedelta) -> float:
    return min(max(wait.total_seconds(), _SESSION_OPEN_WAIT), SESSION_OPEN_LIMIT.total_seconds())


def _as_bus_message(message: ServiceBusReceivedMessage, name: str) -> BusMessage:
    payload = json.loads(b"".join(message.body))
    return BusMessage(
        id=message.message_id or "",
        topic=name,
        event_type=message.subject or "",
        payload=payload,
        session_id=message.session_id,
    )


async def _take(
    sb: ServiceBusClient, sessions: ServiceBusClient, name: str, wait: timedelta
) -> ServiceBusReceivedMessage | None:
    """Complete and return the next message as the SDK sees it, unparsed (the drain needs this)."""
    seconds = wait.total_seconds()
    if name in QUEUES:
        receiver = sb.get_queue_receiver(name, max_wait_time=seconds)
    elif name in _TOPIC_SUBSCRIPTIONS:
        receiver = sessions.get_subscription_receiver(
            name,
            _TOPIC_SUBSCRIPTIONS[name],
            session_id=ServiceBusSessionFilter.NEXT_AVAILABLE,
            max_wait_time=session_open_window(wait),
        )
    else:
        raise AssertionError(f"{name} has no subscription in the contract")
    async with AsyncExitStack() as stack:
        try:
            # The session link opens here. With NEXT_AVAILABLE and nothing waiting, the open
            # times out instead of returning an empty list (lesson L127). That is no message,
            # not a failure. Only this open is guarded, not the receive or the complete.
            await stack.enter_async_context(receiver)
        except OperationTimeoutError:
            if name not in _TOPIC_SUBSCRIPTIONS:
                raise
            return None
        found = await receiver.receive_messages(max_message_count=1, max_wait_time=seconds)
        if not found:
            return None
        await receiver.complete_message(found[0])
        return found[0]


async def _receive_from(
    sb: ServiceBusClient, sessions: ServiceBusClient, name: str, wait: timedelta
) -> BusMessage | None:
    message = await _take(sb, sessions, name, wait)
    return None if message is None else _as_bus_message(message, name)


async def _drain(sb: ServiceBusClient, sessions: ServiceBusClient, names: tuple[str, ...]) -> None:
    """Remove what is already waiting, so a message from an earlier run is not received."""
    for name in names:
        # Taken without parsing: a leftover from another run may not be this contract's JSON.
        while await _take(sb, sessions, name, _DRAIN_WAIT) is not None:
            pass


class _RecordingBus:
    """The adapter, with the scheduled messages a test left pending remembered, so close() can
    cancel them. A cancel for a message that was already delivered does nothing (port)."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self.pending: set[tuple[str, int]] = set()

    async def publish(self, message: BusMessage) -> None:
        await self._bus.publish(message)

    async def enqueue(self, queue: str, message: BusMessage) -> None:
        await self._bus.enqueue(queue, message)

    async def schedule(self, queue: str, message: BusMessage, enqueue_at: datetime) -> int:
        number = await self._bus.schedule(queue, message, enqueue_at)
        self.pending.add((queue, number))
        return number

    async def cancel(self, queue: str, sequence_number: int) -> None:
        self.pending.discard((queue, sequence_number))
        await self._bus.cancel(queue, sequence_number)


async def make_servicebus_event_bus() -> Harness[EventBus]:
    """The Service Bus emulator (I02, DEC-008 pattern: no state carries between tests)."""
    sb = servicebus_client()
    # A timed-out session open is the normal empty case, so it fails at once instead of retrying
    # for about 40 s per call (DEC-102 item 4).
    sessions = servicebus_client(retry_total=0)
    try:
        bus = ServiceBusEventBus(sb)
    except BaseException:
        await sb.close()
        raise
    recorder = _RecordingBus(bus)
    await _drain(sb, sessions, (*_CONTRACT_QUEUES, *_TOPIC_SUBSCRIPTIONS))

    async def advance(delta: timedelta) -> None:
        await asyncio.sleep(delta.total_seconds())

    async def receive(name: str, timeout: timedelta) -> BusMessage | None:
        return await _receive_from(sb, sessions, name, timeout)

    async def close() -> None:
        try:
            for queue, number in sorted(recorder.pending):
                await bus.cancel(queue, number)
            await _drain(sb, sessions, _CONTRACT_QUEUES)
        finally:
            await bus.close()
            await sessions.close()
            await sb.close()

    return Harness(
        subject=recorder,
        now=lambda: datetime.now(UTC),
        advance=advance,
        close=close,
        receive=receive,
    )


CODE_STORE_FACTORIES = [
    pytest.param(make_memory_code_store, id="memory"),
    pytest.param(make_redis_code_store, id="redis", marks=pytest.mark.integration),
]
CACHE_FACTORIES = [
    pytest.param(make_memory_cache, id="memory"),
    pytest.param(make_redis_cache, id="redis", marks=pytest.mark.integration),
]
EVENT_BUS_FACTORIES = [
    pytest.param(make_memory_event_bus, id="memory"),
    pytest.param(make_servicebus_event_bus, id="servicebus", marks=pytest.mark.integration),
]
