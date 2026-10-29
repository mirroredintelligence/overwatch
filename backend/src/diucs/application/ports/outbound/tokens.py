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


class SecretStore(Protocol):
    def get(self, name: str) -> bytes: ...


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
