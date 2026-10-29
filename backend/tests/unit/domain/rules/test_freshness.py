"""Tests for diucs.domain.rules.freshness: overdue, data age and the stale warning (D05).

Rules: docs/spec/domain-rules.md 1.5 and the D05 prompt. The sample service is UCR West, Monday to
Friday 08:00 to 20:00 London local, due every 2 hours. 2026-10-23 is a Friday in British summer
time; the clocks go back on 2026-10-25, so Monday 2026-10-26 is on GMT (its first due is 08:00Z).
Every instant is compared as UTC (lesson L4). DEC-029 records the one case where the prompt's
expectation and the rule book differ (no report ever, before the first due on Monday).
"""

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Final

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from diucs.domain.codes import Cadence, Channel, Measure, ServiceCategory
from diucs.domain.model import tenant_policy
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from diucs.domain.rules import freshness as freshness_rules
from diucs.domain.rules.freshness import (
    STALE_WARNING_AFTER,
    Freshness,
    assess_freshness,
    data_age_text,
)
from diucs.domain.rules.london_time import london_to_utc, to_london
from diucs.domain.rules.schedule import due_times_on
from tests.support.policy_samples import policies, policy

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
    # DEC-029. The prompt expected "not overdue" at 06:30Z. Friday 19:00Z was due, its reply-by
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


def test_report_exactly_at_the_due_time_answers_it() -> None:
    # "No report has arrived at or after it": a report at 11:00Z answers the 11:00Z due.
    result = assess_freshness(UCR_WEST, utc(2026, 10, 23, 11, 0), utc(2026, 10, 23, 11, 31))
    assert result.overdue is False


def test_reply_by_exactly_now_is_not_yet_missed() -> None:
    # Reply-by is 11:30Z. "Before now" is strict, so at 11:30Z exactly it is not missed.
    result = assess_freshness(UCR_WEST, utc(2026, 10, 23, 9, 15), utc(2026, 10, 23, 11, 30))
    assert result.overdue is False


def test_one_microsecond_after_reply_by_is_overdue() -> None:
    now = utc(2026, 10, 23, 11, 30) + timedelta(microseconds=1)
    result = assess_freshness(UCR_WEST, utc(2026, 10, 23, 9, 15), now)
    assert result.overdue is True
    assert result.was_due == utc(2026, 10, 23, 11, 0)


# --- Tenant policy (TEN-021) ----------------------------------------------------------------

FRIDAY: Final = date(2026, 10, 23)  # British summer time: 10:00 London is 09:00Z
ONE_MICROSECOND_DELTA: Final = timedelta(microseconds=1)


def london(hour: int, minute: int = 0, extra: timedelta = timedelta(0)) -> datetime:
    return london_to_utc(FRIDAY, time(hour, minute)) + extra


def overdue_at(now: datetime, reply_window: timedelta) -> bool:
    last = london(8, 0)  # the last report: the 08:00 due was answered
    return assess_freshness(UCR_WEST, last, now, policy(reply_window=reply_window)).overdue


# Test 7. Boundaries: a due at 10:00 and a last report at 08:00 (London).


def test_default_window_10_30_exactly_is_not_overdue_and_one_microsecond_later_is() -> None:
    assert not overdue_at(london(10, 30), DEFAULT_POLICY.reply_window)
    assert overdue_at(london(10, 30, ONE_MICROSECOND_DELTA), DEFAULT_POLICY.reply_window)


def test_fifteen_minute_window_10_15_exactly_is_not_overdue_and_one_microsecond_later_is() -> None:
    fifteen = timedelta(minutes=15)
    assert not overdue_at(london(10, 15), fifteen)
    assert overdue_at(london(10, 15, ONE_MICROSECOND_DELTA), fifteen)


def test_10_20_is_overdue_under_fifteen_minutes_and_not_under_thirty() -> None:
    assert overdue_at(london(10, 20), timedelta(minutes=15))
    assert not overdue_at(london(10, 20), timedelta(minutes=30))


def test_with_a_fifteen_minute_window_the_10_00_due_is_missed_from_10_15_and_was_due() -> None:
    tenant = policy(reply_window=timedelta(minutes=15))
    result = assess_freshness(UCR_WEST, london(8, 0), london(10, 16), tenant)
    assert result.overdue
    assert result.was_due == london(10, 0)


# Test 8. Oracle property, independent of the code under test.


def oracle_overdue(
    prof: ServiceProfile,
    last: datetime | None,
    now: datetime,
    tenant: TenantPolicy,
) -> tuple[bool, datetime | None]:
    """Brute force: the latest due of the eight days before now that is missed and after last."""
    today = to_london(now).date()
    missed = [
        due
        for offset in range(-8, 1)
        for due in due_times_on(prof, today + timedelta(days=offset), tenant)
        if due + tenant.reply_window < now and (last is None or due > last)
    ]
    latest = max(missed, default=None)
    return latest is not None, latest


PROFILE_FACTORIES: Final = (
    lambda cadence: profile(cadence),
    lambda cadence: ServiceProfile(
        id="svc-afternoon",
        name="UCR West",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals in the next 2 hrs",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=cadence,
        available_times=(AvailableTime.weekdays(time(14, 30), time(20, 0)),),
        channel=Channel.TEXT,
    ),
    lambda cadence: ServiceProfile(
        id="svc-overnight",
        name="UCR West",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals in the next 2 hrs",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=cadence,
        available_times=(AvailableTime.every_day(time(10, 0), time(6, 0)),),
        channel=Channel.TEXT,
    ),
)


JITTER: Final = st.sampled_from(
    [-ONE_MICROSECOND_DELTA, timedelta(0), ONE_MICROSECOND_DELTA, timedelta(minutes=1)]
)


@settings(max_examples=200, deadline=None)
@given(
    tenant=policies(),
    factory=st.sampled_from(PROFILE_FACTORIES),
    cadence=st.sampled_from(list(Cadence)),
    day=st.dates(min_value=date(2026, 3, 20), max_value=date(2026, 11, 2)),
    pick=st.integers(min_value=0, max_value=12),
    jitter=JITTER,
    last_pick=st.one_of(st.none(), st.integers(min_value=0, max_value=12)),
)
def test_overdue_and_was_due_equal_the_brute_force_oracle(
    tenant: TenantPolicy,
    factory: Callable[[Cadence], ServiceProfile],
    cadence: Cadence,
    day: date,
    pick: int,
    jitter: timedelta,
    last_pick: int | None,
) -> None:
    """`now` sits at a due time plus the policy window, plus a jitter of a microsecond either side,
    so the boundary of every policy is exercised, not only the instants a uniform draw happens to
    hit. The last report is None or a due time before now."""
    prof = factory(cadence)
    dues = due_times_on(prof, day, tenant)
    assume(dues)
    now = dues[pick % len(dues)] + tenant.reply_window + jitter
    earlier = [due for due in due_times_on(prof, day, tenant) if due <= now]
    last = None if last_pick is None or not earlier else earlier[last_pick % len(earlier)]
    result = assess_freshness(prof, last, now, tenant)
    expected_overdue, expected_was_due = oracle_overdue(prof, last, now, tenant)
    assert result.overdue == expected_overdue
    assert result.was_due == expected_was_due


# Test 9. The stale warning: strictly older than the policy's limit.


def test_stale_warning_default_limit_is_two_hours_as_a_literal() -> None:
    assert timedelta(hours=2) == STALE_WARNING_AFTER
    assert STALE_WARNING_AFTER is DEFAULT_POLICY.stale_warning_after


def test_a_ninety_minute_old_report_warns_by_default_only_with_a_one_hour_limit() -> None:
    last = london(8, 0)
    now = last + timedelta(minutes=90)
    assert not assess_freshness(UCR_WEST, last, now).stale_warning
    tenant = policy(stale_warning_after=timedelta(hours=1))
    assert assess_freshness(UCR_WEST, last, now, tenant).stale_warning


@pytest.mark.parametrize("hours", [1, 2, 4])
def test_age_exactly_at_the_limit_does_not_warn(hours: int) -> None:
    last = london(8, 0)
    tenant = policy(stale_warning_after=timedelta(hours=hours))
    assert not assess_freshness(UCR_WEST, last, last + timedelta(hours=hours), tenant).stale_warning


@pytest.mark.parametrize("hours", [1, 2, 4])
def test_age_one_microsecond_over_the_limit_warns(hours: int) -> None:
    last = london(8, 0)
    tenant = policy(stale_warning_after=timedelta(hours=hours))
    later = last + timedelta(hours=hours, microseconds=1)
    assert assess_freshness(UCR_WEST, last, later, tenant).stale_warning


def test_the_module_constant_is_the_default_policy_value() -> None:
    assert freshness_rules.STALE_WARNING_AFTER is tenant_policy.DEFAULT_POLICY.stale_warning_after


# Test 10. The policy must be exactly a TenantPolicy.


class _SubclassedPolicy(TenantPolicy):
    """A subclass instance looks like a policy but is not exactly one."""


@pytest.mark.parametrize(
    "bad",
    [None, {"reply_window": 15}, _SubclassedPolicy()],
    ids=["none", "mapping", "subclass"],
)
def test_a_policy_that_is_not_exactly_a_tenant_policy_is_refused(bad: object) -> None:
    with pytest.raises(TypeError, match="a TenantPolicy is required"):
        assess_freshness(UCR_WEST, None, london(12, 0), bad)  # type: ignore[arg-type]


# Rule 4(d): the default argument equals the explicit default policy.


@settings(max_examples=80, deadline=None)
@given(
    cadence=st.sampled_from(list(Cadence)),
    now=st.datetimes(min_value=datetime(2026, 3, 20), max_value=datetime(2026, 11, 3)).map(
        lambda naive: naive.replace(tzinfo=UTC)
    ),
    age=st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=5)),
)
def test_the_default_argument_equals_the_default_policy(
    cadence: Cadence, now: datetime, age: timedelta
) -> None:
    prof = profile(cadence)
    last = now - age
    assert assess_freshness(prof, last, now) == assess_freshness(prof, last, now, DEFAULT_POLICY)
