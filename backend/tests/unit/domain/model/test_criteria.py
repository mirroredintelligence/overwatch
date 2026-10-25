"""Service criteria validation (D20, docs/spec/domain-rules.md section 4.2).

Fixtures are synthetic: a sample service (UCR West v3) from the D20 prompt. No patient data.
"""

from datetime import date
from enum import StrEnum

import pytest

from diucs.domain.codes import CriteriaStatus, NeedCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria


class _OtherCodes(StrEnum):
    """A different enum whose member has the same value as a need (lesson L3)."""

    FRAILTY = "frailty"


def ucr_west(**overrides: object) -> ServiceCriteria:
    values: dict[str, object] = {
        "id": "crit-ucr-west-3",
        "service_id": "svc-ucr-west",
        "version": 3,
        "status": CriteriaStatus.CURRENT,
        "age_min": 18,
        "age_max": None,
        "districts": frozenset({"DT1", "DT2", "DT3", "DT4"}),
        "accepts": frozenset({NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY}),
        "excludes": frozenset(
            {
                NeedCategory.SUSPECTED_FRACTURE,
                NeedCategory.HEAD_INJURY_ANTICOAGULANTS,
                NeedCategory.IV_THERAPY,
            }
        ),
        "review_by": date(2027, 1, 31),
        "owner_role_id": "role-owner-ucr-west",
    }
    values.update(overrides)
    return ServiceCriteria(**values)  # type: ignore[arg-type]


def test_the_sample_service_is_built_as_given() -> None:
    criteria = ucr_west()
    assert criteria.version == 3
    assert criteria.age_max is None
    assert criteria.change_reason == ""
    assert criteria.supersedes_id is None


@pytest.mark.parametrize("version", [0, -1])
def test_version_must_be_at_least_one(version: int) -> None:
    with pytest.raises(ValidationFailed) as error:
        ucr_west(version=version)
    assert error.value.field == "version"


def test_age_min_cannot_be_negative() -> None:
    with pytest.raises(ValidationFailed) as error:
        ucr_west(age_min=-1)
    assert error.value.field == "age_min"


def test_age_max_may_equal_age_min() -> None:
    assert ucr_west(age_min=18, age_max=18).age_max == 18


def test_age_max_below_age_min_is_refused() -> None:
    with pytest.raises(ValidationFailed) as error:
        ucr_west(age_min=18, age_max=17)
    assert error.value.field == "age_max"


def test_accepts_and_excludes_must_be_disjoint() -> None:
    with pytest.raises(ValidationFailed):
        ucr_west(
            accepts=frozenset({NeedCategory.FRAILTY, NeedCategory.IV_THERAPY}),
            excludes=frozenset({NeedCategory.IV_THERAPY}),
        )


@pytest.mark.parametrize("district", ["dt4", "DT4 8", "", "Dt4"])
def test_districts_must_be_upper_case_outward_codes(district: str) -> None:
    with pytest.raises(ValidationFailed) as error:
        ucr_west(districts=frozenset({district}))
    assert error.value.field == "districts"


def test_a_need_from_another_enum_with_the_same_value_is_refused() -> None:
    with pytest.raises(ValidationFailed) as error:
        ucr_west(accepts=frozenset({_OtherCodes.FRAILTY}))
    assert error.value.field == "accepts"


def test_a_plain_string_is_not_a_need() -> None:
    with pytest.raises(ValidationFailed) as error:
        ucr_west(excludes=frozenset({"iv-therapy"}))
    assert error.value.field == "excludes"


def test_status_must_be_a_criteria_status() -> None:
    with pytest.raises(ValidationFailed) as error:
        ucr_west(status="current")
    assert error.value.field == "status"


def test_a_need_in_both_lists_raises_validation_failed() -> None:
    with pytest.raises(ValidationFailed):
        ucr_west(
            accepts=frozenset({NeedCategory.SUSPECTED_FRACTURE}),
            excludes=frozenset({NeedCategory.SUSPECTED_FRACTURE}),
        )
