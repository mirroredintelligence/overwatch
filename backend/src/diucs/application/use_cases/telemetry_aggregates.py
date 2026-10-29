"""The daily telemetry aggregates (O08): build one day, and read the insights back.

BuildDailyAggregates reads one day of telemetry for the bound tenant through TelemetryQuery and
replaces that day's rows in one unit of work, so a re-run of the day leaves the same rows.
ReadInsights reads the rows of a range and returns figures with the suppression floor applied
(domain/rules/telemetry_insights).

Tenancy (DEC-130, DEC-132): both use cases read the tenant from the unit of work and from the
TelemetryQuery's bound context, never from an argument. The insights are one tenant's own;
nothing spans two tenants.

An AuditEntry is not written by the build: it is derived data rebuilt from telemetry, and no
person acts in it. The run is visible from the rows' own day and count (decision for O08).
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from diucs.application.ports.outbound.aggregates import check_one_day
from diucs.application.ports.outbound.telemetry_query import TelemetryQuery
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.telemetry_insights import (
    FUNNELS,
    FrictionFigure,
    FunnelFigure,
    QueryFigure,
    RouteFigure,
    friction_figures,
    funnel_figures,
    query_figures,
    rate_window_start,
    route_figures,
)

USE_CASE_BUILD: Final = "BuildDailyAggregates"


@dataclass(frozen=True, slots=True)
class BuildDailyAggregatesResult:
    day: date
    rows: int


def _calendar_day(value: object) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValidationFailed("day", "must be a calendar day")
    return value


def _ordered(start: date, end: date) -> None:
    if start > end:
        raise ValidationFailed("end", "must not be before the start")


class BuildDailyAggregates:
    def __init__(self, uow_factory: UnitOfWorkFactory, telemetry: TelemetryQuery) -> None:
        self._uow_factory = uow_factory
        self._telemetry = telemetry

    async def execute(self, day: date) -> BuildDailyAggregatesResult:
        """Replace the bound tenant's rows of `day` with that day's summary. Reads telemetry before
        the
        unit of work opens, so no read runs inside it.

        """
        day = _calendar_day(day)
        aggregates = await self._telemetry.daily_aggregates(day)
        rows = [
            *aggregates.funnel,
            *aggregates.friction,
            *aggregates.usage,
            *aggregates.routes,
            *aggregates.queries,
        ]
        check_one_day(day, rows)
        async with self._uow_factory() as uow:
            await uow.aggregates.replace_day(day, aggregates)
            await uow.commit()
        return BuildDailyAggregatesResult(day=day, rows=len(rows))


class ReadInsights:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def funnel(self, funnel: str, start: date, end: date) -> list[FunnelFigure]:
        """The steps of one funnel between start and end, with the suppression floor applied."""
        if funnel not in FUNNELS:
            raise ValidationFailed("funnel", "is not one of the funnels")
        start, end = _calendar_day(start), _calendar_day(end)
        _ordered(start, end)
        async with self._uow_factory() as uow:
            rows = await uow.aggregates.funnel_rows(funnel, start, end)
        return funnel_figures(rows)

    async def friction(self, end: date) -> list[FrictionFigure]:
        """Friction per element, role and device over the seven days that end on `end`, with the
        review flag for each element over the line.

        """
        end = _calendar_day(end)
        start = rate_window_start(end)
        async with self._uow_factory() as uow:
            friction = await uow.aggregates.friction_rows(start, end)
            usage = await uow.aggregates.usage_rows(start, end)
        return friction_figures(friction, usage)

    async def routes(self, start: date, end: date) -> list[RouteFigure]:
        start, end = _calendar_day(start), _calendar_day(end)
        _ordered(start, end)
        async with self._uow_factory() as uow:
            rows = await uow.aggregates.route_rows(start, end)
        return route_figures(rows)

    async def queries(self, start: date, end: date) -> list[QueryFigure]:
        start, end = _calendar_day(start), _calendar_day(end)
        _ordered(start, end)
        async with self._uow_factory() as uow:
            rows = await uow.aggregates.query_rows(start, end)
        return query_figures(rows)
