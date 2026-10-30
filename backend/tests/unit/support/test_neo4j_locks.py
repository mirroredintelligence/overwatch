"""The two cross-process locks of the shared Neo4j (TEN-034, audit E 4.2 and 7.1).

The use lock: runs that share the instance hold it shared, and a run that selected an `exclusive`
test holds it exclusively, so it never overlaps another run's tests. The migration lock: two
sessions that find the schema behind apply it one after the other, because the runner is not safe
against a second runner (concurrent DDL, the `Migration` records). Both are plain `flock` files, so
the operating system frees a dead process's hold. Real files, in a temporary directory.
"""

import asyncio
import fcntl
import os
import time
from pathlib import Path

import pytest

from tests.support.neo4j_locks import (
    LockTimeout,
    acquire_use,
    apply_migrations_once,
    lock_path,
)


@pytest.fixture
def path(tmp_path: Path) -> str:
    return str(tmp_path / "use.lock")


# the use lock


def test_runs_that_share_the_instance_hold_the_use_lock_together(path: str) -> None:
    first = acquire_use("k", exclusive=False, path=path, timeout_s=1)
    second = acquire_use("k", exclusive=False, path=path, timeout_s=1)

    first.release()
    second.release()


def test_an_exclusive_run_waits_for_every_sharing_run_to_finish(path: str) -> None:
    sharing = acquire_use("k", exclusive=False, path=path, timeout_s=1)

    with pytest.raises(LockTimeout):
        acquire_use("k", exclusive=True, path=path, timeout_s=0.3, poll_s=0.05)

    sharing.release()
    acquire_use("k", exclusive=True, path=path, timeout_s=1).release()


def test_a_sharing_run_waits_for_an_exclusive_run(path: str) -> None:
    exclusive = acquire_use("k", exclusive=True, path=path, timeout_s=1)

    with pytest.raises(LockTimeout):
        acquire_use("k", exclusive=False, path=path, timeout_s=0.3, poll_s=0.05)

    exclusive.release()
    acquire_use("k", exclusive=False, path=path, timeout_s=1).release()


def test_two_exclusive_runs_do_not_overlap(path: str) -> None:
    first = acquire_use("k", exclusive=True, path=path, timeout_s=1)

    with pytest.raises(LockTimeout):
        acquire_use("k", exclusive=True, path=path, timeout_s=0.3, poll_s=0.05)

    first.release()


def test_a_release_twice_is_harmless_and_frees_the_lock_once(path: str) -> None:
    hold = acquire_use("k", exclusive=True, path=path, timeout_s=1)

    hold.release()
    hold.release()

    acquire_use("k", exclusive=True, path=path, timeout_s=1).release()


def test_the_timeout_message_names_what_waited_and_for_how_long(path: str) -> None:
    sharing = acquire_use("k", exclusive=False, path=path, timeout_s=1)

    with pytest.raises(LockTimeout) as failure:
        acquire_use("k", exclusive=True, path=path, timeout_s=0.2, poll_s=0.05)

    sharing.release()
    assert "exclusive" in str(failure.value)
    assert "0.2" in str(failure.value)


def test_a_waiting_run_gets_the_lock_when_the_holder_lets_go(path: str) -> None:
    holder = acquire_use("k", exclusive=True, path=path, timeout_s=1)
    started = time.monotonic()

    import threading

    threading.Timer(0.3, holder.release).start()
    waiter = acquire_use("k", exclusive=False, path=path, timeout_s=5, poll_s=0.05)

    waiter.release()
    assert time.monotonic() - started >= 0.25


def test_the_lock_file_is_per_instance_and_names_no_secret() -> None:
    one = lock_path("use", "bolt://localhost:7690", {})
    two = lock_path("use", "bolt://localhost:7691", {})
    migrate = lock_path("migrate", "bolt://localhost:7690", {})

    assert len({one, two, migrate}) == 3
    assert one.startswith("/tmp/diucs-neo4j-use-")
    assert lock_path("use", "bolt://localhost:7690", {}) == one
    assert "localhost" not in one


def test_the_lock_directory_can_be_set_for_a_machine_without_tmp() -> None:
    elsewhere = lock_path("use", "k", {"DIUCS_TEST_NEO4J_LOCK_DIR": "/var/tmp/x"})

    assert elsewhere.startswith("/var/tmp/x/diucs-neo4j-use-")


def test_the_operating_system_frees_the_hold_of_a_process_that_died(path: str) -> None:
    pid = os.fork()
    if pid == 0:  # the child takes the exclusive lock and dies without releasing it
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
        fcntl.flock(fd, fcntl.LOCK_EX)
        os._exit(0)
    os.waitpid(pid, 0)

    acquire_use("k", exclusive=True, path=path, timeout_s=1).release()


# the migration lock


async def test_two_sessions_that_need_the_schema_apply_it_one_after_the_other(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    state = {"applied": False}

    async def needs_it() -> bool:
        return not state["applied"]

    async def apply(driver: object) -> None:
        events.append("start")
        await asyncio.sleep(0.2)
        events.append("end")
        state["applied"] = True

    lock = str(tmp_path / "migrate.lock")

    results = await asyncio.gather(
        apply_migrations_once(object(), "k", apply=apply, needs_migrating=needs_it, path=lock),  # type: ignore[arg-type]
        apply_migrations_once(object(), "k", apply=apply, needs_migrating=needs_it, path=lock),  # type: ignore[arg-type]
    )

    assert events == ["start", "end"], "the second session applied the schema again"
    assert sorted(results) == [False, True]


async def test_two_sessions_that_both_apply_do_not_overlap(tmp_path: Path) -> None:
    """When the check cannot tell (the schema looks behind to both), the runs are still serial."""
    events: list[str] = []

    async def always() -> bool:
        return True

    async def apply(driver: object) -> None:
        events.append("start")
        await asyncio.sleep(0.15)
        events.append("end")

    lock = str(tmp_path / "migrate.lock")

    await asyncio.gather(
        apply_migrations_once(object(), "k", apply=apply, needs_migrating=always, path=lock),  # type: ignore[arg-type]
        apply_migrations_once(object(), "k", apply=apply, needs_migrating=always, path=lock),  # type: ignore[arg-type]
        apply_migrations_once(object(), "k", apply=apply, needs_migrating=always, path=lock),  # type: ignore[arg-type]
    )

    assert events == ["start", "end"] * 3


async def test_a_schema_that_is_up_to_date_is_not_locked_and_not_applied(tmp_path: Path) -> None:
    """The common case costs one read and waits for no one, even while another session holds the
    migration lock."""
    lock = str(tmp_path / "migrate.lock")
    holder = os.open(lock, os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(holder, fcntl.LOCK_EX)
    applied: list[str] = []

    async def up_to_date() -> bool:
        return False

    async def apply(driver: object) -> None:
        applied.append("apply")

    try:
        result = await apply_migrations_once(
            object(),  # type: ignore[arg-type]
            "k",
            apply=apply,
            needs_migrating=up_to_date,
            path=lock,
            timeout_s=0.2,
        )
    finally:
        os.close(holder)

    assert result is False
    assert applied == []


async def test_a_session_that_waits_too_long_for_the_migration_lock_fails_clearly(
    tmp_path: Path,
) -> None:
    lock = str(tmp_path / "migrate.lock")
    holder = os.open(lock, os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(holder, fcntl.LOCK_EX)

    async def behind() -> bool:
        return True

    async def apply(driver: object) -> None:
        raise AssertionError("must not run while another session holds the lock")

    try:
        with pytest.raises(LockTimeout, match="migration"):
            await apply_migrations_once(
                object(),  # type: ignore[arg-type]
                "k",
                apply=apply,
                needs_migrating=behind,
                path=lock,
                timeout_s=0.2,
                poll_s=0.05,
            )
    finally:
        os.close(holder)


async def test_the_migration_lock_is_released_when_the_runner_fails(tmp_path: Path) -> None:
    lock = str(tmp_path / "migrate.lock")

    async def behind() -> bool:
        return True

    async def broken(driver: object) -> None:
        raise RuntimeError("migration failed")

    with pytest.raises(RuntimeError, match="migration failed"):
        await apply_migrations_once(
            object(),  # type: ignore[arg-type]
            "k",
            apply=broken,
            needs_migrating=behind,
            path=lock,
        )

    fd = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)
