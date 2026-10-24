"""Tests for diucs.domain.rules.opening_hours: is a service in hours, and when it next opens (D03).

Rules from docs/spec/domain-rules.md 1.3 (rule 2) and the D03 prompt. Windows are London local.
A window with start < end covers start <= t < end on each listed day. An end earlier than the
start is overnight and runs into the next morning. All day covers each listed day in full.
Days are 0 = Monday to 6 = Sunday. The clock changes are 2026-03-29 and 2026-10-25; the gap
(local 01:00 to 02:00 on 2026-03-29) is compared by instant, never by local time (lesson L4).
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from diucs.domain.model.service import AvailableTime
from diucs.domain.rules.london_time import london_to_utc, to_london
from diucs.domain.rules.opening_hours import is_in_hours, next_opening

ALL_DAYS = frozenset(range(7))
WEEKDAYS = frozenset({0, 1, 2, 3, 4})
SPRING_CHANGE = date(2026, 3, 29)
AUTUMN_CHANGE = date(2026, 10, 25)

# UCR West (sample service from the spec): Monday to Friday 08:00 to 20:00 London local.
UCR_WEST = [AvailableTime.weekdays(time(8, 0), time(20, 0))]


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def timed(days: frozenset[int], start: time, end: time) -> AvailableTime:
    return AvailableTime(days=days, all_day=False, start=start, end=end)


# Rule 1 and 2: timed windows, end exclusive, sample service UCR West.


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 10, 23, 13, 12), True),  # Fri 14:12 BST, mid-window
        (utc(2026, 10, 23, 6, 59), False),  # Fri 07:59 BST, one minute before opening
        (utc(2026, 10, 23, 7, 0), True),  # Fri 08:00 BST, opening is inclusive
        (utc(2026, 10, 23, 19, 0), False),  # Fri 20:00 BST, closing is exclusive
        (utc(2026, 10, 23, 18, 59), True),  # Fri 19:59 BST, last minute open
        (utc(2026, 10, 24, 12, 0), False),  # Sat 13:00 BST, weekend is closed
    ],
)
def test_ucr_west_weekday_hours(now: datetime, expected: bool) -> None:
    assert is_in_hours(UCR_WEST, now) is expected


def test_saturday_next_opening_is_monday_0800_after_the_clock_change() -> None:
    # Sat 2026-10-24 12:00Z. Monday 2026-10-26 08:00 is GMT by then, so 08:00Z.
    assert next_opening(UCR_WEST, utc(2026, 10, 24, 12, 0)) == utc(2026, 10, 26, 8, 0)


def test_friday_before_opening_next_opening_is_0800_bst() -> None:
    # Fri 05:00Z is 06:00 BST; the window opens 08:00 BST, which is 07:00Z.
    assert next_opening(UCR_WEST, utc(2026, 10, 23, 5, 0)) == utc(2026, 10, 23, 7, 0)


def test_two_windows_weekday_and_saturday_morning() -> None:
    times = [
        AvailableTime.weekdays(time(8, 0), time(20, 0)),
        timed(frozenset({5}), time(9, 0), time(13, 0)),
    ]
    assert is_in_hours(times, utc(2026, 10, 24, 9, 30)) is True  # Sat 10:30 BST
    assert is_in_hours(times, utc(2026, 10, 24, 13, 30)) is False  # Sat 14:30 BST


# Rule 5: a service that spans the clock change. Window 08:00 to 20:00 every day.


def test_every_day_window_across_the_autumn_change() -> None:
    times = [AvailableTime.every_day(time(8, 0), time(20, 0))]
    assert is_in_hours(times, utc(2026, 10, 25, 7, 30)) is False  # 07:30 GMT
    assert is_in_hours(times, utc(2026, 10, 25, 8, 0)) is True  # 08:00 GMT


def test_every_day_window_across_the_spring_change() -> None:
    times = [AvailableTime.every_day(time(8, 0), time(20, 0))]
    assert is_in_hours(times, utc(2026, 3, 29, 7, 30)) is True  # 08:30 BST


# Rule 6 and 7: overnight windows.


def test_overnight_ward_every_day_covers_the_small_hours() -> None:
    times = [AvailableTime.every_day(time(20, 0), time(8, 0))]
    assert is_in_hours(times, utc(2026, 10, 24, 1, 40)) is True  # Sat 02:40 BST
    assert is_in_hours(times, utc(2026, 10, 24, 12, 0)) is False  # Sat 13:00 BST


def test_overnight_on_friday_only_runs_into_saturday_morning() -> None:
    times = [timed(frozenset({4}), time(20, 0), time(8, 0))]
    assert is_in_hours(times, utc(2026, 10, 24, 6, 0)) is True  # Sat 07:00 BST, Friday's window
    assert is_in_hours(times, utc(2026, 10, 25, 6, 0)) is False  # Sun 06:00 GMT, not listed


def test_overnight_window_is_not_open_on_its_listed_day_before_start() -> None:
    times = [timed(frozenset({4}), time(20, 0), time(8, 0))]
    assert is_in_hours(times, utc(2026, 10, 23, 18, 0)) is False  # Fri 19:00 BST, before 20:00


# Rule 8: all day.


def test_all_day_every_day_is_always_in_hours() -> None:
    times = [AvailableTime.every_day_all_day()]
    for now in [utc(2026, 10, 24, 0, 0), utc(2026, 10, 24, 23, 59), utc(2026, 3, 29, 0, 30)]:
        assert is_in_hours(times, now) is True


def test_all_day_every_day_never_opens() -> None:
    assert next_opening([AvailableTime.every_day_all_day()], utc(2026, 10, 24, 12, 0)) is None


def test_all_day_on_listed_days_only() -> None:
    times = [AvailableTime(days=frozenset({0}), all_day=True, start=None, end=None)]
    assert is_in_hours(times, utc(2026, 10, 26, 12, 0)) is True  # Mon 12:00 GMT
    assert is_in_hours(times, utc(2026, 10, 27, 12, 0)) is False  # Tue 12:00 GMT


def test_next_opening_from_sunday_for_a_monday_all_day_service_is_monday_midnight() -> None:
    times = [AvailableTime(days=frozenset({0}), all_day=True, start=None, end=None)]
    assert next_opening(times, utc(2026, 10, 25, 12, 0)) == utc(2026, 10, 26, 0, 0)


# Spring gap: local 01:00 to 02:00 on 2026-03-29 does not exist. Compare instants (L4).
# Window 00:30 to 03:00 every day: opens 00:30 GMT (00:30Z), closes 03:00 BST (02:00Z).


def test_window_across_the_spring_gap_compares_instants() -> None:
    times = [AvailableTime.every_day(time(0, 30), time(3, 0))]
    assert is_in_hours(times, utc(2026, 3, 29, 0, 29)) is False
    assert is_in_hours(times, utc(2026, 3, 29, 0, 30)) is True
    assert is_in_hours(times, utc(2026, 3, 29, 1, 59)) is True  # 02:59 BST
    assert is_in_hours(times, utc(2026, 3, 29, 2, 0)) is False  # 03:00 BST, end exclusive


def test_window_starting_inside_the_spring_gap_maps_to_one_instant() -> None:
    # Local 01:30 on the gap day does not exist. london_to_utc shifts it forward to 02:30 BST.
    assert london_to_utc(SPRING_CHANGE, time(1, 30)) == utc(2026, 3, 29, 1, 30)


def test_next_opening_from_before_the_spring_gap_is_the_gap_start_instant() -> None:
    times = [AvailableTime.every_day(time(1, 30), time(4, 0))]
    assert next_opening(times, utc(2026, 3, 29, 0, 0)) == utc(2026, 3, 29, 1, 30)


# Rule 9 and 10: next_opening.


def test_next_opening_mid_window_is_the_next_days_opening() -> None:
    # Fri 14:00 BST is inside the window; the next start is Monday 08:00 GMT.
    assert next_opening(UCR_WEST, utc(2026, 10, 23, 13, 0)) == utc(2026, 10, 26, 8, 0)


def test_next_opening_is_strictly_after_now() -> None:
    # Fri 07:00Z is exactly the opening instant; the next one is Monday, not now.
    assert next_opening(UCR_WEST, utc(2026, 10, 23, 7, 0)) == utc(2026, 10, 26, 8, 0)


def test_next_opening_is_none_when_there_are_no_windows() -> None:
    assert next_opening([], utc(2026, 10, 23, 7, 0)) is None


def test_no_windows_is_never_in_hours() -> None:
    assert is_in_hours([], utc(2026, 10, 23, 12, 0)) is False


def test_adjacent_windows_do_not_count_as_an_opening_at_the_join() -> None:
    # Mon 08:00 to 12:00, then 12:00 to 20:00. The service never closes at 12:00, so from
    # Mon 09:00 the next opening is Tuesday 08:00, not Monday 12:00.
    times = [
        timed(frozenset({0}), time(8, 0), time(12, 0)),
        timed(frozenset({0}), time(12, 0), time(20, 0)),
    ]
    assert next_opening(times, utc(2026, 10, 26, 9, 0)) == utc(2026, 11, 2, 8, 0)


def test_adjacent_windows_stay_in_hours_across_the_join() -> None:
    times = [
        timed(frozenset({0}), time(8, 0), time(12, 0)),
        timed(frozenset({0}), time(12, 0), time(20, 0)),
    ]
    assert is_in_hours(times, utc(2026, 10, 26, 11, 59)) is True  # 11:59 GMT
    assert is_in_hours(times, utc(2026, 10, 26, 12, 0)) is True  # 12:00 GMT


# Naive datetimes are a bug: reject them.


def test_is_in_hours_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError):
        is_in_hours(UCR_WEST, datetime(2026, 10, 23, 12, 0))


def test_next_opening_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError):
        next_opening(UCR_WEST, datetime(2026, 10, 23, 12, 0))


# Property tests. The oracle reads the local wall clock of the instant. Windows whose bounds
# fall in the 01:00 to 02:00 hour on a change day are excluded, because the wall clock is
# ambiguous or missing there. Instants in that hour are still tested.


def ambiguous_hour(bound: time) -> bool:
    return time(1, 0) <= bound < time(2, 0)


def oracle_in_hours(days: frozenset[int], start: time, end: time, now: datetime) -> bool:
    local = to_london(now)
    minute = time(local.hour, local.minute)
    previous = local.date() - timedelta(days=1)
    if start < end:
        return local.weekday() in days and start <= minute < end
    # Overnight: this morning belongs to yesterday's window; the evening to today's.
    if local.weekday() in days and minute >= start:
        return True
    return previous.weekday() in days and minute < end


@given(
    days=st.frozensets(st.integers(0, 6), min_size=1),
    start_minute=st.integers(0, 1439),
    end_minute=st.integers(0, 1439),
    now=st.datetimes(
        min_value=datetime(2026, 3, 20),
        max_value=datetime(2026, 11, 5),
        timezones=st.just(UTC),
    ),
)
def test_timed_window_matches_the_local_wall_clock_oracle(
    days: frozenset[int], start_minute: int, end_minute: int, now: datetime
) -> None:
    assume(start_minute != end_minute)
    start = time(start_minute // 60, start_minute % 60)
    end = time(end_minute // 60, end_minute % 60)
    assume(not any(ambiguous_hour(bound) for bound in (start, end)))
    window = timed(days, start, end)
    assert is_in_hours([window], now) is oracle_in_hours(days, start, end, now)


@given(
    days=st.frozensets(st.integers(0, 6), min_size=1),
    start_minute=st.integers(0, 1439),
    end_minute=st.integers(0, 1439),
    now=st.datetimes(
        min_value=datetime(2026, 3, 20),
        max_value=datetime(2026, 11, 5),
        timezones=st.just(UTC),
    ),
)
def test_next_opening_is_a_real_opening_strictly_after_now(
    days: frozenset[int], start_minute: int, end_minute: int, now: datetime
) -> None:
    assume(start_minute != end_minute)
    start = time(start_minute // 60, start_minute % 60)
    end = time(end_minute // 60, end_minute % 60)
    assume(not any(ambiguous_hour(bound) for bound in (start, end)))
    times = [timed(days, start, end)]
    opening = next_opening(times, now)
    assert opening is not None
    assert opening > now
    assert opening.tzinfo is not None and opening.utcoffset() == timedelta(0)
    assert is_in_hours(times, opening) is True
    assert is_in_hours(times, opening - timedelta(microseconds=1)) is False
