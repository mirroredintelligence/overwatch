"""QueryBoard: the read model behind the wall board and the exec view (U08).

Contract: docs/spec/contracts.md, "QueryBoard result". Read-only: the unit of work is opened, read
and left without a commit, so nothing is written, audited or put on the outbox.

Rules: domain-rules 1.2 to 1.7 through compute_status, next_due and system_pressure. Entries are
ordered by ServiceCategory enum order, then name (ASSUMED, the prompt). Services are read in bulk:
one list of active services, one flag query, one latest-report query, one open-booking query and
one confirmation query for all services (DEC-088 supersedes DEC-085 item 1).
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Final

from overwatch.application.actor import Actor, require_actor_in_bound_tenant
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from overwatch.domain.codes import Cadence, Role, ServiceCategory, Status
from overwatch.domain.errors import NotAllowed
from overwatch.domain.model.capacity import CapacityReport
from overwatch.domain.model.flags import SERVICE_FLAG_SUSPENDED
from overwatch.domain.model.service import ServiceProfile
from overwatch.domain.rules.pressure import Pressure, all_limited_or_worse, system_pressure
from overwatch.domain.rules.schedule import next_due
from overwatch.domain.rules.status import compute_status

_CATEGORY_ORDER: Final[dict[ServiceCategory, int]] = {
    category: position for position, category in enumerate(ServiceCategory)
}


@dataclass(frozen=True, slots=True)
class QueryBoardQuery:
    actor: Actor


@dataclass(frozen=True, slots=True)
class BoardEntry:
    service_id: str
    name: str
    category: ServiceCategory
    status: Status
    effective_available: int | None
    over_by: int | None
    used: int | None
    established: int
    pending: int
    unit_label: str
    comment: str
    reported_at: datetime | None
    next_due_at: datetime | None
    was_due_at: datetime | None
    cadence: Cadence | None = None
    """How often the service promised to report (DEC-1343)."""
    overdue: bool = False
    """The service's own report is past due, judged against its cadence (DEC-1343)."""
    stale_warning: bool = False
    """The figure is older than the tenant's stale limit (DEC-1343)."""


@dataclass(frozen=True, slots=True)
class Board:
    entries: tuple[BoardEntry, ...]
    pressure: Pressure
    all_limited_or_worse: bool
    generated_at: datetime


class QueryBoard:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, query: QueryBoardQuery) -> Board:
        if query.actor.role is Role.ANONYMOUS_LINK:
            raise NotAllowed("the anonymous link cannot read the board")
        # The board is the bound tenant's (TEN-039): an actor of another tenant, a network scope
        # and no scope are refused before a unit of work opens.
        require_actor_in_bound_tenant(query.actor)
        now = self._clock.now()

        async with self._uow_factory() as uow:
            profiles = await uow.services.list_active()
            service_ids = [profile.id for profile in profiles]
            suspended = await uow.flags.services_with_flag(SERVICE_FLAG_SUSPENDED)
            reports = await uow.capacity.latest_for_services(service_ids)
            open_bookings = await uow.bookings.open_for_services(service_ids)
            gaps = await _staffing_gaps(uow, service_ids, now)
            confirmed: dict[str, list[datetime]] = {}
            if reports:
                # One read for every service with a report. The earliest report time is the
                # lower bound; availability keeps only the confirmations at or after each
                # service's own report (domain-rules 1.6).
                since = min(report.effective_at for report in reports.values())
                confirmed = await uow.bookings.confirmed_since_for_services(list(reports), since)

        entries = [
            _entry(
                profile,
                reports.get(profile.id),
                confirmed.get(profile.id, []),
                len(open_bookings.get(profile.id, [])),
                profile.id in suspended,
                now,
                (gaps[profile.id],) if profile.id in gaps else None,
            )
            for profile in profiles
        ]
        entries.sort(
            key=lambda entry: (_CATEGORY_ORDER[entry.category], entry.name, entry.service_id)
        )
        statuses = [entry.status for entry in entries]
        return Board(
            entries=tuple(entries),
            pressure=system_pressure(statuses),
            all_limited_or_worse=all_limited_or_worse(statuses),
            generated_at=now,
        )


STAFFING_GRACE: Final = timedelta(minutes=15)
"""How long after the last duty manager's shift ended a rostered service is still shown as it was,
before the board says nobody is on and the figure is stale (DEC-1341 item 6)."""
_STAFFED_STATUSES: Final = frozenset(
    {Status.ACCEPTING, Status.LIMITED, Status.NOT_ACCEPTING, Status.OVER_CAPACITY}
)


async def _staffing_gaps(
    uow: UnitOfWork, service_ids: list[str], now: datetime
) -> dict[str, datetime | None]:
    """The rostered services with nobody on shift past the grace, each with when the last shift
    ended (None when nobody was ever on). A service with no roster is not read here, and a service
    with anyone reporting for it (an always-on reporter, or a roster duty manager on shift) is
    staffed."""
    gaps: dict[str, datetime | None] = {}
    for service_id in service_ids:
        roster = await uow.people.roster_for_service(service_id)
        if not roster or await uow.people.reporter_roles_for_service(service_id, now):
            continue
        ended = [
            role.period_end
            for role in roster
            if role.active and role.period_end is not None and role.period_end <= now
        ]
        last_end = max(ended) if ended else None
        if last_end is None or now >= last_end + STAFFING_GRACE:
            gaps[service_id] = last_end
    return gaps


def _entry(
    profile: ServiceProfile,
    report: CapacityReport | None,
    confirmed_at: list[datetime],
    pending: int,
    suspended: bool,
    now: datetime,
    staffing_gap: tuple[datetime | None] | None = None,
) -> BoardEntry:
    if suspended:
        profile = replace(profile, suspended=True)
    state = compute_status(profile, report, confirmed_at, now)
    if staffing_gap is not None and state.status in _STAFFED_STATUSES:
        # Nobody is on shift to keep the figure true, so it is stale whatever its age (DEC-1341).
        # The last figure stays in `used` for the chase card; the board shows it as not updated.
        (gap_start,) = staffing_gap
        return BoardEntry(
            service_id=profile.id,
            name=profile.name,
            category=profile.category,
            status=Status.NOT_UPDATED,
            effective_available=None,
            over_by=None,
            used=state.used,
            established=profile.established_capacity,
            pending=pending,
            unit_label=profile.unit_label,
            comment=profile.comment,
            reported_at=None if report is None else report.effective_at,
            next_due_at=next_due(profile, now),
            was_due_at=now if gap_start is None else gap_start,
            cadence=profile.cadence,
            overdue=True,
            stale_warning=True,
        )
    return BoardEntry(
        service_id=profile.id,
        name=profile.name,
        category=profile.category,
        status=state.status,
        effective_available=state.effective_available,
        over_by=state.over_by,
        used=state.used,
        established=profile.established_capacity,
        pending=pending,
        unit_label=profile.unit_label,
        comment=profile.comment,
        reported_at=None if report is None else report.effective_at,
        next_due_at=next_due(profile, now),
        was_due_at=state.freshness.was_due,
        cadence=profile.cadence,
        overdue=state.freshness.overdue,
        stale_warning=state.freshness.stale_warning,
    )
