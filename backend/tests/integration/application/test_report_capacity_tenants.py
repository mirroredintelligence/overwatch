"""Two-tenant tests for ReportCapacity (TEN-024, DEC-130 to DEC-134, reworks U01).

Tenant A and tenant B each run their own service of one id. What is proved, on a graph that holds
both:

- a report in A for a service that only B has reads exactly as a report for an id nobody has
  (`NotFound`, the same text), takes no lock (a lock B holds does not delay it) and writes nothing
  in either tenant;
- a performer role of B named in A's report is one fixed `NotFound` and writes nothing;
- one command key used in both tenants is two commands: neither replays nor conflicts with the
  other, and a key B used with a different body is no `Conflict` for A (no existence oracle);
- an actor of B in work bound to A is refused before anything is read (`TenantMismatch`);
- the tenant's own configuration reaches the status and the audit snapshot records its version.

Runs on the shared harness database (the contracted schema, DEC-159). Synthetic values only.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import TenantMismatch
from diucs.application.use_cases.report_capacity import (
    PERFORMER_NOT_FOUND,
    ReportCapacity,
    ReportCapacityCommand,
)
from diucs.application.use_cases.tenant_config import (
    ApproveConfigCommand,
    ApproveTenantConfig,
    DraftConfigCommand,
    DraftTenantConfig,
)
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    ReportSource,
    Role,
    ServiceCategory,
    Status,
)
from diucs.domain.errors import Conflict, NotFound
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import read_tx, run_scope_ids
from tests.support.tenancy import as_tenant
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 23, 11, 45, tzinfo=UTC)  # 12:45 BST, Friday
SERVICE = "ucr-west"
ROLE = "role-west"
PRACTITIONER = "prac-west"

PROFILE = ServiceProfile(
    id=SERVICE,
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)


def _reporter(tenant: str) -> Actor:
    return Actor(
        role=Role.REPORTER,
        practitioner_id=PRACTITIONER,
        device_id=None,
        channel="text",
        service_ids=frozenset({SERVICE}),
        tenant_id=tenant,
    )


@dataclass(frozen=True)
class Tenants:
    driver: AsyncDriver
    a: str
    b: str
    factory_a: UnitOfWorkFactory
    factory_b: UnitOfWorkFactory

    def use_case(self, tenant: str) -> ReportCapacity:
        factory = self.factory_a if tenant == self.a else self.factory_b
        return ReportCapacity(
            factory,
            FixedClock(NOW),
            SequentialIds(f"{tenant}-"),
            DriverIdempotencyStore(self.driver),
        )


async def _seed(factory: UnitOfWorkFactory) -> None:
    async with factory() as uow:
        await uow.services.save(PROFILE)
        await uow.people.save_practitioner(
            Practitioner(
                id=PRACTITIONER, active=True, display_name="Sample Reporter", phone_hash=None
            )
        )
        await uow.people.save_role(
            PractitionerRole(
                id=ROLE,
                practitioner_id=PRACTITIONER,
                service_id=SERVICE,
                code=PractitionerRoleCode.DUTY_MANAGER,
                active=True,
                channel=Channel.TEXT,
                period_start=NOW - timedelta(days=30),
            )
        )
        await uow.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def tenants(
    tenant_id: str, other_tenant_id: str, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[Tenants]:
    driver = neo4j_driver
    await ensure_audit_heads(driver, tenant_id, other_tenant_id)
    factory_a = tenant_uow_factory(driver, tenant_id)
    factory_b = tenant_uow_factory(driver, other_tenant_id)
    await _seed(factory_a)
    await _seed(factory_b)
    yield Tenants(driver, tenant_id, other_tenant_id, factory_a, factory_b)


async def _written(tenants: Tenants, tenant: str) -> dict[str, int]:
    """What the tenant holds that a report writes: reports, outbox, communications, audit entries
    (after the head), idempotency records."""

    async def work(tx: AsyncManagedTransaction) -> dict[str, int]:
        counts: dict[str, int] = {}
        for label in (
            "Observation",
            "OutboxMessage",
            "Communication",
            "AuditEvent",
            "IdempotencyRecord",
        ):
            record = await (
                await tx.run(
                    f"MATCH (n:`{label}` {{tenantId: $tenant}}) RETURN count(n) AS total",
                    tenant=tenant,
                )
            ).single()
            assert record is not None
            counts[label] = int(record["total"])
        return counts

    return await read_tx(tenants.driver, work)


def _command(tenant: str, **fields: Any) -> ReportCapacityCommand:
    base: dict[str, Any] = {
        "idempotency_key": "key-1",
        "actor": _reporter(tenant),
        "service_id": SERVICE,
        "value": 4,
        "source": ReportSource.TEXT,
    }
    return ReportCapacityCommand(**{**base, **fields})


async def _report(tenants: Tenants, tenant: str, **fields: Any) -> Any:
    with as_tenant(tenant):
        return await tenants.use_case(tenant).execute(_command(tenant, **fields))


# -- another tenant's service ------------------------------------------------------------------


async def test_a_service_only_the_other_tenant_has_reads_as_an_id_nobody_has(
    tenants: Tenants,
) -> None:
    async with tenants.factory_b() as uow:
        await uow.services.save(replace(PROFILE, id="only-b", name="Only B"))
        await uow.commit()
    before_a = await _written(tenants, tenants.a)
    before_b = await _written(tenants, tenants.b)
    actor = Actor(
        role=Role.ADVISOR,
        practitioner_id="prac-advisor",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=tenants.a,
    )

    with pytest.raises(NotFound) as foreign:
        await _report(
            tenants, tenants.a, service_id="only-b", actor=actor, source=ReportSource.ADVISOR_PHONED
        )
    with pytest.raises(NotFound) as random:
        await _report(
            tenants,
            tenants.a,
            service_id="nobody-has-this",
            actor=actor,
            source=ReportSource.ADVISOR_PHONED,
        )

    assert type(foreign.value) is type(random.value)
    assert str(foreign.value) == str(random.value) == "no active service with this id"
    assert await _written(tenants, tenants.a) == before_a
    assert await _written(tenants, tenants.b) == before_b


async def test_a_lock_the_other_tenant_holds_does_not_delay_a_report_for_its_service_id(
    tenants: Tenants,
) -> None:
    async with tenants.factory_b() as uow:
        await uow.services.save(replace(PROFILE, id="held-by-b", name="Held B"))
        await uow.commit()
    locked, release = asyncio.Event(), asyncio.Event()

    async def hold() -> None:
        # Its own task, so its unit of work is not nested in the test's context.
        async with tenants.factory_b() as holder:
            await holder.capacity.lock_service("held-by-b")  # held until released
            locked.set()
            await release.wait()
            await holder.rollback()

    holder_task = asyncio.create_task(hold())
    try:
        await asyncio.wait_for(locked.wait(), timeout=30)
        advisor = Actor(
            role=Role.ADVISOR,
            practitioner_id="prac-advisor",
            device_id=None,
            channel="web",
            service_ids=frozenset(),
            tenant_id=tenants.a,
        )
        with pytest.raises(NotFound):
            await asyncio.wait_for(
                _report(
                    tenants,
                    tenants.a,
                    service_id="held-by-b",
                    actor=advisor,
                    source=ReportSource.ADVISOR_PHONED,
                ),
                timeout=10,
            )
    finally:
        release.set()
        await holder_task


async def test_the_lock_statement_is_bound_to_the_tenant() -> None:
    assert "tenantId: $tenant" in REGISTRY.get("Q-CAP-LOCK-SERVICE").cypher


# -- the performer -----------------------------------------------------------------------------


async def test_a_role_of_another_tenant_is_not_a_performer_and_the_report_writes_nothing(
    tenants: Tenants,
) -> None:
    async with tenants.factory_b() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-b-only", active=True, display_name="Sample B", phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id="role-b-only",
                practitioner_id="prac-b-only",
                service_id=SERVICE,
                code=PractitionerRoleCode.DUTY_MANAGER,
                active=True,
                channel=Channel.TEXT,
                period_start=NOW - timedelta(days=30),
            )
        )
        await uow.commit()
    before = await _written(tenants, tenants.a)

    with pytest.raises(NotFound, match=PERFORMER_NOT_FOUND):
        await _report(tenants, tenants.a, performer_role_id="role-b-only")

    assert await _written(tenants, tenants.a) == before


async def test_a_role_of_the_tenant_that_belongs_to_someone_else_is_refused_too(
    tenants: Tenants,
) -> None:
    async with tenants.factory_a() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-other", active=True, display_name="Sample Other", phone_hash=None)
        )
        await uow.people.save_role(
            PractitionerRole(
                id="role-other",
                practitioner_id="prac-other",
                service_id=SERVICE,
                code=PractitionerRoleCode.DUTY_MANAGER,
                active=True,
                channel=Channel.TEXT,
                period_start=NOW - timedelta(days=30),
            )
        )
        await uow.commit()
    before = await _written(tenants, tenants.a)

    with pytest.raises(NotFound, match=PERFORMER_NOT_FOUND):
        await _report(tenants, tenants.a, performer_role_id="role-other")

    assert await _written(tenants, tenants.a) == before


async def test_the_actors_own_role_is_accepted_and_is_the_echo_recipient(
    tenants: Tenants,
) -> None:
    result = await _report(tenants, tenants.a, performer_role_id=ROLE)

    async with tenants.factory_a() as uow:
        latest = await uow.capacity.latest(SERVICE)
        sends = [m for m in await uow.outbox.pending(limit=100) if m.event_type == "SendMessage"]
    assert latest is not None and latest.id == result.report_id
    assert latest.performer_role_id == ROLE
    assert [m.payload["recipient_role_id"] for m in sends] == [ROLE]


# -- the command key ---------------------------------------------------------------------------


async def test_one_command_key_in_two_tenants_is_two_commands(tenants: Tenants) -> None:
    first = await _report(tenants, tenants.a, value=4)
    second = await _report(tenants, tenants.b, value=7)

    assert not first.replayed and not second.replayed
    async with tenants.factory_a() as uow:
        latest_a = await uow.capacity.latest(SERVICE)
    async with tenants.factory_b() as uow:
        latest_b = await uow.capacity.latest(SERVICE)
    assert latest_a is not None and latest_a.value == 4
    assert latest_b is not None and latest_b.value == 7


async def test_a_key_the_other_tenant_used_with_another_body_is_no_conflict_here(
    tenants: Tenants,
) -> None:
    await _report(tenants, tenants.b, value=7, idempotency_key="shared-key")

    first_in_a = await _report(tenants, tenants.a, value=2, idempotency_key="shared-key")

    assert first_in_a.replayed is False


async def test_a_reused_key_with_another_body_in_one_tenant_is_still_a_conflict(
    tenants: Tenants,
) -> None:
    await _report(tenants, tenants.a, value=4, idempotency_key="same-key")
    before = await _written(tenants, tenants.a)

    with pytest.raises(Conflict):
        await _report(tenants, tenants.a, value=5, idempotency_key="same-key")

    assert await _written(tenants, tenants.a) == before


async def test_an_identical_replay_in_one_tenant_still_returns_the_first_result(
    tenants: Tenants,
) -> None:
    first = await _report(tenants, tenants.a, value=4, idempotency_key="replay-key")
    before = await _written(tenants, tenants.a)

    again = await _report(tenants, tenants.a, value=4, idempotency_key="replay-key")

    assert again.replayed is True
    assert again.report_id == first.report_id
    assert await _written(tenants, tenants.a) == before


# -- the guard ---------------------------------------------------------------------------------


async def test_an_actor_of_the_other_tenant_in_work_bound_to_this_one_is_refused_before_any_read(
    tenants: Tenants,
) -> None:
    before = await _written(tenants, tenants.a)
    with as_tenant(tenants.a), pytest.raises(TenantMismatch):
        await tenants.use_case(tenants.a).execute(_command(tenants.b))
    assert await _written(tenants, tenants.a) == before


async def _config_in_force(factory: UnitOfWorkFactory) -> int:
    """A first configuration version approved by two people other than its author, as it must be:
    a reply window of 60 minutes (the default is 30)."""

    def person(ref: str) -> Actor:
        return Actor(
            role=Role.OWNER,
            practitioner_id=ref,
            device_id=None,
            channel="web",
            service_ids=frozenset(),
            tenant_id=ACTOR_TENANT,
        )

    roles = frozenset({Role.OWNER})
    clock = FixedClock(NOW)
    drafted = await DraftTenantConfig(factory, clock, roles).execute(
        DraftConfigCommand(
            person("prac-lead-1"),
            0,
            {
                "replyWindowMinutes": 60,
                "reminderAfterMinutes": 60,
                "phoneTaskAfterMinutes": 90,
                "escalateAfterMinutes": 120,
            },
        )
    )
    for approver in ("prac-owner-1", "prac-owner-2"):
        await ApproveTenantConfig(factory, clock, roles).execute(
            ApproveConfigCommand(person(approver), drafted.version)
        )
    return drafted.version


# -- the tenant's own configuration ------------------------------------------------------------


async def test_the_tenants_configuration_reaches_the_status_and_the_audit_records_its_version(
    tenants: Tenants,
) -> None:
    version = await _config_in_force(tenants.factory_a)
    # 10:30Z (11:30 BST) answers the 10:00 prompt but not the 12:00 one. At 12:45 BST the default
    # reply window (30 minutes) has run out for the 12:00 prompt, so the figure is overdue; with the
    # tenant's 60 minutes the 12:00 prompt is still being waited for, and the figure is current.
    answered_before_the_noon_prompt = datetime(2026, 10, 23, 10, 30, tzinfo=UTC)

    in_a = await _report(
        tenants, tenants.a, effective_at=answered_before_the_noon_prompt, idempotency_key="k-a"
    )
    in_b = await _report(
        tenants, tenants.b, effective_at=answered_before_the_noon_prompt, idempotency_key="k-b"
    )

    assert in_a.status is Status.ACCEPTING
    assert in_b.status is Status.NOT_UPDATED

    async def snapshots(tx: AsyncManagedTransaction) -> dict[str, Any]:
        rows = await (
            await tx.run(
                "MATCH (e:AuditEvent) WHERE e.tenantId IN $scopes "
                "AND e.useCase = 'ReportCapacity' "
                "RETURN e.tenantId AS tenant, e.entryJson AS entry",
                scopes=run_scope_ids(),
            )
        ).data()
        return {str(row["tenant"]): str(row["entry"]) for row in rows}

    entries = await read_tx(tenants.driver, snapshots)
    assert f'"config_version":{version}' in entries[tenants.a].replace(" ", "")
    assert "config_version" not in entries[tenants.b]
