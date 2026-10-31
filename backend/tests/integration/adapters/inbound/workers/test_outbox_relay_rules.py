"""The outbox relay: the rows of the capacity-loop triage (KI-88, KI-103), on real Neo4j.

- A bus call that hangs is given up after a timeout and counted as a failed attempt, and the rest
  of the batch goes on (KI-103).
- One row that always fails does not make the whole tenant wait: the tenant waits only when its
  round published nothing (KI-103).
- A crash between the bus accepting a scheduled message and the store keeping its number schedules
  the message again, with the same message id, which the consumers absorb (KI-88).

The clock is 14:16 London; the bus is a recording fake.
"""

import asyncio
from collections.abc import Callable
from datetime import timedelta

import pytest
from neo4j import AsyncDriver

from diucs.adapters.inbound.workers.outbox_relay import OutboxRelay, RelayResult, StaticTenants
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from tests.support.relay_rig import (
    NOW,
    InstrumentedFactory,
    SpyBus,
    add_messages,
    add_scheduled,
    outbox_message,
    outbox_node,
    work_node,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


class HangingBus(SpyBus):
    """A bus whose calls for the chosen ids never return."""

    def __init__(self, inner: ManualEventBus, hang_ids: set[str]) -> None:
        super().__init__(inner)
        self.hang_ids = hang_ids

    async def _maybe_fail(self, message_id: str) -> None:
        if message_id in self.hang_ids:
            await asyncio.sleep(3600)
        await super()._maybe_fail(message_id)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def bus(clock: FixedClock) -> SpyBus:
    return SpyBus(ManualEventBus(clock))


@pytest.fixture
def make_relay(
    uow_factory: UnitOfWorkFactory, clock: FixedClock, tenant_id: str
) -> Callable[..., OutboxRelay]:
    def make(bus: SpyBus, **options: object) -> OutboxRelay:
        factory = options.pop("factory", uow_factory)
        return OutboxRelay(
            factory,  # type: ignore[arg-type]
            bus,
            InMemoryCache(clock),
            clock,
            StaticTenants([tenant_id]),
            **options,  # type: ignore[arg-type]
        )

    return make


# --- KI-103: a bus call that hangs --------------------------------------------------------------


async def test_a_publish_that_hangs_is_given_up_and_the_batch_goes_on(
    make_relay: Callable[..., OutboxRelay],
    clock: FixedClock,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    bus = HangingBus(ManualEventBus(clock), {"out-hang"})
    await add_messages(uow_factory, outbox_message("out-hang", 0), outbox_message("out-ok", 1))

    result = await make_relay(bus, publish_timeout_s=0.05).run_once()

    assert result == RelayResult(published=1, failed=1, skipped_no_lock=False)
    assert [message.id for message in bus.published] == ["out-ok"]
    hung = await outbox_node(neo4j_driver, "out-hang")
    assert hung["status"] == "pending"
    assert hung["attempts"] == 1
    assert hung["lastError"] == "TimeoutError"
    assert (await outbox_node(neo4j_driver, "out-ok"))["status"] == "published"


async def test_a_schedule_that_hangs_is_given_up_and_counted_too(
    make_relay: Callable[..., OutboxRelay],
    clock: FixedClock,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    bus = HangingBus(ManualEventBus(clock), {"out-1"})
    await add_scheduled(uow_factory, "work-1", "out-1")

    result = await make_relay(bus, publish_timeout_s=0.05).run_once()

    assert result == RelayResult(published=0, failed=1, skipped_no_lock=False)
    assert (await outbox_node(neo4j_driver, "out-1"))["lastError"] == "TimeoutError"
    assert (await work_node(neo4j_driver, "work-1")).get("sequenceNumber") is None


async def test_the_timeout_is_shorter_than_the_lock_a_batch_holds() -> None:
    from diucs.adapters.inbound.workers import outbox_relay

    assert outbox_relay.PUBLISH_TIMEOUT_SECONDS > 0
    assert (
        outbox_relay.LOCK_TTL - outbox_relay.LOCK_MARGIN
    ).total_seconds() > outbox_relay.PUBLISH_TIMEOUT_SECONDS


# --- KI-103: one poison row does not back off the tenant ----------------------------------------


async def test_one_row_that_always_fails_does_not_make_the_tenant_wait(
    make_relay: Callable[..., OutboxRelay],
    bus: SpyBus,
    uow_factory: UnitOfWorkFactory,
) -> None:
    bus.always_fail["out-poison"] = ValueError("bad row")
    relay = make_relay(bus)
    await add_messages(
        uow_factory,
        outbox_message("out-1", 0),
        outbox_message("out-poison", 1),
        outbox_message("out-3", 2),
    )

    first = await relay.run_once()
    await add_messages(uow_factory, outbox_message("out-4", 3))
    second = await relay.run_once()  # at once: the clock has not moved

    assert first == RelayResult(published=2, failed=1, skipped_no_lock=False)
    assert second.published == 1
    assert "out-4" in [message.id for message in bus.published]


async def test_a_round_that_published_nothing_still_makes_the_tenant_wait(
    make_relay: Callable[..., OutboxRelay],
    bus: SpyBus,
    clock: FixedClock,
    uow_factory: UnitOfWorkFactory,
) -> None:
    bus.always_fail["out-1"] = ConnectionError("down")
    bus.always_fail["out-2"] = ConnectionError("down")
    relay = make_relay(bus)
    await add_messages(uow_factory, outbox_message("out-1", 0), outbox_message("out-2", 1))
    await relay.run_once()
    tried = len(bus.calls_of("publish"))

    too_early = await relay.run_once()

    assert too_early == RelayResult(published=0, failed=0, skipped_no_lock=False)
    assert len(bus.calls_of("publish")) == tried
    clock.advance(timedelta(seconds=1))
    assert (await relay.run_once()).failed == 2


# --- KI-88: a crash between the bus and the stored number ---------------------------------------


async def test_a_crash_after_the_bus_took_a_schedule_schedules_the_same_message_again(
    make_relay: Callable[..., OutboxRelay],
    bus: SpyBus,
    clock: FixedClock,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
) -> None:
    await add_scheduled(uow_factory, "work-1", "out-1")
    flaky = InstrumentedFactory(uow_factory, fail_mark_published={"out-1"})
    relay = make_relay(bus, factory=flaky)

    first = await relay.run_once()  # the bus has it, the store does not know
    clock.advance(timedelta(seconds=1))
    second = await relay.run_once()

    assert first.published == 0
    assert second.published == 1
    scheduled = [call for call in bus.calls_of("schedule")]
    # The same message id both times: the scheduled-work consumer marks a message id processed once,
    # so the second delivery is a duplicate and does nothing (DEC-190 item 4).
    assert [call[1] for call in scheduled] == ["out-1", "out-1"]
    stored = await work_node(neo4j_driver, "work-1")
    assert stored["sequenceNumber"] == scheduled[-1][2]
    assert (await outbox_node(neo4j_driver, "out-1"))["status"] == "published"


async def test_a_cancel_stops_the_stored_number_and_the_orphan_is_ignored_by_status(
    make_relay: Callable[..., OutboxRelay],
    bus: SpyBus,
    clock: FixedClock,
    uow_factory: UnitOfWorkFactory,
) -> None:
    """The number of the first schedule was lost in the crash, so a cancel stops only the second.
    The first still arrives, and the consumer finds the work cancelled and does nothing: the work
    is the record, the bus message only a wake-up (consumer: ScheduledWorkConsumer.handle)."""
    from diucs.application.scheduling import cancel_work
    from diucs.application.work import CANCELLED

    await add_scheduled(uow_factory, "work-1", "out-1")
    flaky = InstrumentedFactory(uow_factory, fail_mark_published={"out-1"})
    relay = make_relay(bus, factory=flaky)
    await relay.run_once()
    clock.advance(timedelta(seconds=1))
    await relay.run_once()
    async with uow_factory() as uow:
        work = await uow.scheduled_work.get("work-1")
        await cancel_work(uow, work, clock.now())
        await uow.commit()

    async with uow_factory() as uow:
        assert (await uow.scheduled_work.get("work-1")).status == CANCELLED
