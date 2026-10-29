"""Integration tests for the clinical request repository (P18), against the F10 harness Neo4j.

Each write is one committed transaction and each read is a fresh session. Values are synthetic;
there is no patient data, and no note text is written anywhere.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.clinical_request_repository import (
    Neo4jClinicalRequestRepository,
)
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.domain.model.clinical import ClinicalAdvice, ClinicalRequestRecord
from diucs.domain.rules.clinical_queue import ClinicalRequest, give_advice, return_if_idle, take
from tests.support.neo4j import node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip

pytestmark = pytest.mark.asyncio(loop_scope="session")

REQUESTED = datetime(2026, 10, 25, 13, 13, tzinfo=UTC)
TAKEN = datetime(2026, 10, 25, 13, 14, tzinfo=UTC)
ADVISED = datetime(2026, 10, 25, 13, 16, tzinfo=UTC)


def _record(request: ClinicalRequest, advice: ClinicalAdvice | None = None) -> ClinicalRequestRecord:
    return ClinicalRequestRecord(
        request=request, requester_id="adv-1", why="borderline criteria", snapshot_ref=None,
        advice=advice,
    )


WAITING = _record(
    ClinicalRequest(id="req-1", case_id="case-1", urgency="now", requested_at=REQUESTED)
)


async def _seed(driver: AsyncDriver) -> None:
    """The case the request is about, and the advisers, written through the store."""

    async def work(tx: AsyncManagedTransaction) -> None:
        store = ResourceStore(tx)
        await store.put({"resourceType": "Practitioner", "id": "adv-1", "active": True}, None)
        await store.put({"resourceType": "Practitioner", "id": "clin-1", "active": True}, None)
        await store.put({"resourceType": "ServiceRequest", "id": "case-1", "status": "active",
                         "intent": "order"}, None)

    await write_tx(driver, work)


async def _save(driver: AsyncDriver, *records: ClinicalRequestRecord) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = Neo4jClinicalRequestRepository(tx, ResourceStore(tx))
        for record in records:
            if await repo.get(record.request.id) is None:
                await repo.add(record)
            else:
                await repo.save(record)

    await write_tx(driver, work)


async def _read(driver: AsyncDriver, step: Any) -> Any:
    return await read_tx(driver, lambda tx: step(Neo4jClinicalRequestRepository(tx, ResourceStore(tx))))


@pytest.fixture
async def seeded(neo4j_driver: AsyncDriver) -> None:
    await _seed(neo4j_driver)


async def test_a_waiting_request_round_trips(neo4j_driver: AsyncDriver, seeded: None) -> None:
    await assert_round_trip(
        neo4j_driver,
        lambda tx: Neo4jClinicalRequestRepository(tx, ResourceStore(tx)).add(WAITING),
        lambda tx: Neo4jClinicalRequestRepository(tx, ResourceStore(tx)).get("req-1"),
        WAITING,
    )


async def test_the_waiting_queue_is_now_first_then_oldest_first(
    neo4j_driver: AsyncDriver, seeded: None
) -> None:
    within = _record(
        ClinicalRequest(id="req-a", case_id="case-1", urgency="within-15-min",
                        requested_at=datetime(2026, 10, 25, 13, 8, tzinfo=UTC))
    )
    now_late = _record(
        ClinicalRequest(id="req-b", case_id="case-1", urgency="now",
                        requested_at=datetime(2026, 10, 25, 13, 13, tzinfo=UTC))
    )
    now_early = _record(
        ClinicalRequest(id="req-c", case_id="case-1", urgency="now",
                        requested_at=datetime(2026, 10, 25, 13, 10, tzinfo=UTC))
    )
    await _save(neo4j_driver, within, now_late, now_early)

    waiting = await _read(neo4j_driver, lambda repo: repo.waiting())
    assert [r.request.id for r in waiting] == ["req-c", "req-b", "req-a"]


async def test_a_taken_request_leaves_the_queue_and_joins_the_takers_list(
    neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await _save(neo4j_driver, WAITING)
    taken = _record(take(WAITING.request, "clin-1", TAKEN))
    await _save(neo4j_driver, taken)

    assert await _read(neo4j_driver, lambda repo: repo.waiting()) == []
    taken_list = await _read(neo4j_driver, lambda repo: repo.taken_by("clin-1"))
    assert [r.request.id for r in taken_list] == ["req-1"]
    task = await read_tx(neo4j_driver, lambda tx: ResourceStore(tx).get("Task", "req-1"))
    assert task is not None
    assert task["owner"] == {"reference": "Practitioner/clin-1"}


async def test_advice_is_stored_as_a_handle_and_never_as_text(
    neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await _save(neo4j_driver, WAITING)
    taken = _record(take(WAITING.request, "clin-1", TAKEN))
    await _save(neo4j_driver, taken)
    advice = ClinicalAdvice(
        choice="go-ahead", reason="within-criteria", note_handle="h-123",
        clinician_id="clin-1", at=ADVISED,
    )
    advised = _record(give_advice(taken.request, "clin-1", ADVISED), advice=advice)

    await assert_round_trip(
        neo4j_driver,
        lambda tx: Neo4jClinicalRequestRepository(tx, ResourceStore(tx)).save(advised),
        lambda tx: Neo4jClinicalRequestRepository(tx, ResourceStore(tx)).get("req-1"),
        advised,
    )
    props = await node_props(neo4j_driver, "Task", id="req-1")
    assert props["businessStatus"] == "advised"
    assert props["noteHandle"] == "h-123"
    assert "go-ahead" in props.values()
    assert all("they were" not in str(value) for value in props.values())


async def test_a_request_returned_to_the_queue_is_waiting_again(
    neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await _save(neo4j_driver, WAITING)
    taken = _record(take(WAITING.request, "clin-1", TAKEN))
    await _save(neo4j_driver, taken)
    later = datetime(2026, 10, 25, 13, 30, tzinfo=UTC)
    released = _record(return_if_idle(taken.request, later))
    await _save(neo4j_driver, released)

    waiting = await _read(neo4j_driver, lambda repo: repo.waiting())
    assert [r.request.id for r in waiting] == ["req-1"]
    task = await read_tx(neo4j_driver, lambda tx: ResourceStore(tx).get("Task", "req-1"))
    assert task is not None
    assert "owner" not in task


async def test_an_unknown_request_is_none(neo4j_driver: AsyncDriver, seeded: None) -> None:
    assert await _read(neo4j_driver, lambda repo: repo.get("missing")) is None
