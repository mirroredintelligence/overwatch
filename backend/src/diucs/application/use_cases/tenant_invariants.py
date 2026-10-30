"""The daily tenant invariant job (TEN-031): count the nodes that carry no tenant and the
relationships that join two scopes, raise a flag on any, and schedule the next run.

It rides the scheduled-work seam as the daily criteria review does (U31): one ScheduledWork row of
kind `invariant-check` for each tenant, run at 03:30 London (INVARIANT_RUN_AT, [ASSUMED]: a quiet
hour that is not the criteria review's), which schedules its own next run through `schedule_work`
at 03:30 on the next London date, so the clock change is handled by london_to_utc and never by
adding 24 hours. The check itself is platform-wide (two global statements, DEC-163) and is made
under whichever tenant's work carries it; running it once for each tenant is the price of using the
seam, and a check is one read of the graph.

A violation does not stop the job: it raises the process's flag (`InvariantMonitor`, which logs the
counts and label names once on each change) and the job goes on checking every day, so a repair
clears the flag on the next run. The process that starts refuses on a violation instead
(Container.startup).

Idempotency: the run marks its work id as processed in the same unit of work as its writes, and the
mark comes before the check, so a second delivery of the same work id checks nothing and schedules
no second next run. A check that fails (Neo4j did not answer) rolls the unit back, leaving no mark
and no next run, so the delivery is retried. The daily schedule is seeded at start-up with a
deterministic work id per tenant and London date, so two processes starting at once cannot create
two daily chains (the second write is a Conflict).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Final

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.invariants import InvariantReport, TenantInvariants
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.application.work import SCHEDULED, WorkKind
from diucs.domain.errors import Conflict
from diucs.domain.rules.london_time import london_to_utc, to_london

logger = logging.getLogger(__name__)

INVARIANT_RUN_AT: Final = time(3, 30)
"""The daily run, London local time (TEN-031, [ASSUMED])."""
CONSUMER: Final = "tenant-invariants"


def next_run_due(now: datetime) -> datetime:
    """The instant of the run after `now`: 03:30 London on the next London date, as UTC."""
    tomorrow = to_london(now).date() + timedelta(days=1)
    return london_to_utc(tomorrow, INVARIANT_RUN_AT)


def first_run_due(now: datetime) -> datetime:
    """The first run: today at 03:30 London when that is still ahead, otherwise tomorrow's."""
    today = to_london(now).date()
    todays = london_to_utc(today, INVARIANT_RUN_AT)
    return todays if todays > now.astimezone(UTC) else next_run_due(now)


def invariant_work_id(tenant_id: str, due: datetime) -> str:
    return f"invariant-check:{tenant_id}:{to_london(due).date().isoformat()}"


def _tenant_scope(scope: ScopeId | None) -> ScopeId:
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


class InvariantMonitor:
    """What this process last learned from the check: the report, and the flag a violation raises.
    The one place the counts and label names are logged, once on each change from clean to
    violated, and again when the violation changes."""

    def __init__(self) -> None:
        self._report: InvariantReport | None = None

    @property
    def report(self) -> InvariantReport | None:
        return self._report

    @property
    def raised(self) -> bool:
        return self._report is not None and not self._report.ok

    def record(self, report: InvariantReport) -> None:
        changed = report != self._report
        self._report = report
        if not report.ok and changed:
            logger.error("tenant invariant violated: %s", report.summary())
        elif report.ok and changed:
            logger.info("tenant invariants hold")


@dataclass(frozen=True, slots=True)
class RunInvariantCheckCommand:
    work_id: str


@dataclass(frozen=True, slots=True)
class InvariantCheckResult:
    ok: bool
    replayed: bool


class _FixedId:
    """Answers the given value first (the scheduled work's id) and a derived one after it (the
    message's id). Used only for the start-up schedule, whose work id is derived from the tenant
    and the date, so that a second writer is refused."""

    def __init__(self, value: str) -> None:
        self._value = value
        self._calls = 0

    def new_id(self) -> str:
        self._calls += 1
        return self._value if self._calls == 1 else f"{self._value}:message"


class RunInvariantCheck:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        invariants: TenantInvariants,
        monitor: InvariantMonitor,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock
        self._invariants = invariants
        self._monitor = monitor

    async def execute(self, command: RunInvariantCheckCommand) -> InvariantCheckResult:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            if not await uow.processed.mark_if_new(command.work_id, CONSUMER):
                return InvariantCheckResult(ok=not self._monitor.raised, replayed=True)
            report = await self._invariants.check()
            self._monitor.record(report)
            await schedule_work(
                uow,
                self._ids,
                kind=WorkKind.INVARIANT_CHECK,
                about_id=scope.value,
                due_at=next_run_due(now),
                now=now,
            )
            await uow.commit()
        return InvariantCheckResult(ok=report.ok, replayed=False)


async def ensure_invariant_schedule(
    uow_factory: UnitOfWorkFactory, ids: IdGenerator, clock: Clock
) -> bool:
    """Schedule the first daily run for the bound tenant when none is scheduled. Returns True when
    it wrote one. The work id is derived from the tenant and the London date of the run, so a
    second writer for the same run is a Conflict, which means it is already scheduled."""
    now = clock.now()
    scope = current_scope()
    if scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    due = first_run_due(now)
    try:
        async with uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            works = await uow.scheduled_work.for_about(scope.value, WorkKind.INVARIANT_CHECK)
            if any(work.status == SCHEDULED for work in works):
                return False
            await schedule_work(
                uow,
                _FixedId(invariant_work_id(scope.value, due)),
                kind=WorkKind.INVARIANT_CHECK,
                about_id=scope.value,
                due_at=due,
                now=now,
            )
            await uow.commit()
    except Conflict:
        return False
    return True
