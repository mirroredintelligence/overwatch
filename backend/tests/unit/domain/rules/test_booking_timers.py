"""Tests for the booking timers' effects (U19): the phone prompt at +5 minutes and the expiry at
+10 minutes act only on a requested booking. Sample values only.
"""

import pytest

from diucs.domain.codes import BookingStatus
from diucs.domain.rules.booking_timers import TimerEffect, expiry_effect, phone_prompt_effect


@pytest.mark.parametrize("status", [BookingStatus.REQUESTED])
def test_the_phone_prompt_is_due_only_while_the_booking_is_requested(status: BookingStatus) -> None:
    assert phone_prompt_effect(status) is TimerEffect.PHONE_PROMPT


@pytest.mark.parametrize("status", [BookingStatus.REQUESTED])
def test_the_expiry_acts_only_while_the_booking_is_requested(status: BookingStatus) -> None:
    assert expiry_effect(status) is TimerEffect.EXPIRE


@pytest.mark.parametrize(
    "status",
    [
        BookingStatus.CONFIRMED,
        BookingStatus.DECLINED,
        BookingStatus.EXPIRED,
        BookingStatus.CANCELLED_BEFORE,
        BookingStatus.CANCELLED_AFTER,
        BookingStatus.WITHDRAWN,
        BookingStatus.NOT_REACHED,
        BookingStatus.COMPLETED,
    ],
)
def test_a_timer_does_nothing_once_the_booking_is_final(status: BookingStatus) -> None:
    assert phone_prompt_effect(status) is TimerEffect.NONE
    assert expiry_effect(status) is TimerEffect.NONE
