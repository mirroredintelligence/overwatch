"""Composition root: the only module that wires adapters to ports.

Rule: Neo4j-backed ports are never faked in any profile. Every store Neo4j holds
(repositories, unit of work, audit, outbox, idempotency, tokens, scheduled work,
communications, credentials) is the real Neo4j adapter, in tests and in production.
Fakes exist only for external providers and non-record stores (see
docs/spec/contracts.md, "Testing and persistence").
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from neo4j import AsyncDriver

from diucs.adapters.outbound.clock_system.system_clock import SystemClock
from diucs.adapters.outbound.graph_store.driver import create_driver
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
    # One driver per process (DEC-012). G14 adds its close on shutdown.
    neo4j_driver: AsyncDriver
    # Each later task adds one field here, and wires it in build() and build_for_tests().


def _neo4j_driver(settings: Settings) -> AsyncDriver:
    return create_driver(
        settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password.get_secret_value()
    )


def build(settings: Settings) -> Container:
    """Wire the production-facing adapters. Profiles differ only in external providers,
    which later tasks add; the clock and ids are the same in every profile."""
    return Container(clock=SystemClock(), ids=UuidGenerator(), neo4j_driver=_neo4j_driver(settings))


def build_for_tests(
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
    neo4j_driver: AsyncDriver | None = None,
) -> Container:
    """Wire the container for tests: a fixed clock and sequential ids unless overridden.

    The driver is built from default settings unless one is passed in. It connects only when a
    session first needs it, so a unit test that runs no query needs no Neo4j. The caller closes
    the driver it gets.
    """
    return Container(
        clock=FixedClock(TEST_NOW) if clock is None else clock,
        ids=SequentialIds() if ids is None else ids,
        neo4j_driver=_neo4j_driver(Settings()) if neo4j_driver is None else neo4j_driver,
    )
