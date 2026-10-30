"""The outbox relay with two tenants (I03, DEC-130 to DEC-134). The relay is a worker, so it has no
request: it goes through the tenant directory, binds each tenant in turn, and opens every unit of
work under that tenant (DEC-146). Tenant A's relay never touches tenant B's rows, and every message
it publishes or schedules carries its tenant.

Message and work ids differ between the two tenants in these tests, because the outbox id and the
ScheduledWork id are still unique across the whole graph (TEN-005, TEN-016); the evidence lists
that as tenant-pending.
"""

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
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
from diucs.application.ports.outbound.outbox import MAX_ATTEMPTS
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.scheduling import cancel_work
from diucs.application.tenancy import ScopeId
from tests.support.relay_rig import (
    DUE,
    NOW,
    SECRET_TEXT,
    FlakyLockCache,
    InstrumentedFactory,
    SpyBus,
    TenantPrefixedCache,
    add_messages,
    add_scheduled,
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
def relay_for(
    uow_factory: UnitOfWorkFactory, bus: SpyBus, cache: InMemoryCache, clock: FixedClock
) -> Callable[..., OutboxRelay]:
    """A relay over the listed tenant ids, in that order."""

    def make(*tenant_ids: str, **options: Any) -> OutboxRelay:
        factory = options.pop("factory", uow_factory)
        return OutboxRelay(
            factory, bus, options.pop("cache", cache), clock, StaticTenants(tenant_ids), **options
        )

    return make


async def _seed_two_tenants(
    uow_factory_a: UnitOfWorkFactory, uow_factory_b: UnitOfWorkFactory
) -> None:
    await add_messages(uow_factory_a, outbox_message("a-1", 0), outbox_message("a-2", 1))
    await add_messages(uow_factory_b, outbox_message("b-1", 0), outbox_message("b-2", 1))


async def test_a_relay_for_tenant_a_never_publishes_tenant_b_rows(
    relay_for: Callable[..., OutboxRelay],
    bus: SpyBus,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _seed_two_tenants(uow_factory_a, uow_factory_b)
    b_before = [
        await outbox_node(neo4j_driver, "b-1", scope=other_tenant_id),
        await outbox_node(neo4j_driver, "b-2", scope=other_tenant_id),
    ]

    result = await relay_for(tenant_id).run_once()

    assert result == RelayResult(published=2, failed=0, skipped_no_lock=False)
    assert [message.id for message in bus.published] == ["a-1", "a-2"]
    assert {message.tenant_id for message in bus.published} == {tenant_id}
    assert [
        await outbox_node(neo4j_driver, "b-1", scope=other_tenant_id),
        await outbox_node(neo4j_driver, "b-2", scope=other_tenant_id),
    ] == (b_before)
    assert b_before[0]["status"] == "pending"
    assert b_before[0]["attempts"] == 0
    assert (await outbox_node(neo4j_driver, "a-1"))["status"] == "published"


async def test_a_relay_for_tenant_b_leaves_tenant_a_untouched(
    relay_for: Callable[..., OutboxRelay],
    bus: SpyBus,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    other_tenant_id: str,
    tenant_id: str,
) -> None:
    await _seed_two_tenants(uow_factory_a, uow_factory_b)

    await relay_for(other_tenant_id).run_once()

    assert [message.id for message in bus.published] == ["b-1", "b-2"]
    assert {message.tenant_id for message in bus.published} == {other_tenant_id}
    assert (await outbox_node(neo4j_driver, "a-1"))["status"] == "pending"
    assert (await outbox_node(neo4j_driver, "a-2"))["status"] == "pending"


async def test_both_tenants_are_relayed_and_each_message_carries_its_own_tenant(
    relay_for: Callable[..., OutboxRelay],
    bus: SpyBus,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _seed_two_tenants(uow_factory_a, uow_factory_b)

    result = await relay_for(tenant_id, other_tenant_id).run_once()

    assert result == RelayResult(published=4, failed=0, skipped_no_lock=False)
    assert {message.id: message.tenant_id for message in bus.published} == {
        "a-1": tenant_id,
        "a-2": tenant_id,
        "b-1": other_tenant_id,
        "b-2": other_tenant_id,
    }


async def test_every_unit_of_work_opens_under_the_tenant_being_relayed(
    relay_for: Callable[..., OutboxRelay],
    uow_factory: UnitOfWorkFactory,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _seed_two_tenants(uow_factory_a, uow_factory_b)
    factory = InstrumentedFactory(uow_factory)

    await relay_for(tenant_id, other_tenant_id, factory=factory).run_once()

    a, b = ScopeId.tenant(tenant_id), ScopeId.tenant(other_tenant_id)
    # One unit to read each tenant's pending rows and one to mark each of its two messages.
    assert factory.scopes == [a, a, a, b, b, b]


async def test_the_lock_is_taken_under_the_tenant_and_one_tenants_lock_does_not_block_another(
    relay_for: Callable[..., OutboxRelay],
    bus: SpyBus,
    cache: InMemoryCache,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _seed_two_tenants(uow_factory_a, uow_factory_b)
    prefixed = TenantPrefixedCache(cache)
    held = await cache.acquire_lock(f"{tenant_id}:{LOCK_NAME}", LOCK_TTL)
    assert held is not None

    result = await relay_for(tenant_id, other_tenant_id, cache=prefixed).run_once()

    assert result == RelayResult(published=2, failed=0, skipped_no_lock=True)
    assert [message.id for message in bus.published] == ["b-1", "b-2"]
    assert prefixed.names == [f"{tenant_id}:{LOCK_NAME}", f"{other_tenant_id}:{LOCK_NAME}"]


async def test_one_tenant_failing_does_not_stop_or_slow_another(
    relay_for: Callable[..., OutboxRelay],
    bus: SpyBus,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _seed_two_tenants(uow_factory_a, uow_factory_b)
    bus.always_fail["a-1"] = ConnectionError("down")
    relay = relay_for(tenant_id, other_tenant_id)

    first = await relay.run_once()
    await add_messages(uow_factory_b, outbox_message("b-3", 2))
    tried_a = len([call for call in bus.calls if call[1] in ("a-1", "a-2")])
    second = await relay.run_once()

    # Tenant A failed on a-1 and went on to a-2; tenant B published both of its rows.
    assert first == RelayResult(published=3, failed=1, skipped_no_lock=False)
    # The next round, with no time passed, leaves tenant A to wait and still serves tenant B.
    assert second == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert len([call for call in bus.calls if call[1] in ("a-1", "a-2")]) == tried_a
    assert (await outbox_node(neo4j_driver, "b-3", scope=other_tenant_id))["status"] == "published"
    assert (await outbox_node(neo4j_driver, "a-1"))["attempts"] == 1


async def test_a_directory_entry_that_is_not_a_tenant_is_skipped_and_the_rest_go_on(
    relay_for: Callable[..., OutboxRelay],
    bus: SpyBus,
    uow_factory_a: UnitOfWorkFactory,
    tenant_id: str,
) -> None:
    await add_messages(uow_factory_a, outbox_message("a-1"))

    result = await relay_for("net-abcd1234", "Not A Tenant", tenant_id).run_once()

    assert result == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert [message.id for message in bus.published] == ["a-1"]


async def test_a_dead_message_is_logged_with_its_id_topic_and_tenant_only(
    relay_for: Callable[..., OutboxRelay],
    bus: SpyBus,
    clock: FixedClock,
    uow_factory_a: UnitOfWorkFactory,
    tenant_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await add_messages(uow_factory_a, outbox_message("a-1", topic="booking.events"))
    bus.always_fail["a-1"] = ConnectionError("down")
    relay = relay_for(tenant_id)

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        for _ in range(MAX_ATTEMPTS):
            await relay.run_once()
            clock.advance(timedelta(seconds=61))

    dead = [r.getMessage() for r in caplog.records if "dead" in r.getMessage().lower()]
    assert len(dead) == 1
    assert "a-1" in dead[0]
    assert "booking.events" in dead[0]
    assert tenant_id in dead[0]
    assert "4821" not in caplog.text


async def test_scheduled_work_is_scheduled_with_its_tenant_and_the_number_is_saved_under_it(
    relay_for: Callable[..., OutboxRelay],
    bus: SpyBus,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await add_scheduled(uow_factory_a, "wa1", "out-wa1")
    await add_scheduled(uow_factory_b, "wb1", "out-wb1")

    only_a = await relay_for(tenant_id).run_once()

    assert only_a == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert bus.calls == [("schedule", "out-wa1", 1)]
    assert (await work_node(neo4j_driver, "wa1"))["sequenceNumber"] == 1
    assert "sequenceNumber" not in await work_node(neo4j_driver, "wb1", scope=other_tenant_id)
    assert (await outbox_node(neo4j_driver, "out-wb1", scope=other_tenant_id))[
        "status"
    ] == "pending"

    both = await relay_for(tenant_id, other_tenant_id).run_once()

    assert both == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert (await work_node(neo4j_driver, "wb1", scope=other_tenant_id))["sequenceNumber"] == 2
    delivered = {message.id: message.tenant_id for _, message in bus.inner.due(DUE)}
    assert delivered == {"out-wa1": tenant_id, "out-wb1": other_tenant_id}


async def test_a_cancel_in_tenant_a_cancels_only_tenant_as_scheduled_message(
    relay_for: Callable[..., OutboxRelay],
    bus: SpyBus,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    work_a = await add_scheduled(uow_factory_a, "wa1", "out-wa1")
    await add_scheduled(uow_factory_b, "wb1", "out-wb1")
    await relay_for(tenant_id, other_tenant_id).run_once()
    async with uow_factory_a() as uow:
        await cancel_work(uow, work_a, NOW)
        await uow.commit()

    await relay_for(tenant_id, other_tenant_id).run_once()

    assert bus.calls_of("cancel") == [("cancel", 1)]
    assert [(message.id, message.tenant_id) for _, message in bus.inner.due(DUE)] == [
        ("out-wb1", other_tenant_id)
    ]
    assert (await work_node(neo4j_driver, "wb1", scope=other_tenant_id))["status"] == "scheduled"


async def test_a_cache_that_cannot_give_one_tenants_lock_costs_that_tenant_a_wait_only(
    relay_for: Callable[..., OutboxRelay],
    bus: SpyBus,
    cache: InMemoryCache,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _seed_two_tenants(uow_factory_a, uow_factory_b)
    flaky = FlakyLockCache(cache)
    flaky.acquire_fails.add(tenant_id)
    relay = relay_for(tenant_id, other_tenant_id, cache=flaky)

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        first = await relay.run_once()
        again = await relay.run_once()

    assert first == RelayResult(published=2, failed=0, skipped_no_lock=False)
    assert [message.id for message in bus.published] == ["b-1", "b-2"]
    # Tenant A is waiting, so the second round (no time passed) leaves it alone.
    assert again == RelayResult(published=0, failed=0, skipped_no_lock=False)
    assert "ConnectionError" in caplog.text
    assert SECRET_TEXT not in caplog.text


async def test_a_lock_that_cannot_be_released_does_not_undo_the_round(
    relay_for: Callable[..., OutboxRelay],
    bus: SpyBus,
    cache: InMemoryCache,
    uow_factory_a: UnitOfWorkFactory,
    tenant_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await add_messages(uow_factory_a, outbox_message("a-1"))
    flaky = FlakyLockCache(cache)
    flaky.release_fails.add(tenant_id)

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        result = await relay_for(tenant_id, cache=flaky).run_once()

    assert result == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert "ConnectionError" in caplog.text
    assert SECRET_TEXT not in caplog.text


async def test_when_the_attempt_cannot_be_counted_the_batch_stops_and_the_tenant_waits(
    relay_for: Callable[..., OutboxRelay],
    bus: SpyBus,
    clock: FixedClock,
    uow_factory: UnitOfWorkFactory,
    uow_factory_a: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    await add_messages(uow_factory_a, outbox_message("a-1", 0), outbox_message("a-2", 1))
    bus.failures["a-1"] = [ConnectionError("down")]
    factory = InstrumentedFactory(uow_factory, fail_mark_failed={"a-1"})
    relay = relay_for(tenant_id, factory=factory)

    result = await relay.run_once()
    tried_in_the_first_round = [call[1] for call in bus.calls]
    at_once = await relay.run_once()
    clock.advance(timedelta(seconds=1))
    after_the_wait = await relay.run_once()

    assert result == RelayResult(published=0, failed=1, skipped_no_lock=False)
    assert tried_in_the_first_round == ["a-1"]  # a-2 was not tried
    assert (await outbox_node(neo4j_driver, "a-1"))["attempts"] == 0
    assert at_once == RelayResult(published=0, failed=0, skipped_no_lock=False)
    assert after_the_wait == RelayResult(published=2, failed=0, skipped_no_lock=False)


async def test_a_tenant_listed_twice_is_relayed_once(
    relay_for: Callable[..., OutboxRelay],
    uow_factory: UnitOfWorkFactory,
    uow_factory_a: UnitOfWorkFactory,
    tenant_id: str,
) -> None:
    await add_messages(uow_factory_a, outbox_message("a-1"))
    factory = InstrumentedFactory(uow_factory)

    result = await relay_for(tenant_id, tenant_id, factory=factory).run_once()

    assert result == RelayResult(published=1, failed=0, skipped_no_lock=False)
    assert len(factory.scopes) == 2  # one read and one mark, not a second round
