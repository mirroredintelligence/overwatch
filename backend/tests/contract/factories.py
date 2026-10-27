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
from datetime import UTC, datetime, timedelta

import pytest
from azure.servicebus import ServiceBusReceivedMessage, ServiceBusSessionFilter
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.exceptions import OperationTimeoutError
from redis.asyncio import Redis

from diucs.adapters.outbound.bus_servicebus.service_bus import ServiceBusEventBus
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.event_bus import QUEUES, TOPICS, BusMessage, EventBus
from diucs.bootstrap.settings import Settings
from tests.contract.harness import Harness
from tests.support.redis import flush_diucs_keys
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
            # due() removes what it returns, so keep it until the queue asks for it.
            for queue, message in bus.due():
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
    """A RedisCache on the Redis of infra/docker-compose.yml. Each test starts with no diucs: keys
    and leaves none behind, so the suites share no state."""
    url = Settings().redis_url
    cleaner = Redis.from_url(url, decode_responses=True)
    await flush_diucs_keys(cleaner)
    cache = RedisCache.from_url(url)

    async def advance(delta: timedelta) -> None:
        # A real adapter waits in real time; the suites use seconds only (DEC-075 item 4).
        await asyncio.sleep(delta.total_seconds())

    async def close() -> None:
        try:
            await flush_diucs_keys(cleaner)
        finally:
            await cache.aclose()
            await cleaner.aclose()

    return Harness(
        subject=cache,
        now=lambda: datetime.now(UTC),
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


def _as_bus_message(message: ServiceBusReceivedMessage, name: str) -> BusMessage:
    payload = json.loads(b"".join(message.body))
    return BusMessage(
        id=message.message_id or "",
        topic=name,
        event_type=message.subject or "",
        payload=payload,
        session_id=message.session_id,
    )


async def _receive_from(sb: ServiceBusClient, name: str, wait: timedelta) -> BusMessage | None:
    seconds = wait.total_seconds()
    if name in QUEUES:
        receiver = sb.get_queue_receiver(name, max_wait_time=seconds)
    elif name in _TOPIC_SUBSCRIPTIONS:
        receiver = sb.get_subscription_receiver(
            name,
            _TOPIC_SUBSCRIPTIONS[name],
            session_id=ServiceBusSessionFilter.NEXT_AVAILABLE,
            max_wait_time=max(seconds, _SESSION_OPEN_WAIT),
        )
    else:
        raise AssertionError(f"{name} has no subscription in the contract")
    async with receiver:
        try:
            found = await receiver.receive_messages(max_message_count=1, max_wait_time=seconds)
        except OperationTimeoutError:
            # With NEXT_AVAILABLE and nothing waiting, the link open times out instead of
            # returning an empty list (lesson L127). That is no message, not a failure.
            return None
        if not found:
            return None
        await receiver.complete_message(found[0])
        return _as_bus_message(found[0], name)


async def _drain(sb: ServiceBusClient, names: tuple[str, ...]) -> None:
    """Remove what is already waiting, so a message from an earlier run is not received."""
    for name in names:
        while await _receive_from(sb, name, _DRAIN_WAIT) is not None:
            pass


class _RecordingBus:
    """The adapter, with the scheduled messages a test left pending remembered, so close() can
    cancel them. A cancel for a message that was already delivered does nothing (port)."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self.pending: set[tuple[str, int]] = set()

    async def publish(self, message: BusMessage) -> None:
        await self._bus.publish(message)

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
    try:
        bus = ServiceBusEventBus(sb)
    except BaseException:
        await sb.close()
        raise
    recorder = _RecordingBus(bus)
    await _drain(sb, (*_CONTRACT_QUEUES, *_TOPIC_SUBSCRIPTIONS))

    async def advance(delta: timedelta) -> None:
        await asyncio.sleep(delta.total_seconds())

    async def receive(name: str, timeout: timedelta) -> BusMessage | None:
        return await _receive_from(sb, name, timeout)

    async def close() -> None:
        try:
            for queue, number in sorted(recorder.pending):
                await bus.cancel(queue, number)
            await _drain(sb, _CONTRACT_QUEUES)
        finally:
            await bus.close()
            await sb.close()

    return Harness(
        subject=recorder,
        now=lambda: datetime.now(UTC),
        advance=advance,
        close=close,
        receive=receive,
    )


CACHE_FACTORIES = [
    pytest.param(make_memory_cache, id="memory"),
    pytest.param(make_redis_cache, id="redis", marks=pytest.mark.integration),
]
EVENT_BUS_FACTORIES = [
    pytest.param(make_memory_event_bus, id="memory"),
    pytest.param(make_servicebus_event_bus, id="servicebus", marks=pytest.mark.integration),
]
