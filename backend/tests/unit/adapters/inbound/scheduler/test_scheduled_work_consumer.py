"""The scheduled-work consumer without Neo4j (I05, DEC-190 to DEC-192): a message that cannot be
read is dead-lettered before any store is opened, the dispatcher runs the handler of the work's
kind and names a kind it has none for, and a message with no tenant never reaches the consumer."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.inbound.scheduler.scheduled_work_consumer import (
    CONSUMER_NAME,
    EVENT_TYPE,
    ScheduledWorkConsumer,
    ScheduledWorkDispatcher,
    WorkHandler,
    build_scheduled_work_consumer,
)
from diucs.adapters.inbound.workers.consumer import PermanentError
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.tenant_binding import NO_TENANT, TenantBoundConsumer
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.work import SCHEDULED, ScheduledWork, WorkKind
from tests.support.bus import message_with_tenant

DUE = datetime(2026, 10, 23, 11, 0, tzinfo=UTC)


def _work(kind: WorkKind = WorkKind.REMINDER) -> ScheduledWork:
    return ScheduledWork(
        id="work-1",
        kind=kind,
        due_at=DUE,
        about_id="communication-1",
        sequence_number=None,
        status=SCHEDULED,
    )


def _payload(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"work_id": "work-1", "kind": "reminder", "about_id": "c-1"}
    payload.update(changes)
    return payload


def _message(
    payload: Mapping[str, Any] | None = None,
    *,
    tenant_id: str | None = "tenant-a",
    event_type: str = EVENT_TYPE,
) -> BusMessage:
    # The tenant is set without the constructor's check, so a test can hand the consumer a message
    # with none (defence in depth; a validated BusMessage always has one, TEN-020).
    return message_with_tenant(
        tenant_id,
        id="m-1",
        topic="scheduled.work",
        event_type=event_type,
        payload=dict(_payload() if payload is None else payload),
    )


class _NoStore:
    """A unit of work factory that fails the test if anything opens one."""

    def __call__(self) -> Any:
        raise AssertionError("a unit of work was opened for a message that cannot run")


class _Handler:
    def __init__(self) -> None:
        self.works: list[ScheduledWork] = []

    async def __call__(self, work: ScheduledWork) -> None:
        self.works.append(work)


def test_the_consumer_is_named_scheduler_and_the_event_is_scheduled_work_due() -> None:
    assert CONSUMER_NAME == "scheduler"
    assert EVENT_TYPE == "ScheduledWorkDue"


async def test_the_dispatcher_runs_the_handler_of_the_work_kind_with_the_work() -> None:
    handler = _Handler()
    dispatcher = ScheduledWorkDispatcher({WorkKind.REMINDER: handler})

    await dispatcher(_work())

    assert handler.works == [_work()]


async def test_the_dispatcher_refuses_a_kind_with_no_handler_by_naming_it() -> None:
    dispatcher = ScheduledWorkDispatcher({WorkKind.REMINDER: _Handler()})

    with pytest.raises(PermanentError, match="no handler for phone-task"):
        await dispatcher(_work(WorkKind.PHONE_TASK))


def test_the_dispatcher_exposes_its_table_and_its_kinds_read_only() -> None:
    handler: WorkHandler = _Handler()
    dispatcher = ScheduledWorkDispatcher({WorkKind.REMINDER: handler})

    assert dispatcher.kinds == frozenset({WorkKind.REMINDER})
    assert dict(dispatcher.handlers) == {WorkKind.REMINDER: handler}
    with pytest.raises(TypeError):
        dispatcher.handlers[WorkKind.PHONE_TASK] = handler  # type: ignore[index]


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "reminder", "about_id": "c-1"},
        {"work_id": "work-1", "about_id": "c-1"},
        {"work_id": "work-1", "kind": "reminder"},
        _payload(work_id=""),
        _payload(work_id=7),
        _payload(kind="not-a-kind"),
        _payload(about_id=None),
    ],
)
async def test_a_payload_that_cannot_be_read_is_dead_lettered_before_any_store_opens(
    payload: dict[str, Any],
) -> None:
    consumer = ScheduledWorkConsumer(ScheduledWorkDispatcher({}), _NoStore())  # type: ignore[arg-type]

    outcome = await consumer.handle(_message(payload))

    assert outcome.kind == "dead-letter"
    assert outcome.reason is not None
    assert "work-1" not in outcome.reason


async def test_a_message_of_another_event_type_is_dead_lettered_before_any_store_opens() -> None:
    consumer = ScheduledWorkConsumer(ScheduledWorkDispatcher({}), _NoStore())  # type: ignore[arg-type]

    outcome = await consumer.handle(_message(event_type="SmsReceived"))

    assert outcome.kind == "dead-letter"


async def test_a_message_with_no_tenant_never_reaches_the_consumer() -> None:
    consumer = build_scheduled_work_consumer(
        {WorkKind.REMINDER: _Handler()},
        _NoStore(),  # type: ignore[arg-type]
        StaticTenants(["tenant-a"]),
    )

    outcome = await consumer.handle(_message(tenant_id=None))

    assert outcome.kind == "dead-letter"
    assert outcome.reason == NO_TENANT


def test_the_scheduler_is_the_tenant_bound_consumer_of_the_scheduled_work_consumer() -> None:
    consumer = build_scheduled_work_consumer(
        {WorkKind.REMINDER: _Handler()},
        _NoStore(),  # type: ignore[arg-type]
        StaticTenants(["tenant-a"]),
    )

    assert isinstance(consumer, TenantBoundConsumer)
    assert isinstance(consumer._inner, ScheduledWorkConsumer)  # type: ignore[attr-defined]
