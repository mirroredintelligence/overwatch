"""The idempotent consumer core on real Neo4j (I04, DEC-012). Handlers write a TestMark node
through the unit of work's own transaction, so a commit or a rollback is visible in the graph."""

from typing import Any, cast

import pytest

from diucs.adapters.inbound.workers.consumer import (
    TENANT_MISMATCH,
    IdempotentConsumer,
    PermanentError,
)
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import count_nodes, node_props
from tests.support.uow import tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _message(message_id: str = "m-1", tenant: str = ACTOR_TENANT) -> BusMessage:
    """A message of the run tenant, the scope the harness binds around each test (TEN-025: a
    message whose tenant is not the bound scope is dead-lettered)."""
    return BusMessage(
        id=message_id,
        topic="capacity.events",
        event_type="CapacityReported",
        payload={},
        tenant_id=tenant,
    )


async def _mark(uow: UnitOfWork, message: BusMessage) -> None:
    tx: Any = cast(Any, uow)._tx
    await tx.run(
        "CREATE (:TestMark {messageId: $id, tenantId: $tenant})",
        id=message.id,
        tenant=message.tenant_id,
    )


class _Recorder:
    def __init__(self, fail_after_write: Exception | None = None, fail_first: int = 0) -> None:
        self.calls = 0
        self._fail_after_write = fail_after_write
        self._fail_first = fail_first

    async def __call__(self, message: BusMessage, uow: UnitOfWork) -> None:
        self.calls += 1
        await _mark(uow, message)
        if self._fail_after_write is not None and self.calls <= max(self._fail_first, 1):
            raise self._fail_after_write


async def test_a_new_message_runs_the_handler_once_and_commits_both_nodes(
    uow_factory: UnitOfWorkFactory, neo4j_driver: Any
) -> None:
    handler = _Recorder()
    consumer = IdempotentConsumer("board-projector", handler, uow_factory)
    outcome = await consumer.handle(_message())
    assert outcome.kind == "completed"
    assert handler.calls == 1
    assert await count_nodes(neo4j_driver, "Processed") == 1
    assert await count_nodes(neo4j_driver, "TestMark") == 1
    props = await node_props(neo4j_driver, "Processed", messageId="m-1")
    assert props["consumer"] == "board-projector"


async def test_the_same_id_again_is_a_duplicate_and_the_handler_does_not_run(
    uow_factory: UnitOfWorkFactory, neo4j_driver: Any
) -> None:
    handler = _Recorder()
    consumer = IdempotentConsumer("board-projector", handler, uow_factory)
    await consumer.handle(_message())
    outcome = await consumer.handle(_message())
    assert outcome.kind == "duplicate"
    assert handler.calls == 1
    assert await count_nodes(neo4j_driver, "Processed") == 1
    assert await count_nodes(neo4j_driver, "TestMark") == 1


async def test_the_same_id_for_another_consumer_runs_that_consumers_handler(
    uow_factory: UnitOfWorkFactory, neo4j_driver: Any
) -> None:
    first, second = _Recorder(), _Recorder()
    await IdempotentConsumer("board-projector", first, uow_factory).handle(_message())
    outcome = await IdempotentConsumer("alert-evaluator", second, uow_factory).handle(_message())
    assert outcome.kind == "completed"
    assert (first.calls, second.calls) == (1, 1)
    assert await count_nodes(neo4j_driver, "Processed") == 2


async def test_a_permanent_error_dead_letters_and_leaves_nothing_behind(
    uow_factory: UnitOfWorkFactory, neo4j_driver: Any
) -> None:
    handler = _Recorder(fail_after_write=PermanentError("unknown kind"))
    outcome = await IdempotentConsumer("c", handler, uow_factory).handle(_message())
    assert outcome.kind == "dead-letter"
    assert outcome.reason == "unknown kind"
    assert await count_nodes(neo4j_driver, "Processed") == 0
    assert await count_nodes(neo4j_driver, "TestMark") == 0


async def test_any_other_error_retries_commits_nothing_and_a_second_delivery_succeeds(
    uow_factory: UnitOfWorkFactory, neo4j_driver: Any
) -> None:
    handler = _Recorder(fail_after_write=RuntimeError("boom with 4821"), fail_first=1)
    consumer = IdempotentConsumer("c", handler, uow_factory)
    first = await consumer.handle(_message())
    assert first.kind == "retry"
    assert first.reason == "RuntimeError"
    assert await count_nodes(neo4j_driver, "Processed") == 0
    assert await count_nodes(neo4j_driver, "TestMark") == 0
    second = await consumer.handle(_message())
    assert second.kind == "completed"
    assert handler.calls == 2
    assert await count_nodes(neo4j_driver, "Processed") == 1
    assert await count_nodes(neo4j_driver, "TestMark") == 1


async def test_a_write_followed_by_an_error_is_rolled_back(
    uow_factory: UnitOfWorkFactory, neo4j_driver: Any
) -> None:
    handler = _Recorder(fail_after_write=RuntimeError("late"))
    await IdempotentConsumer("c", handler, uow_factory).handle(_message())
    assert await count_nodes(neo4j_driver, "TestMark") == 0


async def test_a_long_permanent_reason_is_cut_short(
    uow_factory: UnitOfWorkFactory,
) -> None:
    async def handler(message: BusMessage, uow: UnitOfWork) -> None:
        raise PermanentError("x" * 500)

    outcome = await IdempotentConsumer("c", handler, uow_factory).handle(_message())
    assert outcome.kind == "dead-letter"
    assert outcome.reason is not None
    assert len(outcome.reason) <= 100


# -- the tenant (TEN-025) ------------------------------------------------------------------------


async def test_a_message_of_another_tenant_than_the_bound_one_is_dead_lettered_and_marks_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: Any, other_tenant_id: str
) -> None:
    handler = _Recorder()
    outcome = await IdempotentConsumer("c", handler, uow_factory).handle(
        _message(tenant=other_tenant_id)
    )

    assert outcome.kind == "dead-letter"
    assert outcome.reason == TENANT_MISMATCH
    assert handler.calls == 0
    assert await count_nodes(neo4j_driver, "Processed") == 0
    assert await count_nodes(neo4j_driver, "TestMark") == 0


async def test_a_unit_that_opens_under_another_tenant_than_the_message_marks_nothing(
    neo4j_driver: Any, tenant_id: str, other_tenant_id: str
) -> None:
    """The scope bound for the work and the scope of the unit disagree (a wiring fault): the
    message is refused before it is marked, and the handler never runs in the other tenant."""
    handler = _Recorder()
    consumer = IdempotentConsumer("c", handler, tenant_uow_factory(neo4j_driver, other_tenant_id))

    outcome = await consumer.handle(_message(tenant=tenant_id))

    assert outcome.kind == "dead-letter"
    assert outcome.reason == TENANT_MISMATCH
    assert handler.calls == 0
    assert await count_nodes(neo4j_driver, "Processed") == 0


@pytest.mark.no_tenant
async def test_with_no_tenant_bound_a_message_is_dead_lettered_and_no_unit_opens(
    uow_factory: UnitOfWorkFactory, neo4j_driver: Any, tenant_id: str
) -> None:
    handler = _Recorder()

    outcome = await IdempotentConsumer("c", handler, uow_factory).handle(_message())

    assert outcome.kind == "dead-letter"
    assert outcome.reason == TENANT_MISMATCH
    assert handler.calls == 0
    assert await count_nodes(neo4j_driver, "Processed", tenant=tenant_id) == 0
