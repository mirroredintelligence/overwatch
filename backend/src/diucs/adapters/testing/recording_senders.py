"""Recording senders (P07): fakes for external providers only (DEC-002, DEC-004).

Each fake returns a receipt with a provider id (sms-1, sms-2, ...; email-n; push-n). Every send
consumes one number, so a refused send still has an id. Only accepted sends are kept in `sent`.
fail_next() refuses the next send only, which lets a test prove how a caller handles a refusal.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from diucs.application.ports.outbound.messaging import (
    PUSH_GONE,
    EmailSender,
    SendReceipt,
    SmsSender,
)
from diucs.application.ports.outbound.sender_resolver import ChannelUnavailable
from diucs.application.tenancy import current_tenant
from diucs.domain.model.tenant_records import TenantChannel


@dataclass(frozen=True, slots=True)
class RecordedSms:
    to: str
    text: str
    message_id: str
    tenant: str | None = None
    identity: str | None = None


@dataclass(frozen=True, slots=True)
class RecordedEmail:
    to: str
    subject: str
    text: str
    html: str | None
    tenant: str | None = None
    identity: str | None = None


@dataclass(frozen=True, slots=True)
class RecordedPush:
    subscription: dict[str, Any]
    title: str
    body: str
    url: str
    urgency: str = "normal"


class _Attempts:
    """Numbers the provider ids and remembers whether the next send is to be refused."""

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._count = 0
        self._refuse_next = False

    def fail_next(self) -> None:
        self._refuse_next = True

    def next_receipt(self) -> SendReceipt:
        self._count += 1
        accepted = not self._refuse_next
        self._refuse_next = False
        return SendReceipt(f"{self._prefix}-{self._count}", accepted)


class RecordingSmsSender:
    def __init__(self, identity: str | None = None) -> None:
        self.sent: list[RecordedSms] = []
        self._attempts = _Attempts("sms")

    async def send(self, to: str, text: str, message_id: str) -> SendReceipt:
        receipt = self._attempts.next_receipt()
        if receipt.accepted:
            self.sent.append(RecordedSms(to, text, message_id))
        return receipt

    def fail_next(self) -> None:
        self._attempts.fail_next()


class RecordingEmailSender:
    def __init__(self, identity: str | None = None) -> None:
        self.sent: list[RecordedEmail] = []
        self._attempts = _Attempts("email")

    async def send(self, to: str, subject: str, text: str, html: str | None) -> SendReceipt:
        receipt = self._attempts.next_receipt()
        if receipt.accepted:
            self.sent.append(RecordedEmail(to, subject, text, html))
        return receipt

    def fail_next(self) -> None:
        self._attempts.fail_next()


class RecordingPushSender:
    def __init__(self) -> None:
        self.sent: list[RecordedPush] = []
        self._attempts = _Attempts("push")
        self._gone_next = 0

    async def send(
        self,
        subscription: dict[str, Any],
        title: str,
        body: str,
        url: str,
        *,
        urgency: str = "normal",
    ) -> SendReceipt:
        if self._gone_next > 0:
            self._gone_next -= 1
            return SendReceipt(provider_message_id="", accepted=False, reason=PUSH_GONE)
        receipt = self._attempts.next_receipt()
        if receipt.accepted:
            self.sent.append(RecordedPush(dict(subscription), title, body, url, urgency))
        return receipt

    def fail_next(self) -> None:
        self._attempts.fail_next()

    def gone_next(self) -> None:
        """The next subscription is gone (the provider answered 410): refused, reason `gone`. Each
        call marks one more send, so two calls make the next two sends gone."""
        self._gone_next += 1


class FixedSenderResolver:
    """A SenderResolver for tests: each tenant gets its own recording sender, read from the tenant
    bound on the unit of work (current_tenant). A tenant that is not listed has no channel, so the
    resolver raises ChannelUnavailable and nothing is sent for it (I10)."""

    def __init__(
        self,
        sms: Mapping[str, SmsSender] | None = None,
        email: Mapping[str, EmailSender] | None = None,
    ) -> None:
        self._sms = dict(sms or {})
        self._email = dict(email or {})

    async def sms_for(self) -> SmsSender:
        tenant = current_tenant()
        sender = self._sms.get(tenant)
        if sender is None:
            raise ChannelUnavailable(f"no text channel for tenant {tenant}")
        return sender

    async def email_for(self, channel: TenantChannel | None = None) -> EmailSender:
        tenant = current_tenant()
        sender = self._email.get(tenant)
        if sender is None:
            raise ChannelUnavailable(f"no email channel for tenant {tenant}")
        return sender
