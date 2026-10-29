"""ServiceActivated (U15): the event a lead's set-up puts on registration.events. Sample values only."""

from datetime import UTC, datetime

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.events import ServiceActivated, from_payload, session_id_for, topic_for

AT = datetime(2026, 10, 29, 9, 10, tzinfo=UTC)


def test_the_payload_is_the_service_and_the_utc_time() -> None:
    assert ServiceActivated("svc-ucr-west", AT).to_payload() == {
        "service_id": "svc-ucr-west",
        "at": "2026-10-29T09:10:00Z",
    }


def test_it_goes_to_the_registration_topic_with_no_session() -> None:
    event = ServiceActivated("svc-ucr-west", AT)
    assert topic_for(event) == "registration.events"
    assert session_id_for(event) is None


def test_the_event_round_trips_through_its_payload() -> None:
    event = ServiceActivated("svc-ucr-west", AT)
    assert from_payload("ServiceActivated", event.to_payload()) == event


def test_a_service_id_is_required_and_must_be_text() -> None:
    # The valid payload is decoded first, so a refusal below cannot pass by the event being unknown.
    assert from_payload(
        "ServiceActivated", {"service_id": "svc-ucr-west", "at": "2026-10-29T09:10:00Z"}
    ) == ServiceActivated("svc-ucr-west", AT)
    with pytest.raises(ValidationFailed):
        from_payload("ServiceActivated", {"at": "2026-10-29T09:10:00Z"})
    with pytest.raises(ValidationFailed):
        from_payload("ServiceActivated", {"service_id": 7, "at": "2026-10-29T09:10:00Z"})


def test_a_time_that_is_not_utc_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        ServiceActivated("svc-ucr-west", datetime(2026, 10, 29, 9, 10))
