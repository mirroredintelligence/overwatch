"""Outbound ports for messages (P07): the SMS, email and push senders, and the record of every
message sent.

The senders stand in for external providers (Twilio for SMS, DEC-002; SMTP; Web Push). Their
recording fakes live in diucs.adapters.testing. The record store is Neo4j and has no fake
(DEC-004, contracts.md "Testing and persistence").
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol

from diucs.domain.codes import Channel

GROUPED_STATUS: Final = "grouped"
"""One C9 text covers every service of a grouped prompt (U04). It is recorded as one Communication
for each service; the one that is sent is 'queued' and moves on as any message does, the others are
'grouped' and never move: they have no message of their own."""

DELIVERY_STATUSES = frozenset({"queued", "sent", "delivered", "failed", "received", GROUPED_STATUS})
"""Statuses a Communication can hold. 'received' marks an inbound message."""


_STATUS_RANK: Final = {"queued": 0, "sent": 1, "delivered": 2, "failed": 2}
"""The order of a sent message's delivery status. delivered and failed share the last rank: both are
final, and neither follows the other."""


def statuses_before(status: str) -> tuple[str, ...]:
    """The delivery statuses a Communication may move from to reach `status`: the ones of a lower
    rank (queued, then sent, then delivered or failed). Nothing leaves delivered or failed, nothing
    repeats itself, and 'received' and 'grouped' never move (they are reached from nothing). A
    status the system does not know is a ValueError."""
    if status not in DELIVERY_STATUSES:
        raise ValueError("not a delivery status")
    rank = _STATUS_RANK.get(status)
    if rank is None:
        return ()
    return tuple(sorted(name for name, other in _STATUS_RANK.items() if other < rank))


PUSH_GONE: Final = "gone"
"""The reason of a push receipt whose subscription the provider no longer holds (404 or 410). The
caller deletes that subscription (I14)."""


@dataclass(frozen=True, slots=True)
class SendReceipt:
    provider_message_id: str
    accepted: bool
    reason: str | None = None
    """Why a refused send was refused, when the provider's answer says (push: PUSH_GONE). None
    for an accepted send."""


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
        self,
        subscription: dict[str, Any],
        title: str,
        body: str,
        url: str,
        *,
        urgency: str = "normal",
    ) -> SendReceipt:
        """Send one push to one installed app. urgency is 'high' for a booking request or an alert,
        'normal' otherwise. A gone subscription is a refused receipt with reason PUSH_GONE; a busy
        provider raises TransientSendError."""
        ...


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


@dataclass(frozen=True, slots=True)
class PromptDue:
    """A capacity prompt that was sent in a period: the service it asked about and when it was sent,
    which is its due time (U35). Ids and times only, no phone number."""

    service_id: str
    due_at: datetime


class CommunicationRepository(Protocol):
    async def prompts_due_between(self, start: datetime, end: datetime) -> list[PromptDue]:
        """The capacity prompts (C1 and grouped C9) sent at or after `start` and before `end`, each
        with the service it is about, oldest first (U35)."""
        ...

    async def add(self, communication: Communication) -> None: ...

    async def get(self, communication_id: str) -> Communication | None: ...

    async def by_provider_id(self, provider_message_id: str) -> Communication | None: ...

    async def set_delivery_status(self, provider_message_id: str, status: str) -> bool:
        """Move the record with this provider id forward to `status` and return True; return False
        when there is no such record or it may not move there. A status only moves forward and
        delivered and failed are final (`statuses_before`), decided in the store under the record's
        write lock, so two receipts handled at once cannot make it go back (I08, DEC-165). An
        unknown status is a ValidationFailed."""
        ...

    async def latest_prompt_for_phone(
        self, role_ids: Collection[str], message_ids: Collection[str]
    ) -> Communication | None: ...

    async def recent_prompts_for_roles(
        self, role_ids: Collection[str], message_ids: Collection[str], since: datetime
    ) -> list[Communication]:
        """Every prompt of these message ids sent to any of these roles at or after `since`, newest
        first (KI-137): a report stops the ladder of each prompt it answers, not only the latest."""
        ...

    async def record_send_outcome(
        self,
        communication_id: str,
        *,
        status: str,
        provider_message_id: str | None,
        error_code: str | None,
    ) -> bool:
        """Record what the send of a queued communication did (I10): move it to `sent` (with the
        provider id) or to `failed`, and keep the reason as `error_code` (for example no-contact).
        Only a communication still queued, with no provider id, moves; the write takes the record's
        lock first, so two senders cannot both record a send. Returns False when nothing moved.
        Status is 'sent' or 'failed' only: a receipt moves a sent message on (I08)."""


@dataclass(frozen=True, slots=True)
class PushSubscription:
    """A Web Push subscription of one installed app on one device (P19). The subscription JSON
    (endpoint and keys) is a capability secret: it is never logged, audited or sent to telemetry."""

    device_id: str
    practitioner_id: str
    subscription: dict[str, Any]
    saved_at: datetime


class PushSubscriptionRepository(Protocol):
    """Push subscriptions, one per device (P19). Adapter: Neo4jPushSubscriptionRepository
    (graph_store/push_subscription_repository.py). Saving for a device replaces its subscription;
    deleting removes the subscription properties and keeps the Device."""

    async def save(self, subscription: PushSubscription) -> None:
        """Store the subscription of its device, replacing any earlier one. An unknown practitioner
        raises NotFound and writes nothing."""
        ...

    async def for_practitioner(self, practitioner_id: str) -> list[PushSubscription]:
        """The subscriptions of this practitioner's devices, newest first."""
        ...

    async def delete(self, device_id: str) -> None:
        """Remove the subscription of this device. The Device stays."""
        ...
