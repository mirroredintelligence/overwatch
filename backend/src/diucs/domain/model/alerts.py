"""Alert records (P17): what each practitioner is alerted about, and each alert raised (U33, U34).

Pure value objects. Validation is added with the implementation (DEC-010: this red stub holds the
fields only).
"""

from dataclasses import dataclass
from datetime import datetime

from diucs.domain.codes import AlertKind
from diucs.domain.rules.alerts import AlertPreferences


@dataclass(frozen=True, slots=True)
class AlertSubscription:
    practitioner_id: str
    preferences: AlertPreferences
    deputy_id: str | None
    daily_summary: bool
    weekly_summary: bool
    updated_at: datetime


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
