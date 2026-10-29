"""Integration tests for the link-token service (P10): issue, resolve and burn, against the real
Neo4j token store. Each step commits in its own transaction and reads back in a fresh session.
Synthetic values only: no patient data, no real phone number."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.link_token_repository import Neo4jLinkTokenRepository
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.tokens import LinkTokenService
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.rules.tokens import LinkTokenRecord, hash_token
from tests.support.neo4j import count_nodes, read_tx, write_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET = b"link-token-test-secret-0123456789abcdef"
OTHER_SECRET = b"another-secret-0123456789abcdef0"
NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
EXPIRES = NOW + timedelta(minutes=30)
PHONE_HASH = "ab" * 32


def _service(tx: AsyncManagedTransaction, clock: FixedClock, secret: bytes) -> LinkTokenService:
    repo = Neo4jLinkTokenRepository(tx)
    return LinkTokenService(repo, FixedSecretStore({"link-token": secret}), clock)


async def _in_write(
    driver: AsyncDriver,
    clock: FixedClock,
    action: Callable[[LinkTokenService], Awaitable[str | None]],
    secret: bytes = SECRET,
) -> str | None:
    async def work(tx: AsyncManagedTransaction) -> str | None:
        return await action(_service(tx, clock, secret))

    return await write_tx(driver, work)


async def _resolve(
    driver: AsyncDriver, clock: FixedClock, token: str, secret: bytes = SECRET
) -> LinkTokenRecord | None:
    async def work(tx: AsyncManagedTransaction) -> LinkTokenRecord | None:
        return await _service(tx, clock, secret).resolve(token)

    return await read_tx(driver, work)


async def _issue(driver: AsyncDriver, clock: FixedClock, expires_at: datetime = EXPIRES) -> str:
    async def action(service: LinkTokenService) -> str:
        return await service.issue("booking-reply", "svc-1", PHONE_HASH, expires_at)

    token = await _in_write(driver, clock, action)
    assert token is not None
    return token


async def _burn(driver: AsyncDriver, clock: FixedClock, token: str, key: str = "req-1") -> None:
    async def action(service: LinkTokenService) -> None:
        await service.burn(token, key)

    await _in_write(driver, clock, action)


async def _every_node_text(driver: AsyncDriver) -> str:
    async def work(tx: AsyncManagedTransaction) -> str:
        rows = await (await tx.run("MATCH (n) RETURN properties(n) AS props")).data()
        return " ".join(str(row["props"]) for row in rows)

    return await read_tx(driver, work)


async def test_issue_returns_a_23_letter_token_and_stores_only_its_hash(
    neo4j_driver: AsyncDriver,
) -> None:
    clock = FixedClock(NOW)
    token = await _issue(neo4j_driver, clock)
    assert len(token) == 23
    stored = await _resolve(neo4j_driver, clock, token)
    assert stored is not None
    assert stored.token_hash == hash_token(token, SECRET)


async def test_the_token_text_is_in_no_stored_property(neo4j_driver: AsyncDriver) -> None:
    clock = FixedClock(NOW)
    token = await _issue(neo4j_driver, clock)
    assert token not in await _every_node_text(neo4j_driver)


async def test_resolve_returns_the_issued_record(neo4j_driver: AsyncDriver) -> None:
    clock = FixedClock(NOW)
    token = await _issue(neo4j_driver, clock)
    stored = await _resolve(neo4j_driver, clock, token)
    assert stored == LinkTokenRecord(
        token_hash=hash_token(token, SECRET),
        purpose="booking-reply",
        about_id="svc-1",
        phone_hash=PHONE_HASH,
        expires_at=EXPIRES,
        used_at=None,
    )


async def test_resolve_of_an_unknown_token_is_none(neo4j_driver: AsyncDriver) -> None:
    clock = FixedClock(NOW)
    assert await _resolve(neo4j_driver, clock, "unknown") is None


async def test_resolve_of_a_malformed_token_is_none(neo4j_driver: AsyncDriver) -> None:
    clock = FixedClock(NOW)
    assert await _resolve(neo4j_driver, clock, "not a token!") is None


async def test_burn_marks_the_link_used_at_the_clock_time(neo4j_driver: AsyncDriver) -> None:
    clock = FixedClock(NOW)
    token = await _issue(neo4j_driver, clock)
    later = NOW + timedelta(minutes=2)
    clock.set(later)
    await _burn(neo4j_driver, clock, token)
    stored = await _resolve(neo4j_driver, clock, token)
    assert stored is not None
    assert stored.used_at == later


async def test_a_second_burn_with_another_key_is_a_conflict_and_changes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    clock = FixedClock(NOW)
    token = await _issue(neo4j_driver, clock)
    first = NOW + timedelta(minutes=2)
    clock.set(first)
    await _burn(neo4j_driver, clock, token, key="req-1")
    clock.set(NOW + timedelta(minutes=3))
    with pytest.raises(Conflict):
        await _burn(neo4j_driver, clock, token, key="req-2")
    stored = await _resolve(neo4j_driver, clock, token)
    assert stored is not None
    assert stored.used_at == first


async def test_a_retried_burn_with_the_same_key_returns_the_original_result_without_a_write(
    neo4j_driver: AsyncDriver,
) -> None:
    """A caller whose burn committed but whose reply was lost retries with the same key. The
    retry must succeed, and it must not write again (DEC-012, the P15 replay pattern)."""
    clock = FixedClock(NOW)
    token = await _issue(neo4j_driver, clock)
    first = NOW + timedelta(minutes=2)
    clock.set(first)
    await _burn(neo4j_driver, clock, token, key="req-1")
    clock.set(NOW + timedelta(minutes=5))
    await _burn(neo4j_driver, clock, token, key="req-1")
    stored = await _resolve(neo4j_driver, clock, token)
    assert stored is not None
    assert stored.used_at == first
    assert await count_nodes(neo4j_driver, "LinkToken") == 1


async def test_burning_an_unknown_token_is_not_found_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    clock = FixedClock(NOW)
    with pytest.raises(NotFound):
        await _burn(neo4j_driver, clock, "unknown-token-value")
    assert await count_nodes(neo4j_driver, "LinkToken") == 0


async def test_a_different_secret_does_not_resolve_the_token(neo4j_driver: AsyncDriver) -> None:
    clock = FixedClock(NOW)
    token = await _issue(neo4j_driver, clock)
    assert await _resolve(neo4j_driver, clock, token, secret=OTHER_SECRET) is None


async def test_a_refused_issue_leaves_zero_nodes(neo4j_driver: AsyncDriver) -> None:
    clock = FixedClock(NOW)
    naive = datetime(2026, 10, 25, 9, 30)
    with pytest.raises(ValidationFailed):
        await _issue(neo4j_driver, clock, expires_at=naive)
    assert await count_nodes(neo4j_driver, "LinkToken") == 0


async def test_burning_malformed_text_is_not_found_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    clock = FixedClock(NOW)
    await _issue(neo4j_driver, clock)
    with pytest.raises(NotFound):
        await _burn(neo4j_driver, clock, "not a token!")
    assert await count_nodes(neo4j_driver, "LinkToken") == 1


async def test_an_empty_secret_is_refused_and_never_used_as_a_key(
    neo4j_driver: AsyncDriver,
) -> None:
    clock = FixedClock(NOW)
    token = await _issue(neo4j_driver, clock)
    with pytest.raises(ValidationFailed, match="secret"):
        await _resolve(neo4j_driver, clock, token, secret=b"")
