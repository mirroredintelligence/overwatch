"""Composition root: the only module that wires adapters to ports.

Rule: Neo4j-backed ports are never faked in any profile. Every store Neo4j holds
(repositories, unit of work, audit, outbox, idempotency, tokens, scheduled work,
communications, credentials) is the real Neo4j adapter, in tests and in production.
Fakes exist only for external providers and non-record stores (see
docs/spec/contracts.md, "Testing and persistence").

Lifecycle (DEC-012): build() creates the one Neo4jConnection and connects to nothing. The
process calls startup() before serving, which opens the driver and refuses to start if Neo4j
cannot be reached, applies the migrations and makes sure the audit head exists (TEN-007), and
shutdown() on exit.

The tenant directory (global, read-only, over the registry nodes) and the secret store are fields
of the container (TEN-007). No secret store exists beyond the fake: `build` takes one from the
process that serves, and without one every secret reads as not found (fail closed).
"""

import random
from dataclasses import dataclass
from datetime import UTC, datetime

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.adapters.outbound.clock_system.system_clock import SystemClock
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection, Neo4jPoolOptions
from diucs.adapters.outbound.graph_store.migrations import apply_migrations
from diucs.adapters.outbound.graph_store.tenant_directory import Neo4jTenantDirectory
from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_uow_factory
from diucs.adapters.outbound.ids_uuid.uuid_ids import UuidGenerator
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.bootstrap.settings import Settings
from diucs.domain.errors import NotFound

TEST_NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
TEST_RNG_SEED = 20261023


@dataclass(frozen=True)
class Container:
    clock: Clock
    ids: IdGenerator
    # One connection per process, which owns the one AsyncDriver (DEC-012).
    neo4j: Neo4jConnection
    # Units of work on that connection: one session and one transaction each (P06).
    uow_factory: UnitOfWorkFactory
    # The platform's record of its tenants: global, read-only, no tenant bound or sent (TEN-007).
    tenants: TenantDirectory
    # Secrets by reference (DEC-131 item 4): the tenant record holds the reference, never the value.
    secrets: SecretStore
    # The cache: Redis in production, short-lived counts and keys only (DEC-003). The pairing
    # limits of the wall screen routes (R15) are kept here.
    cache: Cache
    # The random source of pairing codes and device tokens (U10): cryptographic in production.
    rng: random.Random
    # Each later task adds one field here, and wires it in build() and build_for_tests().

    async def startup(self) -> None:
        """Open the Neo4j connection, apply the migrations that are not yet recorded and make sure
        the audit head exists. Raises Neo4jConnectionError when Neo4j cannot be reached, or the
        failure of a migration, and closes the connection in the second case, so the process does
        not start and leaves nothing open. TEN-017 makes the audit head per scope; the start-up
        will then bind each active tenant in turn."""
        await self.neo4j.open()
        try:
            driver = self.neo4j.driver
            await apply_migrations(driver)
            await ensure_audit_head(driver)
        except BaseException:
            await self.neo4j.close()
            raise

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


class NoSecrets:
    """The secret store of a process that was given none: every secret is not found, so anything
    that needs one fails closed. A real vault adapter is not built (it needs a credential)."""

    def get(self, name: str) -> bytes:
        raise NotFound(f"secret {name}")


def build(settings: Settings, *, secrets: SecretStore | None = None) -> Container:
    """Wire the production-facing adapters. Profiles differ only in external providers,
    which later tasks add; the clock and ids are the same in every profile. Connects to nothing:
    call startup() to open Neo4j. `secrets` is the process's secret store, if it has one. The
    Redis client connects on first use, and the random source is the operating system's."""
    neo4j = _neo4j_connection(settings)
    clock = SystemClock()
    return Container(
        clock=clock,
        ids=UuidGenerator(),
        neo4j=neo4j,
        uow_factory=neo4j_uow_factory(neo4j, clock=clock),
        tenants=Neo4jTenantDirectory(neo4j),
        secrets=NoSecrets() if secrets is None else secrets,
        cache=RedisCache.from_url(settings.redis_url),
        rng=random.SystemRandom(),
    )


def build_for_tests(
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
    *,
    neo4j: Neo4jConnection,
    secrets: SecretStore | None = None,
    cache: Cache | None = None,
    rng: random.Random | None = None,
) -> Container:
    """Wire the container for tests: a fixed clock and sequential ids unless overridden, and a
    recording fake secret store that holds nothing unless one is passed. The cache is an in-memory
    one on the same clock, and the random source is seeded, so a test's codes are repeatable.

    The connection is required, so each test owns one connection (a fixture) and shares it with
    every container it builds. Nothing here creates a driver. The fixture closes the connection.
    """
    resolved_clock = FixedClock(TEST_NOW) if clock is None else clock
    return Container(
        clock=resolved_clock,
        ids=SequentialIds() if ids is None else ids,
        neo4j=neo4j,
        uow_factory=neo4j_uow_factory(neo4j, clock=resolved_clock),
        tenants=Neo4jTenantDirectory(neo4j),
        secrets=FixedSecretStore({}) if secrets is None else secrets,
        cache=InMemoryCache(resolved_clock) if cache is None else cache,
        rng=random.Random(TEST_RNG_SEED) if rng is None else rng,
    )
