"""The `prompt-due` handler of the dispatch table on the real Neo4j (B1 task 4, KI-96, KI-387,
KI-502): a scheduled `prompt-due` work row, run through the container's own dispatcher, sends the
prompt (one sealed text for the reporter, the communication, the ladder) and schedules the next
prompt, in the work's tenant and no other. Run again with the same work it does nothing (the
consumer may deliver twice). Synthetic values only; nothing is sent (the outbox is read, not
relayed).
"""

import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, time

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.work import SCHEDULED, ScheduledWork, WorkKind
from diucs.bootstrap.container import Container, build_for_tests
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    PractitionerRoleCode,
    ServiceCategory,
)
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support.neo4j import ThrowawayNeo4j
from tests.support.tenancy import as_tenant
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

Seed = Callable[..., Awaitable[None]]

DUE = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)  # 10:00 BST, inside UCR West's hours
NOW = datetime(2026, 10, 23, 9, 1, tzinfo=UTC)
SECRET = b"link-token-test-secret-0123456789abcdef"
PHONE_HASH = "ab" * 32

UCR_WEST = ServiceProfile(
    id="ucr-west",
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals in the next 2 hrs",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)


@pytest_asyncio.fixture(loop_scope="session")
async def container(
    harness_container: ThrowawayNeo4j, clean_graph: None
) -> AsyncIterator[Container]:
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        yield build_for_tests(
            clock=FixedClock(NOW),
            ids=SequentialIds(),
            neo4j=connection,
            secrets=FixedSecretStore({"link-token": SECRET}),
        )
    finally:
        await connection.close()


async def _seed_reporter(factory: UnitOfWorkFactory) -> None:
    async with factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-1", active=True, display_name="Reporter 1", phone_hash=PHONE_HASH)
        )
        await uow.people.save_role(
            PractitionerRole(
                id="role-1",
                practitioner_id="prac-1",
                service_id="ucr-west",
                code=PractitionerRoleCode.DUTY_MANAGER,
                active=True,
                channel=Channel.TEXT,
                period_start=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await uow.commit()


async def _schedule(factory: UnitOfWorkFactory, container: Container) -> ScheduledWork:
    async with factory() as uow:
        work = await schedule_work(
            uow,
            container.ids,
            kind=WorkKind.PROMPT_DUE,
            about_id="ucr-west",
            due_at=DUE,
            now=NOW,
        )
        await uow.commit()
    return work


async def _state(factory: UnitOfWorkFactory) -> tuple[int, list[ScheduledWork]]:
    async with factory() as uow:
        sent = [m for m in await uow.outbox.pending(limit=1000) if m.event_type == "SendMessage"]
        works = await uow.scheduled_work.for_about("ucr-west", None)
    return len(sent), works


async def test_the_dispatch_table_sends_the_prompt_and_schedules_the_next_one(
    container: Container, uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    await _seed_reporter(uow_factory)
    work = await _schedule(uow_factory, container)

    await container.scheduled_work(work)

    sent, works = await _state(uow_factory)
    assert sent == 1
    prompts = [w for w in works if w.kind is WorkKind.PROMPT_DUE and w.status == SCHEDULED]
    assert len(prompts) == 2  # the one just run (the consumer marks it done) and the next
    assert any(w.due_at > DUE for w in prompts)


async def test_the_same_work_run_twice_sends_one_prompt(
    container: Container, uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    await _seed_reporter(uow_factory)
    work = await _schedule(uow_factory, container)

    await container.scheduled_work(work)
    first = await _state(uow_factory)
    await container.scheduled_work(work)
    second = await _state(uow_factory)

    assert second[0] == first[0] == 1
    assert len(second[1]) == len(first[1])


async def test_another_tenants_service_of_the_same_id_is_not_prompted_by_this_work(
    container: Container,
    uow_factory: UnitOfWorkFactory,
    seed_service: Seed,
    neo4j_driver: AsyncDriver,
    other_tenant_id: str,
) -> None:
    await seed_service(UCR_WEST)
    await _seed_reporter(uow_factory)
    await seed_service(UCR_WEST, tenant=other_tenant_id)  # the other tenant has no reporter
    other = tenant_uow_factory(neo4j_driver, other_tenant_id, container.clock)
    await ensure_audit_heads(neo4j_driver, other_tenant_id)
    with as_tenant(other_tenant_id):
        work = await _schedule(other, container)
        await container.scheduled_work(work)
        other_sent, _ = await _state(other)

    own_sent, _ = await _state(uow_factory)
    assert (own_sent, other_sent) == (0, 0)  # B has nobody to text, A was never run


async def test_a_service_with_no_one_to_text_is_skipped_and_the_chain_goes_on(
    container: Container, uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await seed_service(dataclasses.replace(UCR_WEST))
    work = await _schedule(uow_factory, container)

    await container.scheduled_work(work)

    sent, works = await _state(uow_factory)
    assert sent == 0
    assert len([w for w in works if w.kind is WorkKind.PROMPT_DUE]) == 2
