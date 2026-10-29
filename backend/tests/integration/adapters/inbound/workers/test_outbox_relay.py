"""The outbox relay on real Neo4j (I03). The outbox and the scheduled work are the real stored
nodes, read back through the graph. Only the bus (a recording ManualEventBus), the cache and the
clock are fakes. The clock is 14:16 London.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from datetime import timedelta

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.inbound.workers.outbox_relay import (
    LOCK_NAME,
    LOCK_TTL,
    OutboxRelay,
    RelayResult,
    StaticTenants,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.outbox import MAX_ATTEMPTS
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.scheduling import cancel_work
from tests.support.relay_rig import (
    ABOUT,
    DUE,
    NOW,
    SECRET_TEXT,
    InstrumentedFactory,
    ScriptedTokenCache,
    SpyBus,
    add_messages,
    add_scheduled,
    instant,
    outbox_message,
    outbox_node,
    work_node,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

LOGGER = "diucs.adapters.inbound.workers.outbox_relay"


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def bus(clock: FixedClock) -> SpyBus:
    return SpyBus(ManualEventBus(clock))


@pytest.fixture
def cache(clock: FixedClock) -> InMemoryCache:
    return InMemoryCache(clock)


@pytest.fixture
def make_relay(
    uow_factory: UnitOfWorkFactory,
    bus: SpyBus,
    cache: InMemoryCache,
    clock: FixedClock,
    tenant_id: str,
) -> Callable[..., OutboxRelay]:
    def make(**options: object) -> OutboxRelay:
        factory = options.pop("factory", uow_factory)
        return OutboxRelay(
            factory,  # type: ignore[arg-type]
            bus,
            options.pop("cache", cache),  # type: ignore[arg-type]
            clock,
            StaticTenants([tenant_id]),
            **options,  # type: ignore[arg-type]
        )

    return make


@pytest.fixture
def relay(make_relay: Callable[..., OutboxRelay]) -> OutboxRelay:
    return make_relay()


# 1 to 6: the plain publish path


async def test_three_pending_messages_are_published_in_creation_order_and_marked_published(
    relay: OutboxRelay, bus: SpyBus, uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    await add_messages(
        uow_factory,
        outbox_message("out-3", 2),
        outbox_message("out-1", 0),
        outbox_message("out-2", 1),
    )

    result = await relay.run_once()

    assert result == RelayResult(published=3, failed=0, skipped_no_lock=False)
    assert [message.id for message in bus.published] == ["out-1", "out-2", "out-3"]
    for message_id in ("out-1", "out-2", "out-3"):
        node = await outbox_node(neo4j_driver, message_id)
        assert node["status"] == "published"
        assert instant(node["publishedAt"]) == NOW


async def test_a_second_round_with_nothing_new_publishes_nothing(
    relay: OutboxRelay, bus: SpyBus, uow_factory: UnitOfWorkFactory
) -> None:
    await add_messages(uow_factory, outbox_message("out-1"))
    await relay.run_once()

    result = await relay.run_once()

    assert result == RelayResult(published=0, failed=0, skipped_no_lock=False)
    assert [message.id for message in bus.published] == ["out-1"]


async def test_at_most_a_batch_is_published_per_round_oldest_first(
    make_relay: Callable[..., OutboxRelay], bus: SpyBus, uow_factory: UnitOfWorkFactory
) -> None:
    relay = make_relay(batch_size=2)
    await add_messages(uow_factory, *(outbox_message(f"out-{n}", n) for n in range(5)))

    counts = [(await relay.run_once()).published for _ in range(3)]

    assert counts == [2, 2, 1]
    assert [message.id for message in bus.published] == [f"out-{n}" for n in range(5)]


async def test_a_failed_publish_counts_an_attempt_keeps_the_message_pending_and_goes_on(
    relay: OutboxRelay, bus: SpyBus, uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    await add_messages(
        uow_factory,
        outbox_message("out-1", 0),
        outbox_message("out-2", 1),
        outbox_message("out-3", 2),
    )
    bus.failures["out-2"] = [ConnectionError("the bus is down")]

    result = await relay.run_once()

    assert result == RelayResult(published=2, failed=1, skipped_no_lock=False)
    assert [message.id for message in bus.published] == ["out-1", "out-3"]
    failed = await outbox_node(neo4j_driver, "out-2")
    assert failed["attempts"] == 1
    assert failed["status"] == "pending"
    assert "publishedAt" not in failed
    assert (await outbox_node(neo4j_driver, "out-1"))["status"] == "published"
    assert (await outbox_node(neo4j_driver, "out-3"))["status"] == "published"


async def test_the_error_kept_with_a_failed_message_is_its_class_and_never_its_text(
    relay: OutboxRelay,
    bus: SpyBus,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await add_messages(uow_factory, outbox_message("out-1"))
    bus.failures["out-1"] = [ConnectionError(f"refused {SECRET_TEXT}")]

    with caplog.at_level(logging.DEBUG):
        await relay.run_once()

    assert (await outbox_node(neo4j_driver, "out-1"))["lastError"] == "ConnectionError"
    assert SECRET_TEXT not in caplog.text


async def test_a_message_that_fails_ten_times_is_dead_and_is_not_tried_again(
    relay: OutboxRelay,
    bus: SpyBus,
    clock: FixedClock,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await add_messages(uow_factory, outbox_message("out-1", topic="booking.events"))
    bus.always_fail["out-1"] = ConnectionError(f"refused {SECRET_TEXT}")

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        for _ in range(MAX_ATTEMPTS):
            await relay.run_once()
            clock.advance(timedelta(seconds=61))
        calls_when_dead = len(bus.calls_of("publish"))
        again = await relay.run_once()

    node = await outbox_node(neo4j_driver, "out-1")
    assert node["status"] == "dead"
    assert node["attempts"] == MAX_ATTEMPTS
    assert calls_when_dead == MAX_ATTEMPTS
    assert len(bus.calls_of("publish")) == MAX_ATTEMPTS
    assert again == RelayResult(published=0, failed=0, skipped_no_lock=False)
    dead_logs = [r.getMessage() for r in caplog.records if "dead" in r.getMessage().lower()]
    assert len(dead_logs) == 1
    assert "out-1" in dead_logs[0]
    assert "booking.events" in dead_logs[0]
    assert SECRET_TEXT not in caplog.text
    assert "4821" not in caplog.text


async def test_session_id_event_type_topic_and_payload_pass_through_unchanged(
    relay: OutboxRelay, bus: SpyBus, uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    payload = {
        "service_id": "svc-ucr-west",
        "value": 8,
        "flag": True,
        "note": None,
        "at": "2026-10-23T13:00:00Z",
    }
    await add_messages(
        uow_factory,
        outbox_message(
            "out-1",
            topic="capacity.events",
            event_type="CapacityReported",
            payload=payload,
            session_id="svc-ucr-west",
        ),
    )

    await relay.run_once()

    assert bus.published == [
        BusMessage(
            id="out-1",
            topic="capacity.events",
            event_type="CapacityReported",
            payload=payload,
            session_id="svc-ucr-west",
            tenant_id=tenant_id,
        )
    ]


# 2b: the wait after a failure


async def test_after_a_failure_a_tenant_waits_one_second_then_doubles_up_to_sixty(
    relay: OutboxRelay, bus: SpyBus, clock: FixedClock, uow_factory: UnitOfWorkFactory
) -> None:
    await add_messages(uow_factory, outbox_message("out-1"))
    bus.always_fail["out-1"] = ConnectionError("down")
    expected_waits = [1, 2, 4, 8, 16, 32, 60, 60]

    await relay.run_once()
    for wait in expected_waits:
        tried = len(bus.calls_of("publish"))
        clock.advance(timedelta(seconds=wait) - timedelta(milliseconds=1))
        too_early = await relay.run_once()
        assert too_early == RelayResult(published=0, failed=0, skipped_no_lock=False)
        assert len(bus.calls_of("publish")) == tried
        clock.advance(timedelta(milliseconds=1))
        retried = await relay.run_once()
        assert retried.failed == 1
        assert len(bus.calls_of("publish")) == tried + 1


async def test_a_good_round_after_a_failure_starts_the_wait_again_at_one_second(
    relay: OutboxRelay, bus: SpyBus, clock: FixedClock, uow_factory: UnitOfWorkFactory
) -> None:
    await add_messages(uow_factory, outbox_message("out-1", 0))
    bus.failures["out-1"] = [ConnectionError("down"), ConnectionError("down")]
    await relay.run_once()  # fails, waits 1 s
    clock.advance(timedelta(seconds=1))
    await relay.run_once()  # fails, waits 2 s
    clock.advance(timedelta(seconds=2))
    assert (await relay.run_once()).published == 1  # goes through: the wait is forgotten
    await add_messages(uow_factory, outbox_message("out-2", 1))
    bus.failures["out-2"] = [ConnectionError("down")]
    await relay.run_once()  # fails again: the wait is 1 s, not 4 s
    clock.advance(timedelta(seconds=1))

    assert (await relay.run_once()).published == 1


# 3: single flight


async def test_a_lock_held_by_another_holder_means_nothing_is_done_this_round(
    relay: OutboxRelay,
    bus: SpyBus,
    cache: InMemoryCache,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    await add_messages(uow_factory, outbox_message("out-1"))
    other = await cache.acquire_lock(LOCK_NAME, LOCK_TTL)
    assert other is not None
    before = await outbox_node(neo4j_driver, "out-1")

    result = await relay.run_once()

    assert result == RelayResult(published=0, failed=0, skipped_no_lock=True)
    assert bus.calls == []
    assert await outbox_node(neo4j_driver, "out-1") == before


async def test_the_lock_is_released_after_a_round_so_the_next_round_can_take_it(
    relay: OutboxRelay, bus: SpyBus, cache: InMemoryCache, uow_factory: UnitOfWorkFactory
) -> None:
    await add_messages(uow_factory, outbox_message("out-1"))
    bus.failures["out-1"] = [ConnectionError("down")]

    await relay.run_once()

    assert bus.calls == [("publish", "out-1")]  # the round ran, took the lock and failed
    lock = await cache.acquire_lock(LOCK_NAME, LOCK_TTL)
    assert lock is not None


async def test_the_lock_lasts_thirty_seconds() -> None:
    assert timedelta(seconds=30) == LOCK_TTL
    assert LOCK_NAME == "outbox-relay"


async def test_a_batch_stops_when_the_lock_is_about_to_run_out(
    relay: OutboxRelay, bus: SpyBus, clock: FixedClock, uow_factory: UnitOfWorkFactory
) -> None:
    await add_messages(uow_factory, outbox_message("out-1", 0), outbox_message("out-2", 1))
    # The first publish takes 26 s: with 4 s of the 30 left, nobody can show this relay still holds
    # the lock, so it stops and leaves the rest for the next round.

    async def slow() -> None:
        clock.advance(timedelta(seconds=26))

    bus.on_call = slow

    first = await relay.run_once()
    bus.on_call = None
    second = await relay.run_once()

    assert first == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert second == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert [message.id for message in bus.published] == ["out-1", "out-2"]


async def test_a_lock_whose_token_is_lower_than_the_last_one_seen_is_refused_and_released(
    make_relay: Callable[..., OutboxRelay],
    bus: SpyBus,
    clock: FixedClock,
    uow_factory: UnitOfWorkFactory,
) -> None:
    # Hazard H-26: after a clock step back or a Redis data loss, a new token can be lower than an
    # earlier one. The relay does not trust it, and gives the lock back so it is not left held.
    cache = ScriptedTokenCache(clock, [5, 3, 6])
    relay = make_relay(cache=cache)
    await add_messages(uow_factory, outbox_message("out-1", 0))
    await relay.run_once()
    await add_messages(uow_factory, outbox_message("out-2", 1))

    refused = await relay.run_once()
    published_when_refused = list(bus.published)
    accepted = await relay.run_once()

    assert refused == RelayResult(published=0, failed=0, skipped_no_lock=True)
    assert [message.id for message in published_when_refused] == ["out-1"]
    assert accepted == RelayResult(published=1, failed=0, skipped_no_lock=False)


# 4: a crash between the publish and the mark


async def test_a_crash_after_the_publish_republishes_the_same_id_and_ends_published(
    make_relay: Callable[..., OutboxRelay],
    bus: SpyBus,
    clock: FixedClock,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    factory = InstrumentedFactory(uow_factory, fail_mark_published={"out-1"})
    relay = make_relay(factory=factory)
    await add_messages(uow_factory, outbox_message("out-1"))

    first = await relay.run_once()
    after_crash = await outbox_node(neo4j_driver, "out-1")
    clock.advance(timedelta(seconds=1))
    second = await relay.run_once()

    assert first == RelayResult(published=0, failed=1, skipped_no_lock=False)
    assert after_crash["status"] == "pending"
    assert after_crash["attempts"] == 0
    assert second == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert [message.id for message in bus.published] == ["out-1", "out-1"]
    node = await outbox_node(neo4j_driver, "out-1")
    assert node["status"] == "published"
    assert instant(node["publishedAt"]) == NOW + timedelta(seconds=1)


async def test_the_message_is_still_pending_while_the_publish_is_in_flight(
    relay: OutboxRelay, bus: SpyBus, uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    await add_messages(uow_factory, outbox_message("out-1"))
    seen: list[object] = []

    async def look() -> None:
        seen.append((await outbox_node(neo4j_driver, "out-1"))["status"])

    bus.on_call = look

    await relay.run_once()

    assert seen == ["pending"]
    assert (await outbox_node(neo4j_driver, "out-1"))["status"] == "published"


# 7 and 8: scheduled work


async def test_a_schedule_work_message_is_scheduled_at_its_time_and_its_number_is_stored(
    relay: OutboxRelay,
    bus: SpyBus,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    await add_scheduled(uow_factory, "w1", "out-w1")

    result = await relay.run_once()

    assert result == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert bus.published == []  # nothing goes to a topic
    assert bus.calls == [("schedule", "out-w1", 1)]
    assert bus.inner.due(DUE - timedelta(seconds=1)) == []
    assert bus.inner.due(DUE) == [
        (
            "scheduled.work",
            BusMessage(
                id="out-w1",
                topic="scheduled.work",
                event_type="ScheduledWorkDue",
                payload={"work_id": "w1", "kind": "prompt-due", "about_id": ABOUT},
                tenant_id=tenant_id,
            ),
        )
    ]
    work = await work_node(neo4j_driver, "w1")
    assert work["sequenceNumber"] == 1
    assert work["status"] == "scheduled"
    assert (await outbox_node(neo4j_driver, "out-w1"))["status"] == "published"


async def test_a_cancel_work_message_after_the_relay_cancels_the_scheduled_message(
    relay: OutboxRelay,
    bus: SpyBus,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    work = await add_scheduled(uow_factory, "w1", "out-w1")
    await relay.run_once()
    async with uow_factory() as uow:
        await cancel_work(uow, work, NOW)
        await uow.commit()

    result = await relay.run_once()

    assert result == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert bus.calls_of("cancel") == [("cancel", 1)]
    assert bus.inner.due(DUE) == []
    stored = await work_node(neo4j_driver, "w1")
    assert stored["status"] == "cancelled"
    assert stored["sequenceNumber"] == 1
    assert (await outbox_node(neo4j_driver, "cancel-w1"))["status"] == "published"


async def test_a_cancel_work_message_relayed_before_its_schedule_does_nothing_to_the_bus(
    make_relay: Callable[..., OutboxRelay],
    bus: SpyBus,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    # The schedule is held back by a batch of one, so the cancel (created first) goes alone.
    relay = make_relay(batch_size=1)
    work = await add_scheduled(uow_factory, "w1", "out-w1", now=NOW + timedelta(minutes=1))
    async with uow_factory() as uow:
        await cancel_work(uow, work, NOW)
        await uow.commit()

    only_the_cancel = await relay.run_once()

    assert only_the_cancel.published == 1
    assert bus.calls == []
    assert (await outbox_node(neo4j_driver, "cancel-w1"))["status"] == "published"
    assert (await outbox_node(neo4j_driver, "out-w1"))["status"] == "pending"


async def test_a_schedule_for_work_already_cancelled_is_scheduled_and_cancelled_at_once(
    make_relay: Callable[..., OutboxRelay],
    bus: SpyBus,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    relay = make_relay()
    work = await add_scheduled(uow_factory, "w1", "out-w1", now=NOW + timedelta(minutes=1))
    async with uow_factory() as uow:
        await cancel_work(uow, work, NOW)  # the cancel message is the older one
        await uow.commit()

    result = await relay.run_once()

    assert result == RelayResult(published=2, failed=0, skipped_no_lock=False)
    assert bus.calls == [("schedule", "out-w1", 1), ("cancel", 1)]
    assert bus.inner.due(DUE) == []
    assert bus.published == []
    stored = await work_node(neo4j_driver, "w1")
    assert stored["status"] == "cancelled"
    assert stored["sequenceNumber"] == 1
    assert (await outbox_node(neo4j_driver, "out-w1"))["status"] == "published"


async def test_a_failed_schedule_stores_no_number_and_is_tried_again(
    relay: OutboxRelay,
    bus: SpyBus,
    clock: FixedClock,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    await add_scheduled(uow_factory, "w1", "out-w1")
    bus.failures["out-w1"] = [ConnectionError("down")]

    first = await relay.run_once()
    after_failure = await work_node(neo4j_driver, "w1")
    clock.advance(timedelta(seconds=1))
    second = await relay.run_once()

    assert first == RelayResult(published=0, failed=1, skipped_no_lock=False)
    assert "sequenceNumber" not in after_failure
    assert (await outbox_node(neo4j_driver, "out-w1"))["attempts"] == 1
    assert second == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert (await work_node(neo4j_driver, "w1"))["sequenceNumber"] == 1


async def test_a_schedule_for_work_that_is_not_stored_fails_and_schedules_nothing(
    relay: OutboxRelay,
    bus: SpyBus,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    await add_messages(
        uow_factory,
        outbox_message(
            "out-w9",
            topic="scheduled.work",
            event_type="ScheduleWork",
            payload={
                "work_id": "w9",
                "kind": "prompt-due",
                "about_id": ABOUT,
                "enqueue_at": "2026-10-23T13:26:00Z",
            },
        ),
    )

    result = await relay.run_once()

    assert result == RelayResult(published=0, failed=1, skipped_no_lock=False)
    assert bus.calls == []
    node = await outbox_node(neo4j_driver, "out-w9")
    assert node["attempts"] == 1
    assert node["status"] == "pending"


async def test_a_cancel_for_work_that_is_not_stored_fails_and_cancels_nothing(
    relay: OutboxRelay,
    bus: SpyBus,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    await add_messages(
        uow_factory,
        outbox_message(
            "cancel-w9",
            topic="scheduled.work",
            event_type="CancelWork",
            payload={"work_id": "w9"},
        ),
    )

    result = await relay.run_once()

    assert result == RelayResult(published=0, failed=1, skipped_no_lock=False)
    assert bus.calls == []
    assert (await outbox_node(neo4j_driver, "cancel-w9"))["attempts"] == 1


# run_forever


@pytest_asyncio.fixture
async def running(
    make_relay: Callable[..., OutboxRelay],
) -> AsyncIterator[Callable[..., tuple[asyncio.Event, asyncio.Task[None]]]]:
    tasks: list[asyncio.Task[None]] = []
    stops: list[asyncio.Event] = []

    def start(**options: object) -> tuple[asyncio.Event, asyncio.Task[None]]:
        relay = make_relay(poll_interval_s=0.01, backoff_start_s=0.01, **options)
        stop = asyncio.Event()
        task = asyncio.ensure_future(relay.run_forever(stop))
        tasks.append(task)
        stops.append(stop)
        return stop, task

    yield start
    for stop in stops:
        stop.set()
    for task in tasks:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(task, timeout=5)


async def _until(check: Callable[[], bool], seconds: float = 10.0) -> None:
    async with asyncio.timeout(seconds):
        while not check():
            await asyncio.sleep(0.02)


async def test_run_forever_publishes_what_arrives_and_stops_when_asked(
    running: Callable[..., tuple[asyncio.Event, asyncio.Task[None]]],
    bus: SpyBus,
    uow_factory: UnitOfWorkFactory,
) -> None:
    stop, task = running()
    await add_messages(uow_factory, outbox_message("out-1", 0))
    await _until(lambda: len(bus.published) == 1)
    await add_messages(uow_factory, outbox_message("out-2", 1))
    await _until(lambda: len(bus.published) == 2)

    stop.set()
    await asyncio.wait_for(task, timeout=2)

    assert [message.id for message in bus.published] == ["out-1", "out-2"]


async def test_run_forever_stops_at_once_when_it_is_waiting_between_rounds(
    make_relay: Callable[..., OutboxRelay],
) -> None:
    relay = make_relay(poll_interval_s=60.0)
    stop = asyncio.Event()
    task = asyncio.ensure_future(relay.run_forever(stop))
    await asyncio.sleep(0.2)

    stop.set()

    await asyncio.wait_for(task, timeout=2)


async def test_run_forever_goes_on_after_a_round_fails_and_loses_no_message(
    make_relay: Callable[..., OutboxRelay],
    bus: SpyBus,
    clock: FixedClock,
    cache: InMemoryCache,
    uow_factory: UnitOfWorkFactory,
    tenant_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FlakyTenants:
        def __init__(self) -> None:
            self.calls = 0

        async def active_tenant_ids(self) -> list[str]:
            self.calls += 1
            if self.calls <= 2:
                raise ConnectionError(f"directory down {SECRET_TEXT}")
            return [tenant_id]

    flaky = FlakyTenants()
    relay = OutboxRelay(
        uow_factory, bus, cache, clock, flaky, poll_interval_s=0.01, backoff_start_s=0.01
    )
    await add_messages(uow_factory, outbox_message("out-1"))
    stop = asyncio.Event()

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        task = asyncio.ensure_future(relay.run_forever(stop))
        await _until(lambda: len(bus.published) == 1)
        stop.set()
        await asyncio.wait_for(task, timeout=2)

    assert flaky.calls >= 3
    assert SECRET_TEXT not in caplog.text
