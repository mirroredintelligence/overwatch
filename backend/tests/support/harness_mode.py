"""Which Neo4j the integration harness uses, and how the shared one is looked after (TEN-034,
DEC-130 item 9; amends DEC-008 and DEC-013 item 3).

Three modes:

* `owned`: the session starts a private container and removes it when it ends, as before (DEC-008).
  The schema and lifecycle tests always use one of these (`own_neo4j`), whatever the mode.
* `shared` (the default): one long-lived container for the machine, found by name or created once,
  that every run uses, each in its own tenants (the run tenant, the second tenant and the network
  scope of its identity). It is not named like a private container, so the reaper (DEC-108) can
  never remove it; `make neo4j-shared-down` does.
* `attached`: an instance named by `DIUCS_TEST_NEO4J_URI`, `DIUCS_TEST_NEO4J_USER` (default `neo4j`)
  and `DIUCS_TEST_NEO4J_PASSWORD`, for example a CI service container. This is the explicit opt-in
  that DEC-013 item 3 left open: the old `NEO4J_URI` is still never read, so a shell that points at
  another stack changes nothing. The compose stack of the owner (loopback port 7687) is refused
  unless `DIUCS_TEST_NEO4J_ALLOW_LOCAL=1`.

On a shared or attached database a run holds the use lock shared, or exclusively when it selected an
`exclusive` test (`neo4j_locks`), applies the migrations once at a time, and sweeps the tenants of
runs whose owner is gone (`sweeper`), on this machine's instances only. `wipe_all` is refused: the
run owns its tenants, not the database.
"""

import asyncio
import contextlib
import enum
import fcntl
import os
import time
from collections.abc import AsyncIterator, Callable, Iterable, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from neo4j import AsyncDriver

from tests.support import neo4j as harness
from tests.support.neo4j import (
    HEAP_ENV,
    MEMORY_ENV,
    NEO4J_BOLT_PORT,
    NEO4J_IMAGE,
    PAGECACHE_ENV,
    DockerRunner,
    HarnessStartError,
    Probe,
    ThrowawayNeo4j,
    connect_or_fail,
    throwaway_driver,
    wait_until_ready,
)
from tests.support.neo4j_locks import (
    DEFAULT_LOCK_DIR,
    LOCK_DIR_ENV,
    LockTimeout,
    acquire_use,
    apply_migrations_once,
)
from tests.support.sweeper import sweep_orphan_tenants
from tests.support.tenancy import RunIdentity
from tests.support.watchdog import paused

MODE_ENV = "DIUCS_TEST_NEO4J"
URI_ENV = "DIUCS_TEST_NEO4J_URI"
USER_ENV = "DIUCS_TEST_NEO4J_USER"
PASSWORD_ENV = "DIUCS_TEST_NEO4J_PASSWORD"
ALLOW_LOCAL_ENV = "DIUCS_TEST_NEO4J_ALLOW_LOCAL"
SWEEP_ENV = "DIUCS_TEST_NEO4J_SWEEP"
SHARED_NAME = "diucs-test-shared-neo4j"
# Not `diucs-test`: that label (with the name prefix) is what the reaper removes (DEC-108).
SHARED_LABEL = "diucs-test-shared"
# The shared container serves several runs at once, so it gets more than a private one (DEC-135
# measured 1g, 256m and 128m for one run). The same environment variables override them.
SHARED_MEMORY = "2g"
SHARED_HEAP = "768m"
SHARED_PAGECACHE = "384m"
SHARED_CREATE_LOCK_TIMEOUT_S = 900.0
COMPOSE_PORT = 7687
_BOLT_SCHEMES = frozenset({"bolt", "neo4j", "bolt+s", "neo4j+s", "bolt+ssc", "neo4j+ssc"})
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


class Mode(enum.StrEnum):
    OWNED = "owned"
    SHARED = "shared"
    ATTACHED = "attached"


@dataclass(frozen=True, slots=True)
class Selection:
    """The mode the environment asks for. The password is never in its text."""

    mode: Mode
    uri: str | None = None
    user: str | None = None
    password: str | None = field(default=None, repr=False)


@dataclass(slots=True)
class HarnessDatabase:
    """The database a session runs on: where it is, a driver to it, the mode, and the runs whose
    leftover tenants were swept when it was opened."""

    target: ThrowawayNeo4j
    driver: AsyncDriver
    mode: Mode
    swept: list[RunIdentity]


class ExclusiveUnderParallel(Exception):
    """An exclusive test was selected for a session that runs with parallel workers."""


def _config(detail: str) -> HarnessStartError:
    return HarnessStartError("config", detail)


def select_mode(environ: Mapping[str, str] | None = None) -> Selection:
    """The mode the environment asks for (default: shared). `NEO4J_URI` and kin are never read."""
    source = os.environ if environ is None else environ
    uri = source.get(URI_ENV)
    named = source.get(MODE_ENV)
    if uri:
        if named is not None:
            raise _config(
                f"{URI_ENV} and {MODE_ENV} are both set; attach or choose a mode, not both."
            )
        return _attached(uri, source)
    if named is None:
        return Selection(Mode.SHARED)
    value = named.strip().lower()
    if value not in (Mode.OWNED, Mode.SHARED):
        raise _config(f"{MODE_ENV} must be owned or shared, not {named!r}.")
    return Selection(Mode(value))


def _attached(uri: str, source: Mapping[str, str]) -> Selection:
    parts = urlsplit(uri)
    if parts.scheme not in _BOLT_SCHEMES or not parts.hostname:
        raise _config(
            f"{URI_ENV} must be a bolt or neo4j uri with a host, such as bolt://host:7690."
        )
    password = source.get(PASSWORD_ENV)
    if not password:
        raise _config(f"{URI_ENV} is set, so {PASSWORD_ENV} must be set too.")
    port = parts.port or COMPOSE_PORT
    if parts.hostname in _LOOPBACK and port == COMPOSE_PORT and source.get(ALLOW_LOCAL_ENV) != "1":
        raise _config(
            f"{URI_ENV} names port {COMPOSE_PORT} on this machine, which is the compose stack of "
            f"the owner. Use another port, or set {ALLOW_LOCAL_ENV}=1 to say it is meant."
        )
    return Selection(Mode.ATTACHED, uri, source.get(USER_ENV) or "neo4j", password)


def _is_local(uri: str) -> bool:
    return (urlsplit(uri).hostname or "") in _LOOPBACK


def shared_run_arguments(password: str) -> list[str]:
    """`docker run` arguments for the shared container: detached, never auto-removed, limited,
    labelled so it is found and not reaped, on a random loopback port that `inspect` reads back."""
    memory = harness._size_from_environment(MEMORY_ENV, SHARED_MEMORY)
    heap = harness._size_from_environment(HEAP_ENV, SHARED_HEAP)
    pagecache = harness._size_from_environment(PAGECACHE_ENV, SHARED_PAGECACHE)
    return [
        "run",
        "-d",
        "--name",
        SHARED_NAME,
        "--memory",
        memory,
        "--label",
        f"{SHARED_LABEL}=true",
        "-p",
        f"127.0.0.1::{NEO4J_BOLT_PORT}",
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


def _inspect(runner: DockerRunner, template: str) -> str | None:
    result = runner("inspect", "-f", template, SHARED_NAME)
    return result.stdout.strip() if result.returncode == 0 else None


def _shared_state(runner: DockerRunner) -> str | None:
    return _inspect(runner, "{{.State.Status}}")


def _shared_target(runner: DockerRunner) -> ThrowawayNeo4j:
    port = _inspect(runner, '{{(index (index .NetworkSettings.Ports "7687/tcp") 0).HostPort}}')
    env = _inspect(runner, "{{range .Config.Env}}{{println .}}{{end}}")
    if not port or env is None:
        raise HarnessStartError(
            "start", f"{SHARED_NAME} is running but its port could not be read."
        )
    password = next(
        (
            line.split("/", 1)[1]
            for line in env.splitlines()
            if line.startswith("NEO4J_AUTH=neo4j/")
        ),
        None,
    )
    if password is None:
        raise HarnessStartError(
            "start", f"{SHARED_NAME} has no NEO4J_AUTH to read the password from."
        )
    return ThrowawayNeo4j(SHARED_NAME, f"bolt://127.0.0.1:{port}", "neo4j", password)


@contextlib.contextmanager
def _creation_lock(path: str | None) -> Iterator[None]:
    """One session at a time looks for, starts or creates the shared container."""
    resolved = (
        path or f"{os.environ.get(LOCK_DIR_ENV) or DEFAULT_LOCK_DIR}/diucs-neo4j-shared-create.lock"
    )
    fd = os.open(resolved, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o666)
    with contextlib.suppress(OSError):
        os.fchmod(fd, 0o666)
    deadline = time.monotonic() + SHARED_CREATE_LOCK_TIMEOUT_S
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise HarnessStartError(
                        "lock", f"the lock {resolved} was not free: another session is creating it."
                    ) from None
                time.sleep(0.25)
        yield
    finally:
        os.close(fd)


def ensure_shared_neo4j(
    *,
    run: DockerRunner | None = None,
    probe: Probe | None = None,
    lock_path: str | None = None,
    sleep: Callable[[float], None] | None = None,
) -> ThrowawayNeo4j:
    """The shared container, running and ready: used as it is if it runs, started if it is stopped,
    created if it is missing (the image is checked first). The look-up is under a lock, so two
    sessions that arrive together create one container. It is never stopped or removed here."""
    runner = run or harness._docker
    wait = sleep or time.sleep
    with _creation_lock(lock_path):
        state = _shared_state(runner)
        if state is None:
            harness._ensure_image(runner)
            harness._docker_run(
                runner, SHARED_NAME, shared_run_arguments(harness.new_container_password())
            )
        elif state != "running":
            started = runner("start", SHARED_NAME)
            if started.returncode != 0:
                raise HarnessStartError(
                    "start", f"{SHARED_NAME} is {state} and could not be started."
                )
        target = _shared_target(runner)
        wait_until_ready(target, probe=probe, sleep=wait)
        return target


def remove_shared_neo4j(*, run: DockerRunner | None = None) -> bool:
    """Remove the shared container and its anonymous volumes (DEC-128). False if there was none."""
    runner = run or harness._docker
    if _shared_state(runner) is None:
        return False
    result = runner("rm", "-f", "-v", SHARED_NAME)
    if result.returncode != 0:
        raise RuntimeError(f"Could not remove the shared Neo4j test container {SHARED_NAME}.")
    return True


def exclusive_selected(items: Iterable[Any]) -> bool:
    """True when any selected test is marked `exclusive`: the session is then an exclusive run."""
    return any(item.get_closest_marker("exclusive") is not None for item in items)


def refuse_exclusive_under_parallel(items: Iterable[Any], workers: int | None) -> None:
    """An exclusive test cannot run beside another test, so it cannot run in a session that has
    parallel workers. The message says which command to use instead."""
    if workers is None or workers <= 1:
        return
    if exclusive_selected(items):
        raise ExclusiveUnderParallel(
            f"tests marked exclusive cannot run with {workers} parallel workers. Run the parallel "
            f'phase with -m "not exclusive" and the serial phase without -n, with -m exclusive '
            f"(make test-parallel does both)."
        )


@asynccontextmanager
async def open_harness_database(
    selection: Selection, *, exclusive: bool = False, own: RunIdentity | None = None
) -> AsyncIterator[HarnessDatabase]:
    """Open the database the session runs on, migrated, and close it afterwards.

    Owned: a private container (removed on exit, with the machine-wide container lock of DEC-135).
    Shared or attached: the use lock (shared, or exclusive for an exclusive run), the connection,
    the migrations under their lock, and the sweep of the tenants of dead runs (not for an instance
    on another host, unless DIUCS_TEST_NEO4J_SWEEP=1). `own` is the run that must not be swept."""
    swept: list[RunIdentity] = []
    if selection.mode is Mode.OWNED:
        async with throwaway_driver() as (container, driver):
            await apply_migrations_once(driver, container.uri)
            yield HarnessDatabase(container, driver, Mode.OWNED, swept)
        return
    if selection.mode is Mode.SHARED:
        target = await asyncio.to_thread(ensure_shared_neo4j)
        key = SHARED_NAME
        sweep = True
    else:
        assert selection.uri is not None and selection.password is not None
        target = ThrowawayNeo4j(
            "attached", selection.uri, selection.user or "neo4j", selection.password
        )
        key = selection.uri
        sweep = _is_local(selection.uri) or os.environ.get(SWEEP_ENV) == "1"
    try:
        with paused():  # the wait for the other runs has its own bound
            hold = await asyncio.to_thread(acquire_use, key, exclusive=exclusive)
    except LockTimeout as error:
        raise HarnessStartError("lock", str(error)) from error
    try:
        driver = await connect_or_fail(target.uri, target.user, target.password)
        try:
            await apply_migrations_once(driver, key)
            if sweep:
                swept = await sweep_orphan_tenants(driver, [own] if own is not None else [])
            yield HarnessDatabase(target, driver, selection.mode, swept)
        finally:
            await driver.close()
    finally:
        hold.release()


def main(argv: list[str] | None = None) -> int:
    """`python -m tests.support.harness_mode up|down|status`: start, remove or look at the shared
    Neo4j container (the Makefile targets neo4j-shared-up and neo4j-shared-down)."""
    import sys

    arguments = sys.argv[1:] if argv is None else argv
    command = arguments[0] if arguments else ""
    if command == "up":
        target = ensure_shared_neo4j()
        print(f"{SHARED_NAME} is ready at {target.uri}")
        return 0
    if command == "down":
        removed = remove_shared_neo4j()
        print(f"{SHARED_NAME} {'removed' if removed else 'was not there'}")
        return 0
    if command == "status":
        state = _shared_state(harness._docker)
        print(f"{SHARED_NAME}: {state or 'absent'}")
        return 0
    print("usage: python -m tests.support.harness_mode up|down|status", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
