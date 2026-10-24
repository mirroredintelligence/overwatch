"""The one place the Neo4j driver is created, and the one place named queries are run.

DEC-012: the composition root creates one AsyncDriver per process with create_driver, and closes it
on shutdown. Nothing else constructs a driver.
"""

import logging
import time
from collections.abc import Callable
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.queries import REGISTRY

QueryObserver = Callable[[str, str, int, float], None]

# The Bolt logger writes every RUN message, with its Cypher text, at DEBUG, and the notifications
# logger writes each server notification with the query text. Both stay at INFO or above, so a
# DEBUG root logger does not put Cypher into the logs (DEC-012, L10).
_TEXT_LOGGERS = ("neo4j.io", "neo4j.notifications")

_observer: QueryObserver | None = None


def create_driver(
    uri: str,
    user: str,
    password: str,
    *,
    max_connection_lifetime: float = 1800.0,
    liveness_check_timeout: float = 30.0,
    connection_acquisition_timeout: float = 30.0,
    max_connection_pool_size: int = 50,
) -> AsyncDriver:
    """Build the driver with the DEC-012 staleness and pool bounds. It opens no connection until a
    session first needs one.

    Server notifications are switched off, and the loggers that write query text are held at INFO
    (see _TEXT_LOGGERS). Nothing in this code base relies on the notifications.
    """
    for name in _TEXT_LOGGERS:
        logging.getLogger(name).setLevel(logging.INFO)
    return AsyncGraphDatabase.driver(
        uri,
        auth=(user, password),
        max_connection_lifetime=max_connection_lifetime,
        liveness_check_timeout=liveness_check_timeout,
        connection_acquisition_timeout=connection_acquisition_timeout,
        max_connection_pool_size=max_connection_pool_size,
        notifications_min_severity="OFF",
    )


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
