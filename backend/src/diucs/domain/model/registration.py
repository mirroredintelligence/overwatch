"""Registration and scope-list records (P13).

A registration is a Task with code register-service (fhir-data-model.md). Its wizard draft is a
mapping of steps, each a non-empty mapping of text, whole-number or flag fields. The draft is kept
as typed graph rows, never as JSON (DEC-001, DEC-080). A scope entry says whether one service is
in the pilot, later or out of scope.

Pure: no I/O. Refusals name fields only, never values.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from diucs.domain.codes import RegistrationStatus, ScopeFlag, ServiceCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.registration import ApprovalChecks


def _aware(name: str, value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(name, "must be a timezone-aware datetime")


def _check_draft(draft: object) -> None:
    if not isinstance(draft, dict):
        raise ValidationFailed("draft", "must be a mapping of steps")
    for step, fields in draft.items():
        if not isinstance(step, str) or not step:
            raise ValidationFailed("draft", "a step name must be text")
        if not isinstance(fields, dict) or not fields:
            raise ValidationFailed("draft", "each step must be a non-empty mapping")
        for name, value in fields.items():
            if not isinstance(name, str) or not name:
                raise ValidationFailed("draft", "a field name must be text")
            if not isinstance(value, str | int | bool):
                raise ValidationFailed("draft", "a field must be text, a whole number or a flag")


@dataclass(frozen=True, slots=True)
class Registration:
    id: str
    service_id: str
    status: RegistrationStatus
    requester_role_id: str | None
    owner_role_id: str | None
    created_at: datetime
    last_modified: datetime
    submitted_at: datetime | None = None
    draft: dict[str, dict[str, Any]] = field(default_factory=dict)
    checks: ApprovalChecks = ApprovalChecks(False, False, None, False)
    note: str = ""

    def __post_init__(self) -> None:
        # Lesson L38: a status is checked by its enum type, never by its value.
        if not isinstance(self.status, RegistrationStatus):
            raise ValidationFailed("status", "must be a registration status")
        _aware("created_at", self.created_at)
        _aware("last_modified", self.last_modified)
        if self.submitted_at is not None:
            _aware("submitted_at", self.submitted_at)
        _check_draft(self.draft)
        if not isinstance(self.checks, ApprovalChecks):
            raise ValidationFailed("checks", "must be the four approval checks")
        if not isinstance(self.note, str):
            raise ValidationFailed("note", "must be text")


@dataclass(frozen=True, slots=True)
class ScopeEntry:
    service_id: str
    name: str
    category: ServiceCategory
    flag: ScopeFlag
    date: date
    reason: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.flag, ScopeFlag):
            raise ValidationFailed("flag", "must be a scope flag")
        if not isinstance(self.category, ServiceCategory):
            raise ValidationFailed("category", "must be a service category")
        # Lesson L48: datetime is a subclass of date, so an instant must be refused explicitly.
        if not isinstance(self.date, date) or isinstance(self.date, datetime):
            raise ValidationFailed("date", "must be a calendar date")
        if not isinstance(self.reason, str):
            raise ValidationFailed("reason", "must be text")
