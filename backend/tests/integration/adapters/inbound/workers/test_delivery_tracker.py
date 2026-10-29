"""The delivery tracker on real Neo4j (I08, DEC-165).

Communications are seeded with the real `Neo4jCommunicationRepository` and read back in a fresh unit
of work. A receipt moves a Communication's delivery status forward and never back: delivered and
failed are final, and a late sent, an out-of-order queued or a repeat changes nothing. The tenant is
the one on the message, bound before the unit of work opens.

TENANT-PENDING (TEN-015): the statements that find and change a Communication by its provider id
are not yet tenant-scoped (no node carries tenantId yet), so one tenant's receipt can still reach
another tenant's Communication with the same provider id. The test that shows this is strict xfail:
it must start passing when the statements are converted, and then the marker is removed.
"""

import itertools
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.delivery_tracker import receipt_consumer
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import current_scope_or_none
from diucs.domain.codes import Channel
from tests.support.inbound_rig import Receiver, UnitLog, logging_factory, raw, receipt_message
from tests.support.neo4j import count_nodes, node_props, read_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

SENT = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)


@pytest.fixture
def tenants(tenant_id: str, other_tenant_id: str) -> StaticTenants:
    return StaticTenants([tenant_id, other_tenant_id])


async def _seed(
    factory: UnitOfWorkFactory,
    provider_id: str | None = "SM1",
    status: str = "sent",
    communication_id: str = "comm-1",
    **changes: Any,
) -> None:
    fields: dict[str, Any] = {
        "id": communication_id,
        "message_id": "C1",
        "channel": Channel.TEXT,
        "recipient_role_id": None,
        "about_id": None,
        "payload_text": "DIUCS: UCR West. We have 3 referrals in the next 2 hrs.",
        "sent_at": SENT,
        "delivery_status": status,
        "provider_message_id": provider_id,
    }
    fields.update(changes)
    async with factory() as uow:
        await uow.communications.add(Communication(**fields))
        await uow.commit()


async def _stored(factory: UnitOfWorkFactory, provider_id: str) -> Communication | None:
    async with factory() as uow:
        return await uow.communications.by_provider_id(provider_id)


async def _status(factory: UnitOfWorkFactory, provider_id: str = "SM1") -> str:
    found = await _stored(factory, provider_id)
    assert found is not None
    return found.delivery_status


# --- 5 to 8 --------------------------------------------------------------------------------------


async def test_a_delivered_receipt_for_a_known_provider_id_sets_the_status_delivered(
    uow_factory: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str
) -> None:
    await _seed(uow_factory, status="sent")

    outcome = await receipt_consumer(uow_factory, tenants).handle(
        receipt_message(tenant_id, "SM1", "delivered")
    )

    assert outcome == Outcome("completed")
    assert await _status(uow_factory) == "delivered"


async def test_a_sent_receipt_after_delivered_leaves_the_status_delivered(
    uow_factory: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str
) -> None:
    await _seed(uow_factory, status="queued")
    consumer = receipt_consumer(uow_factory, tenants)

    await consumer.handle(receipt_message(tenant_id, "SM1", "delivered"))
    late = await consumer.handle(receipt_message(tenant_id, "SM1", "sent"))

    assert late == Outcome("completed")
    assert await _status(uow_factory) == "delivered"


async def test_a_receipt_for_an_unknown_provider_id_completes_and_writes_nothing(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(uow_factory, "SM1", status="sent")
    before = await node_props(neo4j_driver, "Communication", id="comm-1")

    outcome = await receipt_consumer(uow_factory, tenants).handle(
        receipt_message(tenant_id, "SM-NOT-KNOWN", "delivered")
    )

    assert outcome == Outcome("completed")
    assert await node_props(neo4j_driver, "Communication", id="comm-1") == before
    assert await count_nodes(neo4j_driver, "Communication") == 1


async def test_a_failed_receipt_with_an_error_code_is_stored_as_failed(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _seed(uow_factory, status="sent")

    with caplog.at_level("INFO"):
        outcome = await receipt_consumer(uow_factory, tenants).handle(
            receipt_message(tenant_id, "SM1", "failed", "30003")
        )

    assert outcome == Outcome("completed")
    assert await _status(uow_factory) == "failed"
    assert (await node_props(neo4j_driver, "Communication", id="comm-1"))["status"] == "not-done"
    # The provider's code is for staff to read in the log, next to the provider id only.
    assert any("30003" in record.getMessage() for record in caplog.records)


# --- never backwards, duplicates -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "receipt", "expected"),
    [
        ("queued", "sent", "sent"),
        ("queued", "delivered", "delivered"),
        ("queued", "failed", "failed"),
        ("sent", "delivered", "delivered"),
        ("sent", "failed", "failed"),
        ("sent", "queued", "sent"),
        ("sent", "sent", "sent"),
        ("delivered", "queued", "delivered"),
        ("delivered", "sent", "delivered"),
        ("delivered", "failed", "delivered"),
        ("failed", "sent", "failed"),
        ("failed", "delivered", "failed"),
        ("received", "delivered", "received"),
        ("grouped", "delivered", "grouped"),
    ],
)
async def test_a_status_never_goes_backwards_and_delivered_and_failed_are_final(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    stored: str,
    receipt: str,
    expected: str,
) -> None:
    await _seed(uow_factory, status=stored)

    outcome = await receipt_consumer(uow_factory, tenants).handle(
        receipt_message(tenant_id, "SM1", receipt)
    )

    assert outcome == Outcome("completed")
    assert await _status(uow_factory) == expected


async def test_every_arrival_order_of_the_three_receipts_ends_delivered(
    uow_factory: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str
) -> None:
    for order in itertools.permutations(["queued", "sent", "delivered"]):
        await _seed(uow_factory, f"SM-{'-'.join(order)}", "queued", f"c-{'-'.join(order)}")
        consumer = receipt_consumer(uow_factory, tenants)
        for status in order:
            await consumer.handle(receipt_message(tenant_id, f"SM-{'-'.join(order)}", status))
        assert await _status(uow_factory, f"SM-{'-'.join(order)}") == "delivered", order


async def test_the_same_receipt_twice_is_one_marker_and_one_change(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(uow_factory, status="sent")
    consumer = receipt_consumer(uow_factory, tenants)

    first = await consumer.handle(receipt_message(tenant_id, "SM1", "delivered"))
    second = await consumer.handle(receipt_message(tenant_id, "SM1", "delivered"))

    assert (first.kind, second.kind) == ("completed", "duplicate")
    assert await _status(uow_factory) == "delivered"
    assert await count_nodes(neo4j_driver, "Processed") == 1


async def test_the_marker_is_written_with_the_change_or_not_at_all(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    """A receipt the tracker refuses writes no marker, so a corrected redelivery is handled."""
    await _seed(uow_factory, status="sent")

    outcome = await receipt_consumer(uow_factory, tenants).handle(
        receipt_message(tenant_id, "SM1", "read")
    )

    assert outcome.kind == "dead-letter"
    assert await count_nodes(neo4j_driver, "Processed") == 0
    assert await _status(uow_factory) == "sent"


# --- the tenant ----------------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["missing", "unknown", "network"])
async def test_a_receipt_with_no_known_tenant_is_dead_lettered_and_changes_nothing(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    neo4j_driver: AsyncDriver,
    which: str,
) -> None:
    await _seed(uow_factory, status="sent")
    log = UnitLog()
    tenant = {"missing": None, "unknown": "tenant-zz", "network": "net-abcd1234"}[which]

    outcome = await receipt_consumer(logging_factory(uow_factory, log), tenants).handle(
        receipt_message(tenant, "SM1", "delivered")
    )

    assert outcome.kind == "dead-letter"
    assert log.scopes == []
    assert await _status(uow_factory) == "sent"
    assert await count_nodes(neo4j_driver, "Processed") == 0


async def test_the_unit_of_work_opens_in_the_messages_tenant(
    uow_factory: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str, other_tenant_id: str
) -> None:
    await _seed(uow_factory, "SM1", status="sent")
    log = UnitLog()
    consumer = receipt_consumer(logging_factory(uow_factory, log), tenants)

    await consumer.handle(receipt_message(tenant_id, "SM1", "delivered"))
    await consumer.handle(receipt_message(other_tenant_id, "SM9", "delivered"))

    assert [scope.value for scope in log.scopes if scope is not None] == [
        tenant_id,
        other_tenant_id,
    ]
    assert current_scope_or_none() is not None  # the harness binding is back


async def test_two_tenants_each_have_their_own_marker_for_their_receipts(
    uow_factory: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
    other_tenant_id: str,
    neo4j_driver: AsyncDriver,
) -> None:
    """Receipts for tenant A and tenant B each carry their tenant on the marker. (The shared harness
    schema still holds the old single-property marker key, so the two ids differ here; the same id
    in both is in test_inbound_two_tenants.py.)"""
    consumer = receipt_consumer(uow_factory, tenants)

    a = await consumer.handle(receipt_message(tenant_id, "SM1", "delivered"))
    b = await consumer.handle(receipt_message(other_tenant_id, "SM2", "delivered"))
    again = await consumer.handle(receipt_message(other_tenant_id, "SM2", "delivered"))

    assert (a.kind, b.kind, again.kind) == ("completed", "completed", "duplicate")

    async def marked(tx: Any) -> list[tuple[str, str]]:
        result = await tx.run("MATCH (p:Processed) RETURN p.tenantId AS t, p.messageId AS m")
        return sorted([(record["t"], record["m"]) async for record in result])

    assert await read_tx(neo4j_driver, marked) == sorted(
        [(tenant_id, "SM1:delivered"), (other_tenant_id, "SM2:delivered")]
    )


async def test_another_tenants_message_id_reads_as_not_found_and_is_dropped(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    tenants: StaticTenants,
    tenant_id: str,
) -> None:
    """Tenant B holds a Communication with provider id SM1. A receipt for SM1 that arrives for
    tenant A must find nothing, change nothing of B's and complete."""
    await _seed(uow_factory_b, "SM1", status="sent")

    outcome = await receipt_consumer(uow_factory_a, tenants).handle(
        receipt_message(tenant_id, "SM1", "delivered")
    )

    assert outcome == Outcome("completed")
    assert await _status(uow_factory_b) == "sent"


# --- the runner: one poison receipt does not block the queue --------------------------------------


async def test_a_poison_receipt_is_dead_lettered_and_the_next_one_is_applied(
    uow_factory: UnitOfWorkFactory, tenants: StaticTenants, tenant_id: str
) -> None:
    await _seed(uow_factory, status="sent")
    runner = ServiceBusRunner(
        client=None,  # type: ignore[arg-type]
        entity="inbound.receipts",
        subscription=None,
        consumer=receipt_consumer(uow_factory, tenants),
    )
    receiver = Receiver()

    await runner.process(
        receiver, raw(receipt_message(tenant_id, "SM1", "delivered", omit=("status",)))
    )
    await runner.process(receiver, raw(receipt_message(None, "SM1", "delivered")))
    await runner.process(receiver, raw(receipt_message(tenant_id, "SM1", "delivered")))

    assert [name for name, _ in receiver.calls] == ["dead-letter", "dead-letter", "complete"]
    assert await _status(uow_factory) == "delivered"
