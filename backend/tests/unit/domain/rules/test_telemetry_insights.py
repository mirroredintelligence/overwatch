"""The pure rules of the telemetry aggregates (O08): the funnels, the suppression floor and the
friction rate. The Neo4j side is in tests/integration/application/test_telemetry_aggregates.py."""

from dataclasses import fields
from datetime import date

import pytest

from diucs.domain.model.telemetry_aggregates import (
    ElementUsageDailyRow,
    FrictionDailyRow,
    FunnelDailyRow,
    QueryStatDailyRow,
    RouteDailyRow,
)
from diucs.domain.rules.telemetry_insights import (
    FRICTION_REVIEW_RATE,
    FUNNELS,
    RATE_WINDOW_DAYS,
    SUPPRESS_BELOW_SESSIONS,
    for_review,
    friction_figures,
    friction_rate,
    funnel_figures,
    is_suppressed,
    query_figures,
    rate_window_start,
    route_figures,
)


def test_the_seven_funnels_of_the_spec_are_fixed() -> None:
    assert list(FUNNELS) == [
        "reporter-set-up",
        "daily-capacity-loop",
        "booking-service-side",
        "advisor-call",
        "registration",
        "criteria-review",
        "coo-icb-adoption",
    ]


def test_each_funnel_has_its_steps_in_the_spec_order_and_a_defining_event() -> None:
    assert [step.step for step in FUNNELS["reporter-set-up"] if not step.branch][:3] == [
        "Invitation delivered",
        "Link opened",
        "Welcome started",
    ]
    assert len([step for step in FUNNELS["reporter-set-up"] if not step.branch]) == 13
    assert len([step for step in FUNNELS["daily-capacity-loop"] if not step.branch]) == 6
    assert len([step for step in FUNNELS["advisor-call"] if not step.branch]) == 9
    assert len([step for step in FUNNELS["registration"] if not step.branch]) == 11
    assert len([step for step in FUNNELS["criteria-review"] if not step.branch]) == 6
    assert len([step for step in FUNNELS["coo-icb-adoption"] if not step.branch]) == 6
    for steps in FUNNELS.values():
        for step in steps:
            assert step.step and step.event
            assert "." in step.event


def test_the_advisor_call_branches_are_marked_as_branches() -> None:
    branches = [step.step for step in FUNNELS["advisor-call"] if step.branch]
    assert branches == ["Phoned", "Clinical advice requested", "No service fits"]


def test_the_suppression_floor_is_ten_sessions() -> None:
    assert SUPPRESS_BELOW_SESSIONS == 10
    assert is_suppressed(7) is True
    assert is_suppressed(9) is True
    assert is_suppressed(10) is False


def test_a_friction_rate_is_events_over_interactions() -> None:
    assert friction_rate(41, 312) == pytest.approx(41 / 312)


def test_no_interactions_give_no_rate() -> None:
    assert friction_rate(0, 0) is None


def test_41_in_312_is_flagged_for_review_and_3_percent_is_not() -> None:
    assert FRICTION_REVIEW_RATE == 0.05
    assert for_review(41, 312) is True
    assert for_review(3, 100) is False


def test_exactly_five_percent_is_not_over_the_line() -> None:
    assert for_review(5, 100) is False
    assert for_review(6, 100) is True


def test_the_rate_window_is_seven_days_including_the_end_day() -> None:
    assert RATE_WINDOW_DAYS == 7
    assert rate_window_start(date(2026, 10, 29)) == date(2026, 10, 23)


# The read side: figures built from the stored rows, with the suppression floor applied.


DAY = date(2026, 10, 28)


def _funnel(
    step: str, entered: int, completed: int, day: date = DAY, branch: bool = False
) -> FunnelDailyRow:
    return FunnelDailyRow(
        day=day,
        funnel="reporter-set-up",
        step=step,
        role="reporter",
        channel="text",
        device="phone",
        entered=entered,
        completed=completed,
        median_ms=2000.0,
        branch=branch,
    )


def test_a_funnel_step_with_seven_sessions_reads_back_suppressed() -> None:
    figures = funnel_figures([_funnel("Welcome started", 7, 5)])

    assert len(figures) == 1
    assert figures[0].suppressed is True
    assert figures[0].entered is None
    assert figures[0].completed is None
    assert figures[0].conversion is None


def test_funnel_figures_add_up_the_days_and_keep_the_step_order() -> None:
    rows = [
        _funnel("Link opened", 30, 25, day=date(2026, 10, 27)),
        _funnel("Link opened", 20, 15, day=DAY),
        _funnel("Invitation delivered", 60, 58, day=DAY),
    ]

    figures = funnel_figures(rows)

    assert [figure.step for figure in figures] == ["Invitation delivered", "Link opened"]
    link = figures[1]
    assert link.entered == 50
    assert link.completed == 40
    assert link.conversion == pytest.approx(0.8)
    assert link.suppressed is False


def test_a_branch_is_marked_as_a_branch_in_its_figure() -> None:
    figures = funnel_figures([_funnel("Expired", 12, 12, branch=True)])

    assert figures[0].branch is True


def test_41_in_312_is_a_13_percent_friction_figure_flagged_for_review() -> None:
    usage = [ElementUsageDailyRow(DAY, "ADV-OPT-REQUEST-BTN", "advisor", "desktop", 312, 14)]
    friction = [
        FrictionDailyRow(DAY, "ADV-OPT-REQUEST-BTN", "rage", "advisor", "desktop", 312, 41, 14)
    ]

    figures = friction_figures(friction, usage)

    assert len(figures) == 1
    assert figures[0].rate == pytest.approx(41 / 312)
    assert figures[0].for_review is True
    assert figures[0].suppressed is False


def test_3_percent_friction_is_not_flagged() -> None:
    usage = [ElementUsageDailyRow(DAY, "ADV-REF-INPUT", "advisor", "desktop", 100, 12)]
    friction = [
        FrictionDailyRow(DAY, "ADV-REF-INPUT", "validation-loop", "advisor", "desktop", 100, 3, 12)
    ]

    figures = friction_figures(friction, usage)

    assert figures[0].for_review is False


def test_a_friction_group_under_ten_sessions_has_no_rate() -> None:
    usage = [ElementUsageDailyRow(DAY, "ADV-CALL-80-BTN", "advisor", "phone", 9, 2)]
    friction = [FrictionDailyRow(DAY, "ADV-CALL-80-BTN", "rage", "advisor", "phone", 9, 4, 2)]

    figures = friction_figures(friction, usage)

    assert figures[0].suppressed is True
    assert figures[0].rate is None
    assert figures[0].for_review is False


def test_a_route_under_ten_sessions_is_suppressed_and_one_over_is_not() -> None:
    small = RouteDailyRow(
        DAY,
        "/case/[ref]/options",
        "advisor",
        "desktop",
        400.0,
        700.0,
        1300.0,
        2200.0,
        190.0,
        0.05,
        2,
        6,
    )
    large = RouteDailyRow(
        DAY, "/board", "wall", "desktop", 310.0, 480.0, 820.0, 1900.0, 140.0, 0.02, 0, 22
    )

    figures = {figure.route: figure for figure in route_figures([small, large])}

    assert figures["/case/[ref]/options"].suppressed is True
    assert figures["/case/[ref]/options"].p95 is None
    assert figures["/board"].suppressed is False
    assert figures["/board"].p95 == 820.0


def test_query_figures_keep_the_p95_and_carry_no_text() -> None:
    rows = [QueryStatDailyRow(DAY, "Q-BOARD", 120, 38.0, 91.0, 1)]

    figures = query_figures(rows)

    assert figures[0].p95 == 91.0
    names = {field.name for field in fields(figures[0])}
    assert not names & {"cypher", "text", "statement", "parameters"}
