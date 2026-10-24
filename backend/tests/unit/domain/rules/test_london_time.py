"""London local time rules: conversion across the 2026 clock changes, and formatting."""

from datetime import UTC, date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.rules.london_time import LONDON, format_hhmm, london_to_utc, to_london

SPRING_CHANGE = date(2026, 3, 29)
AUTUMN_CHANGE = date(2026, 10, 25)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def last_sunday_of(year: int, month: int) -> date:
    last_day = date(year, month, 31)  # March and October both have 31 days
    return last_day - timedelta(days=(last_day.weekday() + 1) % 7)


def is_spring_gap(day: date, local: time) -> bool:
    return day == last_sunday_of(day.year, 3) and time(1, 0) <= local < time(2, 0)


def test_london_zone_is_europe_london() -> None:
    assert ZoneInfo("Europe/London") == LONDON


def test_clock_change_dates_used_by_the_tests_are_the_last_sundays() -> None:
    assert last_sunday_of(2026, 3) == SPRING_CHANGE
    assert last_sunday_of(2026, 10) == AUTUMN_CHANGE


@pytest.mark.parametrize(
    ("day", "local", "expected"),
    [
        (date(2026, 1, 15), time(10, 0), utc(2026, 1, 15, 10, 0)),
        (date(2026, 7, 1), time(10, 0), utc(2026, 7, 1, 9, 0)),
        # Gap: 01:30 does not exist on 2026-03-29; shifted forward to 02:30 BST.
        (SPRING_CHANGE, time(1, 30), utc(2026, 3, 29, 1, 30)),
        # Fold: 01:30 happens twice on 2026-10-25; the first occurrence (BST) is used.
        (AUTUMN_CHANGE, time(1, 30), utc(2026, 10, 25, 0, 30)),
        # Same local time either side of the autumn change keeps its wall-clock value.
        (date(2026, 10, 24), time(10, 0), utc(2026, 10, 24, 9, 0)),
        (date(2026, 10, 26), time(10, 0), utc(2026, 10, 26, 10, 0)),
    ],
)
def test_london_to_utc_examples(day: date, local: time, expected: datetime) -> None:
    result = london_to_utc(day, local)
    assert result == expected
    assert result.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("local", "expected"),
    [
        (time(1, 0), utc(2026, 10, 25, 0, 0)),  # first 01:00 is BST
        (time(1, 59), utc(2026, 10, 25, 0, 59)),
        (time(2, 0), utc(2026, 10, 25, 2, 0)),  # after the fold, GMT
    ],
)
def test_autumn_fold_and_the_hour_after_it(local: time, expected: datetime) -> None:
    assert london_to_utc(AUTUMN_CHANGE, local) == expected


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (utc(2026, 10, 23, 13, 19), "14:19"),
        (utc(2026, 1, 13, 13, 19), "13:19"),
    ],
)
def test_format_hhmm_uses_london_wall_clock(instant: datetime, expected: str) -> None:
    assert format_hhmm(instant) == expected


def test_to_london_converts_to_london_wall_clock() -> None:
    local = to_london(utc(2026, 7, 1, 9, 0))
    assert local.hour == 10
    assert local.utcoffset() == timedelta(hours=1)


@pytest.mark.parametrize(
    "naive",
    [datetime(2026, 1, 15, 10, 0), datetime(2026, 10, 25, 1, 30)],
)
def test_naive_datetime_is_rejected(naive: datetime) -> None:
    with pytest.raises(ValueError):
        to_london(naive)
    with pytest.raises(ValueError):
        format_hhmm(naive)


def test_aware_time_of_day_is_rejected() -> None:
    with pytest.raises(ValueError):
        london_to_utc(date(2026, 1, 15), time(10, 0, tzinfo=UTC))


minutes_of_day = st.integers(min_value=0, max_value=23 * 60 + 59).map(
    lambda m: time(m // 60, m % 60)
)
london_days = st.dates(min_value=date(2020, 1, 1), max_value=date(2035, 12, 31))


@given(day=london_days, local=minutes_of_day)
def test_result_is_always_aware_utc(day: date, local: time) -> None:
    assert london_to_utc(day, local).utcoffset() == timedelta(0)


@given(day=london_days, local=minutes_of_day)
def test_wall_clock_is_kept_outside_the_spring_gap(day: date, local: time) -> None:
    if is_spring_gap(day, local):
        return
    assert to_london(london_to_utc(day, local)).replace(tzinfo=None) == datetime.combine(day, local)


@given(day=london_days, local=minutes_of_day)
def test_spring_gap_is_shifted_forward_one_hour(day: date, local: time) -> None:
    if not is_spring_gap(day, local):
        return
    shifted = datetime.combine(day, local) + timedelta(hours=1)
    assert to_london(london_to_utc(day, local)).replace(tzinfo=None) == shifted


@given(day=london_days, first=minutes_of_day, second=minutes_of_day)
def test_conversion_is_monotonic_within_a_day_outside_the_gap(
    day: date, first: time, second: time
) -> None:
    if is_spring_gap(day, first) or is_spring_gap(day, second) or first >= second:
        return
    assert london_to_utc(day, first) < london_to_utc(day, second)


@given(local=minutes_of_day)
def test_format_hhmm_round_trips_a_summer_wall_clock_time(local: time) -> None:
    instant = london_to_utc(date(2026, 7, 1), local)
    assert format_hhmm(instant) == local.strftime("%H:%M")


class _TzWithoutOffset(tzinfo):
    def utcoffset(self, dt: datetime | None) -> None:
        return None

    def dst(self, dt: datetime | None) -> None:
        return None


def test_datetime_whose_offset_is_unknown_is_rejected() -> None:
    unknown = datetime(2026, 7, 1, 9, 0, tzinfo=_TzWithoutOffset())
    with pytest.raises(ValueError):
        to_london(unknown)
    with pytest.raises(ValueError):
        format_hhmm(unknown)
