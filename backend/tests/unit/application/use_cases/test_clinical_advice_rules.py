"""Pure rules of the clinical advice requests (U40): the presence key and its wording, the request
and advice choices, the queue that releases idle locks, and the notice text (no postcode, no
name). No I/O."""

from datetime import UTC, datetime, timedelta

import pytest

from diucs.application.use_cases.clinical_advice import (
    ADVICE_CHOICES,
    PRESENCE_TTL,
    REQUEST_WHYS,
    advice_notice,
    parse_presence,
    presence_key,
    queue_now,
    validate_advice,
    validate_request,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.clinical import ClinicalAdvice, ClinicalRequestRecord
from diucs.domain.rules.clinical_queue import ClinicalRequest, Presence

T0 = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)


def _record(
    key: str,
    urgency: str,
    requested: datetime,
    taken_by: str | None = None,
    taken_at: datetime | None = None,
    advised_at: datetime | None = None,
) -> ClinicalRequestRecord:
    return ClinicalRequestRecord(
        request=ClinicalRequest(
            id=key,
            case_id=f"case-{key}",
            urgency=urgency,
            requested_at=requested,
            taken_by=taken_by,
            taken_at=taken_at,
            advised_at=advised_at,
        ),
        requester_id="prac-advisor-1",
        why="borderline-criteria",
        snapshot_ref=None,
    )


def test_the_presence_key_and_its_lifetime_are_as_the_architecture_says() -> None:
    assert presence_key("prac-clin-1") == "presence:clinical:prac-clin-1"
    assert timedelta(seconds=120) == PRESENCE_TTL


def test_an_empty_clinician_has_no_presence_key() -> None:
    with pytest.raises(ValidationFailed):
        presence_key("  ")


@pytest.mark.parametrize(
    ("text", "presence"),
    [("available", Presence.AVAILABLE), ("busy", Presence.BUSY), ("away", Presence.AWAY)],
)
def test_a_known_presence_is_read(text: str, presence: Presence) -> None:
    assert parse_presence(text) is presence


@pytest.mark.parametrize("text", [None, "", "AVAILABLE", "on-call"])
def test_an_unknown_or_missing_presence_is_not_available(text: str | None) -> None:
    assert parse_presence(text) is None


def test_the_request_and_advice_choices_are_fixed() -> None:
    assert set(REQUEST_WHYS) == {"borderline-criteria", "unsure-of-urgency", "other"}
    assert set(ADVICE_CHOICES) == {
        "go-ahead",
        "use-another-service",
        "clinical-call-to-referrer",
        "emergency-route",
    }


def test_a_request_needs_a_known_urgency_and_why() -> None:
    validate_request("now", "other")
    validate_request("within-15-min", "unsure-of-urgency")
    with pytest.raises(ValidationFailed):
        validate_request("today", "other")
    with pytest.raises(ValidationFailed):
        validate_request("now", "because")


def test_advice_needs_a_known_choice_and_a_known_reason_when_given() -> None:
    validate_advice("go-ahead", None)
    validate_advice("emergency-route", "safer-alternative")
    with pytest.raises(ValidationFailed):
        validate_advice("wait", None)
    with pytest.raises(ValidationFailed):
        validate_advice("go-ahead", "because I said so")


def test_an_idle_lock_is_released_into_the_queue() -> None:
    idle = _record("a", "now", T0, taken_by="clin-1", taken_at=T0)
    fresh = _record(
        "b", "now", T0 + timedelta(minutes=1), taken_by="clin-2", taken_at=T0 + timedelta(minutes=5)
    )
    now = T0 + timedelta(minutes=10)
    keys = [r.request.id for r in queue_now([idle, fresh], now)]
    assert keys == ["a"]


def test_an_advised_request_never_returns_to_the_queue() -> None:
    advised = ClinicalRequestRecord(
        request=ClinicalRequest(
            id="a",
            case_id="case-a",
            urgency="now",
            requested_at=T0,
            taken_by="clin-1",
            taken_at=T0,
            advised_at=T0,
        ),
        requester_id="prac-advisor-1",
        why="other",
        snapshot_ref=None,
        advice=ClinicalAdvice(
            choice="go-ahead",
            reason=None,
            note_handle=None,
            clinician_id="clin-1",
            at=T0,
        ),
    )
    assert queue_now([advised], T0 + timedelta(minutes=30)) == []


def test_the_queue_is_now_first_then_within_fifteen_then_oldest_first() -> None:
    within = _record("within", "within-15-min", T0)
    later_now = _record("later-now", "now", T0 + timedelta(minutes=2))
    first_now = _record("first-now", "now", T0)
    keys = [r.request.id for r in queue_now([within, later_now, first_now], T0)]
    assert keys == ["first-now", "later-now", "within"]


def test_the_notice_names_urgency_age_band_and_need_and_no_postcode() -> None:
    title, body = advice_notice("now", "80+", "falls")
    text = f"{title} {body}"
    assert "now" in body and "80+" in body and "falls" in body
    assert "DT4" not in text
