"""Tests for diucs.domain.rules.schedule: report due times and the missed-report ladder (D04).

Rules from docs/spec/domain-rules.md 1.4 and 1.5 and the D04 prompt. Times are London local
(see AvailableTime). Windows that end before they start are overnight and belong to the day they
start. The clock changes are 2026-03-29 and 2026-10-25. Local times are turned into instants with
london_to_utc, never compared as wall-clock values across a change (lessons L4 and L25).
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Final

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.domain.codes import Cadence, Channel, Measure, ServiceCategory
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from diucs.domain.rules import schedule as schedule_rules
from diucs.domain.rules.london_time import london_to_utc, to_london
from diucs.domain.rules.schedule import (
    ESCALATE_AFTER,
    PHONE_TASK_AFTER,
    REMINDER_AFTER,
    REPLY_WINDOW,
    TWICE_A_DAY_SECOND,
    LadderStep,
    current_due,
    due_times_on,
    ladder_times,
    next_due,
    reply_by,
)
from tests.support.policy_samples import policies, policy

ONE_TICK: Final = timedelta(microseconds=1)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def utc_local(day: date, t: time) -> datetime:
    """The UTC instant of a London local time on a summer day."""
    return london_to_utc(day, t)


def profile(
    *windows: AvailableTime,
    cadence: Cadence = Cadence.EVERY_2_HRS,
) -> ServiceProfile:
    """A valid profile. Only the reporting fields matter to the schedule."""
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
        available_times=windows,
        channel=Channel.TEXT,
    )


# UCR West: Monday to Friday 08:00 to 20:00 London local, every 2 hours.
UCR_WEST = profile(AvailableTime.weekdays(time(8, 0), time(20, 0)))


# Rule 1.4: every-2-hrs, sample service UCR West.


def test_friday_in_summer_time_has_seven_due_times_from_0700z() -> None:
    # Fri 2026-10-23 is still BST: 08:00 to 20:00 local is 07:00Z to 19:00Z.
    assert due_times_on(UCR_WEST, date(2026, 10, 23)) == [
        utc(2026, 10, 23, hour) for hour in range(7, 20, 2)
    ]


def test_monday_after_the_clock_change_has_seven_due_times_from_0800z() -> None:
    assert due_times_on(UCR_WEST, date(2026, 10, 26)) == [
        utc(2026, 10, 26, hour) for hour in range(8, 21, 2)
    ]


def test_saturday_has_no_due_times() -> None:
    assert due_times_on(UCR_WEST, date(2026, 10, 24)) == []


def test_due_times_are_sorted_and_have_no_duplicates() -> None:
    twice = profile(
        AvailableTime.weekdays(time(8, 0), time(20, 0)),
        AvailableTime.weekdays(time(8, 0), time(20, 0)),
    )
    times = due_times_on(twice, date(2026, 10, 23))
    assert times == sorted(set(times))
    assert times == due_times_on(UCR_WEST, date(2026, 10, 23))


# Rule 1.4: twice-a-day, once-a-day.


def test_twice_a_day_is_opening_and_1400_local() -> None:
    twice = profile(AvailableTime.weekdays(time(8, 0), time(20, 0)), cadence=Cadence.TWICE_A_DAY)
    # Mon 2026-10-26 is GMT: 08:00 and 14:00 local are 08:00Z and 14:00Z.
    assert due_times_on(twice, date(2026, 10, 26)) == [utc(2026, 10, 26, 8), utc(2026, 10, 26, 14)]


def test_twice_a_day_opening_after_1400_has_only_the_opening() -> None:
    twice = profile(AvailableTime.weekdays(time(15, 0), time(20, 0)), cadence=Cadence.TWICE_A_DAY)
    assert due_times_on(twice, date(2026, 10, 26)) == [utc(2026, 10, 26, 15)]


def test_twice_a_day_opening_at_1400_has_one_due_time() -> None:
    twice = profile(AvailableTime.weekdays(time(14, 0), time(20, 0)), cadence=Cadence.TWICE_A_DAY)
    assert due_times_on(twice, date(2026, 10, 26)) == [utc(2026, 10, 26, 14)]


def test_twice_a_day_closing_at_1400_still_has_1400() -> None:
    # domain-rules 1.4: 14:00 is due unless the service opens after 14:00. The end is not an
    # exception (DEC-024). 08:00 to 14:00 gives 08:00 and 14:00.
    twice = profile(AvailableTime.weekdays(time(8, 0), time(14, 0)), cadence=Cadence.TWICE_A_DAY)
    assert due_times_on(twice, date(2026, 10, 26)) == [utc(2026, 10, 26, 8), utc(2026, 10, 26, 14)]


def test_twice_a_day_window_closing_before_1400_still_has_1400() -> None:
    # Same reading as above (DEC-024): 14:00 is due whenever the opening is not after 14:00.
    twice = profile(AvailableTime.weekdays(time(8, 0), time(12, 0)), cadence=Cadence.TWICE_A_DAY)
    assert due_times_on(twice, date(2026, 10, 26)) == [utc(2026, 10, 26, 8), utc(2026, 10, 26, 14)]


def test_twice_a_day_overnight_10_to_06_keeps_the_1400_due() -> None:
    # The window is open at 14:00 on the day it starts, so the 14:00 due is kept (DEC-024).
    twice = profile(AvailableTime.every_day(time(10, 0), time(6, 0)), cadence=Cadence.TWICE_A_DAY)
    assert due_times_on(twice, date(2026, 10, 26)) == [utc(2026, 10, 26, 10), utc(2026, 10, 26, 14)]


def test_twice_a_day_window_crossing_midnight_from_0600_has_1400() -> None:
    twice = profile(AvailableTime.every_day(time(6, 0), time(2, 0)), cadence=Cadence.TWICE_A_DAY)
    assert due_times_on(twice, date(2026, 10, 26)) == [utc(2026, 10, 26, 6), utc(2026, 10, 26, 14)]


def test_twice_a_day_overnight_opening_after_1400_has_only_the_opening() -> None:
    twice = profile(AvailableTime.every_day(time(22, 0), time(8, 0)), cadence=Cadence.TWICE_A_DAY)
    assert due_times_on(twice, date(2026, 10, 26)) == [utc(2026, 10, 26, 22)]


def test_once_a_day_is_the_opening_only() -> None:
    once = profile(AvailableTime.weekdays(time(8, 0), time(20, 0)), cadence=Cadence.ONCE_A_DAY)
    assert due_times_on(once, date(2026, 10, 26)) == [utc(2026, 10, 26, 8)]


# Rule 1.4: all-day services use 00:00 as the opening, across both clock changes.


ALL_DAY_EVERY_2_HRS = profile(AvailableTime.every_day_all_day(), cadence=Cadence.EVERY_2_HRS)


def test_all_day_every_2_hrs_on_2026_10_25_has_twelve_local_times_from_midnight() -> None:
    times = due_times_on(ALL_DAY_EVERY_2_HRS, date(2026, 10, 25))
    assert len(times) == 12
    assert times[0] == utc(2026, 10, 24, 23)  # 00:00 BST
    assert times[1] == utc(2026, 10, 25, 2)  # 02:00 GMT, after the change
    assert times[-1] == utc(2026, 10, 25, 22)  # 22:00 GMT


def test_all_day_every_2_hrs_on_2026_03_29_skips_the_gap_and_has_no_duplicates() -> None:
    times = due_times_on(ALL_DAY_EVERY_2_HRS, date(2026, 3, 29))
    assert len(times) == 12
    assert times[0] == utc(2026, 3, 29, 0)  # 00:00 GMT
    assert times[1] == utc(2026, 3, 29, 1)  # 02:00 BST is 01:00Z
    assert times[-1] == utc(2026, 3, 29, 21)  # 22:00 BST
    assert times == sorted(set(times))


def test_all_day_twice_a_day_is_midnight_and_1400() -> None:
    twice = profile(AvailableTime.every_day_all_day(), cadence=Cadence.TWICE_A_DAY)
    assert due_times_on(twice, date(2026, 10, 26)) == [utc(2026, 10, 26, 0), utc(2026, 10, 26, 14)]


# Rule 1.4: overnight windows belong to the day they start.


def test_overnight_window_is_due_every_two_hours_into_the_next_morning() -> None:
    overnight = profile(AvailableTime.every_day(time(20, 0), time(8, 0)))
    assert due_times_on(overnight, date(2026, 10, 23)) == [
        utc(2026, 10, 23, 19),  # 20:00 BST
        utc(2026, 10, 23, 21),  # 22:00 BST
        utc(2026, 10, 23, 23),  # 00:00 BST, 24 Oct
        utc(2026, 10, 24, 1),  # 02:00 BST
        utc(2026, 10, 24, 3),  # 04:00 BST
        utc(2026, 10, 24, 5),  # 06:00 BST
        utc(2026, 10, 24, 7),  # 08:00 BST, the closing time is included
    ]


def test_overnight_window_across_the_spring_gap_has_five_distinct_instants() -> None:
    # Sat 2026-03-28 20:00 to Sun 08:00. Local 01:00 on 29 March does not exist; its instant is
    # 01:00Z, and the next due time, 03:00 BST, is 02:00Z. Nothing is duplicated or reordered.
    overnight = profile(AvailableTime.every_day(time(23, 0), time(7, 0)))
    times = due_times_on(overnight, date(2026, 3, 28))
    assert times == [
        utc(2026, 3, 28, 23),
        utc(2026, 3, 29, 1),
        utc(2026, 3, 29, 2),
        utc(2026, 3, 29, 4),
        utc(2026, 3, 29, 6),
    ]


# Rule 1.4: next_due and current_due.


def test_next_due_skips_the_passed_1400_slot_on_a_summer_friday() -> None:
    # Fri 2026-10-23 13:12Z is 14:12 BST. The 14:00 BST due time (13:00Z) has passed.
    assert next_due(UCR_WEST, utc(2026, 10, 23, 13, 12)) == utc(2026, 10, 23, 15)


def test_next_due_is_strictly_after_now() -> None:
    # 13:00Z is exactly a due time, so the next one is 15:00Z.
    assert next_due(UCR_WEST, utc(2026, 10, 23, 13)) == utc(2026, 10, 23, 15)


def test_current_due_at_a_moment_after_a_due_time_is_that_due_time() -> None:
    assert current_due(UCR_WEST, utc(2026, 10, 23, 13, 12)) == utc(2026, 10, 23, 13)


def test_current_due_at_a_due_time_is_that_due_time() -> None:
    assert current_due(UCR_WEST, utc(2026, 10, 23, 13)) == utc(2026, 10, 23, 13)


def test_current_due_on_saturday_noon_is_friday_1900z() -> None:
    assert current_due(UCR_WEST, utc(2026, 10, 24, 12)) == utc(2026, 10, 23, 19)


def test_current_due_on_monday_morning_finds_friday_evening() -> None:
    # Mon 2026-10-26 05:00Z: nothing is due until 08:00 GMT. The last due time was Friday 19:00Z.
    # DEC-023: current_due searches back over 8 days, not only today and yesterday.
    assert current_due(UCR_WEST, utc(2026, 10, 26, 5)) == utc(2026, 10, 23, 19)


def test_current_due_on_sunday_is_friday_1900z() -> None:
    assert current_due(UCR_WEST, utc(2026, 10, 25, 12)) == utc(2026, 10, 23, 19)


# Rule 1.4: reply-by and rule 1.5: the ladder.


def test_reply_by_is_due_plus_30_minutes() -> None:
    assert reply_by(utc(2026, 10, 23, 9)) == utc(2026, 10, 23, 9, 30)
    assert timedelta(minutes=30) == REPLY_WINDOW


def test_ladder_offsets_are_30_60_90_minutes_after_the_prompt() -> None:
    assert timedelta(minutes=30) == REMINDER_AFTER
    assert timedelta(minutes=60) == PHONE_TASK_AFTER
    assert timedelta(minutes=90) == ESCALATE_AFTER
    assert time(14, 0) == TWICE_A_DAY_SECOND


def test_ladder_times_from_a_due_time() -> None:
    assert ladder_times(utc(2026, 10, 23, 11)) == {
        LadderStep.PROMPT: utc(2026, 10, 23, 11),
        LadderStep.REMINDER: utc(2026, 10, 23, 11, 30),
        LadderStep.PHONE_TASK: utc(2026, 10, 23, 12),
        LadderStep.ESCALATE: utc(2026, 10, 23, 12, 30),
    }


def test_ladder_step_values_match_the_contract() -> None:
    assert [step.value for step in LadderStep] == ["prompt", "reminder", "phone-task", "escalate"]


# Properties. Oracles compare instants, or wall-clock times only on days with no clock change.

ANY_2026_INSTANT = st.datetimes(
    min_value=datetime(2026, 1, 1), max_value=datetime(2026, 12, 31)
).map(lambda naive: naive.replace(tzinfo=UTC))


def _slot_time(slot: int) -> time:
    """Half-hour slot 0 to 47 as a time of day."""
    return time(slot // 2, 30 * (slot % 2))


# Every timed window on the half-hour grid, every day of the week. Start and end differ.
timed_window = (
    st.tuples(st.integers(0, 47), st.integers(0, 47))
    .filter(lambda slots: slots[0] != slots[1])
    .map(
        lambda slots: AvailableTime(
            days=frozenset(range(7)),
            all_day=False,
            start=_slot_time(slots[0]),
            end=_slot_time(slots[1]),
        )
    )
)


CADENCES = st.sampled_from(list(Cadence))


@settings(max_examples=200)
@given(window=timed_window, cadence=CADENCES, day=st.dates(date(2026, 1, 1), date(2026, 12, 31)))
def test_due_times_are_strictly_increasing_utc_instants(
    window: AvailableTime, cadence: Cadence, day: date
) -> None:
    times = due_times_on(profile(window, cadence=cadence), day)
    assert all(t.tzinfo is not None and t.utcoffset() == timedelta(0) for t in times)
    assert all(earlier < later for earlier, later in zip(times, times[1:], strict=False))
    assert len(times) <= 13


@settings(max_examples=200)
@given(window=timed_window, cadence=CADENCES, day=st.dates(date(2026, 4, 1), date(2026, 9, 30)))
def test_summer_due_times_sit_on_the_local_grid(
    window: AvailableTime, cadence: Cadence, day: date
) -> None:
    # April to September has no clock change, so a wall-clock oracle is valid (lesson L25).
    start = window.start
    assert start is not None
    for due in due_times_on(profile(window, cadence=cadence), day):
        local = to_london(due).time()
        if cadence is Cadence.ONCE_A_DAY:
            assert local == start
        elif cadence is Cadence.TWICE_A_DAY:
            assert local in {start, TWICE_A_DAY_SECOND}
        else:
            minutes_from_start = (
                (local.hour * 60 + local.minute) - (start.hour * 60 + start.minute)
            ) % (24 * 60)
            assert minutes_from_start % 120 == 0


@settings(max_examples=300)
@given(now=ANY_2026_INSTANT, window=timed_window, cadence=CADENCES)
def test_next_and_current_due_bracket_now_with_no_due_time_between(
    now: datetime, window: AvailableTime, cadence: Cadence
) -> None:
    schedule = profile(window, cadence=cadence)
    upcoming = next_due(schedule, now)
    latest = current_due(schedule, now)
    assert upcoming is not None
    assert latest is not None
    assert latest <= now < upcoming
    # Nothing is due between now and the next due time.
    assert current_due(schedule, upcoming - ONE_TICK) == latest
    assert current_due(schedule, upcoming) == upcoming


@settings(max_examples=300)
@given(window=timed_window, day=st.dates(date(2026, 4, 1), date(2026, 9, 30)))
def test_twice_a_day_has_1400_exactly_when_the_window_does_not_open_after_it(
    window: AvailableTime, day: date
) -> None:
    # Summer days only, so local 14:00 is one instant. Oracle: the rule book's one exception.
    start = window.start
    assert start is not None
    due = due_times_on(profile(window, cadence=Cadence.TWICE_A_DAY), day)
    fourteen = utc_local(day, TWICE_A_DAY_SECOND)
    assert (fourteen in due) is (start <= TWICE_A_DAY_SECOND)


# --- Tenant policy (TEN-021) ----------------------------------------------------------------

FRIDAY: Final = date(2026, 10, 23)  # British summer time
MONDAY_AFTER_CHANGE: Final = date(2026, 10, 26)  # GMT
GRID_PROFILES: Final = {
    "weekday-0800-2000": lambda cadence: profile(
        AvailableTime.weekdays(time(8, 0), time(20, 0)), cadence=cadence
    ),
    "weekday-1430-2000": lambda cadence: profile(
        AvailableTime.weekdays(time(14, 30), time(20, 0)), cadence=cadence
    ),
    "weekday-0800-1200": lambda cadence: profile(
        AvailableTime.weekdays(time(8, 0), time(12, 0)), cadence=cadence
    ),
    "daily-overnight-1000-0600": lambda cadence: profile(
        AvailableTime.every_day(time(10, 0), time(6, 0)), cadence=cadence
    ),
    "daily-all-day": lambda cadence: profile(AvailableTime.every_day_all_day(), cadence=cadence),
}


def at(text: str) -> datetime:
    """An instant written as 2026-10-23T12:00Z (the form of the golden grid)."""
    return datetime.fromisoformat(text)


# Test 1. Golden grid (characterisation): captured from the unmodified rules at commit 26a5b73
# (integration/build), before TEN-021 changed any source. Columns: profile, cadence, instant,
# the due times of the instant's London day, next_due, current_due, reply_by(current_due) and the
# ladder of current_due (prompt, reminder, phone task, escalate). They pass at red and at green.
GOLDEN_GRID: Final = [
    (
        "weekday-0800-2000",
        "once-a-day",
        "2026-03-29T01:30Z",
        [],
        "2026-03-30T07:00Z",
        "2026-03-27T08:00Z",
        "2026-03-27T08:30Z",
        ("2026-03-27T08:00Z", "2026-03-27T08:30Z", "2026-03-27T09:00Z", "2026-03-27T09:30Z"),
    ),
    (
        "weekday-0800-2000",
        "once-a-day",
        "2026-03-29T09:45Z",
        [],
        "2026-03-30T07:00Z",
        "2026-03-27T08:00Z",
        "2026-03-27T08:30Z",
        ("2026-03-27T08:00Z", "2026-03-27T08:30Z", "2026-03-27T09:00Z", "2026-03-27T09:30Z"),
    ),
    (
        "weekday-0800-2000",
        "once-a-day",
        "2026-10-23T12:00Z",
        ["2026-10-23T07:00Z"],
        "2026-10-26T08:00Z",
        "2026-10-23T07:00Z",
        "2026-10-23T07:30Z",
        ("2026-10-23T07:00Z", "2026-10-23T07:30Z", "2026-10-23T08:00Z", "2026-10-23T08:30Z"),
    ),
    (
        "weekday-0800-2000",
        "once-a-day",
        "2026-10-25T01:30Z",
        [],
        "2026-10-26T08:00Z",
        "2026-10-23T07:00Z",
        "2026-10-23T07:30Z",
        ("2026-10-23T07:00Z", "2026-10-23T07:30Z", "2026-10-23T08:00Z", "2026-10-23T08:30Z"),
    ),
    (
        "weekday-0800-2000",
        "twice-a-day",
        "2026-03-29T01:30Z",
        [],
        "2026-03-30T07:00Z",
        "2026-03-27T14:00Z",
        "2026-03-27T14:30Z",
        ("2026-03-27T14:00Z", "2026-03-27T14:30Z", "2026-03-27T15:00Z", "2026-03-27T15:30Z"),
    ),
    (
        "weekday-0800-2000",
        "twice-a-day",
        "2026-03-29T09:45Z",
        [],
        "2026-03-30T07:00Z",
        "2026-03-27T14:00Z",
        "2026-03-27T14:30Z",
        ("2026-03-27T14:00Z", "2026-03-27T14:30Z", "2026-03-27T15:00Z", "2026-03-27T15:30Z"),
    ),
    (
        "weekday-0800-2000",
        "twice-a-day",
        "2026-10-23T12:00Z",
        ["2026-10-23T07:00Z", "2026-10-23T13:00Z"],
        "2026-10-23T13:00Z",
        "2026-10-23T07:00Z",
        "2026-10-23T07:30Z",
        ("2026-10-23T07:00Z", "2026-10-23T07:30Z", "2026-10-23T08:00Z", "2026-10-23T08:30Z"),
    ),
    (
        "weekday-0800-2000",
        "twice-a-day",
        "2026-10-25T01:30Z",
        [],
        "2026-10-26T08:00Z",
        "2026-10-23T13:00Z",
        "2026-10-23T13:30Z",
        ("2026-10-23T13:00Z", "2026-10-23T13:30Z", "2026-10-23T14:00Z", "2026-10-23T14:30Z"),
    ),
    (
        "weekday-0800-2000",
        "every-2-hrs",
        "2026-03-29T01:30Z",
        [],
        "2026-03-30T07:00Z",
        "2026-03-27T20:00Z",
        "2026-03-27T20:30Z",
        ("2026-03-27T20:00Z", "2026-03-27T20:30Z", "2026-03-27T21:00Z", "2026-03-27T21:30Z"),
    ),
    (
        "weekday-0800-2000",
        "every-2-hrs",
        "2026-03-29T09:45Z",
        [],
        "2026-03-30T07:00Z",
        "2026-03-27T20:00Z",
        "2026-03-27T20:30Z",
        ("2026-03-27T20:00Z", "2026-03-27T20:30Z", "2026-03-27T21:00Z", "2026-03-27T21:30Z"),
    ),
    (
        "weekday-0800-2000",
        "every-2-hrs",
        "2026-10-23T12:00Z",
        [
            "2026-10-23T07:00Z",
            "2026-10-23T09:00Z",
            "2026-10-23T11:00Z",
            "2026-10-23T13:00Z",
            "2026-10-23T15:00Z",
            "2026-10-23T17:00Z",
            "2026-10-23T19:00Z",
        ],
        "2026-10-23T13:00Z",
        "2026-10-23T11:00Z",
        "2026-10-23T11:30Z",
        ("2026-10-23T11:00Z", "2026-10-23T11:30Z", "2026-10-23T12:00Z", "2026-10-23T12:30Z"),
    ),
    (
        "weekday-0800-2000",
        "every-2-hrs",
        "2026-10-25T01:30Z",
        [],
        "2026-10-26T08:00Z",
        "2026-10-23T19:00Z",
        "2026-10-23T19:30Z",
        ("2026-10-23T19:00Z", "2026-10-23T19:30Z", "2026-10-23T20:00Z", "2026-10-23T20:30Z"),
    ),
    (
        "weekday-1430-2000",
        "once-a-day",
        "2026-03-29T01:30Z",
        [],
        "2026-03-30T13:30Z",
        "2026-03-27T14:30Z",
        "2026-03-27T15:00Z",
        ("2026-03-27T14:30Z", "2026-03-27T15:00Z", "2026-03-27T15:30Z", "2026-03-27T16:00Z"),
    ),
    (
        "weekday-1430-2000",
        "once-a-day",
        "2026-03-29T09:45Z",
        [],
        "2026-03-30T13:30Z",
        "2026-03-27T14:30Z",
        "2026-03-27T15:00Z",
        ("2026-03-27T14:30Z", "2026-03-27T15:00Z", "2026-03-27T15:30Z", "2026-03-27T16:00Z"),
    ),
    (
        "weekday-1430-2000",
        "once-a-day",
        "2026-10-23T12:00Z",
        ["2026-10-23T13:30Z"],
        "2026-10-23T13:30Z",
        "2026-10-22T13:30Z",
        "2026-10-22T14:00Z",
        ("2026-10-22T13:30Z", "2026-10-22T14:00Z", "2026-10-22T14:30Z", "2026-10-22T15:00Z"),
    ),
    (
        "weekday-1430-2000",
        "once-a-day",
        "2026-10-25T01:30Z",
        [],
        "2026-10-26T14:30Z",
        "2026-10-23T13:30Z",
        "2026-10-23T14:00Z",
        ("2026-10-23T13:30Z", "2026-10-23T14:00Z", "2026-10-23T14:30Z", "2026-10-23T15:00Z"),
    ),
    (
        "weekday-1430-2000",
        "twice-a-day",
        "2026-03-29T01:30Z",
        [],
        "2026-03-30T13:30Z",
        "2026-03-27T14:30Z",
        "2026-03-27T15:00Z",
        ("2026-03-27T14:30Z", "2026-03-27T15:00Z", "2026-03-27T15:30Z", "2026-03-27T16:00Z"),
    ),
    (
        "weekday-1430-2000",
        "twice-a-day",
        "2026-03-29T09:45Z",
        [],
        "2026-03-30T13:30Z",
        "2026-03-27T14:30Z",
        "2026-03-27T15:00Z",
        ("2026-03-27T14:30Z", "2026-03-27T15:00Z", "2026-03-27T15:30Z", "2026-03-27T16:00Z"),
    ),
    (
        "weekday-1430-2000",
        "twice-a-day",
        "2026-10-23T12:00Z",
        ["2026-10-23T13:30Z"],
        "2026-10-23T13:30Z",
        "2026-10-22T13:30Z",
        "2026-10-22T14:00Z",
        ("2026-10-22T13:30Z", "2026-10-22T14:00Z", "2026-10-22T14:30Z", "2026-10-22T15:00Z"),
    ),
    (
        "weekday-1430-2000",
        "twice-a-day",
        "2026-10-25T01:30Z",
        [],
        "2026-10-26T14:30Z",
        "2026-10-23T13:30Z",
        "2026-10-23T14:00Z",
        ("2026-10-23T13:30Z", "2026-10-23T14:00Z", "2026-10-23T14:30Z", "2026-10-23T15:00Z"),
    ),
    (
        "weekday-1430-2000",
        "every-2-hrs",
        "2026-03-29T01:30Z",
        [],
        "2026-03-30T13:30Z",
        "2026-03-27T18:30Z",
        "2026-03-27T19:00Z",
        ("2026-03-27T18:30Z", "2026-03-27T19:00Z", "2026-03-27T19:30Z", "2026-03-27T20:00Z"),
    ),
    (
        "weekday-1430-2000",
        "every-2-hrs",
        "2026-03-29T09:45Z",
        [],
        "2026-03-30T13:30Z",
        "2026-03-27T18:30Z",
        "2026-03-27T19:00Z",
        ("2026-03-27T18:30Z", "2026-03-27T19:00Z", "2026-03-27T19:30Z", "2026-03-27T20:00Z"),
    ),
    (
        "weekday-1430-2000",
        "every-2-hrs",
        "2026-10-23T12:00Z",
        ["2026-10-23T13:30Z", "2026-10-23T15:30Z", "2026-10-23T17:30Z"],
        "2026-10-23T13:30Z",
        "2026-10-22T17:30Z",
        "2026-10-22T18:00Z",
        ("2026-10-22T17:30Z", "2026-10-22T18:00Z", "2026-10-22T18:30Z", "2026-10-22T19:00Z"),
    ),
    (
        "weekday-1430-2000",
        "every-2-hrs",
        "2026-10-25T01:30Z",
        [],
        "2026-10-26T14:30Z",
        "2026-10-23T17:30Z",
        "2026-10-23T18:00Z",
        ("2026-10-23T17:30Z", "2026-10-23T18:00Z", "2026-10-23T18:30Z", "2026-10-23T19:00Z"),
    ),
    (
        "weekday-0800-1200",
        "once-a-day",
        "2026-03-29T01:30Z",
        [],
        "2026-03-30T07:00Z",
        "2026-03-27T08:00Z",
        "2026-03-27T08:30Z",
        ("2026-03-27T08:00Z", "2026-03-27T08:30Z", "2026-03-27T09:00Z", "2026-03-27T09:30Z"),
    ),
    (
        "weekday-0800-1200",
        "once-a-day",
        "2026-03-29T09:45Z",
        [],
        "2026-03-30T07:00Z",
        "2026-03-27T08:00Z",
        "2026-03-27T08:30Z",
        ("2026-03-27T08:00Z", "2026-03-27T08:30Z", "2026-03-27T09:00Z", "2026-03-27T09:30Z"),
    ),
    (
        "weekday-0800-1200",
        "once-a-day",
        "2026-10-23T12:00Z",
        ["2026-10-23T07:00Z"],
        "2026-10-26T08:00Z",
        "2026-10-23T07:00Z",
        "2026-10-23T07:30Z",
        ("2026-10-23T07:00Z", "2026-10-23T07:30Z", "2026-10-23T08:00Z", "2026-10-23T08:30Z"),
    ),
    (
        "weekday-0800-1200",
        "once-a-day",
        "2026-10-25T01:30Z",
        [],
        "2026-10-26T08:00Z",
        "2026-10-23T07:00Z",
        "2026-10-23T07:30Z",
        ("2026-10-23T07:00Z", "2026-10-23T07:30Z", "2026-10-23T08:00Z", "2026-10-23T08:30Z"),
    ),
    (
        "weekday-0800-1200",
        "twice-a-day",
        "2026-03-29T01:30Z",
        [],
        "2026-03-30T07:00Z",
        "2026-03-27T14:00Z",
        "2026-03-27T14:30Z",
        ("2026-03-27T14:00Z", "2026-03-27T14:30Z", "2026-03-27T15:00Z", "2026-03-27T15:30Z"),
    ),
    (
        "weekday-0800-1200",
        "twice-a-day",
        "2026-03-29T09:45Z",
        [],
        "2026-03-30T07:00Z",
        "2026-03-27T14:00Z",
        "2026-03-27T14:30Z",
        ("2026-03-27T14:00Z", "2026-03-27T14:30Z", "2026-03-27T15:00Z", "2026-03-27T15:30Z"),
    ),
    (
        "weekday-0800-1200",
        "twice-a-day",
        "2026-10-23T12:00Z",
        ["2026-10-23T07:00Z", "2026-10-23T13:00Z"],
        "2026-10-23T13:00Z",
        "2026-10-23T07:00Z",
        "2026-10-23T07:30Z",
        ("2026-10-23T07:00Z", "2026-10-23T07:30Z", "2026-10-23T08:00Z", "2026-10-23T08:30Z"),
    ),
    (
        "weekday-0800-1200",
        "twice-a-day",
        "2026-10-25T01:30Z",
        [],
        "2026-10-26T08:00Z",
        "2026-10-23T13:00Z",
        "2026-10-23T13:30Z",
        ("2026-10-23T13:00Z", "2026-10-23T13:30Z", "2026-10-23T14:00Z", "2026-10-23T14:30Z"),
    ),
    (
        "weekday-0800-1200",
        "every-2-hrs",
        "2026-03-29T01:30Z",
        [],
        "2026-03-30T07:00Z",
        "2026-03-27T12:00Z",
        "2026-03-27T12:30Z",
        ("2026-03-27T12:00Z", "2026-03-27T12:30Z", "2026-03-27T13:00Z", "2026-03-27T13:30Z"),
    ),
    (
        "weekday-0800-1200",
        "every-2-hrs",
        "2026-03-29T09:45Z",
        [],
        "2026-03-30T07:00Z",
        "2026-03-27T12:00Z",
        "2026-03-27T12:30Z",
        ("2026-03-27T12:00Z", "2026-03-27T12:30Z", "2026-03-27T13:00Z", "2026-03-27T13:30Z"),
    ),
    (
        "weekday-0800-1200",
        "every-2-hrs",
        "2026-10-23T12:00Z",
        ["2026-10-23T07:00Z", "2026-10-23T09:00Z", "2026-10-23T11:00Z"],
        "2026-10-26T08:00Z",
        "2026-10-23T11:00Z",
        "2026-10-23T11:30Z",
        ("2026-10-23T11:00Z", "2026-10-23T11:30Z", "2026-10-23T12:00Z", "2026-10-23T12:30Z"),
    ),
    (
        "weekday-0800-1200",
        "every-2-hrs",
        "2026-10-25T01:30Z",
        [],
        "2026-10-26T08:00Z",
        "2026-10-23T11:00Z",
        "2026-10-23T11:30Z",
        ("2026-10-23T11:00Z", "2026-10-23T11:30Z", "2026-10-23T12:00Z", "2026-10-23T12:30Z"),
    ),
    (
        "daily-overnight-1000-0600",
        "once-a-day",
        "2026-03-29T01:30Z",
        ["2026-03-29T09:00Z"],
        "2026-03-29T09:00Z",
        "2026-03-28T10:00Z",
        "2026-03-28T10:30Z",
        ("2026-03-28T10:00Z", "2026-03-28T10:30Z", "2026-03-28T11:00Z", "2026-03-28T11:30Z"),
    ),
    (
        "daily-overnight-1000-0600",
        "once-a-day",
        "2026-03-29T09:45Z",
        ["2026-03-29T09:00Z"],
        "2026-03-30T09:00Z",
        "2026-03-29T09:00Z",
        "2026-03-29T09:30Z",
        ("2026-03-29T09:00Z", "2026-03-29T09:30Z", "2026-03-29T10:00Z", "2026-03-29T10:30Z"),
    ),
    (
        "daily-overnight-1000-0600",
        "once-a-day",
        "2026-10-23T12:00Z",
        ["2026-10-23T09:00Z"],
        "2026-10-24T09:00Z",
        "2026-10-23T09:00Z",
        "2026-10-23T09:30Z",
        ("2026-10-23T09:00Z", "2026-10-23T09:30Z", "2026-10-23T10:00Z", "2026-10-23T10:30Z"),
    ),
    (
        "daily-overnight-1000-0600",
        "once-a-day",
        "2026-10-25T01:30Z",
        ["2026-10-25T10:00Z"],
        "2026-10-25T10:00Z",
        "2026-10-24T09:00Z",
        "2026-10-24T09:30Z",
        ("2026-10-24T09:00Z", "2026-10-24T09:30Z", "2026-10-24T10:00Z", "2026-10-24T10:30Z"),
    ),
    (
        "daily-overnight-1000-0600",
        "twice-a-day",
        "2026-03-29T01:30Z",
        ["2026-03-29T09:00Z", "2026-03-29T13:00Z"],
        "2026-03-29T09:00Z",
        "2026-03-28T14:00Z",
        "2026-03-28T14:30Z",
        ("2026-03-28T14:00Z", "2026-03-28T14:30Z", "2026-03-28T15:00Z", "2026-03-28T15:30Z"),
    ),
    (
        "daily-overnight-1000-0600",
        "twice-a-day",
        "2026-03-29T09:45Z",
        ["2026-03-29T09:00Z", "2026-03-29T13:00Z"],
        "2026-03-29T13:00Z",
        "2026-03-29T09:00Z",
        "2026-03-29T09:30Z",
        ("2026-03-29T09:00Z", "2026-03-29T09:30Z", "2026-03-29T10:00Z", "2026-03-29T10:30Z"),
    ),
    (
        "daily-overnight-1000-0600",
        "twice-a-day",
        "2026-10-23T12:00Z",
        ["2026-10-23T09:00Z", "2026-10-23T13:00Z"],
        "2026-10-23T13:00Z",
        "2026-10-23T09:00Z",
        "2026-10-23T09:30Z",
        ("2026-10-23T09:00Z", "2026-10-23T09:30Z", "2026-10-23T10:00Z", "2026-10-23T10:30Z"),
    ),
    (
        "daily-overnight-1000-0600",
        "twice-a-day",
        "2026-10-25T01:30Z",
        ["2026-10-25T10:00Z", "2026-10-25T14:00Z"],
        "2026-10-25T10:00Z",
        "2026-10-24T13:00Z",
        "2026-10-24T13:30Z",
        ("2026-10-24T13:00Z", "2026-10-24T13:30Z", "2026-10-24T14:00Z", "2026-10-24T14:30Z"),
    ),
    (
        "daily-overnight-1000-0600",
        "every-2-hrs",
        "2026-03-29T01:30Z",
        [
            "2026-03-29T09:00Z",
            "2026-03-29T11:00Z",
            "2026-03-29T13:00Z",
            "2026-03-29T15:00Z",
            "2026-03-29T17:00Z",
            "2026-03-29T19:00Z",
            "2026-03-29T21:00Z",
            "2026-03-29T23:00Z",
            "2026-03-30T01:00Z",
            "2026-03-30T03:00Z",
            "2026-03-30T05:00Z",
        ],
        "2026-03-29T03:00Z",
        "2026-03-29T01:00Z",
        "2026-03-29T01:30Z",
        ("2026-03-29T01:00Z", "2026-03-29T01:30Z", "2026-03-29T02:00Z", "2026-03-29T02:30Z"),
    ),
    (
        "daily-overnight-1000-0600",
        "every-2-hrs",
        "2026-03-29T09:45Z",
        [
            "2026-03-29T09:00Z",
            "2026-03-29T11:00Z",
            "2026-03-29T13:00Z",
            "2026-03-29T15:00Z",
            "2026-03-29T17:00Z",
            "2026-03-29T19:00Z",
            "2026-03-29T21:00Z",
            "2026-03-29T23:00Z",
            "2026-03-30T01:00Z",
            "2026-03-30T03:00Z",
            "2026-03-30T05:00Z",
        ],
        "2026-03-29T11:00Z",
        "2026-03-29T09:00Z",
        "2026-03-29T09:30Z",
        ("2026-03-29T09:00Z", "2026-03-29T09:30Z", "2026-03-29T10:00Z", "2026-03-29T10:30Z"),
    ),
    (
        "daily-overnight-1000-0600",
        "every-2-hrs",
        "2026-10-23T12:00Z",
        [
            "2026-10-23T09:00Z",
            "2026-10-23T11:00Z",
            "2026-10-23T13:00Z",
            "2026-10-23T15:00Z",
            "2026-10-23T17:00Z",
            "2026-10-23T19:00Z",
            "2026-10-23T21:00Z",
            "2026-10-23T23:00Z",
            "2026-10-24T01:00Z",
            "2026-10-24T03:00Z",
            "2026-10-24T05:00Z",
        ],
        "2026-10-23T13:00Z",
        "2026-10-23T11:00Z",
        "2026-10-23T11:30Z",
        ("2026-10-23T11:00Z", "2026-10-23T11:30Z", "2026-10-23T12:00Z", "2026-10-23T12:30Z"),
    ),
    (
        "daily-overnight-1000-0600",
        "every-2-hrs",
        "2026-10-25T01:30Z",
        [
            "2026-10-25T10:00Z",
            "2026-10-25T12:00Z",
            "2026-10-25T14:00Z",
            "2026-10-25T16:00Z",
            "2026-10-25T18:00Z",
            "2026-10-25T20:00Z",
            "2026-10-25T22:00Z",
            "2026-10-26T00:00Z",
            "2026-10-26T02:00Z",
            "2026-10-26T04:00Z",
            "2026-10-26T06:00Z",
        ],
        "2026-10-25T02:00Z",
        "2026-10-24T23:00Z",
        "2026-10-24T23:30Z",
        ("2026-10-24T23:00Z", "2026-10-24T23:30Z", "2026-10-25T00:00Z", "2026-10-25T00:30Z"),
    ),
    (
        "daily-all-day",
        "once-a-day",
        "2026-03-29T01:30Z",
        ["2026-03-29T00:00Z"],
        "2026-03-29T23:00Z",
        "2026-03-29T00:00Z",
        "2026-03-29T00:30Z",
        ("2026-03-29T00:00Z", "2026-03-29T00:30Z", "2026-03-29T01:00Z", "2026-03-29T01:30Z"),
    ),
    (
        "daily-all-day",
        "once-a-day",
        "2026-03-29T09:45Z",
        ["2026-03-29T00:00Z"],
        "2026-03-29T23:00Z",
        "2026-03-29T00:00Z",
        "2026-03-29T00:30Z",
        ("2026-03-29T00:00Z", "2026-03-29T00:30Z", "2026-03-29T01:00Z", "2026-03-29T01:30Z"),
    ),
    (
        "daily-all-day",
        "once-a-day",
        "2026-10-23T12:00Z",
        ["2026-10-22T23:00Z"],
        "2026-10-23T23:00Z",
        "2026-10-22T23:00Z",
        "2026-10-22T23:30Z",
        ("2026-10-22T23:00Z", "2026-10-22T23:30Z", "2026-10-23T00:00Z", "2026-10-23T00:30Z"),
    ),
    (
        "daily-all-day",
        "once-a-day",
        "2026-10-25T01:30Z",
        ["2026-10-24T23:00Z"],
        "2026-10-26T00:00Z",
        "2026-10-24T23:00Z",
        "2026-10-24T23:30Z",
        ("2026-10-24T23:00Z", "2026-10-24T23:30Z", "2026-10-25T00:00Z", "2026-10-25T00:30Z"),
    ),
    (
        "daily-all-day",
        "twice-a-day",
        "2026-03-29T01:30Z",
        ["2026-03-29T00:00Z", "2026-03-29T13:00Z"],
        "2026-03-29T13:00Z",
        "2026-03-29T00:00Z",
        "2026-03-29T00:30Z",
        ("2026-03-29T00:00Z", "2026-03-29T00:30Z", "2026-03-29T01:00Z", "2026-03-29T01:30Z"),
    ),
    (
        "daily-all-day",
        "twice-a-day",
        "2026-03-29T09:45Z",
        ["2026-03-29T00:00Z", "2026-03-29T13:00Z"],
        "2026-03-29T13:00Z",
        "2026-03-29T00:00Z",
        "2026-03-29T00:30Z",
        ("2026-03-29T00:00Z", "2026-03-29T00:30Z", "2026-03-29T01:00Z", "2026-03-29T01:30Z"),
    ),
    (
        "daily-all-day",
        "twice-a-day",
        "2026-10-23T12:00Z",
        ["2026-10-22T23:00Z", "2026-10-23T13:00Z"],
        "2026-10-23T13:00Z",
        "2026-10-22T23:00Z",
        "2026-10-22T23:30Z",
        ("2026-10-22T23:00Z", "2026-10-22T23:30Z", "2026-10-23T00:00Z", "2026-10-23T00:30Z"),
    ),
    (
        "daily-all-day",
        "twice-a-day",
        "2026-10-25T01:30Z",
        ["2026-10-24T23:00Z", "2026-10-25T14:00Z"],
        "2026-10-25T14:00Z",
        "2026-10-24T23:00Z",
        "2026-10-24T23:30Z",
        ("2026-10-24T23:00Z", "2026-10-24T23:30Z", "2026-10-25T00:00Z", "2026-10-25T00:30Z"),
    ),
    (
        "daily-all-day",
        "every-2-hrs",
        "2026-03-29T01:30Z",
        [
            "2026-03-29T00:00Z",
            "2026-03-29T01:00Z",
            "2026-03-29T03:00Z",
            "2026-03-29T05:00Z",
            "2026-03-29T07:00Z",
            "2026-03-29T09:00Z",
            "2026-03-29T11:00Z",
            "2026-03-29T13:00Z",
            "2026-03-29T15:00Z",
            "2026-03-29T17:00Z",
            "2026-03-29T19:00Z",
            "2026-03-29T21:00Z",
        ],
        "2026-03-29T03:00Z",
        "2026-03-29T01:00Z",
        "2026-03-29T01:30Z",
        ("2026-03-29T01:00Z", "2026-03-29T01:30Z", "2026-03-29T02:00Z", "2026-03-29T02:30Z"),
    ),
    (
        "daily-all-day",
        "every-2-hrs",
        "2026-03-29T09:45Z",
        [
            "2026-03-29T00:00Z",
            "2026-03-29T01:00Z",
            "2026-03-29T03:00Z",
            "2026-03-29T05:00Z",
            "2026-03-29T07:00Z",
            "2026-03-29T09:00Z",
            "2026-03-29T11:00Z",
            "2026-03-29T13:00Z",
            "2026-03-29T15:00Z",
            "2026-03-29T17:00Z",
            "2026-03-29T19:00Z",
            "2026-03-29T21:00Z",
        ],
        "2026-03-29T11:00Z",
        "2026-03-29T09:00Z",
        "2026-03-29T09:30Z",
        ("2026-03-29T09:00Z", "2026-03-29T09:30Z", "2026-03-29T10:00Z", "2026-03-29T10:30Z"),
    ),
    (
        "daily-all-day",
        "every-2-hrs",
        "2026-10-23T12:00Z",
        [
            "2026-10-22T23:00Z",
            "2026-10-23T01:00Z",
            "2026-10-23T03:00Z",
            "2026-10-23T05:00Z",
            "2026-10-23T07:00Z",
            "2026-10-23T09:00Z",
            "2026-10-23T11:00Z",
            "2026-10-23T13:00Z",
            "2026-10-23T15:00Z",
            "2026-10-23T17:00Z",
            "2026-10-23T19:00Z",
            "2026-10-23T21:00Z",
        ],
        "2026-10-23T13:00Z",
        "2026-10-23T11:00Z",
        "2026-10-23T11:30Z",
        ("2026-10-23T11:00Z", "2026-10-23T11:30Z", "2026-10-23T12:00Z", "2026-10-23T12:30Z"),
    ),
    (
        "daily-all-day",
        "every-2-hrs",
        "2026-10-25T01:30Z",
        [
            "2026-10-24T23:00Z",
            "2026-10-25T02:00Z",
            "2026-10-25T04:00Z",
            "2026-10-25T06:00Z",
            "2026-10-25T08:00Z",
            "2026-10-25T10:00Z",
            "2026-10-25T12:00Z",
            "2026-10-25T14:00Z",
            "2026-10-25T16:00Z",
            "2026-10-25T18:00Z",
            "2026-10-25T20:00Z",
            "2026-10-25T22:00Z",
        ],
        "2026-10-25T02:00Z",
        "2026-10-24T23:00Z",
        "2026-10-24T23:30Z",
        ("2026-10-24T23:00Z", "2026-10-24T23:30Z", "2026-10-25T00:00Z", "2026-10-25T00:30Z"),
    ),
]


@pytest.mark.parametrize(
    ("name", "cadence", "now", "due_day", "next_at", "current_at", "reply_at", "ladder"),
    [
        (
            name,
            Cadence(cadence),
            at(now),
            [at(item) for item in due_day],
            None if next_at is None else at(next_at),
            None if current_at is None else at(current_at),
            None if reply_at is None else at(reply_at),
            None if ladder is None else tuple(at(item) for item in ladder),
        )
        for name, cadence, now, due_day, next_at, current_at, reply_at, ladder in GOLDEN_GRID
    ],
    ids=lambda value: str(value)[:40],
)
def test_golden_grid_matches_the_unmodified_rules(
    name: str,
    cadence: Cadence,
    now: datetime,
    due_day: list[datetime],
    next_at: datetime | None,
    current_at: datetime | None,
    reply_at: datetime | None,
    ladder: tuple[datetime, ...] | None,
) -> None:
    prof = GRID_PROFILES[name](cadence)
    day = to_london(now).date()
    for explicit in (False, True):
        extra = (DEFAULT_POLICY,) if explicit else ()
        assert due_times_on(prof, day, *extra) == due_day
        assert next_due(prof, now, *extra) == next_at
        assert current_due(prof, now, *extra) == current_at
        if current_at is not None:
            assert reply_by(current_at, *extra) == reply_at
            assert ladder is not None
            assert list(ladder_times(current_at, *extra).values()) == list(ladder)
        else:
            assert ladder is None


def test_the_golden_grid_has_at_least_forty_pairs_across_the_clock_changes() -> None:
    pairs = {(name, cadence, now) for name, cadence, now, *_ in GOLDEN_GRID}
    assert len(pairs) >= 40
    days = {to_london(at(now)).date() for _, _, now, *_ in GOLDEN_GRID}
    assert date(2026, 3, 29) in days and date(2026, 10, 25) in days
    assert {cadence for _, cadence, *_ in GOLDEN_GRID} == {c.value for c in Cadence}


# Test 2. reply_by takes the policy's reply window.


def test_reply_by_with_a_fifteen_minute_window_is_due_plus_fifteen() -> None:
    due = utc(2026, 10, 23, 13)
    assert reply_by(due, policy(reply_window=timedelta(minutes=15))) == due + timedelta(minutes=15)


def test_reply_by_default_argument_equals_the_explicit_default_policy() -> None:
    due = utc(2026, 10, 23, 13)
    assert reply_by(due) == reply_by(due, DEFAULT_POLICY) == due + timedelta(minutes=30)


# Test 3. The ladder takes the policy's offsets, in the four LadderStep keys in order.


def test_ladder_with_a_policy_uses_its_four_offsets_in_order() -> None:
    due = utc(2026, 10, 23, 13)
    tenant = policy(
        reply_window=timedelta(minutes=20),
        reminder_after=timedelta(minutes=25),
        phone_task_after=timedelta(minutes=50),
        escalate_after=timedelta(minutes=80),
    )
    ladder = ladder_times(due, tenant)
    assert list(ladder) == [
        LadderStep.PROMPT,
        LadderStep.REMINDER,
        LadderStep.PHONE_TASK,
        LadderStep.ESCALATE,
    ]
    assert list(ladder.values()) == [
        due,
        due + timedelta(minutes=25),
        due + timedelta(minutes=50),
        due + timedelta(minutes=80),
    ]


def test_ladder_default_is_plus_zero_thirty_sixty_ninety() -> None:
    due = utc(2026, 10, 23, 13)
    assert list(ladder_times(due).values()) == [
        due,
        due + timedelta(minutes=30),
        due + timedelta(minutes=60),
        due + timedelta(minutes=90),
    ]
    assert list(ladder_times(due)) == list(ladder_times(due, DEFAULT_POLICY))


# Test 4. Twice a day: the second time is the policy's, and it depends on when the window opens.


def _twice(start: time, end: time) -> ServiceProfile:
    return profile(AvailableTime.weekdays(start, end), cadence=Cadence.TWICE_A_DAY)


def test_twice_a_day_window_0800_to_2000_is_0800_and_1400_by_default() -> None:
    prof = _twice(time(8, 0), time(20, 0))
    assert due_times_on(prof, FRIDAY) == [
        utc_local(FRIDAY, time(8, 0)),
        utc_local(FRIDAY, time(14, 0)),
    ]


def test_twice_a_day_second_time_of_1530_gives_0800_and_1530() -> None:
    prof = _twice(time(8, 0), time(20, 0))
    tenant = policy(twice_a_day_second=time(15, 30))
    assert due_times_on(prof, FRIDAY, tenant) == [
        utc_local(FRIDAY, time(8, 0)),
        utc_local(FRIDAY, time(15, 30)),
    ]


def test_window_opening_after_1400_has_only_its_opening_by_default() -> None:
    prof = _twice(time(14, 30), time(20, 0))
    assert due_times_on(prof, FRIDAY) == [utc_local(FRIDAY, time(14, 30))]


def test_window_opening_at_1430_gets_1530_under_the_1530_policy() -> None:
    prof = _twice(time(14, 30), time(20, 0))
    assert due_times_on(prof, FRIDAY, policy(twice_a_day_second=time(15, 30))) == [
        utc_local(FRIDAY, time(14, 30)),
        utc_local(FRIDAY, time(15, 30)),
    ]


def test_window_opening_exactly_at_the_policy_second_time_gives_one_instant() -> None:
    prof = _twice(time(15, 30), time(20, 0))
    assert due_times_on(prof, FRIDAY, policy(twice_a_day_second=time(15, 30))) == [
        utc_local(FRIDAY, time(15, 30)),
    ]


# Test 5. Property: every policy, every day in the clock-change range.


CHANGE_DAYS: Final = st.one_of(
    st.just(date(2026, 3, 29)),
    st.just(date(2026, 10, 25)),
    st.dates(min_value=date(2026, 3, 23), max_value=date(2026, 10, 31)),
)
ANY_CADENCE: Final = st.sampled_from(list(Cadence))


def _expected_local_times(cadence: Cadence, day: date, second: time) -> list[tuple[date, time]]:
    """The naive London local due times of UCR West (weekdays 08:00 to 20:00) on one day."""
    if day.weekday() >= 5:
        return []
    if cadence is Cadence.ONCE_A_DAY:
        return [(day, time(8, 0))]
    if cadence is Cadence.TWICE_A_DAY:
        return [(day, time(8, 0)), (day, second)]
    return [(day, time(hour, 0)) for hour in range(8, 21, 2)]


@settings(max_examples=120, deadline=None)
@given(tenant=policies(), day=CHANGE_DAYS, cadence=ANY_CADENCE)
def test_due_times_are_sorted_unique_and_equal_the_expected_local_times(
    tenant: TenantPolicy, day: date, cadence: Cadence
) -> None:
    prof = GRID_PROFILES["weekday-0800-2000"](cadence)
    result = due_times_on(prof, day, tenant)
    assert result == sorted(set(result))
    expected = sorted(
        {
            london_to_utc(d, t)
            for d, t in _expected_local_times(cadence, day, tenant.twice_a_day_second)
        }
    )
    assert result == expected


@settings(max_examples=120, deadline=None)
@given(
    tenant=policies(),
    now=st.datetimes(min_value=datetime(2026, 3, 20), max_value=datetime(2026, 11, 3)).map(
        lambda naive: naive.replace(tzinfo=UTC)
    ),
    cadence=ANY_CADENCE,
)
def test_next_and_current_due_bracket_now_and_agree_with_their_neighbours(
    tenant: TenantPolicy, now: datetime, cadence: Cadence
) -> None:
    prof = GRID_PROFILES["weekday-0800-2000"](cadence)
    nxt = next_due(prof, now, tenant)
    cur = current_due(prof, now, tenant)
    assert nxt is not None and nxt > now
    assert cur is not None and cur <= now
    # No due time lies between cur and nxt, so the next due after cur is nxt.
    assert next_due(prof, cur, tenant) == nxt


# Test 6. next_due and current_due for a twice-a-day service that reports at 14:10.


def test_at_1410_next_due_is_monday_0800_by_default_and_1530_the_same_day_under_1530() -> None:
    prof = _twice(time(8, 0), time(20, 0))
    now = utc_local(FRIDAY, time(14, 10))
    assert next_due(prof, now) == utc_local(MONDAY_AFTER_CHANGE, time(8, 0))
    tenant = policy(twice_a_day_second=time(15, 30))
    assert next_due(prof, now, tenant) == utc_local(FRIDAY, time(15, 30))


def test_at_1410_current_due_is_1400_by_default_and_0800_under_1530() -> None:
    prof = _twice(time(8, 0), time(20, 0))
    now = utc_local(FRIDAY, time(14, 10))
    assert current_due(prof, now) == utc_local(FRIDAY, time(14, 0))
    assert current_due(prof, now, policy(twice_a_day_second=time(15, 30))) == utc_local(
        FRIDAY, time(8, 0)
    )


# Test 23 (schedule part). The aliases are the default policy's own objects.


def test_schedule_constants_are_the_default_policy_values() -> None:
    assert timedelta(minutes=30) == REPLY_WINDOW
    assert timedelta(minutes=30) == REMINDER_AFTER
    assert timedelta(minutes=60) == PHONE_TASK_AFTER
    assert timedelta(minutes=90) == ESCALATE_AFTER
    assert time(14, 0) == TWICE_A_DAY_SECOND


def test_schedule_constants_are_the_default_policy_objects() -> None:
    assert schedule_rules.REPLY_WINDOW is DEFAULT_POLICY.reply_window
    assert schedule_rules.REMINDER_AFTER is DEFAULT_POLICY.reminder_after
    assert schedule_rules.PHONE_TASK_AFTER is DEFAULT_POLICY.phone_task_after
    assert schedule_rules.ESCALATE_AFTER is DEFAULT_POLICY.escalate_after
    assert schedule_rules.TWICE_A_DAY_SECOND is DEFAULT_POLICY.twice_a_day_second


# Rule 4(d): with no policy argument, every function equals the call with DEFAULT_POLICY.


@settings(max_examples=60, deadline=None)
@given(
    now=st.datetimes(min_value=datetime(2026, 3, 20), max_value=datetime(2026, 11, 3)).map(
        lambda naive: naive.replace(tzinfo=UTC)
    ),
    cadence=ANY_CADENCE,
)
def test_no_policy_argument_equals_the_default_policy_argument(
    now: datetime, cadence: Cadence
) -> None:
    prof = GRID_PROFILES["weekday-0800-1200"](cadence)
    day = to_london(now).date()
    assert due_times_on(prof, day) == due_times_on(prof, day, DEFAULT_POLICY)
    assert next_due(prof, now) == next_due(prof, now, DEFAULT_POLICY)
    assert current_due(prof, now) == current_due(prof, now, DEFAULT_POLICY)
    assert reply_by(now) == reply_by(now, DEFAULT_POLICY)
    assert ladder_times(now) == ladder_times(now, DEFAULT_POLICY)
