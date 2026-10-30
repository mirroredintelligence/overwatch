"""The audience of a back-end token, and the operator token (TEN-043, DEC-522, DEC-134 item 2).

The back end issues every token (the BFF holds no signing secret), and a token is for one audience:
`diucs-api` for the tenant API (staff, reporter and wall tokens, which name a tenant and its epoch)
and `diucs-ops` for the operator console (an operator or a support person, who names no tenant). A
token for one audience is refused at the other's door, and a token with no audience, or with any
other, is refused at both: a signature that is right is not enough.

Tokens here are forged with the standard library, so the tests do not reuse the code under test.
Every secret and identifier is synthetic.
"""

import base64
import hashlib
import hmac
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.bff_token import (
    BFF_SECRET_MIN_BYTES,
    OPERATOR_AUDIENCE,
    OPERATOR_ROLES,
    STAFF_AUDIENCE,
    BffClaims,
    OperatorClaims,
    TokenRejected,
    decode_bff_token,
    decode_operator_token,
    encode_bff_token,
    encode_operator_token,
)

SECRET = b"synthetic-secret-for-unit-tests-zyxwvutsrqabcdef"
OTHER_SECRET = b"another-synthetic-secret-for-unit-tests-zyxwvutsrq"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
EXPIRES = NOW + timedelta(hours=1)
HEADER: dict[str, Any] = {"alg": "HS256", "typ": "JWT"}
STAFF = BffClaims(
    sub="stf-0123456789abcdef0123456789abcdef",
    role=Role.ADVISOR,
    services=frozenset(),
    expires_at=EXPIRES,
    tenant="tenant-a",
    epoch=3,
)
OPERATOR = OperatorClaims(sub="ref-operator-0123456789", role=Role.SUPPORT, expires_at=EXPIRES)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign(payload: Any, header: Any = HEADER, secret: bytes = SECRET) -> str:
    head = b64(json.dumps(header, separators=(",", ":")).encode())
    body = b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = hmac.new(secret, f"{head}.{body}".encode("ascii"), hashlib.sha256)
    return f"{head}.{body}.{b64(mac.digest())}"


def body_of(token: str) -> dict[str, Any]:
    part = token.split(".")[1]
    decoded: dict[str, Any] = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    return decoded


def staff_payload(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "sub": "stf-1",
        "role": "advisor",
        "services": [],
        "tenant": "tenant-a",
        "epoch": 1,
        "aud": STAFF_AUDIENCE,
        "exp": int(EXPIRES.timestamp()),
    }
    for key, value in changes.items():
        if value is ...:
            del base[key]
        else:
            base[key] = value
    return base


def operator_payload(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "sub": "ref-operator-0123456789",
        "role": "support",
        "aud": OPERATOR_AUDIENCE,
        "exp": int(EXPIRES.timestamp()),
    }
    for key, value in changes.items():
        if value is ...:
            del base[key]
        else:
            base[key] = value
    return base


# ----------------------------------------------------------------------- the two audiences


def test_the_audiences_are_two_fixed_distinct_words() -> None:
    assert STAFF_AUDIENCE == "diucs-api"
    assert OPERATOR_AUDIENCE == "diucs-ops"
    assert STAFF_AUDIENCE != OPERATOR_AUDIENCE


def test_a_tenant_token_names_the_api_audience() -> None:
    assert body_of(encode_bff_token(STAFF, SECRET))["aud"] == STAFF_AUDIENCE


def test_an_operator_token_names_the_operator_audience_and_no_tenant() -> None:
    body = body_of(encode_operator_token(OPERATOR, SECRET))

    assert body["aud"] == OPERATOR_AUDIENCE
    assert set(body) == {"sub", "role", "aud", "exp"}


def test_an_operator_token_gives_back_its_claims() -> None:
    token = encode_operator_token(OPERATOR, SECRET)

    assert decode_operator_token(token, SECRET, NOW) == OPERATOR


@pytest.mark.parametrize("role", sorted(OPERATOR_ROLES, key=lambda r: r.value))
def test_each_operator_role_comes_back_unchanged(role: Role) -> None:
    claims = replace(OPERATOR, role=role)

    assert decode_operator_token(encode_operator_token(claims, SECRET), SECRET, NOW) == claims


def test_the_operator_roles_are_the_platform_operator_and_support_only() -> None:
    assert frozenset({Role.PLATFORM_OPERATOR, Role.SUPPORT}) == OPERATOR_ROLES


# ----------------------------------------------------------------------- audience, negative


@pytest.mark.parametrize(
    "aud",
    [
        pytest.param(..., id="missing"),
        pytest.param(None, id="null"),
        pytest.param("", id="empty"),
        pytest.param(7, id="not-text"),
        pytest.param(["diucs-api"], id="a-list-holding-the-right-word"),
        pytest.param("DIUCS-API", id="upper-case"),
        pytest.param("diucs-api ", id="trailing-space"),
        pytest.param("diucs-ops", id="the-operator-audience"),
        pytest.param("other", id="another-word"),
    ],
)
def test_a_tenant_token_with_no_audience_or_another_is_refused(aud: Any) -> None:
    with pytest.raises(TokenRejected):
        decode_bff_token(sign(staff_payload(aud=aud)), SECRET, NOW)


@pytest.mark.parametrize(
    "aud",
    [
        pytest.param(..., id="missing"),
        pytest.param(None, id="null"),
        pytest.param("", id="empty"),
        pytest.param(7, id="not-text"),
        pytest.param(["diucs-ops"], id="a-list-holding-the-right-word"),
        pytest.param("DIUCS-OPS", id="upper-case"),
        pytest.param("diucs-api", id="the-api-audience"),
        pytest.param("other", id="another-word"),
    ],
)
def test_an_operator_token_with_no_audience_or_another_is_refused(aud: Any) -> None:
    with pytest.raises(TokenRejected):
        decode_operator_token(sign(operator_payload(aud=aud)), SECRET, NOW)


def test_an_operator_token_is_refused_at_the_tenant_door() -> None:
    with pytest.raises(TokenRejected):
        decode_bff_token(encode_operator_token(OPERATOR, SECRET), SECRET, NOW)


def test_a_tenant_token_is_refused_at_the_operator_door() -> None:
    with pytest.raises(TokenRejected):
        decode_operator_token(encode_bff_token(STAFF, SECRET), SECRET, NOW)


def test_an_operator_role_cannot_ride_a_tenant_token_forged_with_the_right_audience() -> None:
    # The audience is right and the signature is right; a tenant token whose role is the operator's
    # still names a tenant and an epoch, and the tenant edge refuses the operator role (TEN-018).
    # What this module guarantees is that the operator decoder will not read it.
    forged = sign(staff_payload(role="support"))

    with pytest.raises(TokenRejected):
        decode_operator_token(forged, SECRET, NOW)


# ----------------------------------------------------------------------- operator claims, negative


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"sub": ...}, id="sub-missing"),
        pytest.param({"sub": ""}, id="sub-empty"),
        pytest.param({"sub": 7}, id="sub-not-text"),
        pytest.param({"role": ...}, id="role-missing"),
        pytest.param({"role": "advisor"}, id="role-of-a-tenant"),
        pytest.param({"role": "tenant-admin"}, id="role-tenant-admin"),
        pytest.param({"role": "wall"}, id="role-wall"),
        pytest.param({"role": "unknown"}, id="role-unknown"),
        pytest.param({"role": 3}, id="role-not-text"),
        pytest.param({"exp": ...}, id="expiry-missing"),
        pytest.param({"exp": True}, id="expiry-is-a-boolean"),
        pytest.param({"exp": 1.5}, id="expiry-is-a-fraction"),
        pytest.param({"tenant": "tenant-a"}, id="names-a-tenant"),
        pytest.param({"tenant": None}, id="names-a-null-tenant"),
        pytest.param({"epoch": 1}, id="carries-an-epoch"),
        pytest.param({"services": ["svc-1"]}, id="carries-services"),
        pytest.param({"device": "dev-1"}, id="carries-a-device"),
    ],
)
def test_a_badly_claimed_operator_token_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(TokenRejected):
        decode_operator_token(sign(operator_payload(**changes)), SECRET, NOW)


@pytest.mark.parametrize(
    ("instant", "accepted"),
    [
        pytest.param(EXPIRES - timedelta(seconds=1), True, id="one-second-before"),
        pytest.param(EXPIRES, False, id="at-the-expiry-instant"),
        pytest.param(EXPIRES + timedelta(seconds=1), False, id="after"),
    ],
)
def test_an_operator_token_expires_at_the_instant_given(instant: datetime, accepted: bool) -> None:
    token = encode_operator_token(OPERATOR, SECRET)

    if accepted:
        assert decode_operator_token(token, SECRET, instant) == OPERATOR
    else:
        with pytest.raises(TokenRejected):
            decode_operator_token(token, SECRET, instant)


def test_an_operator_token_signed_with_another_secret_is_refused() -> None:
    token = encode_operator_token(OPERATOR, OTHER_SECRET)

    with pytest.raises(TokenRejected):
        decode_operator_token(token, SECRET, NOW)


def test_a_changed_operator_claim_under_the_old_signature_is_refused() -> None:
    head, _, signature = encode_operator_token(OPERATOR, SECRET).split(".")
    escalated = b64(json.dumps(operator_payload(role="platform-operator")).encode())

    with pytest.raises(TokenRejected):
        decode_operator_token(f"{head}.{escalated}.{signature}", SECRET, NOW)


def test_an_unsigned_operator_token_is_refused() -> None:
    head = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = b64(json.dumps(operator_payload()).encode())

    with pytest.raises(TokenRejected):
        decode_operator_token(f"{head}.{body}.", SECRET, NOW)


def test_an_operator_token_with_another_algorithm_is_refused() -> None:
    token = sign(operator_payload(), header={"alg": "HS512", "typ": "JWT"})

    with pytest.raises(TokenRejected):
        decode_operator_token(token, SECRET, NOW)


@pytest.mark.parametrize("text", ["", "not-a-token", "a.b", "a.b.c.d", "aaa.bbb.cccé"])
def test_a_malformed_operator_token_is_refused(text: str) -> None:
    with pytest.raises(TokenRejected):
        decode_operator_token(text, SECRET, NOW)


def test_an_oversized_operator_token_is_refused() -> None:
    with pytest.raises(TokenRejected):
        decode_operator_token("x" * 9000, SECRET, NOW)


def test_the_operator_refusal_message_is_fixed() -> None:
    token = sign(operator_payload(sub=""))

    with pytest.raises(TokenRejected) as refused:
        decode_operator_token(token, SECRET, NOW)

    assert str(refused.value) == "bearer token is not valid"
    assert token not in str(refused.value)


# ----------------------------------------------------------------------- operator claims, encoding


@pytest.mark.parametrize("role", [r for r in Role if r not in OPERATOR_ROLES])
def test_an_operator_token_cannot_be_made_with_a_tenant_role(role: Role) -> None:
    with pytest.raises(ValidationFailed):
        encode_operator_token(replace(OPERATOR, role=role), SECRET)


def test_an_operator_token_cannot_be_made_with_an_empty_subject() -> None:
    with pytest.raises(ValidationFailed):
        encode_operator_token(replace(OPERATOR, sub=""), SECRET)


def test_a_naive_operator_expiry_is_refused_when_encoding() -> None:
    with pytest.raises(ValidationFailed):
        encode_operator_token(replace(OPERATOR, expires_at=datetime(2026, 10, 30, 10, 0)), SECRET)


def test_a_naive_instant_is_refused_when_decoding_an_operator_token() -> None:
    with pytest.raises(ValidationFailed):
        decode_operator_token(
            encode_operator_token(OPERATOR, SECRET), SECRET, datetime(2026, 10, 30, 9, 0)
        )


def test_a_short_secret_is_refused_for_an_operator_token() -> None:
    short = b"x" * (BFF_SECRET_MIN_BYTES - 1)

    with pytest.raises(ValueError, match="secret"):
        encode_operator_token(OPERATOR, short)
    with pytest.raises(ValueError, match="secret"):
        decode_operator_token(encode_operator_token(OPERATOR, SECRET), short, NOW)
