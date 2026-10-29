"""ReporterInvited (U24): the event an invitation puts on registration.events. Sample values only."""

from datetime import UTC, datetime

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.events import ReporterInvited, from_payload, session_id_for, topic_for

AT = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


def test_the_payload_is_the_invitation_the_service_and_the_utc_time() -> None:
    assert ReporterInvited("inv-1", "svc-ucr-west", AT).to_payload() == {
        "invitation_id": "inv-1",
        "service_id": "svc-ucr-west",
        "at": "2026-10-29T09:00:00Z",
    }


def test_it_goes_to_the_registration_topic_with_no_session() -> None:
    event = ReporterInvited("inv-1", "svc-ucr-west", AT)
    assert topic_for(event) == "registration.events"
    assert session_id_for(event) is None
    assert event.event_type == "ReporterInvited"


def test_the_event_round_trips_through_its_payload() -> None:
    event = ReporterInvited("inv-1", "svc-ucr-west", AT)
    assert from_payload("ReporterInvited", event.to_payload()) == event


def test_both_ids_are_required_and_must_be_text() -> None:
    valid = {"invitation_id": "inv-1", "service_id": "svc-ucr-west", "at": "2026-10-29T09:00:00Z"}
    assert from_payload("ReporterInvited", valid) == ReporterInvited("inv-1", "svc-ucr-west", AT)
    for missing in ("invitation_id", "service_id"):
        with pytest.raises(ValidationFailed):
            from_payload("ReporterInvited", {k: v for k, v in valid.items() if k != missing})
        with pytest.raises(ValidationFailed):
            from_payload("ReporterInvited", {**valid, missing: 7})


def test_a_time_that_is_not_utc_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        ReporterInvited("inv-1", "svc-ucr-west", datetime(2026, 10, 29, 9, 0))
