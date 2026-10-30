"""The cross-process lock of the Neo4j harness (F10b, DEC-135). No Docker needed.

Four agents ran pytest at once and each session started its own Neo4j; the machine fell over.
The harness now takes an exclusive advisory file lock before it starts a container and holds it
until the container is removed. These tests use a fake flock and a fake clock for the timing
rules, and real processes for the two facts that only the operating system can prove: a second
process waits for the first, and a process that dies releases the lock.
"""

import fcntl
import os
import select
import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import IO

import pytest

from tests.support import harness_lock
from tests.support import neo4j as harness
from tests.support.harness_lock import (
    DEFAULT_LOCK_PATH,
    HarnessLockError,
    HarnessLockTimeout,
    acquire,
    holder_pid,
    lock_path,
    release,
)

BACKEND = Path(__file__).resolve().parents[3]

HOLDER = """
import sys
from tests.support.harness_lock import acquire, release
acquire("child", timeout_s=float(sys.argv[2]), path=sys.argv[1])
print("held", flush=True)
sys.stdin.readline()
release("child")
print("released", flush=True)
"""

WAITER = """
import sys
from tests.support.harness_lock import acquire
acquire("waiter", timeout_s=float(sys.argv[2]), path=sys.argv[1])
print("got", flush=True)
"""


@pytest.fixture(autouse=True)
def _no_lock_left_behind() -> Iterator[None]:
    yield
    harness_lock.release_all()


class FakeClock:
    """Time that only moves when something sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _busy(fd: int, operation: int) -> None:
    raise BlockingIOError(11, "Resource temporarily unavailable")


def _is_free(path: Path) -> bool:
    """True when no one holds the lock: a fresh open file description can take it at once."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    finally:
        os.close(fd)


def _spawn(script: str, path: Path, timeout_s: float) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", script, str(path), str(timeout_s)],
        cwd=BACKEND,
        env={**os.environ, "PYTHONPATH": str(BACKEND)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )


def _line(stream: IO[str] | None, within_s: float) -> str | None:
    """The next line the child printed, or None if it printed nothing within within_s."""
    assert stream is not None
    ready, _, _ = select.select([stream], [], [], within_s)
    return stream.readline().strip() if ready else None


def test_the_default_lock_is_not_the_manual_pytest_lock_and_the_environment_overrides_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DIUCS_NEO4J_LOCK", raising=False)
    assert lock_path() == "/tmp/diucs-neo4j-harness.lock" == DEFAULT_LOCK_PATH
    # The manual whole-run lock of the serial era is gone (TEN-035); nothing else may use this file.
    assert lock_path().endswith("harness.lock")

    monkeypatch.setenv("DIUCS_NEO4J_LOCK", str(tmp_path / "other.lock"))
    assert lock_path() == str(tmp_path / "other.lock")


def test_the_module_documentation_names_the_container_lock() -> None:
    assert harness.__doc__ is not None
    assert "/tmp/diucs-neo4j-harness.lock" in harness.__doc__
    assert "manual flock" in harness.__doc__
    assert "DIUCS_NEO4J_LOCK" in harness.__doc__


def test_acquire_takes_the_lock_and_writes_the_holder_pid(tmp_path: Path) -> None:
    path = tmp_path / "harness.lock"

    acquire("a", path=str(path))

    assert not _is_free(path)
    assert holder_pid(str(path)) == os.getpid()


def test_release_frees_the_lock(tmp_path: Path) -> None:
    path = tmp_path / "harness.lock"
    acquire("a", path=str(path))

    release("a")

    assert _is_free(path)


def test_two_containers_in_one_process_share_one_hold_and_the_last_release_frees_it(
    tmp_path: Path,
) -> None:
    # The harness tests start extra containers while the session container is alive, in one
    # process. They must not wait for themselves.
    path = tmp_path / "harness.lock"
    acquire("session", path=str(path))
    acquire("extra", timeout_s=0.5, path=str(path))

    release("extra")
    assert not _is_free(path)
    release("session")
    assert _is_free(path)


def test_releasing_a_name_that_never_acquired_does_not_free_anyone_elses_hold(
    tmp_path: Path,
) -> None:
    path = tmp_path / "harness.lock"
    acquire("session", path=str(path))

    release("a container that was never started")

    assert not _is_free(path)


def test_acquire_retries_until_the_lock_is_free(tmp_path: Path) -> None:
    clock = FakeClock()
    attempts: list[int] = []

    def busy_three_times(fd: int, operation: int) -> None:
        attempts.append(fd)
        if len(attempts) <= 3:
            raise BlockingIOError(11, "busy")

    acquire(
        "a",
        timeout_s=60,
        path=str(tmp_path / "harness.lock"),
        flock=busy_three_times,
        clock=clock,
        sleep=clock.sleep,
    )

    assert len(attempts) == 4
    assert 0 < clock.now - 1000.0 < 10


def test_a_timeout_names_the_holder_pid_the_file_and_the_wait(tmp_path: Path) -> None:
    path = tmp_path / "harness.lock"
    path.write_text("424242\n", encoding="utf-8")
    clock = FakeClock()

    with pytest.raises(HarnessLockTimeout) as excinfo:
        acquire("a", timeout_s=30, path=str(path), flock=_busy, clock=clock, sleep=clock.sleep)

    message = str(excinfo.value)
    assert "424242" in message
    assert str(path) in message
    assert "30" in message
    assert 30 <= clock.now - 1000.0 < 32  # it waited the whole time, on the fake clock


def test_a_timeout_says_the_holder_is_unknown_when_the_file_names_none(tmp_path: Path) -> None:
    path = tmp_path / "harness.lock"
    clock = FakeClock()

    with pytest.raises(HarnessLockTimeout) as excinfo:
        acquire("a", timeout_s=5, path=str(path), flock=_busy, clock=clock, sleep=clock.sleep)

    assert "unknown" in str(excinfo.value)


def test_a_failed_acquire_leaves_nothing_held(tmp_path: Path) -> None:
    path = tmp_path / "harness.lock"
    clock = FakeClock()
    with pytest.raises(HarnessLockTimeout):
        acquire("a", timeout_s=2, path=str(path), flock=_busy, clock=clock, sleep=clock.sleep)

    acquire("b", timeout_s=1, path=str(path))  # the real lock is free, so this is immediate
    release("b")

    assert _is_free(path)


def test_the_timeout_comes_from_the_environment_when_not_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_LOCK_TIMEOUT", "7")
    clock = FakeClock()

    with pytest.raises(HarnessLockTimeout):
        acquire(
            "a",
            path=str(tmp_path / "harness.lock"),
            flock=_busy,
            clock=clock,
            sleep=clock.sleep,
        )

    assert 7 <= clock.now - 1000.0 < 9


def test_the_default_wait_is_generous_but_bounded() -> None:
    assert 1800 <= harness_lock.DEFAULT_LOCK_TIMEOUT_S <= 7200


def test_a_second_process_waits_until_the_first_releases_the_lock(tmp_path: Path) -> None:
    path = tmp_path / "harness.lock"
    holder = _spawn(HOLDER, path, 30)
    waiter: subprocess.Popen[str] | None = None
    try:
        assert _line(holder.stdout, 30) == "held"
        assert not _is_free(path)
        waiter = _spawn(WAITER, path, 60)

        assert _line(waiter.stdout, 2.0) is None  # still waiting while the holder holds

        assert holder.stdin is not None
        holder.stdin.write("go\n")
        holder.stdin.flush()
        assert _line(holder.stdout, 30) == "released"
        assert _line(waiter.stdout, 30) == "got"
        assert holder_pid(str(path)) == waiter.pid
    finally:
        for process in (holder, waiter):
            if process is not None:
                process.kill()
                process.wait()


def test_a_holder_that_is_killed_releases_the_lock(tmp_path: Path) -> None:
    # The operating system drops a flock when its process dies, with no clean-up code of ours. A
    # SIGKILLed run (which cannot clean up) must therefore never block the next one.
    path = tmp_path / "harness.lock"
    holder = _spawn(HOLDER, path, 30)
    waiter: subprocess.Popen[str] | None = None
    try:
        assert _line(holder.stdout, 30) == "held"
        assert not _is_free(path)
        waiter = _spawn(WAITER, path, 60)
        assert _line(waiter.stdout, 1.5) is None

        holder.send_signal(signal.SIGKILL)
        holder.wait()

        assert _line(waiter.stdout, 30) == "got"
        assert holder_pid(str(path)) == waiter.pid
    finally:
        for process in (holder, waiter):
            if process is not None:
                process.kill()
                process.wait()


def test_a_timeout_against_a_live_holder_names_its_real_pid(tmp_path: Path) -> None:
    path = tmp_path / "harness.lock"
    holder = _spawn(HOLDER, path, 30)
    try:
        assert _line(holder.stdout, 30) == "held"

        with pytest.raises(HarnessLockTimeout) as excinfo:
            acquire("a", timeout_s=1.0, path=str(path))

        assert f"pid {holder.pid}" in str(excinfo.value)
    finally:
        holder.kill()
        holder.wait()


# ---- verifier follow-up N5: the lock file ------------------------------------------------------


def test_a_lock_file_that_is_a_symlink_is_refused_and_its_target_is_left_alone(
    tmp_path: Path,
) -> None:
    target = tmp_path / "somebody-elses-file"
    target.write_text("keep me\n", encoding="utf-8")
    link = tmp_path / "harness.lock"
    link.symlink_to(target)

    with pytest.raises(HarnessLockError, match="harness.lock"):
        acquire("a", timeout_s=1, path=str(link))

    assert target.read_text(encoding="utf-8") == "keep me\n"


def test_a_symlinked_lock_file_fails_a_start_in_the_lock_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "target"
    target.write_text("keep\n", encoding="utf-8")
    link = tmp_path / "link.lock"
    link.symlink_to(target)
    monkeypatch.setenv("DIUCS_NEO4J_LOCK", str(link))
    calls: list[tuple[str, ...]] = []

    def docker(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    with pytest.raises(harness.HarnessStartError) as excinfo:
        harness.start_throwaway_neo4j(run=docker, probe=lambda container: True)

    assert excinfo.value.phase == "lock"
    assert calls == []
    assert target.read_text(encoding="utf-8") == "keep\n"


def test_the_lock_file_is_world_writable_on_purpose_whatever_the_umask(tmp_path: Path) -> None:
    # Agents may run as different users and all of them must be able to take the lock.
    path = tmp_path / "harness.lock"
    old = os.umask(0o077)
    try:
        acquire("a", path=str(path))
    finally:
        os.umask(old)

    assert path.stat().st_mode & 0o777 == 0o666


def test_releasing_the_first_holder_first_keeps_the_lock_for_the_second(tmp_path: Path) -> None:
    # The reverse of the order above: if the second holder was never recorded, releasing the first
    # would free a lock that the second container still holds.
    path = tmp_path / "harness.lock"
    acquire("session", path=str(path))
    acquire("extra", timeout_s=0.5, path=str(path))

    release("session")
    assert not _is_free(path)
    release("extra")
    assert _is_free(path)


def test_freeing_the_lock_empties_the_file_so_a_stale_pid_is_not_left_behind(
    tmp_path: Path,
) -> None:
    path = tmp_path / "harness.lock"
    acquire("a", path=str(path))
    assert holder_pid(str(path)) == os.getpid()

    release("a")

    assert path.read_bytes() == b""
    assert holder_pid(str(path)) is None
