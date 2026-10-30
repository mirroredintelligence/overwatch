"""The consumer of the board projector's subscriptions (TEN-039). Stub for the red commit."""

from collections.abc import Sequence
from typing import Final

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.adapters.inbound.workers.tenant_binding import TenantBoundConsumer, untraced
from diucs.application.ports.outbound.event_bus import BusMessage

BOARD_SUBSCRIPTION: Final = "board-projector"
BOARD_TOPICS: Final = ("capacity.events", "booking.events")
NOT_BOUND_REASON: Final = "message is not bound to its tenant"


class BoardUpdateConsumer:
    def __init__(self, projector: object) -> None:
        raise NotImplementedError

    async def handle(self, message: BusMessage) -> Outcome:
        raise NotImplementedError


def board_consumer(
    projector: object, tenants: ActiveTenants, observe: object = untraced
) -> TenantBoundConsumer:
    raise NotImplementedError


def board_runners(
    client: object, projector: object, tenants: ActiveTenants, observe: object = untraced
) -> Sequence[ServiceBusRunner]:
    raise NotImplementedError
