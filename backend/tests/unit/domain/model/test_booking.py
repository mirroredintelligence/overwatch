"""Booking record and its status moves (P02). Rules: domain-rules.md section 3.2, D13."""

from datetime import UTC, datetime, timedelta

import pytest

from diucs.domain.codes import BookingStatus
from diucs.domain.errors import InvalidTransition, ValidationFailed
from diucs.domain.model.booking import Booking

REQUESTED_AT = datetime(2026, 10, 25, 13, 16, tzinfo=UTC)
REPLY_BY = REQUESTED_AT + timedelta(minutes=10)
CONFIRMED_AT = datetime(2026, 10, 25, 13, 19, tzinfo=UTC)


def _requested() -> Booking:
    return Booking(
        id="bk-4821",
        reference="4821",
        service_id="svc-ucr-west",
        case_id="case-1",
        requester_id="prac-advisor-1",
        status=BookingStatus.REQUESTED,
        requested_at=REQUESTED_AT,
        reply_by=REPLY_BY,
    )


def test_confirming_sets_status_confirmed_at_and_responded_at() -> None:
    booking = _requested().with_status(BookingStatus.CONFIRMED, CONFIRMED_AT)

    assert booking.status is BookingStatus.CONFIRMED
    assert booking.confirmed_at == CONFIRMED_AT
    assert booking.responded_at == CONFIRMED_AT


def test_declining_sets_responded_at_but_not_confirmed_at() -> None:
    booking = _requested().with_status(BookingStatus.DECLINED, CONFIRMED_AT, reason="full")

    assert booking.status is BookingStatus.DECLINED
    assert booking.responded_at == CONFIRMED_AT
    assert booking.confirmed_at is None
    assert booking.reason == "full"


def test_a_requested_booking_cannot_jump_to_completed() -> None:
    with pytest.raises(InvalidTransition):
        _requested().with_status(BookingStatus.COMPLETED, CONFIRMED_AT)


def test_a_terminal_booking_cannot_move_again() -> None:
    declined = _requested().with_status(BookingStatus.DECLINED, CONFIRMED_AT)

    with pytest.raises(InvalidTransition):
        declined.with_status(BookingStatus.CONFIRMED, CONFIRMED_AT)


def test_a_naive_datetime_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        Booking(
            id="bk-1",
            reference="1234",
            service_id="svc-ucr-west",
            case_id="case-1",
            requester_id="prac-advisor-1",
            status=BookingStatus.REQUESTED,
            requested_at=datetime(2026, 10, 25, 13, 16),
            reply_by=REPLY_BY,
        )
