"""Cross-process lock for the Neo4j test harness (F10b, DEC-135).

Several agents run pytest on one machine and each session used to start its own Neo4j. Load reached
15 on 4 cores, readiness probes timed out and the disk filled. The harness now takes an exclusive
advisory lock (flock) on one file before it starts a container, and holds it until that container is
removed. A second session waits, with a bounded timeout, and its error names the holder's pid.

The operating system drops a flock when the process that holds it dies, so a killed run (SIGKILL,
out-of-memory) never blocks the next one. Nothing here needs clean-up code to be safe.

One process can own several containers at once (the harness's own tests start extra ones while the
session container is alive). Holds are kept per container name: the lock is taken for the first and
freed with the last, so a process never waits for itself and a stray release cannot free another
container's hold. Platforms without fcntl (Windows) get no lock and a log line.
"""

import contextlib
import errno
import logging
import os
import threading
import time
from collections.abc import Callable

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

DEFAULT_LOCK_PATH = "/tmp/diucs-neo4j-harness.lock"
LOCK_ENV = "DIUCS_NEO4J_LOCK"
LOCK_TIMEOUT_ENV = "DIUCS_NEO4J_LOCK_TIMEOUT"
# A full serial run is about 15 minutes; four agents queued is an hour.
DEFAULT_LOCK_TIMEOUT_S = 3600.0
POLL_INTERVAL_S = 0.5

_log = logging.getLogger(__name__)
_state = threading.Lock()
_holds: set[str] = set()
_fd: int | None = None


class HarnessLockError(Exception):
    """The lock cannot be taken at all (for example the lock file is a symlink)."""


class HarnessLockTimeout(HarnessLockError):
    """The lock was not free within the timeout. The message names the holder's pid."""


def lock_path() -> str:
    return os.environ.get(LOCK_ENV) or DEFAULT_LOCK_PATH


def _timeout_from_environment() -> float:
    try:
        value = float(os.environ.get(LOCK_TIMEOUT_ENV, ""))
    except ValueError:
        return DEFAULT_LOCK_TIMEOUT_S
    return value if value > 0 else DEFAULT_LOCK_TIMEOUT_S


def holder_pid(path: str) -> int | None:
    """The pid the current holder wrote into the lock file, or None if it names none."""
    try:
        with open(path, encoding="ascii") as handle:
            return int(handle.readline().strip())
    except OSError, ValueError:
        return None


def _os_flock(fd: int, operation: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, operation)


def _open(path: str) -> int:
    """Open the lock file. O_NOFOLLOW: a symlink planted at this path in a shared /tmp must not
    redirect our pid write to someone else's file. The file is made 0666 on purpose, whatever the
    umask: agents may run as different users and every one of them must be able to take the lock
    (the price is that any local user can also hold it; this is a development-machine tool)."""
    flags = os.O_NOFOLLOW
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | flags, 0o666)
    except PermissionError:
        return os.open(path, os.O_RDONLY | flags)  # another user made it; flock works read-only
    with contextlib.suppress(OSError):
        os.fchmod(fd, 0o666)
    return fd


def _write_pid(fd: int) -> None:
    # A read-only descriptor cannot write: the lock still holds, the holder is just not named.
    with contextlib.suppress(OSError):
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{os.getpid()}\n".encode("ascii"), 0)


def acquire(
    owner: str,
    *,
    timeout_s: float | None = None,
    path: str | None = None,
    flock: Callable[[int, int], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Take the harness lock for `owner` (a container name), waiting up to timeout_s. If this
    process already holds it, the hold is shared and this returns at once. Raises
    HarnessLockTimeout, naming the holder's pid, if the lock stays taken."""
    global _fd
    take = flock or _os_flock
    exclusive = (fcntl.LOCK_EX | fcntl.LOCK_NB) if fcntl is not None else 0
    limit = _timeout_from_environment() if timeout_s is None else timeout_s
    resolved = path or lock_path()
    with _state:
        if _fd is not None:
            _holds.add(owner)
            return
        if fcntl is None and flock is None:  # pragma: no cover - Windows
            _log.warning("No flock on this platform: the Neo4j harness lock is not taken.")
            _holds.add(owner)
            return
        try:
            fd = _open(resolved)
        except OSError as error:
            raise HarnessLockError(
                f"The Neo4j harness lock file {resolved} cannot be opened: {error}. "
                f"It must be a plain file, not a symlink."
            ) from error
        deadline = clock() + limit
        warned = False
        while True:
            try:
                take(fd, exclusive)
                break
            except (BlockingIOError, PermissionError) as error:
                if isinstance(error, PermissionError) and error.errno != errno.EACCES:
                    os.close(fd)
                    raise
                now = clock()
                if now >= deadline:
                    os.close(fd)
                    holder = holder_pid(resolved)
                    named = f"pid {holder}" if holder is not None else "a holder that is unknown"
                    raise HarnessLockTimeout(
                        f"The Neo4j harness lock {resolved} was not free within {limit:g} seconds. "
                        f"It is held by {named}: another test run is using the Neo4j harness. "
                        f"Wait for it, or end that process if it is stuck."
                    ) from error
                if not warned:
                    warned = True
                    _log.warning(
                        "Waiting for the Neo4j harness lock %s, held by pid %s",
                        resolved,
                        holder_pid(resolved),
                    )
                sleep(min(POLL_INTERVAL_S, deadline - now))
            except BaseException:
                os.close(fd)
                raise
        _write_pid(fd)
        _fd = fd
        _holds.add(owner)


def _free() -> None:
    global _fd
    if _fd is None:
        return
    fd, _fd = _fd, None
    try:
        os.ftruncate(fd, 0)
        _os_flock(fd, fcntl.LOCK_UN if fcntl is not None else 0)
    except OSError:
        pass
    finally:
        os.close(fd)


def release(owner: str) -> None:
    """End `owner`'s hold. The lock is freed with the last hold. An owner that never acquired
    changes nothing."""
    with _state:
        if owner not in _holds:
            return
        _holds.discard(owner)
        if not _holds:
            _free()


def release_all() -> None:
    """Free the lock whatever holds it. For test clean-up."""
    with _state:
        _holds.clear()
        _free()
