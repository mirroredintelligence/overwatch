"""The network projector's two consumers (TEN-054, DEC-543, DEC-130 item 7, DEC-132 item 4).

`NetworkProducerConsumer` follows the events of a tenant (capacity, criteria, registration) and
asks the producer to refresh the kinds each one touches for the service it names. It runs inside
`TenantBoundConsumer`, which has checked the message's tenant against the directory and bound it,
so the producer reads in that tenant's scope and no other. It writes nothing.

`NetworkApplyConsumer` takes a `ProjectionRequested` message. The tenant property of the message is
the *source* tenant, checked against the directory and against the payload; the network it binds is
the payload's, but only after the registry says that network exists and is active, and the apply
step then asks the registry again about the member, the grant and the listing (the message is never
the authority). The binding is for the handling of one message.

Outcomes (the bus words of `consumer.py`): applied, duplicate, stale and rejected messages are
`completed` (a rejection is acknowledged and not retried); a message that cannot be what it says is
dead-lettered with a fixed word; anything else is a retry that names the class of the error and
never its text. No reason holds a payload value.
"""

import logging
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.tenant_binding import Observe, TenantBoundConsumer, untraced
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.tenancy import ScopeId, bind_scope, current_scope_or_none
from diucs.application.use_cases.apply_projection import ApplyProjection, ProjectionMismatch
from diucs.application.use_cases.project_network import ProjectNetwork
from diucs.domain.errors import DomainError
from diucs.domain.events import ProjectionRequested
from diucs.domain.model.network import GrantScope, NetworkStatus

logger = logging.getLogger(__name__)

PRODUCER_CONSUMER_NAME: Final = "network-projector"
NOT_BOUND_REASON: Final = "message is not bound to its tenant"
SERVICE_MISSING: Final = "service-missing"
MESSAGE_INVALID: Final = "message-invalid"
SOURCE_MISMATCH: Final = "source-mismatch"
TENANT_UNKNOWN: Final = "tenant-unknown"
NETWORK_UNKNOWN: Final = "network-unknown"
PROJECTION_MISMATCH: Final = "projection-mismatch"

_C, _D, _K = GrantScope.CAPACITY, GrantScope.DIRECTORY, GrantScope.CRITERIA
# The events that change something a network shows, and the kinds each one refreshes. A booking
# response or expiry changes the confirmed count that the capacity inputs carry (never a booking).
PRODUCER_EVENTS: Final[Mapping[str, tuple[GrantScope, ...]]] = MappingProxyType(
    {
        "CapacityReported": (_C,),
        "StatusChanged": (_C,),
        "BookingResponded": (_C,),
        "BookingExpired": (_C,),
        "CriteriaApproved": (_K,),
        "RegistrationApproved": (_D, _C, _K),
        "ServiceDirectoryChanged": (_D, _C),
    }
)


class NetworkProducerConsumer:
    """A consumer (`handle(message)`): run it inside `TenantBoundConsumer` (`producer_consumer`)."""

    def __init__(self, producer: ProjectNetwork) -> None:
        self._producer = producer

    async def handle(self, message: BusMessage) -> Outcome:
        scope = current_scope_or_none()
        if scope is None or scope.value != message.tenant_id:
            return Outcome("dead-letter", NOT_BOUND_REASON)
        kinds = PRODUCER_EVENTS.get(message.event_type)
        if kinds is None:
            return Outcome("completed")
        service_id = message.payload.get("service_id")
        if type(service_id) is not str or not service_id:
            return Outcome("dead-letter", SERVICE_MISSING)
        try:
            for kind in kinds:
                await self._producer.project(kind, service_id)
        except Exception as error:
            logger.warning(
                "network projection for message %s will retry: %s", message.id, type(error).__name__
            )
            return Outcome("retry", type(error).__name__)
        return Outcome("completed")


def producer_consumer(
    producer: ProjectNetwork, tenants: ActiveTenants, observe: Observe = untraced
) -> TenantBoundConsumer:
    """The consumer of a producer subscription: the tenant bound from the message, then the
    service's kinds refreshed in that scope."""
    return TenantBoundConsumer(NetworkProducerConsumer(producer), tenants, observe)


class NetworkApplyConsumer:
    def __init__(
        self, apply: ApplyProjection, registry: NetworkRegistry, tenants: ActiveTenants
    ) -> None:
        self._apply = apply
        self._registry = registry
        self._tenants = tenants

    async def handle(self, message: BusMessage) -> Outcome:
        try:
            request = ProjectionRequested.decode(message.payload)
        except Exception:
            return Outcome("dead-letter", MESSAGE_INVALID)
        if message.tenant_id != request.source_tenant_id:
            return Outcome("dead-letter", SOURCE_MISMATCH)
        try:
            if message.tenant_id not in await self._tenants.active_tenant_ids():
                return Outcome("dead-letter", TENANT_UNKNOWN)
            registered = await self._registry.get_network(request.network_id)
            if registered is None or registered.network.status is not NetworkStatus.ACTIVE:
                return Outcome("dead-letter", NETWORK_UNKNOWN)
            with bind_scope(ScopeId.network(request.network_id)):
                await self._apply.execute(
                    request, message_id=message.id, source_tenant_id=message.tenant_id
                )
        except ProjectionMismatch:
            return Outcome("dead-letter", PROJECTION_MISMATCH)
        except DomainError as error:
            logger.warning("projection message %s will retry: %s", message.id, type(error).__name__)
            return Outcome("retry", type(error).__name__)
        except Exception as error:
            logger.warning("projection message %s will retry: %s", message.id, type(error).__name__)
            return Outcome("retry", type(error).__name__)
        return Outcome("completed")
