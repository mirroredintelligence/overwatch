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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
from diucs.adapters.outbound.graph_store.invariants import Neo4jTenantInvariants
from diucs.adapters.outbound.graph_store.migrations import apply_migrations
from diucs.adapters.outbound.graph_store.tenant_directory import Neo4jTenantDirectory
from diucs.adapters.outbound.graph_store.tenant_registry import Neo4jTenantRegistry
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
from diucs.application.actor import system_actor
from diucs.application.ports.outbound.cache import Cache, PlatformSlots
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
from diucs.application.ports.outbound.identity import (
    CodeStore,
    RateLimiter,
    SessionStore,
    TenantKeyedSecrets,
)
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.invariants import (
    TenantInvariants,
    TenantInvariantViolated,
)
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.telemetry_query import (
    SessionFilters,
    SessionSummary,
    SpanRecord,
    TelemetryQuery,
    TelemetryUnavailable,
    TimelineEvent,
)
from diucs.application.ports.outbound.tenant_registry import TenantRegistry
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.terminology import FhirValidator, Terminology
from diucs.application.ports.outbound.tokens import (
    LinkTokenRepository,
    LinkTokenService,
    SecretStore,
)
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, bind_tenant, current_tenant
from diucs.application.tenant_settings import (
    DirectoryLinkBase,
    DirectoryZones,
    LinkBases,
    TenantZones,
)
from diucs.application.use_cases.alerts import (
    EscalateAlert,
    EscalateAlertCommand,
    NotUpdatedCheck,
    NotUpdatedCheckCommand,
)
from diucs.application.use_cases.booking_timers import (
    BookingPhonePrompt,
    ExpireBooking,
    booking_timer_handlers,
)
from diucs.application.use_cases.criteria_reviews import (
    RunCriteriaReviews,
    RunCriteriaReviewsCommand,
    ensure_daily_schedule,
)
from diucs.application.use_cases.missed_report_ladder import (
    LADDER_KINDS,
    LadderStepCommand,
    MissedReportLadder,
)
from diucs.application.use_cases.request_booking import LinkBaseUrlFor
from diucs.application.use_cases.review_registration import AreaDistrictsFor
from diucs.application.use_cases.suspend_service import WordingFor
from diucs.application.use_cases.tenant_invariants import (
    InvariantMonitor,
    RunInvariantCheck,
    RunInvariantCheckCommand,
    ensure_invariant_schedule,
)
from diucs.application.use_cases.withdraw_booking import (
    EscalateWithdrawal,
    EscalateWithdrawalCommand,
)
from diucs.application.work import ScheduledWork, WorkKind
from diucs.bootstrap.areas import area_districts_for
from diucs.bootstrap.settings import Settings
from diucs.domain.errors import NotFound
from diucs.domain.model.telemetry_aggregates import DayAggregates
from diucs.domain.model.tenant import TenantWording
from diucs.domain.rules.tenant_keys import check_key_version

TEST_NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)
# The sample telemetry the test container serves (O07). Sample values only.
TELEMETRY_FIXTURE = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "telemetry" / "s-7f3a.json"
)
TEST_LINK_BASE_URL = "https://diucs.example"
TEST_RNG_SEED = 20261023

SCHEDULER_CHANNEL = "scheduler"
"""The channel of the scheduled-work queue's steps (DEC-193). Its actor is a system actor of the
tenant the step runs in, built per step: there is no platform-wide actor (TEN-018)."""


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
    # The registry's writes (TEN-028, DEC-503): the platform operator's door, held only by the
    # operator use cases (`bootstrap/provisioning.py`) and never by a tenant's own code.
    tenant_registry: TenantRegistry
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
    # The cache's platform namespace (TEN-040): the source-address limiter of the routes with no
    # token counts here, before any tenant is known. The same Redis client as `cache`.
    platform_slots: PlatformSlots
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
    # The tenant invariant check (TEN-031): nodes with no tenantId and relationships between two
    # scopes. Global statements on the one connection; the start-up refuses on a violation and the
    # daily job (scheduled work) raises the monitor's flag.
    invariants: TenantInvariants
    invariant_monitor: InvariantMonitor
    # The dispatch table of the scheduled.work queue: the missed-report ladder steps (I05, DEC-192).
    scheduled_work: ScheduledWorkDispatcher
    # Seals the text code (and any other secret content) before it is written to the outbox, so
    # only the sender that opens it ever sees it (U25, R11).
    sealer: ContentSealer
    # The area of each tenant for the registration review (U28, DEC-317): no default, so a tenant
    # with no entry in the settings has an empty area (R11 wiring, bootstrap/wiring.py).
    area_districts_for: AreaDistrictsFor
    # The link host of a tenant and the wording its booking messages print (R09, L02). Neither has a
    # source in production yet (tenant configuration: TEN-022, TEN-028), so the production profile
    # fails closed: no host is an error, no wording a refused request (H-T15).
    link_base_url_for: LinkBaseUrlFor
    wording_for: WordingFor
    # Each later task adds one field here, and wires it in build() and build_for_tests().

    async def startup(self) -> None:
        """Open the Neo4j connection, apply the migrations that are not yet recorded, make sure each
        active tenant's audit head exists and check the tenant invariants. Raises
        Neo4jConnectionError when Neo4j cannot be reached, the failure of a migration, or
        TenantInvariantViolated when a node has no tenant (TEN-031), and closes the connection in
        every case after the first, so the process does not start and leaves nothing open."""
        await self.neo4j.open()
        try:
            driver = self.neo4j.driver
            await apply_migrations(driver)
            # One chain per scope (TEN-017): each active tenant gets its head, bound in turn. A
            # tenant with no head fails closed at its first append (AuditHeadMissing).
            # A tenant record whose hash key version disagrees with its id would hash with a key its
            # stored hashes were not made with (TEN-023): the process does not start.
            for tenant in await self.tenants.list_active():
                check_key_version(tenant.id, tenant.hash_key_version)
            for tenant_id in await self.tenants.active_tenant_ids():
                with bind_tenant(tenant_id):
                    await ensure_audit_head(driver)
            # Neo4j Community cannot require a tenant on a node (TEN-031): count the nodes that
            # have none, after the migrations have stamped what they stamp, and do not start on
            # any. The same check runs daily as scheduled work.
            report = await self.invariants.check()
            self.invariant_monitor.record(report)
            if not report.ok:
                raise TenantInvariantViolated(report)
        except BaseException:
            await self.neo4j.close()
            raise

    async def seed_daily_schedules(self, tenant_ids: Sequence[str]) -> None:
        """Seed the daily criteria review run (U31) and the daily tenant invariant check (TEN-031)
        for each tenant, once. Each tenant is bound in turn, as the start-up does for the audit
        heads (TEN-017). Idempotent: a second start writes nothing."""
        for tenant_id in tenant_ids:
            with bind_tenant(tenant_id):
                await ensure_daily_schedule(self.uow_factory, self.ids, self.clock)
                await ensure_invariant_schedule(self.uow_factory, self.ids, self.clock)

    async def shutdown(self) -> None:
        if self.http is not None:
            await self.http.aclose()
        try:
            await self.neo4j.close()
        finally:
            await self.redis.aclose()


def _no_link_host(scope: ScopeId) -> str:
    """Production has no link host for a tenant yet (TEN-028): a booking request is refused."""
    raise RuntimeError("no link host is configured for this tenant")


async def _no_wording(scope: ScopeId) -> TenantWording | None:
    """Production has no wording for a tenant yet (TEN-022): a booking request is refused."""
    return None


async def _test_wording(scope: ScopeId) -> TenantWording | None:
    return TenantWording(
        system_name="Test system",
        referral_system_name="Test referral system",
        coordination_team_name="The SPOA shift lead",
    )


def _test_link_host(link_base_url: str) -> LinkBaseUrlFor:
    def link_host(scope: ScopeId) -> str:
        return link_base_url

    return link_host


def ladder_handlers(ladder: MissedReportLadder) -> dict[WorkKind, WorkHandler]:
    """The three ladder kinds, each run as one ladder step keyed by the work's id (DEC-193)."""

    async def step(work: ScheduledWork) -> None:
        await ladder.execute(
            LadderStepCommand(
                idempotency_key=work.id,
                actor=system_actor(current_tenant(), SCHEDULER_CHANNEL),
                work_id=work.id,
            )
        )

    return {kind: step for kind in LADDER_KINDS}


def criteria_review_handler(job: RunCriteriaReviews) -> WorkHandler:
    """The daily criteria review run (U31), run once for each scheduled work of its kind."""

    async def step(work: ScheduledWork) -> None:
        await job.execute(RunCriteriaReviewsCommand(work_id=work.id))

    return step


def invariant_check_handler(job: RunInvariantCheck) -> WorkHandler:
    """The daily tenant invariant check (TEN-031), run once for each scheduled work of its kind."""

    async def step(work: ScheduledWork) -> None:
        await job.execute(RunInvariantCheckCommand(work_id=work.id))

    return step


def alert_timer_handlers(
    uow_factory: UnitOfWorkFactory,
    ids: IdGenerator,
    clock: Clock,
    zones: TenantZones | None = None,
) -> dict[WorkKind, WorkHandler]:
    """The escalation of an unacknowledged alert and the not-updated checks (U34), each run once for
    each scheduled work of its kind."""
    escalate = EscalateAlert(uow_factory, ids, clock)
    checks = NotUpdatedCheck(uow_factory, ids, clock, zones)

    async def on_escalation(work: ScheduledWork) -> None:
        await escalate.execute(EscalateAlertCommand(work_id=work.id, alert_id=work.about_id))

    async def on_check(work: ScheduledWork) -> None:
        await checks.execute(NotUpdatedCheckCommand(work_id=work.id, about_id=work.about_id))

    return {WorkKind.ALERT_ESCALATE: on_escalation, WorkKind.NOT_UPDATED_CHECK: on_check}


def withdrawal_escalation_handler(job: EscalateWithdrawal) -> WorkHandler:
    """The escalation of a booking withdrawal (U21), run once for each scheduled work of its
    kind."""

    async def step(work: ScheduledWork) -> None:
        await job.execute(EscalateWithdrawalCommand(work_id=work.id, booking_id=work.about_id))

    return step


def _scheduled_work(
    uow_factory: UnitOfWorkFactory,
    clock: Clock,
    ids: IdGenerator,
    secrets: SecretStore,
    link_base_url: str | LinkBases,
    invariants: TenantInvariants,
    monitor: InvariantMonitor,
    zones: TenantZones | None = None,
) -> ScheduledWorkDispatcher:
    """The dispatch table, built on the same clock, ids and secrets as the rest of the container.
    `link_base_url` is the tenant source of the reminder's link and `zones` of the tenant's time
    zone: the serving process passes the directory's (TEN-027), the test container a fixed base
    and London."""

    def tokens(repo: LinkTokenRepository) -> LinkTokenService:
        return LinkTokenService(repo, secrets, clock)

    ladder = MissedReportLadder(
        uow_factory, clock, ids, tokens, link_base_url, AesGcmContentSealer(secrets), zones
    )
    handlers: dict[WorkKind, WorkHandler] = dict(ladder_handlers(ladder))
    # The booking timers (U19): the advisor's phone prompt and the expiry of a request.
    handlers.update(
        booking_timer_handlers(
            BookingPhonePrompt(uow_factory, clock), ExpireBooking(uow_factory, clock)
        )
    )
    # The daily criteria review run (U31).
    reviews = RunCriteriaReviews(uow_factory, ids, clock, AesGcmContentSealer(secrets))
    handlers[WorkKind.CRITERIA_REVIEW_REMINDER] = criteria_review_handler(reviews)
    # The daily tenant invariant check (TEN-031).
    handlers[WorkKind.INVARIANT_CHECK] = invariant_check_handler(
        RunInvariantCheck(uow_factory, ids, clock, invariants, monitor)
    )
    # The escalation of an unacknowledged booking withdrawal (U21).
    handlers[WorkKind.WITHDRAWAL_ESCALATE] = withdrawal_escalation_handler(
        EscalateWithdrawal(uow_factory, clock)
    )
    # The alert escalation and the not-updated checks (U34).
    handlers.update(alert_timer_handlers(uow_factory, ids, clock, zones))
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

    async def daily_aggregates(self, day: date) -> DayAggregates:
        raise TelemetryUnavailable

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
    # Every hash and token key is the bound tenant's own (TEN-023, DEC-350): the process's store is
    # seen through TenantKeyedSecrets, and nothing outside it holds the platform key.
    store: SecretStore = TenantKeyedSecrets(NoSecrets() if secrets is None else secrets)
    uow_factory = neo4j_uow_factory(neo4j, clock=clock)
    invariants = Neo4jTenantInvariants(neo4j)
    monitor = InvariantMonitor()
    redis_cache = RedisCache(redis)
    directory = Neo4jTenantDirectory(neo4j)
    return Container(
        clock=clock,
        ids=ids,
        neo4j=neo4j,
        uow_factory=uow_factory,
        tenants=directory,
        tenant_registry=Neo4jTenantRegistry(neo4j),
        secrets=store,
        validator=ProfileValidator(),
        redis=redis,
        sessions=RedisSessionStore(redis),
        codes=RedisCodeStore(redis, clock),
        rate_limiter=RedisRateLimiter(redis),
        cache=redis_cache,
        platform_slots=redis_cache,
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
        invariants=invariants,
        invariant_monitor=monitor,
        scheduled_work=_scheduled_work(
            uow_factory,
            clock,
            ids,
            store,
            # Each tenant's links are on its own host (DEC-134 item 3); only the default tenant,
            # which has no host of its own, falls back to the platform's base URL.
            DirectoryLinkBase(directory, fallback=settings.base_url),
            invariants,
            monitor,
            DirectoryZones(directory),
        ),
        sealer=AesGcmContentSealer(store),
        area_districts_for=area_districts_for(settings.tenant_areas),
        link_base_url_for=_no_link_host,
        wording_for=_no_wording,
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
    areas: Mapping[str, str] | None = None,
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
    invariants = Neo4jTenantInvariants(neo4j)
    monitor = InvariantMonitor()
    memory = InMemoryCache(resolved_clock)
    resolved_cache = memory if cache is None else cache
    return Container(
        clock=resolved_clock,
        ids=resolved_ids,
        neo4j=neo4j,
        uow_factory=uow_factory,
        tenants=Neo4jTenantDirectory(neo4j),
        tenant_registry=Neo4jTenantRegistry(neo4j),
        secrets=store,
        validator=ProfileValidator(),
        redis=resolved_redis,
        sessions=RedisSessionStore(resolved_redis),
        codes=RedisCodeStore(resolved_redis, resolved_clock),
        rate_limiter=RedisRateLimiter(resolved_redis),
        cache=resolved_cache,
        platform_slots=resolved_cache if isinstance(resolved_cache, PlatformSlots) else memory,
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
        invariants=invariants,
        invariant_monitor=monitor,
        scheduled_work=_scheduled_work(
            uow_factory, resolved_clock, resolved_ids, store, link_base_url, invariants, monitor
        ),
        sealer=AesGcmContentSealer(store),
        area_districts_for=area_districts_for({} if areas is None else areas),
        link_base_url_for=_test_link_host(link_base_url),
        wording_for=_test_wording,
    )
