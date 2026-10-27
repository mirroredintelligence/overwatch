"""Bearer tokens from the BFF: HS256 JWTs, checked here (R02, DEC-094).

Rule: docs/plan/prompts/R02.md ("Rules you need"). The token carries `sub`, `role`, `services`,
an optional `device`, and `exp`. Every check is in this module and the refusal is one fixed error.

Pure: no I/O and no clock. The caller passes `now` and the secret as bytes.
A TokenRejected message is fixed words, so it never repeats the token, the secret or a claim.
"""

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from diucs.domain.codes import Role
from diucs.domain.errors import DomainError, ValidationFailed

BFF_TOKEN_ALGORITHM: Final = "HS256"
BFF_SECRET_MIN_BYTES: Final = 32  # 256 bits, the output size of HMAC-SHA256 (DEC-094 item 3)
BFF_TOKEN_MAX_LENGTH: Final = (
    8192  # characters; a longer token is refused before it is parsed (DEC-094 item 2)
)

_BASE64URL: Final = re.compile(r"[A-Za-z0-9_-]*")


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
    _check_secret(secret)
    _check_aware(claims.expires_at, "expires_at")
    body: dict[str, Any] = {
        "sub": claims.sub,
        "role": claims.role.value,
        "services": sorted(claims.services),
        "exp": int(claims.expires_at.timestamp()),
    }
    if claims.device is not None:
        body["device"] = claims.device
    signing_input = f"{_json_b64(_header())}.{_json_b64(body)}"
    return f"{signing_input}.{_b64url_encode(_sign(signing_input, secret))}"


def decode_bff_token(token: str, secret: bytes, now: datetime) -> BffClaims:
    _check_secret(secret)
    _check_aware(now, "now")
    if len(token) > BFF_TOKEN_MAX_LENGTH or not token.isascii():
        raise TokenRejected()
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenRejected()
    head_part, body_part, signature_part = parts
    header = _json_object(_b64url_decode(head_part))
    if header.get("alg") != BFF_TOKEN_ALGORITHM:
        raise TokenRejected()
    if not hmac.compare_digest(
        _sign(f"{head_part}.{body_part}", secret), _b64url_decode(signature_part)
    ):
        raise TokenRejected()
    return _claims(_json_object(_b64url_decode(body_part)), now)


def _header() -> dict[str, str]:
    return {"alg": BFF_TOKEN_ALGORITHM, "typ": "JWT"}


def _check_secret(secret: bytes) -> None:
    if len(secret) < BFF_SECRET_MIN_BYTES:
        raise ValueError("the BFF token secret is shorter than 32 bytes")


def _check_aware(instant: datetime, field: str) -> None:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValidationFailed(field, "must be timezone-aware")


def _sign(signing_input: str, secret: bytes) -> bytes:
    return hmac.new(secret, signing_input.encode("ascii"), hashlib.sha256).digest()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _json_b64(value: dict[str, Any]) -> str:
    return _b64url_encode(json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _b64url_decode(part: str) -> bytes:
    if _BASE64URL.fullmatch(part) is None:
        raise TokenRejected()
    padded = part + "=" * (-len(part) % 4)
    try:
        return base64.urlsafe_b64decode(padded)
    except ValueError:
        raise TokenRejected() from None


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except ValueError, RecursionError:
        raise TokenRejected() from None
    if not isinstance(value, dict):
        raise TokenRejected()
    return value


def _claims(body: dict[str, Any], now: datetime) -> BffClaims:
    exp = body.get("exp")
    if not isinstance(exp, int) or isinstance(exp, bool):
        raise TokenRejected()
    if now.timestamp() >= exp:
        raise TokenRejected()
    try:
        expires_at = datetime.fromtimestamp(exp, UTC)
    except OverflowError, OSError, ValueError:
        raise TokenRejected() from None
    sub = body.get("sub")
    if not isinstance(sub, str) or not sub:
        raise TokenRejected()
    role_text = body.get("role")
    if not isinstance(role_text, str):
        raise TokenRejected()
    try:
        role = Role(role_text)
    except ValueError:
        raise TokenRejected() from None
    services = body.get("services")
    if not isinstance(services, list) or not all(isinstance(item, str) for item in services):
        raise TokenRejected()
    device = body.get("device")
    if device is not None and (not isinstance(device, str) or not device):
        raise TokenRejected()
    return BffClaims(
        sub=sub,
        role=role,
        services=frozenset(services),
        expires_at=expires_at,
        device=device,
    )
