"""Scheduled work: the records that name a message the bus will deliver later (P08).

A use case never schedules a message itself. It writes a ScheduledWork row through schedule_work
(U03), and the outbox relay (I03) asks the bus for the sequence number and stores it on the row, so
the message can be cancelled later (architecture.md, Scheduling).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from diucs.domain.errors import ValidationFailed


class WorkKind(StrEnum):
    PROMPT_DUE = "prompt-due"
    REMINDER = "reminder"
    PHONE_TASK = "phone-task"
    ESCALATE_TO_LEAD = "escalate-to-lead"
    BOOKING_PHONE_PROMPT = "booking-phone-prompt"
    BOOKING_EXPIRE = "booking-expire"
    CRITERIA_REVIEW_REMINDER = "criteria-review-reminder"
    ALERT_ESCALATE = "alert-escalate"
    CLINICAL_RETURN = "clinical-return"
    REVERIFY = "reverify"
    NOT_UPDATED_CHECK = "not-updated-check"
    INVARIANT_CHECK = "invariant-check"
    # The escalation of an unacknowledged booking withdrawal (U21). Its own kind, not
    # ESCALATE_TO_LEAD: the missed-report ladder owns that kind and the dispatcher routes by kind.
    WITHDRAWAL_ESCALATE = "withdrawal-escalate"
    # The projection heartbeat of one tenant that shares capacity with a network (TEN-056): its own
    # chain, one scheduled job at a time, that re-projects and reconciles and schedules the next.
    PROJECTION_HEARTBEAT = "projection-heartbeat"


SCHEDULED = "scheduled"
DONE = "done"
CANCELLED = "cancelled"
WORK_STATUSES = (SCHEDULED, DONE, CANCELLED)


@dataclass(frozen=True, slots=True)
class ScheduledWork:
    id: str
    kind: WorkKind
    due_at: datetime
    about_id: str
    sequence_number: int | None
    status: str

    def __post_init__(self) -> None:
        if self.due_at.tzinfo is None or self.due_at.utcoffset() is None:
            raise ValidationFailed("due_at", "must be a timezone-aware datetime")
        if self.status not in WORK_STATUSES:
            raise ValidationFailed("status", "must be scheduled, done or cancelled")
