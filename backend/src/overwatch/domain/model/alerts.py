"""Alert records (P17): what each practitioner is alerted about, and each alert raised (U33, U34).

Pure value objects. A subscription is one per practitioner; an alert is one raised for one owner.
The alert kinds and their rules are in diucs.domain.rules.alerts (D24). An alert carries no free
text (H-09).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.domain.codes import AlertKind
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.alerts import AlertPreferences

# Business statuses of an alert (P17). `new` and `escalated` are open; `acknowledged` and `closed`
# are done.
ALERT_STATUSES: Final = frozenset({"new", "acknowledged", "escalated", "closed"})


def _text(field: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(field, "is required")


def _aware(field: str, value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must carry a UTC offset")


def _optional_aware(field: str, value: datetime | None) -> None:
    if value is not None:
        _aware(field, value)


@dataclass(frozen=True, slots=True)
class AlertSubscription:
    practitioner_id: str
    preferences: AlertPreferences
    deputy_id: str | None
    daily_summary: bool
    weekly_summary: bool
    updated_at: datetime

    def __post_init__(self) -> None:
        _text("practitioner_id", self.practitioner_id)
        if not isinstance(self.preferences, AlertPreferences):
            raise ValidationFailed("preferences", "must be the alert preferences")
        if self.deputy_id is not None:
            _text("deputy_id", self.deputy_id)
        for name in ("daily_summary", "weekly_summary"):
            if not isinstance(getattr(self, name), bool):
                raise ValidationFailed(name, "must be a flag")
        _aware("updated_at", self.updated_at)


@dataclass(frozen=True, slots=True)
class AlertRecord:
    id: str
    kind: AlertKind
    service_id: str | None
    owner_practitioner_id: str
    status: str
    raised_at: datetime
    escalation_due_at: datetime | None
    part_of_id: str | None
    acknowledged_at: datetime | None = None

    def __post_init__(self) -> None:
        _text("id", self.id)
        if type(self.kind) is not AlertKind:
            raise ValidationFailed("kind", "must be an alert kind")
        if self.kind is AlertKind.SYSTEM_PRESSURE:
            if self.service_id is not None:
                raise ValidationFailed("service_id", "a system-pressure alert names no service")
        else:
            _text("service_id", self.service_id)
        _text("owner_practitioner_id", self.owner_practitioner_id)
        if self.status not in ALERT_STATUSES:
            raise ValidationFailed("status", "must be new, acknowledged, escalated or closed")
        _aware("raised_at", self.raised_at)
        _optional_aware("escalation_due_at", self.escalation_due_at)
        _optional_aware("acknowledged_at", self.acknowledged_at)
        if self.part_of_id is not None:
            _text("part_of_id", self.part_of_id)
            if self.part_of_id == self.id:
                raise ValidationFailed("part_of_id", "an alert cannot escalate from itself")
