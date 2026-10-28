"""The runner against the Service Bus emulator (I04). A message sent twice with one id on
inbound.receipts is processed once. Ids are unique per run (lessons L6, L101)."""

import asyncio
import uuid
from typing import Any

import pytest
from azure.servicebus import ServiceBusMessage

from diucs.adapters.inbound.workers.consumer import IdempotentConsumer
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from tests.support.neo4j import count_nodes
from tests.support.servicebus import client

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


async def test_a_message_sent_twice_with_one_id_is_processed_once(
    uow_factory: UnitOfWorkFactory, neo4j_driver: Any
) -> None:
    calls: list[str] = []

    async def handler(message: BusMessage, uow: UnitOfWork) -> None:
        calls.append(message.id)  # the queue can hold an older run's message: filter by id below

    consumer = IdempotentConsumer("delivery-tracker-i04", handler, uow_factory)
    message_id = f"receipt-{uuid.uuid4()}"
    async with client() as sb:
        async with sb.get_queue_sender("inbound.receipts") as sender:
            for _ in range(2):
                await sender.send_messages(
                    ServiceBusMessage(
                        b'{"status": "delivered"}', message_id=message_id, subject="DeliveryReceipt"
                    )
                )
        runner = ServiceBusRunner(sb, "inbound.receipts", None, consumer)
        stop = asyncio.Event()
        task = asyncio.create_task(runner.run(stop))
        try:
            async with asyncio.timeout(60):
                while message_id not in calls:
                    await asyncio.sleep(0.2)
            await asyncio.sleep(3)  # let the second copy arrive and be settled
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=30)
    assert calls.count(message_id) == 1
    assert await count_nodes(neo4j_driver, "Processed") == len(set(calls))
