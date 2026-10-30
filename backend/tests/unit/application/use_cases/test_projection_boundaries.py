"""The projection heartbeat (TEN-056, DEC-132 item 4, DEC-134 item 6, audit F section 4.7).

One chain of scheduled work for each tenant that shares capacity with a network: each run
re-projects every admitted service (the producer's backfill, which also sets `valid_until`),
reconciles the networks the tenant belongs to or has just left, and schedules the next run at the
earlier of the next boundary of any status and the heartbeat interval (never sooner than a minute).
The chain ends when the tenant has nothing left to share and nothing recently left to reconcile,
and a grant that becomes effective starts it again (`ensure_projection_schedule`). The run is
repeatable: the work's marker is written with the next run in one unit of work, so a delivery that
is repeated schedules no second chain.
"""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.project_network import ProjectionRun
from diucs.application.use_cases.projection_boundaries import (
    AFTER_LEAVE,
    HEARTBEAT_INTERVAL,
    MIN_GAP,
    RunProjectionHeartbeat,
    RunProjectionHeartbeatCommand,
    ensure_projection_schedule,
)
from diucs.application.use_cases.projection_reconcile import ReconcileResult
from diucs.application.work import SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.model.network import (
    GrantScope,
    GrantStatus,
    MembershipEndReason,
    MembershipStatus,
)
from tests.support.network_admin_fakes import Ids, MemoryRegistry, UnitFactories, UnitWorld
from tests.support.network_samples import (
    MEMBER_B,
    NETWORK_ID,
    NOW,
    make_grant,
    make_member,
    make_network,
    make_owner_membership,
    rid,
)

AT = NOW + timedelta(days=1)


class _Producer:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.run = ProjectionRun(3, 0, None)
        self.error: Exception | None = None
        self.calls = 0

    async def backfill(self, kind: Any = None) -> ProjectionRun:
        self.calls += 1
        self.log.append("producer:backfill")
        if self.error is not None:
            raise self.error
        return self.run


class _Reconcile:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.asked: list[tuple[str, str]] = []

    async def member(self, network_id: str, member: str) -> ReconcileResult:
        self.log.append("reconcile")
        self.asked.append((network_id, member))
        return ReconcileResult(0, 0, 0)


class _Rig:
    def __init__(self, supersede: Any = None) -> None:
        self.log: list[str] = []
        self.world = UnitWorld(self.log)
        self.registry = MemoryRegistry(self.log)
        self.registry.seed(make_network(), members=[make_owner_membership(), make_member(MEMBER_B)])
        self.grant = make_grant(id=rid("grant-hb"))
        self.registry.grant_rows[self.grant.id] = self.grant
        self.producer = _Producer(self.log)
        self.reconcile = _Reconcile(self.log)
        self.clock = FixedClock(AT)
        factories = UnitFactories(self.world)
        self.factories = factories
        self.beat = RunProjectionHeartbeat(
            factories.tenant,  # type: ignore[arg-type]
            Ids("hb"),
            self.clock,
            self.registry,  # type: ignore[arg-type]
            self.producer,  # type: ignore[arg-type]
            self.reconcile,  # type: ignore[arg-type]
            supersede,
        )

    async def run(self, work_id: str = "work-1") -> Any:
        return await self.beat.execute(RunProjectionHeartbeatCommand(work_id))

    def next_works(self) -> list[ScheduledWork]:
        return [w for w in self.world.scheduled if w.kind is WorkKind.PROJECTION_HEARTBEAT]


@pytest.fixture
def rig() -> _Rig:
    return _Rig()


@pytest.fixture(autouse=True)
def _tenant() -> Any:
    with bind_tenant(MEMBER_B):
        yield


async def test_a_run_projects_reconciles_and_schedules_the_next_one(rig: _Rig) -> None:
    result = await rig.run()
    assert result.requested == 3 and not result.replayed
    assert rig.producer.calls == 1
    assert rig.reconcile.asked == [(NETWORK_ID, MEMBER_B)]
    [work] = rig.next_works()
    assert (work.about_id, work.status) == (MEMBER_B, SCHEDULED)
    assert work.due_at == AT + HEARTBEAT_INTERVAL
    assert result.next_due == work.due_at


async def test_the_work_is_projected_and_reconciled_before_the_marker_and_the_next_run(
    rig: _Rig,
) -> None:
    await rig.run()
    assert rig.log.index("producer:backfill") < rig.log.index("tenant:open")
    assert rig.log.index("reconcile") < rig.log.index("tenant:open")
    assert rig.log.index("tenant:schedule:projection-heartbeat") < rig.log.index("tenant:commit")


async def test_a_boundary_before_the_interval_brings_the_next_run_forward(rig: _Rig) -> None:
    rig.producer.run = ProjectionRun(1, 0, AT + timedelta(minutes=2))
    await rig.run()
    [work] = rig.next_works()
    assert work.due_at == AT + timedelta(minutes=2)


async def test_a_boundary_that_is_too_close_waits_for_the_minimum_gap(rig: _Rig) -> None:
    rig.producer.run = ProjectionRun(1, 0, AT + timedelta(seconds=5))
    await rig.run()
    [work] = rig.next_works()
    assert work.due_at == AT + MIN_GAP


async def test_a_boundary_after_the_interval_does_not_postpone_the_heartbeat(rig: _Rig) -> None:
    rig.producer.run = ProjectionRun(1, 0, AT + timedelta(hours=3))
    await rig.run()
    [work] = rig.next_works()
    assert work.due_at == AT + HEARTBEAT_INTERVAL


async def test_a_repeated_delivery_schedules_no_second_run(rig: _Rig) -> None:
    await rig.run("work-1")
    again = await rig.run("work-1")
    assert again.replayed and again.next_due is None
    assert len(rig.next_works()) == 1


async def test_a_failing_producer_marks_nothing_and_schedules_nothing(rig: _Rig) -> None:
    rig.producer.error = ConnectionError("down")
    with pytest.raises(ConnectionError):
        await rig.run()
    assert rig.next_works() == [] and rig.world.marked == set()


async def test_a_failed_commit_leaves_no_next_run_to_double(rig: _Rig) -> None:
    rig.world.fail_commit = "tenant"
    with pytest.raises(ConnectionError):
        await rig.run()
    assert rig.next_works() == []
    rig.world.fail_commit = None
    await rig.run()
    assert len(rig.next_works()) == 1


# when the chain ends


async def test_a_tenant_with_no_approved_grant_and_no_recent_leave_ends_the_chain(
    rig: _Rig,
) -> None:
    ended = replace(
        rig.grant, status=GrantStatus.ENDED, ended_at=NOW, ended_by_account_ref="acct-member-b-01"
    )
    rig.registry.grant_rows[ended.id] = ended
    result = await rig.run()
    assert result.next_due is None and rig.next_works() == []
    assert rig.producer.calls == 0  # nothing to project


async def test_a_member_that_left_is_reconciled_until_a_day_has_passed(rig: _Rig) -> None:
    key = rid(f"mem-{MEMBER_B}")
    row = rig.registry.members[key]
    left_at = AT - timedelta(hours=1)
    rig.registry.members[key] = replace(
        row, status=MembershipStatus.LEFT, left_at=left_at, end_reason=MembershipEndReason.LEFT
    )
    rig.registry.grant_rows[rig.grant.id] = replace(
        rig.grant, status=GrantStatus.LAPSED, ended_at=left_at
    )
    first = await rig.run()
    assert rig.reconcile.asked == [(NETWORK_ID, MEMBER_B)]
    assert first.next_due is not None and rig.producer.calls == 0
    rig.clock.set(left_at + AFTER_LEAVE + timedelta(minutes=1))
    last = await rig.run("work-2")
    assert last.next_due is None


async def test_the_supersession_of_due_grants_is_run_with_the_heartbeat() -> None:
    calls: list[str] = []

    async def supersede() -> int:
        calls.append("supersede")
        return 2

    rig = _Rig(supersede)
    result = await rig.run()
    assert calls == ["supersede"] and result.superseded == 2


# the first run


async def test_the_first_run_is_scheduled_a_minute_ahead_once(rig: _Rig) -> None:
    assert await ensure_projection_schedule(rig.factories.tenant, Ids("ens"), rig.clock) is True  # type: ignore[arg-type]
    [work] = rig.next_works()
    assert work.due_at == AT + MIN_GAP and work.about_id == MEMBER_B
    assert await ensure_projection_schedule(rig.factories.tenant, Ids("ens"), rig.clock) is False  # type: ignore[arg-type]
    assert len(rig.next_works()) == 1


def test_the_grant_scopes_are_the_three_kinds() -> None:
    assert set(GrantScope) == {GrantScope.CAPACITY, GrantScope.DIRECTORY, GrantScope.CRITERIA}
