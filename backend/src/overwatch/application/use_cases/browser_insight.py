"""The browser's ui.* events counted into daily aggregates, and the insight tabs read back (W9F).

RecordBrowserEvents reads a batch of events against the schema (domain/rules/browser_insight),
drops what breaks it, and adds the rest to the day's counters of the bound tenant in one unit of
work. No event is kept. A session is told from a new one by a keyed marker, so the graph holds no
session id (see the rules module). The role counted is the caller's, from the verified token.

ReadInsightTab builds the five tabs of the support console's insight page from the stored rows
(domain/rules/insight_views), for the support role only. The pipeline of the release tab is the
tenant's own outbox, read now.

Tenancy (DEC-130, DEC-132): both use cases work in the tenant bound to the unit of work; nothing
here takes a tenant from an argument. An insight is one tenant's own and nothing spans two.
"""

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, timedelta
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.insight import InsightRepository
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import current_tenant
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.model.insight import (
    FrictionAdd,
    FunnelAdd,
    FunnelMark,
    MeasureAdd,
    ReleaseAdd,
    RouteAdd,
    UsageAdd,
)
from diucs.domain.model.telemetry_aggregates import FunnelDailyRow
from diucs.domain.rules.browser_insight import (
    BROWSER_FUNNELS,
    DEVICES,
    MARKER_KEEP_DAYS,
    MARKER_SECRET,
    MAX_BATCH_EVENTS,
    BatchTally,
    UiEvent,
    fold,
    marker_key,
    parse_event,
)
from diucs.domain.rules.insight_views import (
    FrictionTable,
    FunnelView,
    PathsView,
    PerformanceView,
    PipelineView,
    ReleaseCompareView,
    friction_table,
    funnel_views,
    paths_view,
    performance_view,
    pipeline_views,
    range_window,
    release_view,
)

USE_CASE_RECORD: Final = "RecordBrowserEvents"
USE_CASE_READ: Final = "ReadInsightTab"


@dataclass(frozen=True, slots=True)
class RecordedBatch:
    accepted: int
    dropped: int


@dataclass(frozen=True, slots=True)
class ReleasesView:
    compare: ReleaseCompareView | None
    pipeline: tuple[PipelineView, ...]


def _events_of(events: Sequence[Mapping[str, object]]) -> list[UiEvent]:
    parsed: list[UiEvent] = []
    for item in events:
        name = item.get("name")
        attributes = item.get("attributes")
        if isinstance(name, str) and isinstance(attributes, Mapping):
            event = parse_event(name, attributes)
            if event is not None:
                parsed.append(event)
    return parsed


class RecordBrowserEvents:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock, secrets: SecretStore) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._secrets = secrets

    async def execute(self, actor: Actor, events: Sequence[Mapping[str, object]]) -> RecordedBatch:
        """Count the batch. An event that breaks the schema is dropped and counted as dropped; a
        batch over the ceiling is refused whole. Nothing is written for a batch with no event
        that passes."""
        if len(events) > MAX_BATCH_EVENTS:
            raise ValidationFailed("events", f"at most {MAX_BATCH_EVENTS} in a batch")
        parsed = _events_of(events)
        dropped = len(events) - len(parsed)
        if not parsed:
            return RecordedBatch(0, dropped)
        tenant = current_tenant()
        secret = self._secrets.get(MARKER_SECRET)
        today = self._clock.now().astimezone(UTC).date()
        batch = fold(actor.role.value, parsed)

        def marker(family: str, dims: Sequence[str], session: str) -> str:
            return marker_key(secret, tenant, today, family, dims, session)

        async with self._uow_factory() as uow:
            repo = uow.insight
            keys = _marker_keys(batch, marker)
            fresh = await repo.mark_seen(today, sorted(set(keys.all)))
            await repo.add_usage(today, _usage(batch, keys.usage, fresh))
            await repo.add_friction(today, _friction(batch, keys.friction, fresh))
            await repo.add_routes(today, _routes(batch, keys.routes, fresh))
            await repo.add_measures(today, _measures(batch, keys.measures, fresh))
            await repo.add_releases(today, _releases(batch, keys.releases, fresh))
            await repo.add_funnel(today, await _funnel(batch, today, repo, marker))
            await repo.purge_seen(today - timedelta(days=MARKER_KEEP_DAYS))
            await uow.commit()
        return RecordedBatch(len(parsed), dropped)


@dataclass(frozen=True, slots=True)
class _Keys:
    usage: tuple[str, ...]
    friction: tuple[str, ...]
    routes: tuple[str, ...]
    measures: tuple[str, ...]
    releases: tuple[str, ...]

    @property
    def all(self) -> tuple[str, ...]:
        return (*self.usage, *self.friction, *self.routes, *self.measures, *self.releases)


type Marker = Callable[[str, Sequence[str], str], str]


def _marker_keys(batch: BatchTally, marker: Marker) -> _Keys:
    return _Keys(
        usage=tuple(
            marker("usage", (r.element_id, r.role, r.device), r.session_id) for r in batch.usage
        ),
        friction=tuple(
            marker("friction", (r.element_id, r.kind, r.route, r.role, r.device), r.session_id)
            for r in batch.friction
        ),
        routes=tuple(
            marker("route", (r.route, r.role, r.device), r.session_id) for r in batch.routes
        ),
        measures=tuple(
            marker("measure", (r.measure, r.route, r.device, r.release), r.session_id)
            for r in batch.measures
        ),
        releases=tuple(marker("release", (r.release,), r.session_id) for r in batch.releases),
    )


def _new(key: str, fresh: set[str]) -> int:
    return 1 if key in fresh else 0


def _usage(batch: BatchTally, keys: Sequence[str], fresh: set[str]) -> list[UsageAdd]:
    sums: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    for row, key in zip(batch.usage, keys, strict=True):
        total = sums[(row.element_id, row.role, row.device)]
        total[0] += row.count
        total[1] += _new(key, fresh)
    return [UsageAdd(*dims, *counts) for dims, counts in sorted(sums.items())]


def _friction(batch: BatchTally, keys: Sequence[str], fresh: set[str]) -> list[FrictionAdd]:
    sums: dict[tuple[str, str, str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    for row, key in zip(batch.friction, keys, strict=True):
        total = sums[(row.element_id, row.kind, row.route, row.role, row.device)]
        total[0] += row.count
        total[1] += _new(key, fresh)
    return [FrictionAdd(*dims, *counts) for dims, counts in sorted(sums.items())]


def _routes(batch: BatchTally, keys: Sequence[str], fresh: set[str]) -> list[RouteAdd]:
    sums: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    for row, key in zip(batch.routes, keys, strict=True):
        total = sums[(row.route, row.role, row.device)]
        total[0] += row.errors
        total[1] += _new(key, fresh)
    return [RouteAdd(*dims, *counts) for dims, counts in sorted(sums.items())]


def _measures(batch: BatchTally, keys: Sequence[str], fresh: set[str]) -> list[MeasureAdd]:
    sums: dict[tuple[str, str, str, str], tuple[list[int], list[int]]] = {}
    for row, key in zip(batch.measures, keys, strict=True):
        buckets, counts = sums.setdefault(
            (row.measure, row.route, row.device, row.release), ([0] * len(row.buckets), [0, 0])
        )
        for index, count in enumerate(row.buckets):
            buckets[index] += count
        counts[0] += row.samples
        counts[1] += _new(key, fresh)
    return [
        MeasureAdd(*dims, tuple(buckets), counts[0], counts[1])
        for dims, (buckets, counts) in sorted(sums.items())
    ]


def _releases(batch: BatchTally, keys: Sequence[str], fresh: set[str]) -> list[ReleaseAdd]:
    sums: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    for row, key in zip(batch.releases, keys, strict=True):
        total = sums[row.release]
        total[0] += row.interactions
        total[1] += row.friction
        total[2] += row.errors
        total[3] += row.views
        total[4] += _new(key, fresh)
    return [ReleaseAdd(release, *counts) for release, counts in sorted(sums.items())]


async def _funnel(
    batch: BatchTally, today: date, repo: InsightRepository, marker: Marker
) -> list[FunnelAdd]:
    """Each session's funnel steps newly reached today: from the step it was at to the step it is
    at now. A session already at that step adds nothing, however often it sees the screen."""
    furthest: dict[tuple[str, str], tuple[int, str, str, str]] = {}
    for row in batch.funnels:
        group = (row.funnel, row.session_id)
        held = furthest.get(group)
        if held is None or row.top > held[0]:
            furthest[group] = (row.top, row.role, row.channel, row.device)
    marks: dict[str, tuple[str, int, str, str, str]] = {}
    for (funnel, session), (top, role, channel, device) in sorted(furthest.items()):
        marks[marker("funnel", (funnel,), session)] = (funnel, top, role, channel, device)
    moved = await repo.advance_funnels(
        today, [FunnelMark(key, value[1]) for key, value in sorted(marks.items())]
    )
    added: dict[tuple[str, str, str, str, str], int] = defaultdict(int)
    for mark_key, (funnel, _top, role, channel, device) in marks.items():
        before, after = moved[mark_key]
        steps = BROWSER_FUNNELS[funnel]
        for index in range(before + 1, after + 1):
            added[(funnel, steps[index].step, role, channel, device)] += 1
    return [FunnelAdd(*dims, count) for dims, count in sorted(added.items())]


class ReadInsightTab:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    def _window(self, actor: Actor, range_name: str, device: str | None) -> tuple[date, date]:
        if actor.role is not Role.SUPPORT:
            raise NotAllowed("role")
        if device is not None and device not in DEVICES:
            raise ValidationFailed("device", "must be phone, tablet or desktop")
        return range_window(range_name, self._clock.now().astimezone(UTC).date())

    async def funnels(self, actor: Actor, range_name: str, device: str | None) -> list[FunnelView]:
        start, end = self._window(actor, range_name, device)
        rows: dict[str, list[FunnelDailyRow]] = {}
        async with self._uow_factory() as uow:
            for funnel in BROWSER_FUNNELS:
                found = await uow.aggregates.funnel_rows(funnel, start, end)
                rows[funnel] = [r for r in found if device is None or r.device == device]
        return funnel_views(rows)

    async def paths(self, actor: Actor, range_name: str, device: str | None) -> PathsView:
        start, end = self._window(actor, range_name, device)
        async with self._uow_factory() as uow:
            routes = await uow.aggregates.route_rows(start, end)
            friction = await uow.aggregates.friction_rows(start, end)
        return paths_view(
            [r for r in routes if device is None or r.device == device],
            [r for r in friction if device is None or r.device == device],
        )

    async def friction(self, actor: Actor, range_name: str, device: str | None) -> FrictionTable:
        start, end = self._window(actor, range_name, device)
        async with self._uow_factory() as uow:
            friction = await uow.aggregates.friction_rows(start, end)
            usage = await uow.aggregates.usage_rows(start, end)
        return friction_table(
            [r for r in friction if device is None or r.device == device],
            [r for r in usage if device is None or r.device == device],
        )

    async def performance(
        self, actor: Actor, range_name: str, device: str | None
    ) -> PerformanceView:
        start, end = self._window(actor, range_name, device)
        async with self._uow_factory() as uow:
            measures = await uow.insight.measure_rows(start, end)
            queries = await uow.aggregates.query_rows(start, end)
        return performance_view(measures, queries, device)

    async def releases(self, actor: Actor, range_name: str) -> ReleasesView:
        start, end = self._window(actor, range_name, None)
        async with self._uow_factory() as uow:
            releases = await uow.insight.release_rows(start, end)
            measures = await uow.insight.measure_rows(start, end)
            pipeline = await uow.insight.pipeline_rows()
        return ReleasesView(
            release_view(releases, measures),
            tuple(pipeline_views(pipeline, self._clock.now())),
        )
