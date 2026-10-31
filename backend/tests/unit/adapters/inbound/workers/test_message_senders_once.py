"""A text the provider accepted is not sent again when the commit after it fails (KI-185, H-46).

The provider call and the commit of its record are separate. When the commit fails after the
provider accepted the text, the bus redelivers, and the sender used to send it again. The sender now
remembers, for each outbox message, the receipt of the send the provider accepted: a redelivery in
the same process records that receipt and calls the provider no more. The memory is bounded and a
refusal, a failure and a transient error are not kept (a retry must send). A redelivery to another
process, or after a restart, can still send twice: the residual of I10-1, now narrower.

The unit of work is a stub that never commits, as a commit that fails would not; the senders are the
recording fakes, so no message is sent.
"""

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.inbound.workers.message_senders import (
    MESSAGES_TOPIC,
    SEND_MESSAGE_EVENT,
    EmailMessageSender,
    SmsMessageSender,
)
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.recording_senders import RecordingEmailSender, RecordingSmsSender
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.messaging import (
    Communication,
    EmailSender,
    SendReceipt,
    SmsSender,
    TransientSendError,
)
from diucs.application.tenancy import ScopeId
from diucs.domain.codes import Channel
from diucs.domain.model.tenant import NumberStatus
from diucs.domain.model.tenant_records import (
    ChannelKind,
    ChannelProvider,
    TenantChannel,
)
from tests.support.tenancy import as_tenant

SEALER = AesGcmContentSealer(
    FixedSecretStore({"link-token": b"link-token-test-secret-0123456789abcdef"})
)
TENANT = "tenant-a"
ROLE = "role-1"
NOW = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)


class _Communications:
    def __init__(self) -> None:
        self.outcomes: list[tuple[str, str, str | None, str | None]] = []

    async def get(self, communication_id: str) -> Communication:
        # Always queued: the commit that would have recorded the send failed.
        return Communication(
            id=communication_id,
            message_id="C3",
            channel=Channel.TEXT,
            recipient_role_id=ROLE,
            about_id=None,
            payload_text="x",
            sent_at=NOW,
            delivery_status="queued",
        )

    async def record_send_outcome(
        self,
        communication_id: str,
        *,
        status: str,
        provider_message_id: str | None,
        error_code: str | None,
    ) -> bool:
        self.outcomes.append((communication_id, status, provider_message_id, error_code))
        return True


class _People:
    async def get_role(self, role_id: str) -> None:
        return None


class _Contacts:
    async def get_phone(self, role_id: str) -> str:
        return "+447700900111"

    async def get_email(self, role_id: str) -> str:
        return "post.holder@example.test"


class _Config:
    async def channels(self) -> tuple[TenantChannel, ...]:
        return (
            TenantChannel(
                id="email-1",
                kind=ChannelKind.EMAIL,
                provider=ChannelProvider.SMTP,
                status=NumberStatus.ACTIVE,
                sender_label="Capacity email",
                from_address="capacity@example-icb.test",
            ),
        )


class _Unit:
    unit_scope = ScopeId.tenant(TENANT)

    def __init__(self) -> None:
        self.people = _People()
        self.contacts = _Contacts()
        self.communications = _Communications()
        self.tenant_config = _Config()


class _Resolver:
    def __init__(self, sms: Any = None) -> None:
        self.sms = sms if sms is not None else RecordingSmsSender()
        self.email = RecordingEmailSender()

    async def sms_for(self) -> SmsSender:
        return self.sms  # type: ignore[no-any-return]

    async def email_for(self, channel: TenantChannel | None) -> EmailSender:
        return self.email


def _message(outbox_id: str = "outbox-1", channel: str = "text") -> BusMessage:
    content = json.dumps(
        {
            "text": "Thanks.",
            "subject": "Subject" if channel == "email" else None,
            "html": None,
        }
    )
    return BusMessage(
        id=outbox_id,
        topic=MESSAGES_TOPIC,
        event_type=SEND_MESSAGE_EVENT,
        payload={
            "communication_id": f"comm-{outbox_id}",
            "message_id": "C3",
            "channel": channel,
            "recipient_role_id": ROLE,
            "sealed_content": SEALER.seal(
                content, message_id=outbox_id, tenant_id=TENANT, recipient_role_id=ROLE
            ),
        },
        tenant_id=TENANT,
    )


async def _deliver(sender: Any, message: BusMessage, unit: _Unit) -> None:
    with as_tenant(TENANT):
        await sender(message, unit)


async def test_a_redelivery_after_a_failed_commit_records_the_same_send_and_sends_nothing() -> None:
    resolver = _Resolver()
    sender = SmsMessageSender(resolver, SEALER, FixedClock(NOW))
    first, second = _Unit(), _Unit()

    await _deliver(sender, _message(), first)  # the commit after this fails
    await _deliver(sender, _message(), second)  # the bus redelivers

    assert len(resolver.sms.sent) == 1
    assert first.communications.outcomes == [("comm-outbox-1", "sent", "sms-1", None)]
    assert second.communications.outcomes == [("comm-outbox-1", "sent", "sms-1", None)]


async def test_two_different_messages_are_both_sent() -> None:
    resolver = _Resolver()
    sender = SmsMessageSender(resolver, SEALER, FixedClock(NOW))

    await _deliver(sender, _message("outbox-1"), _Unit())
    await _deliver(sender, _message("outbox-2"), _Unit())

    assert len(resolver.sms.sent) == 2


async def test_a_transient_failure_is_not_remembered_so_the_retry_sends() -> None:
    class _FailsOnce:
        def __init__(self) -> None:
            self.calls = 0
            self.sent: list[str] = []

        async def send(self, to: str, text: str, message_id: str) -> SendReceipt:
            self.calls += 1
            if self.calls == 1:
                raise TransientSendError("the provider could not be reached")
            self.sent.append(to)
            return SendReceipt("sms-9", True)

    provider = _FailsOnce()
    sender = SmsMessageSender(_Resolver(provider), SEALER, FixedClock(NOW))

    with pytest.raises(TransientSendError):
        await _deliver(sender, _message(), _Unit())
    await _deliver(sender, _message(), _Unit())

    assert provider.sent == ["+447700900111"]


async def test_a_refusal_is_not_remembered() -> None:
    sms = RecordingSmsSender()
    sms.fail_next()
    resolver = _Resolver(sms)
    sender = SmsMessageSender(resolver, SEALER, FixedClock(NOW))
    refused = _Unit()

    await _deliver(sender, _message(), refused)
    await _deliver(sender, _message(), _Unit())

    assert refused.communications.outcomes[0][1] == "failed"
    assert len(sms.sent) == 1


async def test_the_memory_is_bounded_and_forgets_the_oldest_message_first() -> None:
    resolver = _Resolver()
    sender = SmsMessageSender(resolver, SEALER, FixedClock(NOW), ledger_size=2)

    for number in (1, 2, 3):
        await _deliver(sender, _message(f"outbox-{number}"), _Unit())
    await _deliver(sender, _message("outbox-3"), _Unit())  # remembered: not sent again
    await _deliver(sender, _message("outbox-1"), _Unit())  # forgotten: sent again

    assert len(resolver.sms.sent) == 4


async def test_the_email_sender_does_not_send_twice_either() -> None:
    resolver = _Resolver()
    sender = EmailMessageSender(resolver, SEALER, FixedClock(NOW))
    first, second = _Unit(), _Unit()

    await _deliver(sender, _message(channel="email"), first)
    await _deliver(sender, _message(channel="email"), second)

    assert len(resolver.email.sent) == 1
    assert second.communications.outcomes == [("comm-outbox-1", "sent", "email-1", None)]


async def test_the_memory_holds_no_number_text_or_code() -> None:
    sender = SmsMessageSender(_Resolver(), SEALER, FixedClock(NOW))
    await _deliver(sender, _message(), _Unit())

    held = repr(vars(sender))

    assert "447700900111" not in held and "Thanks" not in held
