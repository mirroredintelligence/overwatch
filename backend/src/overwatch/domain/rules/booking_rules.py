"""Booking rules around the state machine (D14).

Rules: docs/spec/domain-rules.md section 3.2 (timers, one open request, references, reply matching).
Decisions: DEC-016 (references are matched exactly, never by prefix), DEC-021 (statusReason).
Pure: no I/O. Times are passed in as timezone-aware UTC datetimes; timers are instant offsets,
so they are unaffected by the London clock change (lesson L4).

The two timers are tenant policy (TEN-064): each takes a `TenantPolicy` as its last argument,
defaulting to `DEFAULT_POLICY`, and reads `booking_reply_window` and `booking_phone_prompt_after`.
The module constants are aliases of the default policy, kept so existing importers keep working.
The reference format and the other functions read no policy.
"""

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.domain.codes import BookingStatus
from diucs.domain.errors import Conflict
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy, require_policy
from diucs.domain.rules.booking_state import is_open

# Aliases of the default policy (TEN-064): the numbers are defined once, in tenant_policy.py.
BOOKING_REPLY_WINDOW: Final = DEFAULT_POLICY.booking_reply_window
PHONE_PROMPT_AFTER: Final = DEFAULT_POLICY.booking_phone_prompt_after
REFERENCE_ATTEMPTS = 50

_REFERENCE_LOWEST = 1000
_REFERENCE_HIGHEST = 9999


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


def booking_reply_by(requested_at: datetime, policy: TenantPolicy = DEFAULT_POLICY) -> datetime:
    policy = require_policy(policy)  # reads booking_reply_window
    return requested_at + policy.booking_reply_window


def phone_prompt_at(requested_at: datetime, policy: TenantPolicy = DEFAULT_POLICY) -> datetime:
    policy = require_policy(policy)  # reads booking_phone_prompt_after
    return requested_at + policy.booking_phone_prompt_after


def can_request(open_statuses_for_service: Iterable[BookingStatus]) -> bool:
    """A service takes a new request only when none of its bookings is still requested."""
    return not any(is_open(status) for status in open_statuses_for_service)


def new_reference(rng: random.Random, taken: set[str]) -> str:
    """A 4-digit reference without a leading zero, not in `taken` (DEC-007)."""
    for _ in range(REFERENCE_ATTEMPTS):
        candidate = str(rng.randint(_REFERENCE_LOWEST, _REFERENCE_HIGHEST))
        if candidate not in taken:
            return candidate
    raise Conflict("no free booking reference after repeated collisions")


def match_reply(
    open: Sequence[OpenBookingRef], reference: str | None
) -> OpenBookingRef | AskWhichReference | NoOpenBooking:
    """Pick the open booking a text reply is about.

    A reference must match exactly (DEC-016): a prefix or a longer number never matches.
    Without a reference, one open booking is used and several make the reply ask which one.
    """
    if reference is not None:
        for booking in open:
            if booking.reference == reference:
                return booking
        return NoOpenBooking()
    if not open:
        return NoOpenBooking()
    if len(open) == 1:
        return open[0]
    return AskWhichReference(tuple(sorted(booking.reference for booking in open)))
