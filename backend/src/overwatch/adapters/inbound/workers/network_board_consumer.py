"""The consumer of the network board projector's subscription (TEN-058, DEC-547).

The `network-board-projector` subscription of `network.events` delivers the governance events that
change what a network board shows (a grant effective or ended, a member added or removed; a
projection applied reaches the projector through the apply step's notifier instead). Each message
belongs to the tenant that acted: `TenantBoundConsumer` checks the `tenantId` property against the
directory and binds it before this consumer runs. The network a board belongs to is the payload's
`network_id`: the projector validates it as a network id and the registry confirms it when the board
is rebuilt, so a payload is never an authority for anything but which network to rebuild.

A rebuild is idempotent (it recomputes the board from the graph), so there is no processed marker:
a failed rebuild is retried by the bus and the retry rebuilds the same board. An event the board
does not show is completed and does nothing. Outcomes carry a fixed word or the class of an error,
never a payload value: a payload that is not a network id is `message-invalid`, a network the
registry does not know (or that is not active) is `network-unknown`, both permanent.
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
from diucs.domain.errors import NotFound, ValidationFailed

logger = logging.getLogger(__name__)

NETWORK_BOARD_SUBSCRIPTION: Final = "network-board-projector"
NETWORK_EVENTS_TOPIC: Final = "network.events"
NOT_BOUND_REASON: Final = "message is not bound to its tenant"
MESSAGE_INVALID: Final = "message-invalid"
NETWORK_UNKNOWN: Final = "network-unknown"


class NetworkBoardRebuilder(Protocol):
    async def handle(self, event_type: str, payload: Mapping[str, Any]) -> bool: ...


class NetworkBoardConsumer:
    """A consumer (`handle(message)`): run it inside `TenantBoundConsumer`
    (`network_board_consumer`)."""

    def __init__(self, projector: NetworkBoardRebuilder) -> None:
        self._projector = projector

    async def handle(self, message: BusMessage) -> Outcome:
        scope = current_scope_or_none()
        if scope is None or scope.value != message.tenant_id:
            return Outcome("dead-letter", NOT_BOUND_REASON)
        try:
            await self._projector.handle(message.event_type, message.payload)
        except ValidationFailed:
            return Outcome("dead-letter", MESSAGE_INVALID)
        except NotFound:
            return Outcome("dead-letter", NETWORK_UNKNOWN)
        except Exception as error:
            logger.warning(
                "network board rebuild for message %s will retry: %s",
                message.id,
                type(error).__name__,
            )
            return Outcome("retry", type(error).__name__)
        return Outcome("completed")


def network_board_consumer(
    projector: NetworkBoardRebuilder, tenants: ActiveTenants, observe: Observe = untraced
) -> TenantBoundConsumer:
    """The consumer of the subscription: the tenant bound from the message, then the board of the
    payload's network rebuilt."""
    return TenantBoundConsumer(NetworkBoardConsumer(projector), tenants, observe)


def network_board_runners(
    client: ServiceBusClient,
    projector: NetworkBoardRebuilder,
    tenants: ActiveTenants,
    observe: Observe = untraced,
) -> list[ServiceBusRunner]:
    """The runner of the network board projector: `network.events`, no sessions (governance
    events are not ordered by session; every rebuild reads the current state)."""
    return [
        ServiceBusRunner(
            client,
            NETWORK_EVENTS_TOPIC,
            NETWORK_BOARD_SUBSCRIPTION,
            network_board_consumer(projector, tenants, observe),
        )
    ]
