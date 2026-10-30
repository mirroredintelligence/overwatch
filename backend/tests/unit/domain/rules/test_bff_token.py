"""BFF bearer tokens (R02, DEC-094): HS256 signature, expiry at the given instant, typed claims.

Tokens here are built with the standard library, so the tests do not reuse the code under test.
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
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.bff_token import (
    BFF_SECRET_MIN_BYTES,
    BFF_TOKEN_MAX_LENGTH,
    BffClaims,
    TokenRejected,
    decode_bff_token,
    encode_bff_token,
)

SECRET = b"synthetic-secret-for-unit-tests-zyxwvutsrqabcdef"
OTHER_SECRET = b"another-synthetic-secret-for-unit-tests-zyxwvutsrq"
NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
EXPIRES = datetime(2026, 10, 24, 13, 12, tzinfo=UTC)
TENANT = "tenant-a"
CLAIMS = BffClaims(
    sub="prac-1",
    role=Role.REPORTER,
    services=frozenset({"svc-1"}),
    expires_at=EXPIRES,
    tenant=TENANT,
    epoch=1,
)
HEADER: dict[str, Any] = {"alg": "HS256", "typ": "JWT"}


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign(header: Any, payload: Any, secret: bytes = SECRET, digest: str = "sha256") -> str:
    head = b64(json.dumps(header, separators=(",", ":")).encode())
    body = b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(secret, f"{head}.{body}".encode("ascii"), getattr(hashlib, digest))
    return f"{head}.{body}.{b64(signature.digest())}"


def payload(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "sub": "prac-1",
        "role": "reporter",
        "services": ["svc-1"],
        "tenant": TENANT,
        "epoch": 1,
        "aud": "diucs-api",
        "exp": int(EXPIRES.timestamp()),
    }
    for key, value in changes.items():
        if value is ...:
            del base[key]
        else:
            base[key] = value
    return base


def valid_token(**changes: Any) -> str:
    return sign(HEADER, payload(**changes))


def test_a_token_gives_back_its_claims() -> None:
    token = encode_bff_token(CLAIMS, SECRET)

    assert decode_bff_token(token, SECRET, NOW) == CLAIMS


def test_a_wall_token_keeps_its_device_claim() -> None:
    claims = BffClaims(
        sub="dev-1",
        role=Role.WALL,
        services=frozenset(),
        expires_at=EXPIRES,
        tenant=TENANT,
        epoch=1,
        device="dev-1",
    )

    assert decode_bff_token(encode_bff_token(claims, SECRET), SECRET, NOW) == claims


def test_a_token_with_no_services_is_valid() -> None:
    claims = decode_bff_token(valid_token(services=[]), SECRET, NOW)

    assert claims.services == frozenset()


@pytest.mark.parametrize(
    ("instant", "accepted"),
    [
        pytest.param(EXPIRES - timedelta(seconds=1), True, id="one-second-before-expiry"),
        pytest.param(EXPIRES, False, id="at-the-expiry-instant"),
        pytest.param(EXPIRES + timedelta(seconds=1), False, id="after-expiry"),
    ],
)
def test_expiry_is_judged_at_the_instant_given(instant: datetime, accepted: bool) -> None:
    token = encode_bff_token(CLAIMS, SECRET)

    if accepted:
        assert decode_bff_token(token, SECRET, instant) == CLAIMS
    else:
        with pytest.raises(TokenRejected):
            decode_bff_token(token, SECRET, instant)


def test_a_token_signed_with_another_secret_is_refused() -> None:
    token = encode_bff_token(CLAIMS, OTHER_SECRET)

    with pytest.raises(TokenRejected):
        decode_bff_token(token, SECRET, NOW)


def test_a_changed_claim_under_the_old_signature_is_refused() -> None:
    head, _, signature = valid_token().split(".")
    escalated = b64(json.dumps(payload(role="owner"), separators=(",", ":")).encode())

    with pytest.raises(TokenRejected):
        decode_bff_token(f"{head}.{escalated}.{signature}", SECRET, NOW)


def test_an_unsigned_token_is_refused() -> None:
    head = b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = b64(json.dumps(payload()).encode())

    with pytest.raises(TokenRejected):
        decode_bff_token(f"{head}.{body}.", SECRET, NOW)


def test_a_token_signed_with_another_algorithm_is_refused() -> None:
    token = sign({"alg": "HS512", "typ": "JWT"}, payload(), digest="sha512")

    with pytest.raises(TokenRejected):
        decode_bff_token(token, SECRET, NOW)


def _with_padding(token: str) -> str:
    return token + "="


MALFORMED = [
    pytest.param("", id="empty"),
    pytest.param("not-a-token", id="no-dots"),
    pytest.param("a.b", id="two-parts"),
    pytest.param("a.b.c.d", id="four-parts"),
    pytest.param("aaa.bbb.cccé", id="non-ascii"),
    pytest.param(_with_padding(valid_token()), id="base64-padding"),
    pytest.param("!!!." + valid_token().split(".", 1)[1], id="header-not-base64"),
    pytest.param("abcde.abc.abc", id="base64-impossible-length"),
    pytest.param(sign(HEADER, [1, 2]), id="payload-is-a-list"),
    pytest.param(sign(["HS256"], payload()), id="header-is-a-list"),
    pytest.param(valid_token(sub=...), id="sub-missing"),
    pytest.param(valid_token(sub=""), id="sub-empty"),
    pytest.param(valid_token(sub=7), id="sub-not-text"),
    pytest.param(valid_token(role="owner-of-everything"), id="role-unknown"),
    pytest.param(valid_token(role=...), id="role-missing"),
    pytest.param(valid_token(services=...), id="services-missing"),
    pytest.param(valid_token(services="svc-1"), id="services-not-a-list"),
    pytest.param(valid_token(services=[1]), id="services-not-text"),
    pytest.param(valid_token(device=7), id="device-not-text"),
    pytest.param(valid_token(device=""), id="device-empty"),
    pytest.param(valid_token(exp=...), id="expiry-missing"),
    pytest.param(valid_token(exp=True), id="expiry-is-a-boolean"),
    pytest.param(valid_token(exp=1.5), id="expiry-is-a-fraction"),
    pytest.param(valid_token(exp=10**20), id="expiry-beyond-any-date"),
    pytest.param(valid_token(tenant=...), id="tenant-missing"),
    pytest.param(valid_token(tenant=None), id="tenant-null"),
    pytest.param(valid_token(tenant=""), id="tenant-empty"),
    pytest.param(valid_token(tenant=7), id="tenant-not-text"),
    pytest.param(valid_token(tenant=["tenant-a"]), id="tenant-a-list"),
    pytest.param(valid_token(tenant="Tenant-A"), id="tenant-upper-case"),
    pytest.param(valid_token(tenant="t"), id="tenant-one-character"),
    pytest.param(valid_token(tenant="t" * 32), id="tenant-too-long"),
    pytest.param(valid_token(tenant="tenant a"), id="tenant-with-a-space"),
    pytest.param(valid_token(tenant="tenant:a"), id="tenant-with-a-colon"),
    pytest.param(valid_token(tenant="tenant/a"), id="tenant-with-a-slash"),
    pytest.param(valid_token(tenant="tenant-a\n"), id="tenant-with-a-newline"),
    pytest.param(valid_token(tenant="net-dorset"), id="tenant-is-a-network-id"),
    pytest.param(valid_token(tenant="platform"), id="tenant-is-the-platform-scope"),
    pytest.param(valid_token(epoch=...), id="epoch-missing"),
    pytest.param(valid_token(epoch=None), id="epoch-null"),
    pytest.param(valid_token(epoch=True), id="epoch-is-a-boolean"),
    pytest.param(valid_token(epoch=0), id="epoch-zero"),
    pytest.param(valid_token(epoch=-1), id="epoch-negative"),
    pytest.param(valid_token(epoch=1.5), id="epoch-is-a-fraction"),
    pytest.param(valid_token(epoch="1"), id="epoch-is-text"),
    pytest.param(valid_token(epoch=10**12), id="epoch-beyond-any-count"),
]


@pytest.mark.parametrize("token", MALFORMED)
def test_a_malformed_or_badly_claimed_token_is_refused(token: str) -> None:
    with pytest.raises(TokenRejected):
        decode_bff_token(token, SECRET, NOW)


def test_a_header_naming_another_algorithm_is_refused_even_when_the_signature_matches() -> None:
    # HMAC-SHA256 over the input, so only the header's alg claim is wrong.
    token = sign({"alg": "HS512", "typ": "JWT"}, payload(), digest="sha256")

    with pytest.raises(TokenRejected):
        decode_bff_token(token, SECRET, NOW)


def test_an_oversized_but_correctly_signed_token_is_refused() -> None:
    token = valid_token(services=[f"svc-{n:05d}" for n in range(1000)])
    assert len(token) > BFF_TOKEN_MAX_LENGTH

    with pytest.raises(TokenRejected):
        decode_bff_token(token, SECRET, NOW)


def test_an_oversized_token_is_refused_before_it_is_parsed() -> None:
    oversized = "x" * (BFF_TOKEN_MAX_LENGTH + 1)

    with pytest.raises(TokenRejected):
        decode_bff_token(oversized, SECRET, NOW)


def test_a_deeply_nested_signed_payload_is_refused_not_raised() -> None:
    # Nested far past the JSON parser's recursion limit, but under the token length limit, and
    # correctly signed, so only the parser can refuse it.
    head = b64(json.dumps(HEADER, separators=(",", ":")).encode())
    body = b64(b"[" * 2000 + b"]" * 2000)
    signature = hmac.new(SECRET, f"{head}.{body}".encode("ascii"), hashlib.sha256).digest()
    token = f"{head}.{body}.{b64(signature)}"
    assert len(token) < BFF_TOKEN_MAX_LENGTH

    with pytest.raises(TokenRejected):
        decode_bff_token(token, SECRET, NOW)


def test_a_payload_that_is_not_json_is_refused() -> None:
    head = b64(json.dumps(HEADER, separators=(",", ":")).encode())
    body = b64(b"not json at all")
    signature = hmac.new(SECRET, f"{head}.{body}".encode("ascii"), hashlib.sha256).digest()

    with pytest.raises(TokenRejected):
        decode_bff_token(f"{head}.{body}.{b64(signature)}", SECRET, NOW)


def test_a_json_parser_that_hits_its_recursion_limit_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def hits_the_limit(raw: object) -> object:
        raise RecursionError

    monkeypatch.setattr(json, "loads", hits_the_limit)

    with pytest.raises(TokenRejected):
        decode_bff_token(valid_token(), SECRET, NOW)


def test_the_refusal_message_never_repeats_the_token_or_the_secret() -> None:
    token = valid_token(sub="")

    with pytest.raises(TokenRejected) as refused:
        decode_bff_token(token, SECRET, NOW)

    message = str(refused.value)
    assert message == "bearer token is not valid"
    assert token not in message
    assert SECRET.decode() not in message


def test_a_naive_instant_is_refused() -> None:
    token = encode_bff_token(CLAIMS, SECRET)

    with pytest.raises(ValidationFailed):
        decode_bff_token(token, SECRET, datetime(2026, 10, 23, 13, 12))


def test_a_naive_expiry_is_refused_when_encoding() -> None:
    claims = replace(CLAIMS, expires_at=datetime(2026, 10, 24, 13, 12))

    with pytest.raises(ValidationFailed):
        encode_bff_token(claims, SECRET)


def test_a_short_secret_is_refused_when_encoding() -> None:
    short = b"x" * (BFF_SECRET_MIN_BYTES - 1)

    with pytest.raises(ValueError, match="secret"):
        encode_bff_token(CLAIMS, short)


def test_a_short_secret_is_refused_when_decoding() -> None:
    token = encode_bff_token(CLAIMS, SECRET)
    short = b"x" * (BFF_SECRET_MIN_BYTES - 1)

    with pytest.raises(ValueError, match="secret"):
        decode_bff_token(token, short, NOW)


_TEXT = st.text(alphabet="abcdefghijklmnopqrstuvwxyzzyxwvutsrq-", min_size=1, max_size=12)


_TENANTS = st.from_regex(r"[a-z0-9][a-z0-9-]{1,30}", fullmatch=True).filter(
    lambda text: not text.startswith("net-") and text != "platform"
)


@given(
    sub=_TEXT,
    role=st.sampled_from(list(Role)),
    services=st.frozensets(_TEXT, max_size=5),
    device=st.none() | _TEXT,
    tenant=_TENANTS,
    epoch=st.integers(min_value=1, max_value=10**9),
)
def test_any_claims_come_back_unchanged(
    sub: str,
    role: Role,
    services: frozenset[str],
    device: str | None,
    tenant: str,
    epoch: int,
) -> None:
    claims = BffClaims(
        sub=sub,
        role=role,
        services=services,
        expires_at=EXPIRES,
        tenant=tenant,
        epoch=epoch,
        device=device,
    )

    assert decode_bff_token(encode_bff_token(claims, SECRET), SECRET, NOW) == claims


@given(junk=st.text(max_size=200))
def test_any_text_is_refused_with_the_one_rejection(junk: str) -> None:
    with pytest.raises(TokenRejected):
        decode_bff_token(junk, SECRET, NOW)


# ---------------------------------------------------------------- the tenant claim (TEN-018)


def test_a_token_gives_back_its_tenant_and_epoch() -> None:
    claims = decode_bff_token(valid_token(tenant="example-icb", epoch=7), SECRET, NOW)

    assert claims.tenant == "example-icb"
    assert claims.epoch == 7


def test_the_encoded_token_carries_the_tenant_and_epoch_as_claims() -> None:
    token = encode_bff_token(replace(CLAIMS, tenant="example-icb", epoch=3), SECRET)

    body = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert body["tenant"] == "example-icb"
    assert body["epoch"] == 3


def test_a_changed_tenant_under_the_old_signature_is_refused() -> None:
    head, _, signature = valid_token().split(".")
    moved = b64(json.dumps(payload(tenant="tenant-b"), separators=(",", ":")).encode())

    with pytest.raises(TokenRejected):
        decode_bff_token(f"{head}.{moved}.{signature}", SECRET, NOW)


def test_a_token_names_exactly_one_tenant() -> None:
    # A list, a second claim under another name, or a network claim is no tenant at all.
    with pytest.raises(TokenRejected):
        decode_bff_token(valid_token(tenant=["tenant-a", "tenant-b"]), SECRET, NOW)
    claims = decode_bff_token(valid_token(networks=["net-dorset"], tid="tenant-b"), SECRET, NOW)
    assert claims.tenant == TENANT


@pytest.mark.parametrize("role", ["tenant-admin", "network-admin", "platform-operator"])
def test_the_administration_roles_are_carried(role: str) -> None:
    claims = decode_bff_token(valid_token(role=role), SECRET, NOW)

    assert claims.role.value == role


@pytest.mark.parametrize(
    "tenant", ["", "Tenant-A", "t", "net-dorset", "platform", "tenant a", "t" * 32, "a:b"]
)
def test_encoding_refuses_a_tenant_that_decoding_would_refuse(tenant: str) -> None:
    with pytest.raises(ValidationFailed):
        encode_bff_token(replace(CLAIMS, tenant=tenant), SECRET)


@pytest.mark.parametrize("epoch", [0, -1, 10**12])
def test_encoding_refuses_an_epoch_that_decoding_would_refuse(epoch: int) -> None:
    with pytest.raises(ValidationFailed):
        encode_bff_token(replace(CLAIMS, epoch=epoch), SECRET)


def test_encoding_refuses_a_boolean_epoch() -> None:
    with pytest.raises(ValidationFailed):
        encode_bff_token(replace(CLAIMS, epoch=True), SECRET)


def test_a_tenant_refusal_is_the_one_fixed_rejection_with_no_value() -> None:
    with pytest.raises(TokenRejected) as refused:
        decode_bff_token(valid_token(tenant="Secret-Tenant"), SECRET, NOW)

    assert str(refused.value) == "bearer token is not valid"
