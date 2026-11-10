"""What the Analytics User reads (DEC-1368): figures about the tenant's own services, nothing else.

- `GetAnalyticsOverview`: one row per service (status, category, the districts it covers, and its
  figure only when the figure is current), the five status counts, and the lead's Under pressure and
  Underutilised lists put in name order. It reads the board (`QueryBoard`) and the tenant's coverage
  areas through the unit of work, so a status here is the status everywhere else.

Rules: the Analytics User alone (the route and this check). A stale, late or unknown figure carries
no number and is never listed as spare capacity (DEC-1343). No total of places available is made.
Nothing about a case, a patient, a postcode, a phone number or an outcome is read or returned. The
read is the bound tenant's; it does not span tenants (DEC-528).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.lead_views import (
    PressureItem,
    UnderutilisedItem,
    figure_unusable,
    under_pressure,
    underutilised,
)
from overwatch.application.use_cases.query_board import BoardEntry, QueryBoard, QueryBoardQuery
from overwatch.domain.codes import Role, ServiceCategory, Status
from overwatch.domain.errors import NotAllowed

ANALYTICS_ROLES: Final = frozenset({Role.ANALYTICS_USER})
ANALYTICS_ONLY: Final = "only the Analytics User may read this"
COUNTED: Final = (
    Status.ACCEPTING,
    Status.LIMITED,
    Status.NOT_ACCEPTING,
    Status.OVER_CAPACITY,
    Status.NOT_UPDATED,
)


def check_analytics(actor: Actor) -> None:
    if actor.role not in ANALYTICS_ROLES:
        raise NotAllowed(ANALYTICS_ONLY)


@dataclass(frozen=True, slots=True)
class AnalyticsService:
    service_id: str
    name: str
    category: ServiceCategory
    status: Status
    districts: tuple[str, ...]
    figure_current: bool
    available: int | None
    over_by: int | None
    unit_label: str
    reported_at: datetime | None


@dataclass(frozen=True, slots=True)
class AnalyticsOverview:
    generated_at: datetime
    counts: dict[Status, int]
    out_of_hours: int
    services: tuple[AnalyticsService, ...]
    under_pressure: tuple[PressureItem, ...]
    underutilised: tuple[UnderutilisedItem, ...]


def _service(entry: BoardEntry, districts: tuple[str, ...]) -> AnalyticsService:
    current = not figure_unusable(entry)
    return AnalyticsService(
        service_id=entry.service_id,
        name=entry.name,
        category=entry.category,
        status=entry.status,
        districts=tuple(sorted(districts)),
        figure_current=current,
        available=entry.effective_available if current else None,
        over_by=entry.over_by if current else None,
        unit_label=entry.unit_label,
        reported_at=entry.reported_at,
    )


def build_overview(
    entries: tuple[BoardEntry, ...],
    districts: Mapping[str, tuple[str, ...]],
    generated_at: datetime,
) -> AnalyticsOverview:
    """The overview of a board and the districts each service covers. Lists are by name, never
    ranked by status."""
    counts = {status: 0 for status in COUNTED}
    for entry in entries:
        if entry.status in counts:
            counts[entry.status] += 1
    rows = sorted(
        (_service(entry, districts.get(entry.service_id, ())) for entry in entries),
        key=lambda row: (row.name, row.service_id),
    )
    return AnalyticsOverview(
        generated_at=generated_at,
        counts=counts,
        out_of_hours=sum(1 for entry in entries if entry.status is Status.OUT_OF_HOURS),
        services=tuple(rows),
        under_pressure=tuple(
            sorted(under_pressure(entries), key=lambda item: (item.name, item.service_id))
        ),
        underutilised=tuple(
            sorted(underutilised(entries), key=lambda item: (item.name, item.service_id))
        ),
    )


class GetAnalyticsOverview:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor) -> AnalyticsOverview:
        check_analytics(actor)
        board = await QueryBoard(self._uow_factory, self._clock).execute(QueryBoardQuery(actor))
        async with self._uow_factory() as uow:
            districts = await uow.positions.coverage_districts(
                [entry.service_id for entry in board.entries]
            )
        return build_overview(board.entries, districts, board.generated_at)
