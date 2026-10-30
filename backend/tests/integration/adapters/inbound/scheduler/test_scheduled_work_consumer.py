"""The scheduled-work consumer on real Neo4j (I05, DEC-190 to DEC-195).

Each ScheduledWork is seeded through the real repository and read back in a fresh unit of work.
Handlers are recording stubs; they open their own units when they need to, as the ladder steps do,
so a consumer that held a unit around its handler would be refused here (DEC-146 item 4). The
tenant comes from the message's property, bound by TenantBoundConsumer. Synthetic ids only: no
patient data.

Two tests pin the tenancy of the scheduled-work statements (DEC-195 item 2, lesson L168): a message
for tenant A that names tenant B's work, and one work id held by both tenants. They were strict
xfails until TEN-015 converted the statements, and their markers are removed here (DEC-195 item 4).
"""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.inbound.scheduler.scheduled_work_consumer import (
    WorkHandler,
    build_scheduled_work_consumer,
)
from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.tenant_binding import NO_TENANT, UNKNOWN_TENANT
from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_uow_factory
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import current_scope_or_none
from diucs.application.work import CANCELLED, DONE, SCHEDULED, ScheduledWork, WorkKind
from diucs.bootstrap.container import TEST_NOW
from diucs.domain.errors import NotFound, ValidationFailed
from tests.support.bus import message_with_tenant
from tests.support.neo4j import count_nodes
from tests.support.tenancy import tenant_scope
from tests.support.uow import tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

DUE = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)
REFUSED = "the handler refused the scheduled work"
NOT_STORED = "no scheduled work for this message"
DISAGREE = "message and scheduled work disagree"


def _work(
    work_id: str = "work-1",
    kind: WorkKind = WorkKind.REMINDER,
    *,
    about_id: str = "communication-1",
    status: str = SCHEDULED,
) -> ScheduledWork:
    return ScheduledWork(
        id=work_id,
        kind=kind,
        due_at=DUE,
        about_id=about_id,
        sequence_number=7,
        status=status,
    )


def _message(
    work: ScheduledWork | None,
    *,
    tenant_id: str | None,
    message_id: str = "m-1",
    **payload: Any,
) -> BusMessage:
    body: dict[str, Any] = {}
    if work is not None:
        body = {"work_id": work.id, "kind": work.kind.value, "about_id": work.about_id}
    body.update(payload)
    return message_with_tenant(
        tenant_id,
        id=message_id,
        topic="scheduled.work",
        event_type="ScheduledWorkDue",
        payload=body,
    )


async def _seed(factory: UnitOfWorkFactory, *works: ScheduledWork) -> None:
    async with factory() as uow:
        for work in works:
            await uow.scheduled_work.add(work)
        await uow.commit()


async def _stored(factory: UnitOfWorkFactory, work_id: str) -> ScheduledWork:
    async with factory() as uow:
        return await uow.scheduled_work.get(work_id)


class _Recorder:
    """A handler that records the work and the scope it ran under. It can raise once per entry of
    `errors` (in order) and can run an action (which may open its own unit of work)."""

    def __init__(
        self,
        *,
        errors: list[Exception] | None = None,
        action: Callable[[ScheduledWork], Awaitable[None]] | None = None,
    ) -> None:
        self.works: list[ScheduledWork] = []
        self.scopes: list[object] = []
        self._errors = list(errors or [])
        self._action = action

    async def __call__(self, work: ScheduledWork) -> None:
        self.works.append(work)
        self.scopes.append(current_scope_or_none())
        if self._action is not None:
            await self._action(work)
        if self._errors:
            raise self._errors.pop(0)


def _consumer(
    handlers: dict[WorkKind, WorkHandler],
    factory: UnitOfWorkFactory,
    *tenants: str,
) -> Any:
    return build_scheduled_work_consumer(handlers, factory, StaticTenants(list(tenants)))


async def test_a_due_reminder_runs_its_handler_with_the_stored_work_and_is_done(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    work = _work()
    await _seed(uow_factory, work)
    handler = _Recorder()

    outcome = await _consumer({WorkKind.REMINDER: handler}, uow_factory, tenant_id).handle(
        _message(work, tenant_id=tenant_id)
    )

    assert outcome == Outcome("completed")
    assert handler.works == [work]
    assert (await _stored(uow_factory, work.id)).status == DONE


@pytest.mark.parametrize("status", [CANCELLED, DONE])
async def test_work_already_cancelled_or_done_runs_nothing_and_keeps_its_status(
    uow_factory: UnitOfWorkFactory, tenant_id: str, status: str
) -> None:
    work = _work(status=status)
    await _seed(uow_factory, work)
    handler = _Recorder()

    outcome = await _consumer({WorkKind.REMINDER: handler}, uow_factory, tenant_id).handle(
        _message(work, tenant_id=tenant_id)
    )

    assert outcome == Outcome("completed")
    assert handler.works == []
    assert (await _stored(uow_factory, work.id)).status == status


async def test_a_message_for_work_that_is_not_stored_is_dead_lettered(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    handler = _Recorder()

    outcome = await _consumer({WorkKind.REMINDER: handler}, uow_factory, tenant_id).handle(
        _message(_work("never-stored"), tenant_id=tenant_id)
    )

    assert outcome == Outcome("dead-letter", NOT_STORED)
    assert handler.works == []


async def test_a_kind_with_no_handler_is_dead_lettered_naming_the_kind_and_stays_scheduled(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    work = _work(kind=WorkKind.CLINICAL_RETURN)
    await _seed(uow_factory, work)
    handler = _Recorder()

    outcome = await _consumer({WorkKind.REMINDER: handler}, uow_factory, tenant_id).handle(
        _message(work, tenant_id=tenant_id)
    )

    assert outcome == Outcome("dead-letter", "no handler for clinical-return")
    assert handler.works == []
    assert (await _stored(uow_factory, work.id)).status == SCHEDULED


@pytest.mark.parametrize(
    "changed",
    [{"kind": "phone-task"}, {"about_id": "communication-2"}],
    ids=["kind", "subject"],
)
async def test_a_message_that_disagrees_with_the_stored_work_is_dead_lettered(
    uow_factory: UnitOfWorkFactory, tenant_id: str, changed: dict[str, str]
) -> None:
    work = _work()
    await _seed(uow_factory, work)
    handler = _Recorder()
    message = _message(work, tenant_id=tenant_id, **changed)

    outcome = await _consumer({WorkKind.REMINDER: handler}, uow_factory, tenant_id).handle(message)

    assert outcome == Outcome("dead-letter", DISAGREE)
    assert handler.works == []
    assert (await _stored(uow_factory, work.id)).status == SCHEDULED


async def test_a_payload_without_a_kind_is_dead_lettered_and_the_work_is_untouched(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    work = _work()
    await _seed(uow_factory, work)
    handler = _Recorder()
    message = BusMessage(
        id="m-1",
        topic="scheduled.work",
        event_type="ScheduledWorkDue",
        payload={"work_id": work.id, "about_id": work.about_id},
        tenant_id=tenant_id,
    )

    outcome = await _consumer({WorkKind.REMINDER: handler}, uow_factory, tenant_id).handle(message)

    assert outcome.kind == "dead-letter"
    assert handler.works == []
    assert (await _stored(uow_factory, work.id)).status == SCHEDULED


async def test_a_handler_that_raises_is_retried_and_the_work_stays_scheduled_until_it_succeeds(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    work = _work()
    await _seed(uow_factory, work)
    handler = _Recorder(errors=[RuntimeError("the store went away")])
    consumer = _consumer({WorkKind.REMINDER: handler}, uow_factory, tenant_id)
    message = _message(work, tenant_id=tenant_id)

    first = await consumer.handle(message)
    assert first == Outcome("retry", "RuntimeError")
    assert (await _stored(uow_factory, work.id)).status == SCHEDULED

    second = await consumer.handle(message)
    assert second == Outcome("completed")
    assert len(handler.works) == 2
    assert (await _stored(uow_factory, work.id)).status == DONE


@pytest.mark.parametrize(
    "error",
    [NotFound("the service has gone"), ValidationFailed("field", "is out of range")],
    ids=["not-found", "validation"],
)
async def test_a_handler_that_refuses_the_work_is_dead_lettered_with_a_fixed_text(
    uow_factory: UnitOfWorkFactory, tenant_id: str, error: Exception
) -> None:
    work = _work()
    await _seed(uow_factory, work)
    handler = _Recorder(errors=[error])

    outcome = await _consumer({WorkKind.REMINDER: handler}, uow_factory, tenant_id).handle(
        _message(work, tenant_id=tenant_id)
    )

    assert outcome == Outcome("dead-letter", REFUSED)
    assert (await _stored(uow_factory, work.id)).status == SCHEDULED


async def test_a_redelivered_message_is_a_duplicate_and_the_handler_does_not_run_again(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    work = _work()
    await _seed(uow_factory, work)
    handler = _Recorder()
    consumer = _consumer({WorkKind.REMINDER: handler}, uow_factory, tenant_id)
    message = _message(work, tenant_id=tenant_id)

    assert (await consumer.handle(message)).kind == "completed"
    assert (await consumer.handle(message)).kind == "duplicate"
    assert len(handler.works) == 1


async def test_a_cancel_made_while_the_handler_runs_is_kept(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    work = _work()
    await _seed(uow_factory, work)

    async def cancel(stored: ScheduledWork) -> None:
        # The handler opens its own unit, which is only possible because the consumer holds none.
        async with uow_factory() as uow:
            current = await uow.scheduled_work.get(stored.id)
            await uow.scheduled_work.save(replace(current, status=CANCELLED))
            await uow.commit()

    handler = _Recorder(action=cancel)

    outcome = await _consumer({WorkKind.REMINDER: handler}, uow_factory, tenant_id).handle(
        _message(work, tenant_id=tenant_id)
    )

    assert outcome == Outcome("completed")
    assert len(handler.works) == 1
    assert (await _stored(uow_factory, work.id)).status == CANCELLED


async def test_a_poison_message_does_not_stop_the_next_one(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    work = _work()
    await _seed(uow_factory, work)
    handler = _Recorder()
    consumer = _consumer({WorkKind.REMINDER: handler}, uow_factory, tenant_id)

    poison = await consumer.handle(_message(_work("never-stored"), tenant_id=tenant_id))
    good = await consumer.handle(_message(work, tenant_id=tenant_id, message_id="m-2"))

    assert poison == Outcome("dead-letter", NOT_STORED)
    assert good == Outcome("completed")
    assert handler.works == [work]


async def test_the_scope_is_the_message_tenant_while_the_handler_runs_and_is_restored_after_a_raise(
    uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    work = _work()
    await _seed(uow_factory, work)
    before = current_scope_or_none()
    handler = _Recorder(errors=[RuntimeError("boom")])

    outcome = await _consumer({WorkKind.REMINDER: handler}, uow_factory, tenant_id).handle(
        _message(work, tenant_id=tenant_id)
    )

    assert outcome == Outcome("retry", "RuntimeError")
    assert handler.scopes == [tenant_scope(tenant_id)]
    assert current_scope_or_none() == before


async def test_a_message_with_no_tenant_or_an_unlisted_one_runs_nothing(
    uow_factory: UnitOfWorkFactory, tenant_id: str, other_tenant_id: str
) -> None:
    work = _work()
    await _seed(uow_factory, work)
    handler = _Recorder()
    consumer = _consumer({WorkKind.REMINDER: handler}, uow_factory, tenant_id)

    no_tenant = await consumer.handle(_message(work, tenant_id=None))
    unlisted = await consumer.handle(_message(work, tenant_id=other_tenant_id, message_id="m-2"))

    assert no_tenant == Outcome("dead-letter", NO_TENANT)
    assert unlisted == Outcome("dead-letter", UNKNOWN_TENANT)
    assert handler.works == []
    assert (await _stored(uow_factory, work.id)).status == SCHEDULED


async def test_each_tenant_runs_its_own_work_under_its_own_scope(
    tenant_id: str, other_tenant_id: str, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    driver = neo4j_driver
    factory = neo4j_uow_factory(driver, clock=FixedClock(TEST_NOW))
    work_a = _work("work-a")
    work_b = _work("work-b", WorkKind.PHONE_TASK)
    await _seed(tenant_uow_factory(driver, tenant_id, FixedClock(TEST_NOW)), work_a)
    await _seed(tenant_uow_factory(driver, other_tenant_id, FixedClock(TEST_NOW)), work_b)
    handler = _Recorder()
    consumer = build_scheduled_work_consumer(
        {WorkKind.REMINDER: handler, WorkKind.PHONE_TASK: handler},
        factory,
        StaticTenants([tenant_id, other_tenant_id]),
    )

    a = await consumer.handle(_message(work_a, tenant_id=tenant_id, message_id="m-a"))
    b = await consumer.handle(_message(work_b, tenant_id=other_tenant_id, message_id="m-b"))

    assert [a.kind, b.kind] == ["completed", "completed"]
    assert [w.id for w in handler.works] == ["work-a", "work-b"]
    assert handler.scopes == [tenant_scope(tenant_id), tenant_scope(other_tenant_id)]
    assert await count_nodes(driver, "ScheduledWork") == 2


async def test_a_message_for_tenant_a_naming_tenant_bs_work_is_not_found(
    tenant_id: str, other_tenant_id: str, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    driver = neo4j_driver
    factory = neo4j_uow_factory(driver, clock=FixedClock(TEST_NOW))
    work_b = _work("work-b")
    await _seed(tenant_uow_factory(driver, other_tenant_id, FixedClock(TEST_NOW)), work_b)
    handler = _Recorder()

    outcome = await _consumer({WorkKind.REMINDER: handler}, factory, tenant_id).handle(
        _message(work_b, tenant_id=tenant_id)
    )

    assert outcome == Outcome("dead-letter", NOT_STORED)
    assert handler.works == []


async def test_one_work_id_in_two_tenants_is_two_jobs(
    tenant_id: str, other_tenant_id: str, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    driver = neo4j_driver
    factory = neo4j_uow_factory(driver, clock=FixedClock(TEST_NOW))
    await _seed(
        tenant_uow_factory(driver, tenant_id, FixedClock(TEST_NOW)),
        _work("work-same", WorkKind.REMINDER),
    )
    await _seed(
        tenant_uow_factory(driver, other_tenant_id, FixedClock(TEST_NOW)),
        _work("work-same", WorkKind.PHONE_TASK),
    )
    handler = _Recorder()
    consumer = build_scheduled_work_consumer(
        {WorkKind.REMINDER: handler, WorkKind.PHONE_TASK: handler},
        factory,
        StaticTenants([tenant_id, other_tenant_id]),
    )

    await consumer.handle(_message(_work("work-same"), tenant_id=tenant_id, message_id="m-a"))
    await consumer.handle(
        _message(
            _work("work-same", WorkKind.PHONE_TASK), tenant_id=other_tenant_id, message_id="m-b"
        )
    )

    assert [w.kind for w in handler.works] == [WorkKind.REMINDER, WorkKind.PHONE_TASK]
