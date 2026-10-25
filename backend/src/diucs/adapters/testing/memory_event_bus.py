"""Fake of Azure Service Bus with a manual clock (external provider only; DEC-004)."""

from datetime import datetime

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.event_bus import BusMessage


class ManualEventBus:
    def __init__(self, clock: Clock) -> None:
        raise NotImplementedError

    @property
    def published(self) -> list[BusMessage]:
        raise NotImplementedError

    def published_to(self, topic: str) -> list[BusMessage]:
        raise NotImplementedError

    async def publish(self, message: BusMessage) -> None:
        raise NotImplementedError

    async def schedule(self, queue: str, message: BusMessage, enqueue_at: datetime) -> int:
        raise NotImplementedError

    async def cancel(self, queue: str, sequence_number: int) -> None:
        raise NotImplementedError

    def due(self, now: datetime | None = None) -> list[tuple[str, BusMessage]]:
        raise NotImplementedError
