"""Bearer tokens from the BFF: HS256 JWTs, checked here (R02, DEC-094).

Rule: docs/plan/prompts/R02.md ("Rules you need"). The token carries `sub`, `role`, `services`,
an optional `device`, and `exp`. Every check is in this module and the refusal is one fixed error.

Pure: no I/O and no clock. The caller passes `now` and the secret as bytes.
A TokenRejected message is fixed words, so it never repeats the token, the secret or a claim.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.domain.codes import Role
from diucs.domain.errors import DomainError

BFF_TOKEN_ALGORITHM: Final = "HS256"
BFF_SECRET_MIN_BYTES: Final = 32  # 256 bits, the output size of HMAC-SHA256 (DEC-094 item 3)
BFF_TOKEN_MAX_LENGTH: Final = (
    8192  # characters; a longer token is refused before it is parsed (DEC-094 item 2)
)


@dataclass(frozen=True, slots=True)
class BffClaims:
    sub: str
    role: Role
    services: frozenset[str]
    expires_at: datetime
    device: str | None = None


class TokenRejected(DomainError):
    """The bearer token is malformed, unsigned, badly signed, expired or has bad claims. The message
    is fixed and never repeats the token."""

    def __init__(self) -> None:
        super().__init__("bearer token is not valid")


def encode_bff_token(claims: BffClaims, secret: bytes) -> str:
    raise NotImplementedError("encode_bff_token is a DEC-094 red stub")


def decode_bff_token(token: str, secret: bytes, now: datetime) -> BffClaims:
    raise NotImplementedError("decode_bff_token is a DEC-094 red stub")
