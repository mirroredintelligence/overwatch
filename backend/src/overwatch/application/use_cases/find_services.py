"""Advisor v2: find a service, and the capacity overview (DEC-1366).

Browse only. Nothing here opens, reads or writes a case: the postcode is turned into its district,
used for
this one read and dropped, and the age band, needs and urgency are never stored. The one record is
the audit
entry of what was shown (service ids, status, figure, data age: no postcode, district, age band or
need),
as the v1 options write.

A service is found by the same hard criteria as the v1 options (check_hard_criteria, DEC-035): no
eligibility
rule of its own. Unlike v1 its status does not exclude it: a service that is not accepting or not
updated is
shown as it is, and the list is never ranked by status. A late or old figure is never the current
capacity
(`figure_unavailable`) and the last figure is kept to show small as "Last reported" (DEC-1343). A
suspended
service, and one with no current criteria, is never found (fails closed).

Roles: the advisor and Advisor v2 (DEC-1362); every other role is refused as NotAllowed.
"""

import asyncio
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Final

from overwatch.application.actor import Actor
from overwatch.application.area_placement import place_services, site_districts
from overwatch.application.ports.outbound.audit import AuditEntry
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.geo import (
    LatLon,
    Located,
    PostcodeLocator,
    TravelRange,
    TravelTime,
)
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.filter_options import (
    Coverage,
    coverage_of,
    criteria_warnings,
    data_age_warnings,
    fits_for,
    status_warnings,
)
from overwatch.application.use_cases.lead_views import (
    PressureItem,
    UnderutilisedItem,
    figure_unusable,
    under_pressure,
    underutilised,
)
from overwatch.application.use_cases.open_case import district_for
from overwatch.application.use_cases.query_board import BoardEntry, QueryBoard, QueryBoardQuery
from overwatch.domain.codes import (
    AgeBand,
    Cadence,
    NeedCategory,
    Role,
    ServiceCategory,
    Status,
    Urgency,
)
from overwatch.domain.errors import NotAllowed, NotFound
from overwatch.domain.model.criteria import ServiceCriteria
from overwatch.domain.model.flags import SERVICE_FLAG_SUSPENDED
from overwatch.domain.rules.areas import Area, AreaTable
from overwatch.domain.rules.criteria_filter import FilterResult, check_hard_criteria
from overwatch.domain.rules.freshness import STALE_WARNING_AFTER
from overwatch.domain.rules.london_time import to_london

FIND_SERVICES: Final = "FindServices"
READ_ACTION: Final = "R"
FIND_ROLES: Final = (Role.ADVISOR, Role.ADVISOR_V2)
FOUND_ORDER_NOTE: Final = "Travel time, then name. Never ordered by status."
COUNTED_STATUSES: Final = (
    Status.ACCEPTING,
    Status.LIMITED,
    Status.OVER_CAPACITY,
    Status.NOT_ACCEPTING,
    Status.NOT_UPDATED,
)
OVERVIEW_STATUSES: Final = (*COUNTED_STATUSES, Status.OUT_OF_HOURS)
"""The statuses the Advisor v2 overview counts: the five, and Out of hours, so a service outside its
hours is counted and listed under a state of its own, and none is in a total yet in no list."""
ATTENTION_SHOWN: Final = 3
"""The short Needs attention list shows this many of each list; the rest are counted."""


def check_find_role(actor: Actor) -> None:
    if actor.role not in FIND_ROLES:
        raise NotAllowed("only an advisor may find a service")


@dataclass(frozen=True, slots=True)
class ServiceCoverage:
    districts: tuple[str, ...] = ()
    """The postcode districts a visiting service covers, in name order; none for a fixed site."""
    circle: Coverage | None = None
    """The v1 circle of the districts the locator can place (coverage_of); None when none."""


@dataclass(frozen=True, slots=True)
class FoundService:
    service_id: str
    name: str
    category: ServiceCategory
    status: Status
    effective_available: int | None
    over_by: int | None
    unit_label: str
    data_age: timedelta | None
    reported_at: datetime | None
    next_due_at: datetime | None
    cadence: Cadence | None
    overdue: bool
    stale_warning: bool
    figure_unavailable: bool
    last_figure: int | None
    criteria_version: int
    fits: tuple[str, ...]
    warnings: tuple[str, ...]
    phone: str | None = None
    travel: TravelRange | None = None
    position: LatLon | None = None
    """The site position of the service; None when it has none (DEC-1379)."""
    coverage: ServiceCoverage = field(default_factory=ServiceCoverage)
    """The area the service covers, for the map (DEC-1379)."""


@dataclass(frozen=True, slots=True)
class NotSuitableService:
    """A board service that was not found, and why (DEC-1379). The reasons are the hard-criteria
    text, or one of the two fail-closed reasons."""

    service_id: str
    name: str
    category: ServiceCategory
    status: Status
    reasons: tuple[str, ...]
    position: LatLon | None = None


def _figure_unavailable(entry: BoardEntry, data_age: timedelta | None) -> bool:
    if figure_unusable(entry):
        return True
    return data_age is None or data_age > STALE_WARNING_AFTER


def _found_service(
    entry: BoardEntry,
    current: ServiceCriteria,
    result: FilterResult,
    *,
    needs: tuple[NeedCategory, ...],
    now: datetime,
    today: date,
    phone: str | None,
) -> FoundService:
    """One service as the find list and the single check show it: the same figure rules, fit lines
    and warnings, so the two answers cannot disagree. Pure."""
    data_age = None if entry.reported_at is None else now - entry.reported_at
    return FoundService(
        service_id=entry.service_id,
        name=entry.name,
        category=entry.category,
        status=entry.status,
        effective_available=entry.effective_available,
        over_by=entry.over_by,
        unit_label=entry.unit_label,
        data_age=data_age,
        reported_at=entry.reported_at,
        next_due_at=entry.next_due_at,
        cadence=entry.cadence,
        overdue=entry.overdue,
        stale_warning=entry.stale_warning,
        figure_unavailable=_figure_unavailable(entry, data_age),
        last_figure=(
            entry.effective_available if entry.effective_available is not None else entry.used
        ),
        criteria_version=current.version,
        fits=fits_for(current, needs) if result.passes else (),
        warnings=(
            result.warnings
            + status_warnings(entry.status)
            + data_age_warnings(data_age)
            + criteria_warnings(current, today)
        ),
        phone=phone,
    )


def split_services(
    entries: tuple[BoardEntry, ...],
    criteria: Mapping[str, ServiceCriteria],
    *,
    suspended: Collection[str],
    age_band: AgeBand,
    district: str,
    needs: tuple[NeedCategory, ...],
    now: datetime,
    today: date,
    phones: Mapping[str, str] | None = None,
) -> tuple[tuple[FoundService, ...], tuple[NotSuitableService, ...]]:
    """Every board service is either found or not suitable, by the one rule: suspended, or no
    current criteria, or failing the hard criteria is not suitable (fails closed). Found keeps the
    board order; not suitable is by name then id. Pure."""
    found: list[FoundService] = []
    refused: list[NotSuitableService] = []
    for entry in entries:
        current = criteria.get(entry.service_id)
        reasons: tuple[str, ...] = ()
        result: FilterResult | None = None
        if entry.service_id in suspended:
            reasons = (REASON_SUSPENDED,)
        elif current is None:
            reasons = (REASON_NO_CRITERIA,)
        else:
            result = check_hard_criteria(current, age_band, district, needs)
            if not result.passes:
                reasons = result.reasons
        if current is not None and result is not None and result.passes:
            found.append(
                _found_service(
                    entry,
                    current,
                    result,
                    needs=needs,
                    now=now,
                    today=today,
                    phone=None if phones is None else phones.get(entry.service_id),
                )
            )
            continue
        refused.append(
            NotSuitableService(
                service_id=entry.service_id,
                name=entry.name,
                category=entry.category,
                status=entry.status,
                reasons=reasons,
            )
        )
    refused.sort(key=lambda item: (item.name, item.service_id))
    return tuple(found), tuple(refused)


def match_services(
    entries: tuple[BoardEntry, ...],
    criteria: Mapping[str, ServiceCriteria],
    *,
    suspended: Collection[str],
    age_band: AgeBand,
    district: str,
    needs: tuple[NeedCategory, ...],
    now: datetime,
    today: date,
    phones: Mapping[str, str] | None = None,
) -> tuple[FoundService, ...]:
    """The services whose current criteria take this age band, district and needs. Pure."""
    return split_services(
        entries,
        criteria,
        suspended=suspended,
        age_band=age_band,
        district=district,
        needs=needs,
        now=now,
        today=today,
        phones=phones,
    )[0]


def group_totals(entries: tuple[BoardEntry, ...]) -> dict[ServiceCategory, int]:
    """How many services each group has in all, so a card can say "3 of 5 services". Counts only: no
    patient value and no ordering."""
    totals: dict[ServiceCategory, int] = {}
    for entry in entries:
        totals[entry.category] = totals.get(entry.category, 0) + 1
    return totals


def order_key(item: FoundService) -> tuple[int, int, str, str]:
    """Travel low end first, no travel last, then name, then id. Status plays no part."""
    if item.travel is None:
        return (1, 0, item.name, item.service_id)
    return (0, item.travel.low_minutes, item.name, item.service_id)


@dataclass(frozen=True, slots=True)
class FindServicesCommand:
    actor: Actor
    postcode: str
    age_band: AgeBand
    needs: tuple[NeedCategory, ...]
    urgency: Urgency
    """Accepted and shown back; it is not a criterion (as in v1, where it is kept on the case)."""


@dataclass(frozen=True, slots=True)
class FindServicesResult:
    services: tuple[FoundService, ...]
    generated_at: datetime
    not_found: bool = False
    """The locator does not know the district: no travel is shown and the order is by name."""
    group_totals: Mapping[ServiceCategory, int] = field(default_factory=dict)
    """Every service of each group, found or not."""
    not_suitable: tuple[NotSuitableService, ...] = ()
    """Every other service on the board, with the reasons, by name then id (DEC-1379)."""


class FindServices:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        query_board: QueryBoard,
        postcodes: PostcodeLocator,
        travel_time: TravelTime,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._query_board = query_board
        self._postcodes = postcodes
        self._travel_time = travel_time

    async def execute(self, command: FindServicesCommand) -> FindServicesResult:
        check_find_role(command.actor)
        district = district_for(command.postcode)
        board = await self._query_board.execute(QueryBoardQuery(command.actor))
        now = self._clock.now()
        service_ids = [entry.service_id for entry in board.entries]
        async with self._uow_factory() as uow:
            criteria = await uow.criteria.current_for_services(service_ids)
            suspended = await uow.flags.services_with_flag(SERVICE_FLAG_SUSPENDED)
            positions = await uow.positions.get_many(service_ids)
            covered = await uow.positions.coverage_districts(service_ids)
            phones = await uow.services.work_phones(service_ids)
        patient = self._postcodes.locate(district)
        matched, refused = split_services(
            board.entries,
            criteria,
            suspended=suspended,
            age_band=command.age_band,
            district=district,
            needs=command.needs,
            now=now,
            today=to_london(now).date(),
            phones=phones,
        )
        ranges = await asyncio.gather(
            *(self._travel_range(patient, positions.get(item.service_id)) for item in matched)
        )
        ordered = tuple(
            sorted(
                (
                    _with_travel(
                        item, travel, positions, covered, self._postcodes.district_centroid
                    )
                    for item, travel in zip(matched, ranges, strict=True)
                ),
                key=order_key,
            )
        )
        async with self._uow_factory() as audit_uow:
            await audit_uow.audit.append(
                AuditEntry(
                    action=READ_ACTION,
                    use_case=FIND_SERVICES,
                    actor=command.actor,
                    entity_ids=tuple(item.service_id for item in ordered),
                    snapshot={
                        "services": [
                            {
                                "id": item.service_id,
                                "status": item.status.value,
                                "figure_unavailable": item.figure_unavailable,
                                "criteria_version": item.criteria_version,
                                "order": position,
                            }
                            for position, item in enumerate(ordered, 1)
                        ]
                    },
                    at=now,
                )
            )
            await audit_uow.commit()
        return FindServicesResult(
            services=ordered,
            generated_at=now,
            not_found=patient is None,
            group_totals=group_totals(board.entries),
            not_suitable=tuple(
                replace(item, position=positions.get(item.service_id)) for item in refused
            ),
        )

    async def _travel_range(
        self, patient: Located | None, site: LatLon | None
    ) -> TravelRange | None:
        if patient is None or site is None:
            return None
        return await self._travel_time.estimate(patient.lat_lon, site)


def _with_travel(
    item: FoundService,
    travel: TravelRange | None,
    positions: Mapping[str, LatLon],
    covered: Mapping[str, tuple[str, ...]],
    centre_of: Callable[[str], LatLon | None],
) -> FoundService:
    districts = tuple(sorted(set(covered.get(item.service_id, ()))))
    return replace(
        item,
        travel=travel,
        position=positions.get(item.service_id),
        coverage=ServiceCoverage(
            districts=districts,
            circle=None if item.service_id in positions else coverage_of(districts, centre_of),
        ),
    )


CHECK_SERVICE_FIT: Final = "CheckServiceFit"
NO_SUCH_SERVICE: Final = "no service with this id"
REASON_SUSPENDED: Final = "Not currently taking referrals"
REASON_NO_CRITERIA: Final = "No current criteria"


@dataclass(frozen=True, slots=True)
class CheckServiceFitCommand:
    actor: Actor
    service_id: str
    postcode: str
    age_band: AgeBand
    needs: tuple[NeedCategory, ...]
    urgency: Urgency
    """Accepted and dropped: it is not a criterion."""


@dataclass(frozen=True, slots=True)
class ServiceFitResult:
    service_id: str
    fits: bool
    reasons: tuple[str, ...]
    fits_needs: tuple[str, ...]
    warnings: tuple[str, ...]
    phone: str | None
    status: Status
    figure_unavailable: bool


class CheckServiceFit:
    """Does this one service take this patient? The find rule for one service (DEC-1377): the same
    hard criteria, fit lines and warnings as FindServices. Fails closed: a suspended service, and
    one with no current criteria, never fits. Nothing about the patient is stored or audited."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, clock: Clock, query_board: QueryBoard
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._query_board = query_board

    async def execute(self, command: CheckServiceFitCommand) -> ServiceFitResult:
        check_find_role(command.actor)
        district = district_for(command.postcode)
        board = await self._query_board.execute(QueryBoardQuery(command.actor))
        entry = next((e for e in board.entries if e.service_id == command.service_id), None)
        if entry is None:
            raise NotFound(NO_SUCH_SERVICE)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            criteria = await uow.criteria.current_for_services([command.service_id])
            suspended = await uow.flags.services_with_flag(SERVICE_FLAG_SUSPENDED)
            phones = await uow.services.work_phones([command.service_id])
        current = criteria.get(command.service_id)
        result = _fit_of(
            entry,
            current,
            command.service_id in suspended,
            command=command,
            district=district,
            now=now,
            phone=phones.get(command.service_id),
        )
        async with self._uow_factory() as audit_uow:
            await audit_uow.audit.append(
                AuditEntry(
                    action=READ_ACTION,
                    use_case=CHECK_SERVICE_FIT,
                    actor=command.actor,
                    entity_ids=(command.service_id,),
                    snapshot={
                        "service_id": command.service_id,
                        "fits": result.fits,
                        "criteria_version": None if current is None else current.version,
                    },
                    at=now,
                )
            )
            await audit_uow.commit()
        return result


def _fit_of(
    entry: BoardEntry,
    current: ServiceCriteria | None,
    is_suspended: bool,
    *,
    command: CheckServiceFitCommand,
    district: str,
    now: datetime,
    phone: str | None,
) -> ServiceFitResult:
    data_age = None if entry.reported_at is None else now - entry.reported_at
    if current is None or is_suspended:
        return ServiceFitResult(
            service_id=entry.service_id,
            fits=False,
            reasons=(REASON_SUSPENDED if is_suspended else REASON_NO_CRITERIA,),
            fits_needs=(),
            warnings=status_warnings(entry.status) + data_age_warnings(data_age),
            phone=phone,
            status=entry.status,
            figure_unavailable=_figure_unavailable(entry, data_age),
        )
    result = check_hard_criteria(current, command.age_band, district, command.needs)
    shown = _found_service(
        entry,
        current,
        result,
        needs=command.needs,
        now=now,
        today=to_london(now).date(),
        phone=phone,
    )
    return ServiceFitResult(
        service_id=shown.service_id,
        fits=result.passes,
        reasons=result.reasons,
        fits_needs=shown.fits,
        warnings=shown.warnings,
        phone=shown.phone,
        status=shown.status,
        figure_unavailable=shown.figure_unavailable,
    )


@dataclass(frozen=True, slots=True)
class CapacityRow:
    service_id: str
    name: str
    category: ServiceCategory
    status: Status
    effective_available: int | None
    over_by: int | None
    unit_label: str
    reported_at: datetime | None
    figure_unavailable: bool
    last_figure: int | None
    next_due_at: datetime | None = None
    """When the next report is due; when a service is out of hours, when it reopens (DEC-1381)."""
    districts: tuple[str, ...] = ()
    """The postcode districts the service covers; none when none is recorded."""
    area: str | None = None
    """The id of the area the service is placed in, `network` for one that works across areas, None
    when it is not placed or there is no area table (DEC-1375)."""


@dataclass(frozen=True, slots=True)
class CapacityOverview:
    counts: dict[Status, int]
    under_pressure: tuple[PressureItem, ...]
    underutilised: tuple[UnderutilisedItem, ...]
    rows: tuple[CapacityRow, ...]
    generated_at: datetime
    areas: tuple[Area, ...] = ()
    """The named areas in display order, the network-wide one last; none when there is no table."""


def capacity_overview(
    entries: tuple[BoardEntry, ...],
    generated_at: datetime | None = None,
    districts: Mapping[str, tuple[str, ...]] | None = None,
    table: AreaTable | None = None,
    sites: Mapping[str, str] | None = None,
) -> CapacityOverview:
    """The five counts, the two attention lists (the shift lead's own rules, lead_views) and one
    row per
    service by name, never by status. A figure that is late or old is marked unavailable here, on
    the back end."""
    counts = {status: 0 for status in OVERVIEW_STATUSES}
    for entry in entries:
        if entry.status in counts:
            counts[entry.status] += 1
    placed = place_services(
        table, [entry.service_id for entry in entries], districts or {}, sites or {}
    )
    rows = tuple(
        sorted(
            (
                CapacityRow(
                    service_id=entry.service_id,
                    name=entry.name,
                    category=entry.category,
                    status=entry.status,
                    effective_available=entry.effective_available,
                    over_by=entry.over_by,
                    unit_label=entry.unit_label,
                    reported_at=entry.reported_at,
                    figure_unavailable=figure_unusable(entry),
                    next_due_at=entry.next_due_at,
                    districts=tuple(sorted((districts or {}).get(entry.service_id, ()))),
                    area=placed.get(entry.service_id),
                    last_figure=(
                        entry.effective_available
                        if entry.effective_available is not None
                        else entry.used
                    ),
                )
                for entry in entries
            ),
            key=lambda row: (row.name, row.service_id),
        )
    )
    return CapacityOverview(
        counts=counts,
        under_pressure=under_pressure(entries),
        underutilised=underutilised(entries),
        rows=rows,
        generated_at=generated_at or datetime.min,
        areas=() if table is None else table.ordered(),
    )


class ReadCapacityOverview:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        query_board: QueryBoard,
        areas: AreaTable | None = None,
        postcodes: PostcodeLocator | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._query_board = query_board
        self._areas = areas
        self._postcodes = postcodes

    async def execute(self, actor: Actor) -> CapacityOverview:
        check_find_role(actor)
        board = await self._query_board.execute(QueryBoardQuery(actor))
        ids = [entry.service_id for entry in board.entries]
        async with self._uow_factory() as uow:
            districts = await uow.positions.coverage_districts(ids)
            sites = await site_districts(uow, ids, districts, self._areas, self._postcodes)
        return capacity_overview(board.entries, self._clock.now(), districts, self._areas, sites)
