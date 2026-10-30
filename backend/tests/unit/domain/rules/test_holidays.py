"""The bank holiday calendar per nation (TEN-066): checked-in lists for 2026 and 2027, and the
closure predicate a service and a tenant region give. Pure: no zone, no clock.

The lists are checked against the rules they follow (Easter, the first and last Mondays, the
substitute days), not only against themselves, so a mistyped date fails here.
"""

from datetime import date
from typing import Final

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.holidays import REGIONS, ClosurePeriod, bank_holidays, closed_on

ENGLAND_AND_WALES: Final = "england-and-wales"
SCOTLAND: Final = "scotland"
NORTHERN_IRELAND: Final = "northern-ireland"
YEARS: Final = (2026, 2027)


def easter_sunday(year: int) -> date:
    """The Gregorian Easter Sunday (the anonymous algorithm), independent of the calendar data."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return date(year, month, 1 + offset + 7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    following = date(year + (month == 12), month % 12 + 1, 1)
    last = date.fromordinal(following.toordinal() - 1)
    return date.fromordinal(last.toordinal() - (last.weekday() - weekday) % 7)


MONDAY: Final = 0


def test_the_regions_are_the_three_nations() -> None:
    assert frozenset({ENGLAND_AND_WALES, SCOTLAND, NORTHERN_IRELAND}) == REGIONS


@pytest.mark.parametrize("region", ["london", "", "Scotland", "wales", "england"])
def test_an_unknown_region_is_refused(region: str) -> None:
    with pytest.raises(ValidationFailed):
        bank_holidays(region)


@pytest.mark.parametrize("region", sorted(REGIONS))
def test_each_region_has_its_list_for_both_years(region: str) -> None:
    holidays = bank_holidays(region)
    for year in YEARS:
        assert any(day.year == year for day in holidays), (region, year)


def test_no_listed_date_falls_on_a_weekend() -> None:
    for region in REGIONS:
        for day in bank_holidays(region):
            assert day.weekday() < 5, (region, day)


@pytest.mark.parametrize("year", YEARS)
def test_good_friday_is_in_every_nation_and_easter_monday_is_not_in_scotland(year: int) -> None:
    easter = easter_sunday(year)
    good_friday = date.fromordinal(easter.toordinal() - 2)
    easter_monday = date.fromordinal(easter.toordinal() + 1)
    for region in REGIONS:
        assert good_friday in bank_holidays(region), region
    assert easter_monday in bank_holidays(ENGLAND_AND_WALES)
    assert easter_monday in bank_holidays(NORTHERN_IRELAND)
    assert easter_monday not in bank_holidays(SCOTLAND)


@pytest.mark.parametrize("year", YEARS)
def test_the_first_and_last_monday_days_follow_their_rules(year: int) -> None:
    early_may = nth_weekday(year, 5, MONDAY, 1)
    spring = last_weekday(year, 5, MONDAY)
    summer = last_weekday(year, 8, MONDAY)
    for region in (ENGLAND_AND_WALES, NORTHERN_IRELAND):
        assert {early_may, spring, summer} <= bank_holidays(region), region
    assert {early_may, spring} <= bank_holidays(SCOTLAND)


def test_the_scottish_summer_holiday_is_the_first_monday_of_august_and_not_the_last() -> None:
    assert nth_weekday(2026, 8, MONDAY, 1) == date(2026, 8, 3)
    assert date(2026, 8, 3) in bank_holidays(SCOTLAND)
    assert date(2026, 8, 31) not in bank_holidays(SCOTLAND)


@pytest.mark.parametrize(
    ("region", "day", "listed"),
    [
        (ENGLAND_AND_WALES, date(2026, 12, 28), True),  # Boxing Day falls on the Saturday
        (ENGLAND_AND_WALES, date(2026, 12, 26), False),
        (ENGLAND_AND_WALES, date(2027, 12, 27), True),  # Christmas on the Saturday
        (ENGLAND_AND_WALES, date(2027, 12, 28), True),  # Boxing Day on the Sunday
        (SCOTLAND, date(2027, 1, 4), True),  # New Year's Day 2 Jan on the Saturday
        (SCOTLAND, date(2026, 1, 2), True),
        (SCOTLAND, date(2026, 11, 30), True),  # St Andrew's Day
        (SCOTLAND, date(2026, 4, 6), False),
        (NORTHERN_IRELAND, date(2026, 3, 17), True),  # St Patrick's Day, a Tuesday
        (NORTHERN_IRELAND, date(2026, 7, 13), True),  # the 12th fell on the Sunday
        (NORTHERN_IRELAND, date(2026, 7, 12), False),
        (NORTHERN_IRELAND, date(2027, 7, 12), True),  # the 12th is a Monday in 2027
    ],
)
def test_named_days_are_listed_where_their_nation_keeps_them(
    region: str, day: date, listed: bool
) -> None:
    assert (day in bank_holidays(region)) is listed


def test_a_closure_period_is_inclusive_at_both_ends_and_refuses_a_reversed_one() -> None:
    period = ClosurePeriod(first=date(2026, 9, 1), last=date(2026, 9, 3))
    assert period.first <= period.last
    with pytest.raises(ValidationFailed):
        ClosurePeriod(first=date(2026, 9, 3), last=date(2026, 9, 1))


def test_the_predicate_holds_the_holidays_of_the_region_and_the_closed_days_of_the_service() -> (
    None
):
    closed = closed_on(SCOTLAND, [ClosurePeriod(date(2026, 9, 1), date(2026, 9, 3))])
    assert closed(date(2026, 1, 2)) is True  # a Scottish holiday
    assert closed(date(2026, 4, 6)) is False  # Easter Monday is not a Scottish holiday
    assert closed(date(2026, 9, 1)) is True
    assert closed(date(2026, 9, 3)) is True
    assert closed(date(2026, 9, 4)) is False


def test_the_predicate_follows_the_tenant_region_and_nothing_else() -> None:
    """The region is the tenant's (holidayRegion). The same day is closed for one nation and open
    for another, and a predicate without closures is only the holidays."""
    assert closed_on(SCOTLAND)(date(2026, 1, 2)) is True
    assert closed_on(ENGLAND_AND_WALES)(date(2026, 1, 2)) is False
    assert closed_on(ENGLAND_AND_WALES)(date(2026, 1, 1)) is True
