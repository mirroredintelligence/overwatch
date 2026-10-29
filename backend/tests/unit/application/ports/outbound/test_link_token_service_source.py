"""LinkTokenService draws its token from an injectable random source (link-token privacy fix).

The default is the system source (`secrets.token_bytes`). A test passes its own, to force a
particular 128 bits through the real `issue` path.
"""

import secrets
from datetime import UTC, datetime
from typing import Final

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, LinkTokenService
from diucs.domain.rules.tokens import LinkTokenRecord, hash_token, new_link_token

SECRET: Final = b"link-token-test-secret-0123456789abcdef"
NOW: Final = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


class _Repo:
    def __init__(self) -> None:
        self.added: list[LinkTokenRecord] = []

    async def add(self, record: LinkTokenRecord) -> None:
        self.added.append(record)


def _service(repo: _Repo, **kwargs: object) -> LinkTokenService:
    return LinkTokenService(
        repo,  # type: ignore[arg-type]
        FixedSecretStore({LINK_TOKEN_SECRET: SECRET}),
        FixedClock(NOW),
        **kwargs,  # type: ignore[arg-type]
    )


async def test_issue_draws_the_token_from_the_injected_source() -> None:
    repo = _Repo()
    raw = bytes(range(16))
    token = await _service(repo, rng=lambda n: raw).issue("p", "a", None, NOW)
    assert token == new_link_token(lambda n: raw)
    assert repo.added[0].token_hash == hash_token(token, SECRET)


async def test_the_default_source_is_the_system_source() -> None:
    repo = _Repo()
    service = _service(repo)
    first = await service.issue("p", "a", None, NOW)
    second = await service.issue("p", "a", None, NOW)
    assert first != second
    assert len(first) == 23
    assert service._rng is secrets.token_bytes  # noqa: SLF001 (the default is the CSPRNG)
