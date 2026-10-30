"""The remaining rules take the tenant's policy (TEN-064, DEC-134 item 14).

Thirteen functions in seven rule modules gain a trailing `policy: TenantPolicy = DEFAULT_POLICY`
(the shape TEN-021 used): booking timers, report flags, multi-service grouping, the criteria review
reminder, alert defaults and critical kinds, the clinical take timeout and the re-verification
interval. The default equals today's constant, a non-default policy changes the result as its field
says, the bounds hold to the minute, a policy that is not exactly a `TenantPolicy` is refused, and
no call can see another call's policy. Pure: no Neo4j, no clock, no tenant lookup. Sample values
only.
"""

import ast
import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.domain.codes import AlertKind, ReportFlagReason, Status
from diucs.domain.errors import Conflict, NotAllowed, ValidationFailed
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, FIELD_BOUNDS, TenantPolicy
from diucs.domain.rules import (
    alerts,
    booking_rules,
    clinical_queue,
    criteria_workflow,
    identity_policy,
    multi_service,
    report_flags,
)
from diucs.domain.rules.alerts import (
    CRITICAL_KINDS,
    Alert,
    AlertPreferences,
    alert_for_pressure,
    alerts_for_change,
    default_preferences,
    not_updated_alert_due,
)
from diucs.domain.rules.booking_rules import (
    BOOKING_REPLY_WINDOW,
    PHONE_PROMPT_AFTER,
    booking_reply_by,
    phone_prompt_at,
)
from diucs.domain.rules.clinical_queue import TAKE_TIMEOUT, give_advice, return_if_idle, take
from diucs.domain.rules.criteria_workflow import REVIEW_REMINDER_BEFORE, review_reminder_due
from diucs.domain.rules.identity_policy import REVERIFY_EVERY, needs_reverification
from diucs.domain.rules.multi_service import (
    GROUP_WINDOW,
    MAX_SERVICES_PER_PHONE,
    group_due,
    phone_overloaded,
)
from diucs.domain.rules.pressure import Pressure
from diucs.domain.rules.report_flags import (
    MANY_CHANGES_COUNT,
    MANY_CHANGES_WINDOW,
    PHONED_WINDOW,
    flags_for_report,
)
from tests.support.policy_samples import policies, policy
from tests.unit.domain.model.test_criteria import ucr_west
from tests.unit.domain.rules.test_clinical_queue import request as clinical_request
from tests.unit.domain.rules.test_report_flags import phoned, rpt, ward_a

MIN = timedelta(minutes=1)
DAY = timedelta(days=1)
T0 = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
SERVICE = "svc-0001"
MANY = ReportFlagReason.MANY_CHANGES
DIFFERS = ReportFlagReason.DIFFERS_FROM_PHONED


def bounds(field: str) -> tuple[Any, Any]:
    return FIELD_BOUNDS[field]


# ---------------------------------------------------------------- 1. the default is today's value


def test_every_module_constant_is_the_default_policys_own_value() -> None:
    assert BOOKING_REPLY_WINDOW == DEFAULT_POLICY.booking_reply_window == timedelta(minutes=10)
    assert PHONE_PROMPT_AFTER == DEFAULT_POLICY.booking_phone_prompt_after == 5 * MIN
    assert MANY_CHANGES_WINDOW == DEFAULT_POLICY.many_changes_window == 5 * MIN
    assert MANY_CHANGES_COUNT == DEFAULT_POLICY.many_changes_count == 3
    assert PHONED_WINDOW == DEFAULT_POLICY.phoned_window == 60 * MIN
    assert GROUP_WINDOW == DEFAULT_POLICY.group_window == 10 * MIN
    assert MAX_SERVICES_PER_PHONE == DEFAULT_POLICY.max_services_per_phone == 3
    assert REVIEW_REMINDER_BEFORE == DEFAULT_POLICY.criteria_reminder_before == 14 * DAY
    assert TAKE_TIMEOUT == DEFAULT_POLICY.clinical_take_timeout == 10 * MIN
    assert REVERIFY_EVERY == DEFAULT_POLICY.reverify_every == 30 * DAY
    assert DEFAULT_POLICY.critical_alert_kinds == CRITICAL_KINDS
    assert frozenset({AlertKind.SERVICE_CLOSED, AlertKind.SYSTEM_PRESSURE}) == CRITICAL_KINDS


def test_the_module_constants_are_the_default_policys_objects() -> None:
    # `Final = DEFAULT_POLICY.<field>`: the number is written once, in tenant_policy.py (DEC-233).
    assert BOOKING_REPLY_WINDOW is DEFAULT_POLICY.booking_reply_window
    assert PHONE_PROMPT_AFTER is DEFAULT_POLICY.booking_phone_prompt_after
    assert MANY_CHANGES_WINDOW is DEFAULT_POLICY.many_changes_window
    assert PHONED_WINDOW is DEFAULT_POLICY.phoned_window
    assert GROUP_WINDOW is DEFAULT_POLICY.group_window
    assert REVIEW_REMINDER_BEFORE is DEFAULT_POLICY.criteria_reminder_before
    assert TAKE_TIMEOUT is DEFAULT_POLICY.clinical_take_timeout
    assert REVERIFY_EVERY is DEFAULT_POLICY.reverify_every
    assert CRITICAL_KINDS is DEFAULT_POLICY.critical_alert_kinds


def test_booking_timers_default_equals_the_constant_and_the_explicit_default() -> None:
    assert booking_reply_by(T0) == T0 + BOOKING_REPLY_WINDOW == booking_reply_by(T0, DEFAULT_POLICY)
    assert phone_prompt_at(T0) == T0 + PHONE_PROMPT_AFTER == phone_prompt_at(T0, DEFAULT_POLICY)


# ---------------------------------------------------------------- booking timers (2, 3, 6, 13)


def test_a_booking_policy_moves_both_timers() -> None:
    chosen = policy(booking_reply_window=15 * MIN, booking_phone_prompt_after=7 * MIN)

    assert booking_reply_by(T0, chosen) == T0 + 15 * MIN
    assert phone_prompt_at(T0, chosen) == T0 + 7 * MIN


def test_the_booking_timers_at_the_bounds_are_exact() -> None:
    reply_low, reply_high = bounds("booking_reply_window")
    prompt_low, prompt_high = bounds("booking_phone_prompt_after")
    smallest = policy(booking_reply_window=reply_low, booking_phone_prompt_after=prompt_low)
    largest = policy(booking_reply_window=reply_high, booking_phone_prompt_after=prompt_high)

    assert booking_reply_by(T0, smallest) == T0 + reply_low
    assert phone_prompt_at(T0, smallest) == T0 + prompt_low
    assert booking_reply_by(T0, largest) == T0 + reply_high
    assert phone_prompt_at(T0, largest) == T0 + prompt_high


def test_the_two_booking_timers_are_not_swapped() -> None:
    chosen = policy(booking_reply_window=20 * MIN, booking_phone_prompt_after=3 * MIN)

    assert booking_reply_by(T0, chosen) - phone_prompt_at(T0, chosen) == 17 * MIN


@given(chosen=policies())
def test_the_phone_prompt_is_always_before_the_reply_by_time(chosen: TenantPolicy) -> None:
    assert phone_prompt_at(T0, chosen) < booking_reply_by(T0, chosen)


@given(first=policies(), second=policies())
def test_a_longer_booking_window_never_gives_an_earlier_reply_by(
    first: TenantPolicy, second: TenantPolicy
) -> None:
    short, long = sorted((first, second), key=lambda p: p.booking_reply_window)

    assert booking_reply_by(T0, short) <= booking_reply_by(T0, long)


# ---------------------------------------------------------------- report flags (2, 3, 7, 13)


def flags_with(new: Any, recent: Sequence[Any], chosen: TenantPolicy | None = None) -> Any:
    if chosen is None:
        return flags_for_report(new, recent, ward_a())
    return flags_for_report(new, recent, ward_a(), chosen)


NEW_AT = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)


def test_a_three_minute_window_flags_at_exactly_three_minutes_and_not_a_microsecond_past() -> None:
    chosen = policy(many_changes_window=3 * MIN, many_changes_count=2)

    inside = [rpt(4, NEW_AT - 3 * MIN)]
    outside = [rpt(4, NEW_AT - 3 * MIN - timedelta(microseconds=1))]

    assert MANY in flags_with(rpt(5, NEW_AT), inside, chosen)
    assert MANY not in flags_with(rpt(5, NEW_AT), outside, chosen)


def test_a_count_of_two_flags_one_earlier_report_that_the_default_would_not() -> None:
    earlier = [rpt(4, NEW_AT - MIN)]

    assert MANY not in flags_with(rpt(5, NEW_AT), earlier)
    assert MANY in flags_with(rpt(5, NEW_AT), earlier, policy(many_changes_count=2))


def test_a_count_of_ten_needs_nine_earlier_reports() -> None:
    chosen = policy(many_changes_count=10)
    nine = [rpt(i, NEW_AT - MIN * (i + 1) / 10) for i in range(9)]

    assert MANY in flags_with(rpt(5, NEW_AT), nine, chosen)
    assert MANY not in flags_with(rpt(5, NEW_AT), nine[:8], chosen)


def test_the_many_changes_window_at_both_bounds() -> None:
    low, high = bounds("many_changes_window")
    one = [rpt(4, NEW_AT - low)]
    far = [rpt(4, NEW_AT - high)]

    assert MANY in flags_with(
        rpt(5, NEW_AT), one, policy(many_changes_window=low, many_changes_count=2)
    )
    assert MANY in flags_with(
        rpt(5, NEW_AT), far, policy(many_changes_window=high, many_changes_count=2)
    )
    assert MANY not in flags_with(
        rpt(5, NEW_AT),
        [rpt(4, NEW_AT - low - timedelta(seconds=1))],
        policy(many_changes_window=low, many_changes_count=2),
    )


def test_the_phoned_window_follows_the_policy_at_both_edges() -> None:
    chosen = policy(phoned_window=15 * MIN)

    assert DIFFERS in flags_with(rpt(5, NEW_AT), [phoned(2, NEW_AT - 15 * MIN)], chosen)
    assert DIFFERS not in flags_with(
        rpt(5, NEW_AT), [phoned(2, NEW_AT - 15 * MIN - timedelta(seconds=1))], chosen
    )
    # The default window of 60 minutes still flags the same report.
    assert DIFFERS in flags_with(rpt(5, NEW_AT), [phoned(2, NEW_AT - 30 * MIN)])


def test_the_phoned_window_at_both_bounds() -> None:
    low, high = bounds("phoned_window")

    assert DIFFERS in flags_with(
        rpt(5, NEW_AT), [phoned(2, NEW_AT - low)], policy(phoned_window=low)
    )
    assert DIFFERS in flags_with(
        rpt(5, NEW_AT), [phoned(2, NEW_AT - high)], policy(phoned_window=high)
    )


def test_a_report_of_another_service_never_counts_whatever_the_policy() -> None:
    chosen = policy(many_changes_count=2, many_changes_window=30 * MIN)
    other = [rpt(4, NEW_AT - MIN, service_id="svc-elsewhere")]

    assert flags_with(rpt(5, NEW_AT), other, chosen) == []


def test_the_two_flag_fields_are_not_swapped() -> None:
    # Window 3 minutes, count 2: a count read as the window (or the reverse) changes the answer.
    chosen = policy(many_changes_window=3 * MIN, many_changes_count=2)

    assert MANY in flags_with(rpt(5, NEW_AT), [rpt(4, NEW_AT - 2 * MIN)], chosen)
    assert MANY not in flags_with(rpt(5, NEW_AT), [rpt(4, NEW_AT - 4 * MIN)], chosen)


@given(
    gaps=st.lists(st.integers(min_value=0, max_value=40 * 60), min_size=1, max_size=8),
    first=policies(),
    second=policies(),
)
@settings(max_examples=150)
def test_a_longer_window_never_flags_fewer_and_a_higher_count_never_flags_more(
    gaps: list[int], first: TenantPolicy, second: TenantPolicy
) -> None:
    earlier = [rpt(i, NEW_AT - timedelta(seconds=gap)) for i, gap in enumerate(gaps)]
    short, long = sorted((first, second), key=lambda p: p.many_changes_window)
    low, high = sorted((first, second), key=lambda p: p.many_changes_count)
    same_count = policy(
        many_changes_window=short.many_changes_window, many_changes_count=low.many_changes_count
    )
    longer = policy(
        many_changes_window=long.many_changes_window, many_changes_count=low.many_changes_count
    )
    stricter = policy(
        many_changes_window=short.many_changes_window, many_changes_count=high.many_changes_count
    )

    if MANY in flags_with(rpt(99, NEW_AT), earlier, same_count):
        assert MANY in flags_with(rpt(99, NEW_AT), earlier, longer)
    if MANY in flags_with(rpt(99, NEW_AT), earlier, stricter):
        assert MANY in flags_with(rpt(99, NEW_AT), earlier, same_count)


# ---------------------------------------------------------------- multi-service (2, 3, 8, 13)

TEN = datetime(2026, 10, 25, 10, 0, tzinfo=UTC)


def due_at(*offsets: int) -> list[tuple[str, str, datetime]]:
    return [(f"s{n}", f"Service {n}", TEN + offset * MIN) for n, offset in enumerate(offsets)]


def shapes(groups: Any) -> list[list[str]]:
    return [[item.service_id for item in group.items] for group in groups]


def test_the_default_splits_the_third_item_off_and_a_fifteen_minute_window_does_not() -> None:
    items = due_at(0, 5, 12)

    assert shapes(group_due(items)) == [["s0", "s1"], ["s2"]]
    assert shapes(group_due(items, DEFAULT_POLICY)) == [["s0", "s1"], ["s2"]]
    assert shapes(group_due(items, policy(group_window=15 * MIN))) == [["s0", "s1", "s2"]]


def test_the_group_window_is_exclusive_at_its_end_for_any_policy() -> None:
    for window in (5, 10, 15, 20):
        chosen = policy(group_window=window * MIN)

        assert shapes(group_due(due_at(0, window - 1), chosen)) == [["s0", "s1"]]
        assert shapes(group_due(due_at(0, window), chosen)) == [["s0"], ["s1"]]


def test_the_group_window_at_both_bounds() -> None:
    low, high = bounds("group_window")

    assert shapes(group_due(due_at(0, 4), policy(group_window=low))) == [["s0", "s1"]]
    assert shapes(group_due(due_at(0, 5), policy(group_window=low))) == [["s0"], ["s1"]]
    assert shapes(group_due(due_at(0, 19), policy(group_window=high))) == [["s0", "s1"]]
    assert shapes(group_due(due_at(0, 20), policy(group_window=high))) == [["s0"], ["s1"]]


def test_a_grouped_prompts_reply_by_follows_the_tenants_reply_window() -> None:
    chosen = policy(reply_window=45 * MIN, reminder_after=45 * MIN)

    (group,) = group_due(due_at(0, 3), chosen)

    assert group.reply_by == TEN + 45 * MIN
    (default_group,) = group_due(due_at(0, 3))
    assert default_group.reply_by == TEN + 30 * MIN


def test_the_group_is_anchored_on_its_first_item_not_chained() -> None:
    # 0, 6, 12 under the default: 12 is past 0 + 10 even though it is 6 after the item before it.
    assert shapes(group_due(due_at(0, 6, 12))) == [["s0", "s1"], ["s2"]]


def test_the_phone_load_limit_follows_the_policy() -> None:
    chosen = policy(max_services_per_phone=4)

    assert phone_overloaded(4, chosen) is False
    assert phone_overloaded(5, chosen) is True
    assert phone_overloaded(3) is False and phone_overloaded(4) is True
    assert (
        phone_overloaded(3, DEFAULT_POLICY) is False and phone_overloaded(4, DEFAULT_POLICY) is True
    )


def test_the_phone_load_limit_at_both_bounds() -> None:
    low, high = bounds("max_services_per_phone")

    assert phone_overloaded(low, policy(max_services_per_phone=low)) is False
    assert phone_overloaded(low + 1, policy(max_services_per_phone=low)) is True
    assert phone_overloaded(high, policy(max_services_per_phone=high)) is False
    assert phone_overloaded(high + 1, policy(max_services_per_phone=high)) is True


def test_a_negative_count_is_still_refused_whatever_the_policy() -> None:
    with pytest.raises(ValidationFailed):
        phone_overloaded(-1, policy(max_services_per_phone=6))


def test_twenty_seven_items_in_one_window_are_still_refused() -> None:
    items = [(f"s{n}", f"Service {n:02d}", TEN) for n in range(27)]

    with pytest.raises(ValidationFailed):
        group_due(items, policy(group_window=20 * MIN))


def test_a_service_twice_is_still_refused() -> None:
    with pytest.raises(ValidationFailed):
        group_due([("s", "A", TEN), ("s", "B", TEN)], policy(group_window=20 * MIN))


@given(
    offsets=st.lists(st.integers(min_value=0, max_value=90), min_size=1, max_size=20, unique=True),
    chosen=policies(),
)
def test_grouping_partitions_its_input_in_due_order(
    offsets: list[int], chosen: TenantPolicy
) -> None:
    groups = group_due(due_at(*offsets), chosen)

    flat = [item.service_id for group in groups for item in group.items]
    assert sorted(flat) == sorted(f"s{n}" for n in range(len(offsets)))
    assert [group.due for group in groups] == sorted(group.due for group in groups)
    for group in groups:
        assert len(group.items) <= 26
        assert all(item.due - group.due < chosen.group_window for item in group.items)


# ---------------------------------------------------------------- criteria reminder (2, 3, 9)

REVIEW_BY = date(2026, 12, 12)


@pytest.mark.parametrize("days", [7, 14, 30])
def test_the_reminder_is_due_from_the_policys_days_before_review_by(days: int) -> None:
    chosen = policy(criteria_reminder_before=days * DAY)
    criteria = ucr_west(review_by=REVIEW_BY)
    boundary = REVIEW_BY - timedelta(days=days)

    assert review_reminder_due(criteria, boundary, chosen) is True
    assert review_reminder_due(criteria, boundary - DAY, chosen) is False
    assert review_reminder_due(criteria, REVIEW_BY, chosen) is True
    assert review_reminder_due(criteria, REVIEW_BY + DAY, chosen) is False


def test_the_default_reminder_is_unchanged() -> None:
    criteria = ucr_west(review_by=REVIEW_BY)
    for today in (date(2026, 11, 27), date(2026, 11, 28), REVIEW_BY, REVIEW_BY + DAY):
        assert review_reminder_due(criteria, today) == review_reminder_due(
            criteria, today, DEFAULT_POLICY
        )
    assert review_reminder_due(criteria, date(2026, 11, 28)) is True
    assert review_reminder_due(criteria, date(2026, 11, 27)) is False


def test_after_review_by_the_reminder_is_false_but_the_review_is_overdue() -> None:
    criteria = ucr_west(review_by=REVIEW_BY)
    later = REVIEW_BY + DAY

    assert review_reminder_due(criteria, later, policy(criteria_reminder_before=30 * DAY)) is False
    assert criteria_workflow.is_review_overdue(criteria, later) is True


def test_a_datetime_is_still_refused_as_today_under_a_policy() -> None:
    with pytest.raises(ValidationFailed):
        review_reminder_due(
            ucr_west(review_by=REVIEW_BY),
            datetime(2026, 12, 1, tzinfo=UTC),  # type: ignore[arg-type]
            policy(criteria_reminder_before=7 * DAY),
        )


# ---------------------------------------------------------------- alerts (2, 3, 10)

ALERT_AT = datetime(2026, 7, 10, 13, 0, tzinfo=UTC)


def test_default_preferences_equal_the_rule_book_and_the_default_policy() -> None:
    expected = AlertPreferences(
        kinds=frozenset(AlertKind),
        not_updated_hours=2,
        quiet_hours=None,
        quiet_critical_only=True,
        ack_minutes=15,
    )

    assert default_preferences() == expected == default_preferences(DEFAULT_POLICY)
    assert default_preferences().kinds == DEFAULT_POLICY.alert_default_kinds


def test_a_tenants_alert_defaults_start_a_new_users_preferences() -> None:
    chosen = policy(
        alert_default_kinds=frozenset({AlertKind.SERVICE_CLOSED, AlertKind.NOT_UPDATED}),
        alert_default_not_updated_hours=4,
    )

    preferences = default_preferences(chosen)

    assert preferences.kinds == frozenset({AlertKind.SERVICE_CLOSED, AlertKind.NOT_UPDATED})
    assert preferences.not_updated_hours == 4
    # The rest stays fixed: quiet hours none, critical only, acknowledge in 15 minutes.
    assert (preferences.quiet_hours, preferences.quiet_critical_only, preferences.ack_minutes) == (
        None,
        True,
        15,
    )


def test_the_alert_default_hours_follow_the_policy_at_both_choices() -> None:
    assert default_preferences(policy(alert_default_not_updated_hours=2)).not_updated_hours == 2
    assert default_preferences(policy(alert_default_not_updated_hours=4)).not_updated_hours == 4


def test_critical_follows_the_policys_critical_kinds_for_service_alerts() -> None:
    only_over_capacity = policy(critical_alert_kinds=frozenset({AlertKind.OVER_CAPACITY}))

    (closed,) = alerts_for_change(
        SERVICE, Status.ACCEPTING, Status.NOT_ACCEPTING, True, ALERT_AT, only_over_capacity
    )
    (over,) = alerts_for_change(
        SERVICE, Status.ACCEPTING, Status.OVER_CAPACITY, True, ALERT_AT, only_over_capacity
    )

    assert (closed.kind, closed.critical) == (AlertKind.SERVICE_CLOSED, False)
    assert (over.kind, over.critical) == (AlertKind.OVER_CAPACITY, True)


def test_the_default_still_makes_service_closed_critical_and_over_capacity_not() -> None:
    (closed,) = alerts_for_change(SERVICE, Status.ACCEPTING, Status.NOT_ACCEPTING, True, ALERT_AT)
    (over,) = alerts_for_change(SERVICE, Status.ACCEPTING, Status.OVER_CAPACITY, True, ALERT_AT)

    assert closed.critical is True and over.critical is False


def test_a_pressure_alert_is_critical_only_when_the_policy_lists_system_pressure() -> None:
    listed = policy(critical_alert_kinds=frozenset({AlertKind.SYSTEM_PRESSURE}))
    unlisted = policy(critical_alert_kinds=frozenset({AlertKind.SERVICE_CLOSED}))

    assert alert_for_pressure(Pressure.NORMAL, Pressure.HIGH, ALERT_AT, listed) == Alert(
        AlertKind.SYSTEM_PRESSURE, None, ALERT_AT, True
    )
    assert alert_for_pressure(Pressure.NORMAL, Pressure.HIGH, ALERT_AT, unlisted) == Alert(
        AlertKind.SYSTEM_PRESSURE, None, ALERT_AT, False
    )
    assert alert_for_pressure(Pressure.WATCH, Pressure.HIGH, ALERT_AT).critical is True


def test_an_alert_can_be_built_directly_with_critical_for_any_kind() -> None:
    # The policy rule lives in the three functions' one constructor helper: an Alert has no policy.
    assert Alert(AlertKind.OVER_CAPACITY, SERVICE, ALERT_AT, True).critical is True
    assert Alert(AlertKind.SERVICE_CLOSED, SERVICE, ALERT_AT, False).critical is False


@pytest.mark.parametrize(
    ("kind", "service_id", "critical"),
    [
        (AlertKind.SYSTEM_PRESSURE, SERVICE, True),
        (AlertKind.SERVICE_CLOSED, None, True),
        (AlertKind.SERVICE_CLOSED, SERVICE, 1),
        (AlertKind.SERVICE_CLOSED, SERVICE, None),
    ],
)
def test_the_structural_checks_of_an_alert_stay(
    kind: AlertKind, service_id: Any, critical: Any
) -> None:
    with pytest.raises(ValidationFailed):
        Alert(kind, service_id, ALERT_AT, critical)


def test_the_option_sets_stay_global_whatever_the_policy() -> None:
    chosen = policy(alert_default_not_updated_hours=4)
    assert default_preferences(chosen).not_updated_hours == 4

    with pytest.raises(ValidationFailed):
        AlertPreferences(
            kinds=frozenset(AlertKind),
            not_updated_hours=3,
            quiet_hours=None,
            quiet_critical_only=True,
            ack_minutes=15,
        )
    with pytest.raises(ValidationFailed):
        AlertPreferences(
            kinds=frozenset(AlertKind),
            not_updated_hours=2,
            quiet_hours=None,
            quiet_critical_only=True,
            ack_minutes=20,
        )
    with pytest.raises(ValidationFailed):
        not_updated_alert_due(ALERT_AT, 3, ALERT_AT)


# ---------------------------------------------------------------- clinical queue (2, 3, 11, 13)

CLINICIAN = "c1"
OTHER_CLINICIAN = "c2"


def at(minute: int, second: int = 0) -> datetime:
    return datetime(2026, 6, 1, 14, minute, second, tzinfo=UTC)


def held(taken_at: datetime | None = None, advised_at: datetime | None = None) -> Any:
    return clinical_request(
        "r1", taken_by=CLINICIAN, taken_at=taken_at or at(0), advised_at=advised_at
    )


def test_a_second_clinician_is_refused_at_nine_minutes_fifty_nine_and_allowed_at_ten() -> None:
    with pytest.raises(Conflict):
        take(held(), OTHER_CLINICIAN, at(9, 59))
    with pytest.raises(Conflict):
        take(held(), OTHER_CLINICIAN, at(9, 59), DEFAULT_POLICY)

    assert take(held(), OTHER_CLINICIAN, at(10)).taken_by == OTHER_CLINICIAN
    assert take(held(), OTHER_CLINICIAN, at(10), DEFAULT_POLICY).taken_by == OTHER_CLINICIAN


@pytest.mark.parametrize("minutes", [5, 10, 15, 20])
def test_the_take_boundary_moves_with_the_policy(minutes: int) -> None:
    chosen = policy(clinical_take_timeout=minutes * MIN)
    before = at(minutes - 1, 59)
    exactly = at(minutes)

    with pytest.raises(Conflict):
        take(held(), OTHER_CLINICIAN, before, chosen)
    assert take(held(), OTHER_CLINICIAN, exactly, chosen).taken_by == OTHER_CLINICIAN


def test_the_same_clinician_keeps_a_live_lock_and_may_take_again_after_a_lapse() -> None:
    chosen = policy(clinical_take_timeout=5 * MIN)

    assert take(held(), CLINICIAN, at(4), chosen) == held()
    assert take(held(), CLINICIAN, at(5), chosen).taken_at == at(5)


def test_advice_after_the_lock_lapsed_under_the_policy_is_refused() -> None:
    short = policy(clinical_take_timeout=5 * MIN)
    long = policy(clinical_take_timeout=20 * MIN)

    with pytest.raises(NotAllowed):
        give_advice(held(), CLINICIAN, at(5), short)
    assert give_advice(held(), CLINICIAN, at(4, 59), short).advised_at == at(4, 59)
    assert give_advice(held(), CLINICIAN, at(10), long).advised_at == at(10)
    with pytest.raises(NotAllowed):
        give_advice(held(), CLINICIAN, at(10))
    assert give_advice(held(), CLINICIAN, at(9, 59)).advised_at == at(9, 59)


def test_an_idle_unadvised_lock_is_released_at_the_policys_timeout_and_not_before() -> None:
    chosen = policy(clinical_take_timeout=5 * MIN)

    assert return_if_idle(held(), at(4, 59), chosen) == held()
    released = return_if_idle(held(), at(5), chosen)
    assert (released.taken_by, released.taken_at) == (None, None)
    # The default keeps the same lock for ten minutes.
    assert return_if_idle(held(), at(5)) == held()
    assert return_if_idle(held(), at(10)).taken_by is None


def test_an_advised_request_is_never_released() -> None:
    advised = held(advised_at=at(1))

    assert return_if_idle(advised, at(59), policy(clinical_take_timeout=5 * MIN)) == advised


@given(chosen=policies(), minutes=st.integers(min_value=0, max_value=40))
def test_take_then_return_if_idle_never_releases_a_lock_younger_than_the_timeout(
    chosen: TenantPolicy, minutes: int
) -> None:
    locked = held()
    now = at(0) + minutes * MIN

    released = return_if_idle(locked, now, chosen)

    if now - at(0) < chosen.clinical_take_timeout:
        assert released == locked
    else:
        assert released.taken_by is None


# ---------------------------------------------------------------- re-verification (2, 3, 12, 13)

VERIFIED = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def test_thirty_days_under_the_default_and_seven_under_a_shorter_policy() -> None:
    assert needs_reverification(VERIFIED, VERIFIED + 29 * DAY + 23 * 60 * MIN, True) is False
    assert needs_reverification(VERIFIED, VERIFIED + 30 * DAY, True) is True
    assert needs_reverification(VERIFIED, VERIFIED + 30 * DAY, True, DEFAULT_POLICY) is True

    seven = policy(reverify_every=7 * DAY)
    assert needs_reverification(VERIFIED, VERIFIED + 7 * DAY - MIN, True, seven) is False
    assert needs_reverification(VERIFIED, VERIFIED + 7 * DAY, True, seven) is True


def test_the_reverification_bounds_are_seven_to_thirty_days_and_nothing_outside() -> None:
    low, high = bounds("reverify_every")

    assert (low, high) == (7 * DAY, 30 * DAY)
    for outside in (6 * DAY, 31 * DAY):
        with pytest.raises(ValidationFailed):
            policy(reverify_every=outside)


@pytest.mark.parametrize("chosen", [DEFAULT_POLICY, policy(reverify_every=7 * DAY)])
def test_an_unknown_device_a_never_verified_person_and_a_future_time_always_need_a_code(
    chosen: TenantPolicy,
) -> None:
    assert needs_reverification(VERIFIED, VERIFIED, False, chosen) is True
    assert needs_reverification(None, VERIFIED, True, chosen) is True
    assert needs_reverification(VERIFIED + MIN, VERIFIED, True, chosen) is True


@given(first=policies(), second=policies(), age_days=st.integers(min_value=0, max_value=40))
def test_a_longer_interval_never_makes_reverification_due_sooner(
    first: TenantPolicy, second: TenantPolicy, age_days: int
) -> None:
    short, long = sorted((first, second), key=lambda p: p.reverify_every)
    now = VERIFIED + age_days * DAY

    if needs_reverification(VERIFIED, now, True, long):
        assert needs_reverification(VERIFIED, now, True, short)
    if now - VERIFIED < short.reverify_every:
        assert needs_reverification(VERIFIED, now, True, short) is False


# ---------------------------------------------------------------- 4. the wrong argument is refused


@dataclass(frozen=True, slots=True)
class _SubPolicy(TenantPolicy):
    """A subclass of the policy: not exactly a TenantPolicy, so refused (lessons L3 and L38)."""


def _calls() -> dict[str, Callable[[Any], Any]]:
    items = due_at(0, 5)
    return {
        "booking_reply_by": lambda p: booking_reply_by(T0, p),
        "phone_prompt_at": lambda p: phone_prompt_at(T0, p),
        "flags_for_report": lambda p: flags_for_report(rpt(5, NEW_AT), [], ward_a(), p),
        "group_due": lambda p: group_due(items, p),
        "phone_overloaded": lambda p: phone_overloaded(2, p),
        "review_reminder_due": lambda p: review_reminder_due(
            ucr_west(review_by=REVIEW_BY), REVIEW_BY, p
        ),
        "default_preferences": lambda p: default_preferences(p),
        "alerts_for_change": lambda p: alerts_for_change(
            SERVICE, Status.ACCEPTING, Status.NOT_ACCEPTING, True, ALERT_AT, p
        ),
        "alert_for_pressure": lambda p: alert_for_pressure(
            Pressure.NORMAL, Pressure.HIGH, ALERT_AT, p
        ),
        "take": lambda p: take(clinical_request("r1"), CLINICIAN, at(1), p),
        "return_if_idle": lambda p: return_if_idle(held(), at(1), p),
        "give_advice": lambda p: give_advice(held(), CLINICIAN, at(1), p),
        "needs_reverification": lambda p: needs_reverification(VERIFIED, VERIFIED, True, p),
    }


CALLS = _calls()
BAD_POLICIES = [
    pytest.param({}, id="empty-dict"),
    pytest.param(None, id="none"),
    pytest.param("default", id="text"),
    pytest.param(Mock(), id="mock"),
    pytest.param(_SubPolicy(), id="subclass"),
    pytest.param(DEFAULT_POLICY.as_settings(), id="settings-mapping"),
]


@pytest.mark.parametrize("bad", BAD_POLICIES)
@pytest.mark.parametrize("name", sorted(CALLS))
def test_a_policy_that_is_not_exactly_a_tenant_policy_is_refused(name: str, bad: object) -> None:
    with pytest.raises(TypeError, match="a TenantPolicy is required"):
        CALLS[name](bad)


@pytest.mark.parametrize("name", sorted(CALLS))
def test_every_function_accepts_the_default_policy(name: str) -> None:
    CALLS[name](DEFAULT_POLICY)


def test_the_refusal_names_no_value() -> None:
    canary = "CANARY-policy-value"

    with pytest.raises(TypeError) as refused:
        CALLS["booking_reply_by"](canary)

    assert canary not in str(refused.value)


# ---------------------------------------------------------------- 5. no ambient state

POLICY_A = policy(
    booking_reply_window=15 * MIN,
    booking_phone_prompt_after=6 * MIN,
    many_changes_window=3 * MIN,
    many_changes_count=2,
    phoned_window=15 * MIN,
    group_window=15 * MIN,
    reply_window=45 * MIN,
    reminder_after=45 * MIN,
    max_services_per_phone=4,
    criteria_reminder_before=7 * DAY,
    clinical_take_timeout=5 * MIN,
    reverify_every=7 * DAY,
    critical_alert_kinds=frozenset({AlertKind.OVER_CAPACITY}),
    alert_default_kinds=frozenset({AlertKind.SERVICE_CLOSED}),
    alert_default_not_updated_hours=4,
)
POLICY_B = policy(
    booking_reply_window=25 * MIN,
    booking_phone_prompt_after=12 * MIN,
    many_changes_window=25 * MIN,
    many_changes_count=6,
    phoned_window=120 * MIN,
    group_window=20 * MIN,
    reply_window=60 * MIN,
    reminder_after=60 * MIN,
    phone_task_after=90 * MIN,
    escalate_after=120 * MIN,
    max_services_per_phone=6,
    criteria_reminder_before=30 * DAY,
    clinical_take_timeout=20 * MIN,
    reverify_every=14 * DAY,
    critical_alert_kinds=frozenset({AlertKind.NOT_UPDATED}),
    alert_default_kinds=frozenset({AlertKind.NOT_UPDATED, AlertKind.OVER_CAPACITY}),
    alert_default_not_updated_hours=2,
)


def _behaviour(chosen: TenantPolicy) -> list[Any]:
    """One result of every threaded function, built from this policy alone."""
    earlier = [rpt(4, NEW_AT - 2 * MIN), rpt(3, NEW_AT - 90 * MIN), phoned(2, NEW_AT - 20 * MIN)]
    return [
        booking_reply_by(T0, chosen),
        phone_prompt_at(T0, chosen),
        flags_for_report(rpt(5, NEW_AT), earlier, ward_a(), chosen),
        shapes(group_due(due_at(0, 7, 12, 17), chosen)),
        [phone_overloaded(count, chosen) for count in range(0, 8)],
        [
            review_reminder_due(ucr_west(review_by=REVIEW_BY), REVIEW_BY - n * DAY, chosen)
            for n in range(0, 33)
        ],
        default_preferences(chosen),
        alerts_for_change(SERVICE, Status.ACCEPTING, Status.NOT_ACCEPTING, True, ALERT_AT, chosen),
        alerts_for_change(SERVICE, Status.ACCEPTING, Status.OVER_CAPACITY, True, ALERT_AT, chosen),
        alert_for_pressure(Pressure.NORMAL, Pressure.HIGH, ALERT_AT, chosen),
        [return_if_idle(held(), at(minute), chosen).taken_by for minute in range(0, 25)],
        [needs_reverification(VERIFIED, VERIFIED + n * DAY, True, chosen) for n in range(0, 35)],
    ]


FRESH = {
    name: _behaviour(chosen)
    for name, chosen in (("a", POLICY_A), ("d", DEFAULT_POLICY), ("b", POLICY_B))
}
CHOSEN = {"a": POLICY_A, "d": DEFAULT_POLICY, "b": POLICY_B}


def test_the_two_sample_policies_really_differ_from_each_other_and_the_default() -> None:
    assert FRESH["a"] != FRESH["d"] != FRESH["b"] != FRESH["a"]


@pytest.mark.parametrize(
    "order", list(itertools.permutations("adb")) + [tuple("abab"), tuple("dbda")]
)
def test_a_call_depends_only_on_its_own_policy_whatever_ran_before(order: tuple[str, ...]) -> None:
    for key in order + order:
        assert _behaviour(CHOSEN[key]) == FRESH[key]


RULE_MODULES = (
    booking_rules,
    report_flags,
    multi_service,
    criteria_workflow,
    alerts,
    clinical_queue,
    identity_policy,
)
_MUTATORS = frozenset(
    {
        "append",
        "extend",
        "add",
        "update",
        "pop",
        "clear",
        "setdefault",
        "insert",
        "remove",
        "discard",
    }
)


def _module_tree(module: Any) -> ast.Module:
    return ast.parse(Path(module.__file__).read_text(encoding="utf-8"))


def _module_level_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


@pytest.mark.parametrize("module", RULE_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_a_rule_module_keeps_no_state_between_calls(module: Any) -> None:
    tree = _module_tree(module)
    shared = _module_level_names(tree)
    writes: list[str] = []
    for function in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        local = {a.arg for a in function.args.args + function.args.kwonlyargs}
        for node in ast.walk(function):
            if isinstance(node, ast.Global | ast.Nonlocal):
                writes.append(f"{function.name}: global statement")
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                local.add(node.id)
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _MUTATORS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in shared - local
            ):
                writes.append(f"{function.name}: {node.func.value.id}.{node.func.attr}")
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.ctx, ast.Store)
                and isinstance(node.value, ast.Name)
                and node.value.id in shared - local
            ):
                writes.append(f"{function.name}: {node.value.id}[...] =")
    assert writes == []


@pytest.mark.parametrize("module", RULE_MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_a_rule_module_imports_nothing_from_the_application_layer(module: Any) -> None:
    imported = [
        node.module or ""
        for node in ast.walk(_module_tree(module))
        if isinstance(node, ast.ImportFrom)
    ] + [
        alias.name
        for node in ast.walk(_module_tree(module))
        if isinstance(node, ast.Import)
        for alias in node.names
    ]

    assert [name for name in imported if name.startswith("diucs.application")] == []
    assert [name for name in imported if "tenancy" in name or name == "os"] == []
