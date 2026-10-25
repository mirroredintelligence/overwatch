"""Link tokens, wall-screen pairing codes and support codes (D26).

Rule: docs/spec/domain-rules.md section 7.

Pure: no I/O and no clock. Randomness is a parameter (default: the secrets module, which is a
cryptographically secure source), and every time is an argument, so tests are deterministic.

- A link token is 128 bits, base64url without padding (22 characters). Only its keyed hash
  (HMAC-SHA256, hex) is stored. A link is used once; used takes precedence over expired.
- A pairing code is six digits, drawn one digit at a time from ten values, so every code is equally
  likely. It is shown as "482 913" and valid for ten minutes.
- A support code is eight characters from SUPPORT_CODE_ALPHABET, shown as XXXX-XXXX.

Errors name the field and never echo a token, code or secret (a ValidationFailed message is data
for logs). Instants are compared in UTC, so the London clock change cannot make them wrong (DEC-039
item 7, lesson L52).
"""

import base64
import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

from diucs.domain.errors import ValidationFailed

PAIRING_CODE_VALID_FOR: Final = timedelta(minutes=10)
SUPPORT_CODE_ALPHABET: Final = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

LINK_TOKEN_BYTES: Final = 16  # 128 bits, the minimum in domain-rules 7
PAIRING_CODE_DIGITS: Final = 6
PAIRING_DIGIT_CHOICES: Final = 10
SUPPORT_CODE_LENGTH: Final = 8
SUPPORT_CODE_GROUP: Final = 4

_URL_SAFE_TOKEN: Final = re.compile(r"[A-Za-z0-9_-]+")
_PAIRING_CODE: Final = re.compile(r"[0-9]{6}")


class LinkCheck(StrEnum):
    OK = "ok"
    EXPIRED = "expired"
    USED = "used"


@dataclass(frozen=True, slots=True)
class LinkTokenRecord:
    token_hash: str
    purpose: str
    about_id: str
    phone_hash: str | None
    expires_at: datetime
    used_at: datetime | None

    def __post_init__(self) -> None:
        check_phone_hash(self.phone_hash)
        _utc(self.expires_at, "expires_at")
        if self.used_at is not None:
            _utc(self.used_at, "used_at")


_PHONE_HASH: Final = re.compile(r"[0-9a-f]{64}")


def check_phone_hash(value: str | None) -> None:
    """Refuse anything in the phone field that is not a 64-character lower-case hex digest. A phone
    number, a name or a postcode must never reach a stored record (H-09, DEC-047). The message
    never echoes the value."""
    if value is None:
        return
    if not isinstance(value, str) or not _PHONE_HASH.fullmatch(value):
        raise ValidationFailed("phone_hash", "must be a 64-character lower-case hex digest")


def _utc(moment: datetime, field: str) -> datetime:
    """Return the instant in UTC. A naive or non-datetime value is refused by field name."""
    if not isinstance(moment, datetime) or moment.utcoffset() is None:
        raise ValidationFailed(field, "must be a timezone-aware datetime")
    return moment.astimezone(UTC)


def new_link_token(rng: Callable[[int], bytes] = secrets.token_bytes) -> str:
    raw = rng(LINK_TOKEN_BYTES)
    if not isinstance(raw, bytes) or len(raw) != LINK_TOKEN_BYTES:
        raise ValidationFailed("token", "the random source must give exactly 128 bits")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def hash_token(token: str, secret: bytes) -> str:
    if not isinstance(token, str) or not _URL_SAFE_TOKEN.fullmatch(token):
        raise ValidationFailed("token", "must be URL-safe text")
    if not isinstance(secret, bytes) or not secret:
        raise ValidationFailed("secret", "must be non-empty bytes")
    return hmac.new(secret, token.encode("ascii"), hashlib.sha256).hexdigest()


def check_link(record: LinkTokenRecord, now: datetime) -> LinkCheck:
    current = _utc(now, "now")
    if record.used_at is not None:
        return LinkCheck.USED
    if current >= _utc(record.expires_at, "expires_at"):
        return LinkCheck.EXPIRED
    return LinkCheck.OK


def new_pairing_code(rng: Callable[[int], int] = secrets.randbelow) -> str:
    digits: list[str] = []
    for _ in range(PAIRING_CODE_DIGITS):
        digit = rng(PAIRING_DIGIT_CHOICES)
        if type(digit) is not int or not 0 <= digit < PAIRING_DIGIT_CHOICES:
            raise ValidationFailed("code", "each digit must be an int from 0 to 9")
        digits.append(str(digit))
    return "".join(digits)


def format_pairing_code(code: str) -> str:
    if not isinstance(code, str) or not _PAIRING_CODE.fullmatch(code):
        raise ValidationFailed("code", "must be six digits")
    return f"{code[:3]} {code[3:]}"


def pairing_code_expired(issued_at: datetime, now: datetime) -> bool:
    issued = _utc(issued_at, "issued_at")
    current = _utc(now, "now")
    if issued > current:
        raise ValidationFailed("issued_at", "is later than now")
    return current - issued >= PAIRING_CODE_VALID_FOR


def new_support_code(rng: Callable[[int], int] = secrets.randbelow) -> str:
    chars: list[str] = []
    for _ in range(SUPPORT_CODE_LENGTH):
        index = rng(len(SUPPORT_CODE_ALPHABET))
        if type(index) is not int or not 0 <= index < len(SUPPORT_CODE_ALPHABET):
            raise ValidationFailed("code", "index is outside the support alphabet")
        chars.append(SUPPORT_CODE_ALPHABET[index])
    code = "".join(chars)
    return f"{code[:SUPPORT_CODE_GROUP]}-{code[SUPPORT_CODE_GROUP:]}"
