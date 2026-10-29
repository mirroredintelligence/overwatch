"""The missed-report ladder run by the scheduled-work consumer on real Neo4j (I05, U06, DEC-192).

The service is "Virtual ward · frailty", prompted at 12:00 London (Friday 23 October 2026, BST)
with nobody answering. Each step's ScheduledWork is handed to the consumer as a ScheduledWorkDue
message, with the clock at the step's time, and the step's own effect is read back from Neo4j. A
ladder step opens its own units of work, so this also proves the consumer holds none around a
handler (DEC-190). Synthetic values only: no patient data, no real phone number.
"""

from collections.abc import Awaitable, Callable

import pytest
from neo4j import AsyncDriver

from diucs.adapters.inbound.scheduler.scheduled_work_consumer import build_scheduled_work_consumer
from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.tenant_binding import TenantBoundConsumer
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.work import CANCELLED, DONE, WorkKind
from diucs.bootstrap.container import ladder_handlers
from tests.support.ladder_rig import (
    PHONE_HASH_1,
    Rig,
    build_rig,
    london,
    reporter,
    seed_people,
    seed_report,
    virtual_ward,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

Seed = Callable[..., Awaitable[None]]
FIGURE_AT = london(10, 5)


@pytest.fixture
def rig(uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str) -> Rig:
    return build_rig(uow_factory, neo4j_driver, tenant_id)


async def _prompted(rig: Rig, seed_service: Seed) -> str:
    """The service, its reporter, a figure, and the 12:00 prompt. Returns the prompt's id, which
    is the subject of the ladder."""
    await seed_service(virtual_ward())
    await seed_people(rig.factory, reporter(1, PHONE_HASH_1))
    await seed_report(rig.factory, FIGURE_AT)
    result = await rig.prompt(london(12, 0))
    assert result.sent is True
    [prompt_id] = result.communication_ids
    return prompt_id


def _message(rig: Rig, work_id: str, kind: WorkKind, about_id: str) -> BusMessage:
    return BusMessage(
        id=f"due-{work_id}",
        topic="scheduled.work",
        event_type="ScheduledWorkDue",
        payload={"work_id": work_id, "kind": kind.value, "about_id": about_id},
        tenant_id=rig.tenant,
    )


def _consumer(rig: Rig) -> TenantBoundConsumer:
    return build_scheduled_work_consumer(
        ladder_handlers(rig.ladder), rig.factory, StaticTenants([rig.tenant])
    )


async def _outbox_count(rig: Rig, event_type: str) -> int:
    return len(await rig.events(event_type))


@pytest.mark.parametrize(
    ("kind", "effect"),
    [
        (WorkKind.REMINDER, "SendMessage"),
        (WorkKind.PHONE_TASK, "PhoneTaskRaised"),
        (WorkKind.ESCALATE_TO_LEAD, "ReportEscalated"),
    ],
)
async def test_a_due_ladder_step_is_run_by_the_consumer_and_its_work_is_done(
    rig: Rig, seed_service: Seed, kind: WorkKind, effect: str
) -> None:
    prompt_id = await _prompted(rig, seed_service)
    work = await rig.work(prompt_id, kind)
    before = await _outbox_count(rig, effect)
    rig.clock.set(work.due_at)

    outcome = await _consumer(rig).handle(_message(rig, work.id, kind, work.about_id))

    assert outcome == Outcome("completed")
    assert await _outbox_count(rig, effect) == before + 1
    [stored] = await rig.works(prompt_id, kind)
    assert stored.status == DONE


async def test_a_step_whose_ladder_a_report_has_answered_is_stopped_and_completed(
    rig: Rig, seed_service: Seed
) -> None:
    prompt_id = await _prompted(rig, seed_service)
    reminder = await rig.work(prompt_id, WorkKind.REMINDER)
    await rig.report(london(12, 20))  # answers the 12:00 prompt; its ladder is cancelled
    [cancelled] = await rig.works(prompt_id, WorkKind.REMINDER)
    assert cancelled.status == CANCELLED
    before = await _outbox_count(rig, "SendMessage")
    rig.clock.set(reminder.due_at)

    outcome = await _consumer(rig).handle(_message(rig, reminder.id, WorkKind.REMINDER, prompt_id))

    assert outcome == Outcome("completed")
    assert await _outbox_count(rig, "SendMessage") == before
