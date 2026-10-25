"""Practitioners and their posts (P03): a person, the post they fill, and cover.

A person is separate from the post. One phone that reports for three services is one Practitioner
with three PractitionerRoles. When the person leaves, the post stays (fhir-data-model.md, "People,
devices and consent"). The phone number is never here: the Practitioner holds only a keyed hash.

Cover (domain-rules 2.4): while `now < covered_until`, the role's prompts go to the cover
practitioner and the usual holder does not count. Instants are compared in UTC (lesson L52).
Comparing same-zone London datetimes with `<` would use the wall clock across the change.

A role's period is in effect from `period_start` (inclusive) to `period_end` (exclusive), when it
has one. The rule book is silent on periods; this is the reading that uses the fields (DEC-064).
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from diucs.domain.codes import Channel, PractitionerRoleCode
from diucs.domain.errors import ValidationFailed

REPORTER_ROLE_CODES: frozenset[PractitionerRoleCode] = frozenset(
    {PractitionerRoleCode.DUTY_MANAGER, PractitionerRoleCode.COORDINATOR}
)


_PHONE_HASH = re.compile(r"[0-9a-f]{64}")
_EMAIL_DOMAIN = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+")


def check_phone_hash(value: str) -> None:
    """A phone hash is exactly 64 lowercase hex characters (the keyed HMAC, DEC-060). Anything else
    is refused by field name only: the value may be a phone number, so it is never echoed."""
    if not isinstance(value, str) or not _PHONE_HASH.fullmatch(value):
        raise ValidationFailed("phone_hash", "must be a 64-character lowercase hex hash")


def check_email_domain(value: str) -> None:
    """A bare domain: lowercase letters, digits and hyphens, with at least one dot. No '@', no
    spaces, no local part. Refused by field name only, never echoed (DEC-065)."""
    if not isinstance(value, str) or not _EMAIL_DOMAIN.fullmatch(value):
        raise ValidationFailed("email_domain", "must be a bare domain such as nhs.example")


def _aware(field: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Practitioner:
    id: str
    active: bool
    display_name: str
    phone_hash: str | None
    email_domain: str | None = None

    def __post_init__(self) -> None:
        if self.phone_hash is not None:
            check_phone_hash(self.phone_hash)
        if self.email_domain is not None:
            check_email_domain(self.email_domain)


@dataclass(frozen=True, slots=True)
class PractitionerRole:
    id: str
    practitioner_id: str
    service_id: str | None
    code: PractitionerRoleCode
    active: bool
    channel: Channel | None
    period_start: datetime
    period_end: datetime | None = None
    covered_by_practitioner_id: str | None = None
    covered_until: datetime | None = None

    def __post_init__(self) -> None:
        # Type checks use isinstance on the enum class, never the bare value (lesson L3, L38): a
        # plain string or a member of another enum with the same value is refused.
        if not isinstance(self.code, PractitionerRoleCode):
            raise ValidationFailed("code", "not a practitioner role code")
        if self.channel is not None and not isinstance(self.channel, Channel):
            raise ValidationFailed("channel", "not a channel")
        _aware("period_start", self.period_start)
        if self.period_end is not None:
            _aware("period_end", self.period_end)
        if (self.covered_by_practitioner_id is None) != (self.covered_until is None):
            raise ValidationFailed("covered", "needs both the covering practitioner and the end")
        if self.covered_until is not None:
            _aware("covered_until", self.covered_until)


def role_holder(role: PractitionerRole, now: datetime) -> str:
    """The practitioner whose phone gets this role's prompts at `now`."""
    _aware("now", now)
    if (
        role.covered_by_practitioner_id is not None
        and role.covered_until is not None
        and now.astimezone(UTC) < role.covered_until.astimezone(UTC)
    ):
        return role.covered_by_practitioner_id
    return role.practitioner_id


def is_in_effect(role: PractitionerRole, now: datetime) -> bool:
    """Whether the role's period covers `now`: from period_start, and before period_end if set."""
    _aware("now", now)
    at = now.astimezone(UTC)
    if at < role.period_start.astimezone(UTC):
        return False
    return role.period_end is None or at < role.period_end.astimezone(UTC)
