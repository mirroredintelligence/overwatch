"""Alert rules: triggers, subscriptions, quiet hours and escalation (D24).

Rule: docs/spec/domain-rules.md section 8. Pure: no I/O and no clock. `now` is an argument.

- service-closed (critical): a service moves to not-accepting while in hours. Planned out-of-hours
  closures raise nothing.
- over-capacity: a service moves to over-capacity from any other status.
- not-updated: time-based, from `not_updated_alert_due`, which a worker calls with the clock.
- system-pressure (critical): pressure moves to high from normal or watch.

Quiet hours are London local 22:00 to 06:00, or none. Each instant is converted to UTC before it is
compared, so the clock changes of 2026-03-29 and 2026-10-25 do not shift a window (lessons L4, L25,
L52). Choices the prompt leaves open are in DEC-046. Refusals: naive datetimes raise ValueError
(as london_time.py does); a status or pressure that is not an exact member raises TypeError
(DEC-040, lessons L3 and L38); a bad field value raises ValidationFailed with the field name.
An alert carries no free text (H-09).

The defaults of a new user's alert preferences and the critical kinds are tenant policy (TEN-064):
`default_preferences`, `alerts_for_change` and `alert_for_pressure` take a `TenantPolicy` as their
last argument, defaulting to `DEFAULT_POLICY`, and read `alert_default_kinds`,
`alert_default_not_updated_hours` and `critical_alert_kinds`. An alert is critical when its kind is
in the policy's set; that rule lives in one private constructor the three functions use, because an
`Alert` has no policy, so `Alert.__post_init__` keeps only the structural checks. The option sets
(not-updated hours 2 or 4, acknowledge minutes, quiet hours 22:00 to 06:00) and the escalation
ladder stay global.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Final

from diucs.domain.codes import AlertKind, Status
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy, require_policy
from diucs.domain.rules.london_time import london_to_utc, to_london
from diucs.domain.rules.pressure import Pressure

# [ASSUMED] critical set, rule book section 8. Alias of the default policy (TEN-064): the set is
# defined once, in tenant_policy.py.
CRITICAL_KINDS: Final = DEFAULT_POLICY.critical_alert_kinds
NOT_UPDATED_HOURS: Final = frozenset({2, 4})
ACK_MINUTES: Final = frozenset({10, 15, 30})
QUIET_START: Final = time(22, 0)
QUIET_END: Final = time(6, 0)
ESCALATION_LADDER: Final = ("subscriber", "deputy", "shift-lead")


@dataclass(frozen=True, slots=True)
class Alert:
    kind: AlertKind
    service_id: str | None
    raised_at: datetime
    critical: bool

    def __post_init__(self) -> None:
        if self.kind is AlertKind.SYSTEM_PRESSURE:
            if self.service_id is not None:
                raise ValidationFailed("service_id", "a system-pressure alert names no service")
        elif not self.service_id:
            raise ValidationFailed("service_id", "a service alert needs its service id")
        if type(self.critical) is not bool:
            raise ValidationFailed("critical", "must be true or false")


@dataclass(frozen=True, slots=True)
class AlertPreferences:
    kinds: frozenset[AlertKind]
    not_updated_hours: int
    quiet_hours: tuple[time, time] | None
    quiet_critical_only: bool
    ack_minutes: int

    def __post_init__(self) -> None:
        if any(type(kind) is not AlertKind for kind in self.kinds):
            raise ValidationFailed("kinds", "must be alert kinds")
        if self.not_updated_hours not in NOT_UPDATED_HOURS:
            raise ValidationFailed("not_updated_hours", "must be 2 or 4")
        if self.ack_minutes not in ACK_MINUTES:
            raise ValidationFailed("ack_minutes", "must be 10, 15 or 30")
        if self.quiet_hours is not None and self.quiet_hours != (QUIET_START, QUIET_END):
            raise ValidationFailed("quiet_hours", "must be 22:00 to 06:00, or none")


def _alert(
    kind: AlertKind, service_id: str | None, raised_at: datetime, policy: TenantPolicy
) -> Alert:
    """The one constructor of the three functions: critical follows the tenant's critical kinds."""
    return Alert(kind, service_id, raised_at, kind in policy.critical_alert_kinds)


def default_preferences(policy: TenantPolicy = DEFAULT_POLICY) -> AlertPreferences:
    policy = require_policy(policy)
    return AlertPreferences(
        kinds=policy.alert_default_kinds,
        not_updated_hours=policy.alert_default_not_updated_hours,
        quiet_hours=None,
        quiet_critical_only=True,
        ack_minutes=15,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware (UTC)")
    return value.astimezone(UTC)


def _status(value: object) -> Status:
    if type(value) is not Status:
        raise TypeError(f"expected Status, got {type(value).__name__}")
    return value


def _pressure(value: object) -> Pressure:
    if type(value) is not Pressure:
        raise TypeError(f"expected Pressure, got {type(value).__name__}")
    return value


def alerts_for_change(
    service_id: str,
    before: Status | None,
    after: Status,
    in_hours: bool,
    now: datetime,
    policy: TenantPolicy = DEFAULT_POLICY,
) -> list[Alert]:
    policy = require_policy(policy)
    if not service_id:
        raise ValidationFailed("service_id", "required")
    raised_at = _as_utc(now)
    prior = None if before is None else _status(before)
    current = _status(after)
    moved = prior is not current
    alerts: list[Alert] = []
    if current is Status.NOT_ACCEPTING and in_hours and moved:
        alerts.append(_alert(AlertKind.SERVICE_CLOSED, service_id, raised_at, policy))
    if current is Status.OVER_CAPACITY and moved:
        alerts.append(_alert(AlertKind.OVER_CAPACITY, service_id, raised_at, policy))
    return alerts


def alert_for_pressure(
    before: Pressure, after: Pressure, now: datetime, policy: TenantPolicy = DEFAULT_POLICY
) -> Alert | None:
    policy = require_policy(policy)
    raised_at = _as_utc(now)
    prior = _pressure(before)
    current = _pressure(after)
    if current is Pressure.HIGH and (prior is Pressure.NORMAL or prior is Pressure.WATCH):
        return _alert(AlertKind.SYSTEM_PRESSURE, None, raised_at, policy)
    return None


def not_updated_alert_due(not_updated_since: datetime, hours: int, now: datetime) -> bool:
    if hours not in NOT_UPDATED_HOURS:
        raise ValidationFailed("not_updated_hours", "must be 2 or 4")
    since = _as_utc(not_updated_since)
    return _as_utc(now) - since >= timedelta(hours=hours)


def _in_quiet_hours(now: datetime, start: time, end: time) -> bool:
    """True when the UTC instant falls in the London window that wraps midnight (start > end).

    The window for each London date on either side of `now` is built as two UTC instants, and the
    instant is compared with them. Validation allows only 22:00 to 06:00, so start is after end.
    """
    local_date = to_london(now).date()
    for day in (local_date - timedelta(days=1), local_date):
        window_start = london_to_utc(day, start)
        window_end = london_to_utc(day + timedelta(days=1), end)
        if window_start <= now < window_end:
            return True
    return False


def should_notify(prefs: AlertPreferences, alert: Alert, now: datetime) -> bool:
    current = _as_utc(now)
    if alert.kind not in prefs.kinds:
        return False
    if prefs.quiet_hours is None or not _in_quiet_hours(current, *prefs.quiet_hours):
        return True
    return alert.critical or not prefs.quiet_critical_only


def escalation_at(alert_sent_at: datetime, prefs: AlertPreferences) -> datetime:
    return _as_utc(alert_sent_at) + timedelta(minutes=prefs.ack_minutes)


def next_escalation_target(current: str) -> str | None:
    if current not in ESCALATION_LADDER:
        raise ValidationFailed("current", "unknown escalation stage")
    position = ESCALATION_LADDER.index(current) + 1
    return ESCALATION_LADDER[position] if position < len(ESCALATION_LADDER) else None
