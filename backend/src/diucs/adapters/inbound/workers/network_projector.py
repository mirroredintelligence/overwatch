"""The network projector's consumers (TEN-054). Stub for the red commit."""

from collections.abc import Mapping
from typing import Final

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.tenant_binding import Observe, TenantBoundConsumer, untraced
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.network import NetworkRegistry
from diucs.application.use_cases.apply_projection import ApplyProjection
from diucs.application.use_cases.project_network import ProjectNetwork
from diucs.domain.model.network import GrantScope

PRODUCER_EVENTS: Final[Mapping[str, tuple[GrantScope, ...]]] = {}
PRODUCER_CONSUMER_NAME: Final = "network-projector"


class NetworkProducerConsumer:
    def __init__(self, producer: ProjectNetwork) -> None:
        self._producer = producer

    async def handle(self, message: BusMessage) -> Outcome:
        raise NotImplementedError


def producer_consumer(
    producer: ProjectNetwork, tenants: ActiveTenants, observe: Observe = untraced
) -> TenantBoundConsumer:
    return TenantBoundConsumer(NetworkProducerConsumer(producer), tenants, observe)


class NetworkApplyConsumer:
    def __init__(
        self, apply: ApplyProjection, registry: NetworkRegistry, tenants: ActiveTenants
    ) -> None:
        self._apply = apply

    async def handle(self, message: BusMessage) -> Outcome:
        raise NotImplementedError
