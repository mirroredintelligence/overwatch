"""Freshness of a service's figure: overdue, data age and the stale warning (D05).

Rules: docs/spec/domain-rules.md 1.5 and the D05 prompt. Decision DEC-029 records one deviation.
Pure: no I/O and no clock. `now` is an argument. Every instant is converted to UTC before it is
compared or subtracted (lesson L4).

A due time is missed when its reply-by (due + the policy's reply window) is before now. The service
is overdue when a missed due time is later than its last report (no report ever: any missed due
counts). The latest missed due is `was_due`. It is found with current_due only (lesson L30), because
the latest due that is at or before now minus the reply window is the latest missed due. If that one
has been answered, every earlier due has been answered too.

The reply window and the stale limit are tenant policy (TEN-021): `assess_freshness` takes a
`TenantPolicy` after its instants, defaulting to `DEFAULT_POLICY` (tenant_policy.py holds the
defaults and bounds). STALE_WARNING_AFTER below is an alias of the default policy's value. The due
times are read in the `zone` of the tenant (TEN-065), London by default.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy, require_policy
from diucs.domain.rules.london_time import LONDON, require_zone
from diucs.domain.rules.schedule import current_due

# Alias of the default policy (TEN-021): the number is defined once, in tenant_policy.py.
STALE_WARNING_AFTER: Final = DEFAULT_POLICY.stale_warning_after
ONE_MICROSECOND: Final = timedelta(microseconds=1)
ONE_MINUTE: Final = timedelta(minutes=1)
MINUTES_PER_HOUR: Final = 60


@dataclass(frozen=True, slots=True)
class Freshness:
    overdue: bool
    age: timedelta | None
    stale_warning: bool
    was_due: datetime | None


def _as_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _latest_missed_due(
    profile: ServiceProfile,
    last_report_at: datetime | None,
    now: datetime,
    policy: TenantPolicy,
    zone: ZoneInfo,
) -> datetime | None:
    # Missed means reply-by < now, that is due < now - reply window.
    # A valid profile always has a due within the look-back, so None here means no miss.
    latest = current_due(profile, now - policy.reply_window - ONE_MICROSECOND, policy, zone)
    if latest is None or (last_report_at is not None and latest <= last_report_at):
        return None
    return latest


def assess_freshness(
    profile: ServiceProfile,
    last_report_at: datetime | None,
    now: datetime,
    policy: TenantPolicy = DEFAULT_POLICY,
    zone: ZoneInfo = LONDON,
) -> Freshness:
    policy = require_policy(policy)
    zone = require_zone(zone)
    now_utc = _as_utc(now, "now")
    last_utc = None if last_report_at is None else _as_utc(last_report_at, "last_report_at")
    if last_utc is not None and last_utc > now_utc:
        raise ValueError("last_report_at must not be after now")

    age = None if last_utc is None else now_utc - last_utc
    was_due = _latest_missed_due(profile, last_utc, now_utc, policy, zone)
    return Freshness(
        overdue=was_due is not None,
        age=age,
        stale_warning=age is not None and age > policy.stale_warning_after,
        was_due=was_due,
    )


def data_age_text(age: timedelta) -> str:
    if age < timedelta(0):
        raise ValueError("data age must not be negative")
    if age < ONE_MINUTE:
        return "just now"
    minutes = age // ONE_MINUTE  # whole minutes, rounded down
    if minutes < MINUTES_PER_HOUR:
        return f"{minutes} min ago"
    hours, rest = divmod(minutes, MINUTES_PER_HOUR)
    hour_word = "hr" if hours == 1 else "hrs"
    if rest == 0:
        return f"{hours} {hour_word} ago"
    return f"{hours} {hour_word} {rest} min ago"
