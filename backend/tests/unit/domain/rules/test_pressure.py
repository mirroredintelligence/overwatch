"""Tests for diucs.domain.rules.pressure: system pressure and the board banner (D08).

Rule: docs/spec/domain-rules.md 1.7, and the D08 prompt. Limited or worse means limited,
not-accepting or over-capacity. Not-updated is unknown, not worse. Out-of-hours is left out.
The banner shows when every in-hours service is limited or worse (an in-hours not-updated
service stops it). Plain strings and members of other enums are refused (DEC-040, lesson L44).
"""

from enum import StrEnum
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import Status
from diucs.domain.rules.pressure import (
    HIGH_FROM,
    LIMITED_OR_WORSE,
    WATCH_FROM,
    Pressure,
    all_limited_or_worse,
    limited_or_worse_count,
    system_pressure,
)

ACCEPTING: Final = Status.ACCEPTING
LIMITED: Final = Status.LIMITED
NOT_ACCEPTING: Final = Status.NOT_ACCEPTING
OVER_CAPACITY: Final = Status.OVER_CAPACITY
NOT_UPDATED: Final = Status.NOT_UPDATED
OUT_OF_HOURS: Final = Status.OUT_OF_HOURS

RANK: Final = {Pressure.NORMAL: 0, Pressure.WATCH: 1, Pressure.HIGH: 2}


def _board(counts: dict[Status, int]) -> list[Status]:
    return [status for status, n in counts.items() for _ in range(n)]


SAMPLE_BOARD: Final = _board(
    {ACCEPTING: 4, LIMITED: 2, NOT_ACCEPTING: 1, OVER_CAPACITY: 1, NOT_UPDATED: 1}
)
SURGE_BOARD: Final = _board({LIMITED: 4, NOT_ACCEPTING: 3, OVER_CAPACITY: 2})
OVERNIGHT_BOARD: Final = _board({OUT_OF_HOURS: 6, ACCEPTING: 2, LIMITED: 1})


def test_constants_match_the_rule_book() -> None:
    assert WATCH_FROM == 3
    assert HIGH_FROM == 5
    assert frozenset({LIMITED, NOT_ACCEPTING, OVER_CAPACITY}) == LIMITED_OR_WORSE


def test_pressure_values() -> None:
    assert [p.value for p in Pressure] == ["normal", "watch", "high"]


# Prompt tests 1 to 8


def test_sample_board_counts_four_and_is_watch_with_no_banner() -> None:
    assert limited_or_worse_count(SAMPLE_BOARD) == 4
    assert system_pressure(SAMPLE_BOARD) is Pressure.WATCH
    assert all_limited_or_worse(SAMPLE_BOARD) is False


def test_two_limited_with_the_rest_accepting_is_normal() -> None:
    board = _board({LIMITED: 2, ACCEPTING: 7})
    assert system_pressure(board) is Pressure.NORMAL


@pytest.mark.parametrize(
    ("limited_or_worse", "expected"),
    [
        (0, Pressure.NORMAL),
        (2, Pressure.NORMAL),
        (3, Pressure.WATCH),
        (4, Pressure.WATCH),
        (5, Pressure.HIGH),
        (6, Pressure.HIGH),
    ],
)
def test_pressure_thresholds_are_exact(limited_or_worse: int, expected: Pressure) -> None:
    board = _board({LIMITED: limited_or_worse, ACCEPTING: 10})
    assert system_pressure(board) is expected


def test_surge_board_is_high_with_the_banner() -> None:
    assert limited_or_worse_count(SURGE_BOARD) == 9
    assert system_pressure(SURGE_BOARD) is Pressure.HIGH
    assert all_limited_or_worse(SURGE_BOARD) is True


def test_surge_board_plus_out_of_hours_keeps_the_banner() -> None:
    board = [*SURGE_BOARD, OUT_OF_HOURS]
    assert limited_or_worse_count(board) == 9
    assert all_limited_or_worse(board) is True


def test_surge_board_plus_one_not_updated_removes_the_banner() -> None:
    board = [*SURGE_BOARD, NOT_UPDATED]
    assert system_pressure(board) is Pressure.HIGH
    assert all_limited_or_worse(board) is False


def test_overnight_board_is_normal_with_no_banner() -> None:
    assert limited_or_worse_count(OVERNIGHT_BOARD) == 1
    assert system_pressure(OVERNIGHT_BOARD) is Pressure.NORMAL
    assert all_limited_or_worse(OVERNIGHT_BOARD) is False


def test_all_out_of_hours_is_normal_with_no_banner() -> None:
    board = _board({OUT_OF_HOURS: 8})
    assert system_pressure(board) is Pressure.NORMAL
    assert all_limited_or_worse(board) is False


def test_empty_list_is_normal_with_no_banner() -> None:
    assert limited_or_worse_count([]) == 0
    assert system_pressure([]) is Pressure.NORMAL
    assert all_limited_or_worse([]) is False


def test_five_not_updated_is_normal() -> None:
    board = _board({NOT_UPDATED: 5})
    assert limited_or_worse_count(board) == 0
    assert system_pressure(board) is Pressure.NORMAL
    assert all_limited_or_worse(board) is False


# Behaviour added beyond the prompt


def test_banner_needs_at_least_one_in_hours_service() -> None:
    assert all_limited_or_worse([OUT_OF_HOURS]) is False


def test_accepting_service_stops_the_banner() -> None:
    assert all_limited_or_worse([LIMITED, LIMITED, ACCEPTING]) is False


def test_each_limited_or_worse_status_counts_on_its_own() -> None:
    for status in (LIMITED, NOT_ACCEPTING, OVER_CAPACITY):
        assert limited_or_worse_count([status]) == 1
        assert all_limited_or_worse([status]) is True


def test_iterables_are_read_once_so_a_generator_gives_the_same_answer() -> None:
    assert system_pressure(s for s in SURGE_BOARD) is Pressure.HIGH
    assert all_limited_or_worse(s for s in SURGE_BOARD) is True
    assert limited_or_worse_count(s for s in SAMPLE_BOARD) == 4


class _OtherEnum(StrEnum):
    LIMITED = "limited"


@pytest.mark.parametrize("bad", ["limited", _OtherEnum.LIMITED])
def test_plain_strings_and_other_enums_are_refused(bad: object) -> None:
    board: list[object] = [ACCEPTING, bad]
    with pytest.raises(TypeError):
        limited_or_worse_count(board)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        system_pressure(board)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        all_limited_or_worse(board)  # type: ignore[arg-type]


# Properties


_statuses = st.lists(st.sampled_from(list(Status)), max_size=40)


@given(_statuses)
def test_count_is_the_number_of_limited_or_worse_statuses(statuses: list[Status]) -> None:
    expected = sum(1 for s in statuses if s in LIMITED_OR_WORSE)
    assert limited_or_worse_count(statuses) == expected


@given(_statuses)
def test_pressure_is_high_exactly_when_count_reaches_the_alert_threshold(
    statuses: list[Status],
) -> None:
    count = limited_or_worse_count(statuses)
    pressure = system_pressure(statuses)
    assert (pressure is Pressure.HIGH) == (count >= HIGH_FROM)
    assert (pressure is Pressure.NORMAL) == (count < WATCH_FROM)


@given(_statuses)
def test_pressure_does_not_depend_on_order(statuses: list[Status]) -> None:
    assert system_pressure(statuses) is system_pressure(list(reversed(statuses)))
    assert all_limited_or_worse(statuses) is all_limited_or_worse(list(reversed(statuses)))


@given(_statuses, st.sampled_from([LIMITED, NOT_ACCEPTING, OVER_CAPACITY]))
def test_adding_a_limited_or_worse_service_never_lowers_pressure(
    statuses: list[Status], extra: Status
) -> None:
    before = system_pressure(statuses)
    after = system_pressure([*statuses, extra])
    assert RANK[after] >= RANK[before]


@given(_statuses)
def test_banner_implies_every_in_hours_service_is_limited_or_worse(
    statuses: list[Status],
) -> None:
    if all_limited_or_worse(statuses):
        in_hours = [s for s in statuses if s is not OUT_OF_HOURS]
        assert in_hours
        assert all(s in LIMITED_OR_WORSE for s in in_hours)


@given(_statuses)
def test_a_not_updated_service_never_shows_the_banner(statuses: list[Status]) -> None:
    if NOT_UPDATED in statuses:
        assert all_limited_or_worse(statuses) is False


@given(_statuses)
def test_not_updated_never_adds_to_the_count(statuses: list[Status]) -> None:
    without = [s for s in statuses if s is not NOT_UPDATED]
    assert limited_or_worse_count(statuses) == limited_or_worse_count(without)
    assert system_pressure(statuses) is system_pressure(without)
