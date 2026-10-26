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
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime

from diucs.domain.codes import Channel, PractitionerRoleCode
from diucs.domain.errors import ValidationFailed

REPORTER_ROLE_CODES: frozenset[PractitionerRoleCode] = frozenset(
    {PractitionerRoleCode.DUTY_MANAGER, PractitionerRoleCode.COORDINATOR}
)


_PHONE_HASH = re.compile(r"[0-9a-f]{64}")
_EMAIL_DOMAIN = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+")
# The postcode shape of DEC-047 item 1, copied here so the domain model does not depend on the
# messages module. A staff name carries no postcode (DEC-065 item 6).
_POSTCODE = re.compile(r"\b[A-Z]{1,2}[0-9][A-Z0-9]?\s*[0-9][A-Z]{2}\b", re.IGNORECASE)
# A staff name may hold at most nine Unicode decimal digits (Nd) in total (DEC-065 item 11).
_MAX_STAFF_DIGITS = 9


def _normalise_staff_text(value: str) -> str:
    """Normalise before any check, in this order: decompose (NFKD), drop format characters (Cf) and
    combining marks (Mn), then compose (NFKC). The decomposition comes first so that a combining
    mark is seen before NFKC composes it into a letter (DEC-065 item 12)."""
    decomposed = unicodedata.normalize("NFKD", value)
    kept = "".join(c for c in decomposed if unicodedata.category(c) not in ("Cf", "Mn"))
    return unicodedata.normalize("NFKC", kept)


def check_staff_text(field: str, value: str) -> None:
    """A staff name may not carry a postcode, and may not hold ten or more Unicode decimal digits
    in total. Both checks run on the normalised text (DEC-065 items 6, 11 and 12). Refused by field
    name only; the value is never echoed."""
    text = _normalise_staff_text(value)
    digits = sum(1 for character in text if character.isdecimal())
    if _POSTCODE.search(text) or digits > _MAX_STAFF_DIGITS:
        raise ValidationFailed(field, "must not carry a postcode or a phone or NHS number")


def check_phone_hash(value: str) -> None:
    """A phone hash is exactly 64 lowercase hex characters (the keyed HMAC, DEC-060). Anything else
    is refused by field name only: the value may be a phone number, so it is never echoed. The check
    is ASCII by design and is not normalised, so a fullwidth or Arabic-Indic digit is refused rather
    than folded into an ASCII one (DEC-065 item 13)."""
    if not isinstance(value, str) or not _PHONE_HASH.fullmatch(value):
        raise ValidationFailed("phone_hash", "must be a 64-character lowercase hex hash")


def check_email_domain(value: str) -> None:
    """A bare domain: lowercase letters, digits and hyphens, with at least one dot. No '@', no
    spaces, no local part. Refused by field name only, never echoed (DEC-065). ASCII by design and
    not normalised: a fullwidth full stop is refused, not folded into a dot (DEC-065 item 13)."""
    if not isinstance(value, str) or not _EMAIL_DOMAIN.fullmatch(value):
        raise ValidationFailed("email_domain", "must be a bare domain such as nhs.example")


def check_aware(field: str, value: datetime) -> None:
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
        check_staff_text("display_name", self.display_name)
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
        check_aware("period_start", self.period_start)
        if self.period_end is not None:
            check_aware("period_end", self.period_end)
        if (self.covered_by_practitioner_id is None) != (self.covered_until is None):
            raise ValidationFailed("covered", "needs both the covering practitioner and the end")
        if self.covered_until is not None:
            check_aware("covered_until", self.covered_until)


def role_holder(role: PractitionerRole, now: datetime) -> str:
    """The practitioner whose phone gets this role's prompts at `now`."""
    check_aware("now", now)
    if (
        role.covered_by_practitioner_id is not None
        and role.covered_until is not None
        and now.astimezone(UTC) < role.covered_until.astimezone(UTC)
    ):
        return role.covered_by_practitioner_id
    return role.practitioner_id


def is_in_effect(role: PractitionerRole, now: datetime) -> bool:
    """Whether the role's period covers `now`: from period_start, and before period_end if set."""
    check_aware("now", now)
    at = now.astimezone(UTC)
    if at < role.period_start.astimezone(UTC):
        return False
    return role.period_end is None or at < role.period_end.astimezone(UTC)
