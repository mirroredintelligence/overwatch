"""QueryBoard: the read model behind the wall board and the exec view (U08).

Contract: docs/spec/contracts.md, "QueryBoard result". Read-only: the unit of work is opened, read
and left without a commit, so nothing is written, audited or put on the outbox.

Rules: domain-rules 1.2 to 1.7 through compute_status, next_due and system_pressure. Entries are
ordered by ServiceCategory enum order, then name (ASSUMED, the prompt). Services are read in bulk:
one list of active services, one flag query, one latest-report query and one open-booking query for
all services. confirmed_since is per service, because the port has no batch form (DEC-085).
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Role, ServiceCategory, Status
from diucs.domain.errors import NotAllowed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED
from diucs.domain.model.service import ServiceProfile
from diucs.domain.rules.pressure import Pressure, all_limited_or_worse, system_pressure
from diucs.domain.rules.schedule import next_due
from diucs.domain.rules.status import compute_status

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
        now = self._clock.now()

        async with self._uow_factory() as uow:
            profiles = await uow.services.list_active()
            service_ids = [profile.id for profile in profiles]
            suspended = await uow.flags.services_with_flag(SERVICE_FLAG_SUSPENDED)
            reports = await uow.capacity.latest_for_services(service_ids)
            open_bookings = await uow.bookings.open_for_services(service_ids)
            confirmed: dict[str, list[datetime]] = {}
            for service_id, report in reports.items():
                confirmed[service_id] = await uow.bookings.confirmed_since(
                    service_id, report.effective_at
                )

        entries = [
            _entry(
                profile,
                reports.get(profile.id),
                confirmed.get(profile.id, []),
                len(open_bookings.get(profile.id, [])),
                profile.id in suspended,
                now,
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


def _entry(
    profile: ServiceProfile,
    report: CapacityReport | None,
    confirmed_at: list[datetime],
    pending: int,
    suspended: bool,
    now: datetime,
) -> BoardEntry:
    if suspended:
        profile = replace(profile, suspended=True)
    state = compute_status(profile, report, confirmed_at, now)
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
    )
