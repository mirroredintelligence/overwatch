"""Integration tests for the Neo4j link-token store (P10, DEC-004, domain-rules 7).

They run against the throwaway Neo4j the F10 harness starts for the session. Each save commits in
one transaction and each load runs in a fresh session. Synthetic values only: no patient data.
"""

import asyncio
import hashlib
import hmac
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import ClientError

from diucs.adapters.outbound.graph_store.link_token_repository import Neo4jLinkTokenRepository
from diucs.application.tenancy import TenantNotBound
from diucs.domain.errors import Conflict, ValidationFailed
from diucs.domain.rules.tokens import LinkTokenRecord, hash_token, new_link_token
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip
from tests.support.tenancy import as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET = b"link-token-test-secret-0123456789abcdef"
TOKEN = new_link_token(rng=lambda n: bytes(range(n)))
EXPIRES = datetime(2026, 10, 25, 12, 30, tzinfo=UTC)
AT = datetime(2026, 10, 25, 11, 0, tzinfo=UTC)
# Independent oracle: HMAC-SHA256 of the normalised number, keyed by the phone-hash secret.
PHONE_HASH = hmac.new(b"p" * 32, b"07700900123", hashlib.sha256).hexdigest()
PROPERTY_NAMES = {
    "id",
    "tenantId",
    "tokenHash",
    "phoneHash",
    "purpose",
    "aboutId",
    "expiresAt",
    "usedAt",
}


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


async def _mark_used(
    driver: AsyncDriver, token_hash: str, at: datetime, key: str = "req-1"
) -> bool:
    async def work(tx: AsyncManagedTransaction) -> bool:
        return await Neo4jLinkTokenRepository(tx).mark_used(token_hash, at, key)

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


async def test_two_racing_adds_of_one_hash_store_one_node_and_refuse_the_other(
    neo4j_driver: AsyncDriver,
) -> None:
    record = _record()
    results = await asyncio.gather(
        _add(neo4j_driver, record), _add(neo4j_driver, record), return_exceptions=True
    )
    refused = [result for result in results if isinstance(result, Conflict)]
    assert len(refused) == 1, results
    assert await count_nodes(neo4j_driver, "LinkToken") == 1


async def test_a_duplicate_the_precheck_missed_is_still_a_conflict(
    neo4j_driver: AsyncDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A racing add can pass the existence check and then hit the unique constraint. Forcing the
    check to miss shows the constraint's refusal becomes Conflict, and that one node remains."""
    record = _record()
    await _add(neo4j_driver, record)

    async def precheck_misses(self: Neo4jLinkTokenRepository, token_hash: str) -> None:
        return None

    monkeypatch.setattr(Neo4jLinkTokenRepository, "get_by_hash", precheck_misses)
    with pytest.raises(Conflict):
        await _add(neo4j_driver, record)
    monkeypatch.undo()
    assert await count_nodes(neo4j_driver, "LinkToken") == 1


async def test_the_repository_refuses_a_raw_phone_in_the_phone_field_with_zero_nodes(
    neo4j_driver: AsyncDriver,
) -> None:
    """The record type refuses a raw phone when it is built. This shows the repository refuses it
    too, for a record that reached it without that check, and that nothing is written."""
    raw = SimpleNamespace(**{**asdict(_record()), "phone_hash": "07700 900123"})
    with pytest.raises(ValidationFailed):
        await _add(neo4j_driver, cast(LinkTokenRecord, raw))
    assert await count_nodes(neo4j_driver, "LinkToken") == 0


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


@pytest.mark.parametrize("round_number", range(1, 6))
async def test_concurrent_mark_used_lets_exactly_one_caller_win(
    neo4j_driver: AsyncDriver, round_number: int
) -> None:
    token = new_link_token(rng=lambda n: bytes([round_number] * n))
    record = _record(token)
    await _add(neo4j_driver, record)
    results = await asyncio.gather(
        *(_mark_used(neo4j_driver, record.token_hash, AT) for _ in range(16))
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
    # Neo4j stores no null property, so an unused link has no usedAt key at all.
    assert set(props) == PROPERTY_NAMES - {"usedAt"}


async def test_the_phone_is_stored_only_as_its_hash(neo4j_driver: AsyncDriver) -> None:
    record = _record()
    await _add(neo4j_driver, record)
    props = await node_props(neo4j_driver, "LinkToken", tokenHash=record.token_hash)
    assert props["phoneHash"] == PHONE_HASH
    for value in props.values():
        assert "07700" not in str(value)
        assert "900123" not in str(value)


# -- the tenant (L01, DEC-167): a link token belongs to the tenant it was issued in -------------


async def test_a_link_token_carries_the_tenant_it_was_issued_in(
    neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    record = _record()
    await _add(neo4j_driver, record)

    props = await node_props(neo4j_driver, "LinkToken", tokenHash=record.token_hash)

    assert props["tenantId"] == tenant_id


async def test_another_tenants_link_token_is_not_found_marked_used_or_read(
    neo4j_driver: AsyncDriver, other_tenant_id: str
) -> None:
    record = _record()
    await _add(neo4j_driver, record)

    with as_tenant(other_tenant_id):
        assert await _get(neo4j_driver, record.token_hash) is None
        assert await _mark_used(neo4j_driver, record.token_hash, AT) is False

        async def burn_key(tx: AsyncManagedTransaction) -> str | None:
            return await Neo4jLinkTokenRepository(tx).burn_key(record.token_hash)

        assert await read_tx(neo4j_driver, burn_key) is None

    # Nothing of the owner's was changed by the attempts.
    stored = await _get(neo4j_driver, record.token_hash)
    assert stored is not None and stored.used_at is None
    assert "burnKey" not in await node_props(neo4j_driver, "LinkToken", tokenHash=record.token_hash)


async def test_a_token_hash_is_unique_across_tenants_so_a_second_tenant_cannot_store_it(
    neo4j_driver: AsyncDriver, other_tenant_id: str
) -> None:
    """The hash stays globally unique by design (DEC-131 item 5): another tenant that stores the
    same hash is refused, and the owner's link is untouched."""
    record = _record()
    await _add(neo4j_driver, record)

    with as_tenant(other_tenant_id), pytest.raises(Conflict):
        await _add(neo4j_driver, record)

    assert await count_nodes(neo4j_driver, "LinkToken") == 1
    assert await _get(neo4j_driver, record.token_hash) == record


@pytest.mark.no_tenant
async def test_a_link_token_statement_refuses_to_run_with_no_tenant_bound(
    neo4j_driver: AsyncDriver,
) -> None:
    with pytest.raises(TenantNotBound):
        await _get(neo4j_driver, "a" * 64)
    with pytest.raises(TenantNotBound):
        await _add(neo4j_driver, _record())
    assert await count_nodes(neo4j_driver, "LinkToken") == 0
