"""Pure rules of the safety concern and problem report (U41): the categories, the text limit and
the reference format. Sample values only: no patient data.
"""

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.safety_report import (
    MAX_TEXT_LENGTH,
    ProblemCategory,
    SafetyConcernCategory,
    checked_concern_text,
    checked_problem_text,
    concern_notice,
    safety_reference,
)


def test_the_five_safety_concern_categories_are_the_ones_to_agree_with_the_officer() -> None:
    assert {c.value for c in SafetyConcernCategory} == {
        "wrong-service-shown",
        "out-of-date-criteria",
        "wrong-status-on-board",
        "message-went-to-wrong-place",
        "something-else",
    }


def test_the_four_problem_categories_are_the_help_screen_ones() -> None:
    assert {c.value for c in ProblemCategory} == {
        "screen-slow",
        "button-does-not-work",
        "figure-looks-wrong",
        "something-else",
    }


def test_the_text_limit_is_280_characters() -> None:
    assert MAX_TEXT_LENGTH == 280


def test_a_concern_text_of_280_characters_is_kept_as_it_is() -> None:
    text = "a" * 280
    assert checked_concern_text(text) == text


@pytest.mark.parametrize("text", [None, "", "   ", "\n\t", 123, b"bytes"])
def test_a_concern_without_text_is_refused(text: object) -> None:
    with pytest.raises(ValidationFailed):
        checked_concern_text(text)  # type: ignore[arg-type]


def test_a_concern_text_of_281_characters_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        checked_concern_text("a" * 281)


def test_a_refusal_never_echoes_the_text() -> None:
    secret = "Mrs Sample said the figure was wrong " * 10
    with pytest.raises(ValidationFailed) as refused:
        checked_concern_text(secret)
    assert "Mrs Sample" not in str(refused.value)


def test_a_problem_report_may_leave_its_text_out() -> None:
    assert checked_problem_text(None) is None
    assert checked_problem_text("") is None


def test_a_problem_report_text_is_limited_to_280_characters() -> None:
    assert checked_problem_text("b" * 280) == "b" * 280
    with pytest.raises(ValidationFailed):
        checked_problem_text("b" * 281)


@pytest.mark.parametrize(
    ("sequence", "reference"),
    [(1, "SC-0001"), (2, "SC-0002"), (192, "SC-0192"), (9999, "SC-9999"), (10000, "SC-10000")],
)
def test_the_reference_is_sc_and_a_four_digit_sequence(sequence: int, reference: str) -> None:
    assert safety_reference(sequence) == reference


@pytest.mark.parametrize("sequence", [0, -1])
def test_a_sequence_below_one_has_no_reference(sequence: int) -> None:
    with pytest.raises(ValidationFailed):
        safety_reference(sequence)


def test_the_officer_notice_names_the_reference_and_nothing_else() -> None:
    title, body = concern_notice("SC-0192")
    assert title == "New safety concern SC-0192"
    assert "SC-0192" not in body
    assert "wrong" not in (title + body).lower()
