"""Scheduled work: the records that name a message the bus will deliver later (P08).

A use case never schedules a message itself. It writes a ScheduledWork row through schedule_work
(U03), and the outbox relay (I03) asks the bus for the sequence number and stores it on the row, so
the message can be cancelled later (architecture.md, Scheduling).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


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
