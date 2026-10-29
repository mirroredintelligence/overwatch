"""Pure rules of RecordOutcome (U14): the destination rule and the finish summary.

Sample values are the prompt's: a case 4821 for an 80+ patient with a fall and frailty, two scores,
within 2 hrs, booked to UCR West. The postcode is held as its district only (DEC-067).
"""

from datetime import UTC, datetime

import pytest

from diucs.application.use_cases.record_outcome import build_summary, check_destination
from diucs.domain.codes import AgeBand, NeedCategory, Outcome, ReferrerType, Urgency
from diucs.domain.errors import Conflict, ValidationFailed
from diucs.domain.model.case import Case
from diucs.domain.model.scores import ClinicalFrailty, News2

OPENED = datetime(2026, 10, 23, 13, 10, tzinfo=UTC)
UCR_WEST = "svc-ucr-west"


def _case(**changes: object) -> Case:
    fields: dict[str, object] = {
        "id": "case-4821",
        "reference": "4821",
        "referrer_type": ReferrerType.AMBULANCE_CREW,
        "age_band": AgeBand.A80_PLUS,
        "postcode": "DT4",
        "needs": (NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
        "urgency": Urgency.WITHIN_2_HRS,
        "scores": (News2(2), ClinicalFrailty(6)),
        "opened_at": OPENED,
    }
    fields.update(changes)
    return Case(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("outcome", "destination"),
    [
        (Outcome.ACCEPTED_AND_BOOKED, None),
        (Outcome.ACCEPTED_AND_BOOKED, "  "),
        (Outcome.REDIRECTED, None),
        (Outcome.DECLINED, UCR_WEST),
        (Outcome.CALLER_CANCELLED, UCR_WEST),
        (Outcome.NO_SERVICE_FITS, UCR_WEST),
        (Outcome.OUT_OF_AREA, UCR_WEST),
    ],
)
def test_the_destination_is_given_exactly_where_the_outcome_needs_one(
    outcome: Outcome, destination: str | None
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_destination(outcome, destination)

    assert refused.value.field == "destination_service_id"


@pytest.mark.parametrize(
    ("outcome", "destination"),
    [
        (Outcome.ACCEPTED_AND_BOOKED, UCR_WEST),
        (Outcome.REDIRECTED, UCR_WEST),
        (Outcome.DECLINED, None),
        (Outcome.CALLER_CANCELLED, None),
        (Outcome.NO_SERVICE_FITS, None),
        (Outcome.OUT_OF_AREA, None),
    ],
)
def test_a_valid_outcome_and_destination_pair_is_accepted(
    outcome: Outcome, destination: str | None
) -> None:
    check_destination(outcome, destination)


def test_the_summary_has_the_nine_rows_in_order_with_the_stored_district() -> None:
    rows = build_summary(
        _case(),
        destination_name="UCR West",
        booking_line="Confirmed 14:19, reference 4821",
        data_age_line="Capacity 9 min old · criteria v3",
    )

    assert rows == [
        ("Referrer", "Ambulance crew"),
        ("Age band", "80+"),
        ("Postcode", "DT4"),
        ("Needs", "Fall, frailty"),
        ("Urgency", "Within 2 hrs"),
        ("Scores", "NEWS2 2 · Frailty scale 6"),
        ("Destination", "UCR West"),
        ("Booked", "Confirmed 14:19, reference 4821"),
        ("Data age", "Capacity 9 min old · criteria v3"),
    ]


def test_the_booked_row_is_omitted_when_there_is_no_booking() -> None:
    rows = build_summary(
        _case(),
        destination_name="UCR West",
        booking_line=None,
        data_age_line="Capacity 9 min old · criteria v3",
    )

    assert "Booked" not in [label for label, _ in rows]
    assert len(rows) == 8


def test_an_empty_value_is_omitted_and_not_shown_as_a_blank_row() -> None:
    rows = build_summary(
        _case(scores=(), needs=(NeedCategory.FRAILTY,), age_band=None),
        destination_name=None,
        booking_line=None,
        data_age_line=None,
    )

    assert [label for label, _ in rows] == ["Referrer", "Postcode", "Needs", "Urgency"]


def test_the_summary_is_built_only_while_the_case_is_open() -> None:
    closed = _case().close(Outcome.DECLINED, datetime(2026, 10, 23, 13, 40, tzinfo=UTC))

    with pytest.raises(Conflict):
        build_summary(closed, destination_name=None, booking_line=None, data_age_line=None)
