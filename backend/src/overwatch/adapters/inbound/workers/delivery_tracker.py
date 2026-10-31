"""Delivery tracker: provider delivery receipts onto the Communication records (I08, DEC-165).

The consumer of `inbound.receipts`. I07 verifies Twilio's status callback, resolves the tenant from
the subaccount and queues `{provider_message_id, status, error_code}` with the tenant on the message
(DEC-149 item 8). `TenantBoundConsumer` binds that tenant before the unit of work opens, so the
receipt is applied inside it, and `IdempotentConsumer` marks the bus id (`<sid>:<status>`) in the
same unit of work as the change, so a redelivery does nothing.

A receipt moves the Communication forward and never back: queued, then sent, then delivered or
failed, and delivered and failed are final. The rule and the lock that makes it hold when two
receipts are handled at once are in `CommunicationRepository.set_delivery_status`; this handler only
translates. A receipt for a provider id that no Communication holds (it can arrive before the send
is recorded) is parked, not dropped (KI-133): the provider id and the status are kept, and the
sender applies them in the unit of work that records the send. Either way the message completes and
is not retried: the log line holds the provider id and the status only. The provider's error code
is logged with them, for staff, and kept only on a parked receipt.

A payload that cannot be applied (no provider id, a status the system does not record, a code that
is not text, another kind of message) is a PermanentError with a fixed text, so the bus
dead-letters it at once and it does not hold up the queue.

The two statements behind `by_provider_id` and `set_delivery_status` are tenant-scoped (TEN-015):
a receipt for a provider id finds and changes only the Communication of the tenant bound on the
message, so another tenant's Communication with the same provider id reads as no record and the
receipt completes (DEC-165 item 9).
"""

import logging
from typing import Final

from diucs.adapters.inbound.workers.consumer import IdempotentConsumer, PermanentError
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.tenant_binding import Observe, TenantBoundConsumer, untraced
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory

logger = logging.getLogger(__name__)

CONSUMER_NAME: Final = "delivery-tracker"
# The kind I07 queues (sms_webhook.routes.RECEIPT_EVENT; a test pins that they agree).
RECEIPT_EVENT: Final = "SmsDeliveryReceived"
# The statuses I06 maps a provider status to (`parse_status_callback`); a test pins that they agree.
RECEIPT_STATUSES: Final = frozenset({"queued", "sent", "delivered", "failed"})

NOT_A_RECEIPT: Final = "message is not a delivery receipt"
NO_PROVIDER_ID: Final = "receipt has no provider message id"
BAD_STATUS: Final = "receipt status is not one this system records"
BAD_ERROR_CODE: Final = "receipt error code is not text"


class DeliveryTracker:
    """An I04 handler: the receipt is applied on the unit of work the consumer opened."""

    async def __call__(self, message: BusMessage, uow: UnitOfWork) -> None:
        if message.event_type != RECEIPT_EVENT:
            raise PermanentError(NOT_A_RECEIPT)
        payload = message.payload
        provider_id = payload.get("provider_message_id")
        if not isinstance(provider_id, str) or not provider_id:
            raise PermanentError(NO_PROVIDER_ID)
        status = payload.get("status")
        if not isinstance(status, str) or status not in RECEIPT_STATUSES:
            raise PermanentError(BAD_STATUS)
        error_code = payload.get("error_code")
        if error_code is not None and not isinstance(error_code, str):
            raise PermanentError(BAD_ERROR_CODE)

        moved = await uow.communications.set_delivery_status(provider_id, status)
        parked = False
        if not moved and await uow.communications.by_provider_id(provider_id) is None:
            # The receipt beat the send's record (the provider called back before the sender
            # committed the id it got): keep it, and the sender applies it (KI-133). If the id is
            # there by now, the sender committed in between, so apply what is parked ourselves.
            await uow.communications.park_receipt(provider_id, status, error_code)
            parked = True
            if await uow.communications.by_provider_id(provider_id) is not None:
                await uow.communications.apply_parked_receipts(provider_id)
        logger.info(
            "delivery receipt %s: provider_message_id=%s status=%s error_code=%s",
            "applied"
            if moved
            else "parked (no record holds this id yet)"
            if parked
            else "ignored (already past this status)",
            provider_id,
            status,
            error_code or "-",
        )


def receipt_consumer(
    uow_factory: UnitOfWorkFactory, tenants: ActiveTenants, observe: Observe = untraced
) -> TenantBoundConsumer:
    """The consumer of `inbound.receipts`: the tenant bound from the message, then the receipt
    applied once per bus id."""
    inner = IdempotentConsumer(CONSUMER_NAME, DeliveryTracker(), uow_factory)
    return TenantBoundConsumer(inner, tenants, observe)
