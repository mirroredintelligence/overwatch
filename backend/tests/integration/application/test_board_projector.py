"""Integration tests for the board projector (U09): real Neo4j for the board, the in-memory cache.

The board is seeded through committed units of work and read through a fresh one (DEC-004). The
sample service follows the "Main" artboard in docs/spec/ui-screens.md. All values are synthetic;
there is no patient data.

Clock: Friday 23 October 2026 at 14:12 London (BST, 13:12 UTC). The cache and the projector share
one FixedClock, so a test advances both together.
"""

import asyncio
import json
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import Actor
from diucs.application.ports.outbound.cache import BOARD_UPDATES_CHANNEL
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.board_projector import (
    BOARD_CACHE_KEY,
    BoardProjector,
    board_from_dict,
)
from diucs.application.use_cases.query_board import Board, QueryBoard, QueryBoardQuery
from diucs.domain.codes import Cadence, Channel, Measure, ReportSource, ReportType, Role
from diucs.domain.codes import ServiceCategory as Category
from diucs.domain.errors import NotAllowed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.actors import ACTOR_TENANT

pytestmark = pytest.mark.asyncio(loop_scope="session")

FRIDAY_NOON_LONDON = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)  # 14:12 BST
WEST_REPORT_AT = datetime(2026, 10, 23, 13, 3, tzinfo=UTC)  # 14:03 BST
NEWER_REPORT_AT = datetime(2026, 10, 23, 13, 10, tzinfo=UTC)  # 14:10 BST

ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
ANONYMOUS = Actor(
    role=Role.ANONYMOUS_LINK,
    practitioner_id=None,
    device_id=None,
    channel="link",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)


def _ucr(service_id: str, name: str) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=name,
        category=Category.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.weekdays(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


WEST = _ucr("svc-ucr-west", "UCR West")


def _report(report_id: str, value: int, at: datetime) -> CapacityReport:
    return CapacityReport(
        id=report_id,
        service_id=WEST.id,
        value=value,
        measure=WEST.measure,
        effective_at=at,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )


class _CountingQueryBoard(QueryBoard):
    """QueryBoard that counts how often the projector has to compute the board."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        super().__init__(uow_factory, clock)
        self.computations = 0

    async def execute(self, query: QueryBoardQuery) -> Board:
        self.computations += 1
        return await super().execute(query)


class _RecordingCache(InMemoryCache):
    """The in-memory cache, with a record of every write and publish."""

    def __init__(self, clock: Clock) -> None:
        super().__init__(clock)
        self.writes: list[str] = []
        self.publishes: list[tuple[str, str]] = []

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        self.writes.append(key)
        await super().set(key, value, ttl)

    async def publish(self, channel: str, message: str) -> None:
        self.publishes.append((channel, message))
        await super().publish(channel, message)


class _UnreadableCache(InMemoryCache):
    """A cache whose reads fail, as when Redis is down."""

    async def get(self, key: str) -> str | None:
        raise OSError("cache unavailable")


class _ReadingAtPublishCache(InMemoryCache):
    """Records what the cache held at the moment of each publish."""

    def __init__(self, clock: Clock) -> None:
        super().__init__(clock)
        self.held_at_publish: list[str | None] = []

    async def publish(self, channel: str, message: str) -> None:
        self.held_at_publish.append(await super().get(BOARD_CACHE_KEY))
        await super().publish(channel, message)


class _UnpublishableCache(InMemoryCache):
    """A cache that stores and reads but cannot publish."""

    async def publish(self, channel: str, message: str) -> None:
        raise OSError("cache unavailable")


class _UnwritableCache(InMemoryCache):
    """A cache that reads but cannot store or publish."""

    async def set(self, key: str, value: str, ttl: timedelta | None = None) -> None:
        raise OSError("cache unavailable")

    async def publish(self, channel: str, message: str) -> None:
        raise OSError("cache unavailable")


async def _seed(factory: UnitOfWorkFactory, *reports: CapacityReport) -> None:
    async with factory() as uow:
        await uow.services.save(WEST)
        for report in reports:
            await uow.capacity.add(report)
        await uow.commit()


def _projector(
    factory: UnitOfWorkFactory, cache: InMemoryCache, clock: FixedClock
) -> tuple[BoardProjector, _CountingQueryBoard]:
    query_board = _CountingQueryBoard(factory, clock)
    return BoardProjector(query_board, cache, clock), query_board


def _payload(service_id: str) -> dict[str, Any]:
    return {
        "service_id": service_id,
        "report_id": "obs-sample-1",
        "value": 4,
        "at": "2026-10-23T13:03:00Z",
    }


async def test_a_capacity_report_stores_the_board_and_publishes_one_update(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    cache = _RecordingCache(clock)
    projector, _ = _projector(uow_factory, cache, clock)
    updates = await cache.subscribe(BOARD_UPDATES_CHANNEL)

    handled = await projector.handle("CapacityReported", _payload("ucr-west"))

    assert handled is True
    stored = await cache.get(BOARD_CACHE_KEY)
    assert stored is not None
    assert [entry.service_id for entry in board_from_dict(json.loads(stored)).entries] == [WEST.id]
    assert len(cache.publishes) == 1
    channel, message = cache.publishes[0]
    assert channel == BOARD_UPDATES_CHANNEL
    assert await asyncio.wait_for(anext(updates), timeout=1) == message
    body = json.loads(message)
    assert set(body) == {"type", "service_id", "at"}
    assert body["type"] == "board-changed"
    assert body["service_id"] == "ucr-west"
    assert datetime.fromisoformat(body["at"]) == FRIDAY_NOON_LONDON


async def _three_services(factory: UnitOfWorkFactory, west_value: int) -> list[ServiceProfile]:
    """West with `west_value` and two services that are already not accepting: the pressure is
    `watch` once West is limited or worse too (the tenant default: three services)."""
    services = [WEST, _ucr("svc-ucr-north", "UCR North"), _ucr("svc-ucr-south", "UCR South")]
    async with factory() as uow:
        for service in services:
            await uow.services.save(service)
            value = west_value if service is WEST else 0
            await uow.capacity.add(
                CapacityReport(
                    id=f"obs-{service.id}-1403",
                    service_id=service.id,
                    value=value,
                    measure=service.measure,
                    effective_at=WEST_REPORT_AT,
                    source=ReportSource.TEXT,
                    report_type=ReportType.NUMBER,
                )
            )
        await uow.commit()
    return services


async def test_a_change_of_pressure_publishes_a_whole_board_message_after_the_service_one(
    uow_factory: UnitOfWorkFactory,
) -> None:
    # KI-55: the banner belongs to no one service, so the stream is told about it on its own.
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _three_services(uow_factory, west_value=4)
    cache = _RecordingCache(clock)
    projector, _ = _projector(uow_factory, cache, clock)
    await projector.handle("CapacityReported", _payload("svc-ucr-west"))
    first = board_from_dict(json.loads(await cache.get(BOARD_CACHE_KEY) or "null"))
    assert first.pressure.value == "normal"
    cache.publishes.clear()

    async with uow_factory() as uow:
        await uow.capacity.add(_report("obs-west-1410", 0, NEWER_REPORT_AT))
        await uow.commit()
    await projector.handle("CapacityReported", _payload("svc-ucr-west"))

    bodies = [json.loads(message) for _, message in cache.publishes]
    assert [b["service_id"] for b in bodies] == ["svc-ucr-west", None]
    assert all(b["type"] == "board-changed" for b in bodies)
    assert set(bodies[1]) == {"type", "service_id", "at"}


async def test_no_whole_board_message_is_published_while_the_pressure_is_unchanged(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    cache = _RecordingCache(clock)
    projector, _ = _projector(uow_factory, cache, clock)
    await projector.handle("CapacityReported", _payload("svc-ucr-west"))
    cache.publishes.clear()

    async with uow_factory() as uow:
        await uow.capacity.add(_report("obs-west-1410", 3, NEWER_REPORT_AT))
        await uow.commit()
    await projector.handle("CapacityReported", _payload("svc-ucr-west"))

    assert [json.loads(m)["service_id"] for _, m in cache.publishes] == ["svc-ucr-west"]


async def test_an_unreadable_previous_board_does_not_stop_the_publish(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    cache = _RecordingCache(clock)
    await cache.set(BOARD_CACHE_KEY, "{not json", timedelta(seconds=60))
    cache.writes.clear()
    projector, _ = _projector(uow_factory, cache, clock)

    assert await projector.handle("CapacityReported", _payload("svc-ucr-west"))

    assert [json.loads(m)["service_id"] for _, m in cache.publishes] == ["svc-ucr-west"]


async def test_an_event_the_board_does_not_show_changes_nothing(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    cache = _RecordingCache(clock)
    projector, query_board = _projector(uow_factory, cache, clock)

    handled = await projector.handle("SomethingElse", {})

    assert handled is False
    assert await cache.get(BOARD_CACHE_KEY) is None
    assert cache.writes == []
    assert cache.publishes == []
    assert query_board.computations == 0


async def test_the_cached_board_is_computed_once_and_then_read_from_the_cache(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    cache = _RecordingCache(clock)
    projector, query_board = _projector(uow_factory, cache, clock)

    first = await projector.get_board(ADVISOR)
    clock.advance(timedelta(seconds=30))
    second = await projector.get_board(ADVISOR)

    expected = await QueryBoard(uow_factory, FixedClock(FRIDAY_NOON_LONDON)).execute(
        QueryBoardQuery(actor=ADVISOR)
    )
    assert first == expected
    assert second == expected
    assert query_board.computations == 1


async def test_a_new_report_is_visible_on_the_next_read_without_waiting_for_expiry(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    cache = _RecordingCache(clock)
    projector, query_board = _projector(uow_factory, cache, clock)
    before = await projector.get_board(ADVISOR)
    assert [entry.effective_available for entry in before.entries] == [4]

    async with uow_factory() as uow:
        await uow.capacity.add(_report("obs-west-1410", 2, NEWER_REPORT_AT))
        await uow.commit()
    assert await projector.handle("CapacityReported", _payload("svc-ucr-west"))

    after = await projector.get_board(ADVISOR)
    assert [entry.effective_available for entry in after.entries] == [2]
    assert query_board.computations == 2


async def test_the_cached_board_expires_after_sixty_seconds_and_is_recomputed(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    cache = _RecordingCache(clock)
    projector, query_board = _projector(uow_factory, cache, clock)
    await projector.get_board(ADVISOR)

    clock.advance(timedelta(seconds=61))
    await projector.get_board(ADVISOR)

    assert query_board.computations == 2


async def test_a_cache_whose_reads_fail_still_returns_the_computed_board(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    projector, _ = _projector(uow_factory, _UnreadableCache(clock), clock)

    board = await projector.get_board(ADVISOR)

    assert [entry.effective_available for entry in board.entries] == [4]


async def test_a_cache_that_cannot_store_still_returns_the_computed_board(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    projector, _ = _projector(uow_factory, _UnwritableCache(clock), clock)

    board = await projector.get_board(ADVISOR)

    assert [entry.effective_available for entry in board.entries] == [4]


async def test_a_failed_publish_is_raised_so_the_consumer_can_retry(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    projector, _ = _projector(uow_factory, _UnwritableCache(clock), clock)

    with pytest.raises(OSError):
        await projector.handle("CapacityReported", _payload("svc-ucr-west"))


async def test_the_anonymous_link_is_refused_even_when_the_board_is_cached(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    cache = _RecordingCache(clock)
    projector, _ = _projector(uow_factory, cache, clock)
    await projector.get_board(ADVISOR)

    with pytest.raises(NotAllowed):
        await projector.get_board(ANONYMOUS)


async def test_an_unreadable_cached_board_is_replaced_by_a_computed_one(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    cache = _RecordingCache(clock)
    await cache.set(BOARD_CACHE_KEY, '{"entries": "not a board"}')
    projector, query_board = _projector(uow_factory, cache, clock)

    board = await projector.get_board(ADVISOR)

    assert [entry.effective_available for entry in board.entries] == [4]
    assert query_board.computations == 1


async def test_the_board_is_stored_before_the_update_is_published(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    cache = _ReadingAtPublishCache(clock)
    projector, _ = _projector(uow_factory, cache, clock)

    assert await projector.handle("CapacityReported", _payload("svc-ucr-west"))

    assert len(cache.held_at_publish) == 1
    held = cache.held_at_publish[0]
    assert held is not None
    assert [entry.service_id for entry in board_from_dict(json.loads(held)).entries] == [WEST.id]


async def test_a_failed_publish_is_raised_after_the_board_is_stored(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    cache = _UnpublishableCache(clock)
    projector, _ = _projector(uow_factory, cache, clock)

    with pytest.raises(OSError):
        await projector.handle("CapacityReported", _payload("svc-ucr-west"))
    assert await cache.get(BOARD_CACHE_KEY) is not None


async def test_a_board_rebuilt_on_an_event_expires_after_sixty_seconds(
    uow_factory: UnitOfWorkFactory,
) -> None:
    clock = FixedClock(FRIDAY_NOON_LONDON)
    await _seed(uow_factory, _report("obs-west-1403", 4, WEST_REPORT_AT))
    cache = _RecordingCache(clock)
    projector, query_board = _projector(uow_factory, cache, clock)
    assert await projector.handle("CapacityReported", _payload("svc-ucr-west"))

    clock.advance(timedelta(seconds=61))
    await projector.get_board(ADVISOR)

    assert query_board.computations == 2
