"""Integration tests for the Neo4j connection lifecycle, health and recovery (G14, DEC-012).

They run against a real Neo4j. NEO4J_URI is required and has no default, so the tests can never
reach the shared diucs-local stack by accident. NEO4J_CONTAINER names the Docker container of that
same isolated Neo4j: the recovery tests stop and start it. Start an isolated stack first (see the
G14 evidence file) and set both variables. Each test that stops the container starts it again in
a finally block.

Every test writes only nodes with the label G14Probe, and removes them before it runs.
"""

import asyncio
import logging
import os
import subprocess
import time
from collections.abc import AsyncIterator
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

NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "diucs-test-password")
WRONG_PASSWORD = "g14-wrong-password"
PROBE_LABEL = "G14Probe"
# Sample values from the specs. Patient-like values must never reach the logs.
PATIENT_LIKE = "Jane Example"
RECOVERY_DEADLINE_S = 60.0
RETRYABLE_ERRORS = (DriverError, Neo4jError)
HEALTH_TIMEOUT_MARGIN_S = 2.0

log = logging.getLogger(__name__)


def _neo4j_uri() -> str:
    uri = os.environ.get("NEO4J_URI")
    if not uri:
        pytest.fail(
            "NEO4J_URI is not set. These tests need an isolated Neo4j and never default to the "
            "shared diucs-local stack on bolt://localhost:7687. See the G14 evidence file.",
            pytrace=False,
        )
    return uri


def _container_name() -> str:
    name = os.environ.get("NEO4J_CONTAINER")
    if not name:
        pytest.fail(
            "NEO4J_CONTAINER is not set. Name the Docker container of the isolated Neo4j "
            "(diucs-g14-neo4j-1 in the G14 evidence) so the recovery tests can stop and start it.",
            pytrace=False,
        )
    return name


def _docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True, text=True, timeout=180)


def _endpoint() -> tuple[str, int]:
    parts = urlsplit(_neo4j_uri())
    assert parts.hostname is not None and parts.port is not None
    return parts.hostname, parts.port


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


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[Neo4jConnection]:
    connection = Neo4jConnection(_neo4j_uri(), NEO4J_USER, NEO4J_PASSWORD)
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


async def test_bad_password_fails_naming_host_and_port_but_not_the_password() -> None:
    host, port = _endpoint()
    bad = Neo4jConnection(_neo4j_uri(), NEO4J_USER, WRONG_PASSWORD)
    with pytest.raises(Neo4jConnectionError) as failure:
        await bad.open()
    message = str(failure.value)
    assert host in message
    assert str(port) in message
    assert WRONG_PASSWORD not in message
    assert NEO4J_PASSWORD not in message
    await bad.close()


async def test_close_is_a_no_op_the_second_time_and_later_use_raises_a_clear_error() -> None:
    own = Neo4jConnection(_neo4j_uri(), NEO4J_USER, NEO4J_PASSWORD)
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


async def test_in_flight_write_fails_retryably_leaves_no_partial_write_and_recovers(
    conn: Neo4jConnection,
) -> None:
    container = _container_name()
    started = asyncio.Event()

    async def long_write(tx: AsyncManagedTransaction) -> None:
        await tx.run(f"CREATE (:{PROBE_LABEL} {{name: 'inflight'}})")
        started.set()
        while True:
            await _ping(tx)
            await asyncio.sleep(0.2)

    in_flight = asyncio.create_task(conn.run_write(long_write))
    await asyncio.wait_for(started.wait(), timeout=30)

    _docker("stop", container)
    stopped_at = time.monotonic()
    with pytest.raises(RETRYABLE_ERRORS) as failure:
        await asyncio.wait_for(in_flight, timeout=RECOVERY_DEADLINE_S * 2)
    assert failure.value.is_retryable()
    log.info("G14 in-flight write failed %.1f s after stop", time.monotonic() - stopped_at)

    restarted_at = time.monotonic()
    _docker("start", container)
    attempts = 0
    while True:
        attempts += 1
        try:
            rows = await conn.run_read(_ping)
            break
        except RETRYABLE_ERRORS:
            if time.monotonic() - restarted_at > RECOVERY_DEADLINE_S:
                raise
            await asyncio.sleep(1)
    recovered_in = time.monotonic() - restarted_at
    log.info("G14 first successful call %.1f s after restart, %d attempts", recovered_in, attempts)

    assert rows == [{"ok": 1}]
    assert recovered_in <= RECOVERY_DEADLINE_S
    # DEC-012: the failed transaction left no partial write behind.
    assert await _count_probes(conn) == 0
    health = await neo4j_health(conn, timeout=10)
    assert health.status is HealthStatus.OK


async def test_health_reports_degraded_while_neo4j_is_stopped_and_never_raises(
    conn: Neo4jConnection,
) -> None:
    container = _container_name()
    _docker("stop", container)
    try:
        started = time.monotonic()
        health = await neo4j_health(conn, timeout=5)
        elapsed = time.monotonic() - started
        assert health.status is HealthStatus.DEGRADED
        assert health.reason
        # The timeout must bound the check. Without it the driver's retries take about 30 s.
        assert elapsed <= 5 + HEALTH_TIMEOUT_MARGIN_S, f"health took {elapsed:.1f} s"
    finally:
        _docker("start", container)
        await _wait_until_healthy(conn)


async def test_health_of_an_unopened_connection_is_degraded_and_never_raises() -> None:
    unopened = Neo4jConnection(_neo4j_uri(), NEO4J_USER, NEO4J_PASSWORD)
    health = await neo4j_health(unopened, timeout=5)
    assert health.status is HealthStatus.DEGRADED
    assert health.reason


async def test_closing_the_connection_leaves_zero_open_pool_connections() -> None:
    connection = Neo4jConnection(_neo4j_uri(), NEO4J_USER, NEO4J_PASSWORD)
    await connection.open()
    await asyncio.gather(*(connection.run_read(_ping) for _ in range(3)))
    assert connection.pool_connection_count() >= 1
    await connection.close()
    assert connection.pool_connection_count() == 0


async def test_the_pool_uses_the_dec_012_defaults_in_the_installed_driver() -> None:
    connection = Neo4jConnection(_neo4j_uri(), NEO4J_USER, NEO4J_PASSWORD)
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
        pool = driver._pool.pool_config  # type: ignore[attr-defined]
        assert pool.max_connection_lifetime == 1800.0
        assert pool.liveness_check_timeout == 30.0
        assert pool.max_connection_pool_size == 50
        workspace = driver._default_workspace_config  # type: ignore[attr-defined]
        assert workspace.connection_acquisition_timeout == 30.0
    finally:
        await connection.close()


async def test_logs_for_every_path_carry_no_password_and_no_patient_like_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # DEBUG is the most a service could log. The driver's Bolt logger writes RUN and LOGON
    # messages at DEBUG, so the password and the query parameters must stay out of it.
    caplog.set_level(logging.DEBUG)
    uri = _neo4j_uri()

    bad = Neo4jConnection(uri, NEO4J_USER, WRONG_PASSWORD)
    with pytest.raises(Neo4jConnectionError):
        await bad.open()
    await bad.close()

    good = Neo4jConnection(uri, NEO4J_USER, NEO4J_PASSWORD)
    await good.open()
    try:

        async def write(tx: AsyncManagedTransaction) -> None:
            await tx.run(f"CREATE (:{PROBE_LABEL} {{name: $name}})", name=PATIENT_LIKE)

        await good.run_write(write)
        await good.run_read(_ping)
        await _delete_probes(good)
    finally:
        await good.close()

    assert NEO4J_PASSWORD not in caplog.text
    assert WRONG_PASSWORD not in caplog.text
    assert PATIENT_LIKE not in caplog.text


async def test_container_startup_opens_the_connection_and_shutdown_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_URI", _neo4j_uri())
    monkeypatch.setenv("DIUCS_NEO4J_USER", NEO4J_USER)
    monkeypatch.setenv("DIUCS_NEO4J_PASSWORD", NEO4J_PASSWORD)
    container = build(Settings())

    await container.startup()
    assert await container.neo4j.run_read(_ping) == [{"ok": 1}]
    await container.shutdown()
    assert container.neo4j.pool_connection_count() == 0
    with pytest.raises(Neo4jConnectionError, match="closed"):
        await container.neo4j.run_read(_ping)


async def test_container_startup_refuses_to_start_when_neo4j_is_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_URI", _neo4j_uri())
    monkeypatch.setenv("DIUCS_NEO4J_USER", NEO4J_USER)
    monkeypatch.setenv("DIUCS_NEO4J_PASSWORD", WRONG_PASSWORD)
    container = build(Settings())

    with pytest.raises(Neo4jConnectionError) as failure:
        await container.startup()
    assert WRONG_PASSWORD not in str(failure.value)
    await container.shutdown()


async def test_non_default_neo4j_settings_reach_the_built_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_URI", _neo4j_uri())
    monkeypatch.setenv("DIUCS_NEO4J_USER", NEO4J_USER)
    monkeypatch.setenv("DIUCS_NEO4J_PASSWORD", NEO4J_PASSWORD)
    monkeypatch.setenv("DIUCS_NEO4J_MAX_CONNECTION_LIFETIME_S", "600")
    monkeypatch.setenv("DIUCS_NEO4J_LIVENESS_CHECK_TIMEOUT_S", "5")
    monkeypatch.setenv("DIUCS_NEO4J_CONNECTION_ACQUISITION_TIMEOUT_S", "2")
    monkeypatch.setenv("DIUCS_NEO4J_MAX_CONNECTION_POOL_SIZE", "7")
    container = build(Settings())
    await container.startup()
    try:
        driver = container.neo4j._driver
        assert driver is not None
        pool = driver._pool.pool_config  # type: ignore[attr-defined]
        assert pool.max_connection_lifetime == 600.0
        assert pool.liveness_check_timeout == 5.0
        assert pool.max_connection_pool_size == 7
        workspace = driver._default_workspace_config  # type: ignore[attr-defined]
        assert workspace.connection_acquisition_timeout == 2.0
    finally:
        await container.shutdown()
