"""Integration tests for the idempotency store and processed-message markers (P15, DEC-012).

They run against the throwaway Neo4j the F10 harness starts for the session, in real transactions.
Each test asserts on what was committed, read back in a fresh session. Synthetic values only.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import ConstraintError
from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store.idempotency_store import (
    DriverIdempotencyStore,
    Neo4jIdempotencyStore,
    Neo4jProcessedMessages,
)
from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import current_tenant
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.scoped import scoped

pytestmark = pytest.mark.asyncio(loop_scope="session")

AT = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)


def _result(action: str = "report-capacity") -> AuditEntry:
    return AuditEntry(
        action=action,
        use_case="ReportCapacity",
        actor=Actor(
            role=Role.REPORTER,
            practitioner_id=None,
            device_id="dev-sms-1",
            channel="text",
            service_ids=frozenset({"svc-ucr-west"}),
            tenant_id=ACTOR_TENANT,
        ),
        entity_ids=("obs-1",),
        snapshot=None,
        at=AT,
    )


async def test_a_committed_result_is_returned_by_a_fresh_unit_of_work(
    uow_factory: UnitOfWorkFactory,
) -> None:
    async with uow_factory() as uow:
        await uow.idempotency.put("cmd-1", _result())
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.idempotency.get("cmd-1") == _result()
        await uow.commit()


async def test_a_put_that_is_not_committed_is_not_seen(
    uow_factory: UnitOfWorkFactory,
) -> None:
    async with uow_factory() as uow:
        await uow.idempotency.put("cmd-2", _result())
    async with uow_factory() as uow:
        assert await uow.idempotency.get("cmd-2") is None
        await uow.commit()


async def test_a_key_never_put_is_none(uow_factory: UnitOfWorkFactory) -> None:
    async with uow_factory() as uow:
        assert await uow.idempotency.get("never-put") is None
        await uow.commit()


async def test_a_second_put_of_the_same_result_is_a_no_op(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    for _ in range(2):
        async with uow_factory() as uow:
            await uow.idempotency.put("cmd-3", _result())
            await uow.commit()
    assert await count_nodes(neo4j_driver, "IdempotencyRecord") == 1


async def test_a_second_put_with_a_different_result_is_refused_and_the_first_is_kept(
    uow_factory: UnitOfWorkFactory,
) -> None:
    async with uow_factory() as uow:
        await uow.idempotency.put("cmd-4", _result("first"))
        await uow.commit()
    async with uow_factory() as uow:
        with pytest.raises(Conflict):
            await uow.idempotency.put("cmd-4", _result("second"))
        await uow.rollback()
    async with uow_factory() as uow:
        assert await uow.idempotency.get("cmd-4") == _result("first")
        await uow.commit()


async def test_a_refused_put_cannot_be_committed_even_if_the_caller_swallows_the_conflict(
    uow_factory: UnitOfWorkFactory,
) -> None:
    async with uow_factory() as uow:
        await uow.idempotency.put("cmd-5", _result("first"))
        await uow.commit()
    async with uow_factory() as uow:
        with pytest.raises(Conflict):
            await uow.idempotency.put("cmd-5", _result("second"))
        with pytest.raises(Conflict):
            await uow.commit()
    async with uow_factory() as uow:
        assert await uow.idempotency.get("cmd-5") == _result("first")
        await uow.commit()


async def test_a_racing_put_waits_for_a_held_put_and_is_refused(
    neo4j_driver: AsyncDriver,
) -> None:
    """Held transaction (lesson L94): the second put must wait for the first, then be refused."""
    first_session = neo4j_driver.session()
    first_tx = scoped(await first_session.begin_transaction())
    try:
        await Neo4jIdempotencyStore(first_tx).put("cmd-6", _result("first"))

        async def second() -> None:
            async with neo4j_driver.session() as session:
                tx = scoped(await session.begin_transaction())
                try:
                    await Neo4jIdempotencyStore(tx).put("cmd-6", _result("second"))
                except BaseException:
                    await tx.rollback()
                    raise
                await tx.commit()

        task = asyncio.create_task(second())
        await asyncio.sleep(1)
        assert not task.done(), "the second put must wait for the held put"
        await first_tx.commit()
        with pytest.raises(Conflict):
            await task
    finally:
        await first_session.close()
    assert await count_nodes(neo4j_driver, "IdempotencyRecord") == 1


async def test_sixteen_racing_puts_for_one_key_leave_one_record(
    neo4j_driver: AsyncDriver,
) -> None:
    async def racer(index: int) -> str:
        async with neo4j_driver.session() as session:
            tx = scoped(await session.begin_transaction())
            try:
                await Neo4jIdempotencyStore(tx).put("cmd-7", _result(f"racer-{index}"))
            except Conflict:
                await tx.rollback()
                return "refused"
            await tx.commit()
            return "committed"

    outcomes = await asyncio.gather(*(racer(i) for i in range(16)))
    assert outcomes.count("committed") == 1
    assert await count_nodes(neo4j_driver, "IdempotencyRecord") == 1


async def test_the_driver_store_puts_and_gets_in_its_own_transactions(
    neo4j_driver: AsyncDriver,
) -> None:
    store = DriverIdempotencyStore(neo4j_driver)
    await store.put("cmd-8", _result())
    assert await store.get("cmd-8") == _result()
    assert await store.get("cmd-unknown") is None


async def test_no_stored_node_holds_a_map_a_list_of_maps_or_a_json_string(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    async with uow_factory() as uow:
        await uow.idempotency.put("cmd-9", _result())
        await uow.processed.mark_if_new("m-schema", "reply-processor")
        await uow.commit()

    async def values(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (n {tenantId: $tenant}) WHERE n:IdempotencyRecord OR n:IdempotencyValue OR "
            "n:Processed "
            "RETURN properties(n) AS props"
        )
        return [dict(row["props"]) for row in await result.data()]

    rows = await read_tx(neo4j_driver, values)
    assert rows
    for props in rows:
        for value in props.values():
            assert not isinstance(value, dict)
            if isinstance(value, list):
                assert not any(isinstance(item, dict) for item in value)
            if isinstance(value, str):
                assert not value.lstrip().startswith(("{", "["))
    record = await node_props(neo4j_driver, "IdempotencyRecord", key="cmd-9")
    assert isinstance(record["createdAt"], DateTime)


async def test_a_message_is_processed_once_per_consumer(
    uow_factory: UnitOfWorkFactory,
) -> None:
    async with uow_factory() as uow:
        assert await uow.processed.mark_if_new("m1", "reply-processor") is True
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.processed.mark_if_new("m1", "reply-processor") is False
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.processed.mark_if_new("m1", "board-projector") is True
        await uow.commit()


@pytest.mark.parametrize(
    ("first", "second"),
    [(("a|b", "c"), ("a", "b|c")), (("x", "1:y"), ("1:x", "y"))],
)
async def test_markers_do_not_collide_when_the_separator_appears_in_the_values(
    uow_factory: UnitOfWorkFactory, first: tuple[str, str], second: tuple[str, str]
) -> None:
    async with uow_factory() as uow:
        assert await uow.processed.mark_if_new(*first) is True
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.processed.mark_if_new(*second) is True
        await uow.commit()


async def test_sixteen_racing_marks_for_one_message_let_exactly_one_win(
    uow_factory: UnitOfWorkFactory,
) -> None:
    async def racer() -> str:
        try:
            async with uow_factory() as uow:
                created = await uow.processed.mark_if_new("m2", "c")
                await uow.commit()
                return "created" if created else "already"
        except Conflict:
            return "refused"

    outcomes = await asyncio.gather(*(racer() for _ in range(16)))
    assert outcomes.count("created") == 1
    assert outcomes.count("already") == 15


async def test_a_racing_mark_waits_for_a_held_mark_and_leaves_one_marker(
    neo4j_driver: AsyncDriver,
) -> None:
    """Held transaction (lesson L94): without the unique key the second mark makes a second node."""
    first_session = neo4j_driver.session()
    first_tx = scoped(await first_session.begin_transaction())
    try:
        assert await Neo4jProcessedMessages(first_tx).mark_if_new("m3", "c") is True

        async def second() -> bool:
            async with neo4j_driver.session() as session:
                tx = scoped(await session.begin_transaction())
                try:
                    created = await Neo4jProcessedMessages(tx).mark_if_new("m3", "c")
                except BaseException:
                    await tx.rollback()
                    raise
                await tx.commit()
                return created

        task = asyncio.create_task(second())
        await asyncio.sleep(1)
        assert not task.done(), "the second mark must wait for the held mark"
        await first_tx.commit()
        # The MERGE waits for the held mark, then matches the committed marker: not new.
        assert await task is False
    finally:
        await first_session.close()
    assert await count_nodes(neo4j_driver, "Processed") == 1


async def test_a_processed_marker_records_the_time_as_a_datetime(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    async with uow_factory() as uow:
        await uow.processed.mark_if_new("m4", "c")
        await uow.commit()
    marker = await node_props(neo4j_driver, "Processed", messageId="m4")
    assert marker
    assert isinstance(marker["processedAt"], DateTime)


async def test_a_colon_in_either_value_cannot_make_two_pairs_share_a_marker(
    uow_factory: UnitOfWorkFactory,
) -> None:
    async with uow_factory() as uow:
        assert await uow.processed.mark_if_new("a:b", "c") is True
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.processed.mark_if_new("a", "b:c") is True
        await uow.commit()


async def test_an_instant_in_a_result_is_stored_as_a_neo4j_datetime(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    async with uow_factory() as uow:
        await uow.idempotency.put("cmd-10", _result())
        await uow.commit()

    async def instants(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (v:IdempotencyValue {kind: 'instant', tenantId: $tenant}) RETURN properties(v) "
            "AS props"
        )
        return [dict(row["props"]) for row in await result.data()]

    rows = await read_tx(neo4j_driver, instants)
    assert len(rows) == 1
    assert isinstance(rows[0]["at"], DateTime)
    assert "text" not in rows[0]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (("a:b", "c"), ("a", "b:c")),  # equal as message:consumer
        (("a:b", "c"), ("b", "c:a")),  # equal as consumer:message
        (("ab", "c"), ("a", "bc")),  # equal as message+consumer, no separator
        (("b", "ca"), ("ab", "c")),  # equal as consumer+message, no separator
    ],
)
async def test_pairs_whose_unprefixed_text_is_equal_keep_separate_markers(
    uow_factory: UnitOfWorkFactory, first: tuple[str, str], second: tuple[str, str]
) -> None:
    async with uow_factory() as uow:
        assert await uow.processed.mark_if_new(*first) is True
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.processed.mark_if_new(*second) is True
        await uow.commit()


async def _create_processed(tx: AsyncManagedTransaction, key: str) -> None:
    result = await tx.run(
        "CREATE (:Processed {key: $key, tenantId: $tenant})", key=key, tenant=current_tenant()
    )
    await result.consume()


async def _create_record(tx: AsyncManagedTransaction, key: str) -> None:
    result = await tx.run(
        "CREATE (:IdempotencyRecord {key: $key, tenantId: $tenant})",
        key=key,
        tenant=current_tenant(),
    )
    await result.consume()


async def test_a_raw_second_create_of_a_processed_key_is_refused_by_the_database(
    neo4j_driver: AsyncDriver,
) -> None:
    await write_tx(neo4j_driver, lambda tx: _create_processed(tx, "raw-processed"))
    with pytest.raises(ConstraintError):
        await write_tx(neo4j_driver, lambda tx: _create_processed(tx, "raw-processed"))


async def test_a_raw_second_create_of_a_record_key_is_refused_by_the_database(
    neo4j_driver: AsyncDriver,
) -> None:
    await write_tx(neo4j_driver, lambda tx: _create_record(tx, "raw-record"))
    with pytest.raises(ConstraintError):
        await write_tx(neo4j_driver, lambda tx: _create_record(tx, "raw-record"))


# --- seen: has this consumer marked this message? (I08, DEC-165) ---------------------------------


async def test_a_message_is_not_seen_until_it_is_marked_and_then_it_is(
    uow_factory: UnitOfWorkFactory,
) -> None:
    async with uow_factory() as uow:
        assert await uow.processed.seen("m5", "c") is False
    async with uow_factory() as uow:
        await uow.processed.mark_if_new("m5", "c")
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.processed.seen("m5", "c") is True


async def test_seen_is_per_consumer_and_per_message(uow_factory: UnitOfWorkFactory) -> None:
    async with uow_factory() as uow:
        await uow.processed.mark_if_new("m6", "c")
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.processed.seen("m6", "other") is False
        assert await uow.processed.seen("m7", "c") is False
        assert await uow.processed.seen("m6", "c") is True


async def test_seen_writes_nothing_and_a_mark_that_was_rolled_back_is_not_seen(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    async with uow_factory() as uow:
        await uow.processed.mark_if_new("m8", "c")
        await uow.rollback()
    async with uow_factory() as uow:
        assert await uow.processed.seen("m8", "c") is False
        await uow.commit()
    assert await count_nodes(neo4j_driver, "Processed") == 0


async def test_a_colon_in_either_value_cannot_make_seen_answer_for_another_pair(
    uow_factory: UnitOfWorkFactory,
) -> None:
    async with uow_factory() as uow:
        await uow.processed.mark_if_new("a:b", "c")
        await uow.commit()
    async with uow_factory() as uow:
        assert await uow.processed.seen("a", "b:c") is False
        assert await uow.processed.seen("a:b", "c") is True


async def test_seen_asks_only_in_the_bound_tenant(
    uow_factory_a: UnitOfWorkFactory, uow_factory_b: UnitOfWorkFactory
) -> None:
    """The same message and consumer are marked in tenant A, and are not seen by tenant B."""
    async with uow_factory_a() as uow:
        await uow.processed.mark_if_new("m9", "c")
        await uow.commit()
    async with uow_factory_b() as uow:
        assert await uow.processed.seen("m9", "c") is False
    async with uow_factory_a() as uow:
        assert await uow.processed.seen("m9", "c") is True
