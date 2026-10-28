"""Cross-process lock for the Neo4j test harness (F10b). Stub: no behaviour yet (DEC-010)."""

DEFAULT_LOCK_PATH = "/tmp/diucs-neo4j-harness.lock"
LOCK_ENV = "DIUCS_NEO4J_LOCK"
LOCK_TIMEOUT_ENV = "DIUCS_NEO4J_LOCK_TIMEOUT"
DEFAULT_LOCK_TIMEOUT_S = 3600.0


class HarnessLockTimeout(Exception):
    """The lock was not free within the timeout."""


def lock_path() -> str:
    return DEFAULT_LOCK_PATH


def holder_pid(path: str) -> int | None:
    return None


def acquire(owner, *, timeout_s=None, path=None, flock=None, clock=None, sleep=None) -> None:  # type: ignore[no-untyped-def]
    return None


def release(owner: str) -> None:
    return None


def release_all() -> None:
    return None
