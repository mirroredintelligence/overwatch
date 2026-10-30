"""The `networks` claim of the BFF token (TEN-059, DEC-548, DEC-132 item 4).

The claim is a hint that routes: it tells the edge and the page that a network view exists for the
signed-in person's tenant. It is never the authority (the registry is, on every request), so a
token that omits it, or carries a stale one, is harmless. It is still a signed claim, so it is
checked as strictly as the others: a list of network ids, a small number of them, nothing else.
Tokens are built with the standard library, so the tests do not reuse the code under test.
"""

import base64
import hashlib
import hmac
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.domain.codes import Role
from diucs.domain.rules.bff_token import (
    NETWORKS_MAX,
    BffClaims,
    TokenRejected,
    decode_bff_token,
    encode_bff_token,
)

SECRET = b"synthetic-secret-for-unit-tests-zyxwvutsrqabcdef"
NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
EXPIRES = datetime(2026, 10, 24, 13, 12, tzinfo=UTC)
CLAIMS = BffClaims(
    sub="prac-1",
    role=Role.ADVISOR,
    services=frozenset(),
    expires_at=EXPIRES,
    tenant="tenant-a",
    epoch=1,
)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _token(**changes: Any) -> str:
    body: dict[str, Any] = {
        "sub": "prac-1",
        "role": "advisor",
        "services": [],
        "tenant": "tenant-a",
        "epoch": 1,
        "exp": int(EXPIRES.timestamp()),
    }
    body.update(changes)
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps(body).encode())
    signature = hmac.new(SECRET, f"{head}.{payload}".encode(), hashlib.sha256).digest()
    return f"{head}.{payload}.{_b64(signature)}"


def test_a_token_with_no_networks_claim_has_no_networks() -> None:
    assert decode_bff_token(_token(), SECRET, NOW).networks == frozenset()
    assert CLAIMS.networks == frozenset()


def test_the_claim_round_trips_and_is_sorted_on_the_wire() -> None:
    claims = replace(CLAIMS, networks=frozenset({"net-pilot", "net-alpha"}))
    token = encode_bff_token(claims, SECRET)
    assert decode_bff_token(token, SECRET, NOW) == claims
    body = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert body["networks"] == ["net-alpha", "net-pilot"]


def test_a_token_without_networks_is_unchanged_on_the_wire() -> None:
    body = json.loads(
        base64.urlsafe_b64decode(encode_bff_token(CLAIMS, SECRET).split(".")[1] + "==")
    )
    assert "networks" not in body


def test_the_claim_is_signed_with_the_rest() -> None:
    token = _token(networks=["net-pilot"])
    head, payload, signature = token.split(".")
    forged = _b64(
        json.dumps(
            {**json.loads(base64.urlsafe_b64decode(payload + "==")), "networks": ["net-x"]}
        ).encode()
    )
    with pytest.raises(TokenRejected):
        decode_bff_token(f"{head}.{forged}.{signature}", SECRET, NOW)


@pytest.mark.parametrize(
    "value",
    [
        "net-pilot",
        {"net-pilot": True},
        7,
        ["tenant-a"],
        ["net-"],
        ["net-bad id"],
        ["Net-Pilot"],
        [7],
        [None],
        [["net-pilot"]],
        ["net-pilot", "tenant-a"],
        [f"net-{index}" for index in range(NETWORKS_MAX + 1)],
    ],
)
def test_a_networks_claim_that_is_not_a_short_list_of_network_ids_is_refused(value: Any) -> None:
    with pytest.raises(TokenRejected):
        decode_bff_token(_token(networks=value), SECRET, NOW)


def test_the_largest_allowed_list_is_accepted() -> None:
    ids = [f"net-{index}" for index in range(NETWORKS_MAX)]
    assert len(decode_bff_token(_token(networks=ids), SECRET, NOW).networks) == NETWORKS_MAX


def test_a_null_claim_is_the_same_as_none() -> None:
    assert decode_bff_token(_token(networks=None), SECRET, NOW).networks == frozenset()
