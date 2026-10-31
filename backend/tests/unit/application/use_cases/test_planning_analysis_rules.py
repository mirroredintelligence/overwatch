"""Pure rules of the planning analysis (U43): the default cohort, the need groups, the best-fit
rule, the hiding of counts under 10, the heat grid, the flows and the declines. No I/O."""

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from diucs.application.use_cases.planning_analysis import (
    MIN_COUNT,
    DeclineFact,
    DisplayFact,
    HiddenCount,
    OutcomeFact,
    PlanningQuery,
    best_fit,
    build_planning,
    decision_for,
    heat_cell,
    hide,
    in_cohort,
    is_unavailable,
    share_of,
    validate_query,
    windows,
)
from diucs.domain.errors import ValidationFailed

THU_NOON_LONDON_BST = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)  # Thursday 13:00 BST


def _outcome(
    key: str = "c1",
    *,
    age: str = "80+",
    urgency: str = "within-2-hrs",
    referrer: str = "ambulance-crew",
    needs: tuple[str, ...] = ("fall-no-injury", "frailty"),
    opened: datetime = THU_NOON_LONDON_BST,
    closed: datetime | None = None,
    destination: str | None = None,
) -> OutcomeFact:
    return OutcomeFact(
        case_key=key,
        opened_at=opened,
        closed_at=closed or datetime(2026, 10, 22, 12, 30, tzinfo=UTC),
        age_band=age,
        urgency=urgency,
        referrer=referrer,
        needs=needs,
        destination_id=destination,
    )


def _row(service_id: str, status: str, number: int | None) -> dict[str, object]:
    return {
        "id": service_id,
        "status": status,
        "number": number,
        "data_age_seconds": 60,
        "criteria_version": 1,
        "shown_as": "option",
    }


def _display(key: str, rows: list[dict[str, object]], at: datetime | None = None) -> DisplayFact:
    return DisplayFact(
        case_key=key, at=at or datetime(2026, 10, 22, 12, 10, tzinfo=UTC), rows=tuple(rows)
    )


def test_a_query_outside_the_allowed_periods_or_groups_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        validate_query(PlanningQuery(period_days=60, need_group="all"))
    with pytest.raises(ValidationFailed):
        validate_query(PlanningQuery(period_days=30, need_group="dementia"))


@pytest.mark.parametrize("period", [30, 90, 365])
def test_the_allowed_periods_are_accepted(period: int) -> None:
    validate_query(PlanningQuery(period_days=period, need_group="all"))


def test_the_default_cohort_is_65_plus_within_two_hours_by_ambulance_or_care_home() -> None:
    assert in_cohort(_outcome(), "all")
    assert in_cohort(_outcome(age="65-79", referrer="care-home"), "all")


@pytest.mark.parametrize(
    "fact",
    [
        _outcome(age="16-64"),
        _outcome(urgency="today"),
        _outcome(urgency="planned"),
        _outcome(referrer="gp"),
        _outcome(referrer="nhs-111"),
    ],
)
def test_a_case_outside_the_default_cohort_is_left_out(fact: OutcomeFact) -> None:
    assert not in_cohort(fact, "all")


def test_the_need_groups_match_on_their_needs() -> None:
    assert in_cohort(_outcome(needs=("frailty",)), "falls-and-frailty")
    assert in_cohort(_outcome(needs=("fall-no-injury",)), "falls-and-frailty")
    assert not in_cohort(_outcome(needs=("wound-care",)), "falls-and-frailty")
    assert in_cohort(_outcome(needs=("iv-therapy",)), "iv-therapy")
    assert not in_cohort(_outcome(needs=("frailty",)), "iv-therapy")
    assert in_cohort(_outcome(needs=("palliative",)), "palliative")


def test_the_decision_is_the_last_display_at_or_before_the_outcome() -> None:
    early = _display(
        "c1", [_row("a", "accepting", 2)], at=datetime(2026, 10, 22, 12, 5, tzinfo=UTC)
    )
    late = _display(
        "c1", [_row("b", "accepting", 3)], at=datetime(2026, 10, 22, 12, 20, tzinfo=UTC)
    )
    after = _display(
        "c1", [_row("c", "accepting", 1)], at=datetime(2026, 10, 22, 13, 0, tzinfo=UTC)
    )
    chosen = decision_for(
        _outcome(closed=datetime(2026, 10, 22, 12, 30, tzinfo=UTC)), [early, late, after]
    )
    assert chosen is late


def test_no_display_before_the_outcome_gives_no_decision() -> None:
    later = _display(
        "c1", [_row("a", "accepting", 2)], at=datetime(2026, 10, 22, 13, 0, tzinfo=UTC)
    )
    assert decision_for(_outcome(), [later]) is None


def test_the_best_fit_is_the_first_option_row_of_a_display_with_no_order() -> None:
    rows = [
        {**_row("a", "accepting", 4), "shown_as": "not-suitable"},
        _row("b", "limited", 2),
        _row("c", "accepting", 5),
    ]
    assert best_fit(rows)["id"] == "b"  # type: ignore[index]


@pytest.mark.parametrize(
    ("status", "number", "unavailable"),
    [
        ("not-accepting", 0, True),
        ("over-capacity", 14, True),
        ("not-updated", 3, True),
        ("accepting", 0, True),
        ("accepting", 4, False),
        ("limited", 2, False),
    ],
)
def test_a_best_fit_is_unavailable_when_closed_or_empty(
    status: str, number: int, unavailable: bool
) -> None:
    assert is_unavailable(_row("a", status, number)) is unavailable


def test_counts_under_ten_are_hidden_and_others_are_shown() -> None:
    assert hide(MIN_COUNT - 1) == HiddenCount(None, True)
    assert hide(MIN_COUNT) == HiddenCount(MIN_COUNT, False)


def test_a_share_is_hidden_when_its_base_is_under_ten() -> None:
    assert share_of(112, 640) == HiddenCount(18, False)
    assert share_of(3, 9) == HiddenCount(None, True)


def test_the_heat_cell_is_the_london_weekday_and_six_hour_band_of_the_arrival() -> None:
    assert heat_cell(THU_NOON_LONDON_BST) == (3, "12-18")
    assert heat_cell(datetime(2026, 10, 22, 22, 30, tzinfo=UTC)) == (3, "18-24")  # 23:30 BST
    assert heat_cell(datetime(2026, 10, 22, 4, 0, tzinfo=UTC)) == (3, "00-06")  # 05:00 BST


def _case_set(
    n: int, status: str, destination: str | None = None
) -> tuple[list[OutcomeFact], list[DisplayFact]]:
    outcomes: list[OutcomeFact] = []
    displays: list[DisplayFact] = []
    for index in range(n):
        key = f"{status}-{index}"
        outcomes.append(_outcome(key, destination=destination))
        displays.append(
            _display(
                key,
                [_row("ucr-west", status, 0 if status == "not-accepting" else 3)],
            )
        )
    return outcomes, displays


def test_the_referral_and_best_fit_counts_and_the_share() -> None:
    outcomes, displays = _case_set(112, "not-accepting")
    ok_outcomes, ok_displays = _case_set(528, "accepting")
    result = build_planning(
        PlanningQuery(period_days=30, need_group="all"),
        [*outcomes, *ok_outcomes],
        [*displays, *ok_displays],
        [],
        {"ucr-west": "UCR West"},
    )
    assert result.referrals == HiddenCount(640, False)
    assert result.best_fit_unavailable == HiddenCount(112, False)
    assert result.best_fit_unavailable_pct == HiddenCount(18, False)


def test_a_flow_under_ten_is_hidden_and_one_over_ten_is_shown() -> None:
    home_outcomes, home_displays = _case_set(18, "over-capacity", destination="ucr-west")
    ed_outcomes, ed_displays = _case_set(6, "over-capacity", destination="ed")
    for index, fact in enumerate(home_displays):
        home_displays[index] = DisplayFact(
            fact.case_key, fact.at, (_row("home", "over-capacity", 14),)
        )
    for index, fact in enumerate(ed_displays):
        ed_displays[index] = DisplayFact(
            fact.case_key, fact.at, (_row("home", "over-capacity", 14),)
        )
    result = build_planning(
        PlanningQuery(period_days=30, need_group="all"),
        [*home_outcomes, *ed_outcomes],
        [*home_displays, *ed_displays],
        [],
        {"home": "Hospital at home", "ucr-west": "UCR West", "ed": "Emergency department"},
    )
    by_destination = {flow.destination: flow.count for flow in result.flows}
    assert by_destination["UCR West"] == HiddenCount(18, False)
    assert by_destination["Emergency department"] == HiddenCount(None, True)


def test_the_busiest_cell_is_the_largest_visible_cell_and_hidden_when_small() -> None:
    outcomes, displays = _case_set(12, "not-accepting")
    thursday = [dataclasses.replace(o, opened_at=THU_NOON_LONDON_BST) for o in outcomes]
    result = build_planning(
        PlanningQuery(period_days=30, need_group="all"),
        thursday,
        displays,
        [],
        {"ucr-west": "UCR West"},
    )
    assert result.heat[(3, "12-18")] == HiddenCount(12, False)
    assert result.busiest == (3, "12-18")

    small_outcomes, small_displays = _case_set(4, "not-accepting")
    small = build_planning(
        PlanningQuery(period_days=30, need_group="all"),
        small_outcomes,
        small_displays,
        [],
        {"ucr-west": "UCR West"},
    )
    assert small.busiest is None


def test_declined_despite_capacity_is_grouped_by_service_and_hidden_under_ten() -> None:
    declines = [DeclineFact("ward-a", THU_NOON_LONDON_BST) for _ in range(14)]
    declines += [DeclineFact("svc-small", THU_NOON_LONDON_BST) for _ in range(4)]
    result = build_planning(
        PlanningQuery(period_days=30, need_group="all"),
        [],
        [],
        declines,
        {"ward-a": "Ward A", "svc-small": "Small service"},
    )
    assert dict(result.declined_despite) == {
        "Ward A": HiddenCount(14, False),
        "Small service": HiddenCount(None, True),
    }


def test_a_case_with_no_display_is_not_counted_as_a_referral() -> None:
    outcomes, _ = _case_set(3, "accepting")
    result = build_planning(PlanningQuery(period_days=30, need_group="all"), outcomes, [], [], {})
    assert result.referrals == HiddenCount(None, True)


# KI-476, H-193: the best fit is the option the advisor was shown first, which is the nearest.


def _ordered(row: dict[str, object], order: int) -> dict[str, object]:
    return {**row, "order": order}


def test_the_best_fit_is_the_option_shown_first_not_the_first_in_the_snapshot() -> None:
    rows = [
        _ordered(_row("far", "accepting", 4), 2),
        _ordered(_row("near", "accepting", 1), 1),
    ]

    assert best_fit(rows)["id"] == "near"  # type: ignore[index]


def test_not_suitable_rows_have_no_order_and_are_never_the_best_fit() -> None:
    rows = [
        {**_row("no", "not-accepting", 0), "shown_as": "not-suitable"},
        _ordered(_row("far", "accepting", 4), 2),
        _ordered(_row("near", "accepting", 1), 1),
    ]

    assert best_fit(rows)["id"] == "near"  # type: ignore[index]


def test_a_display_with_an_order_on_some_options_only_keeps_the_listed_order() -> None:
    rows = [_row("first", "accepting", 4), _ordered(_row("second", "accepting", 1), 1)]

    assert best_fit(rows)["id"] == "first"  # type: ignore[index]


def test_a_best_fit_that_was_full_is_counted_when_it_was_the_nearest() -> None:
    nearest_full = _ordered(_row("near", "accepting", 0), 1)
    farther = _ordered(_row("far", "accepting", 4), 2)
    displays = [
        _display(f"c{n}", [farther, nearest_full])  # the board listed the far one first
        for n in range(10)
    ]
    outcomes = [_outcome(f"c{n}", destination="far") for n in range(10)]

    result = build_planning(
        PlanningQuery(30, "all"), outcomes, displays, [], {"near": "Near", "far": "Far"}
    )

    assert result.best_fit_unavailable == HiddenCount(10, False)
    assert result.went_elsewhere == HiddenCount(10, False)
    assert result.flows[0].best_fit == "Near"


# KI-477: the window is read in months, not in one piece.


def test_the_window_is_cut_into_contiguous_pieces_that_cover_it_exactly() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=365)

    pieces = windows(start, end, 30)

    assert pieces[0][0] == start
    assert pieces[-1][1] == end
    assert all(a[1] == b[0] for a, b in zip(pieces, pieces[1:], strict=False))
    assert all(low < high for low, high in pieces)
    assert all(high - low <= timedelta(days=30) for low, high in pieces)


def test_a_short_window_is_one_piece() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)

    assert windows(start, start + timedelta(days=30), 30) == [(start, start + timedelta(days=30))]
