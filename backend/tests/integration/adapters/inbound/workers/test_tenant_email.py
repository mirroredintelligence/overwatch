"""Email from each tenant's own identity, on real Neo4j (TEN-042, DEC-131 item 1).

Tenant A and tenant B each hold an active email channel record in their own scope (a sender
address and the reference of their own SMTP secret). The production resolver builds the sender from
the record the sender consumer read in its unit of work, so a message of A leaves from A's address
with A's secret and a message of B from B's, through the one platform relay. A tenant with no
channel sends nothing and records the message as failed. The SMTP call is a recording fake: no mail
leaves the machine. Written in the build wave; run in the verification stage. Synthetic values.
"""

import json
from typing import Any

import httpx
import pytest

from diucs.adapters.inbound.workers.message_senders import (
    MESSAGES_TOPIC,
    NO_CHANNEL,
    SEND_MESSAGE_EVENT,
)
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.outbound.email_smtp.smtp_email import SmtpRelay
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.tenants import secret_ref
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.bootstrap.tenant_senders import TenantSenderResolver
from diucs.domain.codes import Channel
from diucs.domain.model.tenant import NumberStatus
from diucs.domain.model.tenant_records import ChannelKind, ChannelProvider, TenantChannel
from tests.integration.adapters.inbound.workers.test_message_senders import (
    EMAIL,
    HTML,
    SEALER,
    SENT,
    SUBJECT,
    TEXT,
    _email_consumer,
    _stored,
)
from tests.support.neo4j import node_props

pytestmark = pytest.mark.asyncio(loop_scope="session")

RELAY = SmtpRelay(host="relay.example.test", port=2525, starttls=True)


# Until TEN-032 two tenants cannot hold one protected-contact key, one communication id or one
# concept (a catalogue message id, a channel) on the shared test schema (lesson L169), so each
# tenant's role, communication, outbox id, catalogue message and stored channel differ. The channel
# stored on a Communication does not decide how it is sent: the payload's channel does.
def _ids(tenant_label: str) -> dict[str, str]:
    return {
        "role": f"role-{tenant_label}",
        "communication": f"comm-{tenant_label}",
        "outbox": f"outbox-{tenant_label}",
        "message": {"a": "C1", "b": "C2"}[tenant_label],
        "stored_channel": {"a": "text", "b": "push"}[tenant_label],
    }


async def _seed_for(factory: UnitOfWorkFactory, tenant_label: str) -> None:
    ids = _ids(tenant_label)
    async with factory() as uow:
        await uow.contacts.put_email(ids["role"], EMAIL)
        await uow.communications.add(
            Communication(
                id=ids["communication"],
                message_id=ids["message"],
                channel=Channel(ids["stored_channel"]),
                recipient_role_id=ids["role"],
                about_id=None,
                payload_text=TEXT,
                sent_at=SENT,
                delivery_status="queued",
            )
        )
        await uow.commit()


def _email_message(tenant: str, tenant_label: str) -> BusMessage:
    ids = _ids(tenant_label)
    content = json.dumps(
        {"text": TEXT, "subject": SUBJECT, "html": HTML},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return BusMessage(
        id=ids["outbox"],
        topic=MESSAGES_TOPIC,
        event_type=SEND_MESSAGE_EVENT,
        payload={
            "communication_id": ids["communication"],
            "message_id": ids["message"],
            "channel": "email",
            "recipient_role_id": ids["role"],
            "sealed_content": SEALER.seal(
                content,
                message_id=ids["outbox"],
                tenant_id=tenant,
                recipient_role_id=ids["role"],
            ),
        },
        tenant_id=tenant,
    )


class _Captured:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, message: Any, **kwargs: Any) -> None:
        self.calls.append({"from": message["From"], "to": message["To"], **kwargs})


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> _Captured:
    sink = _Captured()
    monkeypatch.setattr("aiosmtplib.send", sink)
    return sink


def _channel(
    tenant: str, address: str, status: NumberStatus = NumberStatus.ACTIVE
) -> TenantChannel:
    return TenantChannel(
        id="email-1",
        kind=ChannelKind.EMAIL,
        provider=ChannelProvider.SMTP,
        status=status,
        sender_label="Capacity email",
        secret_ref=secret_ref("smtp", tenant, "relay-login"),
        from_address=address,
        from_display_name=f"Capacity {address.split('@')[1].split('.')[0]}",
    )


async def _put(factory: UnitOfWorkFactory, channel: TenantChannel) -> None:
    async with factory() as uow:
        await uow.tenant_config.put_channel(channel)
        await uow.commit()


def _resolver(tenant: str, other: str) -> TenantSenderResolver:
    secrets = FixedSecretStore(
        {
            secret_ref("smtp", tenant, "relay-login"): b"password-of-a",
            secret_ref("smtp", other, "relay-login"): b"password-of-b",
        }
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    return TenantSenderResolver(
        None,  # type: ignore[arg-type]  # the directory is not asked for email
        secrets,
        http,
        "https://diucs.example/webhooks/sms/twilio/status",
        smtp_relay=RELAY,
    )


async def test_each_tenants_email_leaves_from_its_own_address_with_its_own_secret(
    clean_graph: None,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
    captured: _Captured,
) -> None:
    await _seed_for(uow_factory_a, "a")
    await _seed_for(uow_factory_b, "b")
    await _put(uow_factory_a, _channel(tenant_id, "capacity@alpha.example.test"))
    await _put(uow_factory_b, _channel(other_tenant_id, "capacity@bravo.example.test"))
    tenants = StaticTenants([tenant_id, other_tenant_id])
    resolver = _resolver(tenant_id, other_tenant_id)

    first = await _email_consumer(uow_factory_a, tenants, resolver).handle(  # type: ignore[arg-type]
        _email_message(tenant_id, "a")
    )
    second = await _email_consumer(uow_factory_b, tenants, resolver).handle(  # type: ignore[arg-type]
        _email_message(other_tenant_id, "b")
    )

    assert first.kind == second.kind == "completed"
    one, two = captured.calls
    assert one["from"] == "Capacity alpha <capacity@alpha.example.test>"
    assert (one["username"], one["password"]) == ("capacity@alpha.example.test", "password-of-a")
    assert two["from"] == "Capacity bravo <capacity@bravo.example.test>"
    assert (two["username"], two["password"]) == ("capacity@bravo.example.test", "password-of-b")
    assert one["to"] == two["to"] == EMAIL
    assert (await _stored(uow_factory_a, "comm-a")).delivery_status == "sent"
    assert (await _stored(uow_factory_b, "comm-b")).delivery_status == "sent"


async def test_a_tenant_with_no_email_channel_sends_nothing_and_records_no_channel(
    clean_graph: None,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
    captured: _Captured,
    neo4j_driver: Any,
) -> None:
    await _seed_for(uow_factory_a, "a")
    await _put(uow_factory_b, _channel(other_tenant_id, "capacity@bravo.example.test"))
    tenants = StaticTenants([tenant_id, other_tenant_id])

    outcome = await _email_consumer(  # type: ignore[arg-type]
        uow_factory_a, tenants, _resolver(tenant_id, other_tenant_id)
    ).handle(_email_message(tenant_id, "a"))

    assert outcome.kind == "completed"
    assert captured.calls == []
    assert (await _stored(uow_factory_a, "comm-a")).delivery_status == "failed"
    assert (await node_props(neo4j_driver, "Communication", id="comm-a"))["errorCode"] == NO_CHANNEL


async def test_a_retired_channel_is_not_a_sender(
    clean_graph: None,
    uow_factory_a: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
    captured: _Captured,
) -> None:
    await _seed_for(uow_factory_a, "a")
    await _put(
        uow_factory_a,
        _channel(tenant_id, "capacity@alpha.example.test", NumberStatus.RETIRED),
    )

    outcome = await _email_consumer(  # type: ignore[arg-type]
        uow_factory_a,
        StaticTenants([tenant_id]),
        _resolver(tenant_id, other_tenant_id),
    ).handle(_email_message(tenant_id, "a"))

    assert outcome.kind == "completed"
    assert captured.calls == []
    assert (await _stored(uow_factory_a, "comm-a")).delivery_status == "failed"
