"""Registration and scope-list records (P13).

A registration is a Task with code register-service (fhir-data-model.md). Its wizard draft is a
mapping of steps, each a non-empty mapping of text, whole-number or flag fields. The draft is kept
as typed graph rows, never as JSON (DEC-001, DEC-080). A scope entry says whether one service is
in the pilot, later or out of scope.

Pure: no I/O. Refusals name fields only, never values.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Final

from diucs.domain.codes import RegistrationStatus, ScopeFlag, ServiceCategory, code_system_url
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import check_staff_text
from diucs.domain.rules.registration import ApprovalChecks

DISTRICT_TYPE_CODE: Final = "postcode-district"
"""The Location type of an area a visiting service covers (fhir-data-model.md, Location)."""
LOCATION_TYPE_SYSTEM: Final = code_system_url("location-type")


class CallBackResult(StrEnum):
    """What a reviewer's call-back to the number on the register found (U28)."""

    CONFIRMED = "confirmed"
    NOT_CONFIRMED = "not-confirmed"
    NO_ANSWER = "no-answer"


class Answer(StrEnum):
    """One of the four scope questions answered yes, no or not sure (U28)."""

    YES = "yes"
    NO = "no"
    NOT_SURE = "not-sure"


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


@dataclass(frozen=True, slots=True)
class Invitation:
    """An invitation to report for a service (U24): a Task with code invite-reporter.

    The lead's post asks, the invitee (a practitioner) is the owner, and the registration it opens
    is `registration_id`. `sent_at` is when the latest text went out and `expires_at` is 48 hours
    after it; a resend moves both. The link token is not here: only its hash is stored, by the link
    adapter, and the phone number is never here (it is in the protected contact store).
    """

    id: str
    service_id: str
    registration_id: str
    requester_role_id: str
    invitee_id: str
    role_label: str
    created_at: datetime
    sent_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name in ("id", "service_id", "registration_id", "requester_role_id", "invitee_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValidationFailed(name, "must not be blank")
        if not isinstance(self.role_label, str) or not self.role_label.strip():
            raise ValidationFailed("role_label", "must not be blank")
        check_staff_text("role_label", self.role_label)
        _aware("created_at", self.created_at)
        _aware("sent_at", self.sent_at)
        _aware("expires_at", self.expires_at)
        if self.sent_at < self.created_at:
            raise ValidationFailed("sent_at", "cannot be before the invitation was made")
        if self.expires_at <= self.sent_at:
            raise ValidationFailed("expires_at", "must be after the invitation was sent")
