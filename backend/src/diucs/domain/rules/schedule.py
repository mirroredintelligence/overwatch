"""Report schedule and missed-report ladder times (domain-rules 1.4 and 1.5, D04).

STUB (DEC-010): names and signatures only, so the red tests fail on assertions.
"""

from datetime import date, datetime, time, timedelta
from enum import StrEnum

from diucs.domain.model.service import ServiceProfile

REPLY_WINDOW = timedelta(minutes=30)
REMINDER_AFTER = timedelta(minutes=30)
PHONE_TASK_AFTER = timedelta(minutes=60)
ESCALATE_AFTER = timedelta(minutes=90)
TWICE_A_DAY_SECOND = time(14, 0)


class LadderStep(StrEnum):
    PROMPT = "prompt"
    REMINDER = "reminder"
    PHONE_TASK = "phone-task"
    ESCALATE = "escalate"


def due_times_on(profile: ServiceProfile, london_day: date) -> list[datetime]:
    raise NotImplementedError


def next_due(profile: ServiceProfile, now: datetime) -> datetime | None:
    raise NotImplementedError


def current_due(profile: ServiceProfile, now: datetime) -> datetime | None:
    raise NotImplementedError


def reply_by(due: datetime) -> datetime:
    raise NotImplementedError


def ladder_times(due: datetime) -> dict[LadderStep, datetime]:
    raise NotImplementedError
