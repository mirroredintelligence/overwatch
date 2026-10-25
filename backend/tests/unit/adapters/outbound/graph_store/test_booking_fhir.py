"""Booking to FHIR Task mapping, pure (P02). Rules: fhir-data-model.md 'Booking', D13 to_fhir."""

from datetime import UTC, datetime

import pytest

from diucs.adapters.outbound.graph_store.booking_repository import (
    booking_from_fhir,
    booking_to_fhir,
)
from diucs.domain.codes import BookingStatus
from diucs.domain.model.booking import Booking

REQUESTED_AT = datetime(2026, 10, 25, 13, 16, tzinfo=UTC)
REPLY_BY = datetime(2026, 10, 25, 13, 26, tzinfo=UTC)
RESPONDED_AT = datetime(2026, 10, 25, 13, 19, tzinfo=UTC)


def _booking_in(status: BookingStatus) -> Booking:
    """A booking in the given status, carrying the fields that status has."""
    if status is BookingStatus.REQUESTED:
        responded_at = None
        reason = None
    else:
        responded_at = RESPONDED_AT
        reason = "full" if status is BookingStatus.DECLINED else None
    confirmed_at = RESPONDED_AT if status in (
        BookingStatus.CONFIRMED,
        BookingStatus.CANCELLED_AFTER,
    ) else None
    return Booking(
        id="bk-4821",
        reference="4821",
        service_id="svc-ucr-west",
        case_id="case-1",
        requester_id="prac-advisor-1",
        status=status,
        requested_at=REQUESTED_AT,
        reply_by=REPLY_BY,
        confirmed_at=confirmed_at,
        responded_at=responded_at,
        reason=reason,
    )


@pytest.mark.parametrize("status", list(BookingStatus), ids=lambda s: s.value)
def test_every_status_round_trips_through_the_fhir_task(status: BookingStatus) -> None:
    booking = _booking_in(status)

    assert booking_from_fhir(booking_to_fhir(booking)) == booking


def test_the_task_carries_the_reference_owner_focus_and_requester() -> None:
    resource = booking_to_fhir(_booking_in(BookingStatus.REQUESTED))

    assert resource["resourceType"] == "Task"
    assert resource["id"] == "bk-4821"
    assert resource["intent"] == "order"
    assert resource["status"] == "requested"
    assert resource["businessStatus"]["coding"][0]["code"] == "requested"
    assert resource["identifier"] == [
        {"system": "https://diucs.example/booking-reference", "value": "4821"}
    ]
    assert resource["owner"] == {"reference": "HealthcareService/svc-ucr-west"}
    assert resource["focus"] == {"reference": "ServiceRequest/case-1"}
    assert resource["requester"] == {"reference": "Practitioner/prac-advisor-1"}
    assert "for" not in resource


def test_a_confirmed_task_maps_to_fhir_accepted_with_confirmed_business_status() -> None:
    resource = booking_to_fhir(_booking_in(BookingStatus.CONFIRMED))

    assert resource["status"] == "accepted"
    assert resource["businessStatus"]["coding"][0]["code"] == "confirmed"
    assert "statusReason" not in resource
