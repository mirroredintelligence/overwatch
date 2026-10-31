"""Outbound adapter: verifies a Microsoft Entra ID sign-in (TEN-043, DEC-522).

The credential is the ID token the person signed in with. It is verified here, against the
directory's published signing keys, before the back end issues a token of its own. The checks are
the ones the provider's own guidance gives for a token that carries an `aud` and an `iss`:

- the signature, with RS256 only and a key the directory published under the token's `kid`;
- the audience, which is the app registration of the door the sign-in is for (the staff app or the
  operator console);
- the issuer, which must be the issuer of the token's own `tid` (the directory it was issued by);
- the expiry and issue time, with a minute of clock skew, and the presence of `oid` and `tid`.

The operator console is a single directory: its token must come from `operator_directory_id`. The
staff app is multi-tenant, so any directory may sign in and the tenant rules are applied elsewhere
(the exchange decides which directory may hold which tenant). A token whose groups are not in the
token (the provider's "overage" marker: more groups than the token can carry) is refused, because
the roles cannot be read from it.

Not checked here: the nonce. The port takes no nonce, so the caller cannot pass the one it issued.
A token replayed within its lifetime is accepted (the same residual as the rest of the sign-in
path).

Refusals are `IdentityRejected` with no detail. A failure to reach the directory is not a refusal:
it is raised as it is, so a caller can tell an outage from a bad credential.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import httpx
import jwt
from jwt import PyJWK, PyJWKSet
from jwt.exceptions import InvalidTokenError

from overwatch.application.ports.outbound.identity_verifier import (
    Audience,
    IdentityRejected,
    VerifiedIdentity,
)
from overwatch.domain.errors import ValidationFailed

AUTHORITY: Final = "https://login.microsoftonline.com"
COMMON_KEYS_URL: Final = f"{AUTHORITY}/common/discovery/v2.0/keys"
ALGORITHM: Final = "RS256"
LEEWAY_SECONDS: Final = 60
KEY_CACHE_SECONDS: Final = 3600.0
# A key the directory did not publish under a token's kid is looked up again, at most this often.
KEY_REFRESH_SECONDS: Final = 300.0
FETCH_TIMEOUT_SECONDS: Final = 5.0
REQUIRED_CLAIMS: Final = ("exp", "iat", "aud", "iss", "tid", "oid")
OVERAGE_CLAIM: Final = "groups"


@dataclass(frozen=True, slots=True)
class EntraConfig:
    """The app registrations this verifier accepts tokens for. All three are GUIDs (the staff and
    operator client ids are the audiences; the operator directory is the one tenant it trusts)."""

    staff_client_id: str
    operator_client_id: str
    operator_directory_id: str


def _issuer(tenant_id: str) -> str:
    return f"{AUTHORITY}/{tenant_id}/v2.0"


def _find_key(keys: PyJWKSet, kid: str) -> PyJWK | None:
    for key in keys.keys:
        if key.key_id == kid:
            return key
    return None


class EntraIdentityVerifier:
    """Verifies an ID token for one of the two doors. Signing keys are cached per directory
    (an hour), and a key missing for a token's `kid` is fetched again at most every five minutes."""

    def __init__(
        self,
        config: EntraConfig,
        http: httpx.AsyncClient,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._http = http
        self._clock = clock
        self._keys: dict[str, tuple[float, PyJWKSet]] = {}

    async def verify(self, credential: str, audience: Audience) -> VerifiedIdentity:
        if type(credential) is not str or not credential:
            raise IdentityRejected
        try:
            header = jwt.get_unverified_header(credential)
        except InvalidTokenError:
            raise IdentityRejected from None
        kid = header.get("kid")
        if header.get("alg") != ALGORITHM or type(kid) is not str:
            raise IdentityRejected

        if audience is Audience.OPERATOR:
            keys_url = f"{AUTHORITY}/{self._config.operator_directory_id}/discovery/v2.0/keys"
            client_id = self._config.operator_client_id
        else:
            keys_url = COMMON_KEYS_URL
            client_id = self._config.staff_client_id

        key = await self._signing_key(keys_url, kid)
        if key is None:
            raise IdentityRejected
        try:
            claims = jwt.decode(
                credential,
                key=key.key,
                algorithms=[ALGORITHM],
                audience=client_id,
                leeway=LEEWAY_SECONDS,
                options={"require": list(REQUIRED_CLAIMS), "verify_iss": False},
            )
        except InvalidTokenError:
            raise IdentityRejected from None
        return self._identity(claims, audience)

    def _identity(self, claims: dict[str, object], audience: Audience) -> VerifiedIdentity:
        tenant_id = claims.get("tid")
        issuer = claims.get("iss")
        if type(tenant_id) is not str or type(issuer) is not str or issuer != _issuer(tenant_id):
            raise IdentityRejected
        if (
            audience is Audience.OPERATOR
            and tenant_id.lower() != self._config.operator_directory_id.lower()
        ):
            raise IdentityRejected
        # Overage: the token names its groups by a link instead of listing them, so they cannot
        # be read.
        if OVERAGE_CLAIM in _claim_names(claims):
            raise IdentityRejected
        groups = _texts(claims.get("groups", []))
        roles = _texts(claims.get("roles", []))
        try:
            return VerifiedIdentity(
                directory_id=tenant_id,
                object_id=str(claims["oid"]),
                group_ids=frozenset(groups),
                app_roles=frozenset(roles),
            )
        except ValidationFailed:
            raise IdentityRejected from None

    async def _signing_key(self, keys_url: str, kid: str) -> PyJWK | None:
        keys = await self._load(keys_url, refresh=False)
        found = _find_key(keys, kid)
        if found is None and self._age(keys_url) >= KEY_REFRESH_SECONDS:
            keys = await self._load(keys_url, refresh=True)
            found = _find_key(keys, kid)
        return found

    def _age(self, keys_url: str) -> float:
        cached = self._keys.get(keys_url)
        return float("inf") if cached is None else self._clock() - cached[0]

    async def _load(self, keys_url: str, *, refresh: bool) -> PyJWKSet:
        cached = self._keys.get(keys_url)
        if cached is not None and not refresh and self._clock() - cached[0] < KEY_CACHE_SECONDS:
            return cached[1]
        response = await self._http.get(keys_url, timeout=FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
        keys = PyJWKSet.from_dict(response.json())
        self._keys[keys_url] = (self._clock(), keys)
        return keys


def _claim_names(claims: dict[str, object]) -> dict[str, object]:
    names = claims.get("_claim_names")
    return names if isinstance(names, dict) else {}


def _texts(value: object) -> list[str]:
    """The claim as a list of text, or a refusal: a claim of any other shape is not read."""
    if not isinstance(value, list) or not all(type(item) is str for item in value):
        raise IdentityRejected
    return [str(item) for item in value]
