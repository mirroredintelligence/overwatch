"""The daily tenant invariant job (TEN-031) on the real Neo4j: it checks, flags, schedules its own
next run for the same tenant, does nothing twice for one work id, and the start-up seeds it once.

The check itself is a stub here (it is proved on a real graph in
tests/integration/graph_store/test_tenant_invariants.py): what these tests show is the job's flow
through the unit of work and the scheduled-work seam. Sample values only.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.ports.outbound.invariants import (
    InvariantReport,
    UnstampedNodes,
)
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.tenant_invariants import (
    InvariantMonitor,
    RunInvariantCheck,
    RunInvariantCheckCommand,
    ensure_invariant_schedule,
)
from diucs.application.work import SCHEDULED, WorkKind
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

LONDON = ZoneInfo("Europe/London")
DIRTY = InvariantReport(unstamped=(UnstampedNodes(("Observation",), 3),))


def london(year: int, month: int, day: int, hour: int = 3, minute: int = 30) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=LONDON).astimezone(UTC)


class _Checker:
    def __init__(self, report: InvariantReport | None = None, fail: bool = False) -> None:
        self.report = InvariantReport() if report is None else report
        self.fail = fail
        self.calls = 0

    async def check(self) -> InvariantReport:
        self.calls += 1
        if self.fail:
            raise RuntimeError("no answer")
        return self.report


def _job(
    uow_factory: UnitOfWorkFactory, checker: _Checker, monitor: InvariantMonitor, at: datetime
) -> RunInvariantCheck:
    return RunInvariantCheck(uow_factory, SequentialIds("inv"), FixedClock(at), checker, monitor)


async def _scheduled(uow_factory: UnitOfWorkFactory, tenant: str) -> list:
    async with uow_factory() as uow:
        works = await uow.scheduled_work.for_about(tenant, WorkKind.INVARIANT_CHECK)
    return [w for w in works if w.status == SCHEDULED]


@pytest_asyncio.fixture(loop_scope="session")
async def head(clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str) -> None:
    await ensure_audit_heads(neo4j_driver, tenant_id)


async def test_a_clean_check_clears_the_flag_and_schedules_the_next_run_for_the_next_morning(
    uow_factory: UnitOfWorkFactory, tenant_id: str, head: None
) -> None:
    monitor = InvariantMonitor()
    monitor.record(DIRTY)
    checker = _Checker()
    result = await _job(uow_factory, checker, monitor, london(2026, 10, 23)).execute(
        RunInvariantCheckCommand(work_id="work-1")
    )

    assert result.ok is True
    assert monitor.raised is False
    assert checker.calls == 1
    (next_run,) = await _scheduled(uow_factory, tenant_id)
    assert next_run.due_at == datetime(2026, 10, 24, 2, 30, tzinfo=UTC)
    assert next_run.about_id == tenant_id


async def test_a_violation_raises_the_flag_and_the_job_still_schedules_its_next_run(
    uow_factory: UnitOfWorkFactory, tenant_id: str, head: None
) -> None:
    monitor = InvariantMonitor()
    result = await _job(uow_factory, _Checker(DIRTY), monitor, london(2026, 10, 23)).execute(
        RunInvariantCheckCommand(work_id="work-2")
    )

    assert result.ok is False
    assert monitor.raised is True
    assert monitor.report == DIRTY
    assert len(await _scheduled(uow_factory, tenant_id)) == 1


async def test_the_same_work_id_delivered_twice_checks_once_and_makes_one_next_run(
    uow_factory: UnitOfWorkFactory, tenant_id: str, head: None
) -> None:
    checker = _Checker()
    monitor = InvariantMonitor()
    await _job(uow_factory, checker, monitor, london(2026, 10, 23)).execute(
        RunInvariantCheckCommand(work_id="work-3")
    )
    again = await _job(uow_factory, checker, monitor, london(2026, 10, 23)).execute(
        RunInvariantCheckCommand(work_id="work-3")
    )

    assert again.replayed is True
    assert checker.calls == 1
    assert len(await _scheduled(uow_factory, tenant_id)) == 1


async def test_a_check_that_fails_leaves_no_mark_and_no_next_run_so_the_delivery_retries(
    uow_factory: UnitOfWorkFactory, tenant_id: str, head: None
) -> None:
    monitor = InvariantMonitor()
    with pytest.raises(RuntimeError, match="no answer"):
        await _job(uow_factory, _Checker(fail=True), monitor, london(2026, 10, 23)).execute(
            RunInvariantCheckCommand(work_id="work-4")
        )
    assert await _scheduled(uow_factory, tenant_id) == []

    retried = await _job(uow_factory, _Checker(), monitor, london(2026, 10, 23)).execute(
        RunInvariantCheckCommand(work_id="work-4")
    )
    assert retried.replayed is False
    assert len(await _scheduled(uow_factory, tenant_id)) == 1


async def test_the_daily_schedule_is_created_once_per_tenant(
    uow_factory: UnitOfWorkFactory, tenant_id: str, head: None
) -> None:
    clock = FixedClock(london(2026, 10, 23, 1, 0))
    ids = SequentialIds("start")
    first = await ensure_invariant_schedule(uow_factory, ids, clock)
    second = await ensure_invariant_schedule(uow_factory, ids, clock)

    assert (first, second) == (True, False)
    (only,) = await _scheduled(uow_factory, tenant_id)
    assert only.id == f"invariant-check:{tenant_id}:2026-10-23"
    assert only.due_at == datetime(2026, 10, 23, 2, 30, tzinfo=UTC)
