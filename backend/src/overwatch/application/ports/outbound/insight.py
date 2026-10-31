"""Outbound port: the browser-insight counters and the live pipeline read (W9F).

The ingest counts a batch of browser events into the daily counters of the bound tenant. A counter
is added to, never replaced; a session is told from a new one by a pseudonymous marker (a keyed
hash, domain/rules/browser_insight.marker_key), which this port stores for a day or two and never
shows. No row holds a person, a session id, a typed value or a page text.

The tenant is never an argument: every call works in the tenant bound to its unit of work
(DEC-130, DEC-132).
"""

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from diucs.domain.model.insight import (
    FrictionAdd,
    FunnelAdd,
    FunnelMark,
    MeasureAdd,
    MeasureRow,
    PipelineRow,
    ReleaseAdd,
    ReleaseRow,
    RouteAdd,
    UsageAdd,
)


class InsightRepository(Protocol):
    async def mark_seen(self, day: date, keys: Sequence[str]) -> set[str]:
        """Record these markers for the day; the ones not there before (a new session in the group).
        The keys must be distinct."""
        ...

    async def advance_funnels(
        self, day: date, marks: Sequence[FunnelMark]
    ) -> dict[str, tuple[int, int]]:
        """Move each marker to its furthest funnel step: (step it was at, -1 when new; step it is
        at now). The markers must be distinct."""
        ...

    async def purge_seen(self, before: date) -> int:
        """Remove the markers of days before `before`; how many went."""
        ...

    async def add_usage(self, day: date, rows: Sequence[UsageAdd]) -> None: ...

    async def add_friction(self, day: date, rows: Sequence[FrictionAdd]) -> None: ...

    async def add_routes(self, day: date, rows: Sequence[RouteAdd]) -> None: ...

    async def add_funnel(self, day: date, rows: Sequence[FunnelAdd]) -> None: ...

    async def add_measures(self, day: date, rows: Sequence[MeasureAdd]) -> None: ...

    async def add_releases(self, day: date, rows: Sequence[ReleaseAdd]) -> None: ...

    async def measure_rows(self, start: date, end: date) -> list[MeasureRow]:
        """The web-vital histograms between start and end (both included), in day order."""
        ...

    async def release_rows(self, start: date, end: date) -> list[ReleaseRow]:
        """The release counters between start and end (both included), in day order."""
        ...

    async def pipeline_rows(self) -> list[PipelineRow]:
        """The bound tenant's pending and dead outbox messages, by topic, read now."""
        ...
