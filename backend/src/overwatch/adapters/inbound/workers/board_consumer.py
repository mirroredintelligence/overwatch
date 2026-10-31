"""The consumer of the board projector's subscriptions (TEN-039, DEC-130 item 7, DEC-165).

The board-projector subscription of `capacity.events` (one session per service) and of
`booking.events` delivers the events the wall board shows. Each message belongs to a tenant: the
runner puts the `tenantId` property in `BusMessage.tenant_id`, and `TenantBoundConsumer` checks it
against the directory and binds it before this consumer runs, so the projector rebuilds the board of
that tenant, caches it under that tenant's key and announces it on that tenant's channel. The
payload is never read for a tenant.

A rebuild is idempotent (it recomputes the board from the graph), so there is no processed marker
and no unit of work around it: a failed rebuild is retried by the bus, and the message that retries
rebuilds the same board. An event the board does not show is completed and does nothing. If the
consumer is ever reached with no tenant bound, or a tenant other than the message's, it dead-letters
the message and rebuilds nothing (defence in depth: it is only built inside `TenantBoundConsumer`).
"""

import logging
from collections.abc import Mapping
from typing import Any, Final, Protocol

from azure.servicebus.aio import ServiceBusClient

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.adapters.inbound.workers.tenant_binding import Observe, TenantBoundConsumer, untraced
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.tenancy import current_scope_or_none

logger = logging.getLogger(__name__)

BOARD_SUBSCRIPTION: Final = "board-projector"
CAPACITY_TOPIC: Final = "capacity.events"
BOOKING_TOPIC: Final = "booking.events"
NOT_BOUND_REASON: Final = "message is not bound to its tenant"


class BoardRebuilder(Protocol):
    async def handle(self, event_type: str, payload: Mapping[str, Any]) -> bool: ...


class BoardUpdateConsumer:
    """A consumer (`handle(message)`), not an I04 handler: see the module text. Run it inside a
    `TenantBoundConsumer` (`board_consumer`), which binds the tenant first."""

    def __init__(self, projector: BoardRebuilder) -> None:
        self._projector = projector

    async def handle(self, message: BusMessage) -> Outcome:
        scope = current_scope_or_none()
        if scope is None or scope.value != message.tenant_id:
            return Outcome("dead-letter", NOT_BOUND_REASON)
        try:
            await self._projector.handle(message.event_type, message.payload)
        except Exception as error:
            # The class name only: the text of an error can carry data.
            logger.warning(
                "board rebuild for message %s will retry: %s", message.id, type(error).__name__
            )
            return Outcome("retry", type(error).__name__)
        return Outcome("completed")


def board_consumer(
    projector: BoardRebuilder, tenants: ActiveTenants, observe: Observe = untraced
) -> TenantBoundConsumer:
    """The consumer of a board-projector subscription: the tenant bound from the message, then the
    board rebuilt in that scope."""
    return TenantBoundConsumer(BoardUpdateConsumer(projector), tenants, observe)


def board_runners(
    client: ServiceBusClient,
    projector: BoardRebuilder,
    tenants: ActiveTenants,
    observe: Observe = untraced,
) -> list[ServiceBusRunner]:
    """The two runners of the board: `capacity.events` read through sessions (the subscription
    requires them, one per service) and `booking.events`. Each binds the message's tenant."""
    return [
        ServiceBusRunner(
            client,
            CAPACITY_TOPIC,
            BOARD_SUBSCRIPTION,
            board_consumer(projector, tenants, observe),
            sessions=True,
        ),
        ServiceBusRunner(
            client,
            BOOKING_TOPIC,
            BOARD_SUBSCRIPTION,
            board_consumer(projector, tenants, observe),
        ),
    ]
