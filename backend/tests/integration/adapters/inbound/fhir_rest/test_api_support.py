"""The test container's clock and unit of work (R01 test 10)."""

from datetime import UTC, datetime

from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.bootstrap.container import Container
from diucs.domain.codes import ReportSource
from diucs.domain.events import CapacityReported
from tests.support.neo4j import read_tx

FIXED_NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)


async def stored_outbox_ids(tx: AsyncManagedTransaction) -> list[str]:
    result = await tx.run(
        "MATCH (m:OutboxMessage {tenantId: $tenant}) RETURN m.id AS id ORDER BY id"
    )
    return [record["id"] for record in await result.data()]


async def test_the_test_container_clock_is_the_r01_test_instant(
    test_container: Container,
) -> None:
    assert test_container.clock.now() == FIXED_NOW


async def test_a_unit_of_work_from_the_test_container_writes_to_neo4j(
    test_container: Container, neo4j_driver: AsyncDriver
) -> None:
    event = CapacityReported(
        service_id="svc-ucr-west",
        report_id="rep-api-1",
        value=8,
        source=ReportSource.TEXT,
        at=FIXED_NOW,
    )
    async with test_container.uow_factory() as uow:
        await uow.outbox.add(outbox_message_for(event, id="out-api-1", now=FIXED_NOW))
        await uow.commit()

    assert await read_tx(neo4j_driver, stored_outbox_ids) == ["out-api-1"]
