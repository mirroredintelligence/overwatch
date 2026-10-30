"""The email sender reads the tenant's active email channel in its own unit of work and hands it to
the resolver (TEN-042). The resolver is a recorder and the unit of work a stub, so no Docker is
needed; the behaviour on real Neo4j is in tests/integration/adapters/inbound/workers/. Sample values
only."""

import json
from datetime import UTC, datetime
from typing import Any

from diucs.adapters.inbound.workers.message_senders import (
    MESSAGES_TOPIC,
    SEND_MESSAGE_EVENT,
    EmailMessageSender,
    SmsMessageSender,
)
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.recording_senders import RecordingEmailSender, RecordingSmsSender
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.messaging import Communication, EmailSender, SmsSender
from diucs.application.ports.outbound.sender_resolver import ChannelUnavailable
from diucs.domain.codes import Channel
from diucs.domain.model.tenant import NumberStatus
from diucs.domain.model.tenant_records import ChannelKind, ChannelProvider, TenantChannel

SEALER = AesGcmContentSealer(
    FixedSecretStore({"link-token": b"link-token-test-secret-0123456789abcdef"})
)
TENANT = "tenant-a"
ROLE = "role-1"
OUTBOX_ID = "outbox-1"


def _email_channel(channel_id: str, status: NumberStatus) -> TenantChannel:
    return TenantChannel(
        id=channel_id,
        kind=ChannelKind.EMAIL,
        provider=ChannelProvider.SMTP,
        status=status,
        sender_label="Capacity email",
        from_address="capacity@example-icb.test",
    )


def _sms_channel() -> TenantChannel:
    return TenantChannel(
        id="sms-1",
        kind=ChannelKind.SMS,
        provider=ChannelProvider.TWILIO,
        status=NumberStatus.ACTIVE,
        sender_label="Text",
        account_sid="AC" + "1" * 32,
        secret_ref=f"twilio/{TENANT}/auth-token",
    )


class _Config:
    def __init__(self, channels: tuple[TenantChannel, ...]) -> None:
        self._channels = channels
        self.reads = 0

    async def channels(self) -> tuple[TenantChannel, ...]:
        self.reads += 1
        return self._channels


class _Communications:
    def __init__(self) -> None:
        self.outcomes: list[tuple[str, str, str | None, str | None]] = []

    async def get(self, communication_id: str) -> Communication:
        return Communication(
            id=communication_id,
            message_id="C1",
            channel=Channel.EMAIL,
            recipient_role_id=ROLE,
            about_id=None,
            payload_text="x",
            sent_at=datetime(2026, 10, 23, 13, 0, tzinfo=UTC),
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


class _Contacts:
    async def get_email(self, role_id: str) -> str:
        return "role.inbox@example.test"

    async def get_phone(self, role_id: str) -> str:
        return "07700900123"


class _Unit:
    def __init__(self, channels: tuple[TenantChannel, ...]) -> None:
        self.tenant_config = _Config(channels)
        self.communications = _Communications()
        self.contacts = _Contacts()


class _Resolver:
    """Records the channel it was handed and answers with a recording sender."""

    def __init__(self, unavailable: bool = False) -> None:
        self.channels: list[TenantChannel | None] = []
        self.email = RecordingEmailSender()
        self.sms = RecordingSmsSender()
        self._unavailable = unavailable

    async def sms_for(self) -> SmsSender:
        return self.sms

    async def email_for(self, channel: TenantChannel | None) -> EmailSender:
        self.channels.append(channel)
        if self._unavailable:
            raise ChannelUnavailable(f"no email channel for tenant {TENANT}")
        return self.email


def _message(channel: str) -> BusMessage:
    content = json.dumps(
        {
            "text": "How many referrals?",
            "subject": "UCR West: confirm" if channel == "email" else None,
            "html": None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return BusMessage(
        id=OUTBOX_ID,
        topic=MESSAGES_TOPIC,
        event_type=SEND_MESSAGE_EVENT,
        payload={
            "communication_id": "comm-1",
            "message_id": "C1",
            "channel": channel,
            "recipient_role_id": ROLE,
            "sealed_content": SEALER.seal(
                content, message_id=OUTBOX_ID, tenant_id=TENANT, recipient_role_id=ROLE
            ),
        },
        tenant_id=TENANT,
    )


async def test_the_active_email_channel_is_read_in_the_unit_and_handed_to_the_resolver() -> None:
    active = _email_channel("email-1", NumberStatus.ACTIVE)
    unit: Any = _Unit((_sms_channel(), _email_channel("email-0", NumberStatus.RETIRED), active))
    resolver = _Resolver()

    await EmailMessageSender(resolver, SEALER)(_message("email"), unit)

    assert resolver.channels == [active]
    assert unit.communications.outcomes == [("comm-1", "sent", "email-1", None)]
    assert [m.subject for m in resolver.email.sent] == ["UCR West: confirm"]


async def test_with_no_active_email_channel_the_resolver_gets_none_and_nothing_is_sent() -> None:
    unit: Any = _Unit((_sms_channel(), _email_channel("email-0", NumberStatus.RETIRED)))
    resolver = _Resolver(unavailable=True)

    await EmailMessageSender(resolver, SEALER)(_message("email"), unit)

    assert resolver.channels == [None]
    assert resolver.email.sent == []
    assert unit.communications.outcomes == [("comm-1", "failed", None, "no-channel")]


async def test_two_active_email_channels_are_ambiguous_and_none_is_used() -> None:
    unit: Any = _Unit(
        (
            _email_channel("email-1", NumberStatus.ACTIVE),
            _email_channel("email-2", NumberStatus.ACTIVE),
        )
    )
    resolver = _Resolver(unavailable=True)

    await EmailMessageSender(resolver, SEALER)(_message("email"), unit)

    assert resolver.channels == [None]
    assert resolver.email.sent == []


async def test_a_text_send_reads_no_email_channel() -> None:
    unit: Any = _Unit((_email_channel("email-1", NumberStatus.ACTIVE),))
    resolver = _Resolver()

    await SmsMessageSender(resolver, SEALER)(_message("text"), unit)

    assert unit.tenant_config.reads == 0
    assert resolver.channels == []
