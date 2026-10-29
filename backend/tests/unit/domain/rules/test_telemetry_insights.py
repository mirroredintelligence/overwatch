"""The pure rules of the telemetry aggregates (O08): the funnels, the suppression floor and the
friction rate. The Neo4j side is in tests/integration/application/test_telemetry_aggregates.py."""

from datetime import date

import pytest

from diucs.domain.rules.telemetry_insights import (
    FRICTION_REVIEW_RATE,
    FUNNELS,
    RATE_WINDOW_DAYS,
    SUPPRESS_BELOW_SESSIONS,
    for_review,
    friction_rate,
    is_suppressed,
    rate_window_start,
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
