"""Booking record: one request to a service to take a patient (P02).

Status moves go through the D13 state machine (rules/booking_state.py). Every datetime must be
timezone-aware, because instants are compared across the London clock change (lesson L52).
"""

from dataclasses import dataclass, replace
from datetime import datetime

from diucs.domain.codes import BookingStatus
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.booking_state import transition


def _aware(field: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Booking:
    id: str
    reference: str
    service_id: str
    case_id: str
    requester_id: str
    status: BookingStatus
    requested_at: datetime
    reply_by: datetime
    confirmed_at: datetime | None = None
    responded_at: datetime | None = None
    reason: str | None = None
    phone_prompt_at: datetime | None = None
    """When the advisor is told to phone the service: the tenant's own setting at the time of the
    request, kept so that no page has to guess it (H-493)."""
    request_message_id: str | None = None
    """The id of the message that asked the service, so its delivery state can be read (H-494)."""
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    """When and by whom a withdrawal or a not-reached report was acknowledged (KI-451)."""

    def __post_init__(self) -> None:
        _aware("requested_at", self.requested_at)
        _aware("reply_by", self.reply_by)
        if self.confirmed_at is not None:
            _aware("confirmed_at", self.confirmed_at)
        if self.responded_at is not None:
            _aware("responded_at", self.responded_at)
        if self.phone_prompt_at is not None:
            _aware("phone_prompt_at", self.phone_prompt_at)
        if self.acknowledged_at is not None:
            _aware("acknowledged_at", self.acknowledged_at)

    def with_acknowledgement(self, by: str, at: datetime) -> Booking:
        """The booking after an advisor has seen it withdrawn or not reached. The first
        acknowledgement stands: a later one by another advisor changes nothing."""
        _aware("at", at)
        if self.acknowledged_at is not None:
            return self
        return replace(self, acknowledged_at=at, acknowledged_by=by)

    def with_status(
        self, target: BookingStatus, at: datetime, reason: str | None = None
    ) -> Booking:
        """The booking after a move to `target` at `at`. A confirmation also sets confirmed_at.

        A reason from the earlier state is kept unless this move gives one.
        """
        _aware("at", at)
        status = transition(self.status, target)
        return replace(
            self,
            status=status,
            responded_at=at,
            confirmed_at=at if status is BookingStatus.CONFIRMED else self.confirmed_at,
            reason=self.reason if reason is None else reason,
        )
