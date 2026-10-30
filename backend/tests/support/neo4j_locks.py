"""Cross-process locks for the shared Neo4j (TEN-034, audit E 4.2 and 7.1).

Two plain `flock` files, so the operating system frees the hold of a process that dies and nothing
needs clean-up:

* The use lock. Every run that uses the shared instance holds it shared for the session, and a run
  that selected an `exclusive` test holds it exclusively, so it never overlaps another run's tests
  (it waits for the others to finish, and they wait for it).
* The migration lock. A session that finds the schema behind applies the migrations under it, one
  session at a time: the runner is not safe against a second runner (concurrent DDL, the `Migration`
  records). A schema that is up to date is detected with one read and takes no lock.

The files are keyed by the instance (a short hash of its uri or container name, so no secret and no
host name is in a file name), and live in `/tmp` unless `DIUCS_TEST_NEO4J_LOCK_DIR` says otherwise.
The locks are between processes of one machine: an instance that is used from several machines is
not covered (the harness documents it).
"""

import asyncio
import contextlib
import fcntl
import hashlib
import os
import time
from collections.abc import Awaitable, Callable, Mapping

from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.migrations import MIGRATIONS, apply_migrations
from tests.support.neo4j import read_tx

LOCK_DIR_ENV = "DIUCS_TEST_NEO4J_LOCK_DIR"
DEFAULT_LOCK_DIR = "/tmp"
DEFAULT_TIMEOUT_S = 3600.0
USE_POLL_S = 0.5
MIGRATE_POLL_S = 0.25


class LockTimeout(Exception):
    """A lock stayed taken for the whole timeout."""


def lock_path(kind: str, key: str, environ: Mapping[str, str] | None = None) -> str:
    """The lock file of one kind (`use` or `migrate`) for one instance key."""
    source = os.environ if environ is None else environ
    directory = source.get(LOCK_DIR_ENV) or DEFAULT_LOCK_DIR
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"{directory}/diucs-neo4j-{kind}-{digest}.lock"


def _open(path: str) -> int:
    """Open the lock file for every user of the machine to lock (0666, as the harness lock is)."""
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o666)
    except PermissionError:
        return os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with contextlib.suppress(OSError):
        os.fchmod(fd, 0o666)
    return fd


class UseHold:
    """A hold on a lock file. `release` frees it, once; a second call changes nothing."""

    def __init__(self, fd: int) -> None:
        self._fd: int | None = fd

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _try(fd: int, operation: int) -> bool:
    try:
        fcntl.flock(fd, operation | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def acquire_use(
    key: str,
    *,
    exclusive: bool,
    path: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    poll_s: float = USE_POLL_S,
) -> UseHold:
    """Take the use lock of instance `key`: shared, or exclusive. Waits up to timeout_s and raises
    LockTimeout, saying how it was asked for and how long it waited."""
    resolved = path or lock_path("use", key)
    operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    fd = _open(resolved)
    deadline = time.monotonic() + timeout_s
    try:
        while not _try(fd, operation):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                kind = "exclusive" if exclusive else "shared"
                raise LockTimeout(
                    f"The {kind} use lock {resolved} of the shared Neo4j was not free within "
                    f"{timeout_s:g} seconds: "
                    + (
                        "other runs are still using the instance."
                        if exclusive
                        else "an exclusive run holds it."
                    )
                )
            time.sleep(min(poll_s, remaining))
    except BaseException:
        os.close(fd)
        raise
    return UseHold(fd)


async def _recorded_ids(driver: AsyncDriver) -> set[str]:
    async def work(tx: AsyncManagedTransaction) -> set[str]:
        rows = await (await tx.run("MATCH (m:Migration) RETURN m.id AS id")).data()
        return {str(row["id"]) for row in rows}

    return await read_tx(driver, work)


async def apply_migrations_once(
    driver: AsyncDriver,
    key: str,
    *,
    apply: Callable[[AsyncDriver], Awaitable[object]] | None = None,
    needs_migrating: Callable[[], Awaitable[bool]] | None = None,
    path: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    poll_s: float = MIGRATE_POLL_S,
) -> bool:
    """Bring the schema up to date, one session at a time. True when this call applied migrations,
    False when the schema already was current. The check runs once without the lock (the common
    case waits for no one) and again under it (a session that waited finds the work done)."""
    run = apply or apply_migrations

    async def behind() -> bool:
        if needs_migrating is not None:
            return await needs_migrating()
        return bool({migration.id for migration in MIGRATIONS} - await _recorded_ids(driver))

    if not await behind():
        return False
    resolved = path or lock_path("migrate", key)
    fd = _open(resolved)
    deadline = time.monotonic() + timeout_s
    try:
        while not _try(fd, fcntl.LOCK_EX):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LockTimeout(
                    f"The migration lock {resolved} of the shared Neo4j was not free within "
                    f"{timeout_s:g} seconds: another session is applying the migrations."
                )
            await asyncio.sleep(min(poll_s, remaining))
        try:
            if not await behind():
                return False
            await run(driver)
            return True
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
