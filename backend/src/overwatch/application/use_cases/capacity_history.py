"""ReadCapacityHistory: the figures a service reported over the last day, for the day chart
(DEC-1343).

Each point is what the service could take at the time it reported, or how far over it was; never a
used count that could be read as free places (DEC-391, H-190). A service that counts occupied
patients is shown as the places left of its established capacity. The chart breaks where the
capacity was unknown: the caller is told how long a figure counts (the tenant's stale limit), so a
report followed by a long silence is drawn only as far as that limit, and nothing is drawn past it
until the next report.

Read-only, for the advisor, the clinical advisor, the shift lead and the readers of the service
detail page (Advisor v2, the Analytics User, DEC-1367), in the bound tenant. A service
of another tenant, or none, is NotFound.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from overwatch.application.actor import Actor, require_actor_in_bound_tenant
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.service_detail import READERS as DETAIL_READERS
from overwatch.domain.codes import Role, Status
from overwatch.domain.errors import NotAllowed, NotFound
from overwatch.domain.model.tenant_policy import DEFAULT_POLICY
from overwatch.domain.rules.london_time import LONDON
from overwatch.domain.rules.status import compute_status

READERS: Final = frozenset({Role.ADVISOR, Role.CLINICAL, Role.LEAD}) | DETAIL_READERS
"""Also the readers of the service detail page, whose day chart this is (DEC-1367)."""
DEFAULT_HOURS: Final = 24
MAX_HOURS: Final = 72


@dataclass(frozen=True, slots=True)
class HistoryPoint:
    at: datetime
    available: int | None
    over_by: int | None
    status: Status


@dataclass(frozen=True, slots=True)
class CapacityHistory:
    unit_label: str
    established: int
    since: datetime
    until: datetime
    stale_after: timedelta
    points: tuple[HistoryPoint, ...]


class ReadCapacityHistory:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self, actor: Actor, service_id: str, hours: int = DEFAULT_HOURS
    ) -> CapacityHistory:
        if actor.role not in READERS:
            raise NotAllowed("this role cannot read a service's history")
        require_actor_in_bound_tenant(actor)
        now = self._clock.now()
        since = now - timedelta(hours=min(max(hours, 1), MAX_HOURS))
        async with self._uow_factory() as uow:
            profile = await uow.services.get(service_id)
            if profile is None:
                raise NotFound("no service with this id")
            reports = await uow.capacity.reports_since(service_id, since)
        points: list[HistoryPoint] = []
        for report in sorted(reports, key=lambda item: item.effective_at):
            state = compute_status(profile, report, [], report.effective_at, DEFAULT_POLICY, LONDON)
            available = state.effective_available
            if available is None and state.used is not None:
                available = max(0, profile.established_capacity - state.used)
            points.append(HistoryPoint(report.effective_at, available, state.over_by, state.status))
        return CapacityHistory(
            unit_label=profile.unit_label,
            established=profile.established_capacity,
            since=since,
            until=now,
            stale_after=DEFAULT_POLICY.stale_warning_after,
            points=tuple(points),
        )
