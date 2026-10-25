"""Outbound ports and the service for single-use link tokens (P10, D26, domain-rules 7).

Stub for the red commit (DEC-010): every method raises NotImplementedError until the green commit.
"""

from datetime import datetime
from typing import Protocol

from diucs.application.ports.outbound.clock import Clock
from diucs.domain.rules.tokens import LinkTokenRecord


class LinkTokenRepository(Protocol):
    async def add(self, record: LinkTokenRecord) -> None: ...

    async def get_by_hash(self, token_hash: str) -> LinkTokenRecord | None: ...

    async def mark_used(self, token_hash: str, at: datetime) -> bool: ...


class SecretStore(Protocol):
    def get(self, name: str) -> bytes: ...


class LinkTokenService:
    def __init__(self, repo: LinkTokenRepository, secrets: SecretStore, clock: Clock) -> None:
        self._repo = repo
        self._secrets = secrets
        self._clock = clock

    async def issue(
        self, purpose: str, about_id: str, phone_hash: str | None, expires_at: datetime
    ) -> str:
        raise NotImplementedError

    async def resolve(self, token: str) -> LinkTokenRecord | None:
        raise NotImplementedError

    async def burn(self, token: str) -> None:
        raise NotImplementedError
