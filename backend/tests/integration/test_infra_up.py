"""Smoke tests for the local Docker services in infra/ (F04).

They open their own connections to the services that
`docker compose -f infra/docker-compose.yml up -d --wait` starts. They are not the shared
harness (that arrives with F10), and they do not start containers: DEC-008 gives the test
suite its own throwaway Neo4j, while this file proves the local compose stack itself.

Neo4j follows DEC-012 with no exception: one AsyncDriver for the module, created by the fixture and
closed at the end. Each test that writes or reads uses fresh sessions on that driver.
"""

import json
import os
import subprocess
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession
from redis.asyncio import Redis

# The compose stack of the owner: one set of ports and fixed ids, so these tests never share the
# machine with another run (TEN-034).
pytestmark = [pytest.mark.infra, pytest.mark.exclusive]

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
COMPOSE_FILE = Path(__file__).resolve().parents[3] / "infra" / "docker-compose.yml"
EXPECTED_SERVICES = {
    "neo4j",
    "redis",
    "servicebus-sql",
    "servicebus-emulator",
    "servicebus-ready",
}


def _driver() -> AsyncDriver:
    return AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


async def _single_value(session: AsyncSession, query: str, key: str) -> object:
    result = await session.run(query)
    record = await result.single()
    assert record is not None
    return record[key]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def neo4j_driver() -> AsyncIterator[AsyncDriver]:
    """The module's one Neo4j driver (DEC-012): created once, closed at the end."""
    driver = _driver()
    try:
        yield driver
    finally:
        await driver.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_neo4j_answers_a_query(neo4j_driver: AsyncDriver) -> None:
    async with neo4j_driver.session() as session:
        ok = await _single_value(session, "RETURN 1 AS ok", "ok")
    assert ok == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_neo4j_keeps_a_node_between_sessions(neo4j_driver: AsyncDriver) -> None:
    # DEC-012: one driver, so persistence is proved across sessions on that driver, not across
    # drivers. The write commits in its own session, and the read uses a fresh session.
    async with neo4j_driver.session() as session:
        result = await session.run("CREATE (:InfraProbe {id: 'p1'})")
        await result.consume()
    try:
        async with neo4j_driver.session() as session:
            count = await _single_value(
                session,
                "MATCH (p:InfraProbe {id: 'p1'}) RETURN count(p) AS n",
                "n",
            )
        assert count == 1
    finally:
        async with neo4j_driver.session() as session:
            cleanup = await session.run("MATCH (p:InfraProbe {id: 'p1'}) DELETE p")
            await cleanup.consume()


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


def _compose_ps() -> list[dict[str, str]]:
    completed = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "ps", "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    text = completed.stdout.strip()
    if not text:
        return []
    if text.startswith("["):
        rows: list[dict[str, str]] = json.loads(text)
        return rows
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _compose_config_services() -> dict[str, dict[str, object]]:
    completed = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "config", "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    config: dict[str, dict[str, dict[str, object]]] = json.loads(completed.stdout)
    return config["services"]


def test_compose_config_defines_healthchecks_for_gated_services() -> None:
    # Reads the file, not the running containers: a removed healthcheck fails here even when the
    # container is still running. The emulator has no healthcheck; servicebus-ready gates it.
    services = _compose_config_services()
    for name in ("neo4j", "redis", "servicebus-ready"):
        assert "healthcheck" in services[name], f"{name} has no healthcheck in the compose file"


def test_every_compose_service_reports_healthy() -> None:
    # Fails if a healthcheck is removed from any service: that service then has no Health value.
    # The emulator image has no shell, so it has no healthcheck of its own. Its readiness is
    # reported by servicebus-ready, which is healthy only when the emulator /health returns 200.
    rows = _compose_ps()
    status = {row.get("Service", ""): (row.get("Health", ""), row.get("State", "")) for row in rows}
    assert set(status) == EXPECTED_SERVICES
    assert status["servicebus-emulator"][1] == "running"
    healthchecked = EXPECTED_SERVICES - {"servicebus-emulator"}
    not_healthy = {
        svc: status[svc] for svc in healthchecked if status[svc] != ("healthy", "running")
    }
    assert not_healthy == {}


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


def test_projection_queue_delivers_a_message_with_its_tenant_property() -> None:
    """TEN-055: the queue exists and carries the application property the apply step reads."""
    with ServiceBusClient.from_connection_string(SERVICEBUS_CONNECTION) as client:
        with client.get_queue_sender("projection.work") as sender:
            sender.send_messages(
                ServiceBusMessage(
                    "{}",
                    message_id=f"tenant-x:smoke-{uuid.uuid4().hex}",
                    application_properties={"tenantId": "tenant-x"},
                )
            )
        with client.get_queue_receiver("projection.work", max_wait_time=10) as receiver:
            messages = receiver.receive_messages(max_message_count=1, max_wait_time=10)
            assert len(messages) == 1
            assert messages[0].application_properties is not None
            assert messages[0].application_properties.get(b"tenantId") == b"tenant-x"
            receiver.complete_message(messages[0])


@pytest.mark.parametrize(
    ("topic", "session"),
    [
        ("capacity.events", "svc-net-1"),
        ("booking.events", None),
        ("criteria.events", None),
        ("registration.events", None),
    ],
)
def test_network_projector_subscription_receives_a_publish(topic: str, session: str | None) -> None:
    with ServiceBusClient.from_connection_string(SERVICEBUS_CONNECTION) as client:
        body = f"net-projector {uuid.uuid4().hex}"
        with client.get_topic_sender(topic) as sender:
            sender.send_messages(ServiceBusMessage(body, session_id=session))
        if session is None:
            receiver = client.get_subscription_receiver(
                topic, "network-projector", max_wait_time=10
            )
        else:
            receiver = client.get_subscription_receiver(
                topic, "network-projector", session_id=session, max_wait_time=10
            )
        with receiver:
            messages = receiver.receive_messages(max_message_count=5, max_wait_time=10)
            assert body in [str(m) for m in messages]
            for message in messages:
                receiver.complete_message(message)
