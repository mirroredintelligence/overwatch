"""Rules of the visit offer (DEC-1306 to DEC-1309). Pure: no I/O, no logging.

- what state an offer is really in, given the booking behind it and the time (an offer is never
  rewritten by a timer; a read works the state out, so nothing can be late);
- when a visit is wanted by, and which visit is next (the order is the time a visit is wanted by and
  nothing else: no practitioner, area or history is looked at, so nothing here can rank people);
- the checks of the details an advisor gives and of an estimated arrival;
- how long a shift status stands.

No function puts a value of the address, contact or postcode into an error message.
"""

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Final

from overwatch.domain.codes import BookingStatus, Urgency
from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.visit import (
    ACTIVE_STATES,
    ADDRESS_MAX,
    CONTACT_MAX,
    ETA_MAX_MINUTES,
    ShiftStatus,
    VisitOffer,
    VisitSettings,
    VisitState,
)

WITHIN_2_HRS: Final = timedelta(hours=2)
VISIT_LAPSE: Final = timedelta(hours=24)
"""[ASSUMED] A visit that is still open this long after it was accepted is closed by the scheduled
close, which erases its details (DEC-1308 item 7)."""
STATUS_LIFETIME: Final = timedelta(hours=12)
"""[ASSUMED] A shift status the practitioner set stands for this long, then reads as not set: a
status left on 'Break' overnight must not tell the next morning's coordinator anything."""

_FAR: Final = datetime.max.replace(tzinfo=UTC)
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")

_CANCELLED_AFTER: Final = frozenset({BookingStatus.CANCELLED_AFTER, BookingStatus.WITHDRAWN})


def effective_state(
    offer: VisitOffer, booking_status: BookingStatus | None, now: datetime
) -> VisitState:
    """The state to show. An offer still `offered` is withdrawn once its booking is no longer
    waiting for an answer (another practitioner accepted, the advisor cancelled, the booking
    expired or was answered) and expired once its time has passed. A visit that is under way is
    withdrawn when the booking was cancelled after it was confirmed."""
    if offer.state is VisitState.OFFERED:
        if booking_status is not BookingStatus.REQUESTED:
            return VisitState.WITHDRAWN
        if now >= offer.expires_at:
            return VisitState.EXPIRED
        return VisitState.OFFERED
    if offer.state in ACTIVE_STATES and booking_status in _CANCELLED_AFTER:
        return VisitState.WITHDRAWN
    return offer.state


def close_overdue(
    offer: VisitOffer, booking_status: BookingStatus | None, now: datetime
) -> VisitState | None:
    """The end state a scheduled close gives an offer that is still open in the store, or None when
    it stays as it is. An offer still `offered` ends as `expired` once its time is up, and as
    `withdrawn` if its booking is no longer waiting before that. A visit under way ends as
    `withdrawn` when its booking was cancelled, or when nobody finished it a day after it was
    accepted (`VISIT_LAPSE`): nothing of a visit may outlive the work."""
    if offer.state is VisitState.OFFERED:
        if now >= offer.expires_at:
            return VisitState.EXPIRED
        return VisitState.WITHDRAWN if booking_status is not BookingStatus.REQUESTED else None
    if offer.state in ACTIVE_STATES and (
        booking_status in _CANCELLED_AFTER or now - offer.state_at >= VISIT_LAPSE
    ):
        return VisitState.WITHDRAWN
    return None


def due_by(urgency: Urgency, offered_at: datetime) -> datetime | None:
    """When the patient is wanted seen by, when the urgency gives a time: two hours after the offer
    for 'within 2 hrs'. 'Today' and 'planned' give none."""
    return offered_at + WITHIN_2_HRS if urgency is Urgency.WITHIN_2_HRS else None


def order_of_round(offers: Sequence[VisitOffer]) -> list[VisitOffer]:
    """The visits in the order they are wanted: those with a time first, earliest first, then the
    rest by when they were offered, then by id so the order is the same every time."""

    def key(offer: VisitOffer) -> tuple[datetime, datetime, str]:
        due = due_by(offer.urgency, offer.offered_at)
        return (due if due is not None else _FAR, offer.offered_at, offer.id)

    return sorted(offers, key=key)


def _text(field: str, value: object, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValidationFailed(field, "must be text")
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValidationFailed(field, "is required")
    if len(cleaned) > maximum:
        raise ValidationFailed(field, f"must be at most {maximum} characters")
    if _CONTROL.search(cleaned):
        raise ValidationFailed(field, "must be plain text")
    return cleaned


def check_details(address: object, contact: object) -> tuple[str, str]:
    """The address and contact an advisor gives with an offer, trimmed and checked."""
    return _text("address", address, ADDRESS_MAX), _text("contact", contact, CONTACT_MAX)


def check_eta_minutes(value: object) -> int:
    """A whole number of minutes from 1 to 240; a boolean or a decimal is refused."""
    if type(value) is not int or not 1 <= value <= ETA_MAX_MINUTES:
        raise ValidationFailed("eta_minutes", f"must be a whole number from 1 to {ETA_MAX_MINUTES}")
    return value


def current_status(settings: VisitSettings, now: datetime) -> ShiftStatus | None:
    """The status the practitioner set, while it still stands."""
    if settings.status is None or settings.status_at is None:
        return None
    return settings.status if now - settings.status_at < STATUS_LIFETIME else None
