"""Neo4j test harness (F10, DEC-008, DEC-012, F10b: DEC-135).

start_throwaway_neo4j runs one Neo4j container per pytest session, on a free localhost port, with a
unique name, and stop_throwaway_neo4j removes it. Nothing here reads a shared stack: the container
is ours alone and its port is picked by the OS.

Load protection (DEC-135). Four agents running pytest at once, each with its own Neo4j, took the
machine to load 15 on 4 cores. So:

* One container at a time machine-wide. start_throwaway_neo4j takes an exclusive flock on
  /tmp/diucs-neo4j-harness.lock (environment DIUCS_NEO4J_LOCK overrides the path) and holds it until
  stop_throwaway_neo4j, or until the process dies (the operating system frees it). A second session
  waits up to DIUCS_NEO4J_LOCK_TIMEOUT seconds (default 3600), then fails naming the holder's pid.
  Since TEN-034 this lock matters only for private containers (owned mode, `own_neo4j`): runs on
  the shared Neo4j (tests/support/harness_mode.py) need no lock to queue on, and agents no longer
  wrap pytest in a manual flock.
* Memory limits. The container gets --memory (DIUCS_NEO4J_MEMORY, default 1g) and Neo4j heap
  (DIUCS_NEO4J_HEAP, 256m) and page cache (DIUCS_NEO4J_PAGECACHE, 128m) settings.
* Owner labels. The container is labelled with the owning pid, that process's start time and the
  host, so the reaper can tell a live run's container from a leaked one.
* Readiness is a Bolt check with the Python driver, not `docker exec cypher-shell`, which starts
  a JVM per probe. The image is checked, and pulled if missing, before the readiness clock starts
  (DIUCS_NEO4J_READY_TIMEOUT, default 120 s). A failure names its phase: lock, config, docker,
  image, start or ready.

Helpers run in fresh sessions: a write commits in one session and a read sees it only from another
session, so each round trip proves what was really stored.
"""

import asyncio
import logging
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
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from neo4j import AsyncDriver, AsyncManagedTransaction, GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from diucs.adapters.outbound.graph_store.driver import create_driver
from diucs.application.tenancy import (
    ScopeId,
    TenantNotBound,
    TenantParameterRefused,
    current_scope_or_none,
)
from tests.support import harness_lock
from tests.support.proc import (
    ProcessUnreadable,
    ascii_digits,
    boot_id,
    pid_namespace,
    process_start_marker,
)
from tests.support.scoped import scoped
from tests.support.watchdog import paused

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


class HarnessStartError(Neo4jNotRunning):
    """The harness failed in one named phase: lock, config, image, start or ready."""

    def __init__(self, phase: str, detail: str) -> None:
        super().__init__(f"Neo4j test harness failed in the {phase} phase: {detail}")
        self.phase = phase


OWNER_PID_LABEL = "diucs-test-owner-pid"
OWNER_START_LABEL = "diucs-test-owner-start"
OWNER_HOST_LABEL = "diucs-test-owner-host"
OWNER_NS_LABEL = "diucs-test-owner-pidns"
OWNER_BOOT_LABEL = "diucs-test-owner-boot"
# DEC-135: heap 256m and page cache 128m inside a 1g container; see the decision for the measured
# peak. A heavier test can raise them with the environment variables named in the module docstring.
DEFAULT_CONTAINER_MEMORY = "1g"
DEFAULT_HEAP = "256m"
DEFAULT_PAGECACHE = "128m"
MEMORY_ENV = "DIUCS_NEO4J_MEMORY"
HEAP_ENV = "DIUCS_NEO4J_HEAP"
PAGECACHE_ENV = "DIUCS_NEO4J_PAGECACHE"
READY_TIMEOUT_ENV = "DIUCS_NEO4J_READY_TIMEOUT"
IMAGE_PULL_TIMEOUT_S = 900.0
DOCKER_RUN_TIMEOUT_S = 120.0
_SIZE = re.compile(r"^[1-9][0-9]*[kKmMgG]$")
Probe = Callable[["ThrowawayNeo4j"], bool]


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


def new_container_password() -> str:
    """A random password for one container: 128 bits as hex. Hex never starts with a dash, which
    neo4j-admin would read as an option and refuse (the container then exits at once)."""
    return secrets.token_hex(16)


def owner_labels() -> dict[str, str]:
    """The labels that name this process as the owner of a container: pid, process start time, host,
    pid namespace and boot. Empty where the start time cannot be read (no /proc). The namespace and
    boot labels may be empty when they cannot be read; the reaper then cannot match the owner and
    judges it by the six-hour age (DEC-135 item 3)."""
    try:
        marker = process_start_marker(os.getpid())
    except ProcessUnreadable:
        return {}
    if marker is None:
        return {}
    return {
        OWNER_PID_LABEL: str(os.getpid()),
        OWNER_START_LABEL: marker,
        OWNER_HOST_LABEL: socket.gethostname(),
        OWNER_NS_LABEL: pid_namespace(),
        OWNER_BOOT_LABEL: boot_id(),
    }


def _size_from_environment(variable: str, default: str) -> str:
    value = os.environ.get(variable) or default
    if not _SIZE.match(value):
        raise HarnessStartError(
            "config", f"{variable} must be a size such as 1g or 2g, not {value!r}."
        )
    return value


def ready_timeout_s() -> float:
    value = os.environ.get(READY_TIMEOUT_ENV)
    if not value:
        return CONTAINER_READY_TIMEOUT_S
    try:
        seconds = float(value)
    except ValueError:
        seconds = 0.0
    if not seconds > 0:  # also refuses nan, which compares false with everything
        raise HarnessStartError("config", f"{READY_TIMEOUT_ENV} must be a number of seconds.")
    return seconds


def _memory_limits() -> tuple[str, str, str]:
    """Container memory, heap and page cache from the environment, checked up front."""
    return (
        _size_from_environment(MEMORY_ENV, DEFAULT_CONTAINER_MEMORY),
        _size_from_environment(HEAP_ENV, DEFAULT_HEAP),
        _size_from_environment(PAGECACHE_ENV, DEFAULT_PAGECACHE),
    )


def _run_arguments(name: str, port: int, password: str, limits: tuple[str, str, str]) -> list[str]:
    memory, heap, pagecache = limits
    arguments = ["run", "-d", "--name", name, "--memory", memory, "--label", f"{TEST_LABEL}=true"]
    for key, value in owner_labels().items():
        arguments += ["--label", f"{key}={value}"]
    arguments += [
        "-p",
        f"127.0.0.1:{port}:{NEO4J_BOLT_PORT}",
        "-e",
        f"NEO4J_AUTH=neo4j/{password}",
        "-e",
        f"NEO4J_server_memory_heap_initial__size={heap}",
        "-e",
        f"NEO4J_server_memory_heap_max__size={heap}",
        "-e",
        f"NEO4J_server_memory_pagecache_size={pagecache}",
        NEO4J_IMAGE,
    ]
    return arguments


def _first_line(text: str) -> str:
    return (text.strip().splitlines() or ["no output"])[0]


_DAEMON_UNREACHABLE = (
    "cannot connect to the docker daemon",
    "is the docker daemon running",
    "permission denied while trying to connect",
    "error during connect",
)


def _ensure_image(run: DockerRunner) -> None:
    """Make sure the Neo4j image is on this machine, pulling it only if it is missing. This runs
    before the readiness clock starts, so a slow pull is never counted against the container. An
    inspect that fails because the daemon cannot be reached is the docker phase, not a missing
    image."""
    try:
        inspected = run("image", "inspect", NEO4J_IMAGE)
        if inspected.returncode == 0:
            return
        if any(text in inspected.stderr.lower() for text in _DAEMON_UNREACHABLE):
            raise HarnessStartError(
                "docker",
                f"Docker is not available, so the Neo4j test harness cannot start its "
                f"container: {_first_line(inspected.stderr)}",
            )
        pulled = run("pull", NEO4J_IMAGE, timeout=IMAGE_PULL_TIMEOUT_S)
    except OSError as error:
        raise HarnessStartError(
            "docker",
            f"Docker is not available, so the Neo4j test harness cannot start its container: "
            f"{error}",
        ) from error
    except subprocess.TimeoutExpired as error:
        raise HarnessStartError(
            "image", f"pulling {NEO4J_IMAGE} timed out after {IMAGE_PULL_TIMEOUT_S:.0f} seconds."
        ) from error
    if pulled.returncode != 0:
        raise HarnessStartError(
            "image",
            f"{NEO4J_IMAGE} is not present and could not be pulled: {_first_line(pulled.stderr)}",
        )


def _remove_quietly(name: str, run: DockerRunner) -> None:
    """Best-effort `docker rm -f -v`, for a start that failed. A failed run can leave a created
    container behind, and its anonymous volumes with it (DEC-128)."""
    try:
        run("rm", "-f", "-v", name)
    except OSError, subprocess.TimeoutExpired:
        _reaper_log.warning("Could not remove the failed Neo4j test container %s", name)


def _docker_run(run: DockerRunner, name: str, arguments: list[str]) -> None:
    try:
        started = run(*arguments, timeout=DOCKER_RUN_TIMEOUT_S)
    except OSError as error:
        raise HarnessStartError(
            "docker",
            f"Docker is not available, so the Neo4j test harness cannot start its container: "
            f"{error}",
        ) from error
    except subprocess.TimeoutExpired as error:
        _remove_quietly(name, run)
        raise HarnessStartError(
            "start",
            f"docker run for {name} timed out after {DOCKER_RUN_TIMEOUT_S:.0f} seconds (the "
            f"image was already present, so this is not a pull).",
        ) from error
    if started.returncode != 0:
        _remove_quietly(name, run)
        raise HarnessStartError(
            "start",
            f"Docker could not start the Neo4j test container (is Docker running?): "
            f"{_first_line(started.stderr)}",
        )


def start_throwaway_neo4j(
    *,
    run: DockerRunner | None = None,
    probe: Probe | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ThrowawayNeo4j:
    """Start a container and wait until Neo4j answers on Bolt. Phases, in order, each named in its
    error (HarnessStartError.phase): config, lock (wait for the machine-wide harness lock), docker
    and image (make sure the image is here), start (docker run) and ready (the readiness clock,
    default 120 s, which starts only after the image is present). The lock is held until
    stop_throwaway_neo4j, and is released here on any failure. `run`, `probe`, `clock` and `sleep`
    are injectable for tests."""
    runner = run or _docker
    name = f"{NAME_PREFIX}{uuid.uuid4().hex[:12]}"
    password = new_container_password()
    limits = _memory_limits()  # a bad environment value fails here, before anything is started
    ready_timeout_s()
    try:
        with paused():  # the lock wait has its own bound; it must not count against set-up
            harness_lock.acquire(name, clock=clock, sleep=sleep)
    except harness_lock.HarnessLockError as error:
        raise HarnessStartError("lock", str(error)) from error
    try:
        port = _free_port()  # after the lock: a pick made before a long wait would be stale
        arguments = _run_arguments(name, port, password, limits)
        with paused():  # a pull has its own bound too
            _ensure_image(runner)
        _docker_run(runner, name, arguments)
        container = ThrowawayNeo4j(
            name=name, uri=f"bolt://127.0.0.1:{port}", user="neo4j", password=password
        )
        try:
            wait_until_ready(container, probe=probe, clock=clock, sleep=sleep)
        except BaseException:
            _remove_quietly(name, runner)
            raise
    except BaseException:
        harness_lock.release(name)
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


def bolt_ready(container: ThrowawayNeo4j) -> bool:
    """True when the server answers on Bolt and the default database runs a query. This uses the
    driver in this process, not `docker exec cypher-shell`, which starts a JVM per probe and timed
    out under load. Each attempt is bounded by the driver's connection timeout."""
    try:
        with GraphDatabase.driver(
            container.uri,
            auth=(container.user, container.password),
            connection_timeout=3.0,
            connection_acquisition_timeout=5.0,
            notifications_min_severity="OFF",
        ) as driver:
            driver.verify_connectivity()
            with driver.session() as session:
                session.run("RETURN 1").consume()
    except Exception:
        return False
    return True


def wait_until_ready(
    container: ThrowawayNeo4j,
    *,
    probe: Probe | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    timeout_s: float | None = None,
) -> None:
    """Block until Neo4j answers on Bolt, for up to timeout_s (default DIUCS_NEO4J_READY_TIMEOUT or
    120 s), probing with a backoff from 0.25 s to 2 s. Raises HarnessStartError (phase ready, a
    Neo4jNotRunning) if it does not. The caller decides whether to remove the container."""
    limit = ready_timeout_s() if timeout_s is None else timeout_s
    check = probe or bolt_ready
    deadline = clock() + limit
    pause = 0.25
    while not check(container):
        remaining = deadline - clock()
        if remaining <= 0:
            raise HarnessStartError(
                "ready",
                f"The Neo4j test container {container.name} did not answer on Bolt within "
                f"{limit:g} seconds.",
            )
        sleep(max(min(pause, remaining), 0.1))
        pause = min(pause * 1.5, 2.0)


def stop_throwaway_neo4j(container: ThrowawayNeo4j, *, run: DockerRunner | None = None) -> None:
    """Remove the container and its anonymous volumes (DEC-128), then free its hold on the harness
    lock. The lock is freed even if the removal fails: the next session's reaper finishes it."""
    if not container.name.startswith(NAME_PREFIX):
        raise ValueError(
            f"{container.name} is not a private test container; only a container this session "
            f"started (a name starting {NAME_PREFIX}) is removed here (the shared one is kept)."
        )
    try:
        result = (run or _docker)("rm", "-f", "-v", container.name)
    finally:
        harness_lock.release(container.name)
    if result.returncode != 0:
        raise RuntimeError(f"Could not remove the Neo4j test container {container.name}.")


@asynccontextmanager
async def throwaway_driver() -> AsyncIterator[tuple[ThrowawayNeo4j, AsyncDriver]]:
    """Start a container, connect to it, and yield (container, driver). The driver is closed and
    the container removed on exit, including when connecting fails."""
    container = start_throwaway_neo4j()
    try:
        driver = await connect_or_fail(container.uri, container.user, container.password)
        mark_owned(driver)  # a private container: nothing else uses it, so it may be wiped whole
        try:
            yield container, driver
        finally:
            forget_owned(driver)
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
    async def scoped_fn(tx: AsyncManagedTransaction) -> T:
        return await fn(scoped(tx))

    async with driver.session() as session:
        return await session.execute_write(scoped_fn)


async def read_tx[T](
    driver: AsyncDriver, fn: Callable[[AsyncManagedTransaction], Awaitable[T]]
) -> T:
    async def scoped_fn(tx: AsyncManagedTransaction) -> T:
        return await fn(scoped(tx))

    async with driver.session() as session:
        return await session.execute_read(scoped_fn)


def _checked_name(name: str) -> str:
    if not _SAFE_NAME.match(name):
        raise ValueError(f"not a safe Neo4j label or property name: {name!r}")
    return name


class WipeRefused(Exception):
    """A global wipe was asked of a database this process does not own."""


# Databases this process started itself (a private container). Only these may be wiped whole: on
# anything else other runs may be using the instance (TEN-033, DEC-130 item 9). Keyed by identity,
# because a driver is not hashable by value.
_OWNED: dict[int, AsyncDriver] = {}


def mark_owned(driver: AsyncDriver) -> None:
    """Record that `driver` points at a database this process started and no other run uses."""
    _OWNED[id(driver)] = driver


def forget_owned(driver: AsyncDriver) -> None:
    _OWNED.pop(id(driver), None)


def is_owned(driver: AsyncDriver) -> bool:
    return _OWNED.get(id(driver)) is driver


def _scope_values(scopes: tuple[str | ScopeId, ...]) -> list[str]:
    """The scope ids to delete, each checked as a tenant or network id before anything is sent."""
    if not scopes:
        raise ValueError("wipe_tenant needs at least one scope")
    return [
        ScopeId.parse(scope.value if isinstance(scope, ScopeId) else scope).value
        for scope in scopes
    ]


# A tenant's own nodes carry `tenantId`; its directory record (and the numbers on it) is the
# registry's and carries the id as `id` (DEC-131). Both go, and nothing else: the `Migration`
# bookkeeping has neither.
_WIPE_REGISTRY = (
    "MATCH (t:Tenant) WHERE t.id IN $scopes "
    "OPTIONAL MATCH (t)-[:HAS_NUMBER]->(number:TenantNumber) "
    "DETACH DELETE t, number RETURN count(t) AS deleted"
)
_WIPE_NETWORK_REGISTRY = (
    "MATCH (n:Network) WHERE n.id IN $scopes DETACH DELETE n RETURN count(n) AS deleted"
)
# A network's membership, grant and listing records carry no `tenantId`; they name the network as
# `networkId`, so a network scope's wipe takes them too.
_WIPE_NETWORK_RECORDS = (
    "MATCH (n) WHERE (n:NetworkMembership OR n:Grant OR n:Listing) AND n.networkId IN $scopes "
    "DETACH DELETE n RETURN count(n) AS deleted"
)
_WIPE_BATCH = (
    f"MATCH (n) WHERE n.tenantId IN $scopes WITH n LIMIT {DELETE_BATCH} "
    "DETACH DELETE n RETURN count(*) AS deleted"
)


async def _delete(driver: AsyncDriver, cypher: str, **params: Any) -> int:
    async def work(tx: AsyncManagedTransaction) -> int:
        rows = await (await tx.run(cypher, **params)).data()
        return int(rows[0]["deleted"]) if rows else 0

    return await write_tx(driver, work)


async def wipe_tenant(driver: AsyncDriver, *scopes: str | ScopeId) -> None:
    """Delete every node that carries one of these scope ids (a tenant or a network), and the
    directory records of those scopes, in batches. Nothing else is touched: not another tenant's
    data on the same Neo4j, not the `Migration` records, not the constraints and indexes. This is
    the wipe between tests (`clean_graph`) and the sweeper's."""
    values = _scope_values(scopes)
    await _delete(driver, _WIPE_REGISTRY, scopes=values)
    await _delete(driver, _WIPE_NETWORK_REGISTRY, scopes=values)
    await _delete(driver, _WIPE_NETWORK_RECORDS, scopes=values)
    while await _delete(driver, _WIPE_BATCH, scopes=values):
        pass


async def wipe_all(driver: AsyncDriver) -> None:
    """Delete every node and relationship of a database this process owns, in batches. The
    `Migration` nodes stay, and so do constraints and indexes. Refused (WipeRefused, nothing sent)
    for a database that was not marked owned: another run may be using it."""
    if not is_owned(driver):
        raise WipeRefused("a whole-database wipe is allowed only on a database this run started")
    query = (
        f"MATCH (n) WHERE NOT n:Migration WITH n LIMIT {DELETE_BATCH} "
        "DETACH DELETE n RETURN count(*) AS deleted"
    )
    while await _delete(driver, query):
        pass


def _bound_or_given(tenant: str | None) -> str:
    """The scope a helper reads: the one given, else the one bound now (TenantNotBound if none)."""
    if tenant is not None:
        return ScopeId.parse(tenant).value
    scope = current_scope_or_none()
    if scope is None:
        raise TenantNotBound
    return scope.value


async def tx_run(tx: Any, cypher: str, /, **params: Any) -> Any:
    """Run raw test Cypher with `tenant` set to the tenant bound now, so a statement can say
    `{tenantId: $tenant}` without every call site passing it. A `tenant` argument is refused, as
    `run_query` refuses it: the tenant is the one that is bound."""
    if "tenant" in params:
        raise TenantParameterRefused
    return await tx.run(cypher, **params, tenant=_bound_or_given(None))


def run_scope_ids() -> list[str]:
    """The scope ids of this process's run (tenant, second tenant, network scope), as the conftest
    exported them (`DIUCS_TEST_TENANT`, `_OTHER_TENANT`, `_NETWORK`): the only scopes a test of this
    run may write to, and so the only ones a whole-graph scan of a test needs to read."""
    names = ("DIUCS_TEST_TENANT", "DIUCS_TEST_OTHER_TENANT", "DIUCS_TEST_NETWORK")
    values = [os.environ.get(name, "") for name in names]
    if not all(values):
        raise RuntimeError("the run's scope ids are not set: the tests conftest sets them")
    return values


# Every node of this run's scopes: those that carry one of its ids as `tenantId`, and the registry
# records (`Tenant`, `Network`) that carry it as `id`. The graph holds other runs' data too (one
# shared Neo4j, DEC-461), so a test that reads "every node" means this run's, never the database's.
RUN_NODES = (
    "MATCH (n) WHERE n.tenantId IN $scopes OR ((n:Tenant OR n:Network) AND n.id IN $scopes) "
)


async def run_nodes(tx: Any, returning: str) -> Any:
    """Run `MATCH <every node of the run's scopes> RETURN <returning>` (the node is `n`)."""
    return await tx.run(f"{RUN_NODES}RETURN {returning}", scopes=run_scope_ids())


async def run_relationships(tx: Any, returning: str) -> Any:
    """The relationships (`r`) that leave a node of the run's scopes."""
    return await tx.run(
        f"MATCH (a)-[r]->() WHERE a.tenantId IN $scopes OR "
        f"((a:Tenant OR a:Network) AND a.id IN $scopes) RETURN {returning}",
        scopes=run_scope_ids(),
    )


async def count_nodes(driver: AsyncDriver, label: str, *, tenant: str | None = None) -> int:
    """The nodes with this label in the tenant bound now (or in `tenant`). With nothing bound and
    no tenant given it raises TenantNotBound: a global count is `count_nodes_all`."""
    query = f"MATCH (n:`{_checked_name(label)}` {{tenantId: $tenant}}) RETURN count(n) AS total"
    scope = _bound_or_given(tenant)
    return await _total(driver, query, tenant=scope)


async def count_nodes_run(driver: AsyncDriver, label: str) -> int:
    """The nodes with this label in every scope of this run (its tenant, its second tenant and its
    network scope): for a test that works in two tenants and counts what both hold. Other runs'
    nodes on the same Neo4j are not counted."""
    query = (
        f"MATCH (n:`{_checked_name(label)}`) WHERE n.tenantId IN $scopes RETURN count(n) AS total"
    )
    return await _total(driver, query, scopes=run_scope_ids())


async def count_nodes_all(driver: AsyncDriver, label: str) -> int:
    """The nodes with this label in every tenant, and those with none. For the registry labels
    (`Migration`, `Tenant`) and for a test that means the whole database."""
    return await _total(driver, f"MATCH (n:`{_checked_name(label)}`) RETURN count(n) AS total")


async def _total(driver: AsyncDriver, query: str, **params: Any) -> int:
    async def work(tx: AsyncManagedTransaction) -> int:
        rows = await (await tx.run(query, **params)).data()
        return int(rows[0]["total"])

    return await read_tx(driver, work)


async def node_props(
    driver: AsyncDriver, label: str, *, scope: str | None = None, **match: Any
) -> dict[str, Any]:
    """Properties of the single node with this label and these property values in the tenant bound
    now (or in `scope`). Fails unless exactly one node matches, and the message names how many
    did."""
    conditions = " AND ".join(
        ["n.tenantId = $tenant", *(f"n.`{_checked_name(key)}` = ${key}" for key in match)]
    )
    query = f"MATCH (n:`{_checked_name(label)}`) WHERE {conditions} RETURN properties(n) AS props"
    tenant = _bound_or_given(scope)

    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run(query, **match, tenant=tenant)).data()

    rows = await read_tx(driver, work)
    if len(rows) != 1:
        raise AssertionError(
            f"expected exactly 1 {label} node matching {match!r}, found {len(rows)}"
        )
    props: dict[str, Any] = rows[0]["props"]
    return props


# DEC-108, amended by DEC-135. A container labelled with its owner is judged by whether that owner
# is still running, at any age. This age is only the fallback for a container with no owner label
# at all (made by the harness before F10b): test runs take under 20 minutes, so one this old cannot
# belong to a live run.
REAPER_MAX_AGE = timedelta(minutes=90)
# A container whose owner cannot be checked from this process is removed only after this much
# longer age. "Cannot be checked" covers: another host name, another pid namespace, another boot
# (a pid and start time can repeat across boots), an owner label that is only partly written, and
# a process table that will not say (see proc.process_start_marker). The owner may be alive there.
OTHER_HOST_MAX_AGE = timedelta(hours=6)
TEST_LABEL = "diucs-test"
# A container is removed only if its name has this prefix AND it carries TEST_LABEL (DEC-108).
NAME_PREFIX = "diucs-test-neo4j-"
DockerRunner = Callable[..., subprocess.CompletedProcess[str]]
ProcessStart = Callable[[int], str | None]
_CREATED_AT = re.compile(
    r"^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]+))?(Z|[+-][0-9]{2}:[0-9]{2})$"
)
_reaper_log = logging.getLogger(__name__)

_ALIVE = "alive"
_GONE = "gone"
_UNKNOWN = "unknown"


class _OwnerLabels(NamedTuple):
    """The owner labels of one container, or of this process when used as the "here" side."""

    pid: str
    start: str
    host: str
    namespace: str
    boot: str

    def is_empty(self) -> bool:
        return not any(self)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_created(text: str) -> datetime:
    """Parse docker's Created value, RFC 3339 with up to nanoseconds, into an aware datetime."""
    match = _CREATED_AT.match(text.strip())
    if match is None:
        raise ValueError(f"unrecognised Created time: {text!r}")
    base, fraction, zone = match.groups()
    micros = (fraction or "")[:6].ljust(6, "0")
    offset = "+00:00" if zone == "Z" else zone
    return datetime.fromisoformat(f"{base}.{micros}{offset}")


def _owner_verdict(
    owner: _OwnerLabels, here: _OwnerLabels, process_start: ProcessStart
) -> tuple[str, timedelta | None]:
    """Is the owner of a container running? Returns the verdict and, for an unknown one, the age
    after which the container may be removed anyway (None for alive and gone).

    alive: the owner is in this pid namespace and boot on this host, its pid exists here, and it has
    the start time on the label.
    gone: only when this process can see that no such process exists: the pid is absent from this
    pid table (kill(pid, 0) says so) or it was reused by a process that started at another time.
    unknown: anything else. A container with no owner label at all (made before F10b) keeps the
    90-minute age rule (REAPER_MAX_AGE); an owner whose pid or start label is not ASCII digits keeps
    REAPER_MAX_AGE too; every other unknown owner keeps OTHER_HOST_MAX_AGE.
    """
    if owner.is_empty():
        return _UNKNOWN, REAPER_MAX_AGE
    if not ascii_digits(owner.pid) or not ascii_digits(owner.start):
        return _UNKNOWN, REAPER_MAX_AGE
    if not (owner.host and owner.namespace and owner.boot):
        return _UNKNOWN, OTHER_HOST_MAX_AGE
    if owner.host != here.host or owner.namespace != here.namespace or owner.boot != here.boot:
        return _UNKNOWN, OTHER_HOST_MAX_AGE
    try:
        marker = process_start(int(owner.pid))
    except Exception:
        # The process table could not say (hidepid, no descriptors left, a garbled line). That is
        # not "gone": the age rule decides.
        return _UNKNOWN, OTHER_HOST_MAX_AGE
    return (_ALIVE, None) if marker == owner.start else (_GONE, None)


def reap_stale_test_containers(
    max_age: timedelta = REAPER_MAX_AGE,
    *,
    run: DockerRunner = _docker,
    now: Callable[[], datetime] = _utc_now,
    process_start: ProcessStart = process_start_marker,
    host: str | None = None,
    here_namespace: str | None = None,
    here_boot: str | None = None,
) -> list[str]:
    """Remove the diucs-test containers whose owner has gone, and return their names.

    A run killed by a timeout or a signal never reaches stop_throwaway_neo4j, so its container
    stays. Each container carries the pid and start time of its owner (owner_labels): the sweep
    removes it when this process can see that the owner is gone, whatever its age, and never removes
    one whose owner is running. The owner is comparable only from its own host name, pid namespace
    and boot: any other, or an owner that cannot be seen, is kept until OTHER_HOST_MAX_AGE (a pid or
    start label that is not ASCII digits keeps the 90-minute rule instead). A
    container with no owner label at all (made before F10b) keeps the age rule, `max_age`
    (DEC-108). `here_namespace` and `here_boot` default to this process's identities and are
    injectable for tests. This runs once per pytest session (conftest.py). It never raises: if
    Docker is missing or fails, it logs a warning and returns what it removed so far. A container is
    removed only if its name starts with NAME_PREFIX and it carries TEST_LABEL, both checked here as
    well as in the docker filter, and removal is `docker rm -f -v` (DEC-128). A Created value that
    does not parse skips that one container, not the sweep.
    """
    here = _OwnerLabels(
        pid="",
        start="",
        host=host if host is not None else socket.gethostname(),
        namespace=here_namespace if here_namespace is not None else pid_namespace(),
        boot=here_boot if here_boot is not None else boot_id(),
    )
    removed: list[str] = []
    try:
        listed = run("ps", "-a", "--filter", f"label={TEST_LABEL}=true", "--format", "{{.Names}}")
        if listed.returncode != 0:
            _reaper_log.warning("Could not list test containers: %s", listed.stderr.strip())
            return removed
        names = [name for name in listed.stdout.split() if name.startswith(NAME_PREFIX)]
        if not names:
            return removed
        labels = (
            TEST_LABEL,
            OWNER_PID_LABEL,
            OWNER_START_LABEL,
            OWNER_HOST_LABEL,
            OWNER_NS_LABEL,
            OWNER_BOOT_LABEL,
        )
        label_format = "|".join(f'{{{{index .Config.Labels "{label}"}}}}' for label in labels)
        inspected = run(
            "inspect", "--format", f"{{{{.Name}}}}|{{{{.Created}}}}|{label_format}", *names
        )
        if inspected.returncode != 0:
            _reaper_log.warning("Could not inspect test containers: %s", inspected.stderr.strip())
            return removed
        current = now()
        for line in inspected.stdout.splitlines():
            fields = (line.split("|") + [""] * 8)[:8]
            name, created, label, pid_text, start, owner_host, owner_ns, owner_boot = fields
            name = name.lstrip("/")
            if label != "true" or name not in names:
                continue
            owner = _OwnerLabels(pid_text, start, owner_host, owner_ns, owner_boot)
            verdict, fallback_age = _owner_verdict(owner, here, process_start)
            if verdict == _ALIVE:
                continue
            if verdict == _UNKNOWN:
                assert fallback_age is not None
                try:
                    created_at = _parse_created(created)
                except ValueError:
                    _reaper_log.warning(
                        "Skipping %s: its Created value %r does not parse", name, created
                    )
                    continue
                if created_at >= current - max(fallback_age, max_age):
                    continue
            result = run("rm", "-f", "-v", name)
            if result.returncode == 0:
                removed.append(name)
            else:
                _reaper_log.warning("Could not remove stale test container %s", name)
    except Exception:
        _reaper_log.warning(
            "Stale test container reaper skipped: Docker is unavailable or failed.", exc_info=True
        )
    return removed
