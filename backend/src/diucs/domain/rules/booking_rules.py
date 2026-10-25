"""Booking rules around the state machine (D14).

Rules: docs/spec/domain-rules.md section 3.2 (timers, one open request, references, reply matching).
Decisions: DEC-016 (references are matched exactly, never by prefix), DEC-021 (statusReason).
Pure: no I/O. Times are passed in as timezone-aware UTC datetimes.
"""

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from diucs.domain.codes import BookingStatus
from diucs.domain.errors import Conflict

BOOKING_REPLY_WINDOW = timedelta(minutes=10)
PHONE_PROMPT_AFTER = timedelta(minutes=5)
REFERENCE_ATTEMPTS = 50


@dataclass(frozen=True, slots=True)
class OpenBookingRef:
    booking_id: str
    reference: str
    service_id: str


@dataclass(frozen=True, slots=True)
class AskWhichReference:
    references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NoOpenBooking:
    pass


def booking_reply_by(requested_at: datetime) -> datetime:
    raise NotImplementedError


def phone_prompt_at(requested_at: datetime) -> datetime:
    raise NotImplementedError


def can_request(open_statuses_for_service: Iterable[BookingStatus]) -> bool:
    raise NotImplementedError


def new_reference(rng: random.Random, taken: set[str]) -> str:
    raise NotImplementedError


def match_reply(
    open: Sequence[OpenBookingRef], reference: str | None
) -> OpenBookingRef | AskWhichReference | NoOpenBooking:
    raise NotImplementedError


__all__ = [
    "BOOKING_REPLY_WINDOW",
    "PHONE_PROMPT_AFTER",
    "REFERENCE_ATTEMPTS",
    "AskWhichReference",
    "Conflict",
    "NoOpenBooking",
    "OpenBookingRef",
    "booking_reply_by",
    "can_request",
    "match_reply",
    "new_reference",
    "phone_prompt_at",
]
