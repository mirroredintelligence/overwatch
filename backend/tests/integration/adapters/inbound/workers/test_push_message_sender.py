"""The push message sender against real Neo4j (I14): a gone subscription is deleted and the
Communication is settled; a send reaches the recording fake only (no real push).

WRITTEN, NOT RUN in the build wave (no Neo4j per build-wave rules); verification runs them.
"""

import json
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.inbound.workers.message_senders import (
    MESSAGES_TOPIC,
    SEND_MESSAGE_EVENT,
    PushMessageSender,
)
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.recording_senders import RecordingPushSender
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.messaging import Communication, PushSubscription
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Channel
from tests.support.ladder_rig import reporter, seed_people, virtual_ward
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

SECRET = b"link-token-test-secret-0123456789abcdef"
SEALER = AesGcmContentSealer(FixedSecretStore({"link-token": SECRET}))
NOW = datetime(2026, 10, 25, 13, 12, tzinfo=UTC)
APP_URL = "https://diucs.example/reporter"
ROLE = "role-1"
OUTBOX_ID = "outbox-push-1"
COMM_ID = "comm-push-1"


def _subscription(device: str) -> PushSubscription:
    return PushSubscription(
        device_id=device,
        practitioner_id="prac-1",
        subscription={
            "endpoint": f"https://push.example/{device}",
            "keys": {"auth": "sample-auth", "p256dh": "sample-p256dh"},
        },
        saved_at=NOW,
    )


def _message(tenant: str) -> BusMessage:
    content = json.dumps(
        {"text": "Confirm or update", "subject": "UCR West", "html": None},
        sort_keys=True,
        separators=(",", ":"),
    )
    sealed = SEALER.seal(content, message_id=OUTBOX_ID, tenant_id=tenant, recipient_role_id=ROLE)
    payload = {
        "communication_id": COMM_ID,
        "message_id": "C1",
        "channel": "push",
        "recipient_role_id": ROLE,
        "sealed_content": sealed,
    }
    return BusMessage(
        id=OUTBOX_ID,
        topic=MESSAGES_TOPIC,
        event_type=SEND_MESSAGE_EVENT,
        payload=payload,
        tenant_id=tenant,
    )


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(
    clean_graph: None,
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
) -> None:
    await ensure_audit_heads(neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        await uow.services.save(virtual_ward())
        await uow.commit()
    await seed_people(uow_factory, reporter(1, None))
    async with uow_factory() as uow:
        await uow.communications.add(
            Communication(
                id=COMM_ID,
                message_id=OUTBOX_ID,
                channel=Channel.PUSH,
                recipient_role_id=ROLE,
                about_id=None,
                payload_text="Confirm or update",
                sent_at=NOW,
                delivery_status="queued",
            )
        )
        await uow.commit()
    async with uow_factory() as uow:
        await uow.push_subscriptions.save(_subscription("dev-1"))
        await uow.push_subscriptions.save(_subscription("dev-2"))
        await uow.commit()


async def _run(uow_factory: UnitOfWorkFactory, tenant_id: str, sender: RecordingPushSender) -> None:
    handler = PushMessageSender(sender, SEALER, APP_URL, FixedClock(NOW))
    async with uow_factory() as uow:
        await handler(_message(tenant_id), uow)
        await uow.commit()


async def test_a_send_reaches_each_device_and_records_the_communication_as_sent(
    uow_factory: UnitOfWorkFactory, tenant_id: str, seeded: None
) -> None:
    sender = RecordingPushSender()
    await _run(uow_factory, tenant_id, sender)

    assert len(sender.sent) == 2
    async with uow_factory() as uow:
        communication = await uow.communications.get(COMM_ID)
    assert communication is not None and communication.delivery_status == "sent"


async def test_a_gone_subscription_is_deleted_and_the_others_still_receive(
    uow_factory: UnitOfWorkFactory, tenant_id: str, seeded: None
) -> None:
    sender = RecordingPushSender()
    sender.gone_next()
    await _run(uow_factory, tenant_id, sender)

    async with uow_factory() as uow:
        remaining = await uow.push_subscriptions.for_practitioner("prac-1")
        communication = await uow.communications.get(COMM_ID)
    assert len(remaining) == 1
    assert communication is not None and communication.delivery_status == "sent"


async def test_when_every_subscription_is_gone_the_communication_is_failed(
    uow_factory: UnitOfWorkFactory, tenant_id: str, seeded: None
) -> None:
    sender = RecordingPushSender()
    sender.gone_next()
    sender.gone_next()
    await _run(uow_factory, tenant_id, sender)

    async with uow_factory() as uow:
        remaining = await uow.push_subscriptions.for_practitioner("prac-1")
        communication = await uow.communications.get(COMM_ID)
    assert remaining == []
    assert communication is not None and communication.delivery_status == "failed"
