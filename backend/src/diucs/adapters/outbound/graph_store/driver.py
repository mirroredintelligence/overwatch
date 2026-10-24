"""The one place the Neo4j driver is created, and the one place named queries are run."""

from collections.abc import Callable
from typing import Any

from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.queries import REGISTRY

QueryObserver = Callable[[str, str, int, float], None]


def create_driver(uri: str, user: str, password: str) -> AsyncDriver:
    raise NotImplementedError


async def run_query(
    tx: AsyncManagedTransaction, query_id: str, /, **params: Any
) -> list[dict[str, Any]]:
    raise NotImplementedError


def set_query_observer(fn: QueryObserver | None) -> None:
    return None
