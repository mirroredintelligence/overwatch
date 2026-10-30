"""Tests for the pure rule that reads a booking reply sent by text (U22).

A CONFIRMED or DECLINE is about the phone's open booking, matched by reference when one is given
(DEC-016: exact match). A digit 1, 2 or 3 sent within ten minutes of a decline without a reason sets
the reason; any other digit is left to the capacity path. Sample values only.
"""

from datetime import UTC, datetime, timedelta

import pytest

from diucs.domain.codes import BookingStatus, DeclineReason
from diucs.domain.model.booking import Booking
from diucs.domain.rules.booking_reply_text import (
    DECLINE_REASON_WINDOW,
    AskReference,
    BookingTextPlan,
    Expired,
    NothingWaiting,
    RespondTo,
    SetReason,
    plan_booking_text,
)
from diucs.domain.rules.booking_rules import OpenBookingRef
from diucs.domain.rules.reply_parser import (
    BookingConfirm,
    BookingDecline,
    Confirm,
    Number,
    ParsedReply,
    Unrecognised,
)

NOW = datetime(2026, 10, 29, 14, 30, tzinfo=UTC)
SERVICE = "ucr-west"
DEFAULT = SERVICE


def booking(
    booking_id: str,
    reference: str,
    status: BookingStatus,
    *,
    responded_at: datetime | None = None,
    reason: str | None = None,
) -> Booking:
    return Booking(
        id=booking_id,
        reference=reference,
        service_id=SERVICE,
        case_id="case-1001",
        requester_id="advisor-1",
        status=status,
        requested_at=NOW - timedelta(minutes=5),
        reply_by=NOW + timedelta(minutes=10),
        responded_at=responded_at,
        reason=reason,
    )


def open_ref(booking_id: str, reference: str) -> OpenBookingRef:
    return OpenBookingRef(booking_id=booking_id, reference=reference, service_id=SERVICE)


def plan(
    parsed: tuple[ParsedReply, ...],
    open_refs: list[OpenBookingRef],
    latest: list[Booking],
    now: datetime = NOW,
) -> BookingTextPlan | None:
    return plan_booking_text(parsed, open_refs, latest, now, default_service_id=DEFAULT)


def test_the_decline_window_is_ten_minutes() -> None:
    assert timedelta(minutes=10) == DECLINE_REASON_WINDOW


def test_a_bare_confirmed_with_one_open_booking_responds_to_it() -> None:
    result = plan(
        (BookingConfirm(reference=None),),
        [open_ref("bk-1", "4821")],
        [booking("bk-1", "4821", BookingStatus.REQUESTED)],
    )
    assert result == RespondTo(booking_id="bk-1", service_id=SERVICE, decision="confirm")


def test_a_confirmed_with_a_reference_responds_to_the_booking_with_that_reference() -> None:
    result = plan(
        (BookingConfirm(reference="4821"),),
        [open_ref("bk-1", "4821"), open_ref("bk-2", "5555")],
        [],
    )
    assert result == RespondTo(booking_id="bk-1", service_id=SERVICE, decision="confirm")


def test_a_decline_with_one_open_booking_declines_it() -> None:
    result = plan((BookingDecline(reference=None),), [open_ref("bk-1", "4821")], [])
    assert result == RespondTo(booking_id="bk-1", service_id=SERVICE, decision="decline")


def test_a_bare_confirmed_with_two_open_bookings_asks_which_reference() -> None:
    result = plan(
        (BookingConfirm(reference=None),),
        [open_ref("bk-2", "5555"), open_ref("bk-1", "4821")],
        [],
    )
    assert result == AskReference(references=("4821", "5555"))


def test_a_reference_that_matches_no_open_booking_is_nothing_waiting_not_a_prefix_match() -> None:
    result = plan((BookingConfirm(reference="482"),), [open_ref("bk-1", "4821")], [])
    assert result == NothingWaiting(service_id=DEFAULT)


def test_a_bare_confirmed_after_expiry_is_reported_as_expired() -> None:
    latest = [booking("bk-1", "4821", BookingStatus.EXPIRED, responded_at=NOW)]
    result = plan((BookingConfirm(reference=None),), [], latest)
    assert result == Expired(service_id=SERVICE)


def test_a_confirmed_with_the_reference_of_an_expired_booking_is_reported_as_expired() -> None:
    latest = [booking("bk-1", "4821", BookingStatus.EXPIRED, responded_at=NOW)]
    result = plan((BookingConfirm(reference="4821"),), [], latest)
    assert result == Expired(service_id=SERVICE)


def test_a_bare_confirmed_with_no_booking_at_all_is_nothing_waiting() -> None:
    result = plan((BookingConfirm(reference=None),), [], [])
    assert result == NothingWaiting(service_id=DEFAULT)


@pytest.mark.parametrize(
    ("digit", "reason"),
    [(1, DeclineReason.FULL), (2, DeclineReason.OUTSIDE_CRITERIA), (3, DeclineReason.OTHER)],
)
def test_a_digit_a_minute_after_a_decline_sets_its_reason(
    digit: int, reason: DeclineReason
) -> None:
    declined = booking(
        "bk-1", "4821", BookingStatus.DECLINED, responded_at=NOW - timedelta(minutes=1)
    )
    result = plan((Number(value=digit),), [], [declined])
    assert result == SetReason(booking_id="bk-1", service_id=SERVICE, reason=reason)


def test_a_digit_exactly_ten_minutes_after_a_decline_still_sets_its_reason() -> None:
    declined = booking(
        "bk-1", "4821", BookingStatus.DECLINED, responded_at=NOW - DECLINE_REASON_WINDOW
    )
    result = plan((Number(value=2),), [], [declined])
    assert result == SetReason(
        booking_id="bk-1", service_id=SERVICE, reason=DeclineReason.OUTSIDE_CRITERIA
    )


def test_a_digit_after_the_window_is_left_to_the_capacity_path() -> None:
    declined = booking(
        "bk-1", "4821", BookingStatus.DECLINED, responded_at=NOW - timedelta(minutes=15)
    )
    assert plan((Number(value=2),), [], [declined]) is None


def test_a_digit_just_past_the_window_is_left_to_the_capacity_path() -> None:
    declined = booking(
        "bk-1",
        "4821",
        BookingStatus.DECLINED,
        responded_at=NOW - DECLINE_REASON_WINDOW - timedelta(seconds=1),
    )
    assert plan((Number(value=2),), [], [declined]) is None


def test_a_digit_after_a_decline_that_already_has_a_reason_is_left_to_the_capacity_path() -> None:
    declined = booking(
        "bk-1",
        "4821",
        BookingStatus.DECLINED,
        responded_at=NOW - timedelta(minutes=1),
        reason=DeclineReason.FULL.value,
    )
    assert plan((Number(value=1),), [], [declined]) is None


@pytest.mark.parametrize("digit", [0, 4, 9])
def test_a_digit_outside_one_to_three_is_left_to_the_capacity_path(digit: int) -> None:
    declined = booking(
        "bk-1", "4821", BookingStatus.DECLINED, responded_at=NOW - timedelta(minutes=1)
    )
    assert plan((Number(value=digit),), [], [declined]) is None


def test_a_digit_with_no_decline_to_follow_is_left_to_the_capacity_path() -> None:
    confirmed = booking("bk-1", "4821", BookingStatus.CONFIRMED, responded_at=NOW)
    assert plan((Number(value=2),), [], [confirmed]) is None


@pytest.mark.parametrize("parsed", [(Confirm(),), (Unrecognised(text="hello"),)])
def test_a_text_that_is_not_a_booking_word_is_not_a_booking_reply(
    parsed: tuple[ParsedReply, ...],
) -> None:
    assert plan(parsed, [open_ref("bk-1", "4821")], []) is None
