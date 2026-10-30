"""Suspending and resuming a tenant on a real Neo4j (TEN-073, DEC-507, DEC-130 to DEC-136).

Two active tenants, each with a service and a prompt chain. The operator suspends one. What is
proved, on a private contracted graph (DEC-159):

- the tenant's record says suspended, with its mode and reason, and its epoch is one higher; the
  directory no longer lists it as active (so the relay and the consumers skip it), and the other
  tenant is untouched in every respect (record, chain, scheduled work, outbox);
- the edge's gate, reading the real directory, refuses the tenant's token within its cache interval,
  and a token from before the suspension stays refused after the resume (the epoch went up twice);
- a resume schedules the next prompt of each active service once, cancels the prompt that fell due
  while the tenant was suspended, writes a StatusChanged for each service in the tenant's own
  outbox, leaves a service its lead suspended suspended, and reactivates the record last;
- the audit chain of the tenant holds the operator's two actions, named, and verifies; the other
  tenant's chain did not move;
- an operator bound to the other tenant, and a role that is not the platform operator, cannot
  suspend or resume it.

Written in build wave 5 and not run there: the full integration run follows on the merged tip.
Synthetic values only.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.inbound.fhir_rest.tenant_gate import RECORD_TTL, TenantGate
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.tenant_directory import Neo4jTenantDirectory
from diucs.adapters.outbound.graph_store.tenant_registry import Neo4jTenantRegistry
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import TenantMismatch, bind_tenant
from diucs.application.tenant_settings import DirectoryZones
from diucs.application.use_cases.tenant_suspend import (
    ResumeTenant,
    ResumeTenantCommand,
    SuspendTenant,
    SuspendTenantCommand,
)
from diucs.application.work import CANCELLED, SCHEDULED, ScheduledWork, WorkKind
from diucs.bootstrap.provisioning import AuditHeads
from diucs.domain.codes import Cadence, Channel, Measure, Role, ServiceCategory
from diucs.domain.errors import InvalidTransition, NotAllowed
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant import (
    OrganisationType,
    SuspendMode,
    SuspendReason,
    Tenant,
    TenantStatus,
)
from diucs.domain.rules.bff_token import BffClaims
from diucs.domain.rules.edge_access import EdgeVerdict
from tests.support.neo4j import ThrowawayNeo4j, read_tx, wipe_all
from tests.support.tenancy import as_tenant
from tests.support.uow import tenant_uow_factory

pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.schema]

A, B = "susp-alpha", "susp-bravo"
NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
SERVICE = "svc-susp"
LEAD_SERVICE = "svc-lead-suspended"


@dataclass
class World:
    driver: AsyncDriver
    connection: Neo4jConnection
    directory: Neo4jTenantDirectory
    registry: Neo4jTenantRegistry
    clock: FixedClock
    ids: SequentialIds

    def factory(self, tenant: str) -> UnitOfWorkFactory:
        return tenant_uow_factory(self.driver, tenant)

    def suspend(self, tenant: str, on_changed: Any = ()) -> SuspendTenant:
        return SuspendTenant(
            self.directory, self.registry, self.factory(tenant), self.clock, on_changed
        )

    def resume(self, tenant: str) -> ResumeTenant:
        return ResumeTenant(
            self.directory,
            self.registry,
            self.factory(tenant),
            SequentialIds.scoped(tenant),
            self.clock,
            DirectoryZones(self.directory),
        )


def _operator(tenant: str, role: Role = Role.PLATFORM_OPERATOR) -> Actor:
    return Actor(
        role=role,
        practitioner_id="operator-1",
        device_id=None,
        channel="script",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def _profile(service_id: str) -> ServiceProfile:
    return ServiceProfile(
        id=service_id,
        name=f"Service {service_id}",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals in the next 2 hrs",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.every_day(time(2, 0), time(23, 0)),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


@asynccontextmanager
async def _private_graph(
    own: tuple[ThrowawayNeo4j, AsyncDriver],
) -> AsyncIterator[tuple[AsyncDriver, Neo4jConnection]]:
    """The module's private container (`own_neo4j`: every migration applied, the registry is the
    whole database's, so it cannot share a Neo4j with other runs), emptied for each test, and a
    connection to it for the directory and the registry."""
    container, driver = own
    await wipe_all(driver)
    connection = Neo4jConnection(container.uri, container.user, container.password)
    await connection.open()
    try:
        yield driver, connection
    finally:
        await connection.close()
        await wipe_all(driver)


async def _make_active(world: World, tenant_id: str) -> None:
    """An active tenant with its chain, two services (one the lead has suspended), a prompt that is
    due and a prompt that fell due long ago."""
    created = Tenant(
        id=tenant_id,
        display_name=f"Org {tenant_id}",
        legal_name=f"Org {tenant_id} Ltd",
        organisation_type=OrganisationType.OTHER,
        status=TenantStatus.PROVISIONING,
        created_at=NOW - timedelta(days=30),
    )
    await world.registry.create(created)
    activated = _activated(created)
    assert await world.registry.save(
        activated, expected_epoch=1, expected_status=TenantStatus.PROVISIONING
    )
    with bind_tenant(tenant_id):
        await AuditHeads(world.connection).ensure_audit_head()
        async with world.factory(tenant_id)() as uow:
            await uow.services.save(_profile(SERVICE))
            await uow.services.save(_profile(LEAD_SERVICE))
            await uow.flags.set_service_flag(
                ServiceFlag(
                    service_id=LEAD_SERVICE,
                    code=SERVICE_FLAG_SUSPENDED,
                    active=True,
                    reason="other",
                    actor_id="prac-lead",
                    at=NOW - timedelta(days=1),
                )
            )
            await uow.scheduled_work.add(
                ScheduledWork(
                    id=f"{tenant_id}-stale",
                    kind=WorkKind.PROMPT_DUE,
                    due_at=NOW - timedelta(hours=3),
                    about_id=SERVICE,
                    sequence_number=None,
                    status=SCHEDULED,
                )
            )
            await uow.commit()


def _activated(created: Tenant) -> Tenant:
    from dataclasses import replace

    return replace(created, status=TenantStatus.ACTIVE, activated_at=NOW - timedelta(days=29))


@pytest_asyncio.fixture(loop_scope="session")
async def world(own_neo4j: tuple[ThrowawayNeo4j, AsyncDriver]) -> AsyncIterator[World]:
    async with _private_graph(own_neo4j) as (driver, connection):
        built = World(
            driver,
            connection,
            Neo4jTenantDirectory(connection),
            Neo4jTenantRegistry(connection),
            FixedClock(NOW),
            SequentialIds(),
        )
        await _make_active(built, A)
        await _make_active(built, B)
        yield built


async def _rows(world: World, tenant: str, cypher: str) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run(cypher, t=tenant)).data()

    return await read_tx(world.driver, work)


async def _chain(world: World, tenant: str) -> list[str]:
    rows = await _rows(
        world, tenant, "MATCH (e:AuditEvent {tenantId: $t}) RETURN e.useCase AS u ORDER BY e.seq"
    )
    return [str(r["u"]) for r in rows]


async def _outbox_ids(world: World, tenant: str) -> list[str]:
    rows = await _rows(
        world, tenant, "MATCH (m:OutboxMessage {tenantId: $t}) RETURN m.id AS id ORDER BY m.id"
    )
    return [str(r["id"]) for r in rows]


async def _prompts(world: World, tenant: str) -> list[ScheduledWork]:
    with bind_tenant(tenant):
        async with world.factory(tenant)() as uow:
            return await uow.scheduled_work.for_about(SERVICE, WorkKind.PROMPT_DUE)


def _claims(tenant: str, epoch: int) -> BffClaims:
    return BffClaims(
        sub="prac-1",
        role=Role.LEAD,
        services=frozenset(),
        expires_at=NOW + timedelta(hours=8),
        tenant=tenant,
        epoch=epoch,
    )


# -- suspend ---------------------------------------------------------------------------------------


async def test_a_suspension_writes_the_record_and_leaves_the_other_tenant_untouched(
    world: World,
) -> None:
    other_before = await world.directory.get(B)
    other_chain = await _chain(world, B)
    other_prompts = await _prompts(world, B)
    other_outbox = await _outbox_ids(world, B)

    with as_tenant(A):
        result = await world.suspend(A).execute(
            SuspendTenantCommand(_operator(A), SuspendMode.BLOCKED, SuspendReason.SECURITY_INCIDENT)
        )

    tenant = await world.directory.get(A)
    assert tenant is not None and tenant.status is TenantStatus.SUSPENDED
    assert tenant.suspend_mode is SuspendMode.BLOCKED and tenant.epoch == 2 == result.epoch
    assert A not in await world.directory.active_tenant_ids()  # the relay and consumers skip it
    assert B in await world.directory.active_tenant_ids()
    assert await world.directory.get(B) == other_before
    assert await _chain(world, B) == other_chain
    assert await _prompts(world, B) == other_prompts
    assert await _outbox_ids(world, B) == other_outbox
    assert (await _chain(world, A))[-1] == "SuspendTenant"


async def test_the_edge_refuses_the_suspended_tenants_token_within_the_cache_interval(
    world: World,
) -> None:
    clock = FixedClock(NOW)
    gate = TenantGate(world.directory, clock)
    assert await gate.verdict(_claims(A, 1), "GET") is EdgeVerdict.ALLOWED
    assert await gate.verdict(_claims(B, 1), "GET") is EdgeVerdict.ALLOWED

    with as_tenant(A):
        await world.suspend(A).execute(
            SuspendTenantCommand(_operator(A), SuspendMode.BLOCKED, SuspendReason.CONTRACT)
        )

    clock.set(NOW + RECORD_TTL)
    assert await gate.verdict(_claims(A, 1), "GET") is EdgeVerdict.REFUSED
    assert await gate.verdict(_claims(B, 1), "GET") is EdgeVerdict.ALLOWED


async def test_a_read_only_suspension_lets_only_the_tenant_administrator_read(
    world: World,
) -> None:
    gate = TenantGate(world.directory, FixedClock(NOW))
    with as_tenant(A):
        await world.suspend(A, (gate.forget,)).execute(
            SuspendTenantCommand(
                _operator(A), SuspendMode.READ_ONLY, SuspendReason.INFORMATION_GOVERNANCE
            )
        )
    admin = BffClaims(
        sub="prac-9",
        role=Role.TENANT_ADMIN,
        services=frozenset(),
        expires_at=NOW + timedelta(hours=8),
        tenant=A,
        epoch=2,
    )
    assert await gate.verdict(admin, "GET") is EdgeVerdict.ALLOWED
    assert await gate.verdict(admin, "POST") is EdgeVerdict.REFUSED
    assert await gate.verdict(_claims(A, 2), "GET") is EdgeVerdict.REFUSED


async def test_a_second_suspension_and_a_suspension_of_a_suspended_tenant_change_nothing(
    world: World,
) -> None:
    with as_tenant(A):
        await world.suspend(A).execute(
            SuspendTenantCommand(_operator(A), SuspendMode.BLOCKED, SuspendReason.CONTRACT)
        )
        chain = await _chain(world, A)
        with pytest.raises(InvalidTransition):
            await world.suspend(A).execute(
                SuspendTenantCommand(
                    _operator(A), SuspendMode.READ_ONLY, SuspendReason.OPERATOR_REQUEST
                )
            )
    tenant = await world.directory.get(A)
    assert tenant is not None and tenant.suspend_mode is SuspendMode.BLOCKED and tenant.epoch == 2
    assert await _chain(world, A) == chain


async def test_another_role_and_an_operator_of_another_tenant_cannot_suspend(
    world: World,
) -> None:
    before = await world.directory.get(A)
    with as_tenant(A):
        for role in (Role.OWNER, Role.LEAD, Role.TENANT_ADMIN, Role.SUPPORT):
            with pytest.raises(NotAllowed):
                await world.suspend(A).execute(
                    SuspendTenantCommand(
                        _operator(A, role), SuspendMode.BLOCKED, SuspendReason.CONTRACT
                    )
                )
        with pytest.raises(TenantMismatch):
            await world.suspend(A).execute(
                SuspendTenantCommand(_operator(B), SuspendMode.BLOCKED, SuspendReason.CONTRACT)
            )
    assert await world.directory.get(A) == before


# -- resume ----------------------------------------------------------------------------------------


async def test_a_resume_prompts_each_service_again_and_reactivates_the_record_last(
    world: World,
) -> None:
    other_before = await world.directory.get(B)
    other_prompts = await _prompts(world, B)
    with as_tenant(A):
        await world.suspend(A).execute(
            SuspendTenantCommand(_operator(A), SuspendMode.BLOCKED, SuspendReason.CONTRACT)
        )
        result = await world.resume(A).execute(ResumeTenantCommand(_operator(A)))

    tenant = await world.directory.get(A)
    assert tenant is not None and tenant.status is TenantStatus.ACTIVE
    assert tenant.epoch == 3 == result.epoch
    assert (tenant.suspend_mode, tenant.suspend_reason, tenant.suspended_at) == (None,) * 3
    assert A in await world.directory.active_tenant_ids()

    prompts = await _prompts(world, A)
    stale = next(p for p in prompts if p.id == f"{A}-stale")
    fresh = [p for p in prompts if p.id != f"{A}-stale"]
    assert stale.status == CANCELLED
    assert len(fresh) == 1 and fresh[0].status == SCHEDULED and fresh[0].due_at > NOW
    assert result.services_prompted == 1  # the service the lead suspended is not counted

    # The lead's own suspension stands: no prompt, no event for that service.
    with bind_tenant(A):
        async with world.factory(A)() as uow:
            assert await uow.scheduled_work.for_about(LEAD_SERVICE, WorkKind.PROMPT_DUE) == []
    outbox = await _outbox_ids(world, A)
    assert outbox and all(not i.endswith(LEAD_SERVICE) for i in outbox)
    assert f"tenant-resume-3-{SERVICE}" in await _outbox_ids(world, A)

    assert (await _chain(world, A))[-2:] == ["SuspendTenant", "ResumeTenant"]
    with bind_tenant(A):
        async with world.factory(A)() as uow:
            assert await uow.audit.verify_chain() is True
    # The other tenant is exactly as it was.
    assert await world.directory.get(B) == other_before
    assert await _prompts(world, B) == other_prompts


async def test_a_token_from_before_the_suspension_stays_refused_after_the_resume(
    world: World,
) -> None:
    gate = TenantGate(world.directory, FixedClock(NOW))
    with as_tenant(A):
        await world.suspend(A, (gate.forget,)).execute(
            SuspendTenantCommand(_operator(A), SuspendMode.BLOCKED, SuspendReason.CONTRACT)
        )
        await world.resume(A).execute(ResumeTenantCommand(_operator(A)))
    gate.forget(A)

    assert await gate.verdict(_claims(A, 1), "GET") is EdgeVerdict.REFUSED
    assert await gate.verdict(_claims(A, 2), "GET") is EdgeVerdict.REFUSED
    assert await gate.verdict(_claims(A, 3), "GET") is EdgeVerdict.ALLOWED


async def test_only_a_suspended_tenant_is_resumed_and_only_by_the_operator(world: World) -> None:
    with as_tenant(A):
        with pytest.raises(InvalidTransition):
            await world.resume(A).execute(ResumeTenantCommand(_operator(A)))
        await world.suspend(A).execute(
            SuspendTenantCommand(_operator(A), SuspendMode.BLOCKED, SuspendReason.CONTRACT)
        )
        with pytest.raises(NotAllowed):
            await world.resume(A).execute(ResumeTenantCommand(_operator(A, Role.TENANT_ADMIN)))
        with pytest.raises(TenantMismatch):
            await world.resume(A).execute(ResumeTenantCommand(_operator(B)))
    tenant = await world.directory.get(A)
    assert tenant is not None and tenant.status is TenantStatus.SUSPENDED
