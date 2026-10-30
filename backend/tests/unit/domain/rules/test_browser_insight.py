"""The pure rules that fold the browser's ui.* events into daily counters (W9F): what an event may
carry, which counter it feeds, the histogram buckets and the pseudonymous session marker. The
Neo4j side is in tests/integration/application/test_browser_insight.py.

Synthetic values only: a session id is hex, an element id is an upper-case code.
"""

import math
import re
from datetime import date

import pytest

from diucs.domain.rules.browser_insight import (
    BROWSER_FUNNELS,
    BUCKET_COUNT,
    BUDGETS,
    EDGES,
    MAX_BATCH_EVENTS,
    UNKNOWN_ROUTE,
    UiEvent,
    bucket_of,
    fold,
    marker_key,
    parse_event,
    percentile,
)
from diucs.domain.rules.telemetry_insights import FUNNELS

SESSION = "a1b2c3d4e5f60718"
OTHER_SESSION = "0f1e2d3c4b5a6978"
COMMON = {
    "session.id": SESSION,
    "user.role": "advisor",
    "release": "1.4.2",
    "device.type": "desktop",
    "app.mode": "browser",
}


def event(name: str, **extra: object) -> UiEvent:
    parsed = parse_event(name, {**COMMON, **extra})
    assert parsed is not None, (name, extra)
    return parsed


# ---- what an event may carry ---------------------------------------------------------------------


def test_a_click_with_an_element_id_is_read_and_carries_no_free_text() -> None:
    parsed = parse_event(
        "ui.click", {**COMMON, "element.id": "ADV-OPT-REQUEST-BTN", "dwell_ms": 40}
    )

    assert parsed is not None
    assert parsed.element_id == "ADV-OPT-REQUEST-BTN"
    assert parsed.session_id == SESSION
    assert parsed.device == "desktop"
    assert parsed.release == "1.4.2"


@pytest.mark.parametrize(
    ("name", "attributes"),
    [
        ("ui.click", {"element.id": "Sample Patient"}),
        ("ui.click", {"element.id": "adv-opt-request-btn"}),
        ("ui.click", {"element.id": "A" * 80}),
        ("ui.click", {}),
        ("ui.submit", {"form.id": "DT4 8XX"}),
        ("ui.page_view", {"page.route": "/advisor/case/DT4 8XX"}),
        ("ui.page_view", {"page.route": "advisor"}),
        ("ui.page_view", {"page.route": "/Advisor/board"}),
        ("ui.page_view", {"page.route": "/advisor/[ref"}),
        ("ui.page_view", {}),
        ("ui.friction", {"kind": "rage-quit", "element.id": "ADV-X"}),
        ("ui.friction", {"kind": "rage"}),
        ("ui.web_vital", {"metric": "fid", "reading": 10}),
        ("ui.web_vital", {"metric": "lcp", "reading": -1}),
        ("ui.web_vital", {"metric": "lcp", "reading": True}),
        ("ui.web_vital", {"metric": "lcp", "reading": math.nan}),
        ("ui.web_vital", {"metric": "lcp", "reading": math.inf}),
        ("ui.web_vital", {"metric": "lcp", "reading": "2500"}),
        ("ui.unknown", {"element.id": "ADV-X"}),
    ],
)
def test_an_event_that_breaks_the_schema_is_not_read(
    name: str, attributes: dict[str, object]
) -> None:
    assert parse_event(name, {**COMMON, **attributes}) is None


@pytest.mark.parametrize(
    "broken",
    [
        {"session.id": "not-hex"},
        {"session.id": "abc"},
        {"release": "latest"},
        {"release": "1.4"},
        {"device.type": "watch"},
        {"app.mode": "kiosk"},
    ],
)
def test_an_event_with_a_broken_common_attribute_is_not_read(broken: dict[str, str]) -> None:
    attributes = {**COMMON, **broken, "element.id": "ADV-X"}
    assert parse_event("ui.click", attributes) is None


def test_an_event_with_no_session_id_or_release_is_not_read() -> None:
    for missing in ("session.id", "release", "device.type"):
        attributes = {key: value for key, value in COMMON.items() if key != missing}
        assert parse_event("ui.click", {**attributes, "element.id": "ADV-X"}) is None


def test_a_missing_app_mode_is_the_browser() -> None:
    attributes = {key: value for key, value in COMMON.items() if key != "app.mode"}
    parsed = parse_event("ui.click", {**attributes, "element.id": "ADV-X"})
    assert parsed is not None
    assert parsed.app_mode == "browser"


def test_the_role_the_browser_claims_is_not_kept() -> None:
    parsed = parse_event("ui.click", {**COMMON, "user.role": "lead", "element.id": "ADV-X"})
    assert parsed is not None
    assert not hasattr(parsed, "role")


def test_a_batch_has_a_fixed_ceiling() -> None:
    assert MAX_BATCH_EVENTS == 50


# ---- the histogram -------------------------------------------------------------------------------


def test_the_budgets_are_the_web_vitals_good_thresholds() -> None:
    assert BUDGETS == {"lcp": 2500.0, "inp": 200.0, "cls": 0.1}


def test_a_budget_is_a_bucket_edge_so_exactly_on_budget_is_within_it() -> None:
    for measure, budget in BUDGETS.items():
        assert budget in EDGES[measure]
        buckets = [0] * BUCKET_COUNT
        buckets[bucket_of(measure, budget)] += 10
        assert percentile(buckets, measure, 0.75) == budget

        over = [0] * BUCKET_COUNT
        over[bucket_of(measure, budget * 1.01)] += 10
        reported = percentile(over, measure, 0.75)
        assert reported is not None
        assert reported > budget


def test_every_edge_set_fits_the_fixed_bucket_list() -> None:
    for edges in EDGES.values():
        assert list(edges) == sorted(edges)
        assert len(edges) + 1 <= BUCKET_COUNT


def test_a_value_above_the_last_edge_falls_in_the_overflow_bucket() -> None:
    assert bucket_of("lcp", 60_000) == len(EDGES["lcp"])
    assert bucket_of("lcp", 0) == 0


def test_the_percentile_walks_the_cumulative_count() -> None:
    buckets = [0] * BUCKET_COUNT
    buckets[bucket_of("lcp", 900)] = 60  # 1000
    buckets[bucket_of("lcp", 2400)] = 20  # 2500
    buckets[bucket_of("lcp", 3500)] = 20  # 4000

    assert percentile(buckets, "lcp", 0.5) == 1000
    assert percentile(buckets, "lcp", 0.75) == 2500
    assert percentile(buckets, "lcp", 0.95) == 4000


def test_the_overflow_bucket_reports_the_last_edge_and_still_breaks_the_budget() -> None:
    buckets = [0] * BUCKET_COUNT
    buckets[len(EDGES["lcp"])] = 10

    assert percentile(buckets, "lcp", 0.75) == EDGES["lcp"][-1]
    assert EDGES["lcp"][-1] > BUDGETS["lcp"]


def test_no_samples_give_no_percentile() -> None:
    assert percentile([0] * BUCKET_COUNT, "lcp", 0.75) is None


# ---- folding a batch into counters ---------------------------------------------------------------


def test_clicks_and_submits_are_interactions_and_nothing_else_is() -> None:
    batch = fold(
        "advisor",
        [
            event("ui.click", **{"element.id": "ADV-X-BTN"}),
            event("ui.click", **{"element.id": "ADV-X-BTN"}),
            event("ui.chip", **{"element.id": "ADV-X-BTN", "state": "true"}),
            event("ui.input", **{"element.id": "ADV-X-INPUT", "valid": True}),
            event("ui.toggle", **{"element.id": "ADV-X-BTN", "state": "on"}),
            event("ui.submit", **{"form.id": "ADV-FORM", "error_count": 0}),
        ],
    )

    counts = {row.element_id: row.count for row in batch.usage}
    assert counts == {"ADV-X-BTN": 2, "ADV-FORM": 1}
    assert {row.role for row in batch.usage} == {"advisor"}
    assert {row.session_id for row in batch.usage} == {SESSION}
    assert batch.releases[0].interactions == 3


def test_the_role_is_the_callers_not_the_browsers() -> None:
    batch = fold("lead", [event("ui.click", **{"element.id": "ADV-X-BTN", "user.role": "owner"})])

    assert batch.usage[0].role == "lead"


def test_a_friction_event_counts_once_whatever_its_burst_count() -> None:
    batch = fold(
        "advisor",
        [event("ui.friction", kind="rage", **{"element.id": "ADV-OPT-REQUEST-BTN", "count": 4})],
    )

    row = batch.friction[0]
    assert (row.element_id, row.kind, row.count, row.route) == (
        "ADV-OPT-REQUEST-BTN",
        "rage",
        1,
        "",
    )
    assert batch.releases[0].friction == 1


def test_friction_on_the_page_keeps_the_route_it_happened_on() -> None:
    batch = fold(
        "advisor",
        [
            event(
                "ui.friction",
                kind="u-turn",
                **{"element.id": "PAGE", "page.route": "/advisor/board"},
            ),
            event("ui.friction", kind="u-turn", **{"element.id": "PAGE"}),
        ],
    )

    routes = sorted(row.route for row in batch.friction)
    assert routes == ["/advisor/board", UNKNOWN_ROUTE]


def test_a_page_view_counts_a_session_on_the_route_and_a_view_on_the_release() -> None:
    batch = fold(
        "advisor",
        [
            event("ui.page_view", **{"page.route": "/advisor/board"}),
            event("ui.page_view", **{"page.route": "/advisor/board"}),
            event("ui.error_shown", **{"page.route": "/advisor/board", "error.code": "NETWORK"}),
        ],
    )

    route = batch.routes[0]
    assert (route.route, route.role, route.device, route.errors) == (
        "/advisor/board",
        "advisor",
        "desktop",
        1,
    )
    assert batch.releases[0].views == 2
    assert batch.releases[0].errors == 1


def test_a_web_vital_lands_in_one_bucket_of_its_measure_route_device_and_release() -> None:
    batch = fold(
        "advisor",
        [
            event("ui.web_vital", metric="lcp", reading=2400, **{"page.route": "/advisor/board"}),
            event("ui.web_vital", metric="lcp", reading=2400, **{"page.route": "/advisor/board"}),
            event("ui.web_vital", metric="cls", reading=0.04, **{"page.route": "/advisor/board"}),
        ],
    )

    by_measure = {row.measure: row for row in batch.measures}
    lcp = by_measure["lcp"]
    assert (lcp.route, lcp.device, lcp.release, lcp.samples) == (
        "/advisor/board",
        "desktop",
        "1.4.2",
        2,
    )
    assert lcp.buckets[bucket_of("lcp", 2400)] == 2
    assert sum(lcp.buckets) == 2
    assert len(lcp.buckets) == BUCKET_COUNT
    assert by_measure["cls"].buckets[bucket_of("cls", 0.04)] == 1


def test_a_web_vital_with_no_route_is_filed_under_the_unknown_route() -> None:
    batch = fold("advisor", [event("ui.web_vital", metric="inp", reading=120)])

    assert batch.measures[0].route == UNKNOWN_ROUTE


def test_two_sessions_in_one_batch_stay_two_rows_so_each_is_counted_once() -> None:
    other = parse_event(
        "ui.click", {**COMMON, "session.id": OTHER_SESSION, "element.id": "ADV-X-BTN"}
    )
    assert other is not None
    batch = fold("advisor", [event("ui.click", **{"element.id": "ADV-X-BTN"}), other])

    assert sorted(row.session_id for row in batch.usage) == sorted([SESSION, OTHER_SESSION])


def test_a_different_device_is_a_different_row() -> None:
    phone = parse_event("ui.click", {**COMMON, "device.type": "phone", "element.id": "ADV-X-BTN"})
    assert phone is not None
    batch = fold("advisor", [event("ui.click", **{"element.id": "ADV-X-BTN"}), phone])

    assert sorted(row.device for row in batch.usage) == ["desktop", "phone"]


def test_an_empty_batch_folds_to_nothing() -> None:
    batch = fold("advisor", [])

    assert not (batch.usage or batch.friction or batch.routes or batch.funnels or batch.measures)
    assert batch.releases == ()


def test_the_folded_rows_come_out_in_a_fixed_order() -> None:
    events = [
        event("ui.click", **{"element.id": "ADV-B-BTN"}),
        event("ui.click", **{"element.id": "ADV-A-BTN"}),
    ]

    assert fold("advisor", events) == fold("advisor", list(reversed(events)))
    assert [row.element_id for row in fold("advisor", events).usage] == ["ADV-A-BTN", "ADV-B-BTN"]


# ---- the funnels the browser can see -------------------------------------------------------------


def test_every_browser_funnel_is_one_of_the_spec_funnels_with_two_or_more_steps() -> None:
    for funnel, steps in BROWSER_FUNNELS.items():
        assert funnel in FUNNELS
        assert len(steps) >= 2
        names = [step.step for step in steps]
        assert len(set(names)) == len(names)
        for step in steps:
            assert step.routes
            for route in step.routes:
                assert re.fullmatch(r"/(?:[a-z0-9\-]|/|\[[A-Za-z0-9]+\])*", route), route


def test_a_route_belongs_to_at_most_one_step_of_a_funnel() -> None:
    for steps in BROWSER_FUNNELS.values():
        routes = [route for step in steps for route in step.routes]
        assert len(set(routes)) == len(routes)


def test_a_page_view_of_a_funnel_route_moves_the_session_to_that_step() -> None:
    batch = fold(
        "reporter",
        [
            event("ui.page_view", **{"page.route": "/setup"}),
            event("ui.page_view", **{"page.route": "/setup/home-screen"}),
            event("ui.page_view", **{"page.route": "/setup/pin"}),
        ],
    )

    row = next(item for item in batch.funnels if item.funnel == "reporter-set-up")
    steps = [step.step for step in BROWSER_FUNNELS["reporter-set-up"]]
    assert steps[row.top] == "PIN screen viewed"
    assert row.channel == "browser"
    assert row.role == "reporter"


def test_a_session_is_taken_as_far_as_its_furthest_step_in_the_batch() -> None:
    batch = fold(
        "reporter",
        [
            event("ui.page_view", **{"page.route": "/setup/pin"}),
            event("ui.page_view", **{"page.route": "/setup"}),
        ],
    )

    row = next(item for item in batch.funnels if item.funnel == "reporter-set-up")
    assert BROWSER_FUNNELS["reporter-set-up"][row.top].step == "PIN screen viewed"


def test_the_installed_app_is_its_own_channel() -> None:
    batch = fold(
        "reporter", [event("ui.page_view", **{"page.route": "/setup", "app.mode": "installed"})]
    )

    row = next(item for item in batch.funnels if item.funnel == "reporter-set-up")
    assert row.channel == "app"


def test_a_page_that_is_in_no_funnel_adds_no_funnel_row() -> None:
    batch = fold("advisor", [event("ui.page_view", **{"page.route": "/advisor/board"})])

    assert batch.funnels == ()


# ---- the pseudonymous session marker -------------------------------------------------------------


def test_the_marker_is_a_keyed_hash_that_does_not_contain_the_session_id() -> None:
    key = marker_key(
        b"k" * 32, "tenant-a", date(2026, 10, 29), "usage", ("ADV-X", "advisor"), SESSION
    )

    assert re.fullmatch(r"[0-9a-f]{32}", key)
    assert SESSION not in key


def test_the_marker_changes_with_every_input() -> None:
    base = (b"k" * 32, "tenant-a", date(2026, 10, 29), "usage", ("ADV-X", "advisor"), SESSION)
    keys = {marker_key(*base)}
    keys.add(marker_key(b"j" * 32, *base[1:]))
    keys.add(marker_key(base[0], "tenant-b", *base[2:]))
    keys.add(marker_key(base[0], base[1], date(2026, 10, 30), *base[3:]))
    keys.add(marker_key(base[0], base[1], base[2], "friction", *base[4:]))
    keys.add(marker_key(base[0], base[1], base[2], base[3], ("ADV-Y", "advisor"), base[5]))
    keys.add(marker_key(*base[:5], OTHER_SESSION))

    assert len(keys) == 7


def test_the_same_inputs_give_the_same_marker() -> None:
    args = (b"k" * 32, "tenant-a", date(2026, 10, 29), "route", ("/x", "advisor"), SESSION)

    assert marker_key(*args) == marker_key(*args)


def test_dimensions_that_run_together_do_not_collide() -> None:
    first = marker_key(b"k" * 32, "t", date(2026, 10, 29), "usage", ("AB", "C"), SESSION)
    second = marker_key(b"k" * 32, "t", date(2026, 10, 29), "usage", ("A", "BC"), SESSION)

    assert first != second
