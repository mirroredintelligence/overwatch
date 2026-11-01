"""Neo4j round trips of the admin-consent invite and the service principal kept at consent
(DEC-1316, DEC-1317). Synthetic values only. WRITTEN, NOT RUN: the build session had no Docker. The
statements are also run as tenant A and as tenant B by the generated test
(test_tenant_isolation.py), which covers `Q-ACI-CONSENTED` and `Q-ACI-SP` from their scenarios."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from overwatch.adapters.outbound.graph_store.admin_consent_repository import (
    Neo4jAdminConsentRepository,
)
from overwatch.domain.rules.admin_consent import AdminConsentInvite, InviteStatus
from tests.support.neo4j import read_tx, write_tx
from tests.support.tenancy import as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
DIRECTORY = "11111111-2222-3333-4444-555555555555"
SP = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

Work = Callable[[Neo4jAdminConsentRepository], Awaitable[Any]]


def _invite(invite_id: str, state: str) -> AdminConsentInvite:
    return AdminConsentInvite(
        invite_id=invite_id,
        directory_id=DIRECTORY,
        email_hash="a" * 64,
        email_masked="j***@example.org",
        state_hash=state * 64,
        status=InviteStatus.PENDING,
        created_at=T0,
        expires_at=T0 + timedelta(days=7),
    )


async def _write(driver: AsyncDriver, tenant: str, work: Work) -> Any:
    async def run(tx: AsyncManagedTransaction) -> Any:
        return await work(Neo4jAdminConsentRepository(tx))

    with as_tenant(tenant):
        return await write_tx(driver, run)


async def _read(driver: AsyncDriver, tenant: str, work: Work) -> Any:
    async def run(tx: AsyncManagedTransaction) -> Any:
        return await work(Neo4jAdminConsentRepository(tx))

    with as_tenant(tenant):
        return await read_tx(driver, run)


async def test_consent_keeps_the_service_principal_and_the_consented_read_returns_it(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    async def make(repo: Neo4jAdminConsentRepository) -> None:
        await repo.add(_invite("inv-1", "b"))
        assert await repo.mark_consented("inv-1", T1, SP)

    await _write(neo4j_driver, tenant_id, make)
    found = await _read(neo4j_driver, tenant_id, lambda repo: repo.consented())

    assert found is not None and found.status is InviteStatus.CONSENTED
    assert found.service_principal_id == SP and found.consented_at == T1


async def test_a_pending_invite_is_not_the_consented_one(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _write(neo4j_driver, tenant_id, lambda repo: repo.add(_invite("inv-1", "b")))
    assert await _read(neo4j_driver, tenant_id, lambda repo: repo.consented()) is None


async def test_a_consent_with_no_principal_can_be_given_one_later_and_only_once_consented(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    async def make(repo: Neo4jAdminConsentRepository) -> None:
        await repo.add(_invite("inv-1", "b"))
        await repo.set_service_principal("inv-1", SP)  # not consented yet: changes nothing
        assert await repo.mark_consented("inv-1", T1)

    await _write(neo4j_driver, tenant_id, make)
    before = await _read(neo4j_driver, tenant_id, lambda repo: repo.consented())
    assert before is not None and before.service_principal_id is None

    await _write(neo4j_driver, tenant_id, lambda repo: repo.set_service_principal("inv-1", SP))
    after = await _read(neo4j_driver, tenant_id, lambda repo: repo.consented())
    assert after is not None and after.service_principal_id == SP


async def test_another_tenants_consent_is_not_seen(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    async def make(repo: Neo4jAdminConsentRepository) -> None:
        await repo.add(_invite("inv-1", "b"))
        await repo.mark_consented("inv-1", T1, SP)

    await _write(neo4j_driver, tenant_id, make)

    assert await _read(neo4j_driver, other_tenant_id, lambda repo: repo.consented()) is None
    await _write(
        neo4j_driver, other_tenant_id, lambda repo: repo.set_service_principal("inv-1", SP)
    )
    mine = await _read(neo4j_driver, tenant_id, lambda repo: repo.consented())
    assert (
        mine is not None and mine.service_principal_id == SP
    )  # untouched by the other tenant's call
