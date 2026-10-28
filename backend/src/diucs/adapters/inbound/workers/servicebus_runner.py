"""Service Bus runner for IdempotentConsumer (I04). Red-commit stub (DEC-010)."""

import asyncio
from typing import Any, Protocol

from azure.servicebus.aio import ServiceBusClient

from diucs.adapters.inbound.workers.consumer import IdempotentConsumer


class Receiver(Protocol):
    async def complete_message(self, message: Any) -> None: ...

    async def abandon_message(self, message: Any) -> None: ...

    async def dead_letter_message(
        self, message: Any, reason: str | None = None, error_description: str | None = None
    ) -> None: ...


class ServiceBusRunner:
    def __init__(
        self,
        client: ServiceBusClient,
        entity: str,
        subscription: str | None,
        consumer: IdempotentConsumer,
        sessions: bool = False,
        max_concurrency: int = 4,
    ) -> None:
        self._consumer = consumer

    async def process(self, receiver: Receiver, raw: Any) -> None:
        return None

    async def run(self, stop: asyncio.Event) -> None:
        await stop.wait()
