"""Hard criteria filter (D20, docs/spec/domain-rules.md section 4.1).

Fixtures are synthetic: the UCR West v3 sample service from the D20 prompt. No patient data.
The filter fails closed: an unknown or missing criterion excludes the service.
"""

from enum import StrEnum

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.domain.codes import AgeBand, CriteriaStatus, NeedCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.rules.criteria_filter import AGE_BAND_BOUNDS, FilterResult, check_hard_criteria
from tests.unit.domain.model.test_criteria import ucr_west

AGE_OVERLAP_WARNING = "Check age: band overlaps the service's age limits"


class _OtherCodes(StrEnum):
    """A different enum whose member has the same value as a need (lesson L3)."""

    FRAILTY = "frailty"


def run(
    criteria: ServiceCriteria | None = None,
    age: AgeBand | None = AgeBand.A80_PLUS,
    district: str = "DT4",
    needs: tuple[object, ...] = (NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
) -> FilterResult:
    # Untyped inputs are passed on purpose: the filter must fail closed at run time too.
    return check_hard_criteria(
        criteria if criteria is not None else ucr_west(),
        age,  # type: ignore[arg-type]
        district,
        needs,  # type: ignore[arg-type]
    )


def test_passes_with_no_reasons_and_no_warnings() -> None:
    result = run()
    assert result.passes is True
    assert result.reasons == ()
    assert result.warnings == ()


def test_partial_age_overlap_passes_with_the_age_warning() -> None:
    result = run(age=AgeBand.A16_64, needs=(NeedCategory.FRAILTY,))
    assert result.passes is True
    assert result.reasons == ()
    assert result.warnings == (AGE_OVERLAP_WARNING,)


def test_band_entirely_below_the_age_minimum_fails() -> None:
    result = run(age=AgeBand.A0_15, needs=(NeedCategory.FRAILTY,))
    assert result.passes is False
    assert result.reasons == ("Age 0-15 outside 18 to no limit",)
    assert result.warnings == ()


def test_district_not_covered_fails() -> None:
    result = run(district="DT5", needs=(NeedCategory.FRAILTY,))
    assert result.passes is False
    assert result.reasons == ("Does not cover DT5",)


def test_excluded_need_fails_with_does_not_accept() -> None:
    result = run(needs=(NeedCategory.FRAILTY, NeedCategory.SUSPECTED_FRACTURE))
    assert result.passes is False
    assert result.reasons == ("Does not accept suspected-fracture",)


def test_need_not_in_accepts_fails_with_does_not_take() -> None:
    result = run(needs=(NeedCategory.WOUND_CARE,))
    assert result.passes is False
    assert result.reasons == ("Does not take wound-care",)


def test_a_service_whose_criteria_are_not_current_fails() -> None:
    criteria = ucr_west(status=CriteriaStatus.PENDING_APPROVAL)
    result = run(criteria=criteria, needs=(NeedCategory.FRAILTY,))
    assert result.passes is False
    assert result.reasons == ("Criteria not current",)


@pytest.mark.parametrize(
    "status",
    [CriteriaStatus.DRAFT, CriteriaStatus.SUPERSEDED, CriteriaStatus.RETIRED],
)
def test_every_status_other_than_current_fails(status: CriteriaStatus) -> None:
    result = run(criteria=ucr_west(status=status), needs=(NeedCategory.FRAILTY,))
    assert result.passes is False
    assert result.reasons == ("Criteria not current",)


def test_two_failures_give_two_reasons_in_the_stated_order() -> None:
    result = run(
        criteria=ucr_west(status=CriteriaStatus.DRAFT),
        district="DT5",
        needs=(NeedCategory.FRAILTY, NeedCategory.SUSPECTED_FRACTURE),
    )
    assert result.reasons == (
        "Criteria not current",
        "Does not cover DT5",
        "Does not accept suspected-fracture",
    )


def test_reasons_follow_the_order_status_district_excluded_accepts_age() -> None:
    result = run(
        criteria=ucr_west(status=CriteriaStatus.RETIRED),
        age=AgeBand.A0_15,
        district="DT9",
        needs=(NeedCategory.WOUND_CARE, NeedCategory.IV_THERAPY),
    )
    assert result.reasons == (
        "Criteria not current",
        "Does not cover DT9",
        "Does not accept iv-therapy",
        "Does not take wound-care",
        "Age 0-15 outside 18 to no limit",
    )


def test_empty_needs_pass_the_need_checks() -> None:
    result = run(needs=())
    assert result.passes is True
    assert result.reasons == ()


def test_each_offending_need_gives_its_own_reason() -> None:
    result = run(needs=(NeedCategory.WOUND_CARE, NeedCategory.PALLIATIVE))
    assert result.reasons == ("Does not take wound-care", "Does not take palliative")


def test_age_maximum_is_reported_when_it_is_the_limit() -> None:
    criteria = ucr_west(age_min=18, age_max=64)
    result = run(criteria=criteria, age=AgeBand.A80_PLUS, needs=(NeedCategory.FRAILTY,))
    assert result.passes is False
    assert result.reasons == ("Age 80+ outside 18 to 64",)


@pytest.mark.parametrize(
    ("age", "passes", "warned"),
    [
        (AgeBand.A0_15, False, False),
        (AgeBand.A16_64, True, True),
        (AgeBand.A65_79, True, False),
        (AgeBand.A80_PLUS, True, False),
    ],
)
def test_each_band_against_the_sample_age_limits(age: AgeBand, passes: bool, warned: bool) -> None:
    result = run(age=age, needs=(NeedCategory.FRAILTY,))
    assert result.passes is passes
    assert (result.warnings == (AGE_OVERLAP_WARNING,)) is warned


def test_age_bound_table_matches_the_rule_book() -> None:
    assert AGE_BAND_BOUNDS == {
        AgeBand.A0_15: (0, 15),
        AgeBand.A16_64: (16, 64),
        AgeBand.A65_79: (65, 79),
        AgeBand.A80_PLUS: (80, None),
    }


def test_an_unrecognised_age_band_excludes_the_service() -> None:
    result = run(age="80+", needs=(NeedCategory.FRAILTY,))  # type: ignore[arg-type]
    assert result.passes is False
    assert result.reasons == ("Age not recognised",)


def test_a_missing_age_band_excludes_the_service() -> None:
    result = run(age=None, needs=(NeedCategory.FRAILTY,))
    assert result.passes is False
    assert result.reasons == ("Age not recognised",)


def test_an_unrecognised_need_excludes_the_service_without_echoing_it() -> None:
    result = run(needs=(NeedCategory.FRAILTY, "frailty"))
    assert result.passes is False
    assert result.reasons == ("Need not recognised",)


def test_a_need_from_another_enum_with_the_same_value_is_not_accepted() -> None:
    result = run(needs=(_OtherCodes.FRAILTY,))
    assert result.passes is False
    assert result.reasons == ("Need not recognised",)


_NEEDS = list(NeedCategory)


@settings(max_examples=200, deadline=None)
@given(needs=st.lists(st.sampled_from(_NEEDS), max_size=6))
def test_passes_exactly_when_every_need_is_accepted_and_none_excluded(
    needs: list[NeedCategory],
) -> None:
    criteria = ucr_west()
    result = check_hard_criteria(criteria, AgeBand.A80_PLUS, "DT4", needs)
    expected = set(needs) <= criteria.accepts
    assert result.passes is expected
    if any(need in criteria.excludes for need in needs):
        assert result.passes is False


@settings(max_examples=100, deadline=None)
@given(district=st.sampled_from(["DT1", "DT2", "DT3", "DT4", "DT5", "DT6", "SW1A"]))
def test_district_passes_exactly_when_it_is_covered(district: str) -> None:
    criteria = ucr_west()
    result = check_hard_criteria(criteria, AgeBand.A80_PLUS, district, (NeedCategory.FRAILTY,))
    assert result.passes is (district in criteria.districts)


def test_a_service_with_no_districts_is_never_covered() -> None:
    result = run(criteria=ucr_west(districts=frozenset()), needs=(NeedCategory.FRAILTY,))
    assert result.passes is False
    assert result.reasons == ("Does not cover DT4",)


def test_a_non_text_district_is_not_covered() -> None:
    result = run(district=None, needs=(NeedCategory.FRAILTY,))  # type: ignore[arg-type]
    assert result.passes is False
    assert result.reasons == ("Does not cover None",)


@pytest.mark.parametrize(
    ("age_min", "age_max", "age", "passes", "warned"),
    [
        (65, None, AgeBand.A65_79, True, False),
        (18, 65, AgeBand.A65_79, True, True),
        (64, None, AgeBand.A16_64, True, True),
        (15, None, AgeBand.A0_15, True, True),
        (16, None, AgeBand.A0_15, False, False),
    ],
)
def test_age_edges_are_inclusive(
    age_min: int, age_max: int | None, age: AgeBand, passes: bool, warned: bool
) -> None:
    criteria = ucr_west(age_min=age_min, age_max=age_max)
    result = run(criteria=criteria, age=age, needs=(NeedCategory.FRAILTY,))
    assert result.passes is passes
    assert (result.warnings == (AGE_OVERLAP_WARNING,)) is warned


def test_band_fully_inside_an_upper_limit_it_meets_passes_without_warning() -> None:
    # 65-79 ends exactly at age_max 79: fully inside, so no overlap warning (mutant: band_max < age_max).
    result = run(
        criteria=ucr_west(age_min=18, age_max=79), age=AgeBand.A65_79, needs=(NeedCategory.FRAILTY,)
    )
    assert result.passes is True
    assert result.warnings == ()


def test_band_ending_one_year_past_the_upper_limit_passes_with_warning() -> None:
    result = run(
        criteria=ucr_west(age_min=18, age_max=78), age=AgeBand.A65_79, needs=(NeedCategory.FRAILTY,)
    )
    assert result.passes is True
    assert result.warnings == (AGE_OVERLAP_WARNING,)


def test_a_missing_criteria_version_is_refused_with_the_field_named() -> None:
    with pytest.raises(ValidationFailed) as error:
        check_hard_criteria(None, AgeBand.A80_PLUS, "DT4", (NeedCategory.FRAILTY,))  # type: ignore[arg-type]
    assert error.value.field == "criteria"


def test_missing_needs_are_refused_with_the_field_named() -> None:
    with pytest.raises(ValidationFailed) as error:
        check_hard_criteria(ucr_west(), AgeBand.A80_PLUS, "DT4", None)  # type: ignore[arg-type]
    assert error.value.field == "needs"
