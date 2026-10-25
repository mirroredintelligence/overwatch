"""Link tokens, wall-screen pairing codes and support codes (D26).

Rule: docs/spec/domain-rules.md section 7.

DEC-010 stub for the red commit: names and shapes only. Every function raises NotImplementedError.
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

PAIRING_CODE_VALID_FOR: Final = timedelta(minutes=10)
SUPPORT_CODE_ALPHABET: Final = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


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


def new_link_token(rng: Callable[[int], bytes] = secrets.token_bytes) -> str:
    raise NotImplementedError


def hash_token(token: str, secret: bytes) -> str:
    raise NotImplementedError


def check_link(record: LinkTokenRecord, now: datetime) -> LinkCheck:
    raise NotImplementedError


def new_pairing_code(rng: Callable[[int], int] = secrets.randbelow) -> str:
    raise NotImplementedError


def format_pairing_code(code: str) -> str:
    raise NotImplementedError


def pairing_code_expired(issued_at: datetime, now: datetime) -> bool:
    raise NotImplementedError


def new_support_code(rng: Callable[[int], int] = secrets.randbelow) -> str:
    raise NotImplementedError
