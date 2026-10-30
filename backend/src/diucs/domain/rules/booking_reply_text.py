"""Reading a booking reply sent by text (U22). Stub: the red commit.

Rules: docs/spec/domain-rules.md 2.1 and 3.2. Pure: no I/O and no clock.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from diucs.domain.codes import DeclineReason
from diucs.domain.model.booking import Booking
from diucs.domain.rules.booking_rules import OpenBookingRef
from diucs.domain.rules.reply_parser import ParsedReply

DECLINE_REASON_WINDOW: Final = timedelta(minutes=10)


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
    raise NotImplementedError
