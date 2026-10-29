"""Support access rules (O06): a support code, its window, the open window and the lead check.

Rule: docs/spec/observability.md "Privacy and governance" (a support code is valid for a set number
of
hours, a support access is shown to the person) and the O06 prompt. Pure: no clock and no store.
Every
time is an argument, and an aware time is compared in UTC. A naive time is refused with ValueError.

- A support code is the eight characters of SUPPORT_CODE_ALPHABET (tokens.py), shown XXXX-XXXX. A
  typed
  code may carry spaces, hyphens and lower case; normalise_support_code gives the display form or
  None.
- Only the keyed hash of the display form is stored (hash_token, secret SUPPORT_CODE_SECRET).
- SUPPORT_CODE_VALID_FOR [ASSUMED 4 hours] is the life of a code. SUPPORT_ACCESS_VALID_FOR [ASSUMED
  1 hour] is the life of one open.
- A lead for a ticket open is an active practitioner with an active role whose code is one of
  LEAD_ROLE_CODES [ASSUMED: shift-lead and clinical-lead, to be confirmed by the owner].
"""

import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Final

from diucs.domain.codes import PractitionerRoleCode, Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import PractitionerRole
from diucs.domain.rules.tokens import (
    SUPPORT_CODE_ALPHABET,
    SUPPORT_CODE_GROUP,
    SUPPORT_CODE_LENGTH,
    hash_token,
)

SUPPORT_CODE_VALID_FOR: Final = timedelta(hours=4)  # [ASSUMED]
SUPPORT_ACCESS_VALID_FOR: Final = timedelta(hours=1)  # [ASSUMED]
SUPPORT_CODE_SECRET: Final = "support-code"
LEAD_ROLE_CODES: Final[frozenset[PractitionerRoleCode]] = frozenset(
    {PractitionerRoleCode.SHIFT_LEAD, PractitionerRoleCode.CLINICAL_LEAD}
)  # [ASSUMED]

_SEPARATORS: Final = re.compile(r"[ \-]")


def _utc(moment: datetime, name: str) -> datetime:
    if not isinstance(moment, datetime) or moment.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return moment.astimezone(UTC)


def normalise_support_code(text: object) -> str | None:
    """The display form XXXX-XXXX of a typed code, or None when it is not a support code. Spaces and
    hyphens are dropped and letters are upper-cased before the check, so "abcd efgh" is accepted."""
    if not isinstance(text, str):
        return None
    compact = _SEPARATORS.sub("", text).upper()
    if len(compact) != SUPPORT_CODE_LENGTH or any(c not in SUPPORT_CODE_ALPHABET for c in compact):
        return None
    return f"{compact[:SUPPORT_CODE_GROUP]}-{compact[SUPPORT_CODE_GROUP:]}"


def hash_support_code(code: str, secret: bytes) -> str:
    """The keyed hash the store keeps. Refuses anything that is not a support code, by field
    name."""
    canonical = normalise_support_code(code)
    if canonical is None:
        raise ValidationFailed("code", "is not a support code")
    return hash_token(canonical, secret)


def code_window(now: datetime) -> datetime:
    """When a code made at `now` stops being valid."""
    return _utc(now, "now") + SUPPORT_CODE_VALID_FOR


def access_window(now: datetime) -> datetime:
    """When an open that starts at `now` ends."""
    return _utc(now, "now") + SUPPORT_ACCESS_VALID_FOR


def support_code_usable(expires_at: datetime, stopped_at: datetime | None, now: datetime) -> bool:
    """A code opens a session while it has not expired (before the instant, not at it) and has not
    been stopped by the person who shared it."""
    expires = _utc(expires_at, "expires_at")
    current = _utc(now, "now")
    if stopped_at is not None:
        _utc(stopped_at, "stopped_at")
        return False
    return current < expires


def is_lead(roles: Iterable[PractitionerRole], practitioner_active: bool) -> bool:
    """True when the practitioner is active and holds at least one active lead role."""
    if not practitioner_active:
        return False
    return any(role.active and role.code in LEAD_ROLE_CODES for role in roles)


def may_open_support(role: Role) -> bool:
    """Only the support role may open a session, and only with a code or an approved ticket."""
    return role is Role.SUPPORT
