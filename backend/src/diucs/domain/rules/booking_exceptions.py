"""Rules for the exceptions after a confirmed booking: withdrawal and not-reached (U21).

Rules: docs/spec/domain-rules.md section 3.2 (transitions) and the reasons of section 3.2.
Pure: no I/O and no clock. Reasons are checked by enum type, never by value: a member of another
enum with the same value is refused (lesson L3).
"""

from typing import Final

from diucs.domain.codes import BookingStatus, NotReachedReason, WithdrawReason
from diucs.domain.errors import InvalidTransition, ValidationFailed
from diucs.domain.rules.booking_state import transition

_FROM: Final = BookingStatus.CONFIRMED


def withdraw_target(current: BookingStatus) -> BookingStatus:
    """The state a withdrawal moves a booking to: withdrawn, and only from confirmed (U21)."""
    if current is not _FROM:
        raise InvalidTransition(f"booking cannot be withdrawn from {current.value}")
    return transition(current, BookingStatus.WITHDRAWN)


def not_reached_target(current: BookingStatus) -> BookingStatus:
    """The state a not-reached report moves a booking to: not-reached, and only from confirmed."""
    if current is not _FROM:
        raise InvalidTransition(f"booking cannot be reported not reached from {current.value}")
    return transition(current, BookingStatus.NOT_REACHED)


def checked_withdraw_reason(reason: WithdrawReason) -> WithdrawReason:
    if type(reason) is not WithdrawReason:
        raise ValidationFailed("reason", "is required: a withdraw reason from the rule book")
    return reason


def checked_not_reached_reason(reason: NotReachedReason) -> NotReachedReason:
    if type(reason) is not NotReachedReason:
        raise ValidationFailed("reason", "is required: a not-reached reason from the rule book")
    return reason
