"""The inbound consumers with the same sender and the same provider id in two tenants (I08).

The shared harness schema still holds the superseded single-property keys (until TEN-032), so a
second tenant cannot use a message id the first holds. This test runs on a private container with
every migration applied and those keys dropped, the schema the platform will have
(the contracted schema, DEC-159). Tenant A and tenant B each
receive a text from the same phone hash with the same Twilio message id, and a receipt with the same
bus id: each is handled in its own tenant and none is taken for the other's duplicate.
"""

import pytest
from neo4j import AsyncDriver

from diucs.adapters.inbound.workers.delivery_tracker import receipt_consumer
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.reply_processor import reply_consumer
from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_uow_factory
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.bootstrap.container import TEST_NOW
from tests.support.inbound_rig import (
    PHONE,
    RecordingUseCase,
    UnitLog,
    logging_factory,
    receipt_message,
    reply_message,
)
from tests.support.neo4j import read_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_the_same_sender_and_the_same_message_id_in_two_tenants_are_two_messages(
    tenant_id: str, other_tenant_id: str, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    tenants = StaticTenants([tenant_id, other_tenant_id])
    driver = neo4j_driver
    log = UnitLog()
    factory = logging_factory(neo4j_uow_factory(driver, clock=FixedClock(TEST_NOW)), log)
    use_case = RecordingUseCase(factory)
    replies = reply_consumer(use_case, factory, tenants)
    receipts = receipt_consumer(factory, tenants)

    a = await replies.handle(reply_message(tenant_id, "SM1", text="4"))
    b = await replies.handle(reply_message(other_tenant_id, "SM1", text="4"))
    again_a = await replies.handle(reply_message(tenant_id, "SM1", text="4"))
    again_b = await replies.handle(reply_message(other_tenant_id, "SM1", text="4"))
    ra = await receipts.handle(receipt_message(tenant_id, "SM1", "delivered"))
    rb = await receipts.handle(receipt_message(other_tenant_id, "SM1", "delivered"))
    r_again = await receipts.handle(receipt_message(other_tenant_id, "SM1", "delivered"))

    assert [m.kind for m in (a, b, again_a, again_b)] == [
        "completed",
        "completed",
        "duplicate",
        "duplicate",
    ]
    assert [m.kind for m in (ra, rb, r_again)] == ["completed", "completed", "duplicate"]
    assert use_case.tenants == [tenant_id, other_tenant_id]
    assert [(c.idempotency_key, c.from_phone_hash) for c in use_case.commands] == [
        (f"sms-reply:{tenant_id}:SM1", PHONE),
        (f"sms-reply:{other_tenant_id}:SM1", PHONE),
    ]

    async def markers(tx: object) -> list[tuple[str, str, str]]:
        result = await tx.run(  # type: ignore[attr-defined]
            "MATCH (p:Processed) RETURN p.tenantId AS t, p.consumer AS c, p.messageId AS m"
        )
        return sorted([(r["t"], r["c"], r["m"]) async for r in result])

    assert await read_tx(driver, markers) == sorted(
        [
            (tenant_id, "reply-processor", "SM1"),
            (other_tenant_id, "reply-processor", "SM1"),
            (tenant_id, "delivery-tracker", "SM1:delivered"),
            (other_tenant_id, "delivery-tracker", "SM1:delivered"),
        ]
    )
    assert {s.value for s in log.scopes if s is not None} == {tenant_id, other_tenant_id}
    assert None not in log.scopes
