"""Integration tests for report flags (U07), against the real Neo4j the harness starts.

A capacity report that breaks a rule raises a flag for the shift lead to check (domain-rules 2.3).
Flags are their own nodes: reports are never edited. Every assertion reads back through a fresh unit
of work or the harness helpers. Values are synthetic. There is no patient data.

Times are on Friday 23 October 2026, in UTC (the service is open from 07:00 to 19:00 UTC).
"""

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity, ConfirmCapacityCommand
from diucs.application.use_cases.report_capacity import (
    ReportCapacity,
    ReportCapacityCommand,
    ReportCapacityResult,
)
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportFlagReason,
    ReportSource,
    Role,
    ServiceCategory,
)
from diucs.domain.model.flags import (
    REPORT_FLAG_CHECKED,
    REPORT_FLAG_OPEN,
    ReportFlag,
)
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.neo4j import count_nodes

Seed = Callable[..., Awaitable[None]]

pytestmark = pytest.mark.asyncio(loop_scope="session")

MANY = ReportFlagReason.MANY_CHANGES
PHONED = ReportFlagReason.DIFFERS_FROM_PHONED
OUT_OF_RANGE = ReportFlagReason.OUT_OF_RANGE_TWICE


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 23, hour, minute, tzinfo=UTC)


REPORTER = Actor(
    role=Role.REPORTER,
    practitioner_id="prac-reporter-1",
    device_id="device-1",
    channel="link",
    service_ids=frozenset({"ucr-west", "ward-a"}),
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
WARD_A = dataclasses.replace(
    UCR_WEST,
    id="ward-a",
    name="Ward A",
    established_capacity=12,
    usual_range=(0, 12),
)


class Rig:
    """The two use cases that write reports, on one clock, one id source and one idempotency
    store. The ids are shared so a second command never reuses a report id (lesson L134)."""

    def __init__(self, factory: UnitOfWorkFactory, driver: AsyncDriver) -> None:
        self.factory = factory
        self.clock = FixedClock(at(13, 0))
        ids = SequentialIds()
        store = DriverIdempotencyStore(driver)
        self.reports = ReportCapacity(factory, self.clock, ids, store)
        self.confirms = ConfirmCapacity(factory, self.clock, ids, store)
        self._count = 0

    def _key(self) -> str:
        self._count += 1
        return f"key-{self._count}"

    async def number(
        self,
        value: int,
        when: datetime,
        *,
        service_id: str = "ucr-west",
        flag: ReportFlagReason | None = None,
        key: str | None = None,
        effective_at: datetime | None = None,
        clock_at: datetime | None = None,
    ) -> ReportCapacityResult:
        self.clock.set(clock_at or when)
        return await self.reports.execute(
            ReportCapacityCommand(
                idempotency_key=key or self._key(),
                actor=REPORTER,
                service_id=service_id,
                value=value,
                source=ReportSource.LINK,
                effective_at=effective_at,
                flag=flag,
            )
        )

    async def phoned(self, value: int, when: datetime, *, service_id: str = "ucr-west") -> None:
        self.clock.set(when)
        await self.reports.execute(
            ReportCapacityCommand(
                idempotency_key=self._key(),
                actor=ADVISOR,
                service_id=service_id,
                value=value,
                source=ReportSource.ADVISOR_PHONED,
            )
        )

    async def confirm(self, when: datetime, *, service_id: str = "ucr-west") -> None:
        self.clock.set(when)
        await self.confirms.execute(
            ConfirmCapacityCommand(
                idempotency_key=self._key(),
                actor=REPORTER,
                service_id=service_id,
                source=ReportSource.LINK,
            )
        )


async def _open_flags(factory: UnitOfWorkFactory, service_id: str | None = None) -> list[ReportFlag]:
    async with factory() as uow:
        return await uow.flags.open_report_flags(service_id)


async def _flagged_events(factory: UnitOfWorkFactory) -> list[OutboxMessage]:
    async with factory() as uow:
        return [m for m in await uow.outbox.pending(limit=1000) if m.event_type == "ReportFlagged"]


def _reasons(flags: list[ReportFlag]) -> list[ReportFlagReason]:
    return [flag.reason for flag in flags]


# --- 1. a flag the caller names ------------------------------------------------------------------


async def test_a_flag_on_the_command_is_stored_open_on_its_report_and_announced(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.number(40, at(14, 0), flag=OUT_OF_RANGE)

    assert len(result.flag_ids) == 1
    [flag] = await _open_flags(uow_factory, "ucr-west")
    assert flag == ReportFlag(
        id=result.flag_ids[0],
        report_id=result.report_id,
        service_id="ucr-west",
        reason=OUT_OF_RANGE,
        status=REPORT_FLAG_OPEN,
        created_at=at(14, 0),
    )
    [event] = await _flagged_events(uow_factory)
    assert event.topic == "capacity.events"
    assert event.session_id == "ucr-west"
    assert event.payload == {
        "flag_id": flag.id,
        "service_id": "ucr-west",
        "report_id": result.report_id,
        "reason": "out-of-range-twice",
        "at": "2026-10-23T14:00:00Z",
    }
    assert await count_nodes(neo4j_driver, "Observation") == 1
    assert await count_nodes(neo4j_driver, "ReportFlag") == 1


async def test_a_report_that_breaks_no_rule_raises_no_flag(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.number(4, at(14, 0))

    assert result.flag_ids == ()
    assert await _open_flags(uow_factory) == []
    assert await _flagged_events(uow_factory) == []
    assert await count_nodes(neo4j_driver, "ReportFlag") == 0


async def test_the_audit_entry_names_the_flags_it_raised(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.number(40, at(14, 0), flag=OUT_OF_RANGE)

    async with uow_factory() as uow:
        [record] = await uow.audit.records()
    assert record.entry.entity_ids == (result.report_id, "ucr-west", *result.flag_ids)
    assert len(result.flag_ids) == 1


# --- 2 and 3. many changes -----------------------------------------------------------------------


async def test_ward_a_y_then_nine_then_two_raises_many_changes_on_the_third_only(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(WARD_A)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.number(4, at(13, 0), service_id="ward-a")

    await rig.confirm(at(14, 0), service_id="ward-a")
    assert await _open_flags(uow_factory) == []
    first = await rig.number(9, at(14, 2), service_id="ward-a")
    assert first.flag_ids == ()
    assert await _open_flags(uow_factory) == []

    third = await rig.number(2, at(14, 4), service_id="ward-a")

    [flag] = await _open_flags(uow_factory, "ward-a")
    assert flag.reason is MANY
    assert flag.report_id == third.report_id
    assert third.flag_ids == (flag.id,)
    assert len(await _flagged_events(uow_factory)) == 1


async def test_a_fourth_report_does_not_raise_a_second_many_changes_while_the_first_is_open(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(WARD_A)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.number(4, at(13, 0), service_id="ward-a")
    await rig.confirm(at(14, 0), service_id="ward-a")
    await rig.number(9, at(14, 2), service_id="ward-a")
    await rig.number(2, at(14, 4), service_id="ward-a")

    fourth = await rig.number(3, at(14, 5), service_id="ward-a")

    assert fourth.flag_ids == ()
    assert len(await _open_flags(uow_factory, "ward-a")) == 1
    assert len(await _flagged_events(uow_factory)) == 1
    assert await count_nodes(neo4j_driver, "Observation") == 5


async def test_once_the_flag_is_checked_the_next_breaking_report_raises_a_new_one(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """One OPEN flag per service and reason: a resolved flag no longer stops a new one."""
    await seed_service(WARD_A)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.number(4, at(13, 0), service_id="ward-a")
    await rig.confirm(at(14, 0), service_id="ward-a")
    await rig.number(9, at(14, 2), service_id="ward-a")
    await rig.number(2, at(14, 4), service_id="ward-a")
    [first] = await _open_flags(uow_factory, "ward-a")
    async with uow_factory() as uow:
        await uow.flags.save_report_flag(
            dataclasses.replace(
                first, status=REPORT_FLAG_CHECKED, resolved_at=at(14, 5), outcome="checked"
            )
        )
        await uow.commit()

    again = await rig.number(3, at(14, 6), service_id="ward-a")

    assert len(again.flag_ids) == 1
    [second] = await _open_flags(uow_factory, "ward-a")
    assert second.id == again.flag_ids[0] != first.id
    assert second.reason is MANY


async def test_confirmations_count_towards_many_changes_and_the_third_may_be_a_confirmation(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.number(5, at(14, 0))
    await rig.confirm(at(14, 1))
    assert await _open_flags(uow_factory) == []

    await rig.confirm(at(14, 2))

    [flag] = await _open_flags(uow_factory, "ucr-west")
    assert flag.reason is MANY
    async with uow_factory() as uow:
        confirmed = await uow.capacity.latest("ucr-west")
    assert confirmed is not None
    assert flag.report_id == confirmed.id
    assert confirmed.value == 5


async def test_reports_five_minutes_apart_do_not_raise_many_changes(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.number(4, at(14, 0))
    await rig.number(5, at(14, 6))
    await rig.number(6, at(14, 12))

    assert await _open_flags(uow_factory) == []


async def test_the_reports_of_another_service_do_not_count(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, WARD_A)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.number(4, at(14, 0), service_id="ucr-west")
    await rig.number(5, at(14, 1), service_id="ward-a")
    await rig.number(6, at(14, 2), service_id="ucr-west")
    await rig.number(7, at(14, 3), service_id="ward-a")

    assert await _open_flags(uow_factory) == []


async def test_a_flag_on_one_service_does_not_stop_the_same_reason_on_another(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, WARD_A)
    rig = Rig(uow_factory, neo4j_driver)
    west = await rig.number(40, at(14, 0), service_id="ucr-west", flag=OUT_OF_RANGE)

    ward = await rig.number(40, at(14, 1), service_id="ward-a", flag=OUT_OF_RANGE)

    assert len(west.flag_ids) == len(ward.flag_ids) == 1
    assert [f.service_id for f in await _open_flags(uow_factory)] == ["ucr-west", "ward-a"]
    assert [f.service_id for f in await _open_flags(uow_factory, "ward-a")] == ["ward-a"]


# --- 4. differs from phoned ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("phoned_at", "phoned", "text_at", "text", "expected"),
    [
        pytest.param(at(13, 30), 2, at(14, 0), 5, [PHONED], id="phoned 2 at 13:30, text 5"),
        pytest.param(at(13, 30), 2, at(14, 0), 2, [], id="phoned 2 at 13:30, text 2"),
        pytest.param(at(12, 30), 2, at(14, 0), 5, [], id="phoned at 12:30 is outside"),
        pytest.param(at(13, 0), 2, at(14, 0), 5, [PHONED], id="exactly 60 minutes is inside"),
        pytest.param(at(12, 59), 2, at(14, 0), 5, [], id="61 minutes is outside"),
    ],
)
async def test_a_figure_that_differs_from_a_phoned_one_in_the_last_hour_is_flagged(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
    phoned_at: datetime,
    phoned: int,
    text_at: datetime,
    text: int,
    expected: list[ReportFlagReason],
) -> None:
    await seed_service(UCR_WEST)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.phoned(phoned, phoned_at)

    result = await rig.number(text, text_at)

    assert _reasons(await _open_flags(uow_factory, "ucr-west")) == expected
    assert len(result.flag_ids) == len(expected)
    # The report is stored in every case (flags never block a report).
    assert await count_nodes(neo4j_driver, "Observation") == 2
    assert len(await _flagged_events(uow_factory)) == len(expected)


async def test_a_back_dated_report_is_judged_against_the_hour_before_its_own_time(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """The windows run from the report's effective time, not from the clock: a report sent at
    15:00 for 14:00 is compared with what was phoned at 13:30, which is 90 minutes before the clock
    and 30 minutes before the report."""
    await seed_service(UCR_WEST)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.phoned(2, at(13, 30))

    result = await rig.number(5, at(14, 0), effective_at=at(14, 0), clock_at=at(15, 0))

    [flag] = await _open_flags(uow_factory, "ucr-west")
    assert flag.reason is PHONED
    assert flag.report_id == result.report_id
    assert flag.created_at == at(15, 0)


async def test_an_advisor_phoned_report_is_not_flagged_against_an_earlier_one(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.phoned(2, at(13, 30))

    await rig.phoned(7, at(14, 0))

    assert await _open_flags(uow_factory) == []


# --- the caller's flag and the rules together ----------------------------------------------------


async def test_the_callers_flag_and_a_rule_flag_are_both_raised_rule_first(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.number(4, at(14, 0))
    await rig.number(5, at(14, 1))

    result = await rig.number(40, at(14, 2), flag=OUT_OF_RANGE)

    flags = await _open_flags(uow_factory, "ucr-west")
    assert _reasons(flags) == [MANY, OUT_OF_RANGE]
    assert result.flag_ids == tuple(flag.id for flag in flags)
    assert {flag.report_id for flag in flags} == {result.report_id}
    assert len(await _flagged_events(uow_factory)) == 2


async def test_a_caller_flag_that_a_rule_also_raises_is_raised_once(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.number(4, at(14, 0))
    await rig.number(5, at(14, 1))

    result = await rig.number(6, at(14, 2), flag=MANY)

    assert len(result.flag_ids) == 1
    assert _reasons(await _open_flags(uow_factory)) == [MANY]


async def test_a_caller_flag_with_the_same_reason_already_open_is_not_raised_again(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.number(40, at(14, 0), flag=OUT_OF_RANGE)

    second = await rig.number(40, at(14, 30), flag=OUT_OF_RANGE)

    assert second.flag_ids == ()
    assert len(await _open_flags(uow_factory)) == 1
    assert len(await _flagged_events(uow_factory)) == 1
    assert await count_nodes(neo4j_driver, "Observation") == 2


# --- atomicity and replay ------------------------------------------------------------------------


class _FailingFlags:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def add_report_flag(self, flag: ReportFlag) -> None:
        raise RuntimeError("flag write failed")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _FailingFlagsUnitOfWork:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def flags(self) -> _FailingFlags:
        return _FailingFlags(self._inner.flags)

    async def __aenter__(self) -> "_FailingFlagsUnitOfWork":
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._inner.__aexit__(*exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def test_when_the_flag_cannot_be_written_neither_the_report_nor_the_flag_is_stored(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    clock = FixedClock(at(14, 0))
    failing = ReportCapacity(
        lambda: _FailingFlagsUnitOfWork(uow_factory()),  # type: ignore[arg-type,return-value]
        clock,
        SequentialIds(),
        DriverIdempotencyStore(neo4j_driver),
    )
    command = ReportCapacityCommand(
        idempotency_key="key-fail",
        actor=REPORTER,
        service_id="ucr-west",
        value=40,
        source=ReportSource.LINK,
        flag=OUT_OF_RANGE,
    )

    with pytest.raises(RuntimeError, match="flag write failed"):
        await failing.execute(command)

    assert await count_nodes(neo4j_driver, "Observation") == 0
    assert await count_nodes(neo4j_driver, "ReportFlag") == 0
    assert await count_nodes(neo4j_driver, "OutboxMessage") == 0
    assert await count_nodes(neo4j_driver, "AuditEvent") == 0
    # Nothing was recorded for the key either, so the same command may be tried again.
    working = ReportCapacity(uow_factory, clock, SequentialIds(), DriverIdempotencyStore(neo4j_driver))
    retried = await working.execute(command)
    assert len(retried.flag_ids) == 1
    assert await count_nodes(neo4j_driver, "Observation") == 1


async def test_a_replayed_command_returns_the_same_flags_and_raises_no_new_one(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    rig = Rig(uow_factory, neo4j_driver)
    first = await rig.number(40, at(14, 0), flag=OUT_OF_RANGE, key="same")

    again = await rig.number(40, at(14, 0), flag=OUT_OF_RANGE, key="same")

    assert again == dataclasses.replace(first, replayed=True)
    assert len(again.flag_ids) == 1
    assert await count_nodes(neo4j_driver, "ReportFlag") == 1
    assert len(await _flagged_events(uow_factory)) == 1


# --- tenancy -------------------------------------------------------------------------------------


def test_the_command_carries_no_tenant_and_the_event_payload_names_none() -> None:
    """DEC-130: the tenant is bound at the edge, never taken from a command or sent in a payload.
    This task adds no Cypher statement: flags are written and read through the existing flag
    repository, whose statements are on the ratchet and run in the bound scope."""
    fields = {f.name for f in dataclasses.fields(ReportCapacityCommand)}
    assert not {name for name in fields if "tenant" in name or "scope" in name}
    assert {f.name for f in dataclasses.fields(ReportCapacityResult)} == {
        "report_id",
        "status",
        "status_changed",
        "next_due",
        "replayed",
        "flag_ids",
    }


async def test_flags_are_read_for_the_service_asked_for_only(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, WARD_A)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.number(40, at(14, 0), service_id="ucr-west", flag=OUT_OF_RANGE)

    assert await _open_flags(uow_factory, "ward-a") == []
    assert [f.service_id for f in await _open_flags(uow_factory, "ucr-west")] == ["ucr-west"]

