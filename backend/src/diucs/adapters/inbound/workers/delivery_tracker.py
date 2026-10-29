"""Delivery tracker (I08, DEC-165). Stub."""

from typing import Final

from diucs.adapters.inbound.workers.consumer import IdempotentConsumer
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.tenant_binding import Observe, TenantBoundConsumer, untraced
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory

CONSUMER_NAME: Final = "delivery-tracker"
RECEIPT_EVENT: Final = "SmsDeliveryReceived"
RECEIPT_STATUSES: Final = frozenset({"queued", "sent", "delivered", "failed"})


class DeliveryTracker:
    async def __call__(self, message: BusMessage, uow: UnitOfWork) -> None:
        return None


def receipt_consumer(
    uow_factory: UnitOfWorkFactory, tenants: ActiveTenants, observe: Observe = untraced
) -> TenantBoundConsumer:
    inner = IdempotentConsumer(CONSUMER_NAME, DeliveryTracker(), uow_factory)
    return TenantBoundConsumer(inner, tenants, observe)
