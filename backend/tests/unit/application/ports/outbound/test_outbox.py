"""Unit tests for the outbox port (P06): the message an event becomes. No database."""

from datetime import UTC, datetime

from diucs.application.ports.outbound.outbox import MAX_ATTEMPTS, outbox_message_for
from diucs.domain.codes import ReportSource
from diucs.domain.events import BookingRequested, CapacityReported

NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)


def test_a_capacity_event_becomes_a_pending_message_on_capacity_events_for_its_service() -> None:
    event = CapacityReported(
        service_id="svc-ucr-west",
        report_id="rep-1",
        value=8,
        source=ReportSource.TEXT,
        at=NOW,
    )

    message = outbox_message_for(event, id="out-1", now=NOW)

    assert message.id == "out-1"
    assert message.topic == "capacity.events"
    assert message.event_type == "CapacityReported"
    assert message.session_id == "svc-ucr-west"
    assert message.payload == event.to_payload()
    assert message.status == "pending"
    assert message.attempts == 0
    assert message.created_at == NOW


def test_an_event_that_is_not_per_service_has_no_session_id() -> None:
    event = BookingRequested(
        booking_id="bk-1",
        service_id="svc-ucr-west",
        reference="4821",
        at=NOW,
    )

    message = outbox_message_for(event, id="out-2", now=NOW)

    assert message.topic == "booking.events"
    assert message.session_id is None


def test_ten_attempts_is_the_dead_letter_limit() -> None:
    assert MAX_ATTEMPTS == 10
