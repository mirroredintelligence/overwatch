"""A message goes to whoever holds the recipient post now (F6B): while a cover runs, the cover's
number, never the original holder's. The text and email senders read the post, then the contact
that `phone_contact_key` names. The unit of work is a stub and the senders are the recording fakes,
so no message is sent and no Docker is needed. The sample numbers are the `07700 900xxx` range.
"""

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from typing import Any

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
from diucs.application.ports.outbound.messaging import Communication, EmailSender, SmsSender
from diucs.domain.codes import Channel, PractitionerRoleCode
from diucs.domain.model.people import PractitionerRole
from diucs.domain.model.tenant import NumberStatus
from diucs.domain.model.tenant_records import ChannelKind, ChannelProvider, TenantChannel

SEALER = AesGcmContentSealer(
    FixedSecretStore({"link-token": b"link-token-test-secret-0123456789abcdef"})
)
TENANT = "tenant-a"
ROLE = "role-1"
OUTBOX_ID = "outbox-1"
NOW = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
OWN_NUMBER = "+447700900111"
COVER_NUMBER = "+447700900222"
OWN_EMAIL = "post.holder@example.test"

POST = PractitionerRole(
    id=ROLE,
    practitioner_id="p-own",
    service_id="svc-ucr-west",
    code=PractitionerRoleCode.DUTY_MANAGER,
    active=True,
    channel=Channel.TEXT,
    period_start=datetime(2026, 10, 1, tzinfo=UTC),
)
COVERED = dataclasses.replace(
    POST, covered_by_practitioner_id="p-cover", covered_until=NOW + timedelta(hours=9)
)


class _People:
    def __init__(self, role: PractitionerRole | None) -> None:
        self._role = role

    async def get_role(self, role_id: str) -> PractitionerRole | None:
        return self._role if self._role is not None and self._role.id == role_id else None


class _Contacts:
    def __init__(self, phones: dict[str, str], emails: dict[str, str]) -> None:
        self._phones = phones
        self._emails = emails

    async def get_phone(self, role_id: str) -> str | None:
        return self._phones.get(role_id)

    async def get_email(self, role_id: str) -> str | None:
        return self._emails.get(role_id)


class _Communications:
    def __init__(self, channel: Channel) -> None:
        self._channel = channel
        self.outcomes: list[tuple[str, str, str | None, str | None]] = []

    async def get(self, communication_id: str) -> Communication:
        return Communication(
            id=communication_id,
            message_id="C1",
            channel=self._channel,
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
    def __init__(
        self,
        role: PractitionerRole | None,
        channel: Channel,
        phones: dict[str, str],
        emails: dict[str, str] | None = None,
    ) -> None:
        self.people = _People(role)
        self.contacts = _Contacts(phones, emails if emails is not None else {ROLE: OWN_EMAIL})
        self.communications = _Communications(channel)
        self.tenant_config = _Config()


class _Resolver:
    def __init__(self) -> None:
        self.sms = RecordingSmsSender()
        self.email = RecordingEmailSender()

    async def sms_for(self) -> SmsSender:
        return self.sms

    async def email_for(self, channel: TenantChannel | None) -> EmailSender:
        return self.email


def _message(channel: str, recipient: str = ROLE) -> BusMessage:
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
            "recipient_role_id": recipient,
            "sealed_content": SEALER.seal(
                content, message_id=OUTBOX_ID, tenant_id=TENANT, recipient_role_id=recipient
            ),
        },
        tenant_id=TENANT,
    )


async def _text(unit: Any, at: datetime = NOW, recipient: str = ROLE) -> _Resolver:
    resolver = _Resolver()
    await SmsMessageSender(resolver, SEALER, FixedClock(at))(_message("text", recipient), unit)
    return resolver


async def test_a_text_for_a_post_with_no_cover_goes_to_the_posts_own_number() -> None:
    unit = _Unit(POST, Channel.TEXT, {ROLE: OWN_NUMBER})

    resolver = await _text(unit)

    assert [sent.to for sent in resolver.sms.sent] == [OWN_NUMBER]
    assert unit.communications.outcomes == [("comm-1", "sent", "sms-1", None)]


async def test_a_text_during_a_cover_goes_to_the_covers_number_not_the_original_holders() -> None:
    unit = _Unit(COVERED, Channel.TEXT, {ROLE: OWN_NUMBER, f"cover-{ROLE}": COVER_NUMBER})

    resolver = await _text(unit)

    assert [sent.to for sent in resolver.sms.sent] == [COVER_NUMBER]
    assert OWN_NUMBER not in [sent.to for sent in resolver.sms.sent]
    assert unit.communications.outcomes == [("comm-1", "sent", "sms-1", None)]


async def test_a_text_after_the_cover_has_ended_goes_back_to_the_posts_own_number() -> None:
    unit = _Unit(COVERED, Channel.TEXT, {ROLE: OWN_NUMBER, f"cover-{ROLE}": COVER_NUMBER})
    assert COVERED.covered_until is not None

    resolver = await _text(unit, at=COVERED.covered_until)

    assert [sent.to for sent in resolver.sms.sent] == [OWN_NUMBER]


async def test_a_text_a_minute_before_the_cover_ends_still_goes_to_the_cover() -> None:
    unit = _Unit(COVERED, Channel.TEXT, {ROLE: OWN_NUMBER, f"cover-{ROLE}": COVER_NUMBER})
    assert COVERED.covered_until is not None

    resolver = await _text(unit, at=COVERED.covered_until - timedelta(minutes=1))

    assert [sent.to for sent in resolver.sms.sent] == [COVER_NUMBER]


async def test_during_a_cover_with_no_cover_number_nothing_is_sent_to_the_original_holder() -> None:
    # A cover set without a number kept (a service move, U37): the original holder has handed the
    # post on, so the text is not sent to them. The Communication records no contact.
    unit = _Unit(COVERED, Channel.TEXT, {ROLE: OWN_NUMBER})

    resolver = await _text(unit)

    assert resolver.sms.sent == []
    assert unit.communications.outcomes == [("comm-1", "failed", None, "no-contact")]


async def test_a_text_for_a_key_that_is_not_a_post_is_addressed_by_the_key() -> None:
    # Text codes and a few other messages are addressed by a contact key that is not a role.
    unit = _Unit(None, Channel.TEXT, {"key-9": OWN_NUMBER})

    resolver = await _text(unit, recipient="key-9")

    assert [sent.to for sent in resolver.sms.sent] == [OWN_NUMBER]


async def test_an_email_during_a_cover_is_not_sent_to_the_original_holders_address() -> None:
    unit = _Unit(COVERED, Channel.EMAIL, {ROLE: OWN_NUMBER, f"cover-{ROLE}": COVER_NUMBER})
    resolver = _Resolver()

    await EmailMessageSender(resolver, SEALER, FixedClock(NOW))(_message("email"), unit)

    assert resolver.email.sent == []
    assert unit.communications.outcomes == [("comm-1", "failed", None, "no-contact")]


async def test_an_email_with_no_cover_goes_to_the_posts_own_address() -> None:
    unit = _Unit(POST, Channel.EMAIL, {ROLE: OWN_NUMBER})
    resolver = _Resolver()

    await EmailMessageSender(resolver, SEALER, FixedClock(NOW))(_message("email"), unit)

    assert [sent.to for sent in resolver.email.sent] == [OWN_EMAIL]
