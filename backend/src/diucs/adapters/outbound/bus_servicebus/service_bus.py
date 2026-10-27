"""Azure Service Bus adapter for the event bus port (I02, DEC-003, DEC-094).

Stub only, in the red commit (DEC-010). The behaviour is added in the green commit.
"""

from datetime import datetime

from azure.servicebus import ServiceBusMessage
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.exceptions import ServiceBusError

from diucs.application.ports.outbound.event_bus import BusMessage


def to_service_bus_message(message: BusMessage) -> ServiceBusMessage:
    raise NotImplementedError("I02: to_service_bus_message is not built yet")


def is_unscheduled_cancel(error: ServiceBusError, sequence_number: int) -> bool:
    raise NotImplementedError("I02: is_unscheduled_cancel is not built yet")


class ServiceBusEventBus:
    def __init__(self, client: ServiceBusClient) -> None:
        raise NotImplementedError("I02: ServiceBusEventBus is not built yet")

    async def publish(self, message: BusMessage) -> None:
        raise NotImplementedError("I02: publish is not built yet")

    async def schedule(self, queue: str, message: BusMessage, enqueue_at: datetime) -> int:
        raise NotImplementedError("I02: schedule is not built yet")

    async def cancel(self, queue: str, sequence_number: int) -> None:
        raise NotImplementedError("I02: cancel is not built yet")

    async def close(self) -> None:
        raise NotImplementedError("I02: close is not built yet")
