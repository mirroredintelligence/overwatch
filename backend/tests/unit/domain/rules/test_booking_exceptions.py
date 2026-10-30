"""Tests for the pure rules of the exceptions after a confirmed booking (U21): withdrawal and
not-reached. Both start only from confirmed, and their reasons are the enums of the rule book, with
a member of another enum refused even when its value matches (lesson L3).
"""

import pytest

from diucs.domain.codes import BookingStatus, NotReachedReason, WithdrawReason
from diucs.domain.errors import InvalidTransition, ValidationFailed
from diucs.domain.rules.booking_exceptions import (
    checked_not_reached_reason,
    checked_withdraw_reason,
    not_reached_target,
    withdraw_target,
)


def test_a_confirmed_booking_is_withdrawn() -> None:
    assert withdraw_target(BookingStatus.CONFIRMED) is BookingStatus.WITHDRAWN


def test_a_confirmed_booking_is_reported_not_reached() -> None:
    assert not_reached_target(BookingStatus.CONFIRMED) is BookingStatus.NOT_REACHED


@pytest.mark.parametrize(
    "status",
    [
        BookingStatus.REQUESTED,
        BookingStatus.DECLINED,
        BookingStatus.EXPIRED,
        BookingStatus.CANCELLED_BEFORE,
        BookingStatus.CANCELLED_AFTER,
        BookingStatus.WITHDRAWN,
        BookingStatus.NOT_REACHED,
        BookingStatus.COMPLETED,
    ],
)
def test_only_a_confirmed_booking_can_be_withdrawn_or_reported_not_reached(
    status: BookingStatus,
) -> None:
    with pytest.raises(InvalidTransition):
        withdraw_target(status)
    with pytest.raises(InvalidTransition):
        not_reached_target(status)


@pytest.mark.parametrize("reason", list(WithdrawReason))
def test_every_withdraw_reason_of_the_rule_book_is_accepted(reason: WithdrawReason) -> None:
    assert checked_withdraw_reason(reason) is reason


@pytest.mark.parametrize("value", ["staffing", "now-full", "other"])
def test_a_bare_string_is_not_a_withdraw_reason(value: str) -> None:
    with pytest.raises(ValidationFailed):
        checked_withdraw_reason(value)  # type: ignore[arg-type]


def test_a_not_reached_reason_is_not_taken_for_a_withdraw_reason_with_the_same_value() -> None:
    # 'other' is a member of both enums: the enum decides, never the value (lesson L3).
    assert checked_not_reached_reason(NotReachedReason.OTHER) is NotReachedReason.OTHER
    with pytest.raises(ValidationFailed):
        checked_withdraw_reason(NotReachedReason.OTHER)  # type: ignore[arg-type]


@pytest.mark.parametrize("reason", list(NotReachedReason))
def test_every_not_reached_reason_of_the_rule_book_is_accepted(reason: NotReachedReason) -> None:
    assert checked_not_reached_reason(reason) is reason


@pytest.mark.parametrize("value", ["no-answer", "not-at-address"])
def test_a_bare_string_is_not_a_not_reached_reason(value: str) -> None:
    with pytest.raises(ValidationFailed):
        checked_not_reached_reason(value)  # type: ignore[arg-type]
