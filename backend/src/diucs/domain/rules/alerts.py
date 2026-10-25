"""Alert rules: triggers, subscriptions, quiet hours and escalation (D24).

Rule: docs/spec/domain-rules.md section 8. Pure: no I/O and no clock. `now` is an argument.

DEC-010 stub: declarations only. Every behaviour raises NotImplementedError until the green commit.
"""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Final

from diucs.domain.codes import AlertKind, Status
from diucs.domain.rules.pressure import Pressure

CRITICAL_KINDS: Final = frozenset({AlertKind.SERVICE_CLOSED, AlertKind.SYSTEM_PRESSURE})  # [ASSUMED]
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


@dataclass(frozen=True, slots=True)
class AlertPreferences:
    kinds: frozenset[AlertKind]
    not_updated_hours: int
    quiet_hours: tuple[time, time] | None
    quiet_critical_only: bool
    ack_minutes: int

    def __post_init__(self) -> None:
        raise NotImplementedError


def default_preferences() -> AlertPreferences:
    raise NotImplementedError


def alerts_for_change(
    service_id: str, before: Status | None, after: Status, in_hours: bool, now: datetime
) -> list[Alert]:
    raise NotImplementedError


def alert_for_pressure(before: Pressure, after: Pressure, now: datetime) -> Alert | None:
    raise NotImplementedError


def not_updated_alert_due(not_updated_since: datetime, hours: int, now: datetime) -> bool:
    raise NotImplementedError


def should_notify(prefs: AlertPreferences, alert: Alert, now: datetime) -> bool:
    raise NotImplementedError


def escalation_at(alert_sent_at: datetime, prefs: AlertPreferences) -> datetime:
    raise NotImplementedError


def next_escalation_target(current: str) -> str | None:
    raise NotImplementedError
