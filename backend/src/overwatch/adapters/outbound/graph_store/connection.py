"""Owns the one AsyncDriver of the process (DEC-012).

The composition root (bootstrap/container.py) builds one Neo4jConnection, calls open() at startup
and close() at shutdown. Nothing else creates a driver. Work runs through session() or
run_read / run_write, and each session is closed by a context manager, on success and on error.

Retries: the driver's managed transactions retry transient errors with backoff. A write run
through run_write can therefore run more than once, so it must be idempotent (keys from P15).
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from neo4j import AsyncDriver, AsyncManagedTransaction, AsyncSession

from diucs.adapters.outbound.graph_store.driver import ScopedTx, create_driver
from diucs.application.tenancy import scope_for_new_unit

log = logging.getLogger(__name__)

_CLOSED_MESSAGE = "the Neo4j connection is closed; build a new Neo4jConnection"


@dataclass(frozen=True, slots=True)
class Neo4jPoolOptions:
    """The four DEC-012 values. Defaults are [ASSUMED] until measured."""

    max_connection_lifetime: float = 1800.0
    liveness_check_timeout: float = 30.0
    connection_acquisition_timeout: float = 30.0
    max_connection_pool_size: int = 50


class Neo4jConnectionError(RuntimeError):
    """The connection cannot be opened, or is used before open or after close."""


class _State(StrEnum):
    NEW = "new"
    OPEN = "open"
    CLOSED = "closed"


def _endpoint_of(uri: str) -> str:
    """host:port from a bolt URI, for messages. Never includes credentials."""
    parts = urlsplit(uri)
    host = parts.hostname or "unknown-host"
    return host if parts.port is None else f"{host}:{parts.port}"


class Neo4jConnection:
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        options: Neo4jPoolOptions | None = None,
    ) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._options = Neo4jPoolOptions() if options is None else options
        self._endpoint = _endpoint_of(uri)
        # Kept after close() so pool_connection_count() can prove the pool is empty.
        self._driver: AsyncDriver | None = None
        self._state = _State.NEW
        self._open_sessions = 0

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def pool_options(self) -> Neo4jPoolOptions:
        return self._options

    @property
    def open_session_count(self) -> int:
        return self._open_sessions

    async def open(self) -> None:
        """Create the driver and verify connectivity. Idempotent while open.

        Raises Neo4jConnectionError, naming the host and port but not the password, when Neo4j
        cannot be reached or rejects the credentials. The caller should then refuse to start.
        """
        if self._state is _State.OPEN:
            return
        if self._state is _State.CLOSED:
            raise Neo4jConnectionError(_CLOSED_MESSAGE)
        options = self._options
        driver = create_driver(
            self._uri,
            self._user,
            self._password,
            max_connection_lifetime=options.max_connection_lifetime,
            liveness_check_timeout=options.liveness_check_timeout,
            connection_acquisition_timeout=options.connection_acquisition_timeout,
            max_connection_pool_size=options.max_connection_pool_size,
        )
        try:
            await driver.verify_connectivity()
        except Exception as exc:
            await driver.close()
            kind = type(exc).__name__
            log.error("Neo4j connection to %s failed at startup: %s", self._endpoint, kind)
            raise Neo4jConnectionError(
                f"cannot connect to Neo4j at {self._endpoint} ({kind}); check the address "
                "and the DIUCS_NEO4J_* credentials"
            ) from None
        self._driver = driver
        self._state = _State.OPEN
        log.info("Neo4j connection open to %s", self._endpoint)

    async def close(self) -> None:
        """Close the driver and its pool. Idempotent: a second call does nothing."""
        was_open = self._state is _State.OPEN
        self._state = _State.CLOSED
        if was_open and self._driver is not None:
            await self._driver.close()
            log.info("Neo4j connection closed")

    @property
    def driver(self) -> AsyncDriver:
        """The one driver, for the start-up steps that take a driver (migrations and the audit
        head). Raises Neo4jConnectionError before open() and after close()."""
        return self._require_open()

    def _require_open(self) -> AsyncDriver:
        if self._state is _State.OPEN and self._driver is not None:
            return self._driver
        if self._state is _State.CLOSED:
            raise Neo4jConnectionError(_CLOSED_MESSAGE)
        raise Neo4jConnectionError("the Neo4j connection is not open; call open() at startup")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """A session for one unit of work. Closed on exit, whether the body succeeded or raised."""
        driver = self._require_open()
        self._open_sessions += 1
        try:
            async with driver.session() as session:
                yield session
        finally:
            self._open_sessions -= 1

    async def run_read[T](self, work: Callable[[AsyncManagedTransaction], Awaitable[T]]) -> T:
        async with self.session() as session:
            return await session.execute_read(work)

    async def run_write[T](self, work: Callable[[AsyncManagedTransaction], Awaitable[T]]) -> T:
        async with self.session() as session:
            return await session.execute_write(work)

    async def run_scoped_read[T](self, work: Callable[[ScopedTx], Awaitable[T]]) -> T:
        """Run `work` in a read transaction on a ScopedTx carrying the scope bound now. The scope
        is read once, before the session opens, so a managed-transaction retry uses the same one.
        The supported way for a worker to run scoped work outside a unit of work: it claims no unit
        of work slot."""
        scope = scope_for_new_unit()

        async def scoped(tx: AsyncManagedTransaction) -> T:
            return await work(ScopedTx(tx, scope))

        return await self.run_read(scoped)

    async def run_scoped_write[T](self, work: Callable[[ScopedTx], Awaitable[T]]) -> T:
        """As run_scoped_read, in a write transaction. A retried write must be idempotent."""
        scope = scope_for_new_unit()

        async def scoped(tx: AsyncManagedTransaction) -> T:
            return await work(ScopedTx(tx, scope))

        return await self.run_write(scoped)

    def pool_connection_count(self) -> int:
        """Connections the driver's pool holds, idle or in use. Zero after close().

        Reads the pool of neo4j 6.4.1, which is not public API; G14 evidence records the version.
        """
        driver = self._driver
        if driver is None:
            return 0
        pool = driver._pool
        return sum(len(connections) for connections in pool.connections.values())
