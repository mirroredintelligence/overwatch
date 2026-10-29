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
from pathlib import Path

import httpx
from redis.asyncio import Redis

from diucs.adapters.inbound.scheduler.scheduled_work_consumer import (
    ScheduledWorkDispatcher,
    WorkHandler,
)
from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.cache_redis.code_store import RedisCodeStore
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.adapters.outbound.cache_redis.sessions import RedisRateLimiter, RedisSessionStore
from diucs.adapters.outbound.clock_system.system_clock import SystemClock
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.outbound.fhir_validator.validator import ProfileValidator
from diucs.adapters.outbound.geocoder_os_places.os_places import (
    REQUEST_TIMEOUT_SECONDS,
    OsPlacesGeocoder,
)
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection, Neo4jPoolOptions
from diucs.adapters.outbound.graph_store.migrations import apply_migrations
from diucs.adapters.outbound.graph_store.tenant_directory import Neo4jTenantDirectory
from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_uow_factory
from diucs.adapters.outbound.ids_uuid.uuid_ids import UuidGenerator
from diucs.adapters.outbound.postcodes_local.centroids import CsvPostcodeLocator
from diucs.adapters.outbound.telemetry.azure_monitor_query import (
    AzureMonitorTelemetryQuery,
    LogsQueryClient,
)
from diucs.adapters.outbound.telemetry.result_attributes import result_attributes
from diucs.adapters.outbound.terminology.local_terminology import LocalTerminology
from diucs.adapters.outbound.travel_time.straight_line import StraightLineTravelTime
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_geo import FixedGeocoder, FixedPostcodeLocator, FixedTravelTime
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.fixed_terminology import FixedTerminology
from diucs.adapters.testing.fixture_telemetry import FixtureTelemetryQuery
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import Actor
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.geo import (
    AddressCandidate,
    Geocoder,
    LatLon,
    Located,
    PostcodeLocator,
    TravelRange,
    TravelTime,
)
from diucs.application.ports.outbound.identity import CodeStore, RateLimiter, SessionStore
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.telemetry_query import (
    SessionFilters,
    SessionSummary,
    SpanRecord,
    TelemetryQuery,
    TelemetryUnavailable,
    TimelineEvent,
)
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.terminology import FhirValidator, Terminology
from diucs.application.ports.outbound.tokens import (
    LinkTokenRepository,
    LinkTokenService,
    SecretStore,
)
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.booking_timers import (
    BookingPhonePrompt,
    ExpireBooking,
    booking_timer_handlers,
)
from diucs.application.use_cases.missed_report_ladder import (
    LADDER_KINDS,
    LadderStepCommand,
    MissedReportLadder,
)
from diucs.application.work import ScheduledWork, WorkKind
from diucs.bootstrap.settings import Settings
from diucs.domain.codes import Role
from diucs.domain.errors import NotFound

TEST_NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
# The sample telemetry the test container serves (O07). Sample values only.
TELEMETRY_FIXTURE = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "telemetry" / "s-7f3a.json"
)
TEST_LINK_BASE_URL = "https://diucs.example"
TEST_RNG_SEED = 20261023

SCHEDULER_ACTOR = Actor(
    role=Role.OWNER,
    practitioner_id=None,
    device_id=None,
    channel="scheduler",
    service_ids=frozenset(),
)
"""The actor of the scheduled-work queue's steps (DEC-193): the role enum has no system role."""


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
    # The FHIR profile validator (R14): pure Python, no store and no external provider.
    validator: FhirValidator
    # Short-lived identity state in Redis (I13): sessions, text codes and rate limits. Each store
    # takes the tenant from the bound unit of work, and connects lazily, so losing Redis signs
    # people out and loses no record. The client is owned here and closed on shutdown.
    redis: Redis
    sessions: SessionStore
    codes: CodeStore
    rate_limiter: RateLimiter
    # The Cache port on the same Redis client (DEC-003: short-lived counts and keys only). The
    # pairing limits of the wall screen routes (R15) are kept here.
    cache: Cache
    # The random source of pairing codes and device tokens (U10): cryptographic in production.
    rng: random.Random
    # Postcode centroids for the patient's position, read from the local file (I11). A patient
    # postcode never leaves the Trust.
    postcodes: PostcodeLocator
    # The travel-time estimate until a routing engine is chosen (I11, I15).
    travel: TravelTime
    # Address lookup for a service's site postcode (I12). Only registration uses it.
    geocoder: Geocoder
    # The ODS sample and the local display names (I12). The live ODS service is not built.
    terminology: Terminology
    # The HTTP client behind the geocoder, closed by shutdown(); None when there is no geocoder.
    http: httpx.AsyncClient | None
    # The support console's raw telemetry (O07): Azure Monitor in a process that has a workspace and
    # a client, otherwise NoTelemetry, which refuses every read.
    telemetry: TelemetryQuery
    # The dispatch table of the scheduled.work queue: the missed-report ladder steps (I05, DEC-192).
    scheduled_work: ScheduledWorkDispatcher
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
            # One chain per scope (TEN-017): each active tenant gets its head, bound in turn. A
            # tenant with no head fails closed at its first append (AuditHeadMissing).
            for tenant_id in await self.tenants.active_tenant_ids():
                with bind_tenant(tenant_id):
                    await ensure_audit_head(driver)
        except BaseException:
            await self.neo4j.close()
            raise

    async def shutdown(self) -> None:
        if self.http is not None:
            await self.http.aclose()
        try:
            await self.neo4j.close()
        finally:
            await self.redis.aclose()


def ladder_handlers(ladder: MissedReportLadder) -> dict[WorkKind, WorkHandler]:
    """The three ladder kinds, each run as one ladder step keyed by the work's id (DEC-193)."""

    async def step(work: ScheduledWork) -> None:
        await ladder.execute(
            LadderStepCommand(idempotency_key=work.id, actor=SCHEDULER_ACTOR, work_id=work.id)
        )

    return {kind: step for kind in LADDER_KINDS}


def _scheduled_work(
    uow_factory: UnitOfWorkFactory,
    clock: Clock,
    ids: IdGenerator,
    secrets: SecretStore,
    link_base_url: str,
) -> ScheduledWorkDispatcher:
    """The dispatch table, built on the same clock, ids and secrets as the rest of the container."""

    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, secrets, clock)

    ladder = MissedReportLadder(
        uow_factory, clock, ids, tokens, link_base_url, AesGcmContentSealer(secrets)
    )
    handlers: dict[WorkKind, WorkHandler] = dict(ladder_handlers(ladder))
    # The booking timers (U19): the advisor's phone prompt and the expiry of a request.
    handlers.update(
        booking_timer_handlers(
            BookingPhonePrompt(uow_factory, clock), ExpireBooking(uow_factory, clock)
        )
    )
    return ScheduledWorkDispatcher(handlers)


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


class NoPostcodes:
    """The postcode locator of a process with no centroid file: nothing is located, so the advisor
    sees no position rather than a guessed one (fail closed, I11)."""

    def centroid(self, postcode: str) -> LatLon | None:
        return None

    def district_centroid(self, district: str) -> LatLon | None:
        return None

    def locate(self, postcode: str) -> Located | None:
        return None


class NoGeocoder:
    """The geocoder of a process with no OS Places key: no address is found, so registration offers
    none rather than a guess (fail closed, I12)."""

    async def find_addresses(self, postcode: str) -> list[AddressCandidate]:
        return []


class NoTelemetry:
    """The telemetry query of a process with no workspace or no client: every read is refused, so
    the console says it cannot show telemetry rather than showing an empty timeline (fail closed,
    O07)."""

    async def session_timeline(
        self, session_id: str, start: datetime, end: datetime
    ) -> list[TimelineEvent]:
        raise TelemetryUnavailable

    async def trace(self, trace_id: str) -> list[SpanRecord]:
        raise TelemetryUnavailable

    async def search_sessions(self, filters: SessionFilters) -> list[SessionSummary]:
        raise TelemetryUnavailable


class NoSecrets:
    """The secret store of a process that was given none: every secret is not found, so anything
    that needs one fails closed. A real vault adapter is not built (it needs a credential)."""

    def get(self, name: str) -> bytes:
        raise NotFound(f"secret {name}")


def _redis_client(url: str) -> Redis:
    return Redis.from_url(url, decode_responses=True)


def build(
    settings: Settings,
    *,
    secrets: SecretStore | None = None,
    telemetry_client: LogsQueryClient | None = None,
) -> Container:
    """Wire the production-facing adapters. Profiles differ only in external providers,
    which later tasks add; the clock and ids are the same in every profile. Connects to nothing:
    call startup() to open Neo4j. `secrets` is the process's secret store, if it has one.
    `telemetry_client` is the process's Azure Monitor logs client (O07); with no client, or with
    no workspace id in the settings, the telemetry query refuses every read."""
    neo4j = _neo4j_connection(settings)
    clock = SystemClock()
    redis = _redis_client(settings.redis_url)
    key = settings.os_places_api_key
    http = None if key is None else httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS)
    ids = UuidGenerator()
    store: SecretStore = NoSecrets() if secrets is None else secrets
    uow_factory = neo4j_uow_factory(neo4j, clock=clock)
    return Container(
        clock=clock,
        ids=ids,
        neo4j=neo4j,
        uow_factory=uow_factory,
        tenants=Neo4jTenantDirectory(neo4j),
        secrets=store,
        validator=ProfileValidator(),
        redis=redis,
        sessions=RedisSessionStore(redis),
        codes=RedisCodeStore(redis, clock),
        rate_limiter=RedisRateLimiter(redis),
        cache=RedisCache(redis),
        rng=random.SystemRandom(),
        postcodes=(
            NoPostcodes()
            if settings.postcode_centroids_path is None
            else CsvPostcodeLocator(settings.postcode_centroids_path)
        ),
        travel=StraightLineTravelTime(),
        geocoder=NoGeocoder()
        if http is None or key is None
        else OsPlacesGeocoder(http, key.get_secret_value()),
        terminology=LocalTerminology(settings.terminology_dir, settings.pathways_dx_file),
        http=http,
        telemetry=(
            NoTelemetry()
            if telemetry_client is None or settings.telemetry_workspace_id is None
            else AzureMonitorTelemetryQuery(
                telemetry_client, settings.telemetry_workspace_id, clock
            )
        ),
        scheduled_work=_scheduled_work(uow_factory, clock, ids, store, settings.base_url),
    )


def build_for_tests(
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
    *,
    neo4j: Neo4jConnection,
    secrets: SecretStore | None = None,
    redis: Redis | None = None,
    cache: Cache | None = None,
    rng: random.Random | None = None,
    telemetry: TelemetryQuery | None = None,
    link_base_url: str = TEST_LINK_BASE_URL,
) -> Container:
    """Wire the container for tests: a fixed clock and sequential ids unless overridden, and a
    recording fake secret store that holds nothing unless one is passed.

    The connection is required, so each test owns one connection (a fixture) and shares it with
    every container it builds. Nothing here creates a driver. The fixture closes the connection.
    The Redis stores use the Redis of Settings unless a client is passed; they connect only when a
    test uses them, so building a container needs no Redis server. The telemetry query is the
    fixture fake (O07, s-7f3a) unless one is passed.
    """
    resolved_clock = FixedClock(TEST_NOW) if clock is None else clock
    resolved_redis = _redis_client(Settings().redis_url) if redis is None else redis
    resolved_ids = SequentialIds() if ids is None else ids
    store: SecretStore = FixedSecretStore({}) if secrets is None else secrets
    uow_factory = neo4j_uow_factory(neo4j, clock=resolved_clock)
    return Container(
        clock=resolved_clock,
        ids=resolved_ids,
        neo4j=neo4j,
        uow_factory=uow_factory,
        tenants=Neo4jTenantDirectory(neo4j),
        secrets=store,
        validator=ProfileValidator(),
        redis=resolved_redis,
        sessions=RedisSessionStore(resolved_redis),
        codes=RedisCodeStore(resolved_redis, resolved_clock),
        rate_limiter=RedisRateLimiter(resolved_redis),
        cache=InMemoryCache(resolved_clock) if cache is None else cache,
        rng=random.Random(TEST_RNG_SEED) if rng is None else rng,
        postcodes=FixedPostcodeLocator({}, {}),
        travel=FixedTravelTime(TravelRange(low_minutes=10, high_minutes=20, source="test fixed")),
        geocoder=FixedGeocoder({}),
        terminology=FixedTerminology({}, {}),
        http=None,
        telemetry=(
            FixtureTelemetryQuery(TELEMETRY_FIXTURE, result_attributes)
            if telemetry is None
            else telemetry
        ),
        scheduled_work=_scheduled_work(
            uow_factory, resolved_clock, resolved_ids, store, link_base_url
        ),
    )
