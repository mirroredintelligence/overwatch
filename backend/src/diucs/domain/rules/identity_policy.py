"""Identity policy for reporters and COO or ICB users: text codes, PINs and re-verification (D27).

Rules: docs/spec/domain-rules.md section 7 and the D27 prompt. Pure: no I/O and no clock. `now`
is an argument. The PIN itself never enters this module. Stub only, for the red commit (DEC-010).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

CODE_VALID_FOR: Final = timedelta(minutes=10)
CODE_MAX_TRIES: Final = 5
CODE_RESEND_AFTER: Final = timedelta(seconds=60)
PIN_MAX_TRIES: Final = 5
REVERIFY_EVERY: Final = timedelta(days=30)


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


def code_attempt(state: CodeState, entered_ok: bool, now: datetime) -> CodeState:
    raise NotImplementedError


def can_resend(last_sent_at: datetime, now: datetime) -> bool:
    raise NotImplementedError


def pin_attempt(state: PinState, ok: bool, now: datetime) -> PinState:
    raise NotImplementedError


def reset_pin_state() -> PinState:
    raise NotImplementedError


def validate_pin_format(pin: str) -> None:
    raise NotImplementedError


def needs_reverification(last_verified_at: datetime | None, now: datetime, device_known: bool) -> bool:
    raise NotImplementedError
