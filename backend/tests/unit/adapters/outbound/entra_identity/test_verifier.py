"""The Entra verifier (TEN-043): every refusal, and the identity it accepts. No network: the signing
keys are served by an in-memory transport, and the tokens are signed here with a test key."""

import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from diucs.adapters.outbound.entra_identity.verifier import (
    AUTHORITY,
    COMMON_KEYS_URL,
    EntraConfig,
    EntraIdentityVerifier,
)
from diucs.application.ports.outbound.identity_verifier import (
    Audience,
    IdentityRejected,
    VerifiedIdentity,
)

STAFF_CLIENT = "7fb43bde-6a6d-4aed-9cac-9118de48ab52"
OPERATOR_CLIENT = "9b4e9144-358a-47cc-9ffb-e63bf0d21c41"
OPERATOR_DIRECTORY = "c5901e0b-8d43-4ae8-97c3-ca6c52573a33"
OTHER_TENANT = "11111111-2222-4333-8444-555555555555"
USER = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
GROUP = "66666666-7777-4888-8999-000000000000"
KID = "test-key-1"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks(*keys: rsa.RSAPrivateKey) -> dict[str, object]:
    entries = []
    for index, key in enumerate(keys):
        entry = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        entry["kid"] = KID if index == 0 else f"{KID}-{index}"
        entry["use"] = "sig"
        entries.append(entry)
    return {"keys": entries}


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def _claims(
    tenant: str = OTHER_TENANT, audience: str = STAFF_CLIENT, **extra: object
) -> dict[str, object]:
    issued = int(time.time())
    base: dict[str, object] = {
        "aud": audience,
        "iss": f"{AUTHORITY}/{tenant}/v2.0",
        "tid": tenant,
        "oid": USER,
        "iat": issued,
        "nbf": issued,
        "exp": issued + 3600,
        "groups": [GROUP],
        "roles": ["Reporter"],
    }
    base.update(extra)
    return base


def _token(claims: dict[str, object], key: rsa.RSAPrivateKey = _KEY, kid: str = KID) -> str:
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def _verifier(
    jwks: dict[str, object], clock: _Clock | None = None, fetches: list[str] | None = None
) -> EntraIdentityVerifier:
    def handler(request: httpx.Request) -> httpx.Response:
        if fetches is not None:
            fetches.append(str(request.url))
        return httpx.Response(200, json=jwks)

    config = EntraConfig(
        staff_client_id=STAFF_CLIENT,
        operator_client_id=OPERATOR_CLIENT,
        operator_directory_id=OPERATOR_DIRECTORY,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return EntraIdentityVerifier(config, client, clock or _Clock())


async def test_a_staff_token_yields_its_identity_groups_and_roles() -> None:
    token = _token(_claims(tenant=OTHER_TENANT))

    identity = await _verifier(_jwks(_KEY)).verify(token, Audience.STAFF)

    assert identity == VerifiedIdentity(
        directory_id=OTHER_TENANT,
        object_id=USER,
        group_ids=frozenset({GROUP}),
        app_roles=frozenset({"Reporter"}),
    )


async def test_an_operator_token_from_the_operator_directory_is_accepted() -> None:
    token = _token(_claims(tenant=OPERATOR_DIRECTORY, audience=OPERATOR_CLIENT))
    keys_url = f"{AUTHORITY}/{OPERATOR_DIRECTORY}/discovery/v2.0/keys"

    fetches: list[str] = []
    identity = await _verifier(_jwks(_KEY), fetches=fetches).verify(token, Audience.OPERATOR)

    assert identity.directory_id == OPERATOR_DIRECTORY
    assert fetches == [keys_url]


async def test_an_operator_token_from_another_directory_is_refused() -> None:
    token = _token(_claims(tenant=OTHER_TENANT, audience=OPERATOR_CLIENT))

    with pytest.raises(IdentityRejected):
        await _verifier(_jwks(_KEY)).verify(token, Audience.OPERATOR)


async def test_a_staff_token_presented_to_the_operator_door_is_refused() -> None:
    token = _token(_claims(tenant=OPERATOR_DIRECTORY, audience=STAFF_CLIENT))

    with pytest.raises(IdentityRejected):
        await _verifier(_jwks(_KEY)).verify(token, Audience.OPERATOR)


async def test_the_wrong_audience_is_refused() -> None:
    token = _token(_claims(audience="22222222-3333-4444-8555-666666666666"))

    with pytest.raises(IdentityRejected):
        await _verifier(_jwks(_KEY)).verify(token, Audience.STAFF)


async def test_an_issuer_that_does_not_match_the_token_tenant_is_refused() -> None:
    claims = _claims(tenant=OTHER_TENANT)
    claims["iss"] = f"{AUTHORITY}/{OPERATOR_DIRECTORY}/v2.0"

    with pytest.raises(IdentityRejected):
        await _verifier(_jwks(_KEY)).verify(_token(claims), Audience.STAFF)


async def test_an_expired_token_is_refused() -> None:
    claims = _claims()
    claims["exp"] = int(time.time()) - 3600
    claims["iat"] = int(time.time()) - 7200

    with pytest.raises(IdentityRejected):
        await _verifier(_jwks(_KEY)).verify(_token(claims), Audience.STAFF)


async def test_a_token_signed_with_another_key_under_the_same_kid_is_refused() -> None:
    token = _token(_claims(), key=_OTHER_KEY)

    with pytest.raises(IdentityRejected):
        await _verifier(_jwks(_KEY)).verify(token, Audience.STAFF)


async def test_a_symmetric_algorithm_is_refused() -> None:
    token = jwt.encode(_claims(), "x" * 32, algorithm="HS256", headers={"kid": KID})

    with pytest.raises(IdentityRejected):
        await _verifier(_jwks(_KEY)).verify(token, Audience.STAFF)


async def test_an_unsigned_token_is_refused() -> None:
    token = jwt.encode(_claims(), key=None, algorithm="none")

    with pytest.raises(IdentityRejected):
        await _verifier(_jwks(_KEY)).verify(token, Audience.STAFF)


async def test_text_that_is_not_a_token_is_refused() -> None:
    for garbage in ("", "not a token", "a.b.c", "x" * 40):
        with pytest.raises(IdentityRejected):
            await _verifier(_jwks(_KEY)).verify(garbage, Audience.STAFF)


async def test_a_token_missing_its_object_id_is_refused() -> None:
    claims = _claims()
    del claims["oid"]

    with pytest.raises(IdentityRejected):
        await _verifier(_jwks(_KEY)).verify(_token(claims), Audience.STAFF)


async def test_an_overage_token_is_refused_because_its_groups_cannot_be_read() -> None:
    claims = _claims()
    del claims["groups"]
    claims["_claim_names"] = {"groups": "src1"}
    claims["_claim_sources"] = {"src1": {"endpoint": "https://graph.example"}}

    with pytest.raises(IdentityRejected):
        await _verifier(_jwks(_KEY)).verify(_token(claims), Audience.STAFF)


async def test_a_group_that_is_not_a_guid_is_refused() -> None:
    claims = _claims(groups=["not-a-guid"])

    with pytest.raises(IdentityRejected):
        await _verifier(_jwks(_KEY)).verify(_token(claims), Audience.STAFF)


async def test_an_unknown_kid_refetches_at_most_every_five_minutes() -> None:
    clock = _Clock()
    fetches: list[str] = []
    verifier = _verifier(_jwks(_KEY), clock=clock, fetches=fetches)
    token = _token(_claims(), kid="never-published")

    with pytest.raises(IdentityRejected):
        await verifier.verify(token, Audience.STAFF)
    assert fetches == [COMMON_KEYS_URL]

    clock.now += 60
    with pytest.raises(IdentityRejected):
        await verifier.verify(token, Audience.STAFF)
    assert len(fetches) == 1, "within five minutes the key set is not fetched again"

    clock.now += 300
    with pytest.raises(IdentityRejected):
        await verifier.verify(token, Audience.STAFF)
    assert len(fetches) == 2


async def test_a_directory_that_cannot_be_reached_is_an_outage_not_a_refusal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    config = EntraConfig(
        staff_client_id=STAFF_CLIENT,
        operator_client_id=OPERATOR_CLIENT,
        operator_directory_id=OPERATOR_DIRECTORY,
    )
    verifier = EntraIdentityVerifier(
        config, httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    with pytest.raises(httpx.HTTPStatusError):
        await verifier.verify(_token(_claims()), Audience.STAFF)


async def test_the_identity_does_not_show_its_fields() -> None:
    identity = await _verifier(_jwks(_KEY)).verify(_token(_claims()), Audience.STAFF)

    assert USER not in repr(identity)
    assert USER not in str(identity)
