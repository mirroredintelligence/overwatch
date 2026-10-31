"""Outbound ports and the service for single-use link tokens (P10, D26, domain-rules 7).

Only the keyed hash of a token is stored (HMAC-SHA256 with the secret `link-token`). The token
text is returned once, to the caller that issued it, and never reaches the database or a log.
Decisions: DEC-057.
"""

from collections.abc import Callable
from datetime import datetime
from secrets import token_bytes
from typing import Final, Protocol

from diucs.application.ports.outbound.clock import Clock
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.rules.tokens import LinkTokenRecord, hash_token, new_link_token

LINK_TOKEN_SECRET: Final = "link-token"


class LinkTokenRepository(Protocol):
    async def add(self, record: LinkTokenRecord) -> None: ...

    async def get_by_hash(self, token_hash: str) -> LinkTokenRecord | None: ...

    async def mark_used(self, token_hash: str, at: datetime, key: str) -> bool: ...

    async def burn_key(self, token_hash: str) -> str | None: ...

    async def open_for_phone(
        self, purpose: str, phone_hash: str, now: datetime
    ) -> LinkTokenRecord | None:
        """The link of this purpose held by this phone hash that is unused and not expired at
        `now`, or None (U25: an open invitation). Only the bound tenant's links are seen."""
        ...

    async def open_for_about(
        self, purpose: str, about_id: str, now: datetime
    ) -> LinkTokenRecord | None:
        """The link of this purpose about this id that is unused and not expired at `now`, or None
        (U24: the link of one invitation, so a resend burns that link and no other). When several
        are open, the one that expires last. Only the bound tenant's links are seen."""
        ...


class SecretStoreUnavailable(Exception):
    """A secret exists or may exist but could not be read now: the vault is down, refused the
    identity or throttled, or a file could not be opened (DEC-1304 item 4). It is deliberately not
    `NotFound` and not a `DomainError`: no caller may read it as "not configured" and carry on with
    a default, and no edge may turn it into a 4xx. Every caller of `SecretStore.get` handles
    `NotFound` and nothing else, so this passes through and the request or the message fails
    closed (a 500, or a retry of the message). The text names the secret and never a value."""


class SecretStore(Protocol):
    def get(self, name: str) -> bytes:
        """The secret's bytes. `NotFound` when it is not held (or the name is not a valid one);
        `SecretStoreUnavailable` when it could not be read now."""
        ...


class LinkTokenService:
    def __init__(
        self,
        repo: LinkTokenRepository,
        secrets: SecretStore,
        clock: Clock,
        rng: Callable[[int], bytes] = token_bytes,
    ) -> None:
        """`rng` gives the random bytes of a token: the system source by default. A test passes its
        own to force particular bits through `issue`."""
        self._repo = repo
        self._secrets = secrets
        self._clock = clock
        self._rng = rng

    async def issue(
        self, purpose: str, about_id: str, phone_hash: str | None, expires_at: datetime
    ) -> str:
        """Create a token, store its hash and return the token text once. A record that breaks a
        rule (for example a naive expiry) is refused before anything is written."""
        token = new_link_token(self._rng)
        record = LinkTokenRecord(
            token_hash=hash_token(token, self._secrets.get(LINK_TOKEN_SECRET)),
            purpose=purpose,
            about_id=about_id,
            phone_hash=phone_hash,
            expires_at=expires_at,
            used_at=None,
        )
        await self._repo.add(record)
        return token

    async def resolve(self, token: str) -> LinkTokenRecord | None:
        """Return the stored record for a token, or None. Text that cannot be a token is not
        found, so a malformed link is treated like an unknown one."""
        token_hash = self._hash_or_none(token)
        if token_hash is None:
            return None
        return await self._repo.get_by_hash(token_hash)

    async def burn(self, token: str, key: str) -> None:
        """Mark a token used, for the attempt identified by `key`. A replay with the same key (a
        retry after a lost reply) returns without writing again. A different key for a token
        already used is Conflict; unknown or malformed text is NotFound. The expiry is not checked
        here: the caller checks check_link first."""
        token_hash = self._hash_or_none(token)
        if token_hash is None:
            raise NotFound("link token")
        if await self._repo.mark_used(token_hash, self._clock.now(), key):
            return
        if await self._repo.get_by_hash(token_hash) is None:
            raise NotFound("link token")
        if await self._repo.burn_key(token_hash) == key:
            return
        raise Conflict("link token has already been used")

    def _hash_or_none(self, token: str) -> str | None:
        try:
            return hash_token(token, self._secrets.get(LINK_TOKEN_SECRET))
        except ValidationFailed as error:
            if error.field == "token":
                return None
            raise
