"""Composition root: the only module that wires adapters to ports.

Rule: Neo4j-backed ports are never faked in any profile. Every store Neo4j holds
(repositories, unit of work, audit, outbox, idempotency, tokens, scheduled work,
communications, credentials) is the real Neo4j adapter, in tests and in production.
Fakes exist only for external providers and non-record stores (see
docs/spec/contracts.md, "Testing and persistence").
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from diucs.adapters.outbound.clock_system.system_clock import SystemClock
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
    # Each later task adds one field here, and wires it in build() and build_for_tests().


def build(settings: Settings) -> Container:
    """Wire the production-facing adapters. Profiles differ only in external providers,
    which later tasks add; the clock and ids are the same in every profile."""
    return Container(clock=SystemClock(), ids=UuidGenerator())


def build_for_tests(clock: Clock | None = None, ids: IdGenerator | None = None) -> Container:
    """Wire the container for tests: a fixed clock and sequential ids unless overridden."""
    return Container(
        clock=FixedClock(TEST_NOW) if clock is None else clock,
        ids=SequentialIds() if ids is None else ids,
    )
