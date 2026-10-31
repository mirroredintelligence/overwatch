"""The prompt due at a service's closing time is sent (DEC-1100 Q3, KI-22).

An 08:00 to 20:00 service has a due time at 20:00 (every-2-hrs runs up to and including the closing
time). `is_in_hours` is end-exclusive, which the status rule needs (a service is not taking
referrals at its closing time), so SendPrompts skipped that prompt as out of hours every day. The
last prompt of the day is the closing figure a night coordinator relies on: for due times only, the
closing time counts as inside the hours. `is_in_hours` itself does not change.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from diucs.domain.model.service import AvailableTime
from diucs.domain.rules.london_time import local_to_utc
from diucs.domain.rules.opening_hours import is_in_hours
from diucs.domain.rules.prompt_hours import ONE_TICK, is_due_time_in_hours

DAY = date(2026, 10, 23)  # a Friday, BST
DAYTIME = (AvailableTime.every_day(time(8, 0), time(20, 0)),)
OVERNIGHT = (AvailableTime.every_day(time(20, 0), time(8, 0)),)
NEW_YORK = ZoneInfo("America/New_York")


def london(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return local_to_utc(day, time(hour, minute))


def test_the_opening_time_is_inside() -> None:
    assert is_due_time_in_hours(DAYTIME, london(8)) is True


def test_a_time_in_the_middle_is_inside() -> None:
    assert is_due_time_in_hours(DAYTIME, london(14)) is True


def test_the_closing_time_is_inside_for_a_due_time() -> None:
    assert is_due_time_in_hours(DAYTIME, london(20)) is True


def test_is_in_hours_is_still_end_exclusive_for_the_status_rule() -> None:
    assert is_in_hours(DAYTIME, london(20)) is False
    assert is_in_hours(DAYTIME, london(20) - ONE_TICK) is True


def test_one_tick_after_the_closing_time_is_outside() -> None:
    assert is_due_time_in_hours(DAYTIME, london(20) + ONE_TICK) is False


def test_a_time_before_opening_is_outside() -> None:
    assert is_due_time_in_hours(DAYTIME, london(8) - ONE_TICK) is False
    assert is_due_time_in_hours(DAYTIME, london(7, 59)) is False


def test_an_overnight_window_closes_at_its_end_next_morning() -> None:
    next_day = date(2026, 10, 24)

    assert is_due_time_in_hours(OVERNIGHT, london(8, day=next_day)) is True
    assert is_due_time_in_hours(OVERNIGHT, london(8, 1, day=next_day)) is False
    assert is_due_time_in_hours(OVERNIGHT, london(14)) is False


def test_a_day_the_service_is_closed_has_no_closing_time() -> None:
    weekdays = (AvailableTime.weekdays(time(8, 0), time(20, 0)),)
    saturday = date(2026, 10, 24)

    assert is_due_time_in_hours(weekdays, london(20, day=saturday)) is False


def test_the_zone_is_the_tenants() -> None:
    closing_in_new_york = local_to_utc(DAY, time(20, 0), NEW_YORK)

    assert is_due_time_in_hours(DAYTIME, closing_in_new_york, NEW_YORK) is True
    assert is_due_time_in_hours(DAYTIME, closing_in_new_york) is False


def test_the_clock_change_does_not_move_the_closing_time() -> None:
    autumn = date(2026, 10, 25)  # the clocks go back at 02:00 BST

    assert is_due_time_in_hours(DAYTIME, local_to_utc(autumn, time(20, 0))) is True
    assert (
        is_due_time_in_hours(DAYTIME, local_to_utc(autumn, time(20, 0)) + timedelta(hours=1))
        is False
    )


def test_a_naive_time_is_refused() -> None:
    with pytest.raises(ValueError):
        is_due_time_in_hours(DAYTIME, datetime(2026, 10, 23, 20, 0))


def test_utc_is_the_instant_not_the_wall_clock() -> None:
    assert (
        is_due_time_in_hours(DAYTIME, datetime(2026, 10, 23, 19, 0, tzinfo=UTC)) is True
    )  # 20:00 BST
