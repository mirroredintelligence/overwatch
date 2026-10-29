"""Reply processor: queued texts onto `HandleInboundText` (I08, DEC-165).

The consumer of `inbound.replies`. I07 verifies the Twilio signature, resolves the tenant from the
number called and the account, and queues `{phone_hash, text, received_at, provider_message_id}`
with the tenant on the message (DEC-149 item 5). `TenantBoundConsumer` binds that tenant before
anything here runs, from a verified source only (lesson L153 item 4: the use case has no tenant of
its own). This module only translates: parsing, the reply policy and the reply texts are the use
case's.

Why this is not an `IdempotentConsumer`. That consumer holds one unit of work around its handler,
and `HandleInboundText` opens its own units (a read pass, one per write, a last one for its own
record), which the graph store refuses inside an open one (DEC-146 item 4). So the processor holds
none while the use case runs, and keeps the same promise in three steps:

1. ask whether this consumer has marked the message (`processed.seen`): if so it is a duplicate;
2. run the use case, under an idempotency key built from the tenant and the provider message id, so
   a second run of the same message is answered as a replay and writes nothing;
3. mark the message in its own unit of work.

A crash or a store failure between 2 and 3 leaves no marker, the bus delivers the message again,
and step 2 replays. Two deliveries at once both run step 2 (a replay, or one of them is refused as
a Conflict and retried), and the second to mark is told the marker is held. At least once, and the
use case's own record makes it at most once in effect.

Outcomes: a payload that cannot be read, or a use case that refuses it as invalid
(ValidationFailed), is a PermanentError with a fixed text and the bus dead-letters it at once; the
text, the phone hash and the provider id are never in a reason or a log line. Any other failure,
a Conflict included (it can be a race the next delivery will not meet), is a retry, and the bus
dead-letters the message after its delivery limit. A text the use case drops (a phone that is
nobody's reporter) is finished, not retried.
"""

import logging
from datetime import UTC, datetime
from typing import Final, Protocol

from diucs.adapters.inbound.workers.consumer import MAX_REASON_LENGTH, Outcome, PermanentError
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.tenant_binding import Observe, TenantBoundConsumer, untraced
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import current_tenant
from diucs.application.use_cases.handle_inbound_text import (
    HandleInboundTextCommand,
    HandleInboundTextResult,
)
from diucs.domain.errors import ValidationFailed

logger = logging.getLogger(__name__)

CONSUMER_NAME: Final = "reply-processor"
# The kind I07 queues (sms_webhook.routes.REPLY_EVENT; a test pins that they agree).
REPLY_EVENT: Final = "SmsReceived"

NOT_A_REPLY: Final = "message is not an inbound text"
USE_CASE_REFUSED: Final = "the use case refused the text as invalid"


class HandlesInboundText(Protocol):
    async def execute(self, command: HandleInboundTextCommand) -> HandleInboundTextResult: ...


def reply_key(provider_message_id: str) -> str:
    """The idempotency key of a reply, from the bound tenant: no tenant bound is an error, never a
    default. The replay store is not yet tenant-scoped (its statements are on the ratchet, L160), so
    the tenant is in the key and two tenants' texts that share a provider id are two commands. The
    one place the key is built; TEN-011 converts the store and the key can then be the bare id."""
    return f"sms-reply:{current_tenant()}:{provider_message_id}"


def _field(payload: dict[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise PermanentError(f"inbound text has no usable {name}")
    return value


def _received_at(payload: dict[str, object]) -> datetime:
    text = _field(payload, "received_at")
    try:
        instant = datetime.fromisoformat(text)
    except ValueError:
        raise PermanentError("inbound text has no usable received_at") from None
    if instant.utcoffset() is None:  # a wall time is not an instant
        raise PermanentError("inbound text has no usable received_at")
    return instant.astimezone(UTC)


def _command(message: BusMessage) -> HandleInboundTextCommand:
    if message.event_type != REPLY_EVENT:
        raise PermanentError(NOT_A_REPLY)
    payload = message.payload
    # The text may be any string, a blank one included: the use case answers it.
    text = payload.get("text")
    if not isinstance(text, str):
        raise PermanentError("inbound text has no usable text")
    return HandleInboundTextCommand(
        idempotency_key=reply_key(_field(payload, "provider_message_id")),
        from_phone_hash=_field(payload, "phone_hash"),
        text=text,
        received_at=_received_at(payload),
    )


class ReplyProcessor:
    """A consumer (`handle(message)`), not an I04 handler: see the module text. Run it inside a
    `TenantBoundConsumer` (`reply_consumer`), which binds the tenant first."""

    def __init__(
        self, handle_inbound_text: HandlesInboundText, uow_factory: UnitOfWorkFactory
    ) -> None:
        self._use_case = handle_inbound_text
        self._uow_factory = uow_factory

    async def handle(self, message: BusMessage) -> Outcome:
        try:
            command = _command(message)
            if await self._seen(message):
                return Outcome("duplicate")
            result = await self._run(command)
            if not await self._mark(message):
                return Outcome("duplicate")
        except PermanentError as error:
            return Outcome("dead-letter", str(error)[:MAX_REASON_LENGTH])
        except Exception as error:
            logger.warning(
                "consumer %s will retry message %s: %s",
                CONSUMER_NAME,
                message.id,
                type(error).__name__,
            )
            return Outcome("retry", type(error).__name__)
        logger.info("reply handled: message=%s outcome=%s", message.id, result.outcome)
        return Outcome("completed")

    async def _seen(self, message: BusMessage) -> bool:
        async with self._uow_factory() as uow:
            return await uow.processed.seen(message.id, CONSUMER_NAME)

    async def _run(self, command: HandleInboundTextCommand) -> HandleInboundTextResult:
        try:
            return await self._use_case.execute(command)
        except ValidationFailed:
            # Its text can name the field and the value: it is not repeated.
            raise PermanentError(USE_CASE_REFUSED) from None

    async def _mark(self, message: BusMessage) -> bool:
        async with self._uow_factory() as uow:
            created = await uow.processed.mark_if_new(message.id, CONSUMER_NAME)
            await uow.commit()
        return created


def reply_consumer(
    handle_inbound_text: HandlesInboundText,
    uow_factory: UnitOfWorkFactory,
    tenants: ActiveTenants,
    observe: Observe = untraced,
) -> TenantBoundConsumer:
    """The consumer of `inbound.replies`: the tenant bound from the message, then the text handled
    once per provider message id."""
    return TenantBoundConsumer(ReplyProcessor(handle_inbound_text, uow_factory), tenants, observe)
