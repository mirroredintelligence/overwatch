"""Tests for diucs.domain.rules.freshness: overdue, data age and the stale warning (D05).

Rules: docs/spec/domain-rules.md 1.5 and the D05 prompt. The sample service is UCR West, Monday to
Friday 08:00 to 20:00 London local, due every 2 hours. 2026-10-23 is a Friday in British summer
time; the clocks go back on 2026-10-25, so Monday 2026-10-26 is on GMT (its first due is 08:00Z).
Every instant is compared as UTC (lesson L4). DEC-027 records the one case where the prompt's
expectation and the rule book differ (no report ever, before the first due on Monday).
"""

import re
from datetime import UTC, datetime, time, timedelta, timezone
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import Cadence, Channel, Measure, ServiceCategory
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.freshness import (
    STALE_WARNING_AFTER,
    Freshness,
    assess_freshness,
    data_age_text,
)

BST: Final = timezone(timedelta(hours=1))


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def profile(cadence: Cadence = Cadence.EVERY_2_HRS) -> ServiceProfile:
    return ServiceProfile(
        id="svc-ucr-west",
        name="UCR West",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals in the next 2 hrs",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=cadence,
        available_times=(AvailableTime.weekdays(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
    )


UCR_WEST: Final = profile()


def test_recent_report_is_fresh_with_no_warning() -> None:
    # Friday 2026-10-23, 14:03 BST and 14:12 BST. The 14:00 BST due (13:00Z) was answered.
    result = assess_freshness(UCR_WEST, utc(2026, 10, 23, 13, 3), utc(2026, 10, 23, 13, 12))
    assert result == Freshness(
        overdue=False, age=timedelta(minutes=9), stale_warning=False, was_due=None
    )


def test_due_is_not_overdue_until_its_reply_by_has_passed() -> None:
    # Due 11:00Z (12:00 BST). Last report 09:15Z, after the 09:00Z due. Reply-by is 11:30Z.
    result = assess_freshness(UCR_WEST, utc(2026, 10, 23, 9, 15), utc(2026, 10, 23, 11, 29))
    assert result.overdue is False
    assert result.was_due is None
    assert result.age == timedelta(hours=2, minutes=14)
    assert result.stale_warning is True


def test_overdue_once_reply_by_has_passed_with_was_due_the_missed_due() -> None:
    result = assess_freshness(UCR_WEST, utc(2026, 10, 23, 9, 15), utc(2026, 10, 23, 11, 31))
    assert result.overdue is True
    assert result.was_due == utc(2026, 10, 23, 11, 0)


def test_report_after_the_due_clears_it() -> None:
    # Same as above but the report arrives at 11:06Z, after the 11:00Z due.
    result = assess_freshness(UCR_WEST, utc(2026, 10, 23, 11, 6), utc(2026, 10, 23, 11, 31))
    assert result.overdue is False
    assert result.was_due is None


def test_virtual_ward_example_is_overdue_from_the_missed_12_00_bst_due() -> None:
    # Last report 10:00 BST, now 14:10 BST. The 12:00 BST due was missed. The 14:00 BST due's
    # reply-by (14:30 BST) has not passed, but overdue stays set from the earlier miss.
    result = assess_freshness(UCR_WEST, utc(2026, 10, 23, 9, 0), utc(2026, 10, 23, 13, 10))
    assert result.overdue is True
    assert result.was_due == utc(2026, 10, 23, 11, 0)
    assert result.age == timedelta(hours=4, minutes=10)


def test_weekend_gap_is_not_overdue_before_monday_reply_by_and_overdue_after() -> None:
    # Friday's last due is 20:00 BST (19:00Z); the report at 19:05Z answers it.
    last = utc(2026, 10, 23, 19, 5)
    before = assess_freshness(UCR_WEST, last, utc(2026, 10, 26, 7, 31))
    assert before.overdue is False
    assert before.was_due is None

    # Monday's first due is 08:00Z (GMT). Its reply-by 08:30Z has passed at 08:31Z.
    after = assess_freshness(UCR_WEST, last, utc(2026, 10, 26, 8, 31))
    assert after.overdue is True
    assert after.was_due == utc(2026, 10, 26, 8, 0)


def test_no_report_ever_is_overdue_with_no_age() -> None:
    result = assess_freshness(UCR_WEST, None, utc(2026, 10, 26, 7, 31))
    assert result.overdue is True
    assert result.age is None
    assert result.stale_warning is False


def test_no_report_ever_before_monday_first_due_is_overdue_from_friday() -> None:
    # DEC-027. The prompt expected "not overdue" at 06:30Z. Friday 19:00Z was due, its reply-by
    # has passed, and with no report ever any missed due counts (domain-rules 1.5).
    result = assess_freshness(UCR_WEST, None, utc(2026, 10, 26, 6, 30))
    assert result.overdue is True
    assert result.was_due == utc(2026, 10, 23, 19, 0)
    assert result.age is None


def test_report_2_hrs_10_min_old_after_the_current_due_is_not_overdue_but_warns() -> None:
    # Last report 11:20Z, 2 hrs 10 min before now (13:30Z). It is after the 11:00Z due, which is
    # therefore answered. The 13:00Z due's reply-by (13:30Z) is not before now, so not overdue.
    result = assess_freshness(UCR_WEST, utc(2026, 10, 23, 11, 20), utc(2026, 10, 23, 13, 30))
    assert result.overdue is False
    assert result.age == timedelta(hours=2, minutes=10)
    assert result.stale_warning is True


def test_exactly_two_hours_old_has_no_stale_warning() -> None:
    result = assess_freshness(UCR_WEST, utc(2026, 10, 23, 11, 0), utc(2026, 10, 23, 13, 0))
    assert result.age == STALE_WARNING_AFTER
    assert result.stale_warning is False
    assert result.overdue is False


def test_one_second_over_two_hours_has_the_stale_warning() -> None:
    result = assess_freshness(UCR_WEST, utc(2026, 10, 23, 11, 0), utc(2026, 10, 23, 13, 0, 1))
    assert result.overdue is False
    assert result.stale_warning is True


def test_a_london_local_report_time_gives_the_same_result_as_utc() -> None:
    # 14:03 BST is 13:03Z. Compared as wall clock this would look an hour different.
    local_report = datetime(2026, 10, 23, 14, 3, tzinfo=BST)
    assert assess_freshness(UCR_WEST, local_report, utc(2026, 10, 23, 13, 12)) == (
        assess_freshness(UCR_WEST, utc(2026, 10, 23, 13, 3), utc(2026, 10, 23, 13, 12))
    )


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError):
        assess_freshness(UCR_WEST, utc(2026, 10, 23, 13, 3), datetime(2026, 10, 23, 13, 12))


def test_naive_last_report_is_rejected() -> None:
    with pytest.raises(ValueError):
        assess_freshness(UCR_WEST, datetime(2026, 10, 23, 13, 3), utc(2026, 10, 23, 13, 12))


def test_report_after_now_is_rejected() -> None:
    with pytest.raises(ValueError):
        assess_freshness(UCR_WEST, utc(2026, 10, 23, 13, 13), utc(2026, 10, 23, 13, 12))


@pytest.mark.parametrize(
    ("age", "text"),
    [
        (timedelta(seconds=30), "just now"),
        (timedelta(0), "just now"),
        (timedelta(minutes=1), "1 min ago"),
        (timedelta(minutes=9), "9 min ago"),
        (timedelta(minutes=59, seconds=59), "59 min ago"),
        (timedelta(minutes=60), "1 hr ago"),
        (timedelta(minutes=65), "1 hr 5 min ago"),
        (timedelta(minutes=130), "2 hrs 10 min ago"),
        (timedelta(minutes=180), "3 hrs ago"),
        (timedelta(minutes=250), "4 hrs 10 min ago"),
    ],
)
def test_data_age_text_examples(age: timedelta, text: str) -> None:
    assert data_age_text(age) == text


def test_data_age_text_rejects_a_negative_age() -> None:
    with pytest.raises(ValueError):
        data_age_text(timedelta(minutes=-1))


AGE_TEXT: Final = re.compile(
    r"^(just now|\d+ min ago|1 hr ago|\d+ hrs ago|1 hr \d+ min ago|\d+ hrs \d+ min ago)$"
)


@given(st.integers(min_value=0, max_value=60 * 60 * 48))
def test_data_age_text_is_always_one_of_the_documented_shapes(seconds: int) -> None:
    text = data_age_text(timedelta(seconds=seconds))
    assert AGE_TEXT.match(text), text
    if seconds < 60:
        assert text == "just now"
    elif seconds < 3600:
        assert text == f"{seconds // 60} min ago"


@given(st.integers(min_value=0, max_value=60 * 60 * 48))
def test_stale_warning_is_exactly_age_over_two_hours(seconds: int) -> None:
    now = utc(2026, 10, 23, 13, 0)
    result = assess_freshness(UCR_WEST, now - timedelta(seconds=seconds), now)
    assert result.age == timedelta(seconds=seconds)
    assert result.stale_warning is (seconds > 2 * 3600)


@given(st.integers(min_value=0, max_value=60 * 60 * 72))
def test_overdue_names_a_due_after_the_last_report_and_past_its_reply_by(
    seconds_since_report: int,
) -> None:
    now = utc(2026, 10, 26, 9, 0)
    last = now - timedelta(seconds=seconds_since_report)
    result = assess_freshness(UCR_WEST, last, now)
    if result.overdue:
        assert result.was_due is not None
        assert result.was_due > last
        assert result.was_due + timedelta(minutes=30) < now
    else:
        assert result.was_due is None
