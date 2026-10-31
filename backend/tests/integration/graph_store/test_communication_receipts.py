"""A receipt that beats the send's record is kept and applied (KI-133), and the error code of a
failed send is read back (KI-189), on real Neo4j.

The provider can call back before the sender has committed the provider id it got: the tracker then
finds no Communication for the id. It used to drop the receipt, so the record stayed `sent` for
good, even when the text was never delivered. The receipt is now parked, and applied, in order, in
the unit of work that records the send (or by the tracker itself when the id is there by then).
"""

import pytest
from neo4j import AsyncDriver

from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import Channel
from tests.support.neo4j import count_nodes
from tests.support.relay_rig import NOW

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _queued(factory: UnitOfWorkFactory, communication_id: str = "comm-1") -> None:
    async with factory() as uow:
        await uow.communications.add(
            Communication(
                id=communication_id,
                message_id="C1",
                channel=Channel.TEXT,
                recipient_role_id=None,
                about_id=None,
                payload_text="DIUCS: UCR West. We have 3 referrals in the next 2 hrs.",
                sent_at=NOW,
                delivery_status="queued",
            )
        )
        await uow.commit()


async def _park(factory: UnitOfWorkFactory, provider_id: str, status: str) -> None:
    async with factory() as uow:
        await uow.communications.park_receipt(provider_id, status, None)
        await uow.commit()


async def _record_send(
    factory: UnitOfWorkFactory, provider_id: str = "SM-early", communication_id: str = "comm-1"
) -> bool:
    async with factory() as uow:
        recorded = await uow.communications.record_send_outcome(
            communication_id, status="sent", provider_message_id=provider_id, error_code=None
        )
        await uow.commit()
    return recorded


async def _get(factory: UnitOfWorkFactory, communication_id: str = "comm-1") -> Communication:
    async with factory() as uow:
        found = await uow.communications.get(communication_id)
    assert found is not None
    return found


# --- KI-133 ---------------------------------------------------------------------------------------


async def test_a_receipt_parked_before_the_send_is_applied_when_the_send_is_recorded(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    await _queued(uow_factory)
    await _park(uow_factory, "SM-early", "delivered")

    assert await _record_send(uow_factory) is True

    stored = await _get(uow_factory)
    assert (stored.delivery_status, stored.provider_message_id) == ("delivered", "SM-early")
    assert await count_nodes(neo4j_driver, "ProviderReceipt") == 0


async def test_a_failed_receipt_that_came_first_is_not_lost(
    uow_factory: UnitOfWorkFactory,
) -> None:
    await _queued(uow_factory)
    await _park(uow_factory, "SM-early", "failed")

    await _record_send(uow_factory)

    assert (await _get(uow_factory)).delivery_status == "failed"


@pytest.mark.parametrize(
    ("order", "final"),
    [
        (["sent", "delivered"], "delivered"),
        (["delivered", "sent"], "delivered"),
        (["queued", "sent", "failed"], "failed"),
    ],
)
async def test_parked_receipts_apply_in_order_and_never_move_a_status_back(
    order: list[str], final: str, uow_factory: UnitOfWorkFactory
) -> None:
    await _queued(uow_factory)
    for status in order:
        await _park(uow_factory, "SM-early", status)

    await _record_send(uow_factory)

    assert (await _get(uow_factory)).delivery_status == final


async def test_a_receipt_parked_for_another_id_is_left_alone(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    await _queued(uow_factory)
    await _park(uow_factory, "SM-other", "delivered")

    await _record_send(uow_factory)

    assert (await _get(uow_factory)).delivery_status == "sent"
    assert await count_nodes(neo4j_driver, "ProviderReceipt") == 1


async def test_the_same_receipt_parked_twice_is_one_receipt(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    await _park(uow_factory, "SM-early", "delivered")
    await _park(uow_factory, "SM-early", "delivered")

    assert await count_nodes(neo4j_driver, "ProviderReceipt") == 1


async def test_a_send_with_nothing_parked_is_recorded_as_before(
    uow_factory: UnitOfWorkFactory,
) -> None:
    await _queued(uow_factory)

    await _record_send(uow_factory)

    assert (await _get(uow_factory)).delivery_status == "sent"


async def test_a_parked_receipt_holds_the_provider_id_and_the_status_only(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    from tests.support.neo4j import node_props

    await _park(uow_factory, "SM-early", "delivered")

    props = await node_props(neo4j_driver, "ProviderReceipt", providerMessageId="SM-early")

    assert set(props) <= {
        "key",
        "providerMessageId",
        "status",
        "errorCode",
        "receivedAt",
        "tenantId",
    }


# --- KI-189 ---------------------------------------------------------------------------------------


async def test_the_error_code_of_a_failed_send_is_read_back(
    uow_factory: UnitOfWorkFactory,
) -> None:
    await _queued(uow_factory)
    async with uow_factory() as uow:
        await uow.communications.record_send_outcome(
            "comm-1", status="failed", provider_message_id=None, error_code="no-contact"
        )
        await uow.commit()

    stored = await _get(uow_factory)

    assert stored.delivery_status == "failed"
    assert stored.error_code == "no-contact"


async def test_a_communication_with_no_failure_has_no_error_code(
    uow_factory: UnitOfWorkFactory,
) -> None:
    await _queued(uow_factory)
    await _record_send(uow_factory)

    stored = await _get(uow_factory)

    assert stored.error_code is None
    async with uow_factory() as uow:
        by_provider = await uow.communications.by_provider_id("SM-early")
    assert by_provider is not None and by_provider.error_code is None
