"""The delivery tracker keeps a receipt that arrives before the send is recorded (KI-133).

The tracker finds no Communication for the provider id, so it parks the receipt (the provider id and
the status, nothing else) and completes the message. The sender applies it in the unit of work that
records the send. A receipt for a record that is there, and one that cannot move it, parks nothing.
"""

import pytest
from neo4j import AsyncDriver

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.delivery_tracker import receipt_consumer
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from tests.integration.graph_store.test_communication_receipts import _get, _queued
from tests.support.inbound_rig import receipt_message
from tests.support.neo4j import count_nodes

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def tenants(tenant_id: str) -> StaticTenants:
    return StaticTenants([tenant_id])


async def test_a_receipt_before_the_send_is_parked_and_applied_when_the_send_is_recorded(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    await _queued(uow_factory)

    outcome = await receipt_consumer(uow_factory, tenants).handle(
        receipt_message(tenant_id, "SM-early", "delivered")
    )

    assert outcome == Outcome("completed")
    assert await count_nodes(neo4j_driver, "ProviderReceipt") == 1
    assert (await _get(uow_factory)).delivery_status == "queued"
    async with uow_factory() as uow:
        await uow.communications.record_send_outcome(
            "comm-1", status="sent", provider_message_id="SM-early", error_code=None
        )
        await uow.commit()
    assert (await _get(uow_factory)).delivery_status == "delivered"
    assert await count_nodes(neo4j_driver, "ProviderReceipt") == 0


async def test_a_receipt_for_a_record_that_is_there_is_applied_and_parks_nothing(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    await _queued(uow_factory)
    async with uow_factory() as uow:
        await uow.communications.record_send_outcome(
            "comm-1", status="sent", provider_message_id="SM-1", error_code=None
        )
        await uow.commit()

    await receipt_consumer(uow_factory, tenants).handle(
        receipt_message(tenant_id, "SM-1", "delivered")
    )

    assert (await _get(uow_factory)).delivery_status == "delivered"
    assert await count_nodes(neo4j_driver, "ProviderReceipt") == 0


async def test_a_late_receipt_that_cannot_move_a_record_parks_nothing(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    await _queued(uow_factory)
    async with uow_factory() as uow:
        await uow.communications.record_send_outcome(
            "comm-1", status="sent", provider_message_id="SM-1", error_code=None
        )
        await uow.commit()
    consumer = receipt_consumer(uow_factory, tenants)
    await consumer.handle(receipt_message(tenant_id, "SM-1", "delivered"))

    late = await consumer.handle(receipt_message(tenant_id, "SM-1", "sent"))

    assert late == Outcome("completed")
    assert (await _get(uow_factory)).delivery_status == "delivered"
    assert await count_nodes(neo4j_driver, "ProviderReceipt") == 0


async def test_the_same_receipt_twice_before_the_send_is_parked_once(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    consumer = receipt_consumer(uow_factory, tenants)

    await consumer.handle(receipt_message(tenant_id, "SM-early", "delivered"))
    await consumer.handle(receipt_message(tenant_id, "SM-early", "delivered"))

    assert await count_nodes(neo4j_driver, "ProviderReceipt") == 1
