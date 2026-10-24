from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock

START = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


def test_now_returns_the_time_it_was_given() -> None:
    assert FixedClock(START).now() == START


def test_advance_moves_the_time_forward() -> None:
    clock = FixedClock(START)
    clock.advance(timedelta(minutes=5))
    assert clock.now() == START + timedelta(minutes=5)


def test_set_replaces_the_time() -> None:
    clock = FixedClock(START)
    later = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
    clock.set(later)
    assert clock.now() == later


def test_non_utc_input_is_reported_as_the_same_instant_in_utc() -> None:
    local = datetime(2026, 7, 1, 10, 0, tzinfo=ZoneInfo("Europe/London"))
    now = FixedClock(local).now()
    assert now == datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    assert now.utcoffset() == timedelta(0)


def test_naive_datetime_is_rejected_on_construction() -> None:
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 10, 24, 9, 0))


def test_naive_datetime_is_rejected_by_set() -> None:
    clock = FixedClock(START)
    with pytest.raises(ValueError):
        clock.set(datetime(2026, 10, 24, 9, 0))
    assert clock.now() == START
