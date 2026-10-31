"""Booking replies, decline reasons, echoes and cancellations: the rules around RespondToBooking
(U18) and CancelBooking (U20).

Rules: docs/spec/domain-rules.md section 3.2 (replies), and the state machine of booking_state
(D13).
Pure: no I/O and no clock. Silence is never acceptance: only a requested booking moves on a reply.
"""

from collections.abc import Iterable
from typing import Final

from diucs.domain.codes import BookingStatus, Role
from diucs.domain.errors import Conflict, InvalidTransition, ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.rules.booking_state import transition

CONFIRM: Final = "confirm"
DECLINE: Final = "decline"
DECISIONS: Final = frozenset({CONFIRM, DECLINE})

_DECISION_TARGET: Final[dict[str, BookingStatus]] = {
    CONFIRM: BookingStatus.CONFIRMED,
    DECLINE: BookingStatus.DECLINED,
}
_ECHO: Final[dict[BookingStatus, MessageId]] = {
    BookingStatus.CONFIRMED: MessageId.B4,
    BookingStatus.DECLINED: MessageId.B5,
}
_CANCEL_TARGET: Final[dict[BookingStatus, BookingStatus]] = {
    BookingStatus.REQUESTED: BookingStatus.CANCELLED_BEFORE,
    BookingStatus.CONFIRMED: BookingStatus.CANCELLED_AFTER,
}
_RESPONDERS: Final = frozenset({Role.REPORTER, Role.ANONYMOUS_LINK})
_CANCELLERS: Final = frozenset({Role.ADVISOR, Role.CLINICAL})


def plan_response(current: BookingStatus, decision: str) -> BookingStatus | None:
    """The state a reply moves a booking to, or None when the booking is already final.

    A reply to an expired booking is not an error: it changes nothing and is reported as already
    final (U18). Every other state that is not requested raises InvalidTransition, and so does any
    decision that is not confirm or decline.
    """
    if decision not in DECISIONS:
        raise ValidationFailed("decision", "must be confirm or decline")
    if current is BookingStatus.EXPIRED:
        return None
    return transition(current, _DECISION_TARGET[decision])


def may_set_decline_reason(current: BookingStatus, *, reason_set: bool) -> None:
    """A decline reason can be given after the decline, once (U18). A booking that is not declined
    has no decline reason to give, and a second reason is a conflict."""
    if current is not BookingStatus.DECLINED:
        raise InvalidTransition("a decline reason is only set on a declined booking")
    if reason_set:
        raise Conflict("this declined booking already has a reason")


def echo_message(status: BookingStatus) -> MessageId:
    """The echo to the service for a booking that was answered: B4 for a confirmation and B5 for a
    decline (D16). Any other state has no echo."""
    if status not in _ECHO:
        raise ValidationFailed("status", "only a confirmation or a decline is echoed")
    return _ECHO[status]


def responder_may_act(role: Role, service_ids: Iterable[str], service_id: str) -> bool:
    """A reporter or an anonymous link may answer for their own service, and no other (U18)."""
    return role in _RESPONDERS and service_id in set(service_ids)


def cancel_target(current: BookingStatus) -> BookingStatus:
    """The state a cancellation moves a booking to: cancelled-before from requested, and
    cancelled-after from confirmed (U20). Any other state is an invalid transition."""
    if current not in _CANCEL_TARGET:
        raise InvalidTransition(f"booking cannot be cancelled from {current.value}")
    return transition(current, _CANCEL_TARGET[current])


def advisor_may_cancel(role: Role) -> bool:
    """Only an advisor or a clinician cancels a booking (U20)."""
    return role in _CANCELLERS
