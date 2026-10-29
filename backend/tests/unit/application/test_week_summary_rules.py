"""The pure rules of the week summary (U35): the London week, the suppression of small groups, the
percentages, the median, the on-time count and the time-back text. No Neo4j."""

from datetime import UTC, date, datetime, timedelta

import pytest

from diucs.application.actor import Actor
from diucs.application.use_cases.week_summary import (
    check_may_read,
    count_measure,
    london_week,
    median_measure,
    on_time_updates,
    percent_measure,
    time_back_text,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed

MONDAY = date(2026, 10, 19)


# --- the week ------------------------------------------------------------------------------------


def test_the_week_starts_at_monday_midnight_london_time_in_utc() -> None:
    start, _ = london_week(MONDAY)
    assert start == datetime(2026, 10, 18, 23, 0, tzinfo=UTC)  # BST: 00:00 London is 23:00 UTC


def test_the_week_ends_at_the_next_monday_midnight_london_time() -> None:
    _, end = london_week(MONDAY)
    assert end == datetime(2026, 10, 26, 0, 0, tzinfo=UTC)  # the clocks went back on 25 Oct


def test_the_week_that_crosses_the_clock_change_has_169_hours() -> None:
    start, end = london_week(MONDAY)
    assert end - start == timedelta(hours=169)


def test_a_sunday_evening_case_is_in_the_week_and_a_monday_just_after_midnight_is_not() -> None:
    start, end = london_week(MONDAY)
    # 23:30 London on Sunday 25 October is GMT, so 23:30 UTC.
    sunday_2330 = datetime(2026, 10, 25, 23, 30, tzinfo=UTC)
    assert start <= sunday_2330 < end
    monday_0010 = datetime(2026, 10, 26, 0, 10, tzinfo=UTC)  # 00:10 London on Monday 26 October
    assert not (start <= monday_0010 < end)


def test_a_week_that_does_not_start_on_a_monday_is_refused() -> None:
    with pytest.raises(ValueError):
        london_week(date(2026, 10, 20))


# --- small groups are hidden -------------------------------------------------------------------


@pytest.mark.parametrize("count", [0, 1, 9])
def test_a_count_under_ten_is_hidden(count: int) -> None:
    measure = count_measure(count, "referrals")
    assert measure.hidden is True
    assert measure.value is None


def test_a_count_of_exactly_ten_is_shown() -> None:
    measure = count_measure(10, "referrals")
    assert measure.hidden is False
    assert measure.value == 10


def test_email_updates_of_seven_are_hidden() -> None:
    assert count_measure(7, "email/link").hidden is True


def test_a_percentage_whose_base_is_under_ten_is_hidden() -> None:
    assert percent_measure(3, 9, "best fit not available").hidden is True


def test_a_percentage_is_rounded_to_a_whole_percent() -> None:
    # 115 of 640 is 17.97 per cent: 18 per cent (the week example, U35 test 1).
    measure = percent_measure(115, 640, "best fit not available")
    assert measure.hidden is False
    assert measure.value == 18


def test_on_time_is_412_of_448_prompts_which_is_92_per_cent() -> None:
    assert percent_measure(412, 448, "on time").value == 92


# --- the median ----------------------------------------------------------------------------------


def test_the_median_of_ten_or_more_confirmed_bookings_is_the_middle_value() -> None:
    values = [3, 4, 4, 4, 4, 4, 4, 5, 6, 8]
    assert median_measure(values, "median minutes").value == 4


def test_the_median_of_an_even_count_is_the_mean_of_the_middle_pair() -> None:
    values = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    assert median_measure(values, "median minutes").value == 6.5


def test_a_median_from_fewer_than_ten_bookings_is_hidden() -> None:
    measure = median_measure([3, 4, 4, 5, 6, 7, 8, 9, 10], "median minutes")
    assert measure.hidden is True and measure.value is None


# --- on time -------------------------------------------------------------------------------------

DUE = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


def test_a_report_exactly_at_reply_by_is_on_time() -> None:
    reply_by = DUE + timedelta(minutes=30)
    assert on_time_updates([("ucr-west", DUE)], [("ucr-west", reply_by)]) == 1


def test_a_report_one_second_after_reply_by_is_not_on_time() -> None:
    late = DUE + timedelta(minutes=30, seconds=1)
    assert on_time_updates([("ucr-west", DUE)], [("ucr-west", late)]) == 0


def test_a_report_for_another_service_does_not_count_for_the_prompt() -> None:
    assert on_time_updates([("ucr-west", DUE)], [("ucr-east", DUE)]) == 0


def test_a_report_before_any_prompt_of_its_service_is_not_counted() -> None:
    assert on_time_updates([("ucr-west", DUE)], [("ucr-west", DUE - timedelta(minutes=5))]) == 0


def test_a_report_answers_the_latest_prompt_at_or_before_it() -> None:
    earlier = DUE
    later = DUE + timedelta(hours=2)
    report = DUE + timedelta(hours=2, minutes=10)
    assert (
        on_time_updates([("ucr-west", earlier), ("ucr-west", later)], [("ucr-west", report)]) == 1
    )


# --- the time-back estimate ----------------------------------------------------------------------


def test_the_time_back_text_gives_the_minutes_per_call_and_says_estimate() -> None:
    text = time_back_text(412, 4)
    assert text == (
        "412 updates by text, app or email. Each replaces about one phone call of 4 minutes. "
        "Estimate."
    )


def test_an_unset_minutes_per_call_shows_a_placeholder_not_a_guess() -> None:
    assert "[x]" in time_back_text(412, None)
    assert "Estimate" in time_back_text(412, None)


def test_a_small_count_of_updates_in_the_time_back_text_is_not_stated() -> None:
    assert "7 updates" not in time_back_text(7, 4)
    assert "Fewer than 10 updates" in time_back_text(7, 4)


# --- who may read -----------------------------------------------------------------------------


@pytest.mark.parametrize("role", [Role.EXEC, Role.LEAD])
def test_the_exec_and_the_lead_may_read_the_week_summary(role: Role) -> None:
    check_may_read(
        Actor(
            role=role, practitioner_id="p", device_id=None, channel="web", service_ids=frozenset()
        )
    )


@pytest.mark.parametrize("role", [Role.REPORTER, Role.ADVISOR, Role.OWNER, Role.WALL])
def test_no_other_role_may_read_the_week_summary(role: Role) -> None:
    with pytest.raises(NotAllowed):
        check_may_read(
            Actor(
                role=role,
                practitioner_id="p",
                device_id=None,
                channel="web",
                service_ids=frozenset(),
            )
        )
