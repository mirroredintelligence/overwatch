"""Integration tests for ConfirmCapacity (U02), against the real Neo4j the harness starts.

UCR West is seeded with a number report of 3 at 08:15 London on Friday 23 October 2026 (07:15 UTC).
Every assertion reads back through a fresh unit of work or the harness helpers. Values are
synthetic. There is no patient data.
"""

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any, Self

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.use_cases.confirm_capacity import (
    ConfirmCapacity,
    ConfirmCapacityCommand,
    ConfirmCapacityResult,
)
from diucs.application.use_cases.report_capacity import ReportCapacity, ReportCapacityCommand
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
    Status,
)
from diucs.domain.errors import (
    ConfirmLimitReached,
    Conflict,
    NotAllowed,
    NotFound,
    NothingToConfirm,
)
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.neo4j import count_nodes, read_tx

Seed = Callable[..., Awaitable[None]]

pytestmark = pytest.mark.asyncio(loop_scope="session")

REPORT_AT = datetime(2026, 10, 23, 7, 15, tzinfo=UTC)  # 08:15 BST
AT_1005 = datetime(2026, 10, 23, 9, 5, tzinfo=UTC)  # 10:05 BST
AT_1205 = datetime(2026, 10, 23, 11, 5, tzinfo=UTC)  # 12:05 BST
AT_1412 = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)  # 14:12 BST
SEED_REPORT_ID = "seed-number-0815"

REPORTER = Actor(
    role=Role.REPORTER,
    practitioner_id="prac-reporter-1",
    device_id="device-1",
    channel="text",
    service_ids=frozenset({"ucr-west"}),
)
ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)
UCR_WEST = ServiceProfile(
    id="ucr-west",
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)


def _seed_report(value: int = 3) -> CapacityReport:
    return CapacityReport(
        id=SEED_REPORT_ID,
        service_id="ucr-west",
        value=value,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=REPORT_AT,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )


class GatedUnitOfWork:
    """Wraps a real unit of work. When `hold` was set before it opened, its commit announces
    itself on `entered` and waits for `release`, so the write locks it holds stay held (the test
    forces the interleaving; a timing race alone cannot, lesson L94)."""

    def __init__(self, inner: UnitOfWork, gate: CommitGate, hold: bool) -> None:
        self._inner = inner
        self._gate = gate
        self._hold = hold

    async def __aenter__(self) -> Self:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> Any:
        return await self._inner.__aexit__(*exc)

    async def commit(self) -> None:
        if self._hold:
            self._gate.entered.set()
            await self._gate.release.wait()
        await self._inner.commit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class CommitGate:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.hold_next = False


def gated_factory(factory: UnitOfWorkFactory, gate: CommitGate) -> UnitOfWorkFactory:
    """A factory whose next unit of work is held at commit, if gate.hold_next was set."""

    def make() -> UnitOfWork:
        hold = gate.hold_next
        gate.hold_next = False
        return GatedUnitOfWork(factory(), gate, hold)  # type: ignore[return-value]

    return make


async def _seed_with_report(
    factory: UnitOfWorkFactory, seed_service: Seed, report: CapacityReport | None
) -> None:
    await seed_service(UCR_WEST)
    if report is not None:
        async with factory() as uow:
            await uow.capacity.add(report)
            await uow.commit()


class Rig:
    def __init__(
        self, factory: UnitOfWorkFactory, driver: AsyncDriver, ids: SequentialIds | None = None
    ) -> None:
        self.clock = FixedClock(AT_1005)
        ids = ids or SequentialIds()
        store = DriverIdempotencyStore(driver)
        self.confirm = ConfirmCapacity(factory, self.clock, ids, store)
        self.report = ReportCapacity(factory, self.clock, ids, store)

    async def number(self, value: int, at: datetime, key: str) -> None:
        self.clock.set(at)
        await self.report.execute(
            ReportCapacityCommand(
                idempotency_key=key,
                actor=REPORTER,
                service_id="ucr-west",
                value=value,
                source=ReportSource.TEXT,
            )
        )

    async def yes(
        self,
        at: datetime,
        key: str,
        *,
        actor: Actor = REPORTER,
        source: ReportSource = ReportSource.TEXT,
        performer: str | None = None,
        service_id: str = "ucr-west",
    ) -> ConfirmCapacityResult:
        self.clock.set(at)
        return await self.confirm.execute(
            ConfirmCapacityCommand(
                idempotency_key=key,
                actor=actor,
                service_id=service_id,
                source=source,
                performer_role_id=performer,
            )
        )


async def _latest(factory: UnitOfWorkFactory) -> CapacityReport | None:
    async with factory() as uow:
        return await uow.capacity.latest("ucr-west")


async def _confirmed_count(driver: AsyncDriver) -> int:
    async def work(tx: AsyncManagedTransaction) -> int:
        row = await (
            await tx.run("MATCH (o:Observation {ext_reportType: 'confirmed'}) RETURN count(o) AS n")
        ).single()
        assert row is not None
        return int(row["n"])

    return await read_tx(driver, work)


async def _outbox(factory: UnitOfWorkFactory) -> list[OutboxMessage]:
    async with factory() as uow:
        return await uow.outbox.pending(limit=1000)


async def _derived_from(driver: AsyncDriver, report_id: str) -> list[str]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (:Observation {id: $id})-[:DERIVED_FROM]->(t:Observation) RETURN t.id AS id",
            id=report_id,
        )
        return await result.data()

    return [str(row["id"]) for row in await read_tx(driver, work)]


async def test_a_confirmation_is_stored_as_a_confirmed_report_derived_from_the_latest(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())

    result = await Rig(uow_factory, neo4j_driver).yes(AT_1005, "k1")

    latest = await _latest(uow_factory)
    assert latest is not None
    assert latest.report_type is ReportType.CONFIRMED
    assert latest.value == 3
    assert latest.effective_at == AT_1005
    assert latest.derived_from == SEED_REPORT_ID
    assert latest.id == result.report_id
    assert await _derived_from(neo4j_driver, latest.id) == [SEED_REPORT_ID]
    assert result.confirmed_value == 3
    assert result.replayed is False
    assert result.status is Status.ACCEPTING


async def test_a_second_confirmation_is_accepted_and_derives_from_the_latest_confirmation(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver)
    first = await rig.yes(AT_1005, "k1")

    second = await rig.yes(AT_1205, "k2")

    latest = await _latest(uow_factory)
    assert latest is not None
    assert latest.id == second.report_id
    assert latest.derived_from == first.report_id
    assert latest.value == 3
    assert await _confirmed_count(neo4j_driver) == 2


async def test_a_third_confirmation_in_a_row_is_refused_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver)
    await rig.yes(AT_1005, "k1")
    await rig.yes(AT_1205, "k2")
    outbox_before = len(await _outbox(uow_factory))
    audits_before = await count_nodes(neo4j_driver, "AuditEvent")
    communications_before = await count_nodes(neo4j_driver, "Communication")

    with pytest.raises(ConfirmLimitReached):
        await rig.yes(AT_1412, "k3", performer="role-1")

    assert await _confirmed_count(neo4j_driver) == 2
    assert len(await _outbox(uow_factory)) == outbox_before
    assert await count_nodes(neo4j_driver, "OutboxMessage") == outbox_before
    assert await count_nodes(neo4j_driver, "AuditEvent") == audits_before
    assert await count_nodes(neo4j_driver, "Communication") == communications_before


async def test_a_new_number_resets_the_count(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, None)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.number(3, REPORT_AT, "n1")
    await rig.yes(AT_1005, "y1")
    await rig.yes(AT_1205, "y2")
    await rig.number(5, AT_1205 + timedelta(minutes=10), "n2")

    result = await rig.yes(AT_1205 + timedelta(minutes=20), "y3")

    assert result.confirmed_value == 5
    latest = await _latest(uow_factory)
    assert latest is not None
    assert latest.report_type is ReportType.CONFIRMED
    assert latest.value == 5


async def test_nothing_on_record_is_nothing_to_confirm(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, None)

    with pytest.raises(NothingToConfirm):
        await Rig(uow_factory, neo4j_driver).yes(AT_1005, "k1")

    assert await count_nodes(neo4j_driver, "Observation") == 0
    assert await count_nodes(neo4j_driver, "OutboxMessage") == 0
    assert await count_nodes(neo4j_driver, "AuditEvent") == 0


async def test_a_text_confirmation_gets_the_c3_echo_with_the_confirmed_value(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())

    await Rig(uow_factory, neo4j_driver).yes(AT_1005, "k1", performer="role-1")

    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (c:Communication) OPTIONAL MATCH (c)-[:TOPIC]->(t:Concept) "
            "RETURN c.payloadText AS text, t.code AS messageId"
        )
        return await result.data()

    rows = await read_tx(neo4j_driver, work)
    assert len(rows) == 1
    assert rows[0]["messageId"] == "C3"
    assert "UCR West: 3 referrals" in rows[0]["text"]
    sends = [m for m in await _outbox(uow_factory) if m.event_type == "SendMessage"]
    assert len(sends) == 1
    assert sends[0].payload["recipient_role_id"] == "role-1"


async def test_a_link_confirmation_is_not_echoed(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    link_actor = dataclasses.replace(REPORTER, channel="link")

    await Rig(uow_factory, neo4j_driver).yes(
        AT_1005, "k1", actor=link_actor, source=ReportSource.LINK, performer="role-1"
    )

    assert await count_nodes(neo4j_driver, "Communication") == 0


async def test_confirming_an_overdue_service_writes_status_changed_from_not_updated(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())

    result = await Rig(uow_factory, neo4j_driver).yes(AT_1412, "k1")

    assert result.status is Status.ACCEPTING
    assert result.status_changed is True
    changes = [m for m in await _outbox(uow_factory) if m.event_type == "StatusChanged"]
    assert len(changes) == 1
    assert changes[0].payload["before"] == "not-updated"
    assert changes[0].payload["after"] == "accepting"
    reported = [m for m in await _outbox(uow_factory) if m.event_type == "CapacityReported"]
    assert len(reported) == 1


async def test_a_replayed_key_returns_the_first_result_and_writes_once(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver)
    first = await rig.yes(AT_1005, "k1")
    outbox_after_first = len(await _outbox(uow_factory))

    second = await rig.yes(AT_1205, "k1")

    assert second == dataclasses.replace(first, replayed=True)
    assert await _confirmed_count(neo4j_driver) == 1
    assert await count_nodes(neo4j_driver, "AuditEvent") == 1
    assert len(await _outbox(uow_factory)) == outbox_after_first


async def test_a_reused_key_for_another_service_or_actor_is_a_conflict(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver)
    await rig.yes(AT_1005, "k1", performer="role-1")

    with pytest.raises(Conflict):
        await rig.yes(AT_1205, "k1", performer="role-2")

    assert await _confirmed_count(neo4j_driver) == 1


async def test_a_key_used_by_a_report_is_a_conflict_for_a_confirmation(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver)
    await rig.number(4, AT_1005, "shared")

    with pytest.raises(Conflict):
        await rig.yes(AT_1205, "shared")

    assert await _confirmed_count(neo4j_driver) == 0


async def test_the_audit_record_names_the_confirmation(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver)
    await rig.yes(AT_1005, "k1")
    result = await rig.yes(AT_1205, "k2")

    async with uow_factory() as uow:
        records = await uow.audit.records()
        chain_ok = await uow.audit.verify_chain()

    assert [r.entry.use_case for r in records] == ["ConfirmCapacity", "ConfirmCapacity"]
    entry = records[1].entry
    assert entry.action == "C"
    assert entry.actor == REPORTER
    assert entry.entity_ids == (result.report_id, "ucr-west")
    assert entry.at == AT_1205
    assert entry.snapshot is not None
    assert entry.snapshot["value"] == 3
    assert entry.snapshot["derived_from"] is not None
    assert entry.snapshot["consecutive"] == 2
    assert records[0].entry.snapshot is not None
    assert records[0].entry.snapshot["consecutive"] == 1
    assert chain_ok is True


async def test_a_confirmation_from_a_confirmed_figure_of_zero_is_kept_as_zero(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report(value=0))

    result = await Rig(uow_factory, neo4j_driver).yes(AT_1005, "k1")

    assert result.confirmed_value == 0
    assert result.status is Status.NOT_ACCEPTING


async def test_a_reporter_for_another_service_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    other = dataclasses.replace(REPORTER, service_ids=frozenset({"ucr-east"}))

    with pytest.raises(NotAllowed):
        await Rig(uow_factory, neo4j_driver).yes(AT_1005, "k1", actor=other)

    assert await _confirmed_count(neo4j_driver) == 0


async def test_an_advisor_may_confirm_only_as_advisor_phoned(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver)

    with pytest.raises(NotAllowed):
        await rig.yes(AT_1005, "k1", actor=ADVISOR, source=ReportSource.TEXT)
    result = await rig.yes(AT_1005, "k2", actor=ADVISOR, source=ReportSource.ADVISOR_PHONED)

    assert result.confirmed_value == 3


async def test_an_unknown_service_is_not_found(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, None)

    with pytest.raises(NotFound):
        await Rig(uow_factory, neo4j_driver).yes(AT_1005, "k1", service_id="nowhere")


async def test_an_inactive_service_is_not_found(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(dataclasses.replace(UCR_WEST, active=False))

    with pytest.raises(NotFound):
        await Rig(uow_factory, neo4j_driver).yes(AT_1005, "k1")

    assert await _confirmed_count(neo4j_driver) == 0


async def test_a_suspended_service_confirms_and_is_not_updated(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """domain-rules 1.3 step 1: an active suspended flag makes the status Not updated. U02 does
    not refuse a confirmation for a suspended service, as U01 does not refuse a report (DEC-112
    item 9)."""
    flag = ServiceFlag(
        service_id="ucr-west",
        code=SERVICE_FLAG_SUSPENDED,
        active=True,
        reason="suspended for the test",
        actor_id="prac-lead-1",
        at=REPORT_AT,
    )
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    async with uow_factory() as uow:
        await uow.flags.set_service_flag(flag)
        await uow.commit()

    result = await Rig(uow_factory, neo4j_driver).yes(AT_1005, "k1")

    assert result.status is Status.NOT_UPDATED
    assert result.confirmed_value == 3
    assert await _confirmed_count(neo4j_driver) == 1


async def test_a_key_stored_by_a_report_is_a_conflict_for_a_confirmation_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """Reverse direction of the shared key space (DEC-112 item 6): the key ReportCapacity stored
    is refused by ConfirmCapacity, whatever its body."""
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver)
    await rig.number(4, AT_1005, "shared-2")
    reports_before = await count_nodes(neo4j_driver, "Observation")

    with pytest.raises(Conflict):
        await rig.yes(AT_1205, "shared-2")

    assert await count_nodes(neo4j_driver, "Observation") == reports_before
    assert await _confirmed_count(neo4j_driver) == 0


async def test_a_reporter_for_another_service_is_refused_before_nothing_to_confirm(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """DEC-112 item 5: a refused actor learns nothing about the figure. A service with no report
    must answer NotAllowed to another service's reporter, not NothingToConfirm."""
    await _seed_with_report(uow_factory, seed_service, None)
    other = dataclasses.replace(REPORTER, service_ids=frozenset({"ucr-east"}))

    with pytest.raises(NotAllowed):
        await Rig(uow_factory, neo4j_driver).yes(AT_1005, "k1", actor=other)

    assert await _confirmed_count(neo4j_driver) == 0
    assert await count_nodes(neo4j_driver, "Observation") == 0


async def test_a_reporter_for_another_service_is_refused_before_the_limit(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """DEC-112 item 5: a service already confirmed twice in a row must answer NotAllowed to
    another service's reporter, not ConfirmLimitReached, so the refusal reveals nothing."""
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver)
    await rig.yes(AT_1005, "k1")
    await rig.yes(AT_1205, "k2")
    other = dataclasses.replace(REPORTER, service_ids=frozenset({"ucr-east"}))

    with pytest.raises(NotAllowed):
        await rig.yes(AT_1412, "k3", actor=other)

    assert await _confirmed_count(neo4j_driver) == 2


async def test_a_text_confirmation_stores_the_performer_the_command_carried(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """The confirmation report records who performed it (the performer role the command named),
    read back through a fresh unit of work, not only the echo."""
    await _seed_with_report(uow_factory, seed_service, _seed_report())

    await Rig(uow_factory, neo4j_driver).yes(AT_1005, "k1", performer="role-1")

    latest = await _latest(uow_factory)
    assert latest is not None
    assert latest.report_type is ReportType.CONFIRMED
    assert latest.performer_role_id == "role-1"


async def test_a_key_stored_by_a_confirmation_is_a_conflict_for_a_report_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """DEC-112 item 6, reverse direction: a key ConfirmCapacity stored is refused by
    ReportCapacity with Conflict. The refusal comes from the idempotency store's put (a different
    result for a stored key), so the unit of work that wrote the report never commits."""
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    ids = SequentialIds()
    rig = Rig(uow_factory, neo4j_driver, ids)
    await rig.yes(AT_1005, "shared-3")
    observations_before = await count_nodes(neo4j_driver, "Observation")

    with pytest.raises(Conflict):
        await rig.number(4, AT_1205, "shared-3")

    assert await count_nodes(neo4j_driver, "Observation") == observations_before
    assert await _confirmed_count(neo4j_driver) == 1
    latest = await _latest(uow_factory)
    assert latest is not None
    assert latest.value == 3


async def test_a_second_confirmation_waits_for_a_held_confirmation_then_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """The first confirmation is held at commit, with its write lock on the service. A second one
    with another key must wait, then see the first and be refused: exactly two confirmed reports."""
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    ids = SequentialIds()  # one generator for the whole test: report ids never collide (L134)
    await Rig(uow_factory, neo4j_driver, ids).yes(AT_1005, "k1")  # one confirmed, committed

    gate = CommitGate()
    store = DriverIdempotencyStore(neo4j_driver)
    clock = FixedClock(AT_1205)
    held = ConfirmCapacity(gated_factory(uow_factory, gate), clock, ids, store)
    second = ConfirmCapacity(uow_factory, clock, ids, store)
    command_a = ConfirmCapacityCommand("k2", REPORTER, "ucr-west", ReportSource.TEXT)
    command_b = ConfirmCapacityCommand("k3", REPORTER, "ucr-west", ReportSource.TEXT)

    gate.hold_next = True
    first_task = asyncio.ensure_future(held.execute(command_a))
    await asyncio.wait_for(gate.entered.wait(), timeout=30)
    second_task = asyncio.ensure_future(second.execute(command_b))
    await asyncio.sleep(1.0)
    still_waiting = not second_task.done()
    gate.release.set()

    first_result = await asyncio.wait_for(first_task, timeout=60)
    with pytest.raises(ConfirmLimitReached):
        await asyncio.wait_for(second_task, timeout=60)

    assert still_waiting is True
    assert first_result.confirmed_value == 3
    assert await _confirmed_count(neo4j_driver) == 2
    assert await count_nodes(neo4j_driver, "Observation") == 3


async def test_the_same_key_twice_at_once_writes_once_and_replays_inside_the_unit_of_work(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """Both calls pass the early key check before either has committed. The second waits on the
    service lock, then finds the first one's stored result inside its own unit of work and replays
    it (DEC-112 items 6 and 8). One confirmed report, one audit event."""
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    ids = SequentialIds()
    gate = CommitGate()
    store = DriverIdempotencyStore(neo4j_driver)
    clock = FixedClock(AT_1205)
    held = ConfirmCapacity(gated_factory(uow_factory, gate), clock, ids, store)
    second = ConfirmCapacity(uow_factory, clock, ids, store)
    command = ConfirmCapacityCommand("k1", REPORTER, "ucr-west", ReportSource.TEXT)

    gate.hold_next = True
    first_task = asyncio.ensure_future(held.execute(command))
    await asyncio.wait_for(gate.entered.wait(), timeout=30)
    second_task = asyncio.ensure_future(second.execute(command))
    await asyncio.sleep(1.0)
    still_waiting = not second_task.done()
    gate.release.set()

    first_result = await asyncio.wait_for(first_task, timeout=60)
    second_result = await asyncio.wait_for(second_task, timeout=60)

    assert still_waiting is True
    assert second_result == dataclasses.replace(first_result, replayed=True)
    assert await _confirmed_count(neo4j_driver) == 1
    assert await count_nodes(neo4j_driver, "AuditEvent") == 1


async def test_sixteen_confirmations_at_once_let_exactly_two_through(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """Sixteen callers with sixteen keys: the limit holds under real concurrency (L94, L102).
    Every caller must end in success or ConfirmLimitReached, never another error."""
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver)

    outcomes = await asyncio.gather(
        *(rig.yes(AT_1005, f"race-{i}") for i in range(16)), return_exceptions=True
    )

    accepted = [o for o in outcomes if isinstance(o, ConfirmCapacityResult)]
    refused = [o for o in outcomes if isinstance(o, ConfirmLimitReached)]
    assert len(accepted) == 2
    assert len(refused) == 14
    assert len(accepted) + len(refused) == 16
    assert await _confirmed_count(neo4j_driver) == 2
