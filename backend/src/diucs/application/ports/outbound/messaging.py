"""Outbound ports for messages (P07): the SMS, email and push senders, and the record of every
message sent.

The senders stand in for external providers (Twilio for SMS, DEC-002; SMTP; Web Push). Their
recording fakes live in diucs.adapters.testing. The record store is Neo4j and has no fake
(DEC-004, contracts.md "Testing and persistence").
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from diucs.domain.codes import Channel

DELIVERY_STATUSES = frozenset({"queued", "sent", "delivered", "failed", "received"})
"""Statuses a Communication can hold. 'received' marks an inbound message."""


@dataclass(frozen=True, slots=True)
class SendReceipt:
    """The provider's answer to one send. accepted False is a refusal for good (a listed permanent
    refusal, DEC-103): the provider issued no id, so provider_message_id is "". A consumer must not
    store "" as a provider id."""

    provider_message_id: str
    accepted: bool


class TransientSendError(Exception):
    """A send that may succeed on retry: the provider was unreachable, timed out or was busy.

    The caller (the outbox consumer, I10) retries it. No receipt exists for it.
    """


class SendFailedError(Exception):
    """A send the provider answered in a way that is neither accepted nor a listed refusal.

    Not retried: the answer shows a configuration or contract fault that a retry will not fix.
    The error text names the status and the provider's error code only, never the number or body.
    """


@dataclass(frozen=True, slots=True)
class DeliveryUpdate:
    """A provider's delivery report for one message, mapped to the statuses of DELIVERY_STATUSES
    (queued, sent, delivered, failed). error_code is the provider's code, or None."""

    provider_message_id: str
    status: str
    error_code: str | None


class SmsSender(Protocol):
    async def send(self, to: str, text: str, message_id: str) -> SendReceipt: ...


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, text: str, html: str | None) -> SendReceipt: ...


class PushSender(Protocol):
    async def send(
        self, subscription: dict[str, Any], title: str, body: str, url: str
    ) -> SendReceipt: ...


@dataclass(frozen=True, slots=True)
class Communication:
    """One message sent (outbound) or received (inbound). The recipient is a PractitionerRole id,
    never a phone number: phone numbers live only in the protected contact store (P16)."""

    id: str
    message_id: str
    channel: Channel
    recipient_role_id: str | None
    about_id: str | None
    payload_text: str
    sent_at: datetime
    delivery_status: str
    provider_message_id: str | None = None
    in_response_to: str | None = None


class CommunicationRepository(Protocol):
    async def add(self, communication: Communication) -> None: ...

    async def get(self, communication_id: str) -> Communication | None: ...

    async def by_provider_id(self, provider_message_id: str) -> Communication | None: ...

    async def set_delivery_status(self, provider_message_id: str, status: str) -> bool: ...

    async def latest_prompt_for_phone(
        self, role_ids: Collection[str], message_ids: Collection[str]
    ) -> Communication | None: ...
