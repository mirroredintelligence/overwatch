"""Outbound message senders (I10): the consumers of `messages.outbound` (DEC-115, DEC-116, DEC-131).

The outbox relay publishes one `SendMessage` per Communication that a use case queued (U03). Each
sender takes the ones for its channel, from its own subscription (the filters are in
infra/servicebus-config.json), and:

1. opens the sealed content with the outbox message id, the tenant and the recipient role as its
   associated data, so the text belongs to this message, tenant and person (DEC-116);
2. looks the recipient up in the protected contact store, inside the unit of work (P16), by the
   post's contact at send time: while a cover holds the post, the cover's number
   (`cover-<role id>`), never the original holder's (F6B). No number or address means nothing is
   sent;
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
from datetime import datetime
from typing import Final, Literal

from azure.servicebus.aio import ServiceBusClient

from diucs.adapters.inbound.workers.consumer import IdempotentConsumer, PermanentError
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.adapters.inbound.workers.tenant_binding import Observe, TenantBoundConsumer, untraced
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.messaging import (
    PUSH_GONE,
    Communication,
    EmailSender,
    PushSender,
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
from diucs.domain.messages.templates import render
from diucs.domain.model.people import cover_in_force, phone_contact_key, role_holder
from diucs.domain.model.tenant import NumberStatus
from diucs.domain.model.tenant_records import ChannelKind

logger = logging.getLogger(__name__)

MESSAGES_TOPIC: Final = "messages.outbound"
SEND_MESSAGE_EVENT: Final = "SendMessage"
CONSUMER_SMS: Final = "sender-sms"
CONSUMER_EMAIL: Final = "sender-email"
CONSUMER_PUSH: Final = "sender-push"
SMS_SUBSCRIPTION: Final = "text-sender"
EMAIL_SUBSCRIPTION: Final = "email-sender"
PUSH_SUBSCRIPTION: Final = "push-sender"

NO_TENANT: Final = "tenant-missing"
NOT_A_SEND: Final = "message is not a send"
BAD_PAYLOAD: Final = "outbound payload is not one this system sends"
BAD_CHANNEL: Final = "outbound message is for another channel"
BAD_CONTENT: Final = "outbound content cannot be opened"
NO_COMMUNICATION: Final = "the communication to send is not stored"
RECIPIENT_PERSON: Final = "recipient_practitioner_id"
PERSON_TITLE_MAX: Final = 120
PERSON_BODY_MAX: Final = 300

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

    def __init__(self, senders: SenderResolver, sealer: ContentSealer, clock: Clock) -> None:
        self._senders = senders
        self._sealer = sealer
        self._clock = clock

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

        address = await self._address(uow, outbound.recipient_role_id, self._clock.now())
        if address is None:
            await self._settle(uow, message, communication.id, "failed", None, NO_CONTACT)
            return
        try:
            receipt = await self._send(uow, address, outbound, message.id)
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

    async def _push_to_person(self, message: BusMessage, uow: UnitOfWork) -> None:
        """A push that names a PERSON (W9H, DEC-1044): an alert (K3) or an executive's test. An
        executive holds no post, so there is no role, no Communication and no sealed content; the
        message carries the plain K3 title and body, which name a service and the kind of alert (or
        the test words) and no patient, no link. One recipient kind per message: a payload that
        also names a role is refused. Delivered to every installed app of the person; a
        subscription the provider reports gone is deleted; a person with no app, or an app that
        refuses, is logged by reason only (the alert's own escalation timer is the follow-up).
        A transient failure raises, so the bus redelivers."""
        payload = message.payload
        if _channel(payload.get("channel")) is not self.channel:
            raise PermanentError(BAD_CHANNEL)
        person = _text(payload.get(RECIPIENT_PERSON))
        title = _text(payload.get("title"))
        body = _text(payload.get("body"))
        if (
            "recipient_role_id" in payload
            or person is None
            or title is None
            or body is None
            or not title.strip()
            or not body.strip()
            or payload.get("message_id") != MessageId.K3.value
            or len(title) > PERSON_TITLE_MAX
            or len(body) > PERSON_BODY_MAX
        ):
            raise PermanentError(BAD_PAYLOAD)
        try:
            render(MessageId.K3, self.channel, title=title, body=body)
        except ValidationFailed:
            raise PermanentError(BAD_CONTENT) from None

        devices = await uow.push_subscriptions.for_practitioner(person)
        accepted = 0
        for device in devices:
            try:
                receipt = await self._sender.send(
                    device.subscription,
                    title,
                    body,
                    self._app_url,
                    urgency=push_urgency(MessageId.K3.value),
                )
            except TransientSendError:
                raise
            except SendFailedError:
                continue
            if receipt.accepted:
                accepted += 1
            elif receipt.reason == PUSH_GONE:
                await uow.push_subscriptions.delete(device.device_id)
        logger.info(
            "%s person push: message=%s apps=%d accepted=%d",
            self.name,
            message.id,
            len(devices),
            accepted,
        )

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

    async def _address(self, uow: UnitOfWork, role_id: str, now: datetime) -> str | None:
        """Where the message goes at `now`, or None when no one holds an address for it."""
        raise NotImplementedError

    async def _send(
        self, uow: UnitOfWork, address: str, outbound: OutboundMessage, outbox_id: str
    ) -> SendReceipt:
        """The receipt of the send. ChannelUnavailable means nothing is sent. A TransientSendError
        propagates: the message is retried."""
        raise NotImplementedError


class SmsMessageSender(_OutboundSender):
    """The `text-sender` subscription: texts from the bound tenant's number (I10)."""

    channel = Channel.TEXT
    name = CONSUMER_SMS

    async def _address(self, uow: UnitOfWork, role_id: str, now: datetime) -> str | None:
        # The post's own number is the original holder's. While a cover holds the post the text
        # goes to the cover's number, and to no one when none was kept (F6B). A recipient that is
        # not a post (a text code's contact key) is addressed by the key itself.
        role = await uow.people.get_role(role_id)
        return await uow.contacts.get_phone(
            role_id if role is None else phone_contact_key(role, now)
        )

    async def _send(
        self, uow: UnitOfWork, address: str, outbound: OutboundMessage, outbox_id: str
    ) -> SendReceipt:
        sender: SmsSender = await self._senders.sms_for()
        return await sender.send(address, outbound.text, outbox_id)


class EmailMessageSender(_OutboundSender):
    """The `email-sender` subscription: email from the bound tenant's sender identity (I10)."""

    channel = Channel.EMAIL
    name = CONSUMER_EMAIL

    async def _address(self, uow: UnitOfWork, role_id: str, now: datetime) -> str | None:
        # A cover is known by a number only, so while one holds the post there is no address to
        # write to, and the original holder's address is not used (F6B).
        role = await uow.people.get_role(role_id)
        if role is not None and cover_in_force(role, now):
            return None
        return await uow.contacts.get_email(role_id)

    async def _send(
        self, uow: UnitOfWork, address: str, outbound: OutboundMessage, outbox_id: str
    ) -> SendReceipt:
        # The tenant's email channel is read here, in the unit of work this message is handled in
        # (a second unit may not be opened inside it), and handed to the resolver (TEN-042). Exactly
        # one active email channel is the tenant's sender; none, or more than one, is no channel.
        channels = [
            channel
            for channel in await uow.tenant_config.channels()
            if channel.kind is ChannelKind.EMAIL and channel.status is NumberStatus.ACTIVE
        ]
        sender: EmailSender = await self._senders.email_for(
            channels[0] if len(channels) == 1 else None
        )
        if outbound.subject is None:
            raise PermanentError(BAD_CONTENT)
        return await sender.send(address, outbound.subject, outbound.text, outbound.html)


def push_runner(
    client: ServiceBusClient,
    uow_factory: UnitOfWorkFactory,
    tenants: ActiveTenants,
    sender: PushSender,
    sealer: ContentSealer,
    clock: Clock,
    app_url: str,
    observe: Observe = untraced,
) -> ServiceBusRunner:
    """The runner of the `push-sender` subscription of `messages.outbound` (I14). It binds the
    message's tenant like the other two senders do; the VAPID key is platform-wide."""
    push = TenantBoundConsumer(
        IdempotentConsumer(
            CONSUMER_PUSH, PushMessageSender(sender, sealer, app_url, clock), uow_factory
        ),
        tenants,
        observe,
    )
    return ServiceBusRunner(client, MESSAGES_TOPIC, PUSH_SUBSCRIPTION, push)


def sender_runners(
    client: ServiceBusClient,
    uow_factory: UnitOfWorkFactory,
    tenants: ActiveTenants,
    senders: SenderResolver,
    sealer: ContentSealer,
    clock: Clock,
    observe: Observe = untraced,
) -> list[ServiceBusRunner]:
    """The two runners of `messages.outbound`: the text sender and the email sender. Each binds the
    tenant of the message before it opens a unit of work (TenantBoundConsumer). The clock decides
    who holds a post when a message goes, which a cover changes."""
    sms = TenantBoundConsumer(
        IdempotentConsumer(CONSUMER_SMS, SmsMessageSender(senders, sealer, clock), uow_factory),
        tenants,
        observe,
    )
    email = TenantBoundConsumer(
        IdempotentConsumer(CONSUMER_EMAIL, EmailMessageSender(senders, sealer, clock), uow_factory),
        tenants,
        observe,
    )
    return [
        ServiceBusRunner(client, MESSAGES_TOPIC, SMS_SUBSCRIPTION, sms),
        ServiceBusRunner(client, MESSAGES_TOPIC, EMAIL_SUBSCRIPTION, email),
    ]


PUSH_URGENT_IDS: Final = frozenset({MessageId.B3, MessageId.K3})
"""The push messages that are high urgency: a booking request (B3) and an alert (K3). Every other
push is normal urgency (I14, DEC-340)."""


def push_urgency(message_id: str) -> str:
    """'high' for a booking request or an alert push, 'normal' otherwise (I14)."""
    try:
        catalogue = MessageId(message_id)
    except ValueError:
        return "normal"
    return "high" if catalogue in PUSH_URGENT_IDS else "normal"


class PushMessageSender:
    """The `push-sender` subscription: Web Push to every installed app of the practitioner who holds
    the recipient role at send time (I14). A subscription the provider reports gone is deleted; the
    communication is sent when any app accepted, and failed otherwise. A transient failure on any
    app retries the whole message (an app that already took it may take it again: a duplicate is
    safer than a missed alert). Content is the bound tenant's template text; the URL is the
    reporter app's root, never anything about a patient."""

    channel = Channel.PUSH
    name = CONSUMER_PUSH

    def __init__(
        self,
        sender: PushSender,
        sealer: ContentSealer,
        app_url: str,
        clock: Clock,
    ) -> None:
        self._sender = sender
        self._sealer = sealer
        self._app_url = app_url
        self._clock = clock

    async def __call__(self, message: BusMessage, uow: UnitOfWork) -> None:
        if message.event_type != SEND_MESSAGE_EVENT:
            raise PermanentError(NOT_A_SEND)
        tenant_id = message.tenant_id
        if not tenant_id:
            raise PermanentError(NO_TENANT)
        if isinstance(message.payload, Mapping) and RECIPIENT_PERSON in message.payload:
            await self._push_to_person(message, uow)
            return
        outbound = parse_outbound(
            message.payload, message_id=message.id, tenant_id=tenant_id, sealer=self._sealer
        )
        if outbound.channel is not self.channel:
            raise PermanentError(BAD_CHANNEL)
        if outbound.subject is None or outbound.subject.strip() == "":
            # The push title is the template's subject line (K3's title, C1's push subject).
            raise PermanentError(BAD_CONTENT)

        communication = await uow.communications.get(outbound.communication_id)
        if communication is None:
            raise PermanentError(NO_COMMUNICATION)
        if is_handled(communication):
            return

        now = self._clock.now()
        role = await uow.people.get_role(outbound.recipient_role_id)
        if role is None:
            await self._settle(uow, message, communication.id, "failed", NO_CONTACT)
            return
        practitioner_id = role_holder(role, now)
        devices = await uow.push_subscriptions.for_practitioner(practitioner_id)
        if not devices:
            await self._settle(uow, message, communication.id, "failed", NO_CONTACT)
            return

        urgency = push_urgency(outbound.message_id)
        accepted = 0
        gone = 0
        refused = 0
        for device in devices:
            try:
                receipt = await self._sender.send(
                    device.subscription,
                    outbound.subject,
                    outbound.text,
                    self._app_url,
                    urgency=urgency,
                )
            except TransientSendError:
                # Retry the whole message: no send is recorded, so the message stays queued.
                raise
            except SendFailedError:
                refused += 1
                continue
            if receipt.accepted:
                accepted += 1
            elif receipt.reason == PUSH_GONE:
                gone += 1
                await uow.push_subscriptions.delete(device.device_id)
            else:
                refused += 1

        if accepted:
            await self._settle(uow, message, communication.id, "sent", message.id)
        elif refused and not gone:
            await self._settle(uow, message, communication.id, "failed", REFUSED)
        else:
            await self._settle(uow, message, communication.id, "failed", NO_CONTACT)

    async def _push_to_person(self, message: BusMessage, uow: UnitOfWork) -> None:
        """A push that names a PERSON (W9H, DEC-1044): an alert (K3) or an executive's test. An
        executive holds no post, so there is no role, no Communication and no sealed content; the
        message carries the plain K3 title and body, which name a service and the kind of alert (or
        the test words) and no patient, no link. One recipient kind per message: a payload that
        also names a role is refused. Delivered to every installed app of the person; a
        subscription the provider reports gone is deleted; a person with no app, or an app that
        refuses, is logged by reason only (the alert's own escalation timer is the follow-up).
        A transient failure raises, so the bus redelivers."""
        payload = message.payload
        if _channel(payload.get("channel")) is not self.channel:
            raise PermanentError(BAD_CHANNEL)
        person = _text(payload.get(RECIPIENT_PERSON))
        title = _text(payload.get("title"))
        body = _text(payload.get("body"))
        if (
            "recipient_role_id" in payload
            or person is None
            or title is None
            or body is None
            or not title.strip()
            or not body.strip()
            or payload.get("message_id") != MessageId.K3.value
            or len(title) > PERSON_TITLE_MAX
            or len(body) > PERSON_BODY_MAX
        ):
            raise PermanentError(BAD_PAYLOAD)
        try:
            render(MessageId.K3, self.channel, title=title, body=body)
        except ValidationFailed:
            raise PermanentError(BAD_CONTENT) from None

        devices = await uow.push_subscriptions.for_practitioner(person)
        accepted = 0
        for device in devices:
            try:
                receipt = await self._sender.send(
                    device.subscription,
                    title,
                    body,
                    self._app_url,
                    urgency=push_urgency(MessageId.K3.value),
                )
            except TransientSendError:
                raise
            except SendFailedError:
                continue
            if receipt.accepted:
                accepted += 1
            elif receipt.reason == PUSH_GONE:
                await uow.push_subscriptions.delete(device.device_id)
        logger.info(
            "%s person push: message=%s apps=%d accepted=%d",
            self.name,
            message.id,
            len(devices),
            accepted,
        )

    async def _settle(
        self,
        uow: UnitOfWork,
        message: BusMessage,
        communication_id: str,
        status: Literal["sent", "failed"],
        error_code_or_message: str,
    ) -> None:
        """Record the outcome. For 'sent' the provider id is the outbox message id (push has no
        receipt id); for 'failed' the reason is the error code."""
        provider_id = message.id if status == "sent" else None
        error_code = None if status == "sent" else error_code_or_message
        recorded = await uow.communications.record_send_outcome(
            communication_id,
            status=status,
            provider_message_id=provider_id,
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
