"""Integration tests for the service move store (P20), against the F10 harness Neo4j.

Values are synthetic: the phone is a hash, never a number.
"""

from datetime import UTC, datetime

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_move_repository import Neo4jServiceMoveRepository
from diucs.adapters.outbound.graph_store.service_repository import codeable_to_fhir
from diucs.domain.codes import ServiceCategory
from diucs.domain.errors import Conflict
from diucs.domain.model.service_move import ServiceMove
from tests.support.neo4j import read_tx, write_tx
from tests.support.round_trip import assert_round_trip

pytestmark = pytest.mark.asyncio(loop_scope="session")

UNTIL = datetime(2026, 10, 25, 19, 0, tzinfo=UTC)
MOVE = ServiceMove(
    id="move-1",
    service_id="svc-ucr-east",
    from_practitioner_id="p-1",
    to_phone_hash="h9",
    until=UNTIL,
)


async def _seed(driver: AsyncDriver) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        store = ResourceStore(tx)
        await store.put(
            {
                "resourceType": "HealthcareService",
                "id": "svc-ucr-east",
                "active": True,
                "name": "UCR East",
                "category": codeable_to_fhir(ServiceCategory.URGENT_COMMUNITY_RESPONSE),
            },
            None,
        )
        await store.put({"resourceType": "Practitioner", "id": "p-1", "active": True}, None)

    await write_tx(driver, work)


@pytest.fixture
async def seeded(neo4j_driver: AsyncDriver, clean_graph: None) -> None:
    await _seed(neo4j_driver)


async def test_a_move_round_trips(neo4j_driver: AsyncDriver, seeded: None) -> None:
    await assert_round_trip(
        neo4j_driver,
        lambda tx: Neo4jServiceMoveRepository(tx).add(MOVE),
        lambda tx: Neo4jServiceMoveRepository(tx).get("move-1"),
        MOVE,
    )


async def test_one_open_move_per_service(neo4j_driver: AsyncDriver, seeded: None) -> None:
    await write_tx(neo4j_driver, lambda tx: Neo4jServiceMoveRepository(tx).add(MOVE))

    second = ServiceMove(
        id="move-2",
        service_id="svc-ucr-east",
        from_practitioner_id="p-1",
        to_phone_hash="h10",
        until=UNTIL,
    )
    with pytest.raises(Conflict):
        await write_tx(neo4j_driver, lambda tx: Neo4jServiceMoveRepository(tx).add(second))

    completed = ServiceMove(
        id="move-1",
        service_id="svc-ucr-east",
        from_practitioner_id="p-1",
        to_phone_hash="h9",
        until=UNTIL,
        completed_at=datetime(2026, 10, 25, 18, 30, tzinfo=UTC),
    )
    await write_tx(neo4j_driver, lambda tx: Neo4jServiceMoveRepository(tx).save(completed))
    await write_tx(neo4j_driver, lambda tx: Neo4jServiceMoveRepository(tx).add(second))

    open_moves = await read_tx(
        neo4j_driver,
        lambda tx: Neo4jServiceMoveRepository(tx).open_for_service("svc-ucr-east"),
    )
    assert [move.id for move in open_moves] == ["move-2"]
