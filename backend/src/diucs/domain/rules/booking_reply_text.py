"""Reading a booking reply sent by text (U22).

Rules: docs/spec/domain-rules.md 2.1 and 3.2. Pure: no I/O and no clock.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from diucs.domain.codes import BookingStatus, DeclineReason
from diucs.domain.model.booking import Booking
from diucs.domain.rules.booking_rules import (
    AskWhichReference,
    NoOpenBooking,
    OpenBookingRef,
    match_reply,
)
from diucs.domain.rules.reply_parser import BookingConfirm, BookingDecline, Number, ParsedReply

# [ASSUMED] A digit that sets the reason of a decline must come within ten minutes of it (U22).
DECLINE_REASON_WINDOW: Final = timedelta(minutes=10)
_DECLINE_REASON_BY_DIGIT: Final = {
    1: DeclineReason.FULL,
    2: DeclineReason.OUTSIDE_CRITERIA,
    3: DeclineReason.OTHER,
}


@dataclass(frozen=True, slots=True)
class RespondTo:
    booking_id: str
    service_id: str
    decision: str


@dataclass(frozen=True, slots=True)
class AskReference:
    references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Expired:
    service_id: str | None


@dataclass(frozen=True, slots=True)
class NothingWaiting:
    service_id: str | None


@dataclass(frozen=True, slots=True)
class SetReason:
    booking_id: str
    service_id: str
    reason: DeclineReason


BookingTextPlan = RespondTo | AskReference | Expired | NothingWaiting | SetReason


def plan_booking_text(
    parsed: Sequence[ParsedReply],
    open_refs: Sequence[OpenBookingRef],
    latest: Sequence[Booking],
    now: datetime,
    *,
    default_service_id: str,
) -> BookingTextPlan | None:
    """What a text from a phone does with its bookings, or None when it is not a booking reply.

    A confirmed or declined word is about one open booking: the one its reference names (exact
    match), the only open one when no reference is given, or none, which asks which when there are
    several. An expired booking is reported as expired, and nothing is booked. A digit 1 to 3 sets
    the reason of the phone's latest decline, if it came within the window and has no reason yet;
    any other text is left to the capacity path (None).
    """
    booking_words = [item for item in parsed if isinstance(item, BookingConfirm | BookingDecline)]
    if booking_words:
        word = booking_words[0]
        decision = "confirm" if isinstance(word, BookingConfirm) else "decline"
        return _respond(word.reference, decision, open_refs, latest, default_service_id)
    if len(parsed) == 1 and isinstance(parsed[0], Number):
        return _set_reason(parsed[0].value, latest, now)
    return None


def _respond(
    reference: str | None,
    decision: str,
    open_refs: Sequence[OpenBookingRef],
    latest: Sequence[Booking],
    default_service_id: str,
) -> BookingTextPlan:
    match = match_reply(open_refs, reference)
    if isinstance(match, OpenBookingRef):
        return RespondTo(match.booking_id, match.service_id, decision)
    if isinstance(match, AskWhichReference):
        return AskReference(match.references)
    assert isinstance(match, NoOpenBooking)
    if _expired(latest, reference):
        return Expired(service_id=_service_of(latest, reference, default_service_id))
    return NothingWaiting(service_id=default_service_id)


def _expired(latest: Sequence[Booking], reference: str | None) -> bool:
    for booking in latest:
        if reference is not None and booking.reference != reference:
            continue
        if booking.status is BookingStatus.EXPIRED:
            return True
    return False


def _service_of(latest: Sequence[Booking], reference: str | None, default: str) -> str:
    for booking in latest:
        if reference is None or booking.reference == reference:
            return booking.service_id
    return default


def _set_reason(digit: int, latest: Sequence[Booking], now: datetime) -> SetReason | None:
    reason = _DECLINE_REASON_BY_DIGIT.get(digit)
    if reason is None:
        return None
    for booking in latest:
        if booking.status is not BookingStatus.DECLINED or booking.reason is not None:
            continue
        if booking.responded_at is None:
            continue
        if now - booking.responded_at > DECLINE_REASON_WINDOW:
            continue
        return SetReason(booking.id, booking.service_id, reason)
    return None
