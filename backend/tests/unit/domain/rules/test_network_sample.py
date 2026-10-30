"""The hourly sample of a network board and the week measures made from samples (TEN-082,
DEC-136 items 1 and 14). Pure; synthetic values only."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from diucs.domain.codes import Status
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.network_sample import (
    MIN_ORGANISATIONS,
    READINGS,
    SMALL_GROUP,
    NetworkSample,
    hour_of,
    level_of,
    rank_of,
    sample_of,
    week_of_samples,
)
from diucs.domain.rules.pressure import Pressure
from tests.support.network_board_samples import BOARD_AT, board_entry, board_of

WEEK_START = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)  # a Monday, in UTC (the clocks changed)
WEEK_END = WEEK_START + timedelta(days=7)


def sample(
    hours_after: int = 0,
    *,
    organisations: int = 3,
    pressure: Pressure = Pressure.NORMAL,
    **counts: int,
) -> NetworkSample:
    base = {status: 0 for status in READINGS}
    base.update({Status(k.replace("_", "-")): v for k, v in counts.items()})
    hour = WEEK_START + timedelta(hours=hours_after)
    return NetworkSample(
        hour=hour,
        at=hour + timedelta(minutes=30),
        counts=tuple(base.items()),
        unavailable=0,
        organisations=organisations,
        pressure=pressure,
    )


# ---- the hour and the sample of a board


def test_an_hour_is_the_start_of_the_utc_hour() -> None:
    at = datetime(2026, 10, 26, 10, 59, 59, 5, tzinfo=timezone(timedelta(hours=1)))
    assert hour_of(at) == datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize("value", [datetime(2026, 10, 26, 9, 0), "2026-10-26T09:00:00Z", None])
def test_an_hour_needs_an_aware_datetime(value: object) -> None:
    with pytest.raises(ValidationFailed):
        hour_of(value)  # type: ignore[arg-type]


def test_a_sample_counts_the_rows_by_status_and_the_organisations_shown() -> None:
    board = board_of(
        board_entry("a", "North", Status.ACCEPTING),
        board_entry("b", "North", Status.LIMITED),
        board_entry("c", "South", Status.LIMITED),
        board_entry("d", "East", Status.NOT_UPDATED, stale=True),
        board_entry("e", "East", None),
    )
    taken = sample_of(board)
    assert taken.hour == datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
    assert taken.at == BOARD_AT
    assert dict(taken.counts) == {
        Status.ACCEPTING: 1,
        Status.LIMITED: 2,
        Status.NOT_ACCEPTING: 0,
        Status.OVER_CAPACITY: 0,
        Status.NOT_UPDATED: 1,
        Status.OUT_OF_HOURS: 0,
    }
    assert taken.unavailable == 1
    assert taken.organisations == 3
    assert taken.readings == 4
    assert taken.pressure is board.pressure


def test_a_sample_holds_no_name_a_row_reference_or_a_tenant() -> None:
    board = board_of(board_entry("row-ref-1", "North Trust", Status.ACCEPTING))
    text = repr(sample_of(board))
    assert "North" not in text and "row-ref-1" not in text and "Service" not in text


def test_a_sample_of_an_empty_board_is_all_zero() -> None:
    taken = sample_of(board_of())
    assert taken.readings == 0 and taken.unavailable == 0 and taken.organisations == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"hour": datetime(2026, 10, 26, 9, 30, tzinfo=UTC)},
        {"at": datetime(2026, 10, 26, 10, 0, tzinfo=UTC)},
        {"counts": ()},
        {"unavailable": -1},
        {"organisations": True},
        {"pressure": "high"},
    ],
)
def test_a_sample_that_is_not_one_is_refused(changes: dict[str, object]) -> None:
    good = sample(9)
    with pytest.raises(ValidationFailed):
        replace(good, **changes)  # type: ignore[arg-type]


def test_the_pressure_ranks_run_normal_watch_high_and_round_trip() -> None:
    assert [rank_of(p) for p in (Pressure.NORMAL, Pressure.WATCH, Pressure.HIGH)] == [0, 1, 2]
    assert [level_of(r) for r in (0, 1, 2)] == [Pressure.NORMAL, Pressure.WATCH, Pressure.HIGH]
    with pytest.raises(ValidationFailed):
        level_of(3)


# ---- the week


def busy_week(hours: int = 20, **counts: int) -> list[NetworkSample]:
    return [sample(h, **counts) for h in range(hours)]


def test_a_week_with_enough_readings_shows_the_shares_and_the_hours() -> None:
    week = week_of_samples(busy_week(accepting=2, limited=1, not_updated=1), WEEK_START, WEEK_END)
    assert week.withheld is False
    # 20 hours, 4 in-hours readings in each: 80 readings, 20 late
    assert week.on_time_pct.value == 75 and not week.on_time_pct.hidden
    shares = {status: m.value for status, m in week.status_share}
    assert shares[Status.ACCEPTING] == 50
    assert shares[Status.LIMITED] == 25
    assert shares[Status.NOT_UPDATED] == 25
    assert shares[Status.OUT_OF_HOURS] == 0
    assert week.hours_sampled.value == 20
    assert {level: m.value for level, m in week.pressure_hours} == {
        Pressure.NORMAL: 20,
        Pressure.WATCH: None,
        Pressure.HIGH: None,
    }
    assert len(week.pressure_over_time) == 20
    assert week.pressure_over_time[0] == (WEEK_START, Pressure.NORMAL)


def test_out_of_hours_readings_are_not_late_and_are_not_in_the_on_time_base() -> None:
    samples = [sample(h, accepting=2, out_of_hours=8) for h in range(10)]
    week = week_of_samples(samples, WEEK_START, WEEK_END)
    assert week.on_time_pct.value == 100
    assert {s: m.value for s, m in week.status_share}[Status.OUT_OF_HOURS] == 80


def test_a_share_with_a_base_under_ten_is_hidden_and_carries_no_value() -> None:
    week = week_of_samples([sample(0, accepting=SMALL_GROUP - 1)], WEEK_START, WEEK_END)
    assert week.on_time_pct.hidden and week.on_time_pct.value is None
    assert all(m.hidden and m.value is None for _, m in week.status_share)
    assert week.hours_sampled.hidden


def test_a_base_of_exactly_ten_is_shown() -> None:
    week = week_of_samples([sample(0, accepting=SMALL_GROUP)], WEEK_START, WEEK_END)
    assert week.on_time_pct.value == 100 and not week.on_time_pct.hidden


def test_hours_at_a_pressure_level_under_ten_are_hidden_and_ten_or_more_are_shown() -> None:
    samples = [sample(h, accepting=4, pressure=Pressure.HIGH) for h in range(SMALL_GROUP)]
    samples += [sample(SMALL_GROUP + h, accepting=4, pressure=Pressure.WATCH) for h in range(3)]
    levels = dict(week_of_samples(samples, WEEK_START, WEEK_END).pressure_hours)
    assert levels[Pressure.HIGH].value == SMALL_GROUP and not levels[Pressure.HIGH].hidden
    assert levels[Pressure.WATCH].hidden and levels[Pressure.WATCH].value is None


def test_the_pressure_over_time_lists_the_sampled_hours_in_order() -> None:
    samples = [
        sample(5, accepting=4, pressure=Pressure.HIGH),
        sample(2, accepting=4, pressure=Pressure.WATCH),
    ]
    week = week_of_samples(samples, WEEK_START, WEEK_END)
    assert week.pressure_over_time == (
        (WEEK_START + timedelta(hours=2), Pressure.WATCH),
        (WEEK_START + timedelta(hours=5), Pressure.HIGH),
    )


def test_a_network_with_fewer_than_three_organisations_is_withheld_whole() -> None:
    samples = busy_week(accepting=4, organisations=MIN_ORGANISATIONS - 1)
    week = week_of_samples(samples, WEEK_START, WEEK_END)
    assert week.withheld is True
    assert week.pressure_over_time == ()
    assert week.hours_sampled.hidden and week.on_time_pct.hidden
    assert all(m.hidden and m.value is None for _, m in week.status_share)
    assert all(m.hidden and m.value is None for _, m in week.pressure_hours)


def test_three_organisations_in_any_one_sample_is_enough() -> None:
    samples = busy_week(accepting=4, organisations=2)
    samples[7] = sample(7, accepting=4, organisations=MIN_ORGANISATIONS)
    assert week_of_samples(samples, WEEK_START, WEEK_END).withheld is False


def test_an_empty_week_is_withheld() -> None:
    assert week_of_samples([], WEEK_START, WEEK_END).withheld is True


def test_samples_outside_the_week_are_left_out() -> None:
    before = sample(-1, accepting=40)
    after = sample(7 * 24, accepting=40)
    inside = busy_week(10, accepting=4)
    week = week_of_samples([before, after, *inside], WEEK_START, WEEK_END)
    assert week.hours_sampled.value == 10


def test_two_samples_of_one_hour_are_refused() -> None:
    with pytest.raises(ValidationFailed):
        week_of_samples([sample(1, accepting=4), sample(1, accepting=5)], WEEK_START, WEEK_END)


def test_the_measures_hold_no_organisation_service_or_member() -> None:
    week = week_of_samples(busy_week(accepting=4), WEEK_START, WEEK_END)
    text = repr(week)
    assert "tenant" not in text.lower() and "service" not in text.lower()
