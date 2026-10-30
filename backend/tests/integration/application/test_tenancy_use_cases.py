"""The use-case differential over the delivered capacity use cases, and the held-lock timing test
(TEN-027, DEC-130 to DEC-134, DEC-500; audit B TEN-A12 and E TEN-E22).

For each use case that takes an id from outside, two tenants are seeded and the same call is made as
tenant A twice: with an id only tenant B holds, and with an id nobody holds. The two answers must be
indistinguishable (the same exception type and text), nothing is written in either tenant, and no
lock is taken: a lock tenant B holds on its own record does not delay A's call, while a lock A holds
on A's own record does (the control, so the timing test can tell a lock from none).

The use cases: ReportCapacity (U01), ConfirmCapacity (U02), SendPrompts (U03), MissedReportLadder
(U06), SuspendService and ResumeService (U36). A use case added later joins `CASES`.

Runs on contracted_container() (DEC-159). Synthetic values only. Written in build wave 5 and not run
there: the full integration run follows on the merged tip.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import time
from typing import Any

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
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity, ConfirmCapacityCommand
from diucs.application.use_cases.missed_report_ladder import LadderStepCommand, MissedReportLadder
from diucs.application.use_cases.report_capacity import ReportCapacity, ReportCapacityCommand
from diucs.application.use_cases.send_prompts import SendPromptCommand, SendPrompts, prompt_key
from diucs.application.use_cases.suspend_service import (
    ResumeService,
    ResumeServiceCommand,
    SuspendService,
    SuspendServiceCommand,
)
from diucs.application.work import WorkKind
from diucs.domain.codes import ReportSource, Role
from diucs.domain.errors import DomainError
from diucs.domain.model.service import AvailableTime
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from tests.support.ladder_rig import (
    PHONE_HASH_1,
    SECRET,
    london,
    reporter,
    seed_people,
    seed_report,
    virtual_ward,
)
from tests.support.neo4j import read_tx, wipe
from tests.support.tenancy import as_tenant
from tests.support.tenant_seed import contracted_container
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

OWN = "svc-own"  # a service of tenant A (the control)
ONLY_B = "svc-only-b"  # a service of tenant B only
NOBODY = "svc-nobody-has-this"
DUE = london(12, 0)
LOCK_WAIT = 1.0  # a call that waits on a lock is still waiting after this many seconds
FAST = 10.0  # a call that takes no lock answers well inside this


@dataclass
class World:
    driver: AsyncDriver
    a: str
    b: str
    factory_a: UnitOfWorkFactory
    factory_b: UnitOfWorkFactory
    clock: FixedClock
    work_b: str  # a scheduled ladder step of tenant B

    def factory(self, tenant: str) -> UnitOfWorkFactory:
        return self.factory_a if tenant == self.a else self.factory_b


def _lead(tenant: str) -> Actor:
    return Actor(
        role=Role.LEAD,
        practitioner_id="prac-lead",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def _advisor(tenant: str) -> Actor:
    return Actor(
        role=Role.ADVISOR,
        practitioner_id="prac-advisor",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


async def _seed(factory: UnitOfWorkFactory, service_id: str) -> None:
    async with factory() as uow:
        await uow.services.save(
            virtual_ward(
                service_id, available_times=(AvailableTime.every_day(time(2, 0), time(23, 0)),)
            )
        )
        await uow.commit()
    await seed_people(factory, reporter(1, PHONE_HASH_1, service_id))
    await seed_report(factory, london(10, 5), service_id=service_id, report_id=f"{service_id}-seed")


def _tokens(clock: FixedClock) -> Callable[[LinkTokenRepository], LinkTokenService]:
    def make(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, FixedSecretStore({"link-token": SECRET}), clock)

    return make


@pytest_asyncio.fixture(loop_scope="session")
async def world(tenant_id: str, other_tenant_id: str) -> AsyncIterator[World]:
    async with contracted_container() as driver:
        await wipe(driver)
        await ensure_audit_heads(driver, tenant_id, other_tenant_id)
        factory_a = tenant_uow_factory(driver, tenant_id)
        factory_b = tenant_uow_factory(driver, other_tenant_id)
        await _seed(factory_a, OWN)
        await _seed(factory_b, ONLY_B)
        clock = FixedClock(DUE)
        # A ladder step of B: a prompt for B's service, so B holds a scheduled reminder.
        with as_tenant(other_tenant_id):
            sent = await SendPrompts(
                factory_b,
                clock,
                SequentialIds.scoped(other_tenant_id),
                DriverIdempotencyStore(driver),
                _tokens(clock),
                "diucs.example",
                AesGcmContentSealer(FixedSecretStore({"link-token": SECRET})),
            ).execute(
                SendPromptCommand(
                    idempotency_key=prompt_key(ONLY_B, DUE),
                    actor=system_actor(other_tenant_id, "scheduler"),
                    service_id=ONLY_B,
                    due_at=DUE,
                )
            )
        [communication] = sent.communication_ids
        async with factory_b() as uow:
            [reminder] = await uow.scheduled_work.for_about(communication, WorkKind.REMINDER)
        yield World(driver, tenant_id, other_tenant_id, factory_a, factory_b, clock, reminder.id)


# -- the use cases, each as a call with one id --------------------------------------------------

Call = Callable[[World, str], Awaitable[Any]]


async def _report(world: World, service_id: str) -> Any:
    use_case = ReportCapacity(
        world.factory_a,
        world.clock,
        SequentialIds.scoped(world.a),
        DriverIdempotencyStore(world.driver),
    )
    with as_tenant(world.a):
        return await use_case.execute(
            ReportCapacityCommand(
                idempotency_key=f"report-{service_id}",
                actor=_advisor(world.a),
                service_id=service_id,
                value=4,
                source=ReportSource.ADVISOR_PHONED,
            )
        )


async def _confirm(world: World, service_id: str) -> Any:
    use_case = ConfirmCapacity(
        world.factory_a,
        world.clock,
        SequentialIds.scoped(world.a),
        DriverIdempotencyStore(world.driver),
    )
    with as_tenant(world.a):
        return await use_case.execute(
            ConfirmCapacityCommand(
                idempotency_key=f"confirm-{service_id}",
                actor=_advisor(world.a),
                service_id=service_id,
                source=ReportSource.ADVISOR_PHONED,
            )
        )


async def _prompt(world: World, service_id: str) -> Any:
    use_case = SendPrompts(
        world.factory_a,
        world.clock,
        SequentialIds.scoped(world.a),
        DriverIdempotencyStore(world.driver),
        _tokens(world.clock),
        "diucs.example",
        AesGcmContentSealer(FixedSecretStore({"link-token": SECRET})),
    )
    with as_tenant(world.a):
        return await use_case.execute(
            SendPromptCommand(
                idempotency_key=f"prompt-{service_id}",
                actor=system_actor(world.a, "scheduler"),
                service_id=service_id,
                due_at=DUE,
            )
        )


async def _ladder(world: World, target: str) -> Any:
    use_case = MissedReportLadder(
        world.factory_a,
        world.clock,
        SequentialIds.scoped(world.a),
        _tokens(world.clock),
        "diucs.example",
        AesGcmContentSealer(FixedSecretStore({"link-token": SECRET})),
    )
    with as_tenant(world.a):
        return await use_case.execute(
            LadderStepCommand(
                idempotency_key=f"ladder-{target}",
                actor=system_actor(world.a, "scheduler"),
                work_id=target,
            )
        )


def _suspend_use_case(world: World) -> SuspendService:
    return SuspendService(
        world.factory_a,
        DriverIdempotencyStore(world.driver),
        world.clock,
        SequentialIds.scoped(world.a),
        AesGcmContentSealer(FixedSecretStore({"link-token": SECRET})),
        lambda scope: _no_wording(),
        DEFAULT_POLICY,
    )


async def _no_wording() -> None:
    return None


async def _suspend(world: World, service_id: str) -> Any:
    with as_tenant(world.a):
        return await _suspend_use_case(world).execute(
            SuspendServiceCommand(
                idempotency_key=f"suspend-{service_id}",
                actor=_lead(world.a),
                service_id=service_id,
                reason="other",
            )
        )


async def _resume(world: World, service_id: str) -> Any:
    use_case = ResumeService(
        world.factory_a,
        DriverIdempotencyStore(world.driver),
        world.clock,
        SequentialIds.scoped(world.a),
        DEFAULT_POLICY,
    )
    with as_tenant(world.a):
        return await use_case.execute(
            ResumeServiceCommand(
                idempotency_key=f"resume-{service_id}",
                actor=_lead(world.a),
                service_id=service_id,
                phoned_register_number=True,
                reason_resolved=True,
            )
        )


@dataclass(frozen=True)
class Case:
    name: str
    call: Call
    foreign: Callable[[World], str]  # the id only tenant B holds
    random: str  # an id nobody holds
    takes_service_lock: bool  # the use case locks the service before it reads it


CASES = (
    Case("report", _report, lambda w: ONLY_B, NOBODY, True),
    Case("confirm", _confirm, lambda w: ONLY_B, NOBODY, True),
    Case("prompt", _prompt, lambda w: ONLY_B, NOBODY, False),
    Case("ladder", _ladder, lambda w: w.work_b, "work-nobody-has-this", False),
    Case("suspend", _suspend, lambda w: ONLY_B, NOBODY, False),
    Case("resume", _resume, lambda w: ONLY_B, NOBODY, False),
)
IDS = [case.name for case in CASES]
LOCKING = [case for case in CASES if case.takes_service_lock]


async def _written(world: World, tenant: str) -> dict[str, int]:
    async def work(tx: AsyncManagedTransaction) -> dict[str, int]:
        counts: dict[str, int] = {}
        for label in (
            "Observation",
            "OutboxMessage",
            "Communication",
            "ScheduledWork",
            "LinkToken",
            "AuditEvent",
            "IdempotencyRecord",
            "ServiceFlag",
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

    return await read_tx(world.driver, work)


async def _answer(call: Call, world: World, target: str) -> tuple[type, str]:
    with pytest.raises(DomainError) as refused:
        await call(world, target)
    return type(refused.value), str(refused.value)


@pytest.mark.parametrize("case", CASES, ids=IDS)
async def test_an_id_only_the_other_tenant_holds_reads_as_an_id_nobody_holds(
    world: World, case: Case
) -> None:
    before_a = await _written(world, world.a)
    before_b = await _written(world, world.b)

    foreign = await _answer(case.call, world, case.foreign(world))
    random = await _answer(case.call, world, case.random)

    assert foreign == random
    assert await _written(world, world.a) == before_a
    assert await _written(world, world.b) == before_b


# -- the held-lock timing test -----------------------------------------------------------------


async def _hold(
    factory: UnitOfWorkFactory, take: Callable[[Any], Awaitable[None]]
) -> tuple[asyncio.Task[None], asyncio.Event]:
    """Hold a lock in a task of its own (so its unit of work is not nested in the test's context)
    until the returned event is set. Returns once the lock is held."""
    locked, release = asyncio.Event(), asyncio.Event()

    async def hold() -> None:
        async with factory() as holder:
            await take(holder)
            locked.set()
            await release.wait()
            await holder.rollback()

    task = asyncio.create_task(hold())
    await asyncio.wait_for(locked.wait(), timeout=30)
    return task, release


@pytest.mark.parametrize("case", LOCKING, ids=lambda c: c.name)
async def test_a_lock_the_other_tenant_holds_does_not_delay_a_call_for_its_id(
    world: World, case: Case
) -> None:
    task, release = await _hold(world.factory_b, lambda uow: uow.capacity.lock_service(ONLY_B))
    try:
        await asyncio.wait_for(_answer(case.call, world, ONLY_B), timeout=FAST)
    finally:
        release.set()
        await task


@pytest.mark.parametrize("case", LOCKING, ids=lambda c: c.name)
async def test_a_lock_the_tenant_holds_on_its_own_service_does_delay_the_call(
    world: World, case: Case
) -> None:
    """The control: the same shape of test with A's own lock on A's own service waits, so the
    timing test above would notice a lock that crossed tenants."""
    task, release = await _hold(world.factory_a, lambda uow: uow.capacity.lock_service(OWN))
    call = asyncio.create_task(case.call(world, OWN))
    try:
        done, _ = await asyncio.wait({call}, timeout=LOCK_WAIT)
        assert not done, "the call finished while the tenant's own lock was held"
    finally:
        release.set()
        await task
    await asyncio.wait_for(call, timeout=FAST)


async def test_a_ladder_step_given_the_other_tenants_work_id_takes_no_lock(world: World) -> None:
    task, release = await _hold(world.factory_b, lambda uow: uow.capacity.lock_service(ONLY_B))
    try:
        await asyncio.wait_for(_answer(_ladder, world, world.work_b), timeout=FAST)
    finally:
        release.set()
        await task
