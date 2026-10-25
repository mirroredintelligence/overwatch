"""Booking record: one request to a service to take a patient (P02). Red stub: logic not yet built."""

from dataclasses import dataclass
from datetime import datetime

from diucs.domain.codes import BookingStatus


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

    def with_status(
        self, target: BookingStatus, at: datetime, reason: str | None = None
    ) -> "Booking":
        raise NotImplementedError("P02: with_status")
