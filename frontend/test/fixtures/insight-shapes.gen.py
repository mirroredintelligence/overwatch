"""Writes frontend/test/fixtures/insight-shapes.ts: the JSON the back end answers for the five insight
tabs, produced by the back end's own views and JSON mappers over sample daily rows (W9F). Sample
values only. Run from backend/:

    uv run python ../frontend/test/fixtures/insight-shapes.gen.py > ../frontend/test/fixtures/insight-shapes.ts

Re-run it when a mapping changes, so a front-end test never holds a shape the back end does not send.
"""

import json
from datetime import UTC, date, datetime, timedelta

from diucs.adapters.inbound.fhir_rest.routes_insight import (
    friction_json,
    funnels_json,
    paths_json,
    performance_json,
    releases_json,
)
from diucs.application.use_cases.browser_insight import ReleasesView
from diucs.domain.model.insight import MeasureRow, PipelineRow, ReleaseRow
from diucs.domain.model.telemetry_aggregates import (
    ElementUsageDailyRow,
    FrictionDailyRow,
    FunnelDailyRow,
    QueryStatDailyRow,
    RouteDailyRow,
)
from diucs.domain.rules.browser_insight import BUCKET_COUNT, bucket_of
from diucs.domain.rules.insight_views import (
    friction_table,
    funnel_views,
    paths_view,
    performance_view,
    pipeline_views,
    release_view,
)

DAY = date(2026, 10, 29)
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)


def funnel_row(funnel: str, step: str, entered: int, channel: str = "browser") -> FunnelDailyRow:
    return FunnelDailyRow(DAY, funnel, step, "reporter", channel, "phone", entered, 0, None)


def friction_row(element: str, kind: str, events: int, sessions: int, route: str = "") -> FrictionDailyRow:
    return FrictionDailyRow(DAY, element, kind, "advisor", "desktop", 0, events, sessions, route)


def usage_row(element: str, interactions: int, sessions: int) -> ElementUsageDailyRow:
    return ElementUsageDailyRow(DAY, element, "advisor", "desktop", interactions, sessions)


def route_row(route: str, sessions: int) -> RouteDailyRow:
    return RouteDailyRow(DAY, route, "advisor", "desktop", None, None, None, None, None, None, 0, sessions)


def measure_row(measure: str, value: float, sessions: int, *, route: str = "/advisor/board",
                device: str = "desktop", release: str = "1.4.3") -> MeasureRow:
    buckets = [0] * BUCKET_COUNT
    buckets[bucket_of(measure, value)] = sessions
    return MeasureRow(DAY, measure, route, device, release, sessions, sessions, tuple(buckets))


def release_row(release: str, sessions: int, friction: int) -> ReleaseRow:
    return ReleaseRow(DAY, release, sessions, 1000, friction, 6, 500)


FUNNELS = funnels_json(
    funnel_views(
        {
            "reporter-set-up": [
                funnel_row("reporter-set-up", "Set-up opened", 300),
                funnel_row("reporter-set-up", "Set-up opened", 112, "app"),
                funnel_row("reporter-set-up", "Set-up opened", 6, "link"),
                funnel_row("reporter-set-up", "Home-screen guide viewed", 391),
                funnel_row("reporter-set-up", "Notification screen viewed", 346),
                funnel_row("reporter-set-up", "PIN screen viewed", 210),
                funnel_row("reporter-set-up", "Set-up finished", 9),
            ],
            "advisor-call": [
                funnel_row("advisor-call", "Case opened", 80),
                funnel_row("advisor-call", "Options viewed", 70),
                funnel_row("advisor-call", "Outcome screen viewed", 50),
            ],
        }
    ),
    "7d",
    None,
)
FUNNELS_EMPTY = funnels_json([], "7d", None)

PATHS = paths_json(
    paths_view(
        [route_row("/advisor/board", 120), route_row("/advisor/week", 40), route_row("/help", 4)],
        [
            friction_row("PAGE", "u-turn", 15, 12, "/advisor/board"),
            friction_row("PAGE", "u-turn", 2, 2, "/help"),
        ],
    ),
    "7d",
    None,
)

FRICTION = friction_json(
    friction_table(
        [
            friction_row("ADV-OPT-REQUEST-BTN", "rage", 130, 40),
            friction_row("ADV-NEEDS-POSTCODE", "validation-loop", 60, 30),
            friction_row("ADV-SEARCH-BTN", "dead", 20, 30),
            friction_row("ADV-REF-INPUT", "dead", 25, 30),
            friction_row("PAGE", "u-turn", 15, 12, "/advisor/board"),
            friction_row("ADV-TINY-BTN", "rage", 4, 3),
        ],
        [
            usage_row("ADV-OPT-REQUEST-BTN", 1000, 40),
            usage_row("ADV-NEEDS-POSTCODE", 500, 30),
            usage_row("ADV-SEARCH-BTN", 500, 30),
            usage_row("ADV-REF-INPUT", 500, 30),
            usage_row("ADV-TINY-BTN", 9, 3),
        ],
    ),
    "7d",
    None,
)

PERFORMANCE = performance_json(
    performance_view(
        [
            measure_row("lcp", 2400, 40),
            measure_row("lcp", 3500, 30, device="phone"),
            measure_row("lcp", 5000, 10, route="/advisor/case/[ref]"),
            measure_row("inp", 150, 40),
            measure_row("cls", 0.04, 5),
        ],
        [
            QueryStatDailyRow(DAY, "Q-BOARD", 120, 38.0, 91.0, 1),
            QueryStatDailyRow(DAY, "Q-OPTIONS", 60, 80.0, 190.0, 0),
        ],
        None,
    ),
    "7d",
    None,
)
PERFORMANCE_EMPTY = performance_json(performance_view([], [], None), "7d", None)

PIPELINE = pipeline_views(
    [
        PipelineRow("messages.outbound", 3, 1, NOW - timedelta(seconds=95)),
        PipelineRow("capacity.events", 0, 0, None),
    ],
    NOW,
)
RELEASES = releases_json(
    ReleasesView(
        release_view(
            [release_row("1.4.2", 60, 12), release_row("1.4.3", 50, 40)],
            [
                measure_row("lcp", 2000, 60, release="1.4.2"),
                measure_row("lcp", 3000, 50, release="1.4.3"),
                measure_row("inp", 200, 60, release="1.4.2"),
                measure_row("inp", 200, 50, release="1.4.3"),
            ],
        ),
        tuple(PIPELINE),
    ),
    "7d",
)
RELEASES_ALONE = releases_json(ReleasesView(release_view([release_row("1.4.3", 50, 40)], []), tuple(PIPELINE)), "7d")

SHAPES = {
    "INSIGHT_FUNNELS": FUNNELS,
    "INSIGHT_FUNNELS_EMPTY": FUNNELS_EMPTY,
    "INSIGHT_PATHS": PATHS,
    "INSIGHT_FRICTION": FRICTION,
    "INSIGHT_PERFORMANCE": PERFORMANCE,
    "INSIGHT_PERFORMANCE_EMPTY": PERFORMANCE_EMPTY,
    "INSIGHT_RELEASES": RELEASES,
    "INSIGHT_RELEASES_ALONE": RELEASES_ALONE,
}

print("// GENERATED by insight-shapes.gen.py from the back end's own views and JSON mappers (W9F). Do not edit.")
print("// Sample values only: no patient data.")
for name, value in SHAPES.items():
    print(f"export const {name} = {json.dumps(value, indent=2)};")
