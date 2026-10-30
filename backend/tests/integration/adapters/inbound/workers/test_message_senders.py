"""The outbound message senders on real Neo4j (I10).

A queued Communication and its protected contact are seeded with the real repositories and read
back in a fresh unit of work. The provider is a recording fake (RecordingSmsSender and
RecordingEmailSender, or a sender that is unreachable). The tenant comes from the message, bound
before the unit of work opens, as in production. Run only in the verification stage (build wave:
Neo4j is not started by builders).
"""

import json
from datetime import UTC, datetime

import pytest
from neo4j import AsyncDriver

from diucs.adapters.inbound.workers.consumer import IdempotentConsumer, Outcome
from diucs.adapters.inbound.workers.message_senders import (
    BAD_CHANNEL,
    CONSUMER_EMAIL,
    CONSUMER_SMS,
    MESSAGES_TOPIC,
    NO_CHANNEL,
    NO_CONTACT,
    REFUSED,
    SEND_FAILED,
    SEND_MESSAGE_EVENT,
    EmailMessageSender,
    SmsMessageSender,
    sender_runners,
)
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.tenant_binding import TenantBoundConsumer
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.recording_senders import (
    FixedSenderResolver,
    RecordingEmailSender,
    RecordingSmsSender,
)
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.messaging import (
    Communication,
    SendFailedError,
    SendReceipt,
    TransientSendError,
)
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Channel
from tests.support.neo4j import node_props

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET = b"link-token-test-secret-0123456789abcdef"
CLOCK = FixedClock(datetime(2026, 10, 23, 13, 0, tzinfo=UTC))
SEALER = AesGcmContentSealer(FixedSecretStore({"link-token": SECRET}))
SENT = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
ROLE = "role-1"
PHONE = "07700 900123"
EMAIL = "duty.manager@example.test"
TEXT = "How many referrals can you take in the next 2 hrs? Reply with a number. UCR West"
SUBJECT = "DIUCS Dorset: capacity question for UCR West"
HTML = "<p>How many referrals can you take in the next 2 hrs?</p>"


class _Unreachable:
    """A provider that cannot be reached: the send must be retried, not recorded."""

    async def send(self, to: str, text: str, message_id: str) -> SendReceipt:
        raise TransientSendError("the provider could not be reached")


class _Refuses:
    """A provider that answers in a way no retry will fix."""

    async def send(self, to: str, text: str, message_id: str) -> SendReceipt:
        raise SendFailedError("the provider answered 400 with code 21211")


def _sealed(text: str, subject: str | None, html: str | None, outbox: str, tenant: str) -> str:
    content = json.dumps(
        {"text": text, "subject": subject, "html": html},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return SEALER.seal(content, message_id=outbox, tenant_id=tenant, recipient_role_id=ROLE)


def _message(
    tenant: str,
    *,
    outbox: str = "outbox-1",
    communication: str = "comm-1",
    channel: str = "text",
    subject: str | None = None,
    html: str | None = None,
) -> BusMessage:
    return BusMessage(
        id=outbox,
        topic=MESSAGES_TOPIC,
        event_type=SEND_MESSAGE_EVENT,
        payload={
            "communication_id": communication,
            "message_id": "C1",
            "channel": channel,
            "recipient_role_id": ROLE,
            "sealed_content": _sealed(TEXT, subject, html, outbox, tenant),
        },
        tenant_id=tenant,
    )


async def _seed(
    factory: UnitOfWorkFactory,
    *,
    communication: str = "comm-1",
    provider_id: str | None = None,
    status: str = "queued",
    phone: str | None = PHONE,
    email: str | None = EMAIL,
) -> None:
    async with factory() as uow:
        if phone is not None:
            await uow.contacts.put_phone(ROLE, phone)
        if email is not None:
            await uow.contacts.put_email(ROLE, email)
        await uow.communications.add(
            Communication(
                id=communication,
                message_id="C1",
                channel=Channel.TEXT,
                recipient_role_id=ROLE,
                about_id=None,
                payload_text=TEXT,
                sent_at=SENT,
                delivery_status=status,
                provider_message_id=provider_id,
            )
        )
        await uow.commit()


async def _stored(factory: UnitOfWorkFactory, communication: str = "comm-1") -> Communication:
    async with factory() as uow:
        found = await uow.communications.get(communication)
    assert found is not None
    return found


def _text_consumer(
    factory: UnitOfWorkFactory, tenants: StaticTenants, resolver: FixedSenderResolver
) -> TenantBoundConsumer:
    return TenantBoundConsumer(
        IdempotentConsumer(CONSUMER_SMS, SmsMessageSender(resolver, SEALER, CLOCK), factory),
        tenants,
    )


def _email_consumer(
    factory: UnitOfWorkFactory, tenants: StaticTenants, resolver: FixedSenderResolver
) -> TenantBoundConsumer:
    return TenantBoundConsumer(
        IdempotentConsumer(CONSUMER_EMAIL, EmailMessageSender(resolver, SEALER, CLOCK), factory),
        tenants,
    )


@pytest.fixture
def tenants(tenant_id: str, other_tenant_id: str) -> StaticTenants:
    return StaticTenants([tenant_id, other_tenant_id])


# --- the seven acceptance cases ----------------------------------------------------------------


async def test_a_text_payload_is_sent_to_the_stored_number_and_recorded_as_sent(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(uow_factory_a)
    sms = RecordingSmsSender()
    consumer = _text_consumer(uow_factory_a, tenants, FixedSenderResolver(sms={tenant_id: sms}))

    outcome = await consumer.handle(_message(tenant_id))

    assert outcome == Outcome("completed")
    assert [(sent.to, sent.text) for sent in sms.sent] == [(PHONE, TEXT)]
    stored = await _stored(uow_factory_a)
    assert stored.delivery_status == "sent"
    assert stored.provider_message_id == "sms-1"
    assert (await node_props(neo4j_driver, "Communication", id="comm-1"))[
        "deliveryStatus"
    ] == "sent"


async def test_an_email_payload_is_sent_with_subject_text_and_html(
    uow_factory_a: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str
) -> None:
    await _seed(uow_factory_a)
    email = RecordingEmailSender()
    consumer = _email_consumer(
        uow_factory_a, tenants, FixedSenderResolver(email={tenant_id: email})
    )

    outcome = await consumer.handle(
        _message(tenant_id, channel="email", subject=SUBJECT, html=HTML)
    )

    assert outcome == Outcome("completed")
    assert [(s.to, s.subject, s.text, s.html) for s in email.sent] == [(EMAIL, SUBJECT, TEXT, HTML)]
    assert (await _stored(uow_factory_a)).delivery_status == "sent"


async def test_a_role_with_no_phone_is_recorded_as_failed_with_no_contact_and_completes(
    uow_factory_a: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(uow_factory_a, phone=None)
    sms = RecordingSmsSender()
    consumer = _text_consumer(uow_factory_a, tenants, FixedSenderResolver(sms={tenant_id: sms}))

    outcome = await consumer.handle(_message(tenant_id))

    assert outcome == Outcome("completed")
    assert sms.sent == []
    stored = await _stored(uow_factory_a)
    assert stored.delivery_status == "failed"
    assert (await node_props(neo4j_driver, "Communication", id="comm-1"))["errorCode"] == NO_CONTACT


async def test_a_refused_send_is_recorded_as_failed_and_completes(
    uow_factory_a: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str
) -> None:
    await _seed(uow_factory_a)
    sms = RecordingSmsSender()
    sms.fail_next()
    consumer = _text_consumer(uow_factory_a, tenants, FixedSenderResolver(sms={tenant_id: sms}))

    outcome = await consumer.handle(_message(tenant_id))

    assert outcome == Outcome("completed")
    assert sms.sent == []
    stored = await _stored(uow_factory_a)
    assert stored.delivery_status == "failed"
    assert stored.provider_message_id is None


async def test_a_transient_send_error_is_retried_and_leaves_the_communication_unchanged(
    uow_factory_a: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(uow_factory_a)
    before = await node_props(neo4j_driver, "Communication", id="comm-1")
    consumer = _text_consumer(
        uow_factory_a,
        tenants,
        FixedSenderResolver(sms={tenant_id: _Unreachable()}),  # type: ignore[dict-item]
    )

    outcome = await consumer.handle(_message(tenant_id))

    assert outcome == Outcome("retry", "TransientSendError")
    assert await node_props(neo4j_driver, "Communication", id="comm-1") == before


async def test_a_communication_that_already_has_a_provider_id_is_never_sent_again(
    uow_factory_a: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str
) -> None:
    await _seed(uow_factory_a, provider_id="SM-7", status="sent")
    sms = RecordingSmsSender()
    consumer = _text_consumer(uow_factory_a, tenants, FixedSenderResolver(sms={tenant_id: sms}))

    outcome = await consumer.handle(_message(tenant_id))

    assert outcome == Outcome("completed")
    assert sms.sent == []
    assert (await _stored(uow_factory_a)).provider_message_id == "SM-7"


async def test_a_push_payload_given_to_the_text_sender_is_dead_lettered_and_writes_nothing(
    uow_factory_a: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(uow_factory_a)
    before = await node_props(neo4j_driver, "Communication", id="comm-1")
    sms = RecordingSmsSender()
    consumer = _text_consumer(uow_factory_a, tenants, FixedSenderResolver(sms={tenant_id: sms}))

    outcome = await consumer.handle(_message(tenant_id, channel="push"))

    assert outcome == Outcome("dead-letter", BAD_CHANNEL)
    assert sms.sent == []
    assert await node_props(neo4j_driver, "Communication", id="comm-1") == before


# --- tenancy: a message reaches only its own tenant's channel, and nothing else -----------------


async def test_a_message_for_tenant_a_is_sent_through_a_only_and_never_b(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _seed(uow_factory_a)
    sms_a = RecordingSmsSender()
    sms_b = RecordingSmsSender()
    resolver = FixedSenderResolver(sms={tenant_id: sms_a, other_tenant_id: sms_b})
    consumer = _text_consumer(uow_factory_a, tenants, resolver)

    await consumer.handle(_message(tenant_id))

    assert len(sms_a.sent) == 1
    assert sms_b.sent == []


async def test_a_message_for_a_tenant_with_no_channel_sends_nothing_and_records_no_channel(
    uow_factory_a: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    other_tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(uow_factory_a)
    sms_b = RecordingSmsSender()
    consumer = _text_consumer(
        uow_factory_a, tenants, FixedSenderResolver(sms={other_tenant_id: sms_b})
    )

    outcome = await consumer.handle(_message(tenant_id))

    assert outcome == Outcome("completed")
    assert sms_b.sent == []
    assert (await node_props(neo4j_driver, "Communication", id="comm-1"))["errorCode"] == NO_CHANNEL


async def test_a_phone_stored_only_for_tenant_b_is_not_found_from_tenant_a(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _seed(uow_factory_a, phone=None, email=None)
    async with uow_factory_b() as uow:
        await uow.contacts.put_phone(ROLE, PHONE)
        await uow.commit()
    sms_a = RecordingSmsSender()
    sms_b = RecordingSmsSender()
    resolver = FixedSenderResolver(sms={tenant_id: sms_a, other_tenant_id: sms_b})
    consumer = _text_consumer(uow_factory_a, tenants, resolver)

    await consumer.handle(_message(tenant_id))

    assert sms_a.sent == []
    assert sms_b.sent == []
    assert (await _stored(uow_factory_a)).delivery_status == "failed"


async def test_a_communication_of_tenant_b_is_not_found_from_tenant_a(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _seed(uow_factory_b)
    sms_a = RecordingSmsSender()
    sms_b = RecordingSmsSender()
    resolver = FixedSenderResolver(sms={tenant_id: sms_a, other_tenant_id: sms_b})
    consumer = _text_consumer(uow_factory_a, tenants, resolver)

    outcome = await consumer.handle(_message(tenant_id))

    assert outcome == Outcome("dead-letter", "the communication to send is not stored")
    assert sms_a.sent == []
    assert sms_b.sent == []
    assert (await _stored(uow_factory_b)).delivery_status == "queued"


async def test_a_message_for_an_unknown_tenant_is_dead_lettered_before_any_unit_opens(
    uow_factory_a: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str
) -> None:
    await _seed(uow_factory_a)
    sms = RecordingSmsSender()
    consumer = _text_consumer(
        uow_factory_a, tenants, FixedSenderResolver(sms={"tenant-unknown": sms})
    )

    outcome = await consumer.handle(_message("tenant-unknown"))

    assert outcome.kind == "dead-letter"
    assert sms.sent == []


async def test_a_provider_answer_that_is_neither_accepted_nor_refused_is_failed_and_not_retried(
    uow_factory_a: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(uow_factory_a)
    consumer = _text_consumer(
        uow_factory_a, tenants, FixedSenderResolver(sms={tenant_id: _Refuses()})
    )

    outcome = await consumer.handle(_message(tenant_id))

    assert outcome == Outcome("completed")
    assert (await _stored(uow_factory_a)).delivery_status == "failed"
    props = await node_props(neo4j_driver, "Communication", id="comm-1")
    assert props["errorCode"] == SEND_FAILED


async def test_a_provider_refusal_recorded_as_refused_keeps_no_provider_id(
    uow_factory_a: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(uow_factory_a)
    sms = RecordingSmsSender()
    sms.fail_next()
    consumer = _text_consumer(uow_factory_a, tenants, FixedSenderResolver(sms={tenant_id: sms}))

    await consumer.handle(_message(tenant_id))

    props = await node_props(neo4j_driver, "Communication", id="comm-1")
    assert props["errorCode"] == REFUSED
    assert "providerMessageId" not in props


async def test_the_two_sender_runners_are_built_for_the_two_sender_subscriptions(
    tenants: StaticTenants, uow_factory_a: UnitOfWorkFactory
) -> None:
    runners = sender_runners(
        object(),  # type: ignore[arg-type]
        uow_factory_a,
        tenants,
        FixedSenderResolver(),
        SEALER,
        CLOCK,
    )

    assert len(runners) == 2
