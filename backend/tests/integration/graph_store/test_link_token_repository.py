"""Integration tests for the Neo4j link-token store (P10, DEC-004, domain-rules 7).

They run against the throwaway Neo4j the F10 harness starts for the session. Each save commits in
one transaction and each load runs in a fresh session. Synthetic values only: no patient data.
"""

import asyncio
import hashlib
import hmac
from datetime import UTC, datetime, timedelta

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import ClientError

from diucs.adapters.outbound.graph_store.link_token_repository import Neo4jLinkTokenRepository
from diucs.domain.errors import Conflict
from diucs.domain.rules.tokens import LinkTokenRecord, hash_token, new_link_token
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET = b"link-token-test-secret-0123456789abcdef"
TOKEN = new_link_token(rng=lambda n: bytes(range(n)))
EXPIRES = datetime(2026, 10, 25, 12, 30, tzinfo=UTC)
AT = datetime(2026, 10, 25, 11, 0, tzinfo=UTC)
# Independent oracle: HMAC-SHA256 of the normalised number, keyed by the phone-hash secret.
PHONE_HASH = hmac.new(b"p" * 32, b"07700900123", hashlib.sha256).hexdigest()
PROPERTY_NAMES = {"id", "tokenHash", "phoneHash", "purpose", "aboutId", "expiresAt", "usedAt"}


def _record(token: str = TOKEN, used_at: datetime | None = None) -> LinkTokenRecord:
    return LinkTokenRecord(
        token_hash=hash_token(token, SECRET),
        purpose="booking-reply",
        about_id="svc-1",
        phone_hash=PHONE_HASH,
        expires_at=EXPIRES,
        used_at=used_at,
    )


async def _add(driver: AsyncDriver, record: LinkTokenRecord) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jLinkTokenRepository(tx).add(record)

    await write_tx(driver, work)


async def _get(driver: AsyncDriver, token_hash: str) -> LinkTokenRecord | None:
    async def work(tx: AsyncManagedTransaction) -> LinkTokenRecord | None:
        return await Neo4jLinkTokenRepository(tx).get_by_hash(token_hash)

    return await read_tx(driver, work)


async def _mark_used(driver: AsyncDriver, token_hash: str, at: datetime) -> bool:
    async def work(tx: AsyncManagedTransaction) -> bool:
        return await Neo4jLinkTokenRepository(tx).mark_used(token_hash, at)

    return await write_tx(driver, work)


async def test_a_record_round_trips_through_a_fresh_session(neo4j_driver: AsyncDriver) -> None:
    record = _record()
    await assert_round_trip(
        neo4j_driver,
        save=lambda tx: Neo4jLinkTokenRepository(tx).add(record),
        load=lambda tx: Neo4jLinkTokenRepository(tx).get_by_hash(record.token_hash),
        expected=record,
    )


async def test_an_unknown_hash_is_not_found(neo4j_driver: AsyncDriver) -> None:
    assert await _get(neo4j_driver, "f" * 64) is None


async def test_a_second_add_of_the_same_hash_is_a_conflict_and_leaves_one_node(
    neo4j_driver: AsyncDriver,
) -> None:
    await _add(neo4j_driver, _record())
    with pytest.raises(Conflict):
        await _add(neo4j_driver, _record())
    assert await count_nodes(neo4j_driver, "LinkToken") == 1


async def test_the_database_itself_refuses_two_nodes_with_one_hash(
    neo4j_driver: AsyncDriver,
) -> None:
    token_hash = hash_token(TOKEN, SECRET)

    async def create_twice(tx: AsyncManagedTransaction) -> None:
        await tx.run("CREATE (:LinkToken {id: 'first', tokenHash: $h})", h=token_hash)
        await tx.run("CREATE (:LinkToken {id: 'second', tokenHash: $h})", h=token_hash)

    with pytest.raises(ClientError):
        await write_tx(neo4j_driver, create_twice)
    assert await count_nodes(neo4j_driver, "LinkToken") == 0


async def test_mark_used_sets_the_time_once(neo4j_driver: AsyncDriver) -> None:
    record = _record()
    await _add(neo4j_driver, record)
    assert await _mark_used(neo4j_driver, record.token_hash, AT) is True
    stored = await _get(neo4j_driver, record.token_hash)
    assert stored is not None
    assert stored.used_at == AT
    later = AT + timedelta(minutes=1)
    assert await _mark_used(neo4j_driver, record.token_hash, later) is False
    again = await _get(neo4j_driver, record.token_hash)
    assert again is not None
    assert again.used_at == AT


async def test_mark_used_on_an_unknown_hash_is_false_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    assert await _mark_used(neo4j_driver, "e" * 64, AT) is False
    assert await count_nodes(neo4j_driver, "LinkToken") == 0


@pytest.mark.parametrize("round_number", [1, 2, 3])
async def test_concurrent_mark_used_lets_exactly_one_caller_win(
    neo4j_driver: AsyncDriver, round_number: int
) -> None:
    token = new_link_token(rng=lambda n: bytes([round_number] * n))
    record = _record(token)
    await _add(neo4j_driver, record)
    results = await asyncio.gather(
        *(_mark_used(neo4j_driver, record.token_hash, AT) for _ in range(8))
    )
    assert sum(results) == 1, f"{sum(results)} callers were told they burned the link"
    stored = await _get(neo4j_driver, record.token_hash)
    assert stored is not None
    assert stored.used_at == AT


async def test_a_stored_link_token_has_only_the_documented_properties(
    neo4j_driver: AsyncDriver,
) -> None:
    record = _record()
    await _add(neo4j_driver, record)
    props = await node_props(neo4j_driver, "LinkToken", tokenHash=record.token_hash)
    assert set(props) == PROPERTY_NAMES
    assert props["usedAt"] is None


async def test_the_phone_is_stored_only_as_its_hash(neo4j_driver: AsyncDriver) -> None:
    record = _record()
    await _add(neo4j_driver, record)
    props = await node_props(neo4j_driver, "LinkToken", tokenHash=record.token_hash)
    assert props["phoneHash"] == PHONE_HASH
    for value in props.values():
        assert "07700" not in str(value)
        assert "900123" not in str(value)
