"""RegistrationPersisted (U27): the event a registration's resources being written puts on
registration.events. Sample values only."""

from datetime import UTC, datetime

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.events import RegistrationPersisted, from_payload, session_id_for, topic_for

AT = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)


def test_the_payload_is_the_registration_the_service_and_the_utc_time() -> None:
    assert RegistrationPersisted("reg-1", "svc-ucr-west", AT).to_payload() == {
        "registration_id": "reg-1",
        "service_id": "svc-ucr-west",
        "at": "2026-10-29T10:00:00Z",
    }


def test_it_goes_to_the_registration_topic_with_no_session() -> None:
    event = RegistrationPersisted("reg-1", "svc-ucr-west", AT)
    assert topic_for(event) == "registration.events"
    assert session_id_for(event) is None
    assert event.event_type == "RegistrationPersisted"


def test_the_event_round_trips_through_its_payload() -> None:
    event = RegistrationPersisted("reg-1", "svc-ucr-west", AT)
    assert from_payload("RegistrationPersisted", event.to_payload()) == event


def test_both_ids_are_required_and_must_be_text() -> None:
    valid = {"registration_id": "reg-1", "service_id": "svc-ucr-west", "at": "2026-10-29T10:00:00Z"}
    assert from_payload("RegistrationPersisted", valid) == RegistrationPersisted(
        "reg-1", "svc-ucr-west", AT
    )
    for missing in ("registration_id", "service_id"):
        with pytest.raises(ValidationFailed):
            from_payload("RegistrationPersisted", {k: v for k, v in valid.items() if k != missing})
        with pytest.raises(ValidationFailed):
            from_payload("RegistrationPersisted", {**valid, missing: 7})


def test_a_time_that_is_not_utc_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        RegistrationPersisted("reg-1", "svc-ucr-west", datetime(2026, 10, 29, 10, 0))
