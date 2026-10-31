"""Outbound port: the daily telemetry aggregates (O08, docs/spec/fhir-data-model.md "Platform
nodes").

The daily job reads one day of raw telemetry through `TelemetryQuery.daily_aggregates` and
writes the rows here, replacing the day's rows in one unit of work, so a second run of the same
day leaves the same rows. The read side (`ReadInsights`) reads the rows back by day range.

No row holds a person, a session id, a field value, a page text or a query text. A group is
counted by its sessions so the read side can hide a group under the suppression floor
(domain/rules/telemetry_insights). `sessions` is an addition to the spec's field lists on the
three rows that need it: a rate over interactions alone can rest on one person (see the decision
for O08).
"""

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from diucs.domain.model.telemetry_aggregates import (
    DayAggregates,
    ElementUsageDailyRow,
    FrictionDailyRow,
    FunnelDailyRow,
    QueryStatDailyRow,
    RouteDailyRow,
)


class AggregateRepository(Protocol):
    async def replace_day(self, day: date, aggregates: DayAggregates) -> None:
        """Remove the bound tenant's rows of this day and write `aggregates` in their place.
        Every row of
        `aggregates` must carry `day`; a row of another day is refused by the caller.

        """
        ...

    async def funnel_rows(self, funnel: str, start: date, end: date) -> list[FunnelDailyRow]:
        """The funnel rows of the bound tenant between start and end (both included), in day
        order.

        """
        ...

    async def friction_rows(self, start: date, end: date) -> list[FrictionDailyRow]:
        """The friction rows between start and end (both included), in day order."""
        ...

    async def usage_rows(self, start: date, end: date) -> list[ElementUsageDailyRow]:
        """The element usage rows between start and end (both included), in day order."""
        ...

    async def route_rows(self, start: date, end: date) -> list[RouteDailyRow]:
        """The route rows between start and end (both included), in day order."""
        ...

    async def query_rows(self, start: date, end: date) -> list[QueryStatDailyRow]:
        """The query statistics between start and end (both included), in day order."""
        ...


def check_one_day(day: date, rows: Sequence[object]) -> None:
    """Refuse rows of another day (a programming error in the job, never a data error to repair)."""
    for row in rows:
        row_day = getattr(row, "day", None)
        if row_day != day:
            raise ValueError("an aggregate row belongs to another day than the job is run for")
