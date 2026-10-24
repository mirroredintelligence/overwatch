"""Tests for diucs.domain.model.service: the service reporting profile (D01).

Rules from docs/spec/domain-rules.md section 1.1 and the D01 prompt. Days are 0 = Monday to
6 = Sunday. An end earlier than the start is an overnight window. The end is exclusive.
"""

import dataclasses
from collections.abc import Callable
from datetime import UTC, time
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import Cadence, Channel, Measure, ServiceCategory
from diucs.domain.errors import DomainError, ValidationFailed
from diucs.domain.model.service import AvailableTime, ServiceProfile

ALL_DAYS = frozenset(range(7))
WEEKDAYS = frozenset({0, 1, 2, 3, 4})


def assert_field(field: str, build: Callable[[], object]) -> None:
    with pytest.raises(ValidationFailed) as info:
        build()
    assert info.value.field == field


def timed(days: Any, start: Any, end: Any, all_day: bool = False) -> AvailableTime:
    return AvailableTime(days=days, all_day=all_day, start=start, end=end)


def ucr_west(**overrides: Any) -> ServiceProfile:
    fields: dict[str, Any] = {
        "id": "svc-ucr-west",
        "name": "UCR West",
        "category": ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        "measure": Measure.REFERRALS_ACCEPTABLE,
        "unit_label": "referrals in the next 2 hrs",
        "established_capacity": 8,
        "can_exceed_established": False,
        "usual_range": (0, 8),
        "cadence": Cadence.EVERY_2_HRS,
        "available_times": (AvailableTime.weekdays(time(8, 0), time(20, 0)),),
        "channel": Channel.TEXT,
    }
    fields.update(overrides)
    return ServiceProfile(**fields)


# --- UCR West builds with Mon-Fri 08:00-20:00 -------------------------------------------------


def test_ucr_west_builds_with_its_weekday_hours() -> None:
    profile = ucr_west()
    assert profile.available_times[0].days == frozenset({0, 1, 2, 3, 4})
    assert profile.available_times[0].start == time(8, 0)
    assert profile.available_times[0].end == time(20, 0)
    assert profile.usual_range == (0, 8)


def test_defaults_are_applied() -> None:
    profile = ucr_west()
    assert profile.limited_level_percent == 80
    assert profile.active is True
    assert profile.suspended is False
    assert profile.comment == ""


# --- Days -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "days",
    [frozenset(), frozenset({7}), frozenset({-1}), frozenset({0, 7}), frozenset({0, 9})],
)
def test_days_outside_zero_to_six_or_empty_are_rejected(days: frozenset[int]) -> None:
    assert_field("days", lambda: timed(days, time(8), time(20)))


def test_days_must_be_a_frozenset_so_the_value_stays_hashable() -> None:
    assert_field("days", lambda: timed({0, 1}, time(8), time(20)))


def test_bool_is_not_an_accepted_day_number() -> None:
    assert_field("days", lambda: timed(frozenset({True}), time(8), time(20)))


# --- All-day, start and end -------------------------------------------------------------------


def test_all_day_with_a_start_is_rejected_at_start() -> None:
    assert_field("start", lambda: timed(ALL_DAYS, time(8), None, all_day=True))


def test_all_day_with_an_end_is_rejected_at_end() -> None:
    assert_field("end", lambda: timed(ALL_DAYS, None, time(20), all_day=True))


def test_all_day_with_no_times_is_accepted() -> None:
    window = timed(ALL_DAYS, None, None, all_day=True)
    assert window.all_day is True
    assert window.start is None
    assert window.end is None


def test_timed_window_without_an_end_is_rejected_at_end() -> None:
    assert_field("end", lambda: timed(WEEKDAYS, time(8), None))


def test_timed_window_without_a_start_is_rejected_at_start() -> None:
    assert_field("start", lambda: timed(WEEKDAYS, None, time(20)))


def test_start_equal_to_end_is_rejected_at_end() -> None:
    assert_field("end", lambda: timed(WEEKDAYS, time(8), time(8)))


def test_overnight_window_is_accepted() -> None:
    window = timed(ALL_DAYS, time(20), time(8))
    assert window.start == time(20)
    assert window.end == time(8)


def test_times_with_a_timezone_are_rejected_because_window_times_are_london_local() -> None:
    assert_field("start", lambda: timed(WEEKDAYS, time(8, tzinfo=UTC), time(20)))
    assert_field("end", lambda: timed(WEEKDAYS, time(8), time(20, tzinfo=UTC)))


# --- Helpers ----------------------------------------------------------------------------------


def test_weekdays_helper_is_monday_to_friday_with_the_given_hours() -> None:
    assert AvailableTime.weekdays(time(8, 0), time(20, 0)) == timed(
        WEEKDAYS, time(8, 0), time(20, 0)
    )


def test_every_day_helper_covers_all_seven_days() -> None:
    window = AvailableTime.every_day(time(9, 0), time(17, 0))
    assert window.days == ALL_DAYS
    assert window.all_day is False
    assert window.start == time(9, 0)
    assert window.end == time(17, 0)


def test_every_day_all_day_helper_has_no_times() -> None:
    assert AvailableTime.every_day_all_day() == timed(ALL_DAYS, None, None, all_day=True)


# --- Capacity, range, percent, names ----------------------------------------------------------


@pytest.mark.parametrize("capacity", [0, -1])
def test_established_capacity_below_one_is_rejected(capacity: int) -> None:
    assert_field("established_capacity", lambda: ucr_west(established_capacity=capacity))


def test_established_capacity_of_one_is_accepted() -> None:
    assert ucr_west(established_capacity=1).established_capacity == 1


@pytest.mark.parametrize("usual_range", [(9, 8), (-1, 8)])
def test_usual_range_must_be_ordered_and_non_negative(usual_range: tuple[int, int]) -> None:
    assert_field("usual_range", lambda: ucr_west(usual_range=usual_range))


def test_usual_range_of_a_single_value_is_accepted() -> None:
    assert ucr_west(usual_range=(0, 0)).usual_range == (0, 0)


@pytest.mark.parametrize("percent", [0, 101, -5])
def test_limited_level_percent_outside_one_to_hundred_is_rejected(percent: int) -> None:
    assert_field("limited_level_percent", lambda: ucr_west(limited_level_percent=percent))


@pytest.mark.parametrize("percent", [1, 80, 100])
def test_limited_level_percent_inside_one_to_hundred_is_accepted(percent: int) -> None:
    assert ucr_west(limited_level_percent=percent).limited_level_percent == percent


@pytest.mark.parametrize("name", ["", "   "])
def test_blank_name_is_rejected(name: str) -> None:
    assert_field("name", lambda: ucr_west(name=name))


def test_blank_unit_label_is_rejected() -> None:
    assert_field("unit_label", lambda: ucr_west(unit_label=""))


def test_blank_id_is_rejected() -> None:
    assert_field("id", lambda: ucr_west(id=""))


def test_empty_available_times_is_rejected() -> None:
    assert_field("available_times", lambda: ucr_west(available_times=()))


def test_every_failure_is_a_domain_error_naming_the_field() -> None:
    with pytest.raises(DomainError) as info:
        ucr_west(established_capacity=0)
    assert isinstance(info.value, ValidationFailed)
    assert info.value.field == "established_capacity"


# --- Type guards: wrong kinds of value are rejected, never coerced ----------------------------


@pytest.mark.parametrize("capacity", ["8", 8.0, True])
def test_established_capacity_must_be_a_whole_number(capacity: Any) -> None:
    assert_field("established_capacity", lambda: ucr_west(established_capacity=capacity))


@pytest.mark.parametrize("percent", ["80", 80.0, True])
def test_limited_level_percent_must_be_a_whole_number(percent: Any) -> None:
    assert_field("limited_level_percent", lambda: ucr_west(limited_level_percent=percent))


@pytest.mark.parametrize("usual_range", [(0,), (0, 8, 9), [0, 8], ("0", 8), (0, True)])
def test_usual_range_must_be_a_pair_of_whole_numbers(usual_range: Any) -> None:
    assert_field("usual_range", lambda: ucr_west(usual_range=usual_range))


@pytest.mark.parametrize("value", [None, 7, b"UCR West"])
def test_text_fields_must_be_strings(value: Any) -> None:
    assert_field("name", lambda: ucr_west(name=value))


def test_available_times_must_be_a_tuple_of_available_time_values() -> None:
    window = AvailableTime.weekdays(time(8, 0), time(20, 0))
    assert_field("available_times", lambda: ucr_west(available_times=[window]))
    assert_field("available_times", lambda: ucr_west(available_times=(object(),)))


@pytest.mark.parametrize("days", [frozenset({"1"}), frozenset({1.0})])
def test_day_numbers_must_be_integers(days: Any) -> None:
    assert_field("days", lambda: timed(days, time(8), time(20)))


@pytest.mark.parametrize("value", ["08:00", 8])
def test_window_times_must_be_time_values(value: Any) -> None:
    assert_field("start", lambda: timed(WEEKDAYS, value, time(20)))
    assert_field("end", lambda: timed(WEEKDAYS, time(8), value))


# --- Frozen and hashable ----------------------------------------------------------------------


def test_profile_is_frozen() -> None:
    profile = ucr_west()
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.name = "Other"  # type: ignore[misc]


def test_profile_and_window_are_hashable_and_equal_values_hash_equal() -> None:
    first = ucr_west()
    second = ucr_west()
    assert first == second
    assert hash(first) == hash(second)
    assert len({first, second}) == 1
    assert hash(first.available_times[0]) == hash(second.available_times[0])


# --- Property tests ---------------------------------------------------------------------------

MINUTES = st.integers(min_value=0, max_value=23 * 60 + 59)


def to_time(total: int) -> time:
    return time(total // 60, total % 60)


@given(start=MINUTES, end=MINUTES)
def test_any_timed_window_is_accepted_unless_start_equals_end(start: int, end: int) -> None:
    if start == end:
        assert_field("end", lambda: timed(WEEKDAYS, to_time(start), to_time(end)))
        return
    window = timed(WEEKDAYS, to_time(start), to_time(end))
    assert window.start == to_time(start)
    assert window.end == to_time(end)


@given(capacity=st.integers(min_value=-1000, max_value=1000))
def test_established_capacity_is_valid_exactly_when_at_least_one(capacity: int) -> None:
    if capacity >= 1:
        assert ucr_west(established_capacity=capacity).established_capacity == capacity
    else:
        assert_field("established_capacity", lambda: ucr_west(established_capacity=capacity))


@given(percent=st.integers(min_value=-500, max_value=500))
def test_limited_level_percent_is_valid_exactly_from_one_to_hundred(percent: int) -> None:
    if 1 <= percent <= 100:
        assert ucr_west(limited_level_percent=percent).limited_level_percent == percent
    else:
        assert_field("limited_level_percent", lambda: ucr_west(limited_level_percent=percent))


@given(low=st.integers(min_value=-50, max_value=50), high=st.integers(min_value=-50, max_value=50))
def test_usual_range_is_valid_exactly_when_ordered_and_non_negative(low: int, high: int) -> None:
    if 0 <= low <= high:
        assert ucr_west(usual_range=(low, high)).usual_range == (low, high)
    else:
        assert_field("usual_range", lambda: ucr_west(usual_range=(low, high)))
