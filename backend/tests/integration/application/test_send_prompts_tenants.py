"""Two-tenant tests for SendPrompts (TEN-027, DEC-130 to DEC-134, DEC-500; reworks U03 and U04).

Tenant A and tenant B each run a service of one id, with the same reporter ids, figure and prompt
time. What is proved, on a graph that holds both:

- each tenant's link is on its own host, its token is a node of its own tenant, and the sealed
  content opens only with its own tenant as associated data;
- the tenant's zone is asked for the scope the unit is bound to, and the times in the text are that
  tenant's local times (A is given New York, which the rules accept; B is London);
- the tenant's policy is its own: A's configuration gives a 60 minute reply window and a slower
  ladder, B keeps the defaults, and neither sees the other's;
- a prompt for a service only B has reads exactly as one for an id nobody has (`NotFound`), takes no
  lock and writes nothing in either tenant;
- one prompt key used in both tenants is two prompts, and an identical replay in one tenant is the
  first result;
- a tenant named in the constructor that is not the bound one is refused before anything is read.

Runs on the harness database (the shared schema is the contracted schema since TEN-032).
Synthetic values only. Written in build wave 5 and not run
there: the full integration run follows on the merged tip.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor, system_actor
from diucs.application.ports.outbound.tokens import LinkTokenRepository, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, TenantMismatch, TenantNotBound
from diucs.application.use_cases.send_prompts import SendPromptCommand, SendPrompts, prompt_key
from diucs.application.use_cases.tenant_config import (
    ApproveConfigCommand,
    ApproveTenantConfig,
    DraftConfigCommand,
    DraftTenantConfig,
)
from diucs.application.work import WorkKind
from diucs.domain.codes import Role
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.service import AvailableTime
from tests.support.ladder_rig import (
    PHONE_HASH_1,
    SECRET,
    london,
    reporter,
    seed_people,
    seed_report,
    virtual_ward,
)
from tests.support.neo4j import read_tx
from tests.support.tenancy import as_tenant
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICE = "vw-west"
NEW_YORK = ZoneInfo("America/New_York")
LONDON_ZONE = ZoneInfo("Europe/London")
DUE = london(12, 0)  # 11:00 UTC: 12:00 in London, 07:00 in New York
# Open from 02:00 to 23:00 so the due time is in hours in both zones.
PROFILE = virtual_ward(SERVICE, available_times=(AvailableTime.every_day(time(2, 0), time(23, 0)),))


class _Bases:
    """A link base for each tenant, by the scope the unit is bound to."""

    def __init__(self, bases: dict[str, str]) -> None:
        self._bases = bases
        self.asked: list[ScopeId] = []

    async def link_base_url(self, scope: ScopeId) -> str:
        self.asked.append(scope)
        return self._bases[scope.value]


class _Zones:
    def __init__(self, zones: dict[str, ZoneInfo]) -> None:
        self._zones = zones
        self.asked: list[ScopeId] = []

    async def zone_of(self, scope: ScopeId) -> ZoneInfo:
        self.asked.append(scope)
        return self._zones[scope.value]


@dataclass
class Tenants:
    driver: AsyncDriver
    a: str
    b: str
    factory_a: UnitOfWorkFactory
    factory_b: UnitOfWorkFactory
    bases: _Bases
    zones: _Zones
    clock: FixedClock

    def factory(self, tenant: str) -> UnitOfWorkFactory:
        return self.factory_a if tenant == self.a else self.factory_b

    def sender(self, tenant: str, **extra: Any) -> SendPrompts:
        factory = self.factory(tenant)

        def tokens(repo: LinkTokenRepository) -> LinkTokenService:
            return LinkTokenService(repo, FixedSecretStore({"link-token": SECRET}), self.clock)

        return SendPrompts(
            factory,
            self.clock,
            SequentialIds.scoped(tenant),
            DriverIdempotencyStore(self.driver),
            tokens,
            self.bases,
            AesGcmContentSealer(FixedSecretStore({"link-token": SECRET})),
            zones=self.zones,
            **extra,
        )

    async def prompt(self, tenant: str, **fields: Any) -> Any:
        base: dict[str, Any] = {
            "idempotency_key": prompt_key(SERVICE, DUE),
            "actor": system_actor(tenant, "scheduler"),
            "service_id": SERVICE,
            "due_at": DUE,
        }
        with as_tenant(tenant):
            return await self.sender(tenant).execute(SendPromptCommand(**{**base, **fields}))

    async def sends(self, tenant: str) -> list[Any]:
        async with self.factory(tenant)() as uow:
            return [m for m in await uow.outbox.pending(limit=100) if m.event_type == "SendMessage"]

    def opened(self, tenant: str, message: Any) -> dict[str, Any]:
        sealer = AesGcmContentSealer(FixedSecretStore({"link-token": SECRET}))
        opened: dict[str, Any] = json.loads(
            sealer.unseal(
                message.payload["sealed_content"],
                message_id=message.id,
                tenant_id=tenant,
                recipient_role_id=message.payload["recipient_role_id"],
            )
        )
        return opened


async def _seed(factory: UnitOfWorkFactory) -> None:
    async with factory() as uow:
        await uow.services.save(PROFILE)
        await uow.commit()
    await seed_people(factory, reporter(1, PHONE_HASH_1, SERVICE))
    await seed_report(factory, london(10, 5), service_id=SERVICE)


@pytest_asyncio.fixture(loop_scope="session")
async def tenants(
    neo4j_driver: AsyncDriver, clean_graph: None, tenant_id: str, other_tenant_id: str
) -> AsyncIterator[Tenants]:
    driver = neo4j_driver  # the run's scopes were wiped, and both tenants have audit heads
    await ensure_audit_heads(driver, tenant_id, other_tenant_id)
    factory_a = tenant_uow_factory(driver, tenant_id)
    factory_b = tenant_uow_factory(driver, other_tenant_id)
    await _seed(factory_a)
    await _seed(factory_b)
    yield Tenants(
        driver,
        tenant_id,
        other_tenant_id,
        factory_a,
        factory_b,
        _Bases(
            {
                tenant_id: "https://a.example.org/l",
                other_tenant_id: "https://b.example.org/l",
            }
        ),
        _Zones({tenant_id: NEW_YORK, other_tenant_id: LONDON_ZONE}),
        FixedClock(DUE),
    )


async def _count(tenants: Tenants, tenant: str, label: str) -> int:
    async def work(tx: AsyncManagedTransaction) -> int:
        record = await (
            await tx.run(
                f"MATCH (n:`{label}` {{tenantId: $tenant}}) RETURN count(n) AS total", tenant=tenant
            )
        ).single()
        assert record is not None
        return int(record["total"])

    return await read_tx(tenants.driver, work)


async def _written(tenants: Tenants, tenant: str) -> dict[str, int]:
    return {
        label: await _count(tenants, tenant, label)
        for label in (
            "Communication",
            "OutboxMessage",
            "ScheduledWork",
            "LinkToken",
            "AuditEvent",
            "IdempotencyRecord",
        )
    }


# -- the link ----------------------------------------------------------------------------------


async def test_each_tenants_link_is_on_its_own_host_and_its_token_is_its_own(
    tenants: Tenants,
) -> None:
    result_a = await tenants.prompt(tenants.a)
    result_b = await tenants.prompt(tenants.b)

    assert result_a.sent and result_b.sent
    [send_a] = await tenants.sends(tenants.a)
    [send_b] = await tenants.sends(tenants.b)
    text_a = tenants.opened(tenants.a, send_a)["text"]
    text_b = tenants.opened(tenants.b, send_b)["text"]
    assert "https://a.example.org/l/" in text_a and "b.example.org" not in text_a
    assert "https://b.example.org/l/" in text_b and "a.example.org" not in text_b
    assert await _count(tenants, tenants.a, "LinkToken") == 1
    assert await _count(tenants, tenants.b, "LinkToken") == 1
    assert [s.value for s in tenants.bases.asked] == [tenants.a, tenants.b]


async def test_the_sealed_content_opens_only_for_its_own_tenant(tenants: Tenants) -> None:
    await tenants.prompt(tenants.a)
    [send_a] = await tenants.sends(tenants.a)
    sealer = AesGcmContentSealer(FixedSecretStore({"link-token": SECRET}))

    with pytest.raises(ValidationFailed):
        sealer.unseal(
            send_a.payload["sealed_content"],
            message_id=send_a.id,
            tenant_id=tenants.b,
            recipient_role_id=send_a.payload["recipient_role_id"],
        )
    assert tenants.opened(tenants.a, send_a)["text"]


# -- the zone and the policy -------------------------------------------------------------------


async def test_the_zone_is_asked_for_the_bound_scope_and_the_text_is_in_that_zone(
    tenants: Tenants,
) -> None:
    await tenants.prompt(tenants.a)
    await tenants.prompt(tenants.b)

    assert [s.value for s in tenants.zones.asked] == [tenants.a, tenants.b]
    [send_a] = await tenants.sends(tenants.a)
    [send_b] = await tenants.sends(tenants.b)
    text_a = tenants.opened(tenants.a, send_a)["text"]
    text_b = tenants.opened(tenants.b, send_b)["text"]
    # The figure was timed 10:05 London (09:05 UTC): 05:05 in New York. The reply is wanted by
    # 11:30 UTC: 12:30 in London, 07:30 in New York.
    assert "23 Oct 05:05" in text_a and "07:30" in text_a
    assert "23 Oct 10:05" in text_b and "12:30" in text_b


async def _slower_ladder(tenants: Tenants) -> None:
    """A configuration version for A approved by two people other than its author: a 60 minute
    reply window and a ladder of 60, 90 and 120 minutes."""

    def person(ref: str) -> Actor:
        return Actor(
            role=Role.OWNER,
            practitioner_id=ref,
            device_id=None,
            channel="web",
            service_ids=frozenset(),
            tenant_id=tenants.a,
        )

    roles = frozenset({Role.OWNER})
    with as_tenant(tenants.a):
        drafted = await DraftTenantConfig(tenants.factory_a, tenants.clock, roles).execute(
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
            await ApproveTenantConfig(tenants.factory_a, tenants.clock, roles).execute(
                ApproveConfigCommand(person(approver), drafted.version)
            )


async def _ladder_offsets(tenants: Tenants, tenant: str) -> dict[WorkKind, timedelta]:
    result = await tenants.prompt(tenant, idempotency_key=f"ladder-{tenant}")
    [communication] = result.communication_ids
    offsets: dict[WorkKind, timedelta] = {}
    async with tenants.factory(tenant)() as uow:
        for kind in (WorkKind.REMINDER, WorkKind.PHONE_TASK, WorkKind.ESCALATE_TO_LEAD):
            [work] = await uow.scheduled_work.for_about(communication, kind)
            offsets[kind] = work.due_at - DUE
    return offsets


async def test_the_ladder_and_the_reply_window_are_the_tenants_own(tenants: Tenants) -> None:
    await _slower_ladder(tenants)

    in_a = await _ladder_offsets(tenants, tenants.a)
    in_b = await _ladder_offsets(tenants, tenants.b)

    assert in_a == {
        WorkKind.REMINDER: timedelta(minutes=60),
        WorkKind.PHONE_TASK: timedelta(minutes=90),
        WorkKind.ESCALATE_TO_LEAD: timedelta(minutes=120),
    }
    assert in_b == {
        WorkKind.REMINDER: timedelta(minutes=30),
        WorkKind.PHONE_TASK: timedelta(minutes=60),
        WorkKind.ESCALATE_TO_LEAD: timedelta(minutes=90),
    }
    [send_a] = await tenants.sends(tenants.a)
    # A's prompt is answerable for A's 60 minutes: until 12:00 UTC, which is 08:00 in New York.
    assert "08:00" in tenants.opened(tenants.a, send_a)["text"]


# -- another tenant's service ------------------------------------------------------------------


async def test_a_service_only_the_other_tenant_has_reads_as_an_id_nobody_has(
    tenants: Tenants,
) -> None:
    async with tenants.factory_b() as uow:
        await uow.services.save(replace(PROFILE, id="only-b", name="Only B"))
        await uow.commit()
    before_a = await _written(tenants, tenants.a)
    before_b = await _written(tenants, tenants.b)

    with pytest.raises(NotFound) as foreign:
        await tenants.prompt(tenants.a, service_id="only-b", idempotency_key="k-foreign")
    with pytest.raises(NotFound) as random:
        await tenants.prompt(tenants.a, service_id="nobody-has-this", idempotency_key="k-random")

    assert type(foreign.value) is type(random.value)
    assert str(foreign.value) == str(random.value)
    assert await _written(tenants, tenants.a) == before_a
    assert await _written(tenants, tenants.b) == before_b


# -- the prompt key ----------------------------------------------------------------------------


async def test_one_prompt_key_in_two_tenants_is_two_prompts(tenants: Tenants) -> None:
    first = await tenants.prompt(tenants.a)
    second = await tenants.prompt(tenants.b)

    assert not first.replayed and not second.replayed
    assert await _count(tenants, tenants.a, "Communication") == 1
    assert await _count(tenants, tenants.b, "Communication") == 1


async def test_an_identical_replay_in_one_tenant_is_the_first_result(tenants: Tenants) -> None:
    first = await tenants.prompt(tenants.a)
    before = await _written(tenants, tenants.a)

    again = await tenants.prompt(tenants.a)

    assert again.replayed is True
    assert again.communication_ids == first.communication_ids
    assert await _written(tenants, tenants.a) == before


# -- the guard ---------------------------------------------------------------------------------


async def test_a_constructor_tenant_that_is_not_the_bound_one_is_refused_before_any_read(
    tenants: Tenants,
) -> None:
    before = await _written(tenants, tenants.a)
    sender = tenants.sender(tenants.a, tenant_id=tenants.b)
    with as_tenant(tenants.a), pytest.raises(TenantMismatch):
        await sender.execute(
            SendPromptCommand(
                idempotency_key="k-guard",
                actor=system_actor(tenants.a, "scheduler"),
                service_id=SERVICE,
                due_at=DUE,
            )
        )
    assert await _written(tenants, tenants.a) == before


async def test_an_actor_of_the_other_tenant_is_refused_before_any_read_or_write(
    tenants: Tenants,
) -> None:
    before_a = await _written(tenants, tenants.a)
    before_b = await _written(tenants, tenants.b)

    with pytest.raises(TenantMismatch):
        await tenants.prompt(tenants.a, actor=system_actor(tenants.b, "scheduler"))

    assert await _written(tenants, tenants.a) == before_a
    assert await _written(tenants, tenants.b) == before_b


async def test_an_actor_of_the_other_tenant_does_not_get_the_stored_result_of_a_replay(
    tenants: Tenants,
) -> None:
    # The early replay read is outside the unit of work: the actor is compared before it, so a
    # command of another tenant's actor never reads the first result back.
    first = await tenants.prompt(tenants.a)
    assert first.communication_ids
    before = await _written(tenants, tenants.a)

    with pytest.raises(TenantMismatch):
        await tenants.prompt(tenants.a, actor=system_actor(tenants.b, "scheduler"))

    assert await _written(tenants, tenants.a) == before


@pytest.mark.no_tenant
async def test_a_command_with_no_tenant_bound_is_refused(tenants: Tenants) -> None:
    with pytest.raises(TenantNotBound):
        await tenants.sender(tenants.a).execute(
            SendPromptCommand(
                idempotency_key="k-unbound",
                actor=system_actor(tenants.a, "scheduler"),
                service_id=SERVICE,
                due_at=DUE,
            )
        )
