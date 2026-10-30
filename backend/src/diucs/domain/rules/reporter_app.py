"""Rules behind the reporter app's routes (W7C, DEC-810 to DEC-815).

Pure: no I/O and no clock. Every time is an argument, and the tenant's zone is an argument too
(DEC-353): a cover ends at 23:59 on a local day, and "today" is a local day.

- A mobile is shown masked, never whole: its first two and last three digits (`07xxx xxx456`).
- The app's channel words are `app`, `text` and `email`; `app` is the push channel.
- A cover is set by the reporter for `tonight`, `this-week` or a `date`, at most `MAX_COVER_DAYS`
  ahead, and ends at 23:59 local. The shift lead's own change keeps its own rules (U16).
- A service row is `due`, `confirmed` or `paused`, from the service's own due times and its latest
  report (domain-rules 1.4, 1.5).
- A report is a `confirm`, a `number` from 0 to 999 or `closed` (a figure of 0), as for a link.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo

from diucs.domain.codes import Channel
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import TenantPolicy
from diucs.domain.rules.london_time import local_to_utc, require_zone, to_local
from diucs.domain.rules.schedule import current_due, next_due, reply_by

MASKED_NOTHING: Final = "xxxxx xxxxxx"
"""What a value that is not a UK mobile is shown as: no digit of it."""
_NON_DIGITS: Final = re.compile(r"\D")
_NATIONAL_LENGTH: Final = 11
_INTERNATIONAL_LENGTH: Final = 12
_COUNTRY_CODE: Final = "44"

COVER_UNTIL: Final = ("tonight", "this-week", "date")
MAX_COVER_DAYS: Final = 14
"""[ASSUMED] The longest a reporter may hand a service to a cover phone: a fortnight. A longer
absence is the shift lead's change (U16), which has its own audit and approval."""
COVER_ENDS_AT: Final = time(23, 59)
_SUNDAY: Final = 6

MAX_FIGURE: Final = 999
REPORT_KINDS: Final = ("confirm", "number", "closed")

_CHANNEL_BY_WORD: Final = {"app": Channel.PUSH, "text": Channel.TEXT, "email": Channel.EMAIL}
_WORD_BY_CHANNEL: Final = {channel: word for word, channel in _CHANNEL_BY_WORD.items()}


def mask_mobile(stored: str) -> str:
    """A UK mobile (national or +44 form) as `07xxx xxx456`. Anything else shows no digit."""
    if not isinstance(stored, str):
        return MASKED_NOTHING
    digits = _NON_DIGITS.sub("", stored)
    if digits.startswith(_COUNTRY_CODE) and len(digits) == _INTERNATIONAL_LENGTH:
        digits = "0" + digits[len(_COUNTRY_CODE) :]
    if len(digits) != _NATIONAL_LENGTH or not digits.startswith("07"):
        return MASKED_NOTHING
    return f"{digits[:2]}xxx xxx{digits[-3:]}"


def channel_for(word: object) -> Channel:
    """The channel a screen's word names. A word the screens do not use is refused."""
    if isinstance(word, str) and word in _CHANNEL_BY_WORD:
        return _CHANNEL_BY_WORD[word]
    raise ValidationFailed("channel", "must be app, text or email")


def channel_word(channel: Channel | None) -> str:
    """The word a screen shows for a role's channel. A post with none is texted (the default)."""
    return "text" if channel is None else _WORD_BY_CHANNEL[channel]


def cover_end(until: object, day: date | None, now: datetime, zone: ZoneInfo) -> datetime:
    """The instant (UTC) a cover set now ends: 23:59 local on the last day. `tonight` is today,
    `this-week` is this Monday-to-Sunday week's Sunday, `date` is the day given (today to
    MAX_COVER_DAYS ahead). A cover that has already ended is refused."""
    zone = require_zone(zone)
    if not isinstance(until, str) or until not in COVER_UNTIL:
        raise ValidationFailed("until", "must be tonight, this-week or date")
    today = to_local(now, zone).date()
    if until == "date":
        if (
            not isinstance(day, date)
            or isinstance(day, datetime)
            or not today <= day <= today + timedelta(days=MAX_COVER_DAYS)
        ):
            raise ValidationFailed("date", "must be a day from today to a fortnight ahead")
        last = day
    else:
        if day is not None:
            raise ValidationFailed("date", "is only given with a cover until a date")
        last = (
            today
            if until == "tonight"
            else today + timedelta(days=_SUNDAY - to_local(now, zone).weekday())
        )
    ends = local_to_utc(last, COVER_ENDS_AT, zone)
    if now.astimezone(UTC) >= ends:
        raise ValidationFailed("until", "has already ended")
    return ends


def local_day_bounds(now: datetime, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """The UTC instants of this local day's midnight and the next one's (25 or 23 hours long on a
    clock change)."""
    zone = require_zone(zone)
    today = to_local(now, zone).date()
    return (
        local_to_utc(today, time(0, 0), zone),
        local_to_utc(today + timedelta(days=1), time(0, 0), zone),
    )


class RowState(StrEnum):
    CONFIRMED = "confirmed"
    DUE = "due"
    PAUSED = "paused"


@dataclass(frozen=True, slots=True)
class RowAssessment:
    state: RowState
    due_at: datetime | None
    """The latest due time at or before now (the one a due service is answering)."""
    reply_by: datetime | None
    next_due: datetime | None


def assess_row(
    profile: ServiceProfile,
    *,
    suspended: bool,
    latest_at: datetime | None,
    now: datetime,
    policy: TenantPolicy,
    zone: ZoneInfo,
) -> RowAssessment:
    """Where a service stands for its reporter. Suspended is paused, whatever else is true. A
    service is due when its latest due time has had no report since (or it never reported)."""
    due = current_due(profile, now, policy, zone)
    upcoming = next_due(profile, now, policy, zone)
    if suspended:
        return RowAssessment(RowState.PAUSED, due, None, upcoming)
    waiting = due is not None and (latest_at is None or latest_at < due)
    if waiting and due is not None:
        return RowAssessment(RowState.DUE, due, reply_by(due, policy), upcoming)
    return RowAssessment(RowState.CONFIRMED, due, None, upcoming)


def check_report(kind: object, value: object) -> int | None:
    """The figure a report sends: None for a confirm, the number, or 0 for closed. The shape only;
    the reply policy judges the rest."""
    if not isinstance(kind, str) or kind not in REPORT_KINDS:
        raise ValidationFailed("kind", "must be confirm, number or closed")
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationFailed("value", "must be a whole number")
        if not 0 <= value <= MAX_FIGURE:
            raise ValidationFailed("value", "must be from 0 to 999")
        return value
    if value is not None:
        raise ValidationFailed("value", "is only sent with a number")
    return None if kind == "confirm" else 0
