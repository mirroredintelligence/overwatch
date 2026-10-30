"""Back-end bearer tokens: HS256 JWTs, issued and checked here (R02, DEC-094, TEN-043).

Rule: docs/plan/prompts/R02.md ("Rules you need"). The token carries `sub`, `role`, `services`,
`tenant`, `epoch`, an optional `device`, and `exp`. Every check is in this module and the refusal is
one fixed error.

The tenant claim is the only source of the tenant at the REST edge (DEC-130 item 6, TEN-018): a
token without one, or with one that is not a tenant id (a network id, the platform id, a list), is
refused. The epoch is the tenant record's counter when the token was issued: the edge refuses a
token whose epoch the record has moved past, so a suspend takes effect before `exp` (H-T23).

A token is for one audience (TEN-043, DEC-522). The back end issues every token, and the BFF holds
no signing secret (DEC-134 item 2). A tenant token (staff, reporter, wall) is for `diucs-api` and
names a tenant and its epoch; an operator token (an operator or a support person of the operator's
own directory) is for `diucs-ops` and names no tenant, epoch, service or device. Each decoder
refuses the other's token and refuses a token with no audience or with any other: a signature that
verifies is not enough.

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
from diucs.domain.model.tenant import check_tenant_id

BFF_TOKEN_ALGORITHM: Final = "HS256"
BFF_SECRET_MIN_BYTES: Final = 32  # 256 bits, the output size of HMAC-SHA256 (DEC-094 item 3)
BFF_TOKEN_MAX_LENGTH: Final = (
    8192  # characters; a longer token is refused before it is parsed (DEC-094 item 2)
)

STAFF_AUDIENCE: Final = "diucs-api"
OPERATOR_AUDIENCE: Final = "diucs-ops"
# The roles an operator token may carry: tenant lifecycle and support, never a tenant's own role.
OPERATOR_ROLES: Final = frozenset({Role.PLATFORM_OPERATOR, Role.SUPPORT})

# An epoch counts suspends, resumes and role-mapping changes: far below this, and a bound keeps the
# claim a number every JSON reader holds exactly.
EPOCH_MAX: Final = 10**9

_BASE64URL: Final = re.compile(r"[A-Za-z0-9_-]*")


@dataclass(frozen=True, slots=True)
class BffClaims:
    sub: str
    role: Role
    services: frozenset[str]
    expires_at: datetime
    tenant: str
    epoch: int
    device: str | None = None


@dataclass(frozen=True, slots=True)
class OperatorClaims:
    """An operator or support person of the operator's own directory (TEN-043). No tenant: access
    to one tenant is a separate, audited act (TEN-084)."""

    sub: str
    role: Role
    expires_at: datetime


class TokenRejected(DomainError):
    """The bearer token is malformed, unsigned, badly signed, expired or has bad claims. The message
    is fixed and never repeats the token."""

    def __init__(self) -> None:
        super().__init__("bearer token is not valid")


def encode_bff_token(claims: BffClaims, secret: bytes) -> str:
    _check_secret(secret)
    _check_aware(claims.expires_at, "expires_at")
    check_tenant_id(claims.tenant)
    if not _is_epoch(claims.epoch):
        raise ValidationFailed("epoch", "must be a whole number from 1")
    body: dict[str, Any] = {
        "sub": claims.sub,
        "role": claims.role.value,
        "services": sorted(claims.services),
        "tenant": claims.tenant,
        "epoch": claims.epoch,
        "aud": STAFF_AUDIENCE,
        "exp": int(claims.expires_at.timestamp()),
    }
    if claims.device is not None:
        body["device"] = claims.device
    return _sealed(body, secret)


def decode_bff_token(token: str, secret: bytes, now: datetime) -> BffClaims:
    return _claims(_verified_body(token, secret, now, STAFF_AUDIENCE), now)


def encode_operator_token(claims: OperatorClaims, secret: bytes) -> str:
    _check_secret(secret)
    _check_aware(claims.expires_at, "expires_at")
    if type(claims.role) is not Role or claims.role not in OPERATOR_ROLES:
        raise ValidationFailed("role", "is not an operator role")
    if type(claims.sub) is not str or not claims.sub:
        raise ValidationFailed("sub", "must be non-empty text")
    body: dict[str, Any] = {
        "sub": claims.sub,
        "role": claims.role.value,
        "aud": OPERATOR_AUDIENCE,
        "exp": int(claims.expires_at.timestamp()),
    }
    return _sealed(body, secret)


def decode_operator_token(token: str, secret: bytes, now: datetime) -> OperatorClaims:
    return _operator_claims(_verified_body(token, secret, now, OPERATOR_AUDIENCE), now)


def _sealed(body: dict[str, Any], secret: bytes) -> str:
    signing_input = f"{_json_b64(_header())}.{_json_b64(body)}"
    return f"{signing_input}.{_b64url_encode(_sign(signing_input, secret))}"


def _verified_body(token: str, secret: bytes, now: datetime, audience: str) -> dict[str, Any]:
    """The payload of a token whose shape, algorithm, signature and audience are right. The
    signature is compared in constant time before the payload is parsed, and the audience is
    judged before any claim is read, so a token for the other door is refused whole."""
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
    body = _json_object(_b64url_decode(body_part))
    if type(body.get("aud")) is not str or body["aud"] != audience:
        raise TokenRejected()
    return body


def _header() -> dict[str, str]:
    return {"alg": BFF_TOKEN_ALGORITHM, "typ": "JWT"}


def _is_epoch(value: object) -> bool:
    return type(value) is int and 1 <= value <= EPOCH_MAX


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


def _expiry(body: dict[str, Any], now: datetime) -> datetime:
    """The expiry the payload names, when it is a whole number of seconds that has not come."""
    exp = body.get("exp")
    if not isinstance(exp, int) or isinstance(exp, bool):
        raise TokenRejected()
    if now.timestamp() >= exp:
        raise TokenRejected()
    try:
        return datetime.fromtimestamp(exp, UTC)
    except OverflowError, OSError, ValueError:
        raise TokenRejected() from None


def _operator_claims(body: dict[str, Any], now: datetime) -> OperatorClaims:
    expires_at = _expiry(body, now)
    # An operator token names no tenant, epoch, service or device: one that does is for the tenant
    # door and is refused here whole.
    if set(body) - {"sub", "role", "aud", "exp"}:
        raise TokenRejected()
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
    if role not in OPERATOR_ROLES:
        raise TokenRejected()
    return OperatorClaims(sub=sub, role=role, expires_at=expires_at)


def _claims(body: dict[str, Any], now: datetime) -> BffClaims:
    expires_at = _expiry(body, now)
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
    tenant = body.get("tenant")
    try:
        check_tenant_id(tenant)
    except ValidationFailed:
        raise TokenRejected() from None
    epoch = body.get("epoch")
    if type(epoch) is not int or not _is_epoch(epoch):
        raise TokenRejected()
    return BffClaims(
        sub=sub,
        role=role,
        services=frozenset(services),
        expires_at=expires_at,
        tenant=str(tenant),
        epoch=epoch,
        device=device,
    )
