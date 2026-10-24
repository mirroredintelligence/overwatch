"""Neo4j test harness (F10, DEC-008, DEC-012).

start_throwaway_neo4j runs one Neo4j container per pytest session, on a free localhost port, with a
unique name, and stop_throwaway_neo4j removes it. Nothing here reads a shared stack: the container
is ours alone and its port is picked by the OS.

Helpers run in fresh sessions: a write commits in one session and a read sees it only from another
session, so each round trip proves what was really stored.
"""

import asyncio
import os
import re
import secrets
import socket
import subprocess
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import ServiceUnavailable

from diucs.adapters.outbound.graph_store.driver import create_driver

START_MESSAGE = (
    "Neo4j is not running. Start it with: docker compose -f infra/docker-compose.yml up -d neo4j"
)
# The image is the one pinned in infra/docker-compose.yml. Keep the two in step.
NEO4J_IMAGE = "neo4j:5.26.32-community"
NEO4J_BOLT_PORT = 7687
CONTAINER_READY_TIMEOUT_S = 120.0
DELETE_BATCH = 10_000
_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Neo4jNotRunning(Exception):
    """Raised when the Neo4j instance cannot be reached in time."""


@dataclass(frozen=True, slots=True)
class ThrowawayNeo4j:
    name: str
    uri: str
    user: str
    password: str


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _docker(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def _ready(name: str, password: str) -> bool:
    result = _docker(
        "exec", name, "cypher-shell", "-u", "neo4j", "-p", password, "RETURN 1", timeout=20.0
    )
    return result.returncode == 0


def new_container_password() -> str:
    """A random password for one container: 128 bits as hex. Hex never starts with a dash, which
    neo4j-admin would read as an option and refuse (the container then exits at once)."""
    return secrets.token_hex(16)


def start_throwaway_neo4j() -> ThrowawayNeo4j:
    """Start a container and wait until cypher-shell inside it answers. Blocks for up to
    CONTAINER_READY_TIMEOUT_S, because a Neo4j container takes tens of seconds to start."""
    name = f"diucs-test-neo4j-{uuid.uuid4().hex[:12]}"
    port = _free_port()
    password = new_container_password()
    try:
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
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Neo4jNotRunning(
            f"Docker is not available, so the Neo4j test harness cannot start its container: "
            f"{error}"
        ) from error
    if started.returncode != 0:
        first_line = (started.stderr.strip().splitlines() or ["no output"])[0]
        raise Neo4jNotRunning(
            f"Docker could not start the Neo4j test container (is Docker running?): {first_line}"
        )
    container = ThrowawayNeo4j(
        name=name, uri=f"bolt://127.0.0.1:{port}", user="neo4j", password=password
    )
    try:
        wait_until_ready(container)
    except Neo4jNotRunning:
        stop_throwaway_neo4j(container)
        raise
    return container


def stop_container(container: ThrowawayNeo4j) -> None:
    """Stop the running container. It stays on disk, so start_container can bring it back."""
    result = _docker("stop", container.name)
    if result.returncode != 0:
        raise RuntimeError(f"Could not stop the Neo4j test container {container.name}.")


def start_container(container: ThrowawayNeo4j) -> None:
    """Start a stopped container on the same port, with the same data. Call wait_until_ready
    before using it, because `docker start` returns before Neo4j accepts connections (lesson L7)."""
    result = _docker("start", container.name)
    if result.returncode != 0:
        raise RuntimeError(f"Could not start the Neo4j test container {container.name}.")


def wait_until_ready(container: ThrowawayNeo4j) -> None:
    """Block until cypher-shell inside the container answers, for up to CONTAINER_READY_TIMEOUT_S.
    Raises Neo4jNotRunning if it does not. The caller decides whether to remove the container."""
    deadline = time.monotonic() + CONTAINER_READY_TIMEOUT_S
    while not _ready(container.name, container.password):
        if time.monotonic() > deadline:
            raise Neo4jNotRunning(
                f"The Neo4j test container {container.name} did not answer within "
                f"{CONTAINER_READY_TIMEOUT_S:.0f} seconds."
            )
        time.sleep(1.0)


def stop_throwaway_neo4j(container: ThrowawayNeo4j) -> None:
    result = _docker("rm", "-f", container.name)
    if result.returncode != 0:
        raise RuntimeError(f"Could not remove the Neo4j test container {container.name}.")


@asynccontextmanager
async def throwaway_driver() -> AsyncIterator[tuple[ThrowawayNeo4j, AsyncDriver]]:
    """Start a container, connect to it, and yield (container, driver). The driver is closed and
    the container removed on exit, including when connecting fails."""
    container = start_throwaway_neo4j()
    try:
        driver = await connect_or_fail(container.uri, container.user, container.password)
        try:
            yield container, driver
        finally:
            await driver.close()
    finally:
        stop_throwaway_neo4j(container)


def apply_session_env(container: ThrowawayNeo4j) -> None:
    """Point the process environment at the throwaway container. Any NEO4J_URI already set in the
    shell is overwritten (DEC-013)."""
    os.environ["NEO4J_URI"] = container.uri
    os.environ["NEO4J_USER"] = container.user
    os.environ["NEO4J_PASSWORD"] = container.password


async def connect_or_fail(uri: str, user: str, password: str, timeout_s: float = 5) -> AsyncDriver:
    """Return a driver whose server answers within timeout_s, or raise Neo4jNotRunning."""
    driver = create_driver(uri, user, password)
    try:
        await asyncio.wait_for(driver.verify_connectivity(), timeout=timeout_s)
    except (ServiceUnavailable, OSError, TimeoutError) as error:
        await driver.close()
        raise Neo4jNotRunning(START_MESSAGE) from error
    return driver


async def write_tx[T](
    driver: AsyncDriver, fn: Callable[[AsyncManagedTransaction], Awaitable[T]]
) -> T:
    async with driver.session() as session:
        return await session.execute_write(fn)


async def read_tx[T](
    driver: AsyncDriver, fn: Callable[[AsyncManagedTransaction], Awaitable[T]]
) -> T:
    async with driver.session() as session:
        return await session.execute_read(fn)


def _checked_name(name: str) -> str:
    if not _SAFE_NAME.match(name):
        raise ValueError(f"not a safe Neo4j label or property name: {name!r}")
    return name


async def count_nodes(driver: AsyncDriver, label: str) -> int:
    query = f"MATCH (n:`{_checked_name(label)}`) RETURN count(n) AS total"

    async def work(tx: AsyncManagedTransaction) -> int:
        record = await (await tx.run(query)).single()
        assert record is not None
        return int(record["total"])

    return await read_tx(driver, work)


async def node_props(driver: AsyncDriver, label: str, **match: Any) -> dict[str, Any]:
    """Properties of the single node with this label and these property values. Fails unless
    exactly one node matches, and the message names how many did."""
    conditions = " AND ".join(f"n.`{_checked_name(key)}` = ${key}" for key in match)
    where = f" WHERE {conditions}" if conditions else ""
    query = f"MATCH (n:`{_checked_name(label)}`){where} RETURN properties(n) AS props"

    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run(query, **match)).data()

    rows = await read_tx(driver, work)
    if len(rows) != 1:
        raise AssertionError(
            f"expected exactly 1 {label} node matching {match!r}, found {len(rows)}"
        )
    props: dict[str, Any] = rows[0]["props"]
    return props


async def wipe(driver: AsyncDriver) -> None:
    """Delete every node and relationship, in batches. :Migration nodes stay, and so do
    constraints and indexes (deleting nodes does not touch them)."""
    query = (
        f"MATCH (n) WHERE NOT n:Migration WITH n LIMIT {DELETE_BATCH} "
        "DETACH DELETE n RETURN count(*) AS deleted"
    )

    async def batch(tx: AsyncManagedTransaction) -> int:
        record = await (await tx.run(query)).single()
        assert record is not None
        return int(record["deleted"])

    while await write_tx(driver, batch):
        pass
