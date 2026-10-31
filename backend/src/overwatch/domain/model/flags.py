"""Report flags and service flags (P14).

A report flag says a capacity report needs a check by phone. It is a separate record because
capacity reports are never edited: flagging, and later resolving, never touches the Observation.
A service flag (suspended, criteria-overdue) changes what the status rules and the options filter
do. One service flag exists per service and code; setting it again replaces it.

Every datetime is held in UTC, whatever zone it came in: a London-zoned value with the same tzinfo
would compare and subtract by wall clock (lesson L4, DEC-025 item 3).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from diucs.domain.codes import ReportFlagReason
from diucs.domain.errors import ValidationFailed

REPORT_FLAG_OPEN = "open"
REPORT_FLAG_CHECKED = "checked"
REPORT_FLAG_ACCEPTED = "accepted"
REPORT_FLAG_STATUSES = frozenset({REPORT_FLAG_OPEN, REPORT_FLAG_CHECKED, REPORT_FLAG_ACCEPTED})

SERVICE_FLAG_SUSPENDED = "suspended"
SERVICE_FLAG_CRITERIA_OVERDUE = "criteria-overdue"
SERVICE_FLAG_HOLDS_MANY = "holds-many-services"
"""Set on each service of a phone that holds more than three services (U38, D28)."""
SERVICE_FLAG_NO_REPORTER = "no-reporter"
"""Set when a removal leaves a service with nobody to text; prompts go to the shift lead (U37)
[ASSUMED code]."""
SERVICE_FLAG_CODES = frozenset(
    {
        SERVICE_FLAG_SUSPENDED,
        SERVICE_FLAG_CRITERIA_OVERDUE,
        SERVICE_FLAG_HOLDS_MANY,
        SERVICE_FLAG_NO_REPORTER,
    }
)


def _text(field: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(field, "must be text, not empty")


def _instant(field: str, value: Any) -> datetime:
    """The value as UTC. A naive datetime is refused: it has no instant to compare."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must be a timezone-aware datetime")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ReportFlag:
    """A capacity report that needs a check. `resolved_at` is set once the flag is checked or
    accepted, and never before."""

    id: str
    report_id: str
    service_id: str
    reason: ReportFlagReason
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
    outcome: str | None = None
    resolved_by: str | None = None
    """The practitioner who resolved the flag (U39). Set with the resolution and never changed."""

    def __post_init__(self) -> None:
        _text("id", self.id)
        _text("report_id", self.report_id)
        _text("service_id", self.service_id)
        if not isinstance(self.reason, ReportFlagReason):
            raise ValidationFailed("reason", "must be a report flag reason")
        if not isinstance(self.status, str) or self.status not in REPORT_FLAG_STATUSES:
            raise ValidationFailed("status", "must be open, checked or accepted")
        created = _instant("created_at", self.created_at)
        resolved = None if self.resolved_at is None else _instant("resolved_at", self.resolved_at)
        if self.status == REPORT_FLAG_OPEN:
            if resolved is not None:
                raise ValidationFailed("resolved_at", "an open flag has no resolution time")
        else:
            if resolved is None:
                raise ValidationFailed("resolved_at", "a resolved flag needs its resolution time")
            if resolved < created:
                raise ValidationFailed("resolved_at", "is earlier than the flag's creation")
        if self.outcome is not None:
            _text("outcome", self.outcome)
        if self.resolved_by is not None:
            _text("resolved_by", self.resolved_by)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "resolved_at", resolved)


@dataclass(frozen=True, slots=True)
class ServiceFlag:
    """A flag on a service. `active` False records that the flag has been lifted; the record is
    kept, and it is not returned as a flag."""

    service_id: str
    code: str
    active: bool
    reason: str
    actor_id: str
    at: datetime
    expired_count: int | None = None
    """How many open requests a suspension expired (W7B C), so the lead's page can say so later.
    None for any other flag, and for a suspension made before the count was kept."""

    def __post_init__(self) -> None:
        _text("service_id", self.service_id)
        if self.expired_count is not None and (
            type(self.expired_count) is not int or self.expired_count < 0
        ):
            raise ValidationFailed("expired_count", "must be a whole number of zero or more")
        if not isinstance(self.code, str) or self.code not in SERVICE_FLAG_CODES:
            raise ValidationFailed("code", "not a known service flag code")
        if not isinstance(self.active, bool):
            raise ValidationFailed("active", "must be true or false")
        _text("reason", self.reason)
        _text("actor_id", self.actor_id)
        object.__setattr__(self, "at", _instant("at", self.at))
