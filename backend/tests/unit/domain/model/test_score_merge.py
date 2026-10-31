"""Recorded scores and their correction (Q7, DEC-1100, KI-815).

A score is recorded as given. A later write merges by method: a method not yet recorded is added,
a method recorded with another value is a correction, a method not mentioned stays as recorded.
Nothing here calculates or judges a score.
"""

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.scores import (
    AmbulanceCategory,
    ClinicalFrailty,
    ManchesterTriage,
    News2,
    PathwaysDx,
    ScoreCorrectionReason,
    merge_scores,
    score_record,
)


def test_a_first_recording_adds_every_score() -> None:
    merged = merge_scores((), (News2(2), ClinicalFrailty(6)))

    assert merged.scores == (News2(2), ClinicalFrailty(6))
    assert merged.added == (News2(2), ClinicalFrailty(6))
    assert merged.corrected == ()


def test_repeating_the_recorded_scores_changes_nothing() -> None:
    merged = merge_scores((News2(2), ClinicalFrailty(6)), (ClinicalFrailty(6), News2(2)))

    assert merged.scores == (News2(2), ClinicalFrailty(6))
    assert merged.added == ()
    assert merged.corrected == ()


def test_another_value_for_a_recorded_method_is_a_correction_that_keeps_the_original_pair() -> None:
    merged = merge_scores((News2(2), ClinicalFrailty(6)), (News2(5),))

    assert merged.scores == (News2(5), ClinicalFrailty(6))
    assert merged.corrected == ((News2(2), News2(5)),)
    assert merged.added == ()


def test_a_method_not_yet_recorded_is_added_after_the_recorded_ones() -> None:
    merged = merge_scores((News2(2),), (AmbulanceCategory(3), News2(2)))

    assert merged.scores == (News2(2), AmbulanceCategory(3))
    assert merged.added == (AmbulanceCategory(3),)
    assert merged.corrected == ()


def test_a_correction_and_an_addition_can_come_together() -> None:
    merged = merge_scores((ManchesterTriage("urgent"),), (ManchesterTriage("standard"), News2(1)))

    assert merged.scores == (ManchesterTriage("standard"), News2(1))
    assert merged.corrected == ((ManchesterTriage("urgent"), ManchesterTriage("standard")),)
    assert merged.added == (News2(1),)


def test_two_scores_of_one_method_in_one_write_are_refused() -> None:
    with pytest.raises(ValidationFailed) as refused:
        merge_scores((), (News2(1), News2(2)))

    assert refused.value.field == "scores"


def test_the_reasons_are_a_closed_set_of_codes_never_free_text() -> None:
    assert {reason.value for reason in ScoreCorrectionReason} == {
        "typing-error",
        "referrer-corrected",
        "rescored",
    }


@pytest.mark.parametrize(
    ("score", "record"),
    [
        (News2(2), {"method": "news2", "value": 2}),
        (ClinicalFrailty(6), {"method": "cfs", "value": 6}),
        (AmbulanceCategory(1), {"method": "ambulance-category", "value": 1}),
        (ManchesterTriage("urgent"), {"method": "manchester", "value": "urgent"}),
        (PathwaysDx("Dx02"), {"method": "pathways-dx", "value": "Dx02"}),
    ],
)
def test_a_score_record_holds_the_method_and_the_value_only(
    score: object, record: dict[str, object]
) -> None:
    assert score_record(score) == record  # type: ignore[arg-type]
