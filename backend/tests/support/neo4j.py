"""Neo4j test harness (F10). Stub for the red commit (DEC-010): every function raises."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from neo4j import AsyncDriver, AsyncManagedTransaction

START_MESSAGE = (
    "Neo4j is not running. Start it with: docker compose -f infra/docker-compose.yml up -d neo4j"
)


class Neo4jNotRunning(Exception):
    """Raised when the Neo4j instance cannot be reached in time."""


@dataclass(frozen=True, slots=True)
class ThrowawayNeo4j:
    name: str
    uri: str
    user: str
    password: str


def start_throwaway_neo4j() -> ThrowawayNeo4j:
    raise NotImplementedError("F10 red stub: start_throwaway_neo4j")


def stop_throwaway_neo4j(container: ThrowawayNeo4j) -> None:
    raise NotImplementedError("F10 red stub: stop_throwaway_neo4j")


async def connect_or_fail(uri: str, user: str, password: str, timeout_s: float = 5) -> AsyncDriver:
    raise NotImplementedError("F10 red stub: connect_or_fail")


async def write_tx[T](
    driver: AsyncDriver, fn: Callable[[AsyncManagedTransaction], Awaitable[T]]
) -> T:
    raise NotImplementedError("F10 red stub: write_tx")


async def read_tx[T](
    driver: AsyncDriver, fn: Callable[[AsyncManagedTransaction], Awaitable[T]]
) -> T:
    raise NotImplementedError("F10 red stub: read_tx")


async def count_nodes(driver: AsyncDriver, label: str) -> int:
    raise NotImplementedError("F10 red stub: count_nodes")


async def node_props(driver: AsyncDriver, label: str, **match: Any) -> dict[str, Any]:
    raise NotImplementedError("F10 red stub: node_props")


async def wipe(driver: AsyncDriver) -> None:
    raise NotImplementedError("F10 red stub: wipe")
