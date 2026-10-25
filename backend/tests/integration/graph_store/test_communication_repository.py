"""Integration tests for the Neo4j communication records (P07, DEC-004, DEC-054).

They run against the throwaway Neo4j that the F10 harness starts for the pytest session. Each write
commits in one transaction and each read runs in a fresh session, so the assertions are about what
was really stored. The sample values are synthetic: a role id, a catalogue id and a mobile number
from the prompt, never a patient name, NHS number or postcode.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.communication_repository import (
    Neo4jCommunicationRepository,
)
from diucs.application.ports.outbound.messaging import Communication
from diucs.domain.codes import Channel
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip

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
        "MATCH (t:Concept {system: $system, code: 'C1'}) RETURN count(t) AS total",
        system=MESSAGE_SYSTEM,
    )
    medium_count = await _count(
        neo4j_driver,
        "MATCH (m:Concept {system: $system, code: 'text'}) RETURN count(m) AS total",
        system=CHANNEL_SYSTEM,
    )
    recipient_links = await _count(
        neo4j_driver,
        "MATCH (:Communication)-[:RECIPIENT]->(:PractitionerRole {id: 'role-1'}) "
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
        "MATCH (:Communication {id: 'comm-reply'})-[:IN_RESPONSE_TO]->"
        "(:Communication {id: 'comm-1'}) RETURN count(*) AS total",
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
