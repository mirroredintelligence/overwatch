"""The cross-tenant support guard on real Neo4j and a cache with two tenants (TEN-084, DEC-528 to
DEC-533).

The tenants' audit chains are the real hash chains (TEN-017): the guard binds the target tenant, in
a unit of work of its own, to write each entry in THAT tenant's chain; the platform chain is the
recording stand-in (its Neo4j adapter needs a platform scope that does not exist yet, known issue).
The cache is the in-memory fake, which qualifies every name by the bound tenant like Redis does.

What is proved here that the unit tests cannot: an entry written by the guard lands in the target
tenant's chain and in no other, the chains still verify after it, the audited actor is the support
person (never a tenant's own role) at the target tenant, and a code issued in one tenant opens
nothing in the other.

Written in build wave 5 and not run there: the orchestrator runs the full integration suite once on
the merged tip. Synthetic values only.
"""

from datetime import timedelta

import pytest
from diucs.adapters.testing.recording_platform_audit import RecordingPlatformAudit
from diucs.application.cross_tenant_guard import (
    AuthoriseCommand,
    CrossTenantDenied,
    CrossTenantGuard,
    EndAccessCommand,
    IssueCodeCommand,
    OpenAccessCommand,
    PlatformPrincipal,
)
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import TenantKeyedSecrets
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import bind_tenant
from diucs.bootstrap.container import TEST_NOW, Container
from diucs.domain.codes import Role
from diucs.domain.rules.support import SUPPORT_CODE_SECRET
from tests.support.api import seed_edge_tenants
from tests.support.neo4j import write_tx
from tests.support.tenancy import as_tenant
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

KEY = b"synthetic-platform-key-for-the-guard-integration-01"
REF = "ref-support-person-0123456789"
PRINCIPAL = PlatformPrincipal(account_ref=REF, role=Role.SUPPORT)


def _admin(tenant: str) -> Actor:
    return Actor(
        role=Role.TENANT_ADMIN,
        practitioner_id="admin-ten084",
        device_id=None,
        channel="api",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(TEST_NOW)


@pytest.fixture
def platform() -> RecordingPlatformAudit:
    return RecordingPlatformAudit()


async def _guard(
    uow_factory: UnitOfWorkFactory,
    clock: FixedClock,
    platform: RecordingPlatformAudit,
    driver: AsyncDriver,
    directory: TenantDirectory,
    *tenants: str,
) -> CrossTenantGuard:
    await seed_edge_tenants(driver, *tenants)
    await ensure_audit_heads(driver, *tenants)
    return CrossTenantGuard(
        uow_factory,
        InMemoryCache(clock),
        clock,
        SequentialIds("access"),
        TenantKeyedSecrets(FixedSecretStore({SUPPORT_CODE_SECRET: KEY})),
        directory,
        platform,
    )


async def _chain(uow_factory: UnitOfWorkFactory, tenant: str) -> list:  # type: ignore[type-arg]
    with as_tenant(tenant):
        async with uow_factory() as uow:
            assert await uow.audit.verify_chain()
            return list(await uow.audit.records())


async def test_the_entries_land_in_the_target_tenants_chain_and_in_no_other(
    test_container: Container,
    uow_factory: UnitOfWorkFactory,
    clock: FixedClock,
    platform: RecordingPlatformAudit,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    guard = await _guard(
        uow_factory,
        clock,
        platform,
        neo4j_driver,
        test_container.tenants,
        tenant_id,
        other_tenant_id,
    )
    other_before = len(await _chain(uow_factory, other_tenant_id))
    before = len(await _chain(uow_factory, tenant_id))

    with bind_tenant(tenant_id):
        issued = await guard.issue_code(IssueCodeCommand(actor=_admin(tenant_id)))
    elevation = await guard.open(
        OpenAccessCommand(principal=PRINCIPAL, tenant_id=tenant_id, code=issued.code)
    )
    await guard.authorise(
        AuthoriseCommand(
            principal=PRINCIPAL,
            tenant_id=tenant_id,
            access_id=elevation.access_id,
            action="read-session",
        )
    )
    await guard.end(
        EndAccessCommand(principal=PRINCIPAL, tenant_id=tenant_id, access_id=elevation.access_id)
    )

    records = (await _chain(uow_factory, tenant_id))[before:]
    assert [r.entry.action for r in records] == [
        "support-access-code-issued",
        "support-access-opened",
        "support-access-used",
        "support-access-ended",
    ]
    assert len(await _chain(uow_factory, other_tenant_id)) == other_before
    support_entries = [r.entry for r in records[1:]]
    assert all(
        e.actor.role is Role.SUPPORT and e.actor.tenant_id == tenant_id for e in support_entries
    )
    assert all(e.actor.practitioner_id == REF for e in support_entries)
    assert [e.action for e in platform.entries] == [
        "support-access-opened",
        "support-access-used",
        "support-access-ended",
    ]
    assert {e.tenant_id for e in platform.entries} == {tenant_id}


async def test_a_code_issued_in_one_tenant_opens_nothing_in_the_other(
    test_container: Container,
    uow_factory: UnitOfWorkFactory,
    clock: FixedClock,
    platform: RecordingPlatformAudit,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    guard = await _guard(
        uow_factory,
        clock,
        platform,
        neo4j_driver,
        test_container.tenants,
        tenant_id,
        other_tenant_id,
    )
    other_before = len(await _chain(uow_factory, other_tenant_id))
    with bind_tenant(tenant_id):
        issued = await guard.issue_code(IssueCodeCommand(actor=_admin(tenant_id)))

    with pytest.raises(CrossTenantDenied):
        await guard.open(
            OpenAccessCommand(principal=PRINCIPAL, tenant_id=other_tenant_id, code=issued.code)
        )

    assert len(await _chain(uow_factory, other_tenant_id)) == other_before
    assert [e.action for e in platform.entries] == ["support-access-refused"]


async def test_an_access_stops_standing_at_the_hour_and_the_code_opens_only_once(
    test_container: Container,
    uow_factory: UnitOfWorkFactory,
    clock: FixedClock,
    platform: RecordingPlatformAudit,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    guard = await _guard(
        uow_factory,
        clock,
        platform,
        neo4j_driver,
        test_container.tenants,
        tenant_id,
        other_tenant_id,
    )
    with bind_tenant(tenant_id):
        issued = await guard.issue_code(IssueCodeCommand(actor=_admin(tenant_id)))
    elevation = await guard.open(
        OpenAccessCommand(principal=PRINCIPAL, tenant_id=tenant_id, code=issued.code)
    )
    with pytest.raises(CrossTenantDenied):
        await guard.open(
            OpenAccessCommand(principal=PRINCIPAL, tenant_id=tenant_id, code=issued.code)
        )

    clock.advance(timedelta(hours=1))
    with pytest.raises(CrossTenantDenied):
        await guard.authorise(
            AuthoriseCommand(
                principal=PRINCIPAL,
                tenant_id=tenant_id,
                access_id=elevation.access_id,
                action="read-session",
            )
        )


async def test_a_suspended_tenant_cannot_be_accessed(
    test_container: Container,
    uow_factory: UnitOfWorkFactory,
    clock: FixedClock,
    platform: RecordingPlatformAudit,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    guard = await _guard(
        uow_factory,
        clock,
        platform,
        neo4j_driver,
        test_container.tenants,
        tenant_id,
        other_tenant_id,
    )
    with bind_tenant(tenant_id):
        issued = await guard.issue_code(IssueCodeCommand(actor=_admin(tenant_id)))

    async def suspend(tx: AsyncManagedTransaction) -> None:
        await tx.run(
            "MATCH (t:Tenant {id: $id}) SET t.status = 'suspended', t.suspendMode = 'blocked', "
            "t.suspendedAt = $at, t.suspendReason = 'contract'",
            id=tenant_id,
            at=TEST_NOW,
        )

    await write_tx(neo4j_driver, suspend)
    try:
        with pytest.raises(CrossTenantDenied):
            await guard.open(
                OpenAccessCommand(principal=PRINCIPAL, tenant_id=tenant_id, code=issued.code)
            )
    finally:
        await seed_edge_tenants(neo4j_driver, tenant_id)
