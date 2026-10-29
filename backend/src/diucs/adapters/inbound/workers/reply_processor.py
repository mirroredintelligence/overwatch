"""Reply processor (I08, DEC-165). Stub."""

from typing import Final, Protocol

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.tenant_binding import Observe, TenantBoundConsumer, untraced
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.handle_inbound_text import (
    HandleInboundTextCommand,
    HandleInboundTextResult,
)

CONSUMER_NAME: Final = "reply-processor"
REPLY_EVENT: Final = "SmsReceived"


class HandlesInboundText(Protocol):
    async def execute(self, command: HandleInboundTextCommand) -> HandleInboundTextResult: ...


def reply_key(provider_message_id: str) -> str:
    return provider_message_id


class ReplyProcessor:
    def __init__(self, handle_inbound_text: HandlesInboundText, uow_factory: UnitOfWorkFactory):
        self._use_case = handle_inbound_text
        self._uow_factory = uow_factory

    async def handle(self, message: BusMessage) -> Outcome:
        return Outcome("completed")


def reply_consumer(
    handle_inbound_text: HandlesInboundText,
    uow_factory: UnitOfWorkFactory,
    tenants: ActiveTenants,
    observe: Observe = untraced,
) -> TenantBoundConsumer:
    return TenantBoundConsumer(ReplyProcessor(handle_inbound_text, uow_factory), tenants, observe)
