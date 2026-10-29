"""Clinical advice records (P18): the advice and the request record, with their refusals."""

from datetime import UTC, datetime

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.clinical import ClinicalAdvice, ClinicalRequestRecord
from diucs.domain.rules.clinical_queue import ClinicalRequest, give_advice, take

REQUESTED = datetime(2026, 10, 25, 13, 13, tzinfo=UTC)
TAKEN = datetime(2026, 10, 25, 13, 14, tzinfo=UTC)
ADVISED = datetime(2026, 10, 25, 13, 16, tzinfo=UTC)


def _waiting() -> ClinicalRequest:
    return ClinicalRequest(id="req-1", case_id="case-1", urgency="now", requested_at=REQUESTED)


def _record(request: ClinicalRequest | None = None, **changes: object) -> ClinicalRequestRecord:
    fields: dict[str, object] = {
        "request": request or _waiting(),
        "requester_id": "adv-1",
        "why": "borderline criteria",
        "snapshot_ref": "audit-1",
        "advice": None,
    }
    fields.update(changes)
    return ClinicalRequestRecord(**fields)  # type: ignore[arg-type]


def test_a_waiting_request_carries_its_reason_and_requester() -> None:
    record = _record()

    assert record.request.taken_by is None
    assert record.why == "borderline criteria"
    assert record.advice is None


def test_advice_records_its_choice_reason_and_note_handle() -> None:
    advice = ClinicalAdvice(
        choice="go-ahead",
        reason="within-criteria",
        note_handle="h-123",
        clinician_id="clin-1",
        at=ADVISED,
    )
    request = give_advice(take(_waiting(), "clin-1", TAKEN), "clin-1", ADVISED)

    record = _record(request=request, advice=advice)

    assert record.advice == advice


@pytest.mark.parametrize("choice", ["", "   "])
def test_advice_needs_a_choice(choice: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        ClinicalAdvice(
            choice=choice, reason=None, note_handle=None, clinician_id="clin-1", at=ADVISED
        )

    assert refused.value.field == "choice"


def test_advice_refuses_a_naive_time() -> None:
    with pytest.raises(ValidationFailed) as refused:
        ClinicalAdvice(
            choice="go-ahead",
            reason=None,
            note_handle=None,
            clinician_id="clin-1",
            at=datetime(2026, 10, 25, 13, 16),
        )

    assert refused.value.field == "at"


def test_advice_on_a_request_must_match_the_request_it_answers() -> None:
    advice = ClinicalAdvice(
        choice="go-ahead", reason=None, note_handle=None, clinician_id="clin-2", at=ADVISED
    )
    request = give_advice(take(_waiting(), "clin-1", TAKEN), "clin-1", ADVISED)

    with pytest.raises(ValidationFailed) as refused:
        _record(request=request, advice=advice)

    assert refused.value.field == "advice"


def test_a_request_with_advice_must_be_advised() -> None:
    advice = ClinicalAdvice(
        choice="go-ahead", reason=None, note_handle=None, clinician_id="clin-1", at=ADVISED
    )
    request = take(_waiting(), "clin-1", TAKEN)

    with pytest.raises(ValidationFailed) as refused:
        _record(request=request, advice=advice)

    assert refused.value.field == "advice"


def test_a_record_needs_a_requester_and_a_reason() -> None:
    with pytest.raises(ValidationFailed) as no_requester:
        _record(requester_id="")
    assert no_requester.value.field == "requester_id"

    with pytest.raises(ValidationFailed) as no_reason:
        _record(why=" ")
    assert no_reason.value.field == "why"
