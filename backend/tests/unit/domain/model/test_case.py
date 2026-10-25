"""Tests for diucs.domain.model.case: the advisor case, its scores and its outcome (D18).

Rules from docs/spec/domain-rules.md section 4 and the D18 prompt. On close the postcode and
needs are cleared; the audit summary keeps what is needed for audit and is taken before close.
"""

from dataclasses import fields
from datetime import UTC, datetime

import pytest

from diucs.domain.codes import (
    AgeBand,
    BestFitNotUsedReason,
    NeedCategory,
    Outcome,
    ReferrerType,
    Urgency,
)
from diucs.domain.errors import InvalidTransition, ValidationFailed
from diucs.domain.model.case import Case, audit_summary, priority_for
from diucs.domain.model.scores import (
    AmbulanceCategory,
    ClinicalFrailty,
    ManchesterTriage,
    News2,
    PathwaysDx,
)

OPENED = datetime(2026, 10, 24, 8, 15, tzinfo=UTC)
CLOSED = datetime(2026, 10, 24, 8, 40, tzinfo=UTC)
DESTINATION = "svc-ucr-west"


def _case(**overrides: object) -> Case:
    fields_: dict[str, object] = {
        "id": "case-1",
        "reference": "C-0001",
        "referrer_type": ReferrerType.AMBULANCE_CREW,
        "age_band": AgeBand.A80_PLUS,
        "postcode": "DT4 8XX",
        "needs": (NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
        "urgency": Urgency.WITHIN_2_HRS,
        "scores": (News2(2), ClinicalFrailty(6)),
        "opened_at": OPENED,
    }
    fields_.update(overrides)
    return Case(**fields_)  # type: ignore[arg-type]


def test_two_scores_for_the_same_method_are_refused() -> None:
    with pytest.raises(ValidationFailed):
        _case(scores=(News2(2), News2(5)))


def test_one_score_per_method_is_accepted_for_every_method() -> None:
    case = _case(
        scores=(
            News2(2),
            ClinicalFrailty(6),
            AmbulanceCategory(1),
            ManchesterTriage("urgent"),
            PathwaysDx("DX0121"),
        )
    )
    assert len(case.scores) == 5


def test_naive_opened_at_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        _case(opened_at=datetime(2026, 10, 24, 8, 15))


def test_close_clears_postcode_and_needs_and_keeps_the_audit_fields() -> None:
    closed = _case().close(Outcome.ACCEPTED_AND_BOOKED, CLOSED, destination_service_id=DESTINATION)

    assert closed.postcode is None
    assert closed.needs == ()
    assert closed.outcome is Outcome.ACCEPTED_AND_BOOKED
    assert closed.closed_at == CLOSED
    assert closed.destination_service_id == DESTINATION
    assert closed.scores == (News2(2), ClinicalFrailty(6))
    assert closed.age_band is AgeBand.A80_PLUS
    assert closed.urgency is Urgency.WITHIN_2_HRS
    assert closed.id == "case-1"
    assert closed.reference == "C-0001"
    assert closed.referrer_type is ReferrerType.AMBULANCE_CREW


def test_close_returns_a_new_case_and_leaves_the_original_unchanged() -> None:
    original = _case()
    original.close(Outcome.ACCEPTED_AND_BOOKED, CLOSED, destination_service_id=DESTINATION)

    assert original.postcode == "DT4 8XX"
    assert original.needs == (NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY)
    assert original.closed_at is None
    assert original.outcome is None


def test_close_records_the_best_fit_not_used_reason() -> None:
    closed = _case().close(
        Outcome.REDIRECTED,
        CLOSED,
        best_fit_not_used=BestFitNotUsedReason.FULL,
    )
    assert closed.best_fit_not_used is BestFitNotUsedReason.FULL


def test_accepted_and_booked_without_a_destination_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        _case().close(Outcome.ACCEPTED_AND_BOOKED, CLOSED)


def test_closing_twice_raises_invalid_transition() -> None:
    closed = _case().close(Outcome.ACCEPTED_AND_BOOKED, CLOSED, destination_service_id=DESTINATION)
    with pytest.raises(InvalidTransition):
        closed.close(Outcome.DECLINED, CLOSED)


def test_naive_close_time_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        _case().close(Outcome.DECLINED, datetime(2026, 10, 24, 8, 40))


def test_audit_summary_taken_before_close_keeps_both_needs() -> None:
    case = _case()
    summary = audit_summary(
        case, Outcome.ACCEPTED_AND_BOOKED, CLOSED, destination_service_id=DESTINATION
    )

    assert summary.needs == (NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY)
    assert summary.reference == "C-0001"
    assert summary.referrer_type is ReferrerType.AMBULANCE_CREW
    assert summary.age_band is AgeBand.A80_PLUS
    assert summary.urgency is Urgency.WITHIN_2_HRS
    assert summary.scores == (News2(2), ClinicalFrailty(6))
    assert summary.outcome is Outcome.ACCEPTED_AND_BOOKED
    assert summary.destination_service_id == DESTINATION
    assert summary.opened_at == OPENED
    assert summary.closed_at == CLOSED


def test_audit_summary_has_no_postcode_field() -> None:
    names = {field.name for field in fields(audit_summary(_case(), Outcome.DECLINED, CLOSED))}
    assert "postcode" not in names


def test_audit_summary_applies_the_same_destination_rule_as_close() -> None:
    with pytest.raises(ValidationFailed):
        audit_summary(_case(), Outcome.ACCEPTED_AND_BOOKED, CLOSED)


def test_audit_summary_of_a_closed_case_is_refused() -> None:
    closed = _case().close(Outcome.DECLINED, CLOSED)
    with pytest.raises(InvalidTransition):
        audit_summary(closed, Outcome.DECLINED, CLOSED)


@pytest.mark.parametrize(
    ("urgency", "priority"),
    [
        (Urgency.WITHIN_2_HRS, "urgent"),
        (Urgency.TODAY, "routine"),
        (Urgency.PLANNED, "routine"),
    ],
)
def test_priority_for_maps_urgency_to_service_request_priority(
    urgency: Urgency, priority: str
) -> None:
    assert priority_for(urgency) == priority


def test_priority_for_refuses_an_unknown_urgency_rather_than_routine() -> None:
    with pytest.raises(ValidationFailed):
        priority_for("someday")  # type: ignore[arg-type]
