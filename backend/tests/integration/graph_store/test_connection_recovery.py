"""Integration tests for the Neo4j connection lifecycle, health and recovery (G14, DEC-012).

Two kinds of throwaway Neo4j are used. Both are removed when the session ends.

- The F10 harness (`harness_driver`, DEC-008, lesson L11) supplies the container for every test
  that does not stop Neo4j. Its NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD are set for the session,
  and `clean_graph` wipes it before each test.
- The recovery tests stop and start Neo4j, so they need a container that survives a stop. The
  harness starts its container with `docker run --rm`, which removes it on stop. These tests start
  their own container without --rm (`recovery_neo4j`), with the harness's image, port and readiness
  helpers. Moving them onto `harness_driver` needs a restartable mode in the harness. That is a
  named follow-up (see the G14 evidence file).

Every test writes only nodes with the label G14Probe, and removes them before it runs.
"""

import asyncio
import logging
import os
import secrets
import subprocess
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction, AsyncSession
from neo4j.exceptions import DriverError, Neo4jError

from diucs.adapters.outbound.graph_store.connection import (
    Neo4jConnection,
    Neo4jConnectionError,
    Neo4jPoolOptions,
)
from diucs.adapters.outbound.graph_store.health import HealthStatus, neo4j_health
from diucs.bootstrap.container import build
from diucs.bootstrap.settings import Settings
from tests.support.neo4j import (
    CONTAINER_READY_TIMEOUT_S,
    NEO4J_BOLT_PORT,
    NEO4J_IMAGE,
    ThrowawayNeo4j,
    _docker,
    _free_port,
    _ready,
    stop_throwaway_neo4j,
)

# Every test here runs on the session loop, because the harness driver and the recovery container
# are session-scoped (lesson L11).
pytestmark = pytest.mark.asyncio(loop_scope="session")

WRONG_PASSWORD = "g14-wrong-password"
PROBE_LABEL = "G14Probe"
# Sample values from the specs. Patient-like values must never reach the logs.
PATIENT_LIKE = "Jane Example"
RECOVERY_DEADLINE_S = 60.0
HEALTH_TIMEOUT_MARGIN_S = 2.0
RETRYABLE_ERRORS = (DriverError, Neo4jError)
UNREACHABLE_URI = "bolt://localhost:1"

log = logging.getLogger(__name__)


def _harness_settings() -> tuple[str, str, str]:
    """The harness sets these for the session. A test must depend on harness_driver first."""
    return (
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USER"],
        os.environ["NEO4J_PASSWORD"],
    )


async def _ping(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
    result = await tx.run("RETURN 1 AS ok")
    return await result.data()


async def _count_probes(conn: Neo4jConnection) -> int:
    async def work(tx: AsyncManagedTransaction) -> int:
        result = await tx.run(f"MATCH (n:{PROBE_LABEL}) RETURN count(n) AS c")
        record = await result.single()
        assert record is not None
        count: int = record["c"]
        return count

    return await conn.run_read(work)


async def _delete_probes(conn: Neo4jConnection) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(f"MATCH (n:{PROBE_LABEL}) DETACH DELETE n")

    await conn.run_write(work)


def _docker_checked(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=180)


def _start_restartable_neo4j() -> ThrowawayNeo4j:
    """The harness's image, without --rm, so the container can be stopped and started. It has a
    random localhost port, a unique name and a generated password. The fixture removes it."""
    name = f"diucs-test-neo4j-restart-{uuid.uuid4().hex[:12]}"
    port = _free_port()
    password = secrets.token_urlsafe(16)
    started = _docker(
        "run",
        "-d",
        "--name",
        name,
        "--label",
        "diucs-test=true",
        "-p",
        f"127.0.0.1:{port}:{NEO4J_BOLT_PORT}",
        "-e",
        f"NEO4J_AUTH=neo4j/{password}",
        NEO4J_IMAGE,
    )
    if started.returncode != 0:
        stop_throwaway_neo4j(ThrowawayNeo4j(name, "", "", ""))
        pytest.fail(f"could not start the restartable Neo4j container: {started.stderr.strip()}")
    deadline = time.monotonic() + CONTAINER_READY_TIMEOUT_S
    while not _ready(name, password):
        if time.monotonic() > deadline:
            stop_throwaway_neo4j(ThrowawayNeo4j(name, "", "", ""))
            pytest.fail(f"restartable Neo4j {name} did not answer in time")
        time.sleep(1.0)
    return ThrowawayNeo4j(
        name=name, uri=f"bolt://127.0.0.1:{port}", user="neo4j", password=password
    )


@pytest.fixture(scope="session")
def recovery_neo4j() -> Iterator[ThrowawayNeo4j]:
    """One restartable throwaway Neo4j for the recovery tests. Removed when the session ends."""
    container = _start_restartable_neo4j()
    try:
        yield container
    finally:
        stop_throwaway_neo4j(container)


@pytest_asyncio.fixture(loop_scope="session")
async def conn(harness_driver: AsyncDriver) -> AsyncIterator[Neo4jConnection]:
    uri, user, password = _harness_settings()
    connection = Neo4jConnection(uri, user, password)
    await connection.open()
    await _delete_probes(connection)
    try:
        yield connection
    finally:
        await _delete_probes(connection)
        await connection.close()


@pytest_asyncio.fixture(loop_scope="session")
async def recovery_conn(recovery_neo4j: ThrowawayNeo4j) -> AsyncIterator[Neo4jConnection]:
    connection = Neo4jConnection(recovery_neo4j.uri, recovery_neo4j.user, recovery_neo4j.password)
    await connection.open()
    await _delete_probes(connection)
    try:
        yield connection
    finally:
        await _delete_probes(connection)
        await connection.close()


async def _wait_until_healthy(conn: Neo4jConnection) -> None:
    deadline = time.monotonic() + RECOVERY_DEADLINE_S
    while True:
        health = await neo4j_health(conn, timeout=5)
        if health.status is HealthStatus.OK:
            return
        if time.monotonic() > deadline:
            pytest.fail(f"Neo4j did not become healthy within {RECOVERY_DEADLINE_S:g} s")
        await asyncio.sleep(1)


async def test_bad_password_fails_naming_host_and_port_but_not_the_password(
    harness_driver: AsyncDriver,
) -> None:
    uri, user, password = _harness_settings()
    parts = urlsplit(uri)
    bad = Neo4jConnection(uri, user, WRONG_PASSWORD)
    with pytest.raises(Neo4jConnectionError) as failure:
        await bad.open()
    message = str(failure.value)
    assert parts.hostname is not None and parts.hostname in message
    assert parts.port is not None and str(parts.port) in message
    assert WRONG_PASSWORD not in message
    assert password not in message
    await bad.close()


async def test_close_is_a_no_op_the_second_time_and_later_use_raises_a_clear_error(
    harness_driver: AsyncDriver,
) -> None:
    uri, user, password = _harness_settings()
    own = Neo4jConnection(uri, user, password)
    await own.open()
    await own.close()
    await own.close()
    with pytest.raises(Neo4jConnectionError, match="closed"):
        await own.run_read(_ping)
    with pytest.raises(Neo4jConnectionError, match="closed"):
        async with own.session():
            pass
    with pytest.raises(Neo4jConnectionError, match="closed"):
        await own.open()


async def test_every_real_driver_session_is_closed_after_success_and_after_an_exception(
    conn: Neo4jConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Spy on the driver's own sessions and on their close(), not on the adapter's counter.
    opened: list[AsyncSession] = []
    closed: list[AsyncSession] = []
    real_session = AsyncDriver.session
    real_close = AsyncSession.close

    def spy_session(self: AsyncDriver, **config: Any) -> AsyncSession:
        session = real_session(self, **config)
        opened.append(session)
        return session

    async def spy_close(self: AsyncSession) -> None:
        closed.append(self)
        await real_close(self)

    monkeypatch.setattr(AsyncDriver, "session", spy_session)
    monkeypatch.setattr(AsyncSession, "close", spy_close)

    assert await conn.run_read(_ping) == [{"ok": 1}]

    async def fails(tx: AsyncManagedTransaction) -> None:
        await tx.run("RETURN 1")
        raise ValueError("G14 deliberate failure inside the unit of work")

    with pytest.raises(ValueError, match="deliberate"):
        await conn.run_read(fails)

    assert len(opened) >= 2
    assert all(any(c is s for c in closed) for s in opened)
    assert conn.open_session_count == 0


async def test_a_write_that_raises_mid_transaction_leaves_no_node_behind(
    conn: Neo4jConnection,
) -> None:
    async def half_write(tx: AsyncManagedTransaction) -> None:
        await tx.run(f"CREATE (:{PROBE_LABEL} {{name: 'half'}})")
        raise RuntimeError("G14 deliberate mid-transaction failure")

    with pytest.raises(RuntimeError, match="deliberate"):
        await conn.run_write(half_write)
    assert await _count_probes(conn) == 0

    async def whole_write(tx: AsyncManagedTransaction) -> None:
        await tx.run(f"CREATE (:{PROBE_LABEL} {{name: 'whole'}})")

    await conn.run_write(whole_write)
    assert await _count_probes(conn) == 1


async def test_in_flight_write_fails_retryably_and_the_service_recovers(
    recovery_conn: Neo4jConnection, recovery_neo4j: ThrowawayNeo4j
) -> None:
    name = recovery_neo4j.name
    started = asyncio.Event()

    async def long_write(tx: AsyncManagedTransaction) -> None:
        await tx.run(f"CREATE (:{PROBE_LABEL} {{name: 'inflight'}})")
        started.set()
        while True:
            await _ping(tx)
            await asyncio.sleep(0.2)

    in_flight = asyncio.create_task(recovery_conn.run_write(long_write))
    try:
        await asyncio.wait_for(started.wait(), timeout=30)

        _docker_checked("stop", name)
        stopped_at = time.monotonic()
        with pytest.raises(RETRYABLE_ERRORS) as failure:
            await asyncio.wait_for(in_flight, timeout=RECOVERY_DEADLINE_S * 2)
        assert failure.value.is_retryable()
        log.info("G14 in-flight write failed %.1f s after stop", time.monotonic() - stopped_at)

        restarted_at = time.monotonic()
        _docker_checked("start", name)
        attempts = 0
        while True:
            attempts += 1
            try:
                rows = await recovery_conn.run_read(_ping)
                break
            except RETRYABLE_ERRORS:
                if time.monotonic() - restarted_at > RECOVERY_DEADLINE_S:
                    raise
                await asyncio.sleep(1)
        recovered_in = time.monotonic() - restarted_at
        log.info(
            "G14 first successful call %.1f s after restart, %d attempts", recovered_in, attempts
        )

        assert rows == [{"ok": 1}]
        assert recovered_in <= RECOVERY_DEADLINE_S
        # A weak check only: the server discards uncommitted work during an outage, so this
        # cannot fail on its own. The rollback test is the partial-write proof.
        assert await _count_probes(recovery_conn) == 0
        health = await neo4j_health(recovery_conn, timeout=10)
        assert health.status is HealthStatus.OK
    finally:
        if not in_flight.done():
            in_flight.cancel()
            await asyncio.gather(in_flight, return_exceptions=True)
        _docker_checked("start", name)
        await _wait_until_healthy(recovery_conn)


async def test_health_reports_degraded_within_the_timeout_while_stopped_and_never_raises(
    recovery_conn: Neo4jConnection, recovery_neo4j: ThrowawayNeo4j
) -> None:
    name = recovery_neo4j.name
    try:
        _docker_checked("stop", name)
        started = time.monotonic()
        health = await neo4j_health(recovery_conn, timeout=5)
        elapsed = time.monotonic() - started
        assert health.status is HealthStatus.DEGRADED
        assert health.reason
        # The timeout must bound the check. Without it the driver's retries take about 30 s.
        assert elapsed <= 5 + HEALTH_TIMEOUT_MARGIN_S, f"health took {elapsed:.1f} s"
    finally:
        _docker_checked("start", name)
        await _wait_until_healthy(recovery_conn)


async def test_health_of_an_unopened_connection_is_degraded_and_never_raises() -> None:
    unopened = Neo4jConnection(UNREACHABLE_URI, "neo4j", "unused")
    health = await neo4j_health(unopened, timeout=5)
    assert health.status is HealthStatus.DEGRADED
    assert health.reason


async def test_closing_the_connection_leaves_zero_open_pool_connections(
    harness_driver: AsyncDriver,
) -> None:
    uri, user, password = _harness_settings()
    connection = Neo4jConnection(uri, user, password)
    await connection.open()
    await asyncio.gather(*(connection.run_read(_ping) for _ in range(3)))
    assert connection.pool_connection_count() >= 1
    await connection.close()
    assert connection.pool_connection_count() == 0


async def test_the_pool_uses_the_dec_012_defaults_in_the_installed_driver(
    harness_driver: AsyncDriver,
) -> None:
    uri, user, password = _harness_settings()
    connection = Neo4jConnection(uri, user, password)
    assert connection.pool_options == Neo4jPoolOptions(
        max_connection_lifetime=1800.0,
        liveness_check_timeout=30.0,
        connection_acquisition_timeout=30.0,
        max_connection_pool_size=50,
    )
    await connection.open()
    try:
        # The option names reach the installed driver (neo4j 6.4.1) and take effect there.
        driver = connection._driver
        assert driver is not None
        pool = driver._pool.pool_config
        assert pool.max_connection_lifetime == 1800.0
        assert pool.liveness_check_timeout == 30.0
        assert pool.max_connection_pool_size == 50
        workspace = driver._default_workspace_config
        assert workspace.connection_acquisition_timeout == 30.0
    finally:
        await connection.close()


async def test_logs_for_every_path_carry_no_password_and_no_patient_like_value(
    harness_driver: AsyncDriver, caplog: pytest.LogCaptureFixture
) -> None:
    # DEBUG is the most a service could log. The driver's Bolt logger writes RUN and LOGON
    # messages at DEBUG, so the password and the query parameters must stay out of it.
    caplog.set_level(logging.DEBUG)
    uri, user, password = _harness_settings()

    bad = Neo4jConnection(uri, user, WRONG_PASSWORD)
    with pytest.raises(Neo4jConnectionError):
        await bad.open()
    await bad.close()

    good = Neo4jConnection(uri, user, password)
    await good.open()
    try:

        async def write(tx: AsyncManagedTransaction) -> None:
            await tx.run(f"CREATE (:{PROBE_LABEL} {{name: $name}})", name=PATIENT_LIKE)

        await good.run_write(write)
        await good.run_read(_ping)
        await _delete_probes(good)
    finally:
        await good.close()

    assert password not in caplog.text
    assert WRONG_PASSWORD not in caplog.text
    assert PATIENT_LIKE not in caplog.text


async def test_container_startup_opens_the_connection_and_shutdown_closes_it(
    harness_driver: AsyncDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    uri, user, password = _harness_settings()
    monkeypatch.setenv("DIUCS_NEO4J_URI", uri)
    monkeypatch.setenv("DIUCS_NEO4J_USER", user)
    monkeypatch.setenv("DIUCS_NEO4J_PASSWORD", password)
    container = build(Settings())

    await container.startup()
    assert await container.neo4j.run_read(_ping) == [{"ok": 1}]
    await container.shutdown()
    assert container.neo4j.pool_connection_count() == 0
    with pytest.raises(Neo4jConnectionError, match="closed"):
        await container.neo4j.run_read(_ping)


async def test_container_startup_refuses_to_start_when_neo4j_is_wrong(
    harness_driver: AsyncDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    uri, user, _ = _harness_settings()
    monkeypatch.setenv("DIUCS_NEO4J_URI", uri)
    monkeypatch.setenv("DIUCS_NEO4J_USER", user)
    monkeypatch.setenv("DIUCS_NEO4J_PASSWORD", WRONG_PASSWORD)
    container = build(Settings())

    with pytest.raises(Neo4jConnectionError) as failure:
        await container.startup()
    assert WRONG_PASSWORD not in str(failure.value)
    await container.shutdown()


async def test_non_default_neo4j_settings_reach_the_built_driver(
    harness_driver: AsyncDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    uri, user, password = _harness_settings()
    monkeypatch.setenv("DIUCS_NEO4J_URI", uri)
    monkeypatch.setenv("DIUCS_NEO4J_USER", user)
    monkeypatch.setenv("DIUCS_NEO4J_PASSWORD", password)
    monkeypatch.setenv("DIUCS_NEO4J_MAX_CONNECTION_LIFETIME_S", "600")
    monkeypatch.setenv("DIUCS_NEO4J_LIVENESS_CHECK_TIMEOUT_S", "5")
    monkeypatch.setenv("DIUCS_NEO4J_CONNECTION_ACQUISITION_TIMEOUT_S", "2")
    monkeypatch.setenv("DIUCS_NEO4J_MAX_CONNECTION_POOL_SIZE", "7")
    container = build(Settings())
    await container.startup()
    try:
        driver = container.neo4j._driver
        assert driver is not None
        pool = driver._pool.pool_config
        assert pool.max_connection_lifetime == 600.0
        assert pool.liveness_check_timeout == 5.0
        assert pool.max_connection_pool_size == 7
        workspace = driver._default_workspace_config
        assert workspace.connection_acquisition_timeout == 2.0
    finally:
        await container.shutdown()
