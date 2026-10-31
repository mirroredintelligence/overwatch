"""The effective time of a report against the figures already on record (KI-7, KI-8, KI-9, Q8).

A report is current when it is the latest figure, so a figure must be later than every figure on
record. An explicit time that is not later than the latest figure's time is refused (it would be
hidden behind that figure, or tie with it and sort by a whole-second write time, which is
undefined). A figure with no explicit time is taken at the clock, but never at or before the
latest figure's time: a host whose clock is behind the writer's would otherwise sort the new
figure before an older one. Boundary values at one microsecond.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from diucs.domain.rules.effective_time import (
    ONE_MICROSECOND,
    default_effective_at,
    is_later_than_latest,
)

LATEST = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
BST = timezone(timedelta(hours=1))


@pytest.mark.parametrize(
    ("offset", "allowed"),
    [
        (timedelta(minutes=-10), False),
        (-ONE_MICROSECOND, False),
        (timedelta(0), False),
        (ONE_MICROSECOND, True),
        (timedelta(minutes=10), True),
    ],
)
def test_an_explicit_time_is_allowed_only_when_later_than_the_latest_figure(
    offset: timedelta, allowed: bool
) -> None:
    assert is_later_than_latest(LATEST + offset, LATEST) is allowed


def test_any_explicit_time_is_allowed_when_there_is_no_figure() -> None:
    assert is_later_than_latest(LATEST, None) is True


def test_times_are_compared_as_instants_not_as_wall_clock() -> None:
    same_instant = datetime(2026, 10, 23, 14, 12, tzinfo=BST)

    assert is_later_than_latest(same_instant, LATEST) is False
    assert is_later_than_latest(same_instant + ONE_MICROSECOND, LATEST) is True


@pytest.mark.parametrize(
    ("now_offset", "expected_offset"),
    [
        (timedelta(minutes=5), timedelta(minutes=5)),
        (ONE_MICROSECOND * 2, ONE_MICROSECOND * 2),
        (ONE_MICROSECOND, ONE_MICROSECOND),
        (timedelta(0), ONE_MICROSECOND),
        (-ONE_MICROSECOND, ONE_MICROSECOND),
        (timedelta(minutes=-5), ONE_MICROSECOND),
    ],
)
def test_the_default_time_is_the_clock_but_never_at_or_before_the_latest_figure(
    now_offset: timedelta, expected_offset: timedelta
) -> None:
    assert default_effective_at(LATEST + now_offset, LATEST) == LATEST + expected_offset


def test_the_default_time_is_the_clock_when_there_is_no_figure() -> None:
    assert default_effective_at(LATEST, None) == LATEST


def test_the_default_time_is_in_utc() -> None:
    now = datetime(2026, 10, 23, 15, 0, tzinfo=BST)

    result = default_effective_at(now, LATEST)

    assert result.utcoffset() == timedelta(0)
    assert result == now


def test_a_naive_time_is_refused() -> None:
    with pytest.raises(ValueError):
        is_later_than_latest(datetime(2026, 10, 23, 13, 12), LATEST)
    with pytest.raises(ValueError):
        default_effective_at(datetime(2026, 10, 23, 13, 12), LATEST)
    with pytest.raises(ValueError):
        default_effective_at(LATEST, datetime(2026, 10, 23, 13, 12))
