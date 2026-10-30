"""The insight tabs built from the stored daily rows (W9F): what each tab shows, with the floor of
ten sessions applied, no advisor ranking, and the release gate of observability.md.

Synthetic rows only. The stored shapes are tests/integration/application/test_browser_insight.py's.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from diucs.domain.errors import ValidationFailed
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
    GATE_FRICTION_POINTS,
    GATE_SLOWER_FRACTION,
    SLOWEST_LIMIT,
    friction_table,
    funnel_views,
    paths_view,
    performance_view,
    pipeline_views,
    range_window,
    release_view,
)

DAY = date(2026, 10, 28)
NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


# ---- the range -----------------------------------------------------------------------------------


@pytest.mark.parametrize(("name", "days"), [("24h", 2), ("7d", 7), ("30d", 30)])
def test_a_range_is_whole_utc_days_ending_today(name: str, days: int) -> None:
    start, end = range_window(name, date(2026, 10, 29))

    assert end == date(2026, 10, 29)
    assert (end - start).days + 1 == days


def test_a_range_that_is_not_listed_is_refused_by_name() -> None:
    with pytest.raises(ValidationFailed) as refused:
        range_window("1y", date(2026, 10, 29))

    assert refused.value.field == "range"


# ---- funnels -------------------------------------------------------------------------------------


def funnel_row(
    step: str,
    entered: int,
    *,
    channel: str = "browser",
    day: date = DAY,
    funnel: str = "reporter-set-up",
) -> FunnelDailyRow:
    return FunnelDailyRow(
        day=day,
        funnel=funnel,
        step=step,
        role="reporter",
        channel=channel,
        device="phone",
        entered=entered,
        completed=0,
        median_ms=None,
    )


def reporter_rows(*counts: int, channel: str = "browser") -> list[FunnelDailyRow]:
    steps = [
        "Set-up opened",
        "Home-screen guide viewed",
        "Notification screen viewed",
        "PIN screen viewed",
        "Set-up finished",
    ]
    return [funnel_row(step, n, channel=channel) for step, n in zip(steps, counts, strict=False)]


def test_a_step_is_a_share_of_the_first_step_and_the_steps_keep_their_order() -> None:
    views = funnel_views({"reporter-set-up": reporter_rows(40, 30, 20, 12, 10)})

    view = views[0]
    assert (view.name, view.label) == ("reporter-set-up", "Reporter set-up")
    assert [(step.name, step.count, step.pct) for step in view.steps] == [
        ("Set-up opened", 40, 100),
        ("Home-screen guide viewed", 30, 75),
        ("Notification screen viewed", 20, 50),
        ("PIN screen viewed", 12, 30),
        ("Set-up finished", 10, 25),
    ]
    assert not any(step.suppressed for step in view.steps)


def test_a_step_under_ten_sessions_has_no_number_and_no_percentage() -> None:
    view = funnel_views({"reporter-set-up": reporter_rows(40, 30, 9, 3, 0)})[0]

    suppressed = [step for step in view.steps if step.suppressed]
    assert [step.name for step in suppressed] == [
        "Notification screen viewed",
        "PIN screen viewed",
        "Set-up finished",
    ]
    assert all(step.count is None and step.pct is None for step in suppressed)


def test_a_funnel_whose_first_step_is_under_ten_shows_nothing_at_all() -> None:
    view = funnel_views({"reporter-set-up": reporter_rows(9, 8, 7)})[0]

    assert all(step.suppressed and step.count is None and step.pct is None for step in view.steps)
    assert view.split == []


def test_a_funnel_with_no_rows_lists_its_steps_as_hidden_not_as_zero() -> None:
    view = funnel_views({"reporter-set-up": []})[0]

    assert len(view.steps) == 5
    assert all(step.suppressed for step in view.steps)


def test_the_days_of_the_range_add_up() -> None:
    rows = [
        funnel_row("Set-up opened", 6, day=date(2026, 10, 27)),
        funnel_row("Set-up opened", 6, day=DAY),
        funnel_row("Home-screen guide viewed", 6, day=DAY),
        funnel_row("Home-screen guide viewed", 5, day=date(2026, 10, 27)),
    ]

    view = funnel_views({"reporter-set-up": rows})[0]

    assert [(step.name, step.count) for step in view.steps[:2]] == [
        ("Set-up opened", 12),
        ("Home-screen guide viewed", 11),
    ]


def test_roles_and_devices_of_one_step_add_up() -> None:
    rows = reporter_rows(8) + [
        FunnelDailyRow(DAY, "reporter-set-up", "Set-up opened", "reporter", "browser", "tablet", 8, 0, None)
    ]

    view = funnel_views({"reporter-set-up": rows})[0]

    assert view.steps[0].count == 16


def test_the_split_is_the_share_of_first_step_sessions_by_channel_and_hides_small_channels() -> None:
    rows = [
        *reporter_rows(30, 20, channel="browser"),
        *reporter_rows(10, 5, channel="app"),
        *reporter_rows(4, 2, channel="link"),
    ]

    view = funnel_views({"reporter-set-up": rows})[0]

    split = {item.channel: item for item in view.split}
    assert (split["browser"].pct, split["browser"].suppressed) == (68, False)
    assert (split["app"].pct, split["app"].suppressed) == (23, False)
    assert (split["link"].pct, split["link"].suppressed) == (None, True)


def test_only_the_browser_funnels_are_listed_and_unknown_ones_are_left_out() -> None:
    views = funnel_views({"reporter-set-up": [], "coo-icb-adoption": [], "no-such-funnel": []})

    assert [view.name for view in views] == ["reporter-set-up"]


# ---- friction ------------------------------------------------------------------------------------


def friction_row(
    element: str, kind: str, events: int, sessions: int, *, route: str = "", day: date = DAY
) -> FrictionDailyRow:
    return FrictionDailyRow(day, element, kind, "advisor", "desktop", 0, events, sessions, route)


def usage_row(element: str, interactions: int, sessions: int, day: date = DAY) -> ElementUsageDailyRow:
    return ElementUsageDailyRow(day, element, "advisor", "desktop", interactions, sessions)


def test_41_in_312_is_13_percent_and_for_review_and_3_percent_is_not() -> None:
    table = friction_table(
        [
            friction_row("ADV-OPT-REQUEST-BTN", "rage", 41, 14),
            friction_row("ADV-REF-INPUT", "validation-loop", 3, 12),
        ],
        [usage_row("ADV-OPT-REQUEST-BTN", 312, 14), usage_row("ADV-REF-INPUT", 100, 12)],
    )

    rows = {row.element_id: row for row in table.rows}
    assert rows["ADV-OPT-REQUEST-BTN"].rate == pytest.approx(41 / 312)
    assert rows["ADV-OPT-REQUEST-BTN"].review is True
    assert rows["ADV-REF-INPUT"].rate == pytest.approx(0.03)
    assert rows["ADV-REF-INPUT"].review is False


def test_exactly_five_percent_is_not_for_review() -> None:
    table = friction_table([friction_row("ADV-X-BTN", "dead", 5, 12)], [usage_row("ADV-X-BTN", 100, 12)])

    assert table.rows[0].review is False


def test_the_events_of_an_element_and_kind_add_up_across_roles_devices_and_days() -> None:
    table = friction_table(
        [
            friction_row("ADV-X-BTN", "rage", 4, 6),
            FrictionDailyRow(DAY, "ADV-X-BTN", "rage", "lead", "phone", 0, 6, 6),
            friction_row("ADV-X-BTN", "rage", 10, 6, day=date(2026, 10, 27)),
        ],
        [usage_row("ADV-X-BTN", 100, 6), usage_row("ADV-X-BTN", 100, 6, day=date(2026, 10, 27))],
    )

    assert len(table.rows) == 1
    assert (table.rows[0].events, table.rows[0].interactions) == (20, 200)


def test_an_element_under_ten_sessions_is_left_out_and_counted() -> None:
    table = friction_table(
        [friction_row("ADV-X-BTN", "rage", 4, 3), friction_row("ADV-Y-BTN", "rage", 4, 12)],
        [usage_row("ADV-X-BTN", 9, 3), usage_row("ADV-Y-BTN", 50, 12)],
    )

    assert [row.element_id for row in table.rows] == ["ADV-Y-BTN"]
    assert table.suppressed_groups == 1


def test_page_level_friction_has_no_rate_and_is_hidden_when_few_sessions_met_it() -> None:
    table = friction_table(
        [
            friction_row("PAGE", "u-turn", 15, 12, route="/advisor/board"),
            friction_row("PAGE", "u-turn", 4, 4, route="/advisor/week"),
        ],
        [],
    )

    assert [(row.route, row.rate, row.interactions, row.review) for row in table.rows] == [
        ("/advisor/board", None, None, False)
    ]
    assert table.suppressed_groups == 1


def test_the_table_is_ordered_by_rate_then_events_and_names_no_person() -> None:
    table = friction_table(
        [
            friction_row("ADV-A-BTN", "rage", 2, 12),
            friction_row("ADV-B-BTN", "rage", 30, 12),
            friction_row("ADV-C-BTN", "dead", 9, 12),
        ],
        [usage_row("ADV-A-BTN", 100, 12), usage_row("ADV-B-BTN", 100, 12), usage_row("ADV-C-BTN", 100, 12)],
    )

    assert [row.element_id for row in table.rows] == ["ADV-B-BTN", "ADV-C-BTN", "ADV-A-BTN"]
    assert not any(hasattr(row, "advisor") or hasattr(row, "person") for row in table.rows)


# ---- paths ---------------------------------------------------------------------------------------


def route_row(route: str, sessions: int, *, role: str = "advisor", day: date = DAY) -> RouteDailyRow:
    return RouteDailyRow(day, route, role, "desktop", None, None, None, None, None, None, 0, sessions)


def test_routes_are_listed_by_sessions_and_a_small_one_has_no_number() -> None:
    view = paths_view(
        [route_row("/advisor/board", 120), route_row("/advisor/week", 40), route_row("/help", 4)],
        [],
    )

    shown = [(row.route, row.sessions, row.suppressed) for row in view.most_common]
    assert shown[:2] == [("/advisor/board", 120, False), ("/advisor/week", 40, False)]
    assert shown[2] == ("/help", None, True)


def test_the_roles_of_one_route_add_up_and_the_list_is_capped() -> None:
    rows = [route_row("/advisor/board", 6), route_row("/advisor/board", 7, role="lead")]
    rows += [route_row(f"/r{index}", 5) for index in range(15)]

    view = paths_view(rows, [])

    assert len(view.most_common) == 10
    assert view.most_common[0].route == "/advisor/board"
    assert view.most_common[0].sessions == 13


def test_u_turns_are_the_page_level_friction_of_that_kind_by_route() -> None:
    view = paths_view(
        [],
        [
            friction_row("PAGE", "u-turn", 15, 12, route="/advisor/board"),
            friction_row("PAGE", "thrash", 9, 12, route="/advisor/board"),
            friction_row("ADV-X-BTN", "u-turn", 9, 12),
            friction_row("PAGE", "u-turn", 2, 2, route="/help"),
        ],
    )

    assert [(row.route, row.sessions, row.suppressed) for row in view.u_turns] == [
        ("/advisor/board", 12, False),
        ("/help", None, True),
    ]


# ---- performance ---------------------------------------------------------------------------------


def measure_row(
    measure: str,
    value: float,
    samples: int,
    sessions: int,
    *,
    route: str = "/advisor/board",
    device: str = "desktop",
    release: str = "1.4.2",
    day: date = DAY,
) -> MeasureRow:
    buckets = [0] * BUCKET_COUNT
    buckets[bucket_of(measure, value)] = samples
    return MeasureRow(day, measure, route, device, release, sessions, samples, tuple(buckets))


def test_a_vital_is_its_p75_against_its_budget_by_device() -> None:
    view = performance_view(
        [
            measure_row("lcp", 2400, 30, 20),
            measure_row("lcp", 3500, 30, 20, device="phone"),
            measure_row("inp", 150, 30, 20),
            measure_row("cls", 0.04, 30, 20),
        ],
        [],
        None,
    )

    vitals = {(vital.measure, vital.device): vital for vital in view.vitals}
    lcp = vitals[("lcp", "desktop")]
    assert (lcp.label, lcp.p75, lcp.budget, lcp.unit, lcp.suppressed) == (
        "Largest contentful paint",
        2500.0,
        2500.0,
        "ms",
        False,
    )
    assert vitals[("lcp", "phone")].p75 == 4000.0
    assert vitals[("inp", "desktop")].unit == "ms"
    assert vitals[("cls", "desktop")].unit == "score"
    assert vitals[("cls", "desktop")].p75 == pytest.approx(0.05)


def test_a_vital_under_ten_sessions_has_no_number() -> None:
    view = performance_view([measure_row("lcp", 2400, 30, 9)], [], None)

    vital = next(item for item in view.vitals if item.measure == "lcp")
    assert (vital.p75, vital.suppressed) == (None, True)


def test_the_floor_counts_each_days_largest_group_so_routes_are_not_added_twice() -> None:
    # Three routes with 5 sessions each on one day: no group is over ten and the day's best lower
    # bound of distinct sessions is 5, not 15.
    rows = [measure_row("lcp", 2400, 5, 5, route=f"/r{index}") for index in range(3)]

    vital = next(item for item in performance_view(rows, [], None).vitals if item.measure == "lcp")

    assert vital.suppressed is True


def test_each_days_largest_group_is_summed_over_the_range() -> None:
    rows = [
        measure_row("lcp", 2400, 6, 6, day=date(2026, 10, 27)),
        measure_row("lcp", 2400, 6, 6, day=DAY),
    ]

    vital = next(item for item in performance_view(rows, [], None).vitals if item.measure == "lcp")

    assert vital.suppressed is False


def test_a_device_filter_keeps_only_that_device() -> None:
    view = performance_view(
        [measure_row("lcp", 2400, 30, 20), measure_row("lcp", 3500, 30, 20, device="phone")],
        [],
        "phone",
    )

    assert {vital.device for vital in view.vitals} == {"phone"}


def test_the_slowest_routes_are_by_lcp_p95_and_leave_out_small_routes() -> None:
    rows = [
        measure_row("lcp", 900, 30, 20, route="/fast"),
        measure_row("lcp", 5000, 30, 20, route="/slow"),
        measure_row("lcp", 9000, 30, 4, route="/tiny"),
        measure_row("inp", 900, 30, 20, route="/not-lcp"),
    ]

    view = performance_view(rows, [], None)

    assert [(slow.name, slow.p95_ms) for slow in view.slowest_routes] == [
        ("/slow", 6000.0),
        ("/fast", 1000.0),
    ]


def test_at_most_the_limit_of_routes_and_queries_are_listed() -> None:
    rows = [measure_row("lcp", 1000 + index, 30, 20, route=f"/r{index}") for index in range(12)]
    queries = [
        QueryStatDailyRow(DAY, f"Q-{index}", 100, 10.0, float(index), 0) for index in range(12)
    ]

    view = performance_view(rows, queries, None)

    assert len(view.slowest_routes) == SLOWEST_LIMIT
    assert len(view.slowest_queries) == SLOWEST_LIMIT


def test_a_query_is_its_worst_daily_p95_named_by_its_id_only() -> None:
    view = performance_view(
        [],
        [
            QueryStatDailyRow(date(2026, 10, 27), "Q-BOARD", 100, 30.0, 91.0, 0),
            QueryStatDailyRow(DAY, "Q-BOARD", 100, 30.0, 120.0, 1),
            QueryStatDailyRow(DAY, "Q-OPTIONS", 50, 20.0, 80.0, 0),
        ],
        None,
    )

    assert [(slow.name, slow.p95_ms) for slow in view.slowest_queries] == [
        ("Q-BOARD", 120.0),
        ("Q-OPTIONS", 80.0),
    ]


# ---- release comparison -------------------------------------------------------------------------


def release_row(
    release: str,
    sessions: int,
    *,
    interactions: int = 1000,
    friction: int = 10,
    errors: int = 5,
    views: int = 500,
    day: date = DAY,
) -> ReleaseRow:
    return ReleaseRow(day, release, sessions, interactions, friction, errors, views)


def test_the_two_newest_releases_with_ten_sessions_each_are_compared() -> None:
    view = release_view(
        [release_row("1.4.0", 50), release_row("1.4.2", 30), release_row("1.4.10", 20), release_row("1.3.9", 40)],
        [],
    )

    assert view is not None
    assert (view.old, view.new) == ("1.4.2", "1.4.10")


def test_releases_sort_by_number_not_by_text() -> None:
    view = release_view([release_row("1.9.0", 20), release_row("1.10.0", 20)], [])

    assert view is not None
    assert (view.old, view.new) == ("1.9.0", "1.10.0")


def test_a_release_under_ten_sessions_is_not_compared() -> None:
    assert release_view([release_row("1.4.2", 30), release_row("1.4.3", 9)], []) is None
    assert release_view([release_row("1.4.2", 30)], []) is None
    assert release_view([], []) is None


def test_a_releases_sessions_add_up_over_the_range() -> None:
    view = release_view(
        [
            release_row("1.4.2", 6, day=date(2026, 10, 27)),
            release_row("1.4.2", 6, day=DAY),
            release_row("1.4.3", 12),
        ],
        [],
    )

    assert view is not None
    assert (view.old, view.new) == ("1.4.2", "1.4.3")


def test_vitals_are_compared_by_p75_and_a_ten_percent_slowdown_is_held_for_review() -> None:
    view = release_view(
        [release_row("1.4.2", 30), release_row("1.4.3", 30)],
        [
            measure_row("lcp", 2000, 30, 30, release="1.4.2"),
            measure_row("lcp", 3000, 30, 30, release="1.4.3"),
            measure_row("inp", 200, 30, 30, release="1.4.2"),
            measure_row("inp", 200, 30, 30, release="1.4.3"),
        ],
    )

    assert view is not None
    by_name = {measure.measure: measure for measure in view.measures}
    lcp = by_name["Largest contentful paint, p75"]
    assert (lcp.old, lcp.new, lcp.unit, lcp.review) == (2000.0, 3000.0, "ms", True)
    inp = by_name["Interaction to next paint, p75"]
    assert (inp.old, inp.new, inp.review) == (200.0, 200.0, False)


def test_the_gate_is_ten_percent_and_two_points_as_the_spec_says() -> None:
    assert GATE_SLOWER_FRACTION == 0.10
    assert GATE_FRICTION_POINTS == 2.0


def test_friction_is_events_per_hundred_interactions_and_two_points_more_is_held() -> None:
    view = release_view(
        [
            release_row("1.4.2", 30, interactions=1000, friction=30),
            release_row("1.4.3", 30, interactions=1000, friction=51),
        ],
        [],
    )

    assert view is not None
    friction = next(m for m in view.measures if m.measure == "Friction events per 100 interactions")
    assert (friction.old, friction.new, friction.unit, friction.review) == (3.0, 5.1, "percent", True)


def test_a_rise_of_exactly_two_points_is_not_held() -> None:
    view = release_view(
        [
            release_row("1.4.2", 30, interactions=1000, friction=30),
            release_row("1.4.3", 30, interactions=1000, friction=50),
        ],
        [],
    )

    assert view is not None
    friction = next(m for m in view.measures if m.measure == "Friction events per 100 interactions")
    assert friction.review is False


def test_errors_are_per_hundred_page_views() -> None:
    view = release_view(
        [release_row("1.4.2", 30, errors=5, views=500), release_row("1.4.3", 30, errors=20, views=500)],
        [],
    )

    assert view is not None
    errors = next(m for m in view.measures if m.measure == "Errors shown per 100 page views")
    assert (errors.old, errors.new, errors.unit) == (1.0, 4.0, "percent")


def test_a_measure_a_release_has_too_few_sessions_for_is_left_out() -> None:
    view = release_view(
        [release_row("1.4.2", 30), release_row("1.4.3", 30)],
        [
            measure_row("lcp", 2000, 30, 30, release="1.4.2"),
            measure_row("lcp", 3000, 5, 5, release="1.4.3"),
        ],
    )

    assert view is not None
    assert not any(m.measure.startswith("Largest") for m in view.measures)


def test_a_release_with_no_interactions_has_no_friction_rate() -> None:
    view = release_view(
        [release_row("1.4.2", 30, interactions=0), release_row("1.4.3", 30, interactions=0)], []
    )

    assert view is not None
    assert not any(m.measure.startswith("Friction") for m in view.measures)


# ---- pipeline ------------------------------------------------------------------------------------


def test_the_pipeline_is_pending_dead_and_the_age_of_the_oldest_pending_message() -> None:
    views = pipeline_views(
        [
            PipelineRow("messages", 3, 1, NOW - timedelta(seconds=95)),
            PipelineRow("capacity", 0, 0, None),
        ],
        NOW,
    )

    assert [(v.name, v.active, v.dead_lettered, v.oldest_seconds) for v in views] == [
        ("messages", 3, 1, 95),
        ("capacity", 0, 0, None),
    ]


def test_a_topic_that_is_not_a_known_one_is_listed_as_other_and_added_up() -> None:
    views = pipeline_views(
        [
            PipelineRow("messages", 1, 0, NOW - timedelta(seconds=10)),
            PipelineRow("sample-patient-topic", 2, 1, NOW - timedelta(seconds=50)),
            PipelineRow("another-topic", 4, 0, NOW - timedelta(seconds=20)),
        ],
        NOW,
    )

    other = next(v for v in views if v.name == "other")
    assert (other.active, other.dead_lettered, other.oldest_seconds) == (6, 1, 50)
    assert "sample-patient-topic" not in {v.name for v in views}


def test_an_age_in_the_future_is_zero() -> None:
    views = pipeline_views([PipelineRow("messages", 1, 0, NOW + timedelta(seconds=30))], NOW)

    assert views[0].oldest_seconds == 0
