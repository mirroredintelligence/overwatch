"""The insight tabs built from the stored daily rows (W9F).

Pure rules, no I/O. Each function takes the rows a range holds and returns what one tab shows, with
the floor of ten sessions applied (a group under it has no number, a funnel step has no percentage)
and no figure about a person: every group is a screen, an element, a route, a device, a role or a
release (observability.md, "The rule that governs the rest"). Daily rows are summed over the range.

A daily row counts each session once for its group and day, so a count of sessions over a range is
a count of session-days, and a group's sessions across several groups cannot be added without
counting a session once per group. Where a figure spans groups the floor uses a lower bound on the
distinct sessions (`lower_bound_sessions`: each day's largest group, added over the days), so the
floor is never passed on the strength of a double count.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import floor
from typing import Final

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.insight import MeasureRow, PipelineRow, ReleaseRow
from diucs.domain.model.telemetry_aggregates import (
    ElementUsageDailyRow,
    FrictionDailyRow,
    FunnelDailyRow,
    QueryStatDailyRow,
    RouteDailyRow,
)
from diucs.domain.rules.browser_insight import (
    BROWSER_FUNNEL_LABELS,
    BROWSER_FUNNELS,
    BUDGETS,
    DEVICES,
    METRICS,
    PAGE_ELEMENT_ID,
    percentile,
)
from diucs.domain.rules.telemetry_insights import for_review, is_suppressed

# Days (UTC, today included) of each range. The counters are daily, so "24 hours" is yesterday and
# today: the two days that hold the last 24 hours.
RANGE_DAYS: Final[Mapping[str, int]] = {"24h": 2, "7d": 7, "30d": 30}
SLOWEST_LIMIT: Final = 5
ROUTES_LIMIT: Final = 10
# The release gate (observability.md, "How it is enforced"): a vital more than 10% slower at p75,
# or a friction rate more than 2 points higher, is held for review.
GATE_SLOWER_FRACTION: Final = 0.10
GATE_FRICTION_POINTS: Final = 2.0

VITAL_LABELS: Final[Mapping[str, str]] = {
    "lcp": "Largest contentful paint",
    "inp": "Interaction to next paint",
    "cls": "Cumulative layout shift",
}
VITAL_UNITS: Final[Mapping[str, str]] = {"lcp": "ms", "inp": "ms", "cls": "score"}
FRICTION_MEASURE: Final = "Friction events per 100 interactions"
ERRORS_MEASURE: Final = "Errors shown per 100 page views"

# The outbox topics, queues and the code topic a pipeline row may be named by. Anything else is
# listed as "other", so a topic name can never carry more than a fixed word.
PIPELINE_TOPICS: Final = frozenset(
    {
        "capacity.events",
        "booking.events",
        "registration.events",
        "criteria.events",
        "alerts.events",
        "network.events",
        "messages.outbound",
        "codes.dispatch",
        "inbound.replies",
        "inbound.receipts",
        "scheduled.work",
        "projection.work",
    }
)
OTHER_TOPIC: Final = "other"


def range_window(name: str, today: date) -> tuple[date, date]:
    """The first and last day of a range ending today."""
    days = RANGE_DAYS.get(name)
    if days is None:
        raise ValidationFailed("range", "must be 24h, 7d or 30d")
    return today - timedelta(days=days - 1), today


def _percent(count: int, whole: int) -> int:
    return min(100, floor(100 * count / whole + 0.5))


def lower_bound_sessions(rows: Iterable[tuple[date, int]]) -> int:
    """A lower bound on the distinct sessions behind several groups: each day's largest group,
    added over the days."""
    best: dict[date, int] = {}
    for day, sessions in rows:
        best[day] = max(best.get(day, 0), sessions)
    return sum(best.values())


# ---- funnels -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StepView:
    name: str
    count: int | None
    pct: int | None
    suppressed: bool


@dataclass(frozen=True, slots=True)
class SplitView:
    channel: str
    pct: int | None
    suppressed: bool


@dataclass(frozen=True, slots=True)
class FunnelView:
    name: str
    label: str
    steps: tuple[StepView, ...]
    split: tuple[SplitView, ...]


def funnel_views(rows_by_funnel: Mapping[str, Sequence[FunnelDailyRow]]) -> list[FunnelView]:
    """Each funnel of the browser that has rows given for it, steps in order. A step is the number
    of sessions that reached it as a share of those that reached the first one; a group under ten
    sessions, or any step of a funnel whose first step is under ten, has no number."""
    views: list[FunnelView] = []
    for funnel, steps in BROWSER_FUNNELS.items():
        if funnel not in rows_by_funnel:
            continue
        rows = rows_by_funnel[funnel]
        entered: dict[str, int] = defaultdict(int)
        by_channel: dict[str, int] = defaultdict(int)
        first = steps[0].step
        for row in rows:
            entered[row.step] += row.entered
            if row.step == first:
                by_channel[row.channel] += row.entered
        start = entered[first]
        shown: list[StepView] = []
        for step in steps:
            count = entered[step.step]
            if is_suppressed(start) or is_suppressed(count):
                shown.append(StepView(step.step, None, None, True))
            else:
                shown.append(StepView(step.step, count, _percent(count, start), False))
        split: list[SplitView] = []
        if not is_suppressed(start):
            for channel in sorted(by_channel):
                count = by_channel[channel]
                if is_suppressed(count):
                    split.append(SplitView(channel, None, True))
                else:
                    split.append(SplitView(channel, _percent(count, start), False))
        views.append(FunnelView(funnel, BROWSER_FUNNEL_LABELS[funnel], tuple(shown), tuple(split)))
    return views


# ---- friction ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrictionView:
    element_id: str
    kind: str
    route: str | None
    events: int
    interactions: int | None
    rate: float | None
    review: bool


@dataclass(frozen=True, slots=True)
class FrictionTable:
    rows: tuple[FrictionView, ...]
    suppressed_groups: int


def friction_table(
    friction: Sequence[FrictionDailyRow], usage: Sequence[ElementUsageDailyRow]
) -> FrictionTable:
    """Friction per element and kind (and route, for friction of the page itself): the events over
    the element's interactions, with the review flag. A group whose element had fewer than ten
    sessions (or, for the page or an element with no clicks, whose friction was met in fewer than
    ten) is left out and counted."""
    used: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for use in usage:
        used[use.element_id][0] += use.interactions
        used[use.element_id][1] += use.sessions
    groups: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    for row in friction:
        key = (row.element_id, row.kind, row.route)
        groups[key][0] += row.events
        groups[key][1] += row.sessions
    shown: list[FrictionView] = []
    hidden = 0
    for (element, kind, route), (events, met_in) in groups.items():
        has_clicks = element != PAGE_ELEMENT_ID and element in used
        sessions = used[element][1] if has_clicks else met_in
        if is_suppressed(sessions):
            hidden += 1
            continue
        if has_clicks and used[element][0] > 0:
            interactions: int | None = used[element][0]
            rate: float | None = events / used[element][0]
            review = for_review(events, used[element][0])
        else:
            interactions, rate, review = None, None, False
        shown.append(FrictionView(element, kind, route or None, events, interactions, rate, review))
    shown.sort(
        key=lambda view: (
            -(view.rate if view.rate is not None else -1.0),
            -view.events,
            view.element_id,
            view.kind,
            view.route or "",
        )
    )
    return FrictionTable(tuple(shown), hidden)


# ---- paths ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouteUse:
    route: str
    sessions: int | None
    suppressed: bool


@dataclass(frozen=True, slots=True)
class PathsView:
    most_common: tuple[RouteUse, ...]
    u_turns: tuple[RouteUse, ...]


def _route_uses(sessions: Mapping[str, int]) -> tuple[RouteUse, ...]:
    shown = sorted(
        ((route, count) for route, count in sessions.items() if not is_suppressed(count)),
        key=lambda item: (-item[1], item[0]),
    )
    hidden = sorted(route for route, count in sessions.items() if is_suppressed(count))
    uses = [RouteUse(route, count, False) for route, count in shown]
    uses += [RouteUse(route, None, True) for route in hidden]
    return tuple(uses[:ROUTES_LIMIT])


def paths_view(routes: Sequence[RouteDailyRow], friction: Sequence[FrictionDailyRow]) -> PathsView:
    """The routes people were on, by sessions, and the routes people turned back from. A route
    under ten sessions is listed with no number, after the others and in name order, so the
    order says nothing about how few there were."""
    seen: dict[str, int] = defaultdict(int)
    for row in routes:
        seen[row.route] += row.sessions
    turned: dict[str, int] = defaultdict(int)
    for item in friction:
        if item.element_id == PAGE_ELEMENT_ID and item.kind == "u-turn":
            turned[item.route] += item.sessions
    return PathsView(_route_uses(seen), _route_uses(turned))


# ---- performance ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VitalView:
    measure: str
    label: str
    device: str
    p75: float | None
    budget: float
    unit: str
    suppressed: bool


@dataclass(frozen=True, slots=True)
class SlowView:
    name: str
    p95_ms: float


@dataclass(frozen=True, slots=True)
class PerformanceView:
    vitals: tuple[VitalView, ...]
    slowest_routes: tuple[SlowView, ...]
    slowest_queries: tuple[SlowView, ...]


def _summed(rows: Sequence[MeasureRow]) -> list[int]:
    total: list[int] = []
    for row in rows:
        if not total:
            total = [0] * len(row.buckets)
        for index, count in enumerate(row.buckets):
            total[index] += count
    return total


def _sessions(rows: Iterable[MeasureRow]) -> int:
    return lower_bound_sessions((row.day, row.sessions) for row in rows)


def performance_view(
    measures: Sequence[MeasureRow], queries: Sequence[QueryStatDailyRow], device: str | None
) -> PerformanceView:
    rows = [row for row in measures if device is None or row.device == device]
    vitals: list[VitalView] = []
    for measure in METRICS:
        for kind in DEVICES:
            group = [row for row in rows if row.measure == measure and row.device == kind]
            if not group:
                continue
            hidden = is_suppressed(_sessions(group))
            p75 = None if hidden else percentile(_summed(group), measure, 0.75)
            vitals.append(
                VitalView(
                    measure=measure,
                    label=VITAL_LABELS[measure],
                    device=kind,
                    p75=p75,
                    budget=BUDGETS[measure],
                    unit=VITAL_UNITS[measure],
                    suppressed=hidden or p75 is None,
                )
            )
    by_route: dict[str, list[MeasureRow]] = defaultdict(list)
    for row in rows:
        if row.measure == "lcp":
            by_route[row.route].append(row)
    slow_routes: list[SlowView] = []
    for route, group in by_route.items():
        if is_suppressed(_sessions(group)):
            continue
        p95 = percentile(_summed(group), "lcp", 0.95)
        if p95 is not None:
            slow_routes.append(SlowView(route, p95))
    slow_routes.sort(key=lambda slow: (-slow.p95_ms, slow.name))
    worst: dict[str, float] = {}
    for query in queries:
        if query.p95 is not None:
            worst[query.query_id] = max(worst.get(query.query_id, 0.0), query.p95)
    slow_queries = sorted(
        (SlowView(name, p95) for name, p95 in worst.items()), key=lambda s: (-s.p95_ms, s.name)
    )
    return PerformanceView(
        tuple(vitals), tuple(slow_routes[:SLOWEST_LIMIT]), tuple(slow_queries[:SLOWEST_LIMIT])
    )


# ---- release comparison --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReleaseMeasureView:
    measure: str
    old: float
    new: float
    unit: str
    review: bool


@dataclass(frozen=True, slots=True)
class ReleaseCompareView:
    old: str
    new: str
    measures: tuple[ReleaseMeasureView, ...]


def _version(release: str) -> tuple[int, ...]:
    return tuple(int(part) for part in release.split("."))


def _per_hundred(part: int, whole: int) -> float | None:
    return None if whole <= 0 else round(part / whole * 100, 1)


def release_view(
    releases: Sequence[ReleaseRow], measures: Sequence[MeasureRow]
) -> ReleaseCompareView | None:
    """The newest release with ten sessions against the one before it, or None when fewer than two
    releases have that many. A measure is left out when either release has too few sessions behind
    it. The change is flagged for review by the release gate (observability.md)."""
    sessions: dict[str, int] = defaultdict(int)
    for row in releases:
        sessions[row.release] += row.sessions
    eligible = sorted(
        (release for release, count in sessions.items() if not is_suppressed(count)),
        key=_version,
        reverse=True,
    )
    if len(eligible) < 2:
        return None
    new, old = eligible[0], eligible[1]
    total: dict[str, list[int]] = {new: [0, 0, 0, 0], old: [0, 0, 0, 0]}
    for row in releases:
        if row.release in total:
            for index, value in enumerate((row.interactions, row.friction, row.errors, row.views)):
                total[row.release][index] += value
    shown: list[ReleaseMeasureView] = []
    for metric in METRICS:
        figures: dict[str, float] = {}
        for release in (old, new):
            group = [r for r in measures if r.measure == metric and r.release == release]
            p75 = (
                None
                if is_suppressed(_sessions(group))
                else percentile(_summed(group), metric, 0.75)
            )
            if p75 is not None:
                figures[release] = p75
        if len(figures) == 2:
            slower = figures[new] > figures[old] * (1 + GATE_SLOWER_FRACTION)
            shown.append(
                ReleaseMeasureView(
                    f"{VITAL_LABELS[metric]}, p75",
                    figures[old],
                    figures[new],
                    VITAL_UNITS[metric],
                    slower,
                )
            )
    friction_old = _per_hundred(total[old][1], total[old][0])
    friction_new = _per_hundred(total[new][1], total[new][0])
    if friction_old is not None and friction_new is not None:
        shown.append(
            ReleaseMeasureView(
                FRICTION_MEASURE,
                friction_old,
                friction_new,
                "percent",
                friction_new - friction_old > GATE_FRICTION_POINTS,
            )
        )
    errors_old = _per_hundred(total[old][2], total[old][3])
    errors_new = _per_hundred(total[new][2], total[new][3])
    if errors_old is not None and errors_new is not None:
        shown.append(ReleaseMeasureView(ERRORS_MEASURE, errors_old, errors_new, "percent", False))
    return ReleaseCompareView(old, new, tuple(shown))


# ---- pipeline ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PipelineView:
    name: str
    active: int
    dead_lettered: int
    oldest_seconds: int | None


def pipeline_views(rows: Sequence[PipelineRow], now: datetime) -> list[PipelineView]:
    """The tenant's own outbox, a row per known topic in the order given (any other topic is added
    up as "other", last): what waits, what is dead, and the age of the oldest message waiting."""
    named: dict[str, list[PipelineRow]] = defaultdict(list)
    for row in rows:
        named[row.topic if row.topic in PIPELINE_TOPICS else OTHER_TOPIC].append(row)

    def age(group: Sequence[PipelineRow]) -> int | None:
        oldest = [row.oldest_pending for row in group if row.oldest_pending is not None]
        if not oldest:
            return None
        return max(0, int((now - min(oldest)).total_seconds()))

    names = [name for name in named if name != OTHER_TOPIC]
    if OTHER_TOPIC in named:
        names.append(OTHER_TOPIC)
    return [
        PipelineView(
            name,
            sum(row.active for row in group),
            sum(row.dead for row in group),
            age(group),
        )
        for name, group in ((name, named[name]) for name in names)
    ]
