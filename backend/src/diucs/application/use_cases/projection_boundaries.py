"""The projection heartbeat and the boundary projection (TEN-056, DEC-132 item 4, DEC-134 item 6,
audit F section 4.7, hazard H-N03).

The network stores the inputs of a status and computes the status when it is read (DEC-546), so a
network board turns Not updated by itself when a member stops reporting. What a projection cannot
do alone is keep the inputs themselves from going stale: a policy change, a lost message, a service
whose opening hours pass a boundary. For each tenant that shares capacity there is therefore one
chain of scheduled work (`WorkKind.PROJECTION_HEARTBEAT`, about the tenant, one job at a time):

1. the producer's backfill re-projects every admitted service (each capacity projection carries
   `valid_until`, the next instant its status could change, `projection_validity.py`; the version
   of a capacity projection is the instant it was read, so each run moves it forward, which is the
   heartbeat; directory and criteria are ordered by their own versions, so a repeat is a no-op);
2. the revoked-grant leak check (`ReconcileProjection`) runs for every network the tenant is an
   active member of, and for every one it left within a day (`AFTER_LEAVE`), so a leave whose end
   step was lost is healed;
3. due supersessions of grants are carried out (`grants.py`, when wired);
4. the next job is scheduled for the earlier of the next boundary of any status and the heartbeat
   interval, never sooner than a minute, in the same unit of work as the marker of this job.

The chain ends when the tenant has no approved grant in a network it belongs to and has not left a
network within a day. A grant that becomes effective starts it again (`ensure_projection_schedule`,
run by the governance consumer), and the work ids of the first job are derived from the tenant and
the minute, so two starters create one chain. The projection and the reconciliation run before the
marker is written (the producer and the reconciliation open their own units, which are never
nested in this one); a delivery that is repeated after a failure projects again, which is harmless
(the apply step is idempotent), and schedules the next job once. [ASSUMED] interval 5 minutes,
minimum gap 1 minute, 24 hours of reconciliation after a leave.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.tenancy import ScopeKind, TenantNotBound, current_scope, current_tenant
from diucs.application.use_cases.project_network import ProjectNetwork
from diucs.application.use_cases.projection_reconcile import ReconcileProjection
from diucs.application.work import SCHEDULED, WorkKind
from diucs.domain.errors import Conflict
from diucs.domain.model.network import GrantStatus, MembershipStatus

HEARTBEAT_INTERVAL: Final = timedelta(minutes=5)
MIN_GAP: Final = timedelta(minutes=1)
AFTER_LEAVE: Final = timedelta(hours=24)
CONSUMER: Final = "projection-heartbeat"


def heartbeat_work_id(tenant_id: str, due: datetime) -> str:
    """The id of the first job of a chain: the tenant and the minute it is due, so two starters
    write one job (the second is a Conflict)."""
    return f"projection-heartbeat:{tenant_id}:{due.astimezone(UTC).strftime('%Y%m%dT%H%MZ')}"


def next_run_due(now: datetime, boundary: datetime | None) -> datetime:
    """The earlier of the boundary and the interval, and never sooner than the minimum gap."""
    due = now + HEARTBEAT_INTERVAL
    if boundary is not None and boundary < due:
        due = boundary
    return max(due, now + MIN_GAP)


@dataclass(frozen=True, slots=True)
class RunProjectionHeartbeatCommand:
    work_id: str


@dataclass(frozen=True, slots=True)
class HeartbeatResult:
    requested: int
    networks_reconciled: int
    superseded: int
    next_due: datetime | None
    replayed: bool


class RunProjectionHeartbeat:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        registry: NetworkRegistry,
        producer: ProjectNetwork,
        reconcile: ReconcileProjection,
        supersede: Callable[[], Awaitable[int]] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock
        self._registry = registry
        self._producer = producer
        self._reconcile = reconcile
        self._supersede = supersede

    async def execute(self, command: RunProjectionHeartbeatCommand) -> HeartbeatResult:
        tenant = current_tenant()
        now = self._clock.now()
        memberships = await self._registry.memberships_of(tenant)
        grants = await self._registry.grants_of(tenant)
        active = {m.network_id for m in memberships if m.status is MembershipStatus.ACTIVE}
        recent = {
            m.network_id
            for m in memberships
            if m.status in (MembershipStatus.LEFT, MembershipStatus.REMOVED)
            and m.left_at is not None
            and m.left_at > now - AFTER_LEAVE
        }
        shares = any(
            grant.status is GrantStatus.APPROVED and grant.network_id in active for grant in grants
        )
        requested = 0
        boundary: datetime | None = None
        superseded = 0
        if shares:
            run = await self._producer.backfill()
            requested, boundary = run.requested, run.next_boundary
            if self._supersede is not None:
                superseded = await self._supersede()
        networks = sorted(active | recent)
        for network_id in networks:
            await self._reconcile.member(network_id, tenant)
        proceed = shares or bool(recent)
        async with self._uow_factory() as uow:
            if uow.unit_scope is None or uow.unit_scope.kind is not ScopeKind.TENANT:
                raise TenantNotBound
            if not await uow.processed.mark_if_new(command.work_id, CONSUMER):
                return HeartbeatResult(0, 0, 0, None, replayed=True)
            due = None
            if proceed:
                due = next_run_due(now, boundary)
                await schedule_work(
                    uow,
                    self._ids,
                    kind=WorkKind.PROJECTION_HEARTBEAT,
                    about_id=tenant,
                    due_at=due,
                    now=now,
                )
            await uow.commit()
        return HeartbeatResult(requested, len(networks), superseded, due, replayed=False)


class _FirstId:
    """Answers the derived work id first and a derived message id after it."""

    def __init__(self, value: str) -> None:
        self._value = value
        self._calls = 0

    def new_id(self) -> str:
        self._calls += 1
        return self._value if self._calls == 1 else f"{self._value}:message"


async def ensure_projection_schedule(
    uow_factory: UnitOfWorkFactory, ids: IdGenerator, clock: Clock
) -> bool:
    """Start the bound tenant's chain when none is scheduled: the first job a minute ahead. True
    when it wrote one. A second starter for the same minute is a Conflict, which means it exists.
    `ids` is accepted so that a caller can pass the container's generator; the first job's id is
    derived."""
    now = clock.now()
    scope = current_scope()
    if scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    due = now + MIN_GAP
    try:
        async with uow_factory() as uow:
            works = await uow.scheduled_work.for_about(scope.value, WorkKind.PROJECTION_HEARTBEAT)
            if any(work.status == SCHEDULED for work in works):
                return False
            await schedule_work(
                uow,
                _FirstId(heartbeat_work_id(scope.value, due)),
                kind=WorkKind.PROJECTION_HEARTBEAT,
                about_id=scope.value,
                due_at=due,
                now=now,
            )
            await uow.commit()
    except Conflict:
        return False
    return True
