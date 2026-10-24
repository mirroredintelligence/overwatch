"""Smoke tests for the local Docker services in infra/ (F04).

They open their own connections to the services that
`docker compose -f infra/docker-compose.yml up -d --wait` starts. They are not the shared
harness (that arrives with F10), and they do not start containers: DEC-008 gives the test
suite its own throwaway Neo4j, while this file proves the local compose stack itself.
"""

import os

from azure.servicebus import ServiceBusClient, ServiceBusMessage
from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession
from redis.asyncio import Redis

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "diucs-test-password")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
SERVICEBUS_CONNECTION = os.environ.get(
    "SERVICEBUS_CONNECTION",
    "Endpoint=sb://localhost;SharedAccessKeyName=RootManageSharedAccessKey;"
    "SharedAccessKey=SAS_KEY_VALUE;UseDevelopmentEmulator=true;",
)
PROBE_KEY = "infra-probe"


def _driver() -> AsyncDriver:
    return AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


async def _single_value(session: AsyncSession, query: str, key: str) -> object:
    result = await session.run(query)
    record = await result.single()
    assert record is not None
    return record[key]


async def test_neo4j_answers_a_query() -> None:
    driver = _driver()
    try:
        async with driver.session() as session:
            ok = await _single_value(session, "RETURN 1 AS ok", "ok")
        assert ok == 1
    finally:
        await driver.close()


async def test_neo4j_keeps_a_node_across_drivers() -> None:
    writer = _driver()
    try:
        async with writer.session() as session:
            result = await session.run("CREATE (:InfraProbe {id: 'p1'})")
            await result.consume()
    finally:
        await writer.close()

    reader = _driver()
    try:
        async with reader.session() as session:
            try:
                count = await _single_value(
                    session,
                    "MATCH (p:InfraProbe {id: 'p1'}) RETURN count(p) AS n",
                    "n",
                )
                assert count == 1
            finally:
                cleanup = await session.run("MATCH (p:InfraProbe {id: 'p1'}) DELETE p")
                await cleanup.consume()
    finally:
        await reader.close()


async def test_redis_pings_and_expires_a_key_after_five_seconds() -> None:
    client = Redis.from_url(REDIS_URL)
    try:
        assert await client.ping() is True
        await client.set(PROBE_KEY, "alive", ex=5)
        assert await client.get(PROBE_KEY) == b"alive"
        ttl = await client.ttl(PROBE_KEY)
        assert 0 < ttl <= 5
    finally:
        await client.delete(PROBE_KEY)
        await client.aclose()


def test_queue_delivers_message_id_and_body() -> None:
    with ServiceBusClient.from_connection_string(SERVICEBUS_CONNECTION) as client:
        with client.get_queue_sender("inbound.replies") as sender:
            sender.send_messages(ServiceBusMessage("smoke body", message_id="smoke-1"))
        with client.get_queue_receiver("inbound.replies", max_wait_time=10) as receiver:
            messages = receiver.receive_messages(max_message_count=1, max_wait_time=10)
            assert len(messages) == 1
            assert messages[0].message_id == "smoke-1"
            assert str(messages[0]) == "smoke body"
            receiver.complete_message(messages[0])


def test_session_subscription_receives_publish_on_its_session() -> None:
    with ServiceBusClient.from_connection_string(SERVICEBUS_CONNECTION) as client:
        with client.get_topic_sender("capacity.events") as sender:
            sender.send_messages(ServiceBusMessage("svc-1 update", session_id="svc-1"))
        with client.get_subscription_receiver(
            "capacity.events", "board-projector", session_id="svc-1", max_wait_time=10
        ) as receiver:
            messages = receiver.receive_messages(max_message_count=1, max_wait_time=10)
            assert len(messages) == 1
            assert messages[0].session_id == "svc-1"
            assert str(messages[0]) == "svc-1 update"
            receiver.complete_message(messages[0])
