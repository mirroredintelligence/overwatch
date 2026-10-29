"""Identity policy for reporters and COO or ICB users: text codes, PINs and re-verification (D27).

Rules: docs/spec/domain-rules.md section 7 and the D27 prompt. Decision DEC-044 records the
choices the prompt leaves open.

Pure: no I/O and no clock. `now` is an argument. The PIN itself never enters this module: a
PIN is checked by the caller and reported here as a boolean, so nothing here can log or echo it.

Fail closed. A code that has expired, or whose clock reading is impossible, is refused. A
clock that has gone backwards never grants a resend or a verification. Every instant is
converted to UTC before it is compared or added to, because same-zone wall-clock arithmetic
is wrong across the London clock change (lesson L52).
"""

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy

CODE_VALID_FOR: Final = timedelta(minutes=10)
CODE_MAX_TRIES: Final = 5
CODE_RESEND_AFTER: Final = timedelta(seconds=60)  # [ASSUMED cooldown] in domain-rules 7
PIN_MAX_TRIES: Final = 5
REVERIFY_EVERY: Final = timedelta(days=30)

_ASCII_DIGITS: Final = frozenset("0123456789")
PIN_LENGTH: Final = 6


class CodeOutcome(StrEnum):
    VERIFIED = "verified"
    WRONG = "wrong"
    EXPIRED = "expired"
    TOO_MANY_TRIES = "too-many-tries"


@dataclass(frozen=True, slots=True)
class CodeState:
    issued_at: datetime
    failed_tries: int = 0
    verified: bool = False
    last_outcome: CodeOutcome | None = None


class PinOutcome(StrEnum):
    OK = "ok"
    WRONG = "wrong"
    LOCKED = "locked"


@dataclass(frozen=True, slots=True)
class PinState:
    failed_tries: int = 0
    locked: bool = False
    last_outcome: PinOutcome | None = None


def _as_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(name, "must be a timezone-aware datetime")
    return value.astimezone(UTC)


def code_attempt(state: CodeState, entered_ok: bool, now: datetime) -> CodeState:
    """Judge one entry of a text code. Expiry is checked first, then the try limit."""
    now_utc = _as_utc(now, "now")
    issued_utc = _as_utc(state.issued_at, "issued_at")
    if state.verified or now_utc < issued_utc or now_utc >= issued_utc + CODE_VALID_FOR:
        return replace(state, last_outcome=CodeOutcome.EXPIRED)
    if state.failed_tries >= CODE_MAX_TRIES:
        return replace(state, last_outcome=CodeOutcome.TOO_MANY_TRIES)
    if entered_ok:
        return replace(state, verified=True, last_outcome=CodeOutcome.VERIFIED)
    tries = state.failed_tries + 1
    outcome = CodeOutcome.TOO_MANY_TRIES if tries >= CODE_MAX_TRIES else CodeOutcome.WRONG
    return replace(state, failed_tries=tries, last_outcome=outcome)


def can_resend(last_sent_at: datetime, now: datetime) -> bool:
    """A new code may be sent once CODE_RESEND_AFTER has passed. A future send time refuses."""
    elapsed = _as_utc(now, "now") - _as_utc(last_sent_at, "last_sent_at")
    return elapsed >= CODE_RESEND_AFTER


def pin_attempt(state: PinState, ok: bool, now: datetime) -> PinState:
    """Judge one PIN entry. A locked PIN stays locked until reset_pin_state (a text code)."""
    _as_utc(now, "now")
    if state.locked:
        return replace(state, last_outcome=PinOutcome.LOCKED)
    if ok:
        return PinState(failed_tries=0, locked=False, last_outcome=PinOutcome.OK)
    tries = state.failed_tries + 1
    if tries >= PIN_MAX_TRIES:
        return PinState(failed_tries=tries, locked=True, last_outcome=PinOutcome.LOCKED)
    return PinState(failed_tries=tries, locked=False, last_outcome=PinOutcome.WRONG)


def reset_pin_state() -> PinState:
    """Called after a text code is verified: clears the try count and the lock."""
    return PinState()


_PURPOSE: Final = re.compile(r"[a-z][a-z0-9-]{0,31}")


def check_purpose(purpose: str) -> str:
    """A text code's purpose: a plain lower-case name of up to 32 characters (letters, digits and
    hyphen). It is part of the code's key, so a colon or a space is refused. Returns the name."""
    if not isinstance(purpose, str) or _PURPOSE.fullmatch(purpose) is None:
        raise ValidationFailed("purpose", "must be a lower-case name of up to 32 characters")
    return purpose


def validate_pin_format(pin: str) -> None:
    """Refuse anything but exactly six ASCII digits. The message never repeats the value."""
    if len(pin) != PIN_LENGTH or any(c not in _ASCII_DIGITS for c in pin):
        raise ValidationFailed("pin", "must be exactly 6 ASCII digits")


def needs_reverification(
    last_verified_at: datetime | None,
    now: datetime,
    device_known: bool,
    policy: TenantPolicy = DEFAULT_POLICY,  # RED STUB
) -> bool:
    """True when the caller must ask for a text code: new device, never verified, or 30 days old."""
    now_utc = _as_utc(now, "now")
    if not device_known or last_verified_at is None:
        return True
    last_utc = _as_utc(last_verified_at, "last_verified_at")
    if last_utc > now_utc:
        return True
    return now_utc - last_utc >= REVERIFY_EVERY
