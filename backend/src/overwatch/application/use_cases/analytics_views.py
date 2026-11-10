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
from overwatch.application.area_placement import place_services, site_districts
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.geo import PostcodeLocator
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
from overwatch.domain.rules.areas import Area, AreaTable

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
    area: str | None = None
    """The id of the area the service is placed in, `network` for one that works across areas, None
    when it is not placed or there is no area table (DEC-1375)."""


@dataclass(frozen=True, slots=True)
class AnalyticsOverview:
    generated_at: datetime
    counts: dict[Status, int]
    out_of_hours: int
    services: tuple[AnalyticsService, ...]
    under_pressure: tuple[PressureItem, ...]
    underutilised: tuple[UnderutilisedItem, ...]
    areas: tuple[Area, ...] = ()
    """The named areas in display order, the network-wide one last; none when there is no table."""


def _service(
    entry: BoardEntry, districts: tuple[str, ...], area: str | None = None
) -> AnalyticsService:
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
        area=area,
    )


def build_overview(
    entries: tuple[BoardEntry, ...],
    districts: Mapping[str, tuple[str, ...]],
    generated_at: datetime,
    table: AreaTable | None = None,
    sites: Mapping[str, str] | None = None,
) -> AnalyticsOverview:
    """The overview of a board and the districts each service covers. Lists are by name, never
    ranked by status."""
    counts = {status: 0 for status in COUNTED}
    for entry in entries:
        if entry.status in counts:
            counts[entry.status] += 1
    placed = place_services(table, [entry.service_id for entry in entries], districts, sites or {})
    rows = sorted(
        (
            _service(entry, districts.get(entry.service_id, ()), placed.get(entry.service_id))
            for entry in entries
        ),
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
        areas=() if table is None else table.ordered(),
    )


class GetAnalyticsOverview:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        areas: AreaTable | None = None,
        postcodes: PostcodeLocator | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._areas = areas
        self._postcodes = postcodes

    async def execute(self, actor: Actor) -> AnalyticsOverview:
        check_analytics(actor)
        board = await QueryBoard(self._uow_factory, self._clock).execute(QueryBoardQuery(actor))
        ids = [entry.service_id for entry in board.entries]
        async with self._uow_factory() as uow:
            districts = await uow.positions.coverage_districts(ids)
            sites = await site_districts(uow, ids, districts, self._areas, self._postcodes)
        return build_overview(board.entries, districts, board.generated_at, self._areas, sites)
