"""Integration tests for the Neo4j outbox (P06, DEC-012, DEC-001), on the F10 harness Neo4j.

Each message is written in one unit of work and read back through a fresh one. Values are
synthetic; the payloads use the shapes that the domain events produce.
"""

from datetime import UTC, datetime

import pytest
from neo4j import AsyncDriver
from neo4j.time import DateTime

from diucs.application.ports.outbound.outbox import MAX_ATTEMPTS, OutboxMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.errors import Conflict, NotFound
from tests.support.neo4j import count_nodes, node_props

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)


def _message(message_id: str, minute: int = 0, payload: dict | None = None) -> OutboxMessage:
    return OutboxMessage(
        id=message_id,
        topic="capacity.events",
        event_type="CapacityReported",
        payload=payload
        if payload is not None
        else {
            "service_id": "svc-ucr-west",
            "report_id": "rep-1",
            "value": 8,
            "at": "2026-10-23T13:00:00Z",
        },
        created_at=datetime(2026, 10, 23, 9, minute, tzinfo=UTC),
        session_id="svc-ucr-west",
    )


async def _add(uow_factory: UnitOfWorkFactory, *messages: OutboxMessage) -> None:
    async with uow_factory() as uow:
        for message in messages:
            await uow.outbox.add(message)
        await uow.commit()


async def _pending(uow_factory: UnitOfWorkFactory, limit: int = 100) -> list[OutboxMessage]:
    async with uow_factory() as uow:
        return await uow.outbox.pending(limit)


async def test_pending_lists_the_oldest_message_first(uow_factory: UnitOfWorkFactory) -> None:
    await _add(
        uow_factory, _message("out-late", 2), _message("out-early", 0), _message("out-mid", 1)
    )

    ids = [message.id for message in await _pending(uow_factory)]

    assert ids == ["out-early", "out-mid", "out-late"]


async def test_pending_returns_at_most_the_limit(uow_factory: UnitOfWorkFactory) -> None:
    await _add(uow_factory, _message("out-1", 0), _message("out-2", 1), _message("out-3", 2))

    assert [m.id for m in await _pending(uow_factory, limit=2)] == ["out-1", "out-2"]


async def test_a_message_round_trips_with_its_payload_and_session(
    uow_factory: UnitOfWorkFactory,
) -> None:
    payload = {
        "service_id": "svc-ucr-west",
        "value": 8,
        "flag": True,
        "note": None,
        "at": "2026-10-23T13:00:00Z",
        "fraction": "2026-10-23T13:00:00.500000Z",
    }
    await _add(uow_factory, _message("out-1", payload=payload))

    (loaded,) = await _pending(uow_factory)

    assert loaded.payload == payload
    assert loaded.session_id == "svc-ucr-west"
    assert loaded.created_at == datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
    assert loaded.status == "pending"
    assert loaded.attempts == 0


async def test_times_in_a_payload_are_stored_as_datetimes_and_nothing_is_json(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    await _add(uow_factory, _message("out-1"))

    props = await node_props(neo4j_driver, "OutboxMessage", id="out-1")

    assert isinstance(props["payload_at"], DateTime)
    assert props["payload_at"].to_native() == datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
    for name, value in props.items():
        assert not isinstance(value, dict), name
        assert not (isinstance(value, str) and value[:1] in "{["), name


async def test_a_failed_attempt_counts_and_stays_pending_until_the_tenth(
    uow_factory: UnitOfWorkFactory,
) -> None:
    await _add(uow_factory, _message("out-1"))

    async with uow_factory() as uow:
        await uow.outbox.mark_failed("out-1", "queue unavailable")
        await uow.outbox.mark_failed("out-1", "queue unavailable")
        await uow.commit()

    (after_two,) = await _pending(uow_factory)
    assert after_two.attempts == 2
    assert after_two.status == "pending"


async def test_the_tenth_failed_attempt_makes_the_message_dead(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    await _add(uow_factory, _message("out-1"))

    async with uow_factory() as uow:
        for _ in range(MAX_ATTEMPTS):
            await uow.outbox.mark_failed("out-1", "queue unavailable")
        await uow.commit()

    assert await _pending(uow_factory) == []
    props = await node_props(neo4j_driver, "OutboxMessage", id="out-1")
    assert props["status"] == "dead"
    assert props["attempts"] == MAX_ATTEMPTS


async def test_a_published_message_leaves_the_pending_list(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    await _add(uow_factory, _message("out-1"), _message("out-2", 1))

    async with uow_factory() as uow:
        await uow.outbox.mark_published("out-1", NOW)
        await uow.commit()

    assert [m.id for m in await _pending(uow_factory)] == ["out-2"]
    props = await node_props(neo4j_driver, "OutboxMessage", id="out-1")
    assert props["status"] == "published"
    assert props["publishedAt"].to_native() == NOW


async def test_a_repeated_message_id_is_refused_and_stores_nothing_twice(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    await _add(uow_factory, _message("out-1"))

    with pytest.raises(Conflict):
        await _add(uow_factory, _message("out-1", 5))

    assert await count_nodes(neo4j_driver, "OutboxMessage") == 1


async def test_marking_an_unknown_message_is_not_found(uow_factory: UnitOfWorkFactory) -> None:
    async with uow_factory() as uow:
        with pytest.raises(NotFound):
            await uow.outbox.mark_published("out-missing", NOW)
        await uow.rollback()
