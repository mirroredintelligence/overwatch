"""Adapter factories for the contract suites (P12).

Each list holds one `pytest.param(factory, id=...)` per adapter of its port. The memory fakes are
in every normal run. A real adapter is added later with its own factory and a marker:

    pytest.param(make_redis_cache, id="redis", marks=pytest.mark.integration)

A factory is an async function that returns a Harness over a fresh adapter that starts empty.
Real factories must delete what the test wrote when the harness is closed, so one test cannot
change another test's result.
"""

import asyncio
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis

from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.event_bus import QUEUES, TOPICS, BusMessage, EventBus
from diucs.bootstrap.settings import Settings
from tests.contract.harness import Harness
from tests.support.redis import flush_diucs_keys

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


CACHE_FACTORIES = [
    pytest.param(make_memory_cache, id="memory"),
    pytest.param(make_redis_cache, id="redis", marks=pytest.mark.integration),
]
EVENT_BUS_FACTORIES = [pytest.param(make_memory_event_bus, id="memory")]
