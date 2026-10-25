"""Report schedule and missed-report ladder times (domain-rules 1.4 and 1.5, D04).

A service is due a capacity report at the times set by its cadence, in each window it is open.
Windows are London local (see AvailableTime). Local wall-clock times are built as naive datetimes
and converted with london_to_utc only at the end, so a clock change keeps the local time and
shifts the instant. Two local times that map to the same instant (the spring gap) are merged.
Lesson L4 and L25: schedules are compared as instants, never as local wall-clock values.

An overnight window belongs to the London day it starts. Its due times may fall on the next day.
"""

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Final

from diucs.domain.codes import Cadence
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.london_time import london_to_utc, to_london

REPLY_WINDOW: Final = timedelta(minutes=30)
REMINDER_AFTER: Final = timedelta(minutes=30)
PHONE_TASK_AFTER: Final = timedelta(minutes=60)
ESCALATE_AFTER: Final = timedelta(minutes=90)
TWICE_A_DAY_SECOND: Final = time(14, 0)

EVERY_N_HOURS_STEP: Final = timedelta(hours=2)
MIDNIGHT: Final = time(0, 0)
ONE_DAY: Final = timedelta(days=1)
# next_due searches 8 days ahead (D04 prompt). DEC-023 applies the same look-back to current_due.
SEARCH_DAYS: Final = 8


class LadderStep(StrEnum):
    PROMPT = "prompt"
    REMINDER = "reminder"
    PHONE_TASK = "phone-task"
    ESCALATE = "escalate"


def _window_local_times(cadence: Cadence, window: AvailableTime, day: date) -> Iterator[datetime]:
    """Yield the naive London local due times one window gives on the day it starts."""
    opening = datetime.combine(day, MIDNIGHT if window.all_day else _start(window))

    if cadence is Cadence.ONCE_A_DAY:
        yield opening
        return

    if cadence is Cadence.TWICE_A_DAY:
        yield opening
        # domain-rules 1.4 and DEC-024: 14:00 is due unless the window opens after it.
        if window.all_day or _start(window) <= TWICE_A_DAY_SECOND:
            yield datetime.combine(day, TWICE_A_DAY_SECOND)
        return

    # every-2-hrs: from the opening, every 2 hours, up to and including the closing time.
    # An all-day window has no closing time: its last due time is 22:00, before the next midnight.
    if window.all_day:
        last_due = opening + ONE_DAY - EVERY_N_HOURS_STEP  # 22:00, before the next midnight
    else:
        end_day = day if _end(window) > _start(window) else day + ONE_DAY
        last_due = datetime.combine(end_day, _end(window))
    due = opening
    while due <= last_due:
        yield due
        due += EVERY_N_HOURS_STEP


def _start(window: AvailableTime) -> time:
    # AvailableTime guarantees a start on every timed window (D01).
    assert window.start is not None
    return window.start


def _end(window: AvailableTime) -> time:
    assert window.end is not None
    return window.end


def due_times_on(profile: ServiceProfile, london_day: date) -> list[datetime]:
    """Sorted UTC due instants of windows that start on london_day, with no duplicates."""
    instants: set[datetime] = set()
    for window in profile.available_times:
        if london_day.weekday() not in window.days:
            continue
        for local in _window_local_times(profile.cadence, window, london_day):
            instants.add(london_to_utc(local.date(), local.time()))
    return sorted(instants)


def next_due(profile: ServiceProfile, now: datetime) -> datetime | None:
    """The earliest due instant strictly after now, searching SEARCH_DAYS ahead, or None."""
    today = to_london(now).date()
    candidates = [
        due
        for offset in range(-1, SEARCH_DAYS)
        for due in due_times_on(profile, today + timedelta(days=offset))
        if due > now
    ]
    return min(candidates, default=None)


def current_due(profile: ServiceProfile, now: datetime) -> datetime | None:
    """The latest due instant at or before now, searching SEARCH_DAYS back, or None (DEC-023)."""
    today = to_london(now).date()
    candidates = [
        due
        for offset in range(-SEARCH_DAYS, 1)
        for due in due_times_on(profile, today + timedelta(days=offset))
        if due <= now
    ]
    return max(candidates, default=None)


def reply_by(due: datetime) -> datetime:
    return due + REPLY_WINDOW


def ladder_times(due: datetime) -> dict[LadderStep, datetime]:
    return {
        LadderStep.PROMPT: due,
        LadderStep.REMINDER: due + REMINDER_AFTER,
        LadderStep.PHONE_TASK: due + PHONE_TASK_AFTER,
        LadderStep.ESCALATE: due + ESCALATE_AFTER,
    }
