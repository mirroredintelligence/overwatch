"""London local time rules: conversion across the 2026 clock changes, and formatting."""

from datetime import UTC, date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.london_time import (
    LONDON,
    format_hhmm,
    format_stamp,
    local_to_utc,
    london_to_utc,
    require_zone,
    to_local,
    to_london,
    zone_named,
)

SPRING_CHANGE = date(2026, 3, 29)
AUTUMN_CHANGE = date(2026, 10, 25)
CHANGE_DAYS = [SPRING_CHANGE, AUTUMN_CHANGE]


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def last_sunday_of(year: int, month: int) -> date:
    last_day = date(year, month, 31)  # March and October both have 31 days
    return last_day - timedelta(days=(last_day.weekday() + 1) % 7)


def is_spring_gap(day: date, local: time) -> bool:
    """True when wall-clock time `local` does not exist on `day` because the clocks went forward.

    Derived from the zone: a spring change day is one where the UTC offset is GMT at 00:30 local
    and BST at 02:30 local. The gap is 01:00 to 02:00 local on such a day.
    """
    if not time(1, 0) <= local < time(2, 0):
        return False
    return london_offset(day, time(0, 30)) < london_offset(day, time(2, 30))


def london_offset(day: date, local: time) -> timedelta:
    offset = datetime.combine(day, local, tzinfo=ZoneInfo("Europe/London")).utcoffset()
    assert offset is not None
    return offset


def is_change_day(day: date) -> bool:
    """A London day is a change day when its UTC offset at 00:00 differs from its offset at 23:59.

    Derived from the zone itself, so it holds for every year the zone database covers.
    """
    return london_offset(day, time(0, 0)) != london_offset(day, time(23, 59))


def minute_to_time(minute: int) -> time:
    return time(minute // 60, minute % 60)


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
        (time(0, 59), utc(2026, 3, 29, 0, 59)),
        (time(1, 0), utc(2026, 3, 29, 1, 0)),  # gap: shifted to 02:00 BST
        (time(1, 59), utc(2026, 3, 29, 1, 59)),  # gap: shifted to 02:59 BST
        (time(2, 0), utc(2026, 3, 29, 1, 0)),  # 02:00 BST: same instant as local 01:00
        (time(10, 0), utc(2026, 3, 29, 9, 0)),  # after the change: BST
    ],
)
def test_spring_day_boundaries(local: time, expected: datetime) -> None:
    assert london_to_utc(SPRING_CHANGE, local) == expected


@pytest.mark.parametrize(
    ("local", "expected"),
    [
        (time(0, 59), utc(2026, 10, 24, 23, 59)),  # still BST before the fold
        (time(1, 59), utc(2026, 10, 25, 0, 59)),  # first occurrence, BST
        (time(2, 0), utc(2026, 10, 25, 2, 0)),  # GMT after the fold
        (time(2, 59), utc(2026, 10, 25, 2, 59)),
    ],
)
def test_autumn_day_boundaries(local: time, expected: datetime) -> None:
    assert london_to_utc(AUTUMN_CHANGE, local) == expected


def test_spring_day_every_minute_hits_each_branch_as_specified() -> None:
    gap_hits = 0
    for minute in range(24 * 60):
        local = minute_to_time(minute)
        result = london_to_utc(SPRING_CHANGE, local)
        naive_as_utc = datetime.combine(SPRING_CHANGE, local, tzinfo=UTC)
        if 60 <= minute < 120:
            gap_hits += 1
            assert result == naive_as_utc, local  # gap: wall time is kept as the UTC reading
            wall = to_london(result).replace(tzinfo=None)
            assert wall == datetime.combine(SPRING_CHANGE, local) + timedelta(hours=1), local
        elif minute < 60:
            assert result == naive_as_utc, local  # GMT before the change
        else:
            assert result == naive_as_utc - timedelta(hours=1), local  # BST after the change
    assert gap_hits == 60, "the gap branch was not exercised for all 60 gap minutes"


def test_autumn_day_every_minute_hits_each_branch_as_specified() -> None:
    fold_hits = 0
    for minute in range(24 * 60):
        local = minute_to_time(minute)
        result = london_to_utc(AUTUMN_CHANGE, local)
        naive_as_utc = datetime.combine(AUTUMN_CHANGE, local, tzinfo=UTC)
        if 60 <= minute < 120:
            fold_hits += 1
            assert result == naive_as_utc - timedelta(hours=1), local  # first occurrence, BST
        elif minute < 60:
            assert result == naive_as_utc - timedelta(hours=1), local  # still BST
        else:
            assert result == naive_as_utc, local  # GMT after the fold
    assert fold_hits == 60, "the fold branch was not exercised for all 60 fold minutes"


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


minutes_of_day = st.integers(min_value=0, max_value=23 * 60 + 59).map(minute_to_time)
london_days = st.dates(min_value=date(2020, 1, 1), max_value=date(2040, 12, 31))
change_day_minutes = st.integers(min_value=0, max_value=23 * 60 + 59)


@given(day=london_days, local=minutes_of_day)
def test_result_is_always_aware_utc(day: date, local: time) -> None:
    assert london_to_utc(day, local).utcoffset() == timedelta(0)


@given(day=st.sampled_from(CHANGE_DAYS), minute=change_day_minutes)
def test_wall_clock_is_kept_on_change_days_outside_the_spring_gap(day: date, minute: int) -> None:
    local = minute_to_time(minute)
    assume(not is_spring_gap(day, local))
    assert to_london(london_to_utc(day, local)).replace(tzinfo=None) == datetime.combine(day, local)


def test_change_days_are_the_last_sundays_of_march_and_october_for_every_year() -> None:
    for year in range(2020, 2041):
        days_in_year = [date(year, 1, 1) + timedelta(days=i) for i in range(366)]
        derived = [d for d in days_in_year if d.year == year and is_change_day(d)]
        assert derived == [last_sunday_of(year, 3), last_sunday_of(year, 10)], year


def test_2028_spring_change_day_is_a_change_day_and_the_wall_clock_is_not_kept() -> None:
    day, local = date(2028, 3, 26), time(1, 0)
    assert is_change_day(day)
    result = london_to_utc(day, local)
    assert result == utc(2028, 3, 26, 1, 0)  # gap: 01:00 does not exist, shifted to 02:00 BST
    assert to_london(result).replace(tzinfo=None) != datetime.combine(day, local)


def test_spring_gap_is_recognised_on_the_2020_change_day() -> None:
    # Regression for F06: the helper knew only 2026-03-29, so the monotonic property
    # found 2020-03-29 (local 01:00 and 02:00 both map to 01:00Z) and failed.
    day = date(2020, 3, 29)
    assert is_spring_gap(day, time(1, 0))
    assert not is_spring_gap(day, time(2, 0))


def test_spring_gap_is_derived_from_the_zone_for_every_year() -> None:
    for year in range(2020, 2041):
        spring = last_sunday_of(year, 3)
        assert is_spring_gap(spring, time(1, 0)), year
        assert not is_spring_gap(spring, time(0, 59)), year
        assert not is_spring_gap(spring, time(2, 0)), year
        assert not is_spring_gap(last_sunday_of(year, 10), time(1, 30)), year


@given(minute=st.integers(min_value=60, max_value=119))
def test_spring_gap_is_shifted_forward_one_hour_on_2026_03_29(minute: int) -> None:
    local = minute_to_time(minute)
    assert is_spring_gap(SPRING_CHANGE, local)
    shifted = datetime.combine(SPRING_CHANGE, local) + timedelta(hours=1)
    assert to_london(london_to_utc(SPRING_CHANGE, local)).replace(tzinfo=None) == shifted


@given(day=london_days, local=minutes_of_day)
def test_wall_clock_is_kept_on_other_days(day: date, local: time) -> None:
    assume(not is_change_day(day))
    assert to_london(london_to_utc(day, local)).replace(tzinfo=None) == datetime.combine(day, local)


@given(day=st.sampled_from(CHANGE_DAYS), first=change_day_minutes, second=change_day_minutes)
def test_conversion_is_monotonic_on_change_days_outside_the_gap(
    day: date, first: int, second: int
) -> None:
    a, b = minute_to_time(min(first, second)), minute_to_time(max(first, second))
    assume(a < b)
    assume(not is_spring_gap(day, a) and not is_spring_gap(day, b))
    assert london_to_utc(day, a) < london_to_utc(day, b)


@given(day=london_days, first=minutes_of_day, second=minutes_of_day)
def test_conversion_is_monotonic_within_a_day_outside_the_gap(
    day: date, first: time, second: time
) -> None:
    a, b = min(first, second), max(first, second)
    assume(a < b)
    assume(not is_spring_gap(day, a) and not is_spring_gap(day, b))
    assert london_to_utc(day, a) < london_to_utc(day, b)


@given(minute=st.integers(min_value=0, max_value=23 * 60 + 59))
def test_format_hhmm_round_trips_a_summer_wall_clock_time(minute: int) -> None:
    local = minute_to_time(minute)
    instant = london_to_utc(date(2026, 7, 1), local)
    assert format_hhmm(instant) == local.strftime("%H:%M")


# --- format_stamp: the full London date and time of a figure, "23 Oct 08:15" (U05, DEC-148) ------


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (utc(2026, 10, 23, 7, 15), "23 Oct 08:15"),  # BST
        (utc(2026, 12, 22, 17, 0), "22 Dec 17:00"),  # GMT
        (utc(2026, 11, 5, 9, 5), "5 Nov 09:05"),  # no leading zero on the day
        (utc(2026, 10, 22, 23, 30), "23 Oct 00:30"),  # the London date, not the UTC date
        (utc(2026, 3, 29, 0, 59), "29 Mar 00:59"),  # the last minute before the spring gap
        (utc(2026, 3, 29, 1, 0), "29 Mar 02:00"),  # the gap is skipped
        (utc(2026, 10, 25, 0, 30), "25 Oct 01:30"),  # first 01:30 of the autumn fold
        (utc(2026, 10, 25, 1, 30), "25 Oct 01:30"),  # second 01:30: the same words, a later instant
        (utc(2026, 1, 1, 0, 0), "1 Jan 00:00"),
        (utc(2026, 12, 31, 23, 59), "31 Dec 23:59"),
    ],
)
def test_format_stamp_is_the_london_day_month_and_time(instant: datetime, expected: str) -> None:
    assert format_stamp(instant) == expected


def test_format_stamp_refuses_a_naive_datetime() -> None:
    with pytest.raises(ValueError):
        format_stamp(datetime(2026, 10, 23, 7, 15))


# -- the zone is a value (TEN-065) ----------------------------------------------------------------

NEW_YORK = ZoneInfo("America/New_York")


def test_a_local_time_in_another_zone_is_converted_with_that_zone() -> None:
    assert local_to_utc(date(2026, 7, 1), time(10, 0), NEW_YORK) == utc(2026, 7, 1, 14, 0)
    assert local_to_utc(date(2026, 1, 1), time(10, 0), NEW_YORK) == utc(2026, 1, 1, 15, 0)


def test_london_is_the_default_zone_and_the_london_names_are_that_default() -> None:
    d, t = date(2026, 10, 23), time(10, 0)
    assert local_to_utc(d, t) == local_to_utc(d, t, LONDON) == london_to_utc(d, t)
    now = utc(2026, 10, 23, 9, 0)
    assert to_local(now) == to_local(now, LONDON) == to_london(now)


def test_the_spring_gap_of_another_zone_shifts_forward_as_londons_does() -> None:
    # New York, 2026-03-08: 02:30 does not exist; the pre-change offset is kept (03:30 EDT).
    assert local_to_utc(date(2026, 3, 8), time(2, 30), NEW_YORK) == utc(2026, 3, 8, 7, 30)


def test_a_time_of_day_with_a_zone_attached_is_refused_in_any_zone() -> None:
    with pytest.raises(ValueError, match="naive"):
        local_to_utc(date(2026, 7, 1), time(10, 0, tzinfo=UTC), NEW_YORK)


def test_an_instant_is_shown_in_the_zone_given() -> None:
    assert to_local(utc(2026, 7, 1, 14, 0), NEW_YORK).hour == 10
    assert format_hhmm(utc(2026, 7, 1, 14, 0), NEW_YORK) == "10:00"
    assert format_hhmm(utc(2026, 7, 1, 14, 0)) == "15:00"
    assert format_stamp(utc(2026, 7, 1, 14, 0), NEW_YORK) == "1 Jul 10:00"
    assert format_stamp(utc(2026, 7, 1, 14, 0)) == "1 Jul 15:00"


def test_a_naive_instant_is_refused_in_any_zone() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        to_local(datetime(2026, 7, 1, 14, 0), NEW_YORK)


def test_a_zone_is_made_from_a_name_on_the_allow_list_only() -> None:
    assert zone_named("Europe/London") == LONDON
    for bad in ("America/New_York", "UTC", "", "europe/london", None, 7, b"Europe/London"):
        with pytest.raises(ValidationFailed) as refused:
            zone_named(bad)
        assert refused.value.field == "time_zone"


def test_a_zone_the_rules_take_is_exactly_a_zoneinfo() -> None:
    assert require_zone(LONDON) is LONDON
    assert require_zone(NEW_YORK) is NEW_YORK
    for bad in (None, "Europe/London", UTC, 0):
        with pytest.raises(TypeError, match="a ZoneInfo is required"):
            require_zone(bad)
