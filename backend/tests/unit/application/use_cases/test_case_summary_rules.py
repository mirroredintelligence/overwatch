"""The pure rules of the case summary (H-322, W8A K6): the booking line and the data age line.

The summary the advisor copies into the referral says where the patient is going, whether it is
booked and how old the figure was. The read, the destination check and the audit are in
tests/integration/application/test_case_summary.py. Sample values only.
"""

from datetime import UTC, datetime, timedelta

import pytest

from diucs.application.use_cases.case_summary import booking_line, data_age_line
from diucs.domain.codes import BookingStatus
from diucs.domain.model.booking import Booking

REQUESTED = datetime(
    2026, 10, 29, 14, 5, tzinfo=UTC
)  # 14:05 GMT in the London zone in late October


def booking(status: BookingStatus, **changes: object) -> Booking:
    fields: dict[str, object] = {
        "id": "bk-1",
        "reference": "4821",
        "service_id": "svc-1",
        "case_id": "case-1",
        "requester_id": "prac-1",
        "status": status,
        "requested_at": REQUESTED,
        "reply_by": REQUESTED + timedelta(minutes=30),
    }
    fields.update(changes)
    return Booking(**fields)  # type: ignore[arg-type]


def test_a_requested_booking_says_it_is_waiting_for_the_service() -> None:
    assert booking_line(booking(BookingStatus.REQUESTED)) == (
        "Requested 14:05, waiting for the service to confirm"
    )


def test_a_confirmed_booking_says_when_the_service_confirmed() -> None:
    confirmed = booking(BookingStatus.CONFIRMED, confirmed_at=REQUESTED + timedelta(minutes=12))

    assert booking_line(confirmed) == "Confirmed 14:17"


def test_times_are_in_the_london_zone_in_summer_time() -> None:
    summer = datetime(2026, 7, 1, 13, 0, tzinfo=UTC)

    assert booking_line(booking(BookingStatus.REQUESTED, requested_at=summer)) == (
        "Requested 14:00, waiting for the service to confirm"
    )


@pytest.mark.parametrize(
    "status",
    [
        BookingStatus.DECLINED,
        BookingStatus.EXPIRED,
        BookingStatus.CANCELLED_BEFORE,
        BookingStatus.CANCELLED_AFTER,
        BookingStatus.WITHDRAWN,
        BookingStatus.NOT_REACHED,
    ],
)
def test_a_booking_that_did_not_hold_is_not_a_booked_line(status: BookingStatus) -> None:
    assert booking_line(booking(status)) is None


def test_a_completed_booking_says_it_was_confirmed() -> None:
    done = booking(BookingStatus.COMPLETED, confirmed_at=REQUESTED + timedelta(minutes=12))

    assert booking_line(done) == "Confirmed 14:17"


def test_a_confirmed_booking_with_no_confirmation_time_says_confirmed_and_no_time() -> None:
    assert booking_line(booking(BookingStatus.CONFIRMED)) == "Confirmed"


def test_the_data_age_line_says_how_old_the_figure_was() -> None:
    now = datetime(2026, 10, 29, 14, 14, tzinfo=UTC)

    assert data_age_line(now - timedelta(minutes=9), now) == "9 min ago"
    assert data_age_line(now - timedelta(hours=4, minutes=10), now) == "4 hrs 10 min ago"


def test_no_figure_is_said_plainly_and_never_as_a_time() -> None:
    assert data_age_line(None, datetime(2026, 10, 29, 14, 14, tzinfo=UTC)) == "No figure reported"
