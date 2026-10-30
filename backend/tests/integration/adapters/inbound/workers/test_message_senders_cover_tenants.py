"""Two-tenant test of the text sender during a cover (F6B, W7C-K2, W7B C).

The tenants hold a post of the same ids (service, practitioner and role), each on its own original
number, and each lead hands the post to a cover with `ChangeReporterNumber` (the real use case, so
the cover number is kept under `cover-<role id>` as the sender reads it). A queued text for the post
then goes to that tenant's cover number, through that tenant's recording sender, and to no other
number: not the original holder's, and not the other tenant's. When the cover ends the text goes
back to the original number. No message is really sent: the senders are recording fakes. Sample
numbers only (the `07700 900xxx` range). Runs on the harness database.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.inbound.workers.consumer import IdempotentConsumer, Outcome
from diucs.adapters.inbound.workers.message_senders import (
    CONSUMER_SMS,
    MESSAGES_TOPIC,
    NO_CONTACT,
    SEND_MESSAGE_EVENT,
    SmsMessageSender,
)
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.tenant_binding import TenantBoundConsumer
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.recording_senders import FixedSenderResolver, RecordingSmsSender
from diucs.application.actor import Actor
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.change_reporter_number import (
    ChangeReporterNumber,
    ChangeReporterNumberCommand,
    CoverDuration,
)
from diucs.domain.codes import Channel, Role
from tests.support.ladder_rig import reporter, seed_people, virtual_ward
from tests.support.neo4j import node_props
from tests.support.tenancy import as_tenant
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

SERVICE = "vw-frailty"
ROLE = "role-1"
OWN_A = "+447700900111"
OWN_B = "+447700900333"
COVER_A_NATIONAL = "07700 900222"
COVER_B_NATIONAL = "07700 900444"
COVER_A = "+447700900222"
COVER_B = "+447700900444"
HASHER = HmacPhoneHasher(
    FixedSecretStore({PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab"})
)
SEALER = AesGcmContentSealer(
    FixedSecretStore({"link-token": b"link-token-test-secret-0123456789abcdef"})
)
MONDAY_10 = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
TUESDAY_08 = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)  # the cover set on Monday ended at 23:59
TEXT = "How many referrals can you take in the next 2 hrs? Reply with a number. UCR West"


def _lead(tenant: str) -> Actor:
    return Actor(
        role=Role.LEAD,
        practitioner_id="lead-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


async def _cover(
    factory: UnitOfWorkFactory, driver: AsyncDriver, tenant: str, number: str, key: str
) -> None:
    use_case = ChangeReporterNumber(
        factory, FixedClock(MONDAY_10), SequentialIds("cr"), DriverIdempotencyStore(driver), HASHER
    )
    with as_tenant(tenant):
        await use_case.execute(
            ChangeReporterNumberCommand(
                idempotency_key=key,
                actor=_lead(tenant),
                service_id=SERVICE,
                new_mobile=number,
                duration=CoverDuration.TODAY,
            )
        )


async def _seed_post(
    factory: UnitOfWorkFactory, number: str, hash_seed: str, *, text: str = TEXT
) -> None:
    async with factory() as uow:
        await uow.services.save(virtual_ward(SERVICE))
        await uow.commit()
    await seed_people(factory, reporter(1, HASHER.hash(hash_seed), service_id=SERVICE))
    async with factory() as uow:
        await uow.contacts.put_phone(ROLE, number)
        await uow.communications.add(
            Communication(
                id="comm-1",
                message_id="C1",
                channel=Channel.TEXT,
                recipient_role_id=ROLE,
                about_id=SERVICE,
                payload_text=text,
                sent_at=MONDAY_10,
                delivery_status="queued",
            )
        )
        await uow.commit()


def _message(tenant: str, communication: str = "comm-1") -> BusMessage:
    outbox = f"outbox-{communication}"
    content = json.dumps(
        {"text": TEXT, "subject": None, "html": None}, sort_keys=True, separators=(",", ":")
    )
    return BusMessage(
        id=outbox,
        topic=MESSAGES_TOPIC,
        event_type=SEND_MESSAGE_EVENT,
        payload={
            "communication_id": communication,
            "message_id": "C1",
            "channel": "text",
            "recipient_role_id": ROLE,
            "sealed_content": SEALER.seal(
                content, message_id=outbox, tenant_id=tenant, recipient_role_id=ROLE
            ),
        },
        tenant_id=tenant,
    )


@pytest_asyncio.fixture(loop_scope="session")
async def world(
    neo4j_driver: AsyncDriver,
    clean_graph: None,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    """Both tenants hold the post and have handed it to a cover for Monday."""
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    await _seed_post(uow_factory_a, OWN_A, "07700 900111")
    await _seed_post(uow_factory_b, OWN_B, "07700 900333")
    await _cover(uow_factory_a, neo4j_driver, tenant_id, COVER_A_NATIONAL, "cover-a")
    await _cover(uow_factory_b, neo4j_driver, other_tenant_id, COVER_B_NATIONAL, "cover-b")


def _consumer(
    factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    resolver: FixedSenderResolver,
    clock: FixedClock,
) -> TenantBoundConsumer:
    return TenantBoundConsumer(
        IdempotentConsumer(CONSUMER_SMS, SmsMessageSender(resolver, SEALER, clock), factory),
        tenants,
    )


async def test_each_tenants_text_goes_to_its_own_cover_and_to_no_other_number(
    world: None,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    sms_a, sms_b = RecordingSmsSender(), RecordingSmsSender()
    resolver = FixedSenderResolver(sms={tenant_id: sms_a, other_tenant_id: sms_b})
    tenants = StaticTenants([tenant_id, other_tenant_id])
    clock = FixedClock(MONDAY_10)

    outcome_a = await _consumer(uow_factory_a, tenants, resolver, clock).handle(_message(tenant_id))
    outcome_b = await _consumer(uow_factory_b, tenants, resolver, clock).handle(
        _message(other_tenant_id)
    )

    assert (outcome_a, outcome_b) == (Outcome("completed"), Outcome("completed"))
    assert [sent.to for sent in sms_a.sent] == [COVER_A]
    assert [sent.to for sent in sms_b.sent] == [COVER_B]
    for sent in (*sms_a.sent, *sms_b.sent):
        assert sent.to not in (OWN_A, OWN_B)


async def test_after_the_cover_ends_the_text_goes_back_to_the_posts_own_number(
    world: None,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    sms_a, sms_b = RecordingSmsSender(), RecordingSmsSender()
    resolver = FixedSenderResolver(sms={tenant_id: sms_a, other_tenant_id: sms_b})
    tenants = StaticTenants([tenant_id, other_tenant_id])
    clock = FixedClock(TUESDAY_08)

    await _consumer(uow_factory_a, tenants, resolver, clock).handle(_message(tenant_id))
    await _consumer(uow_factory_b, tenants, resolver, clock).handle(_message(other_tenant_id))

    assert [sent.to for sent in sms_a.sent] == [OWN_A]
    assert [sent.to for sent in sms_b.sent] == [OWN_B]


async def test_a_cover_with_no_number_kept_sends_nothing_and_never_reads_the_other_tenants(
    neo4j_driver: AsyncDriver,
    clean_graph: None,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    # Tenant A's post is covered with a number kept. Tenant B's is covered with none kept (as a
    # service move leaves it, U37). The key (`cover-role-1`) is the same in both tenants: B's text
    # has no one to go to, and A's cover number is not used for it. B's original holder, who has
    # handed the post on, is not texted either.
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    await _seed_post(uow_factory_a, OWN_A, "07700 900111")
    await _seed_post(uow_factory_b, OWN_B, "07700 900333")
    await _cover(uow_factory_a, neo4j_driver, tenant_id, COVER_A_NATIONAL, "cover-a")
    cover, _ = reporter(2, HASHER.hash("07700 900444"), service_id=SERVICE)
    async with uow_factory_b() as uow:
        await uow.people.save_practitioner(cover)
        role = await uow.people.get_role(ROLE)
        assert role is not None
        await uow.people.save_role(
            replace(
                role,
                covered_by_practitioner_id=cover.id,
                covered_until=datetime(2026, 11, 2, 23, 59, tzinfo=UTC),
            )
        )
        await uow.commit()
    sms_a, sms_b = RecordingSmsSender(), RecordingSmsSender()
    resolver = FixedSenderResolver(sms={tenant_id: sms_a, other_tenant_id: sms_b})
    tenants = StaticTenants([tenant_id, other_tenant_id])
    clock = FixedClock(MONDAY_10)

    await _consumer(uow_factory_a, tenants, resolver, clock).handle(_message(tenant_id))
    await _consumer(uow_factory_b, tenants, resolver, clock).handle(_message(other_tenant_id))

    assert [sent.to for sent in sms_a.sent] == [COVER_A]
    assert sms_b.sent == []
    with as_tenant(other_tenant_id):
        props = await node_props(neo4j_driver, "Communication", id="comm-1")
    assert props["errorCode"] == NO_CONTACT
