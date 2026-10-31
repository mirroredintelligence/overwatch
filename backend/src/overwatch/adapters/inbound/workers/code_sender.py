"""The consumer of `codes.dispatch`: it texts a text code to a known number (KI-270).

`RequestTextCode` writes one outbox message for each code asked for: `SendCode` for a number the
platform knows, `DiscardCode` for one it does not, so that both paths do the same work before the
response (H-96). The relay publishes it to `codes.dispatch`; this consumer takes it from the
`code-sender` subscription and:

1. discards a `DiscardCode` without opening anything: an unknown number is never texted;
2. opens the sealed code and the sealed number with the outbox message id, the bound tenant and
   the recipient key as their associated data, so neither belongs to any other message, tenant or
   person (DEC-116). A code is six digits and a number is an international UK mobile, or the
   message is refused for good;
3. drops a code that has lived its ten minutes (the person has asked again, or the code cannot be
   verified any more), without an error;
4. texts the K1 wording from the bound tenant's own sender (DEC-131 item 1). A tenant with no
   text channel sends nothing and is not retried.

A transient failure raises, so the unit of work rolls back and the bus redelivers; the consumer's
marker commits with the unit, so a redelivery after a commit finds it handled. Any other answer of
the provider is logged by reason and not retried: the person asks for a new code after the
cooldown. The consumer writes nothing: no Communication, no audit entry (the request already wrote
the audit entry, with the purpose only), and no log line holds the code, the number or the text.
Errors carry fixed texts only.
"""

import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final

from azure.servicebus.aio import ServiceBusClient

from diucs.adapters.inbound.workers.consumer import IdempotentConsumer, PermanentError
from diucs.adapters.inbound.workers.message_senders import (
    BAD_CONTENT,
    BAD_PAYLOAD,
    NO_CHANNEL,
    NO_TENANT,
    NOT_A_SEND,
    REFUSED,
    SEND_FAILED,
)
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.adapters.inbound.workers.tenant_binding import Observe, TenantBoundConsumer, untraced
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.messaging import SendFailedError, TransientSendError
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.sender_resolver import ChannelUnavailable, SenderResolver
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.use_cases.text_code import (
    CODE_DIGITS,
    CODES_TOPIC,
    DISCARD_CODE,
    PURPOSES,
    SEND_CODE,
)
from diucs.domain.codes import Channel
from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.rules.identity_policy import CODE_VALID_FOR

logger = logging.getLogger(__name__)

CODE_SUBSCRIPTION: Final = "code-sender"
CONSUMER_CODE: Final = "sender-code"

EXPIRED: Final = "expired"
DISCARDED: Final = "discarded"
SENT: Final = "sent"

_CODE_PATTERN: Final = re.compile(rf"[0-9]{{{CODE_DIGITS}}}")
_PHONE_PATTERN: Final = re.compile(r"\+447[0-9]{9}")
_KEY_PREFIX: Final = "code:"


def _text(value: object) -> str | None:
    return value if type(value) is str and value else None


class _Opened:
    """One code and where it goes, read from a payload that has passed every check."""

    __slots__ = ("code", "issued_at", "phone")

    def __init__(self, code: str, phone: str, issued_at: datetime) -> None:
        self.code = code
        self.phone = phone
        self.issued_at = issued_at


def _issued_at(value: object) -> datetime:
    text = _text(value)
    if text is None:
        raise PermanentError(BAD_PAYLOAD)
    try:
        issued = datetime.fromisoformat(text)
    except ValueError:
        raise PermanentError(BAD_PAYLOAD) from None
    if issued.utcoffset() is None:
        raise PermanentError(BAD_PAYLOAD)
    return issued.astimezone(UTC)


def open_code(
    payload: object, *, message_id: str, tenant_id: str, sealer: ContentSealer
) -> _Opened:
    """The code, the number and the issue time of a SendCode payload. Raises PermanentError for a
    payload that can never be sent, and for a seal that does not open for this message, tenant and
    recipient key. Nothing in the error holds the code or the number."""
    if not isinstance(payload, Mapping):
        raise PermanentError(BAD_PAYLOAD)
    sealed_code = _text(payload.get("sealed_code"))
    sealed_phone = _text(payload.get("sealed_phone"))
    key = _text(payload.get("recipient_key"))
    purpose = _text(payload.get("purpose"))
    if sealed_code is None or sealed_phone is None or key is None or purpose is None:
        raise PermanentError(BAD_PAYLOAD)
    if purpose not in PURPOSES:
        raise PermanentError(BAD_PAYLOAD)
    # The key is `code:<phone hash>:<purpose>` (text_code.code_key): the purpose must be the one
    # the message names, so a key for another purpose is not accepted.
    if not key.startswith(_KEY_PREFIX) or not key.endswith(f":{purpose}"):
        raise PermanentError(BAD_PAYLOAD)
    if len(key) <= len(_KEY_PREFIX) + len(purpose) + 1:
        raise PermanentError(BAD_PAYLOAD)
    issued_at = _issued_at(payload.get("issued_at"))

    try:
        code = sealer.unseal(
            sealed_code, message_id=message_id, tenant_id=tenant_id, recipient_role_id=key
        )
        phone = sealer.unseal(
            sealed_phone, message_id=message_id, tenant_id=tenant_id, recipient_role_id=key
        )
    except ValidationFailed:
        raise PermanentError(BAD_CONTENT) from None
    if _CODE_PATTERN.fullmatch(code) is None or _PHONE_PATTERN.fullmatch(phone) is None:
        raise PermanentError(BAD_CONTENT)
    return _Opened(code, phone, issued_at)


class CodeMessageSender:
    """The `code-sender` subscription: texts a code from the bound tenant's number (KI-270)."""

    name = CONSUMER_CODE

    def __init__(self, senders: SenderResolver, sealer: ContentSealer, clock: Clock) -> None:
        self._senders = senders
        self._sealer = sealer
        self._clock = clock

    async def __call__(self, message: BusMessage, uow: UnitOfWork) -> None:
        if message.event_type == DISCARD_CODE:
            # A code for a number nobody knows: written so both paths made the same calls, never
            # opened, never sent.
            self._log(message.id, DISCARDED)
            return
        if message.event_type != SEND_CODE:
            raise PermanentError(NOT_A_SEND)
        tenant_id = message.tenant_id
        if not tenant_id:
            raise PermanentError(NO_TENANT)
        opened = open_code(
            message.payload, message_id=message.id, tenant_id=tenant_id, sealer=self._sealer
        )
        if self._clock.now().astimezone(UTC) - opened.issued_at >= CODE_VALID_FOR:
            self._log(message.id, EXPIRED)
            return
        try:
            wording = render(MessageId.K1, Channel.TEXT, code=opened.code).text
        except ValidationFailed:
            raise PermanentError(BAD_CONTENT) from None
        try:
            sender = await self._senders.sms_for()
        except ChannelUnavailable:
            self._log(message.id, NO_CHANNEL)
            return
        try:
            receipt = await sender.send(opened.phone, wording, message.id)
        except TransientSendError:
            raise
        except SendFailedError as error:
            self._log(message.id, SEND_FAILED, type(error).__name__)
            return
        self._log(message.id, SENT if receipt.accepted else REFUSED)

    def _log(self, message_id: str, reason: str, detail: str = "-") -> None:
        # The message id and a reason word only: never the code, the number or the text.
        logger.info("%s: message=%s status=%s detail=%s", self.name, message_id, reason, detail)


def code_runner(
    client: ServiceBusClient,
    uow_factory: UnitOfWorkFactory,
    tenants: ActiveTenants,
    senders: SenderResolver,
    sealer: ContentSealer,
    clock: Clock,
    observe: Observe = untraced,
) -> ServiceBusRunner:
    """The runner of the `code-sender` subscription of `codes.dispatch`. It binds the tenant of the
    message before it opens a unit of work, like the other senders do."""
    consumer = TenantBoundConsumer(
        IdempotentConsumer(CONSUMER_CODE, CodeMessageSender(senders, sealer, clock), uow_factory),
        tenants,
        observe,
    )
    return ServiceBusRunner(client, CODES_TOPIC, CODE_SUBSCRIPTION, consumer)


__all__ = [
    "CODES_TOPIC",
    "CODE_SUBSCRIPTION",
    "CONSUMER_CODE",
    "DISCARDED",
    "EXPIRED",
    "CodeMessageSender",
    "code_runner",
    "open_code",
]
