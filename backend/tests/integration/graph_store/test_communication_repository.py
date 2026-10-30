"""Integration tests for the Neo4j communication records (P07, DEC-004, DEC-056).

They run against the throwaway Neo4j that the F10 harness starts for the pytest session. Each write
commits in one transaction and each read runs in a fresh session, so the assertions are about what
was really stored. The sample values are synthetic: a role id, a catalogue id and a mobile number
from the prompt, never a patient name, NHS number or postcode.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.communication_repository import (
    Neo4jCommunicationRepository,
)
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.tenancy import bind_tenant
from diucs.domain.codes import Channel
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from tests.support.neo4j import count_nodes, node_props, read_tx, run_scope_ids, write_tx
from tests.support.round_trip import assert_round_trip
from tests.support.scoped import scoped

pytestmark = pytest.mark.asyncio(loop_scope="session")

SENT = datetime(2026, 10, 25, 9, 0, 0, tzinfo=UTC)
MESSAGE_SYSTEM = "https://diucs.example/CodeSystem/message-id"
CHANNEL_SYSTEM = "https://diucs.example/CodeSystem/channel"


def _comm(**overrides: Any) -> Communication:
    fields: dict[str, Any] = {
        "id": "comm-1",
        "message_id": "C1",
        "channel": Channel.TEXT,
        "recipient_role_id": "role-1",
        "about_id": "svc-1",
        "payload_text": "UCR West: how many referrals can you take? Reply by 12:30.",
        "sent_at": SENT,
        "delivery_status": "sent",
        "provider_message_id": "sms-1",
        "in_response_to": None,
    }
    fields.update(overrides)
    return Communication(**fields)


def _reply(**overrides: Any) -> Communication:
    fields: dict[str, Any] = {
        "delivery_status": "received",
        "provider_message_id": None,
        "payload_text": "Y",
        "in_response_to": "comm-1",
    }
    fields.update(overrides)
    return _comm(**fields)


async def _add(driver: AsyncDriver, communication: Communication) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jCommunicationRepository(tx).add(communication)

    await write_tx(driver, work)


async def _get(driver: AsyncDriver, communication_id: str) -> Communication | None:
    async def work(tx: AsyncManagedTransaction) -> Communication | None:
        return await Neo4jCommunicationRepository(tx).get(communication_id)

    return await read_tx(driver, work)


async def _count(driver: AsyncDriver, query: str, **params: Any) -> int:
    async def work(tx: AsyncManagedTransaction) -> int:
        record = await (await tx.run(query, **params)).single()
        assert record is not None
        return int(record["total"])

    return await read_tx(driver, work)


async def test_add_then_get_round_trips_in_a_fresh_session(neo4j_driver: AsyncDriver) -> None:
    original = _comm()

    async def save(tx: AsyncManagedTransaction) -> None:
        await Neo4jCommunicationRepository(tx).add(original)

    async def load(tx: AsyncManagedTransaction) -> Communication | None:
        return await Neo4jCommunicationRepository(tx).get("comm-1")

    await assert_round_trip(neo4j_driver, save, load, original)


async def test_a_grouped_communication_round_trips_and_is_a_prompt_for_its_phone(
    neo4j_driver: AsyncDriver,
) -> None:
    # U04: one C9 is stored for each service of a grouped prompt, and only one is sent. The others
    # have the status "grouped" and no provider id, and U05 still finds them as the phone's prompt.
    grouped = _comm(
        id="comm-grouped",
        message_id="C9",
        delivery_status="grouped",
        provider_message_id=None,
        payload_text="DIUCS: 2 services need an update by 10:30. A) UCR East 1. B) UCR West 3.",
    )

    async def save(tx: AsyncManagedTransaction) -> None:
        await Neo4jCommunicationRepository(tx).add(grouped)

    async def load(tx: AsyncManagedTransaction) -> Communication | None:
        return await Neo4jCommunicationRepository(tx).get("comm-grouped")

    await assert_round_trip(neo4j_driver, save, load, grouped)

    async def latest(tx: AsyncManagedTransaction) -> Communication | None:
        return await Neo4jCommunicationRepository(tx).latest_prompt_for_phone({"role-1"}, {"C9"})

    assert await read_tx(neo4j_driver, latest) == grouped
    props = await node_props(neo4j_driver, "Communication", id="comm-grouped")
    assert props["deliveryStatus"] == "grouped"
    assert props["status"] == "completed"


async def test_an_inbound_reply_round_trips_with_its_received_time(
    neo4j_driver: AsyncDriver,
) -> None:
    await _add(neo4j_driver, _comm())
    inbound = _reply(id="comm-in-1", sent_at=SENT + timedelta(minutes=5))
    await _add(neo4j_driver, inbound)
    assert await _get(neo4j_driver, "comm-in-1") == inbound


async def test_the_stored_node_has_the_communication_labels_and_no_json(
    neo4j_driver: AsyncDriver,
) -> None:
    await _add(neo4j_driver, _comm())
    assert await count_nodes(neo4j_driver, "Communication") == 1
    props = await node_props(neo4j_driver, "Communication", id="comm-1")
    assert props["status"] == "completed"
    assert props["deliveryStatus"] == "sent"
    assert props["providerMessageId"] == "sms-1"
    assert props["payloadText"].startswith("UCR West")
    assert "json" not in props
    assert all(not isinstance(value, dict) for value in props.values())


async def test_topic_and_medium_are_shared_concepts_and_the_recipient_is_a_role(
    neo4j_driver: AsyncDriver,
) -> None:
    await _add(neo4j_driver, _comm(id="comm-1"))
    await _add(neo4j_driver, _comm(id="comm-2", provider_message_id="sms-2"))
    topic_count = await _count(
        neo4j_driver,
        "MATCH (t:Concept {system: $system, code: 'C1', tenantId: $tenant}) RETURN count(t) AS "
        "total",
        system=MESSAGE_SYSTEM,
    )
    medium_count = await _count(
        neo4j_driver,
        "MATCH (m:Concept {system: $system, code: 'text', tenantId: $tenant}) RETURN count(m) AS "
        "total",
        system=CHANNEL_SYSTEM,
    )
    recipient_links = await _count(
        neo4j_driver,
        "MATCH (:Communication {tenantId: $tenant})-[:RECIPIENT]->(:PractitionerRole {id: "
        "'role-1', tenantId: $tenant}) "
        "RETURN count(*) AS total",
    )
    assert topic_count == 1
    assert medium_count == 1
    assert recipient_links == 2


async def test_set_delivery_status_updates_the_stored_node_and_returns_true(
    neo4j_driver: AsyncDriver,
) -> None:
    await _add(neo4j_driver, _comm())

    async def work(tx: AsyncManagedTransaction) -> bool:
        return await Neo4jCommunicationRepository(tx).set_delivery_status("sms-1", "delivered")

    assert await write_tx(neo4j_driver, work) is True
    props = await node_props(neo4j_driver, "Communication", id="comm-1")
    assert props["deliveryStatus"] == "delivered"


async def test_set_delivery_status_for_an_unknown_provider_id_returns_false(
    neo4j_driver: AsyncDriver,
) -> None:
    await _add(neo4j_driver, _comm())

    async def work(tx: AsyncManagedTransaction) -> bool:
        return await Neo4jCommunicationRepository(tx).set_delivery_status("sms-9", "delivered")

    assert await write_tx(neo4j_driver, work) is False


async def test_by_provider_id_finds_the_record_and_an_unknown_id_finds_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    original = _comm()
    await _add(neo4j_driver, original)

    async def find(tx: AsyncManagedTransaction, provider_id: str) -> Communication | None:
        return await Neo4jCommunicationRepository(tx).by_provider_id(provider_id)

    async def found(provider_id: str) -> Communication | None:
        async def work(tx: AsyncManagedTransaction) -> Communication | None:
            return await find(tx, provider_id)

        return await read_tx(neo4j_driver, work)

    assert await found("sms-1") == original
    assert await found("sms-9") is None


async def test_get_of_an_unknown_id_returns_none(neo4j_driver: AsyncDriver) -> None:
    assert await _get(neo4j_driver, "comm-missing") is None


async def test_latest_prompt_for_phone_returns_the_newest_matching_and_ignores_a_newer_echo(
    neo4j_driver: AsyncDriver,
) -> None:
    await _add(neo4j_driver, _comm(id="comm-c1", message_id="C1", sent_at=SENT))
    newer = _comm(
        id="comm-c9",
        message_id="C9",
        recipient_role_id="role-2",
        sent_at=SENT + timedelta(minutes=30),
        provider_message_id="sms-2",
    )
    echo = _comm(
        id="comm-c3",
        message_id="C3",
        sent_at=SENT + timedelta(minutes=45),
        provider_message_id="sms-3",
    )
    await _add(neo4j_driver, newer)
    await _add(neo4j_driver, echo)

    async def work(tx: AsyncManagedTransaction) -> Communication | None:
        return await Neo4jCommunicationRepository(tx).latest_prompt_for_phone(
            {"role-1", "role-2"}, {"C1", "C9"}
        )

    assert await read_tx(neo4j_driver, work) == newer


async def test_latest_prompt_ignores_inbound_replies(neo4j_driver: AsyncDriver) -> None:
    prompt = _comm(id="comm-c1", message_id="C1", sent_at=SENT)
    await _add(neo4j_driver, prompt)
    await _add(
        neo4j_driver,
        _reply(
            id="comm-reply",
            message_id="C1",
            sent_at=SENT + timedelta(minutes=5),
            in_response_to="comm-c1",
        ),
    )

    async def work(tx: AsyncManagedTransaction) -> Communication | None:
        return await Neo4jCommunicationRepository(tx).latest_prompt_for_phone({"role-1"}, {"C1"})

    assert await read_tx(neo4j_driver, work) == prompt


async def test_a_reply_threads_to_its_prompt_through_in_response_to(
    neo4j_driver: AsyncDriver,
) -> None:
    await _add(neo4j_driver, _comm(id="comm-1"))
    await _add(neo4j_driver, _reply(id="comm-reply", in_response_to="comm-1"))
    threads = await _count(
        neo4j_driver,
        "MATCH (:Communication {id: 'comm-reply', tenantId: $tenant})-[:IN_RESPONSE_TO]->"
        "(:Communication {id: 'comm-1', tenantId: $tenant}) RETURN count(*) AS total",
    )
    assert threads == 1


async def test_a_reply_to_an_unknown_prompt_is_refused_and_nothing_is_stored(
    neo4j_driver: AsyncDriver,
) -> None:
    with pytest.raises(NotFound):
        await _add(neo4j_driver, _reply(id="comm-orphan", in_response_to="comm-missing"))
    assert await count_nodes(neo4j_driver, "Communication") == 0


async def test_adding_an_existing_id_raises_conflict(neo4j_driver: AsyncDriver) -> None:
    await _add(neo4j_driver, _comm())
    with pytest.raises(Conflict):
        await _add(neo4j_driver, _comm(provider_message_id="sms-7"))
    assert await count_nodes(neo4j_driver, "Communication") == 1


async def test_an_unknown_delivery_status_is_refused(neo4j_driver: AsyncDriver) -> None:
    with pytest.raises(ValidationFailed):
        await _add(neo4j_driver, _comm(delivery_status="lost"))
    assert await count_nodes(neo4j_driver, "Communication") == 0


async def test_a_naive_sent_time_is_refused(neo4j_driver: AsyncDriver) -> None:
    with pytest.raises(ValidationFailed):
        await _add(neo4j_driver, _comm(sent_at=datetime(2026, 10, 25, 9, 0)))
    assert await count_nodes(neo4j_driver, "Communication") == 0


async def test_set_delivery_status_refuses_an_unknown_status(neo4j_driver: AsyncDriver) -> None:
    await _add(neo4j_driver, _comm())

    async def work(tx: AsyncManagedTransaction) -> bool:
        return await Neo4jCommunicationRepository(tx).set_delivery_status("sms-1", "lost")

    with pytest.raises(ValidationFailed):
        await write_tx(neo4j_driver, work)
    props = await node_props(neo4j_driver, "Communication", id="comm-1")
    assert props["deliveryStatus"] == "sent"


async def test_a_refused_reply_that_is_swallowed_and_committed_leaves_no_node(
    neo4j_driver: AsyncDriver,
) -> None:
    """A caller that catches NotFound and commits must find nothing stored: no communication, and
    no placeholder recipient or subject either (DEC-053 item 16, DEC-056 item 7)."""

    async def probe(tx: AsyncManagedTransaction) -> None:
        with contextlib.suppress(NotFound):
            await Neo4jCommunicationRepository(tx).add(
                _reply(id="comm-orphan", in_response_to="comm-missing")
            )

    await write_tx(neo4j_driver, probe)
    assert await count_nodes(neo4j_driver, "Communication") == 0
    assert await count_nodes(neo4j_driver, "Resource") == 0
    assert await count_nodes(neo4j_driver, "PractitionerRole") == 0
    assert await count_nodes(neo4j_driver, "HealthcareService") == 0


async def test_a_retried_add_of_the_same_request_succeeds_without_a_second_write(
    neo4j_driver: AsyncDriver,
) -> None:
    original = _comm()
    await _add(neo4j_driver, original)
    await _add(neo4j_driver, original)
    assert await count_nodes(neo4j_driver, "Communication") == 1
    assert await _get(neo4j_driver, "comm-1") == original


async def test_a_second_add_with_the_same_id_and_different_content_is_refused(
    neo4j_driver: AsyncDriver,
) -> None:
    original = _comm()
    await _add(neo4j_driver, original)
    with pytest.raises(Conflict):
        await _add(neo4j_driver, _comm(payload_text="a different text"))
    assert await _get(neo4j_driver, "comm-1") == original


# --- the delivery status only moves forward (I08, DEC-165) ----------------------------------------


async def _set_status(driver: AsyncDriver, provider_id: str, status: str) -> bool:
    async def work(tx: AsyncManagedTransaction) -> bool:
        return await Neo4jCommunicationRepository(tx).set_delivery_status(provider_id, status)

    return await write_tx(driver, work)


@pytest.mark.parametrize(
    ("stored", "new", "expected", "moved"),
    [
        ("queued", "sent", "sent", True),
        ("queued", "delivered", "delivered", True),
        ("queued", "failed", "failed", True),
        ("sent", "delivered", "delivered", True),
        ("sent", "failed", "failed", True),
        ("queued", "queued", "queued", False),
        ("sent", "queued", "sent", False),
        ("sent", "sent", "sent", False),
        ("delivered", "queued", "delivered", False),
        ("delivered", "sent", "delivered", False),
        ("delivered", "delivered", "delivered", False),
        ("delivered", "failed", "delivered", False),
        ("failed", "queued", "failed", False),
        ("failed", "sent", "failed", False),
        ("failed", "delivered", "failed", False),
        ("failed", "failed", "failed", False),
        ("received", "delivered", "received", False),
        ("grouped", "delivered", "grouped", False),
    ],
)
async def test_a_status_moves_forward_only_and_delivered_and_failed_are_final(
    neo4j_driver: AsyncDriver, stored: str, new: str, expected: str, moved: bool
) -> None:
    await _add(neo4j_driver, _comm(delivery_status=stored))

    result = await _set_status(neo4j_driver, "sms-1", new)

    assert result is moved
    props = await node_props(neo4j_driver, "Communication", id="comm-1")
    assert props["deliveryStatus"] == expected


@pytest.mark.parametrize(
    ("new", "fhir"), [("sent", "completed"), ("delivered", "completed"), ("failed", "not-done")]
)
async def test_the_fhir_status_follows_the_delivery_status(
    neo4j_driver: AsyncDriver, new: str, fhir: str
) -> None:
    await _add(neo4j_driver, _comm(delivery_status="queued"))

    await _set_status(neo4j_driver, "sms-1", new)

    props = await node_props(neo4j_driver, "Communication", id="comm-1")
    assert props["status"] == fhir


async def test_a_refused_move_leaves_the_fhir_status_alone(neo4j_driver: AsyncDriver) -> None:
    await _add(neo4j_driver, _comm(delivery_status="failed"))
    before = await node_props(neo4j_driver, "Communication", id="comm-1")

    await _set_status(neo4j_driver, "sms-1", "delivered")

    assert await node_props(neo4j_driver, "Communication", id="comm-1") == before


async def test_a_late_sent_waits_for_a_held_delivered_and_does_not_overwrite_it(
    neo4j_driver: AsyncDriver,
) -> None:
    """Two receipts handled at once: the delivered one holds the write and has not committed. The
    sent one must wait for it and then see delivered, not decide from the queued it read first."""
    await _add(neo4j_driver, _comm(delivery_status="queued"))
    async with neo4j_driver.session() as session:
        held = scoped(await session.begin_transaction())
        await held.run(
            "MATCH (c:Communication {id: 'comm-1', tenantId: $tenant}) "
            "SET c.deliveryStatus = 'delivered', c.status = 'completed'"
        )
        late = asyncio.create_task(_set_status(neo4j_driver, "sms-1", "sent"))
        await asyncio.sleep(1.0)
        assert not late.done()  # it is waiting for the lock, not deciding from a stale read
        await held.commit()
        assert await asyncio.wait_for(late, timeout=30) is False

    props = await node_props(neo4j_driver, "Communication", id="comm-1")
    assert props["deliveryStatus"] == "delivered"


async def test_receipts_applied_in_every_order_all_end_delivered(
    neo4j_driver: AsyncDriver,
) -> None:
    await _add(neo4j_driver, _comm(delivery_status="queued"))

    results = await asyncio.gather(
        *(
            _set_status(neo4j_driver, "sms-1", status)
            for status in ("sent", "delivered", "queued", "sent", "delivered", "sent")
        )
    )

    props = await node_props(neo4j_driver, "Communication", id="comm-1")
    assert props["deliveryStatus"] == "delivered"
    assert results.count(True) <= 2  # queued to sent, then sent to delivered: never more


# --- two tenants (TEN-015): a communication, its provider id and its concepts are one tenant's ---
#
# Both tenants use the same communication id, provider id and concept codes. The contracted
# container holds the composite keys only (TEN-005, TEN-032), so the two tenants can share them.


@pytest_asyncio.fixture(loop_scope="session")
async def two(neo4j_driver: AsyncDriver, clean_graph: None) -> AsyncIterator[AsyncDriver]:
    yield neo4j_driver


async def _add_as(driver: AsyncDriver, tenant: str, communication: Communication) -> None:
    with bind_tenant(tenant):
        await _add(driver, communication)


async def _get_as(driver: AsyncDriver, tenant: str, communication_id: str) -> Communication | None:
    with bind_tenant(tenant):
        return await _get(driver, communication_id)


async def test_another_tenants_communication_reads_as_absent_and_cannot_be_changed(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _add_as(two, other_tenant_id, _comm(id="comm-1", provider_message_id="SM-1"))

    async def as_a_reads(tx: AsyncManagedTransaction) -> tuple[Any, ...]:
        repo = Neo4jCommunicationRepository(tx)
        return (
            await repo.get("comm-1"),
            await repo.by_provider_id("SM-1"),
            await repo.latest_prompt_for_phone({"role-1"}, {"C1"}),
        )

    async def as_a_moves(tx: AsyncManagedTransaction) -> bool:
        return await Neo4jCommunicationRepository(tx).set_delivery_status("SM-1", "delivered")

    async def as_a_replies(tx: AsyncManagedTransaction) -> None:
        with pytest.raises(NotFound):
            await Neo4jCommunicationRepository(tx).add(_reply(id="comm-2", in_response_to="comm-1"))

    with bind_tenant(tenant_id):
        assert await read_tx(two, as_a_reads) == (None, None, None)
        assert await write_tx(two, as_a_moves) is False
        await write_tx(two, as_a_replies)

    stored = await _get_as(two, other_tenant_id, "comm-1")
    assert stored is not None
    assert stored.delivery_status == "sent"


async def test_the_same_ids_in_two_tenants_are_two_communications(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _add_as(two, tenant_id, _comm(id="comm-1", provider_message_id="SM-1", payload_text="A"))
    await _add_as(
        two, other_tenant_id, _comm(id="comm-1", provider_message_id="SM-1", payload_text="B")
    )

    with bind_tenant(tenant_id):
        await _add(two, _comm(id="comm-1", provider_message_id="SM-1", payload_text="A"))
        assert await _get(two, "comm-1") == _comm(
            id="comm-1", provider_message_id="SM-1", payload_text="A"
        )

    async def move_a(tx: AsyncManagedTransaction) -> bool:
        return await Neo4jCommunicationRepository(tx).set_delivery_status("SM-1", "delivered")

    with bind_tenant(tenant_id):
        assert await write_tx(two, move_a) is True
    stored_b = await _get_as(two, other_tenant_id, "comm-1")
    assert stored_b is not None
    assert (stored_b.payload_text, stored_b.delivery_status) == ("B", "sent")


async def test_the_topic_and_channel_concepts_of_each_tenant_are_its_own(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _add_as(two, tenant_id, _comm(id="comm-1", provider_message_id="SM-1"))
    await _add_as(two, other_tenant_id, _comm(id="comm-1", provider_message_id="SM-1"))

    async def concepts(tx: AsyncManagedTransaction) -> list[tuple[str, int]]:
        result = await tx.run(
            "MATCH (c:Concept) WHERE c.tenantId IN $scopes "
            "RETURN c.tenantId AS tenant, count(c) AS n ORDER BY tenant",
            scopes=run_scope_ids(),
        )
        return [(record["tenant"], int(record["n"])) async for record in result]

    rows = await read_tx(two, concepts)
    assert sorted(rows) == sorted([(tenant_id, 2), (other_tenant_id, 2)])
