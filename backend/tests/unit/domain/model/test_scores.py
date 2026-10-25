"""Tests for diucs.domain.model.scores: referrer score value objects (D18).

Rules from docs/spec/domain-rules.md section 4. Scores are recorded as given; the tool never
calculates or checks them beyond the allowed range or list. Errors never echo the value.
"""

from collections.abc import Callable

import pytest

from diucs.domain.codes import AcuityMethod
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.scores import (
    AmbulanceCategory,
    ClinicalFrailty,
    ManchesterTriage,
    News2,
    PathwaysDx,
    method_of,
)


def assert_rejected(field: str, build: Callable[[], object]) -> None:
    with pytest.raises(ValidationFailed) as info:
        build()
    assert info.value.field == field


@pytest.mark.parametrize("value", [-1, 21, 100])
def test_news2_rejects_values_outside_0_to_20(value: int) -> None:
    assert_rejected("news2", lambda: News2(value))


@pytest.mark.parametrize("value", [0, 20])
def test_news2_accepts_the_boundary_values(value: int) -> None:
    assert News2(value).value == value


def test_news2_rejects_a_bool_even_though_it_is_an_int() -> None:
    assert_rejected("news2", lambda: News2(True))


@pytest.mark.parametrize("value", [0, 10])
def test_clinical_frailty_rejects_values_outside_1_to_9(value: int) -> None:
    assert_rejected("clinical_frailty", lambda: ClinicalFrailty(value))


@pytest.mark.parametrize("value", [1, 9])
def test_clinical_frailty_accepts_the_boundary_values(value: int) -> None:
    assert ClinicalFrailty(value).value == value


@pytest.mark.parametrize("value", [0, 5])
def test_ambulance_category_rejects_values_outside_1_to_4(value: int) -> None:
    assert_rejected("ambulance_category", lambda: AmbulanceCategory(value))


@pytest.mark.parametrize("value", [1, 4])
def test_ambulance_category_accepts_the_boundary_values(value: int) -> None:
    assert AmbulanceCategory(value).value == value


@pytest.mark.parametrize("level", ["high", "Immediate", "", "non urgent"])
def test_manchester_rejects_levels_that_are_not_on_the_list(level: str) -> None:
    assert_rejected("manchester_triage", lambda: ManchesterTriage(level))


@pytest.mark.parametrize("level", ["immediate", "very-urgent", "urgent", "standard", "non-urgent"])
def test_manchester_accepts_each_listed_level(level: str) -> None:
    assert ManchesterTriage(level).level == level


@pytest.mark.parametrize("code", ["Dx0121", "dx0121", "DX-0121", "DX 0121", "D", "DX012345678"])
def test_pathways_dx_rejects_bad_format(code: str) -> None:
    assert_rejected("pathways_dx", lambda: PathwaysDx(code))


def test_pathways_dx_rejects_a_trailing_newline() -> None:
    assert_rejected("pathways_dx", lambda: PathwaysDx("DX0121\n"))


@pytest.mark.parametrize("code", ["DX0121", "DX", "DX01234567"])
def test_pathways_dx_accepts_upper_case_and_digits_from_2_to_10_characters(code: str) -> None:
    assert PathwaysDx(code).code == code


def test_pathways_dx_error_does_not_echo_the_code() -> None:
    with pytest.raises(ValidationFailed) as info:
        PathwaysDx("Dx0121")
    assert "Dx0121" not in str(info.value)


@pytest.mark.parametrize(
    ("build", "method"),
    [
        (lambda: News2(2), AcuityMethod.NEWS2),
        (lambda: ClinicalFrailty(6), AcuityMethod.CFS),
        (lambda: AmbulanceCategory(1), AcuityMethod.AMBULANCE_CATEGORY),
        (lambda: ManchesterTriage("urgent"), AcuityMethod.MANCHESTER),
        (lambda: PathwaysDx("DX0121"), AcuityMethod.PATHWAYS_DX),
    ],
)
def test_method_of_names_the_acuity_method(
    build: Callable[[], object], method: AcuityMethod
) -> None:
    assert method_of(build()) is method  # type: ignore[arg-type]
