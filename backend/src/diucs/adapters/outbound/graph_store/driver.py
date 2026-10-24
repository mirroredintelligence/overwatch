"""The one place the Neo4j driver is created, and the one place named queries are run.

DEC-012: the composition root creates one AsyncDriver per process with create_driver, and closes it
on shutdown. Nothing else constructs a driver.
"""

import time
from collections.abc import Callable
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.queries import REGISTRY

QueryObserver = Callable[[str, str, int, float], None]

_observer: QueryObserver | None = None


def create_driver(uri: str, user: str, password: str) -> AsyncDriver:
    """Build the driver. It opens no connection until a session first needs one."""
    return AsyncGraphDatabase.driver(uri, auth=(user, password))


async def run_query(
    tx: AsyncManagedTransaction, query_id: str, /, **params: Any
) -> list[dict[str, Any]]:
    """Run a registered query inside the caller's transaction and return its rows as dicts.

    The observer, if set, is called once per successful run with the query id, its mode, the row
    count and the duration in milliseconds. It never receives the Cypher text or parameters.
    """
    query = REGISTRY.get(query_id)
    started = time.perf_counter()
    result = await tx.run(query.cypher, **params)
    rows = await result.data()
    duration_ms = (time.perf_counter() - started) * 1000
    observer = _observer
    if observer is not None:
        observer(query.id, query.mode, len(rows), duration_ms)
    return rows


def set_query_observer(fn: QueryObserver | None) -> None:
    global _observer
    _observer = fn
