"""Outbound message senders (I10): the consumers of `messages.outbound` (DEC-115, DEC-116, DEC-131).

The outbox relay publishes one `SendMessage` per Communication that a use case queued (U03). Each
sender takes the ones for its channel, from its own subscription (the filters are in
infra/servicebus-config.json), and:

1. opens the sealed content with the outbox message id, the tenant and the recipient role as its
   associated data, so the text belongs to this message, tenant and person (DEC-116);
2. looks the recipient up in the protected contact store, inside the unit of work (P16). No number
   or address means nothing is sent;
3. gets the sender of the bound tenant from the SenderResolver (DEC-131 item 1). No sender for the
   tenant means nothing is sent;
4. sends. A transient failure raises, so the unit of work rolls back and the bus redelivers. Any
   other answer is recorded on the Communication in the same unit of work as the consumer's
   marker, so a redelivery finds it handled and does nothing.

A Communication that already has a provider id, or has left `queued`, is never sent again.
Errors carry fixed texts only: no number, address, body text or tenant id reaches a log line or an
error (the log holds the message id, the status and the reason code).

Known issue (I10-1): the provider call and the commit of its record are separate. If the commit
fails after the provider accepted the text, the redelivery sends it again. Twilio's Messages API
has no idempotency key used here.
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from azure.servicebus.aio import ServiceBusClient

from diucs.adapters.inbound.workers.consumer import IdempotentConsumer, PermanentError
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.adapters.inbound.workers.tenant_binding import Observe, TenantBoundConsumer, untraced
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.messaging import (
    Communication,
    EmailSender,
    SendFailedError,
    SendReceipt,
    SmsSender,
    TransientSendError,
)
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.sender_resolver import ChannelUnavailable, SenderResolver
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.domain.codes import Channel
from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.catalogue import MessageId

logger = logging.getLogger(__name__)

MESSAGES_TOPIC: Final = "messages.outbound"
SEND_MESSAGE_EVENT: Final = "SendMessage"
CONSUMER_SMS: Final = "sender-sms"
CONSUMER_EMAIL: Final = "sender-email"
SMS_SUBSCRIPTION: Final = "text-sender"
EMAIL_SUBSCRIPTION: Final = "email-sender"
PUSH_SUBSCRIPTION: Final = "push-sender"

NO_TENANT: Final = "message has no tenant"
NOT_A_SEND: Final = "message is not a send"
BAD_PAYLOAD: Final = "outbound payload is not one this system sends"
BAD_CHANNEL: Final = "outbound message is for another channel"
BAD_CONTENT: Final = "outbound content cannot be opened"
NO_COMMUNICATION: Final = "the communication to send is not stored"

# The reason a Communication records when it is not sent (stored as `errorCode`, never logged
# with an address).
NO_CONTACT: Final = "no-contact"
NO_CHANNEL: Final = "no-channel"
REFUSED: Final = "refused"
SEND_FAILED: Final = "send-failed"


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    communication_id: str
    channel: Channel
    recipient_role_id: str
    message_id: str
    text: str
    subject: str | None
    html: str | None


def _text(value: object) -> str | None:
    return value if type(value) is str and value else None


def _channel(value: object) -> Channel | None:
    if type(value) is not str:
        return None
    try:
        return Channel(value)
    except ValueError:
        return None


def _is_catalogue_id(value: str) -> bool:
    try:
        MessageId(value)
    except ValueError:
        return False
    return True


def parse_outbound(
    payload: object, *, message_id: str, tenant_id: str, sealer: ContentSealer
) -> OutboundMessage:
    """The message the outbox wrote, with its content opened. `message_id` is the outbox message
    id, which the content was sealed under. Raises PermanentError for a payload that can never
    be sent, and for content that does not open for this message, tenant and recipient."""
    if not isinstance(payload, Mapping):
        raise PermanentError(BAD_PAYLOAD)
    communication_id = _text(payload.get("communication_id"))
    recipient = _text(payload.get("recipient_role_id"))
    catalogue_id = _text(payload.get("message_id"))
    sealed = _text(payload.get("sealed_content"))
    channel = _channel(payload.get("channel"))
    if communication_id is None or recipient is None or catalogue_id is None or sealed is None:
        raise PermanentError(BAD_PAYLOAD)
    if channel is None or not _is_catalogue_id(catalogue_id):
        raise PermanentError(BAD_PAYLOAD)

    try:
        content = sealer.unseal(
            sealed, message_id=message_id, tenant_id=tenant_id, recipient_role_id=recipient
        )
    except ValidationFailed:
        raise PermanentError(BAD_CONTENT) from None
    try:
        body = json.loads(content)
    except ValueError:
        raise PermanentError(BAD_CONTENT) from None
    if not isinstance(body, dict):
        raise PermanentError(BAD_CONTENT)
    text = _text(body.get("text"))
    subject = body.get("subject")
    html = body.get("html")
    if text is None or text.strip() == "":
        raise PermanentError(BAD_CONTENT)
    if subject is not None and type(subject) is not str:
        raise PermanentError(BAD_CONTENT)
    if html is not None and type(html) is not str:
        raise PermanentError(BAD_CONTENT)
    if channel is Channel.EMAIL and (subject is None or subject.strip() == ""):
        raise PermanentError(BAD_CONTENT)
    return OutboundMessage(
        communication_id=communication_id,
        channel=channel,
        recipient_role_id=recipient,
        message_id=catalogue_id,
        text=text,
        subject=subject,
        html=html,
    )


def is_handled(communication: Communication) -> bool:
    """True when this communication was sent or refused already: it has a provider id, or it has
    left `queued`. Such a message is never sent again (I10)."""
    return (
        communication.provider_message_id is not None or communication.delivery_status != "queued"
    )


class _OutboundSender:
    """The shared path of the text and email senders. A subclass names its channel, how it finds
    the recipient and how it sends through the bound tenant's sender."""

    channel: Channel
    name: str

    def __init__(self, senders: SenderResolver, sealer: ContentSealer) -> None:
        self._senders = senders
        self._sealer = sealer

    async def __call__(self, message: BusMessage, uow: UnitOfWork) -> None:
        if message.event_type != SEND_MESSAGE_EVENT:
            raise PermanentError(NOT_A_SEND)
        tenant_id = message.tenant_id
        if not tenant_id:
            raise PermanentError(NO_TENANT)
        outbound = parse_outbound(
            message.payload, message_id=message.id, tenant_id=tenant_id, sealer=self._sealer
        )
        if outbound.channel is not self.channel:
            raise PermanentError(BAD_CHANNEL)

        communication = await uow.communications.get(outbound.communication_id)
        if communication is None:
            raise PermanentError(NO_COMMUNICATION)
        if is_handled(communication):
            return

        address = await self._address(uow, outbound.recipient_role_id)
        if address is None:
            await self._settle(uow, message, communication.id, "failed", None, NO_CONTACT)
            return
        try:
            receipt = await self._send(address, outbound, message.id)
        except ChannelUnavailable:
            await self._settle(uow, message, communication.id, "failed", None, NO_CHANNEL)
            return
        except TransientSendError:
            raise
        except SendFailedError as error:
            logger.warning(
                "%s not sent, recorded as failed: message=%s reason=%s",
                self.name,
                message.id,
                type(error).__name__,
            )
            await self._settle(uow, message, communication.id, "failed", None, SEND_FAILED)
            return
        if receipt.accepted:
            await self._settle(
                uow, message, communication.id, "sent", receipt.provider_message_id, None
            )
        else:
            await self._settle(uow, message, communication.id, "failed", None, REFUSED)

    async def _settle(
        self,
        uow: UnitOfWork,
        message: BusMessage,
        communication_id: str,
        status: Literal["sent", "failed"],
        provider_message_id: str | None,
        error_code: str | None,
    ) -> None:
        recorded = await uow.communications.record_send_outcome(
            communication_id,
            status=status,
            provider_message_id=provider_message_id,
            error_code=error_code,
        )
        logger.info(
            "%s %s: message=%s status=%s reason=%s",
            self.name,
            "recorded" if recorded else "not recorded (no longer queued)",
            message.id,
            status,
            error_code or "-",
        )

    async def _address(self, uow: UnitOfWork, role_id: str) -> str | None:
        raise NotImplementedError

    async def _send(self, address: str, outbound: OutboundMessage, outbox_id: str) -> SendReceipt:
        """The receipt of the send. ChannelUnavailable means nothing is sent. A TransientSendError
        propagates: the message is retried."""
        raise NotImplementedError


class SmsMessageSender(_OutboundSender):
    """The `text-sender` subscription: texts from the bound tenant's number (I10)."""

    channel = Channel.TEXT
    name = CONSUMER_SMS

    async def _address(self, uow: UnitOfWork, role_id: str) -> str | None:
        return await uow.contacts.get_phone(role_id)

    async def _send(self, address: str, outbound: OutboundMessage, outbox_id: str) -> SendReceipt:
        sender: SmsSender = await self._senders.sms_for()
        return await sender.send(address, outbound.text, outbox_id)


class EmailMessageSender(_OutboundSender):
    """The `email-sender` subscription: email from the bound tenant's sender identity (I10)."""

    channel = Channel.EMAIL
    name = CONSUMER_EMAIL

    async def _address(self, uow: UnitOfWork, role_id: str) -> str | None:
        return await uow.contacts.get_email(role_id)

    async def _send(self, address: str, outbound: OutboundMessage, outbox_id: str) -> SendReceipt:
        sender: EmailSender = await self._senders.email_for()
        if outbound.subject is None:
            raise PermanentError(BAD_CONTENT)
        return await sender.send(address, outbound.subject, outbound.text, outbound.html)


def sender_runners(
    client: ServiceBusClient,
    uow_factory: UnitOfWorkFactory,
    tenants: ActiveTenants,
    senders: SenderResolver,
    sealer: ContentSealer,
    observe: Observe = untraced,
) -> list[ServiceBusRunner]:
    """The two runners of `messages.outbound`: the text sender and the email sender. Each binds the
    tenant of the message before it opens a unit of work (TenantBoundConsumer)."""
    sms = TenantBoundConsumer(
        IdempotentConsumer(CONSUMER_SMS, SmsMessageSender(senders, sealer), uow_factory),
        tenants,
        observe,
    )
    email = TenantBoundConsumer(
        IdempotentConsumer(CONSUMER_EMAIL, EmailMessageSender(senders, sealer), uow_factory),
        tenants,
        observe,
    )
    return [
        ServiceBusRunner(client, MESSAGES_TOPIC, SMS_SUBSCRIPTION, sms),
        ServiceBusRunner(client, MESSAGES_TOPIC, EMAIL_SUBSCRIPTION, email),
    ]
