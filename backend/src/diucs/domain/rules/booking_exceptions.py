"""Rules for the exceptions after a confirmed booking: withdrawal and not-reached (U21).

Rules: docs/spec/domain-rules.md section 3.2 (transitions) and the reasons of section 3.2.
Pure: no I/O and no clock.
"""

from typing import Final

from diucs.domain.codes import BookingStatus, NotReachedReason, WithdrawReason

WITHDRAW_REASONS: Final = frozenset(WithdrawReason)


def withdraw_target(current: BookingStatus) -> BookingStatus:
    raise NotImplementedError


def not_reached_target(current: BookingStatus) -> BookingStatus:
    raise NotImplementedError


def checked_withdraw_reason(reason: WithdrawReason) -> WithdrawReason:
    raise NotImplementedError


def checked_not_reached_reason(reason: NotReachedReason) -> NotReachedReason:
    raise NotImplementedError
