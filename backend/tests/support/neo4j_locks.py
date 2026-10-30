"""Cross-process locks for the shared Neo4j (TEN-034)."""

from collections.abc import Awaitable, Callable, Mapping

from neo4j import AsyncDriver


class LockTimeout(Exception):
    """A lock stayed taken for the whole timeout."""


class UseHold:
    def release(self) -> None:
        raise NotImplementedError


def lock_path(kind: str, key: str, environ: Mapping[str, str] | None = None) -> str:
    raise NotImplementedError


def acquire_use(
    key: str,
    *,
    exclusive: bool,
    path: str | None = None,
    timeout_s: float = 3600.0,
    poll_s: float = 0.5,
) -> UseHold:
    raise NotImplementedError


async def apply_migrations_once(
    driver: AsyncDriver,
    key: str,
    *,
    apply: Callable[[AsyncDriver], Awaitable[object]] | None = None,
    needs_migrating: Callable[[], Awaitable[bool]] | None = None,
    path: str | None = None,
    timeout_s: float = 3600.0,
    poll_s: float = 0.25,
) -> bool:
    raise NotImplementedError
