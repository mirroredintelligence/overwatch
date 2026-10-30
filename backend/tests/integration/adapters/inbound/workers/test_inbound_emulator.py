"""The inbound consumers against the Service Bus emulator and real Neo4j (I08). Needs the Docker
stack in infra/ for the emulator. Every id is unique, because the emulator keeps messages for an
hour and inbound.replies has duplicate detection (lessons L6, L101), and messages of an older run
may still be queued: the consumers dead-letter or complete them and the tests look for their own id.

What this shows that the unit tests cannot: the `tenantId` property the bus adapter sends is the one
the runner reads and the consumer binds, and a message with no tenant does not block the queue.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from azure.servicebus import ServiceBusMessage

from diucs.adapters.inbound.workers.delivery_tracker import receipt_consumer
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.reply_processor import reply_consumer
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.adapters.outbound.bus_servicebus.service_bus import ServiceBusEventBus
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Channel
from tests.support.inbound_rig import RecordingUseCase, receipt_message, reply_message
from tests.support.servicebus import client

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.servicebus,
    pytest.mark.exclusive,
]


@pytest_asyncio.fixture
async def bus() -> AsyncIterator[ServiceBusEventBus]:
    sb = client()
    event_bus = ServiceBusEventBus(sb)
    try:
        yield event_bus
    finally:
        await event_bus.close()
        await sb.close()


async def _until(condition: object, seconds: float = 60.0) -> None:
    async with asyncio.timeout(seconds):
        while not await condition():  # type: ignore[operator]
            await asyncio.sleep(0.2)


async def test_a_text_with_a_tenant_reaches_the_use_case_in_it_and_one_with_none_does_not_block(
    uow_factory: UnitOfWorkFactory, bus: ServiceBusEventBus, tenant_id: str
) -> None:
    run = uuid.uuid4().hex[:12]
    poison_id, good_id = f"SMbad{run}", f"SMgood{run}"
    use_case = RecordingUseCase(uow_factory)
    async with client() as sb:
        runner = ServiceBusRunner(
            sb,
            "inbound.replies",
            None,
            reply_consumer(use_case, uow_factory, StaticTenants([tenant_id])),
        )
        # A message with no tenant property cannot be built by the bus adapter, so it is sent as
        # a bare SDK message: what a producer that skipped the tenant would put on the queue.
        async with sb.get_queue_sender("inbound.replies") as sender:
            await sender.send_messages(
                ServiceBusMessage(
                    body=b"{}",
                    message_id=f"{tenant_id}:{poison_id}",
                    subject="SmsReceived",
                    content_type="application/json",
                )
            )
        await bus.enqueue("inbound.replies", reply_message(tenant_id, good_id))
        stop = asyncio.Event()
        task = asyncio.create_task(runner.run(stop))
        try:

            async def handled() -> bool:
                return any(c.idempotency_key.endswith(good_id) for c in use_case.commands)

            await _until(handled)
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=30)

    mine = [
        (tenant, command.idempotency_key)
        for tenant, command in zip(use_case.tenants, use_case.commands, strict=True)
        if run in command.idempotency_key
    ]
    assert mine == [(tenant_id, f"sms-reply:{tenant_id}:{good_id}")]


async def test_a_receipt_sent_through_the_bus_moves_the_status_in_the_tenant(
    uow_factory: UnitOfWorkFactory, bus: ServiceBusEventBus, tenant_id: str
) -> None:
    provider_id = f"SMrcpt{uuid.uuid4().hex[:12]}"
    async with uow_factory() as uow:
        await uow.communications.add(
            Communication(
                id=f"comm-{provider_id}",
                message_id="C1",
                channel=Channel.TEXT,
                recipient_role_id=None,
                about_id=None,
                payload_text="DIUCS: UCR West. We have 3 referrals in the next 2 hrs.",
                sent_at=datetime(2026, 10, 23, 9, 0, tzinfo=UTC),
                delivery_status="sent",
                provider_message_id=provider_id,
            )
        )
        await uow.commit()
    async with client() as sb:
        runner = ServiceBusRunner(
            sb,
            "inbound.receipts",
            None,
            receipt_consumer(uow_factory, StaticTenants([tenant_id])),
        )
        await bus.enqueue("inbound.receipts", receipt_message(tenant_id, provider_id, "delivered"))
        stop = asyncio.Event()
        task = asyncio.create_task(runner.run(stop))
        try:

            async def delivered() -> bool:
                async with uow_factory() as uow:
                    found = await uow.communications.by_provider_id(provider_id)
                return found is not None and found.delivery_status == "delivered"

            await _until(delivered)
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=30)
