"""The effects of the two booking timers (U19): the phone prompt at +5 minutes and the expiry at
+10 minutes (D14, domain-rules section 3.2).

Pure: no I/O and no clock. Only a requested booking is acted on. A timer that finds the booking
answered, declined or otherwise final does nothing, and so silence is never acceptance.
"""

from enum import StrEnum

from diucs.domain.codes import BookingStatus
from diucs.domain.rules.booking_state import is_open


class TimerEffect(StrEnum):
    NONE = "none"
    PHONE_PROMPT = "phone-prompt"
    EXPIRE = "expire"


def phone_prompt_effect(status: BookingStatus) -> TimerEffect:
    """The advisor is prompted to phone only while the request is still waiting."""
    return TimerEffect.PHONE_PROMPT if is_open(status) else TimerEffect.NONE


def expiry_effect(status: BookingStatus) -> TimerEffect:
    """The request expires only while it is still waiting; a final booking is left as it is."""
    return TimerEffect.EXPIRE if is_open(status) else TimerEffect.NONE
