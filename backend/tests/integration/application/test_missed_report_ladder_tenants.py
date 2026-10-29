"""Two-tenant tests for the missed-report ladder (U06, DEC-130 to DEC-132, DEC-142).

Tenant A and tenant B each run the same service, with the same reporter, the same prompt time and
the same figure. The ladder handler takes its tenant only from the unit of work the consumer bound
(there is no tenant on the command), so a step for A never reads, changes or sends anything of B's.

Until TEN-032 drops the single-property keys, two tenants cannot share a key on the shared test
schema (a resource id, or a Concept system such as the service-category CodeSystem url that the
domain builds, which no test can prefix). So this module runs on a private contracted container
(DEC-159, as the generated isolation test does), and each tenant's ids still carry a prefix so a
failure names its tenant. The resource store (TEN-009), the work and
communication statements (TEN-015), the person statements (TEN-011) and the capacity statements
(TEN-010) are still unconverted (tenant-pending, evidence U06). What is proved here is what the use
case itself decides: the tenant of every row, key and sealed message it writes comes from the unit
of work, and one tenant's ladder never changes another's. That a step for A given B's work id
reads as not found is proved here, since TEN-009 scopes the service lookup.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.missed_report_ladder import (
    IGNORED,
    REMINDED,
    LadderStepCommand,
)
from diucs.application.work import CANCELLED, SCHEDULED, WorkKind
from diucs.domain.errors import NotFound, ValidationFailed
from tests.support.ladder_rig import (
    PHONE_HASH_1,
    SECRET,
    SYSTEM_ACTOR,
    Rig,
    build_rig,
    london,
    reporter,
    seed_people,
    seed_report,
    virtual_ward,
)
from tests.support.neo4j import read_tx, wipe
from tests.support.tenant_seed import contracted_container
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

LADDER = (WorkKind.REMINDER, WorkKind.PHONE_TASK, WorkKind.ESCALATE_TO_LEAD)


async def _tenant_rig(
    factory: UnitOfWorkFactory, driver: AsyncDriver, tenant: str, letter: str
) -> tuple[Rig, str]:
    """A tenant with one service, one reporter and a 12:00 prompt nobody answers. Returns the rig
    and the id of the prompt communication."""
    service_id = f"vw-{letter}"
    rig = build_rig(
        factory,
        driver,
        tenant,
        service_id=service_id,
        ids=SequentialIds.scoped(tenant),
        prefix=f"{letter}-",
    )
    await ensure_audit_heads(driver, tenant)
    async with factory() as uow:
        await uow.services.save(virtual_ward(service_id))
        await uow.commit()
    await seed_people(factory, reporter(1, PHONE_HASH_1, service_id, prefix=f"{letter}-"))
    await seed_report(
        factory, london(10, 5), service_id=service_id, report_id=f"{letter}-seed-report"
    )
    result = await rig.prompt(london(12, 0))
    assert result.sent is True
    [prompt] = result.communication_ids
    return rig, prompt


async def _owners(driver: AsyncDriver, label: str) -> list[Any]:
    async def work(tx: AsyncManagedTransaction) -> list[Any]:
        result = await tx.run(f"MATCH (n:{label}) RETURN n.tenantId AS tenant")
        return [row["tenant"] for row in await result.data()]

    return await read_tx(driver, work)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    """A private Neo4j with every migration applied and the superseded single-property keys
    dropped (DEC-159). The shared harness keeps them until TEN-032, which refuses a second
    tenant's Concept or resource with the same key."""
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def neo4j_driver(two_tenant_driver: AsyncDriver) -> AsyncDriver:
    """Overrides the session driver for this module: every test here runs two tenants."""
    return two_tenant_driver


@pytest_asyncio.fixture(loop_scope="session")
async def two(two_tenant_driver: AsyncDriver) -> AsyncIterator[None]:
    await wipe(two_tenant_driver)
    yield
    await wipe(two_tenant_driver)


@pytest_asyncio.fixture(loop_scope="session")
async def tenants(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
    two: None,
) -> tuple[tuple[Rig, str], tuple[Rig, str]]:
    a = await _tenant_rig(uow_factory_a, neo4j_driver, tenant_id, "a")
    b = await _tenant_rig(uow_factory_b, neo4j_driver, other_tenant_id, "b")
    return a, b


async def test_a_step_for_tenant_a_changes_nothing_of_tenant_b(
    tenants: tuple[tuple[Rig, str], tuple[Rig, str]],
) -> None:
    (rig_a, prompt_a), (rig_b, prompt_b) = tenants
    before_b = (await rig_b.outbox(), await rig_b.works(prompt_b, WorkKind.REMINDER))

    result = await rig_a.step(prompt_a, WorkKind.REMINDER, london(12, 30))

    assert result.action == REMINDED
    assert (await rig_b.outbox(), await rig_b.works(prompt_b, WorkKind.REMINDER)) == before_b
    for kind in (WorkKind.REMINDER, WorkKind.PHONE_TASK, WorkKind.ESCALATE_TO_LEAD):
        assert (await rig_b.work(prompt_b, kind)).status == SCHEDULED
    assert await rig_b.events("StatusChanged") == []
    assert [m for m in await rig_b.events("SendMessage") if m.payload["message_id"] == "C8"] == []
    # What A's step wrote is A's alone.
    assert len(await rig_a.events("StatusChanged")) == 1
    assert {m.payload["service_id"] for m in await rig_a.events("StatusChanged")} == {"vw-a"}


async def test_the_messages_a_step_queues_belong_to_the_tenant_whose_step_it_was(
    tenants: tuple[tuple[Rig, str], tuple[Rig, str]],
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    # The relay binds each message's tenant from the row, and the row carries the tenant of the
    # unit that wrote it: work scheduled through the outbox carries its tenant (DEC-157).
    (rig_a, prompt_a), (rig_b, prompt_b) = tenants
    await rig_a.step(prompt_a, WorkKind.REMINDER, london(12, 30))
    await rig_b.step(prompt_b, WorkKind.PHONE_TASK, london(13, 0))
    await rig_a.report(london(12, 40))

    owners = await _owners(neo4j_driver, "OutboxMessage")

    assert set(owners) == {tenant_id, other_tenant_id}
    for rig in (rig_a, rig_b):
        assert {m.event_type for m in await rig.outbox()}  # each tenant sees its own rows
    assert "PhoneTaskRaised" not in {m.event_type for m in await rig_a.outbox()}
    assert "CancelWork" not in {m.event_type for m in await rig_b.outbox()}
    assert "CancelWork" in {m.event_type for m in await rig_a.outbox()}


async def test_tenant_b_work_given_to_tenant_a_is_not_found_whatever_its_state(
    tenants: tuple[tuple[Rig, str], tuple[Rig, str]],
) -> None:
    (rig_a, _prompt_a), (rig_b, prompt_b) = tenants
    scheduled = await rig_b.work(prompt_b, WorkKind.REMINDER)
    finished = await rig_b.work(prompt_b, WorkKind.PHONE_TASK)
    await rig_b.run(finished, london(13, 0))
    before = (await rig_b.outbox(), await rig_b.works(prompt_b, WorkKind.REMINDER))
    rig_a.clock.set(london(13, 30))

    for work in (scheduled, finished):
        with pytest.raises(NotFound):
            await rig_a.ladder.execute(
                LadderStepCommand(idempotency_key="k", actor=SYSTEM_ACTOR, work_id=work.id)
            )

    # A finished step reads as not found too, not as ignored, so its existence is not told.
    assert (await rig_b.outbox(), await rig_b.works(prompt_b, WorkKind.REMINDER)) == before
    assert (await rig_b.work(prompt_b, WorkKind.REMINDER)).status == SCHEDULED
    assert await rig_a.events("PhoneTaskRaised") == []


async def test_a_report_in_tenant_a_does_not_cancel_tenant_bs_ladder(
    tenants: tuple[tuple[Rig, str], tuple[Rig, str]],
) -> None:
    (rig_a, prompt_a), (rig_b, prompt_b) = tenants

    await rig_a.report(london(12, 40))

    assert {w.status for w in [await rig_a.work(prompt_a, k) for k in LADDER]} == {CANCELLED}
    assert {w.status for w in [await rig_b.work(prompt_b, k) for k in LADDER]} == {SCHEDULED}
    assert await rig_b.events("CancelWork") == []
    [next_b] = await rig_b.works("vw-b", WorkKind.PROMPT_DUE)
    assert next_b.status == SCHEDULED


async def test_the_same_command_key_in_two_tenants_is_two_commands(
    tenants: tuple[tuple[Rig, str], tuple[Rig, str]],
) -> None:
    # Q-IDEM-* is unconverted, so a replay key shared by two tenants would refuse the second
    # (lesson L160): the ladder keeps the tenant in the key it stores.
    (rig_a, prompt_a), (rig_b, prompt_b) = tenants
    work_a = await rig_a.work(prompt_a, WorkKind.REMINDER)
    work_b = await rig_b.work(prompt_b, WorkKind.REMINDER)

    first = await rig_a.run(work_a, london(12, 30), key="one-key")
    second = await rig_b.run(work_b, london(12, 30), key="one-key")

    assert (first.action, first.replayed) == (REMINDED, False)
    assert (second.action, second.replayed) == (REMINDED, False)


async def test_a_reminder_opens_only_in_its_own_tenant(
    tenants: tuple[tuple[Rig, str], tuple[Rig, str]], other_tenant_id: str
) -> None:
    (rig_a, prompt_a), _ = tenants
    await rig_a.step(prompt_a, WorkKind.REMINDER, london(12, 30))
    [message] = [m for m in await rig_a.events("SendMessage") if m.payload["message_id"] == "C8"]
    sealer = AesGcmContentSealer(FixedSecretStore({"link-token": SECRET}))

    assert "has not updated" in rig_a.opened(message)["text"]
    with pytest.raises(ValidationFailed):
        sealer.unseal(
            message.payload["sealed_content"],
            message_id=message.id,
            tenant_id=other_tenant_id,
            recipient_role_id=message.payload["recipient_role_id"],
        )


async def test_both_tenants_run_their_whole_ladders_side_by_side(
    tenants: tuple[tuple[Rig, str], tuple[Rig, str]],
) -> None:
    (rig_a, prompt_a), (rig_b, prompt_b) = tenants
    steps: list[tuple[Rig, str, WorkKind, Any]] = [
        (rig, prompt, kind, at)
        for kind, at in zip(LADDER, (london(12, 30), london(13, 0), london(13, 30)), strict=True)
        for rig, prompt in ((rig_a, prompt_a), (rig_b, prompt_b))
    ]

    actions = [(await rig.step(prompt, kind, at)).action for rig, prompt, kind, at in steps]

    assert IGNORED not in actions
    assert len(actions) == 6
    for rig in (rig_a, rig_b):
        assert len(await rig.events("PhoneTaskRaised")) == 1
        assert len(await rig.events("ReportEscalated")) == 1
        assert len(await rig.events("StatusChanged")) == 1
