"""The consumer of the network projector's subscription of `network.events` (TEN-056, DEC-545 item
6, DEC-132 items 3 and 6).

`network.events` carries the governance events of the network administration (a grant effective, a
grant ended, a member removed or left). Each message belongs to the tenant that acted:
`TenantBoundConsumer` checks the `tenantId` property against the directory and binds it before this
consumer runs. The projector's handler (`NetworkGovernance`) reads the registry, checks that the
sender is a party and acts; it is the second subscription of the topic, beside the network board
projector's (`network-board-projector`), so a slow end never holds a board rebuild back and a
rebuild never holds an end back.

Outcomes use fixed words that hold no payload value: a payload that is not the event is
`message-invalid`, a grant or network the registry does not know is `not-found`, a sender that is no
party or an event that disagrees with the registry is `sender-mismatch`; all three are permanent.
Any other failure is a retry that names the class of the error and never its text: a step that did
not run is run again, and every step is repeatable.
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
from diucs.application.use_cases.network_governance import GovernanceOutcome
from diucs.domain.errors import NotAllowed, NotFound, ValidationFailed

logger = logging.getLogger(__name__)

NETWORK_GOVERNANCE_SUBSCRIPTION: Final = "network-projector"
NETWORK_EVENTS_TOPIC: Final = "network.events"
NOT_BOUND_REASON: Final = "message is not bound to its tenant"
MESSAGE_INVALID: Final = "message-invalid"
NOT_FOUND: Final = "not-found"
SENDER_MISMATCH: Final = "sender-mismatch"


class GovernanceHandler(Protocol):
    async def handle(
        self, event_type: str, payload: Mapping[str, Any], *, bus_tenant: str
    ) -> GovernanceOutcome: ...


class NetworkGovernanceConsumer:
    """A consumer (`handle(message)`): run it inside `TenantBoundConsumer`
    (`network_governance_consumer`)."""

    def __init__(self, governance: GovernanceHandler) -> None:
        self._governance = governance

    async def handle(self, message: BusMessage) -> Outcome:
        scope = current_scope_or_none()
        if scope is None or scope.value != message.tenant_id:
            return Outcome("dead-letter", NOT_BOUND_REASON)
        try:
            await self._governance.handle(
                message.event_type, message.payload, bus_tenant=message.tenant_id
            )
        except ValidationFailed:
            return Outcome("dead-letter", MESSAGE_INVALID)
        except NotFound:
            return Outcome("dead-letter", NOT_FOUND)
        except NotAllowed:
            return Outcome("dead-letter", SENDER_MISMATCH)
        except Exception as error:
            logger.warning(
                "network governance for message %s will retry: %s", message.id, type(error).__name__
            )
            return Outcome("retry", type(error).__name__)
        return Outcome("completed")


def network_governance_consumer(
    governance: GovernanceHandler, tenants: ActiveTenants, observe: Observe = untraced
) -> TenantBoundConsumer:
    """The consumer of the subscription: the tenant bound from the message, then the event handled
    for the network and the grantor the registry names."""
    return TenantBoundConsumer(NetworkGovernanceConsumer(governance), tenants, observe)


def network_governance_runners(
    client: ServiceBusClient,
    governance: GovernanceHandler,
    tenants: ActiveTenants,
    observe: Observe = untraced,
) -> list[ServiceBusRunner]:
    """The runner of the projector's governance subscription: `network.events`, no sessions."""
    return [
        ServiceBusRunner(
            client,
            NETWORK_EVENTS_TOPIC,
            NETWORK_GOVERNANCE_SUBSCRIPTION,
            network_governance_consumer(governance, tenants, observe),
        )
    ]
