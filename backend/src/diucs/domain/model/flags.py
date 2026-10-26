"""Report flags and service flags (P14). Shape only in the red commit; the rules come in the green one.

A report flag says a capacity report needs a check by phone. It is a separate record because
capacity reports are never edited. A service flag (suspended, criteria-overdue) changes what the
status rules and the options filter do.
"""

from dataclasses import dataclass
from datetime import datetime

from diucs.domain.codes import ReportFlagReason

REPORT_FLAG_OPEN = "open"
REPORT_FLAG_CHECKED = "checked"
REPORT_FLAG_ACCEPTED = "accepted"

SERVICE_FLAG_SUSPENDED = "suspended"
SERVICE_FLAG_CRITERIA_OVERDUE = "criteria-overdue"


@dataclass(frozen=True, slots=True)
class ReportFlag:
    id: str
    report_id: str
    service_id: str
    reason: ReportFlagReason
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
    outcome: str | None = None


@dataclass(frozen=True, slots=True)
class ServiceFlag:
    service_id: str
    code: str
    active: bool
    reason: str
    actor_id: str
    at: datetime
