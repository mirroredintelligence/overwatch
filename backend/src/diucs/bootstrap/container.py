"""Composition root: the only module that wires adapters to ports.

Rule: Neo4j-backed ports are never faked in any profile. Every store Neo4j holds
(repositories, unit of work, audit, outbox, idempotency, tokens, scheduled work,
communications, credentials) is the real Neo4j adapter, in tests and in production.
Fakes exist only for external providers and non-record stores (see
docs/spec/contracts.md, "Testing and persistence").

Lifecycle (DEC-012): build() creates the one Neo4jConnection and connects to nothing. The
process calls startup() before serving, which opens the driver and refuses to start if Neo4j
cannot be reached, and shutdown() on exit.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from diucs.adapters.outbound.clock_system.system_clock import SystemClock
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection, Neo4jPoolOptions
from diucs.adapters.outbound.ids_uuid.uuid_ids import UuidGenerator
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.bootstrap.settings import Settings

TEST_NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Container:
    clock: Clock
    ids: IdGenerator
    # One connection per process, which owns the one AsyncDriver (DEC-012).
    neo4j: Neo4jConnection
    # Each later task adds one field here, and wires it in build() and build_for_tests().

    async def startup(self) -> None:
        """Open the Neo4j connection. Raises Neo4jConnectionError, so the process does not start."""
        await self.neo4j.open()

    async def shutdown(self) -> None:
        await self.neo4j.close()


def _neo4j_connection(settings: Settings) -> Neo4jConnection:
    return Neo4jConnection(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password.get_secret_value(),
        Neo4jPoolOptions(
            max_connection_lifetime=settings.neo4j_max_connection_lifetime_s,
            liveness_check_timeout=settings.neo4j_liveness_check_timeout_s,
            connection_acquisition_timeout=settings.neo4j_connection_acquisition_timeout_s,
            max_connection_pool_size=settings.neo4j_max_connection_pool_size,
        ),
    )


def build(settings: Settings) -> Container:
    """Wire the production-facing adapters. Profiles differ only in external providers,
    which later tasks add; the clock and ids are the same in every profile. Connects to nothing:
    call startup() to open Neo4j."""
    return Container(
        clock=SystemClock(),
        ids=UuidGenerator(),
        neo4j=_neo4j_connection(settings),
    )


def build_for_tests(
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
    *,
    neo4j: Neo4jConnection,
) -> Container:
    """Wire the container for tests: a fixed clock and sequential ids unless overridden.

    The connection is required, so each test owns one connection (a fixture) and shares it with
    every container it builds. Nothing here creates a driver. The fixture closes the connection.
    """
    return Container(
        clock=FixedClock(TEST_NOW) if clock is None else clock,
        ids=SequentialIds() if ids is None else ids,
        neo4j=neo4j,
    )
