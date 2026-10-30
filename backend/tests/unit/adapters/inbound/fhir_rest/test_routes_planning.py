"""The planning route (W51, U43): `GET /planning`. The role boundary (a shift lead or an executive
only, refused before any read) and the answer's shape, with every count under 10 hidden, are
pinned here. The stored answers and the tenant boundary are in tests/integration/.
"""

import pytest

from diucs.adapters.inbound.fhir_rest.routes_planning import (
    cohort_text,
    planning_json,
    query_from,
)
from diucs.application.use_cases.planning_analysis import (
    FlowRow,
    HiddenCount,
    PlanningQuery,
    PlanningResult,
)
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from tests.support.route_unit import assert_role_matrix, bearer, route_client

PLANNERS = frozenset({Role.LEAD, Role.EXEC})


def shown(value: int) -> HiddenCount:
    return HiddenCount(value, False)


HIDDEN = HiddenCount(None, True)


def _result() -> PlanningResult:
    return PlanningResult(
        referrals=shown(640),
        best_fit_unavailable=shown(112),
        best_fit_unavailable_pct=shown(18),
        went_elsewhere=shown(62),
        flows=(
            FlowRow("UCR West", "full", "Ward B", shown(40)),
            FlowRow("UCR West", "not updated", "no destination recorded", HIDDEN),
        ),
        heat={(3, "12-18"): shown(12), (0, "00-06"): HIDDEN},
        busiest=(3, "12-18"),
        declined_despite=(("UCR East", shown(11)), ("Ward A", HIDDEN)),
    )


async def test_the_planning_analysis_is_for_a_shift_lead_or_an_executive_only() -> None:
    async with route_client() as client:
        await assert_role_matrix(client, "GET", "/planning?period=90d&need=all", PLANNERS)


async def test_a_period_or_need_that_is_not_listed_is_a_400_that_names_it() -> None:
    async with route_client() as client:
        bad_period = await client.get("/planning?period=7d&need=all", headers=bearer(Role.LEAD))
        bad_need = await client.get("/planning?period=30d&need=everything", headers=bearer(Role.LEAD))

    assert bad_period.status_code == 400
    assert "period" in bad_period.text
    assert bad_need.status_code == 400
    assert "need" in bad_need.text


def test_the_browser_names_are_the_use_cases_names() -> None:
    assert query_from("30d", "all") == PlanningQuery(30, "all")
    assert query_from("90d", "falls-frailty") == PlanningQuery(90, "falls-and-frailty")
    assert query_from("12m", "iv-therapy") == PlanningQuery(365, "iv-therapy")
    assert query_from("12m", "palliative") == PlanningQuery(365, "palliative")
    with pytest.raises(ValidationFailed):
        query_from("1y", "all")


def test_the_cohort_line_says_the_need_group_and_that_small_groups_are_hidden() -> None:
    text = cohort_text(PlanningQuery(90, "falls-and-frailty"))
    assert text == (
        "Cohort: age 65+, falls and frailty, within 2 hrs, ambulance crew or care home "
        "referrers. Groups under 10 are hidden."
    )
    assert "all needs" in cohort_text(PlanningQuery(90, "all"))


def test_a_figure_under_10_has_no_count_and_no_share() -> None:
    body = planning_json(_result(), PlanningQuery(90, "all"))

    assert body["referrals"] == {"count": 640, "suppressed": False}
    assert body["bestFitUnavailable"] == {"count": 112, "pct": 18, "suppressed": False}
    assert body["wentElsewhere"] == {"count": 62, "suppressed": False}
    assert body["flows"][1] == {
        "bestFit": "UCR West",
        "state": "not updated",
        "wentTo": "no destination recorded",
        "count": None,
        "suppressed": True,
    }
    assert body["declinedDespite"] == [
        {"service": "UCR East", "count": 11, "suppressed": False},
        {"service": "Ward A", "count": None, "suppressed": True},
    ]


def test_a_headline_under_10_is_withheld_with_its_share() -> None:
    result = PlanningResult(
        referrals=HIDDEN,
        best_fit_unavailable=HIDDEN,
        best_fit_unavailable_pct=HIDDEN,
        went_elsewhere=HIDDEN,
        flows=(),
        heat={},
        busiest=None,
        declined_despite=(),
    )
    body = planning_json(result, PlanningQuery(30, "all"))

    assert body["referrals"] == {"count": None, "suppressed": True}
    assert body["bestFitUnavailable"] == {"count": None, "pct": None, "suppressed": True}
    assert body["wentElsewhere"] == {"count": None, "suppressed": True}
    assert body["busiest"] is None


def test_the_grid_is_seven_days_by_four_bands_and_every_cell_under_10_is_null() -> None:
    body = planning_json(_result(), PlanningQuery(90, "all"))

    grid = body["grid"]
    assert len(grid) == 7
    assert all(len(row) == 4 for row in grid)
    assert grid[3][2] == 12  # Thursday, 12:00 to 18:00
    assert grid[0][0] is None  # a hidden cell is not a zero
    assert grid[6][3] is None  # a cell nobody landed in is not a zero either
    assert body["busiest"] == {"day": 3, "band": 2, "count": 12}


def test_the_answer_names_no_case_reference_postcode_or_person() -> None:
    text = str(planning_json(_result(), PlanningQuery(90, "all"))).lower()

    for word in ("case-", "postcode", "practitioner", "advisor", "reference"):
        assert word not in text
