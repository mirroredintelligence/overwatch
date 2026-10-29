"""STUB for the red commit (DEC-010): names and shapes only, no checks. TEN-006 replaces it."""

from dataclasses import dataclass
from datetime import time, timedelta
from types import MappingProxyType
from typing import Final

from diucs.domain.codes import AlertKind

type SettingValue = int | str | bool | time | frozenset[str]


@dataclass(frozen=True, slots=True)
class TenantPolicy:
    reply_window: timedelta = timedelta(minutes=30)
    reminder_after: timedelta = timedelta(minutes=30)
    phone_task_after: timedelta = timedelta(minutes=60)
    escalate_after: timedelta = timedelta(minutes=90)
    twice_a_day_second: time = time(14, 0)
    stale_warning_after: timedelta = timedelta(hours=2)
    pressure_watch_from: int = 3
    pressure_high_from: int = 5
    correction_window: timedelta = timedelta(minutes=15)
    max_consecutive_confirms: int = 2
    many_changes_window: timedelta = timedelta(minutes=5)
    many_changes_count: int = 3
    phoned_window: timedelta = timedelta(minutes=60)
    group_window: timedelta = timedelta(minutes=10)
    max_services_per_phone: int = 3
    booking_reply_window: timedelta = timedelta(minutes=10)
    booking_phone_prompt_after: timedelta = timedelta(minutes=5)
    withdrawal_escalate_after: timedelta = timedelta(minutes=10)
    criteria_reminder_before: timedelta = timedelta(days=14)
    clinical_take_timeout: timedelta = timedelta(minutes=10)
    reverify_every: timedelta = timedelta(days=30)
    critical_alert_kinds: frozenset[AlertKind] = frozenset(
        {AlertKind.SERVICE_CLOSED, AlertKind.SYSTEM_PRESSURE}
    )
    alert_default_kinds: frozenset[AlertKind] = frozenset(AlertKind)
    alert_default_not_updated_hours: int = 2

    def as_settings(self) -> dict[str, SettingValue]:
        return {}


FIELD_BOUNDS: Final = MappingProxyType[str, tuple[object, object]]({})
DEFAULT_POLICY: Final = TenantPolicy()


def require_policy(value: object) -> TenantPolicy:
    return value  # type: ignore[return-value]
