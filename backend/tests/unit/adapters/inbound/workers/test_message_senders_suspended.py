"""A prompt that was queued before its service was suspended is not sent after it (KI-388, H-137).

SendPrompts skips a suspended service when it runs, and a suspension cancels the rest of the chain,
but a prompt that SendPrompts had already queued (a Communication and an outbox message) still went
out when the sender got to it. The sender now looks at the service the prompt asks about, at send
time, and sends nothing for one that is suspended or no longer active: the Communication is
recorded as failed with the reason `service-suspended` and the consumer's marker commits with it, so
a redelivery does nothing. Only a message that asks for a figure (C1, C2, C8, C9) is held back: an
echo or a refusal answers a reporter and still goes. The unit of work is a stub and the sender is
the recording fake: nothing real is sent.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, time
from typing import Any

import pytest

from diucs.adapters.inbound.workers.message_senders import (
    MESSAGES_TOPIC,
    SEND_MESSAGE_EVENT,
    SERVICE_SUSPENDED,
    EmailMessageSender,
    SmsMessageSender,
)
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.recording_senders import RecordingEmailSender, RecordingSmsSender
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.messaging import Communication, EmailSender, SmsSender
from diucs.application.tenancy import ScopeId
from diucs.domain.codes import Cadence, Channel, Measure, PractitionerRoleCode, ServiceCategory
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.people import PractitionerRole
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant_records import TenantChannel
from tests.support.tenancy import as_tenant

SEALER = AesGcmContentSealer(
    FixedSecretStore({"link-token": b"link-token-test-secret-0123456789abcdef"})
)
TENANT = "tenant-a"
ROLE = "role-1"
SERVICE = "svc-ucr-west"
OUTBOX_ID = "outbox-1"
NOW = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
PHONE = "+447700900111"
PROFILE = ServiceProfile(
    id=SERVICE,
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals in the next 2 hrs",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)
POST = PractitionerRole(
    id=ROLE,
    practitioner_id="p-own",
    service_id=SERVICE,
    code=PractitionerRoleCode.DUTY_MANAGER,
    active=True,
    channel=Channel.TEXT,
    period_start=datetime(2026, 10, 1, tzinfo=UTC),
)
SUSPENDED = ServiceFlag(
    service_id=SERVICE,
    code=SERVICE_FLAG_SUSPENDED,
    active=True,
    reason="Sample reason",
    actor_id="lead-1",
    at=NOW,
)


class _People:
    async def get_role(self, role_id: str) -> PractitionerRole | None:
        return POST if role_id == ROLE else None


class _Contacts:
    async def get_phone(self, role_id: str) -> str | None:
        return PHONE

    async def get_email(self, role_id: str) -> str | None:
        return "post.holder@example.test"


class _Services:
    def __init__(self, profile: ServiceProfile | None) -> None:
        self._profile = profile

    async def get(self, service_id: str) -> ServiceProfile | None:
        return self._profile


class _Flags:
    def __init__(self, flags: list[ServiceFlag]) -> None:
        self._flags = flags

    async def service_flags(self, service_id: str) -> list[ServiceFlag]:
        return self._flags


class _Communications:
    def __init__(self, message_id: str, about: str | None) -> None:
        self._message_id = message_id
        self._about = about
        self.outcomes: list[tuple[str, str, str | None, str | None]] = []

    async def get(self, communication_id: str) -> Communication:
        return Communication(
            id=communication_id,
            message_id=self._message_id,
            channel=Channel.TEXT,
            recipient_role_id=ROLE,
            about_id=self._about,
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


class _Unit:
    unit_scope = ScopeId.tenant(TENANT)

    def __init__(
        self,
        *,
        message_id: str = "C1",
        about: str | None = SERVICE,
        flags: list[ServiceFlag] | None = None,
        profile: ServiceProfile | None = PROFILE,
    ) -> None:
        self.people = _People()
        self.contacts = _Contacts()
        self.services = _Services(profile)
        self.flags = _Flags(flags or [])
        self.communications = _Communications(message_id, about)


class _Resolver:
    def __init__(self) -> None:
        self.sms = RecordingSmsSender()
        self.email = RecordingEmailSender()

    async def sms_for(self) -> SmsSender:
        return self.sms

    async def email_for(self, channel: TenantChannel | None) -> EmailSender:
        return self.email


def _message(message_id: str) -> BusMessage:
    content = json.dumps({"text": "How many referrals?", "subject": None, "html": None})
    return BusMessage(
        id=OUTBOX_ID,
        topic=MESSAGES_TOPIC,
        event_type=SEND_MESSAGE_EVENT,
        payload={
            "communication_id": "comm-1",
            "message_id": message_id,
            "channel": "text",
            "recipient_role_id": ROLE,
            "sealed_content": SEALER.seal(
                content, message_id=OUTBOX_ID, tenant_id=TENANT, recipient_role_id=ROLE
            ),
        },
        tenant_id=TENANT,
    )


async def _send(unit: _Unit, message_id: str = "C1") -> _Resolver:
    resolver = _Resolver()
    sender = SmsMessageSender(resolver, SEALER, FixedClock(NOW))
    with as_tenant(TENANT):
        await sender(_message(message_id), unit)  # type: ignore[arg-type]
    return resolver


@pytest.mark.parametrize("message_id", ["C1", "C2", "C8", "C9"])
async def test_a_prompt_for_a_suspended_service_is_not_sent_and_is_recorded_as_failed(
    message_id: str,
) -> None:
    unit = _Unit(message_id=message_id, flags=[SUSPENDED])

    resolver = await _send(unit, message_id)

    assert resolver.sms.sent == []
    assert unit.communications.outcomes == [("comm-1", "failed", None, SERVICE_SUSPENDED)]


async def test_a_prompt_for_a_service_that_is_no_longer_active_is_not_sent() -> None:
    unit = _Unit(profile=replace(PROFILE, active=False))

    resolver = await _send(unit)

    assert resolver.sms.sent == []
    assert unit.communications.outcomes == [("comm-1", "failed", None, SERVICE_SUSPENDED)]


async def test_a_prompt_for_a_service_that_is_gone_is_not_sent() -> None:
    unit = _Unit(profile=None)

    resolver = await _send(unit)

    assert resolver.sms.sent == []
    assert unit.communications.outcomes == [("comm-1", "failed", None, SERVICE_SUSPENDED)]


async def test_a_prompt_for_a_service_in_good_standing_is_sent() -> None:
    unit = _Unit()

    resolver = await _send(unit)

    assert len(resolver.sms.sent) == 1
    assert unit.communications.outcomes == [("comm-1", "sent", "sms-1", None)]


@pytest.mark.parametrize("message_id", ["C3", "C4", "C5", "C6", "C7", "C10", "C11", "C12"])
async def test_an_echo_or_a_refusal_to_a_reporter_is_sent_even_for_a_suspended_service(
    message_id: str,
) -> None:
    unit = _Unit(message_id=message_id, flags=[SUSPENDED])

    resolver = await _send(unit, message_id)

    assert len(resolver.sms.sent) == 1


async def test_a_prompt_with_no_service_is_sent_as_before() -> None:
    unit = _Unit(about=None, flags=[SUSPENDED])

    resolver = await _send(unit)

    assert len(resolver.sms.sent) == 1


async def test_a_lifted_flag_is_not_a_suspension() -> None:
    unit = _Unit(flags=[])

    resolver = await _send(unit)

    assert len(resolver.sms.sent) == 1


async def test_the_email_sender_holds_a_prompt_for_a_suspended_service_too() -> None:
    unit = _Unit(flags=[SUSPENDED])
    resolver = _Resolver()
    sender = EmailMessageSender(resolver, SEALER, FixedClock(NOW))
    message = _message("C1")
    payload: dict[str, Any] = dict(message.payload)
    payload["channel"] = "email"
    content = json.dumps({"text": "x", "subject": "Subject", "html": None})
    payload["sealed_content"] = SEALER.seal(
        content, message_id=OUTBOX_ID, tenant_id=TENANT, recipient_role_id=ROLE
    )
    email = BusMessage(
        id=OUTBOX_ID,
        topic=MESSAGES_TOPIC,
        event_type=SEND_MESSAGE_EVENT,
        payload=payload,
        tenant_id=TENANT,
    )

    with as_tenant(TENANT):
        await sender(email, unit)  # type: ignore[arg-type]

    assert resolver.email.sent == []
    assert unit.communications.outcomes == [("comm-1", "failed", None, SERVICE_SUSPENDED)]
