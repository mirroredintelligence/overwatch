import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncGraphDatabase
from redis.asyncio import Redis

from diucs.adapters.outbound.cache_redis.code_store import RedisCodeStore
from diucs.adapters.outbound.cache_redis.sessions import RedisRateLimiter, RedisSessionStore
from diucs.adapters.outbound.clock_system.system_clock import SystemClock
from diucs.adapters.outbound.graph_store import connection as connection_module
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection, Neo4jPoolOptions
from diucs.adapters.outbound.graph_store.tenant_directory import Neo4jTenantDirectory
from diucs.adapters.outbound.ids_uuid.uuid_ids import UuidGenerator
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.identity import TenantKeyedSecrets
from diucs.application.tenancy import (
    DEFAULT_TENANT_ID,
    bind_tenant,
    current_scope,
    current_scope_or_none,
)
from diucs.application.work import WorkKind
from diucs.bootstrap import container as container_module
from diucs.bootstrap.container import build, build_for_tests
from diucs.bootstrap.settings import Settings
from diucs.domain.errors import NotFound
from diucs.domain.model.tenant import Tenant
from diucs.domain.rules.tenant_keys import KeyVersionMismatch, derive_tenant_key
from tests.support.tenant_samples import make_tenant

TEST_NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def neo4j() -> AsyncIterator[Neo4jConnection]:
    """One connection per test, shared by every container the test builds. Nothing here opens it."""
    connection = Neo4jConnection("bolt://localhost:1", "neo4j", "unused-without-a-session")
    try:
        yield connection
    finally:
        await connection.close()


async def test_build_wires_the_system_clock_and_uuid_ids() -> None:
    container = build(Settings())
    try:
        assert isinstance(container.clock, SystemClock)
        assert isinstance(container.ids, UuidGenerator)
    finally:
        await container.shutdown()


async def test_build_for_tests_defaults_to_a_fixed_clock_at_the_test_time(
    neo4j: Neo4jConnection,
) -> None:
    container = build_for_tests(neo4j=neo4j)
    assert container.clock.now() == TEST_NOW
    assert isinstance(container.ids, SequentialIds)


async def test_build_for_tests_uses_a_clock_that_is_passed_in(neo4j: Neo4jConnection) -> None:
    later = datetime(2026, 12, 1, 8, 30, tzinfo=UTC)
    container = build_for_tests(clock=FixedClock(later), neo4j=neo4j)
    assert container.clock.now() == later


async def test_container_is_frozen(neo4j: Neo4jConnection) -> None:
    container = build_for_tests(neo4j=neo4j)
    with pytest.raises(dataclasses.FrozenInstanceError):
        container.clock = SystemClock()  # type: ignore[misc]


async def test_build_for_tests_shares_the_connection_it_is_given(neo4j: Neo4jConnection) -> None:
    first = build_for_tests(neo4j=neo4j)
    second = build_for_tests(neo4j=neo4j)
    assert first.neo4j is neo4j
    assert second.neo4j is neo4j


async def test_build_wires_one_neo4j_connection_from_settings() -> None:
    container = build(Settings())
    try:
        assert isinstance(container.neo4j, Neo4jConnection)
    finally:
        await container.shutdown()


async def test_build_passes_the_dec_012_pool_settings_to_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_MAX_CONNECTION_LIFETIME_S", "600")
    monkeypatch.setenv("DIUCS_NEO4J_LIVENESS_CHECK_TIMEOUT_S", "5")
    monkeypatch.setenv("DIUCS_NEO4J_CONNECTION_ACQUISITION_TIMEOUT_S", "2")
    monkeypatch.setenv("DIUCS_NEO4J_MAX_CONNECTION_POOL_SIZE", "7")
    container = build(Settings())
    try:
        assert container.neo4j.pool_options == Neo4jPoolOptions(
            max_connection_lifetime=600.0,
            liveness_check_timeout=5.0,
            connection_acquisition_timeout=2.0,
            max_connection_pool_size=7,
        )
    finally:
        await container.shutdown()


async def test_build_for_tests_makes_no_driver_calls(
    neo4j: Neo4jConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEC-012: one driver per process, never per test. build_for_tests only uses the connection it
    is given, so neither factory may be called while it builds containers."""
    calls: list[str] = []

    def _spy(name: str) -> Callable[..., AsyncDriver]:
        def _record(*args: object, **kwargs: object) -> AsyncDriver:
            calls.append(name)
            raise AssertionError(f"build_for_tests must not call {name}")

        return _record

    monkeypatch.setattr(connection_module, "create_driver", _spy("create_driver"))
    monkeypatch.setattr(AsyncGraphDatabase, "driver", _spy("AsyncGraphDatabase.driver"))

    build_for_tests(neo4j=neo4j)
    build_for_tests(clock=FixedClock(TEST_NOW), neo4j=neo4j)

    assert calls == []


def test_build_for_tests_requires_the_connection_to_be_passed_in() -> None:
    with pytest.raises(TypeError):
        build_for_tests()  # type: ignore[call-arg]


# TEN-007: the tenant directory and the secret store on the container, and start-up


class _FakeConnection:
    """Stands in for Neo4jConnection: records the order of what the container does with it."""

    def __init__(self, events: list[str], *, fail_open: bool = False) -> None:
        self.events = events
        self.fail_open = fail_open
        self.reads = 0
        self.the_driver = object()

    async def open(self) -> None:
        self.events.append("open")
        if self.fail_open:
            raise RuntimeError("cannot connect")

    async def close(self) -> None:
        self.events.append("close")

    @property
    def driver(self) -> object:
        self.events.append("driver")
        return self.the_driver

    async def run_read(self, work: Callable[..., Awaitable[object]]) -> object:
        self.reads += 1
        return []


async def test_the_container_carries_the_tenant_directory_on_its_own_connection() -> None:
    connection = _FakeConnection([])
    container = build_for_tests(neo4j=cast(Neo4jConnection, connection))
    assert isinstance(container.tenants, Neo4jTenantDirectory)
    assert await container.tenants.get("example-icb") is None
    assert connection.reads == 1


async def test_build_wires_the_directory_over_the_one_connection(neo4j: Neo4jConnection) -> None:
    container = build(Settings())
    try:
        assert isinstance(container.tenants, Neo4jTenantDirectory)
    finally:
        await container.shutdown()


async def test_build_for_tests_gives_a_recording_fake_secret_store_unless_one_is_passed(
    neo4j: Neo4jConnection,
) -> None:
    container = build_for_tests(neo4j=neo4j)
    assert isinstance(container.secrets, FixedSecretStore)
    with pytest.raises(NotFound):
        container.secrets.get("link-token")
    store = FixedSecretStore({"link-token": b"x"})
    assert build_for_tests(neo4j=neo4j, secrets=store).secrets is store


async def test_build_has_no_secret_store_until_one_is_given_and_fails_closed() -> None:
    container = build(Settings())
    try:
        with pytest.raises(NotFound, match="link-token"):
            container.secrets.get("link-token")
    finally:
        await container.shutdown()
    store = FixedSecretStore({"link-token": b"x"})
    given = build(Settings(), secrets=store)
    try:
        # The process's store is wrapped so that every hash and token key is the tenant's own
        # (TEN-023); a name that is not keyed reads straight through.
        assert isinstance(given.secrets, TenantKeyedSecrets)
        with bind_tenant("acme-icb"):
            assert given.secrets.get("link-token") == derive_tenant_key(
                b"x", "acme-icb", "link-token"
            )
        with bind_tenant(DEFAULT_TENANT_ID):
            assert given.secrets.get("link-token") == b"x"
    finally:
        await given.shutdown()


async def test_the_production_container_never_hands_out_the_platform_key_to_a_tenant() -> None:
    store = FixedSecretStore({"phone-hash": b"p" * 32, "twilio/acme-icb/auth-token": b"t"})
    container = build(Settings(), secrets=store)
    try:
        with bind_tenant("acme-icb"):
            assert container.secrets.get("phone-hash") != b"p" * 32
            assert container.secrets.get("twilio/acme-icb/auth-token") == b"t"
    finally:
        await container.shutdown()


async def test_the_container_is_still_frozen_with_the_new_fields(neo4j: Neo4jConnection) -> None:
    container = build_for_tests(neo4j=neo4j)
    with pytest.raises(dataclasses.FrozenInstanceError):
        container.tenants = None  # type: ignore[misc,assignment]
    with pytest.raises(dataclasses.FrozenInstanceError):
        container.secrets = None  # type: ignore[misc,assignment]


class _Tenants:
    """Stands in for the tenant directory: the ids the start-up binds, in order."""

    def __init__(self, ids: list[str], versions: dict[str, int] | None = None) -> None:
        self._ids = ids
        self._versions = {} if versions is None else versions

    async def active_tenant_ids(self) -> list[str]:
        return list(self._ids)

    async def list_active(self) -> list[Tenant]:
        return [
            make_tenant(id=tenant_id, hash_key_version=self._versions.get(tenant_id, 1))
            for tenant_id in self._ids
        ]


async def test_start_up_opens_the_connection_then_migrates_then_ensures_the_audit_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection = _FakeConnection(events)

    async def fake_migrate(driver: object) -> list[str]:
        assert driver is connection.the_driver
        events.append("migrate")
        return []

    async def fake_head(driver: object) -> None:
        assert driver is connection.the_driver
        events.append(f"head:{current_scope().value}")

    monkeypatch.setattr(container_module, "apply_migrations", fake_migrate)
    monkeypatch.setattr(container_module, "ensure_audit_head", fake_head)
    container = dataclasses.replace(
        build_for_tests(neo4j=cast(Neo4jConnection, connection)),
        tenants=cast(Any, _Tenants(["acme-icb"])),
    )

    await container.startup()

    assert [e for e in events if e != "driver"] == ["open", "migrate", "head:acme-icb"]


async def test_start_up_sets_up_each_active_tenants_head_in_turn_and_binds_nothing_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection = _FakeConnection(events)

    async def fake_migrate(driver: object) -> list[str]:
        return []

    async def fake_head(driver: object) -> None:
        events.append(f"head:{current_scope().value}")

    monkeypatch.setattr(container_module, "apply_migrations", fake_migrate)
    monkeypatch.setattr(container_module, "ensure_audit_head", fake_head)
    container = dataclasses.replace(
        build_for_tests(neo4j=cast(Neo4jConnection, connection)),
        tenants=cast(Any, _Tenants(["acme-icb", "bridge-ccg"])),
    )

    await container.startup()

    assert [e for e in events if e.startswith("head:")] == ["head:acme-icb", "head:bridge-ccg"]
    assert current_scope_or_none() is None


async def test_start_up_with_no_active_tenant_makes_no_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection = _FakeConnection(events)

    async def fake_migrate(driver: object) -> list[str]:
        return []

    async def fake_head(driver: object) -> None:
        events.append("head")

    monkeypatch.setattr(container_module, "apply_migrations", fake_migrate)
    monkeypatch.setattr(container_module, "ensure_audit_head", fake_head)
    container = dataclasses.replace(
        build_for_tests(neo4j=cast(Neo4jConnection, connection)),
        tenants=cast(Any, _Tenants([])),
    )

    await container.startup()

    assert "head" not in events


async def test_a_failed_migration_closes_the_connection_and_stops_the_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection = _FakeConnection(events)

    async def failing_migrate(driver: object) -> list[str]:
        raise RuntimeError("migration failed")

    async def fake_head(driver: object) -> None:
        events.append("head")

    monkeypatch.setattr(container_module, "apply_migrations", failing_migrate)
    monkeypatch.setattr(container_module, "ensure_audit_head", fake_head)
    container = build_for_tests(neo4j=cast(Neo4jConnection, connection))

    with pytest.raises(RuntimeError, match="migration failed"):
        await container.startup()

    assert "head" not in events
    assert events[-1] == "close"


async def test_a_failed_audit_head_closes_the_connection_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection = _FakeConnection(events)

    async def fake_migrate(driver: object) -> list[str]:
        return []

    async def failing_head(driver: object) -> None:
        raise RuntimeError("no head")

    monkeypatch.setattr(container_module, "apply_migrations", fake_migrate)
    monkeypatch.setattr(container_module, "ensure_audit_head", failing_head)
    container = dataclasses.replace(
        build_for_tests(neo4j=cast(Neo4jConnection, connection)),
        tenants=cast(Any, _Tenants(["acme-icb"])),
    )

    with pytest.raises(RuntimeError, match="no head"):
        await container.startup()

    assert events[-1] == "close"


async def test_a_connection_that_will_not_open_stops_the_start_before_any_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection = _FakeConnection(events, fail_open=True)

    async def fake_migrate(driver: object) -> list[str]:
        events.append("migrate")
        return []

    monkeypatch.setattr(container_module, "apply_migrations", fake_migrate)
    container = build_for_tests(neo4j=cast(Neo4jConnection, connection))

    with pytest.raises(RuntimeError, match="cannot connect"):
        await container.startup()

    assert "migrate" not in events


async def test_build_wires_the_redis_identity_stores_from_settings() -> None:
    container = build(Settings())
    try:
        assert isinstance(container.sessions, RedisSessionStore)
        assert isinstance(container.codes, RedisCodeStore)
        assert isinstance(container.rate_limiter, RedisRateLimiter)
        assert isinstance(container.redis, Redis)
    finally:
        await container.shutdown()


async def test_build_wires_the_local_postcode_locator_and_the_straight_line_travel_estimate(
    tmp_path: Any,
) -> None:
    from diucs.adapters.outbound.postcodes_local.centroids import CsvPostcodeLocator
    from diucs.adapters.outbound.travel_time.straight_line import StraightLineTravelTime

    fixture = tmp_path / "centroids.csv"
    fixture.write_text("postcode,latitude,longitude\nDT4 8XX,50.6151,-2.4612\n", encoding="utf-8")
    container = build(Settings(postcode_centroids_path=fixture))
    try:
        assert isinstance(container.postcodes, CsvPostcodeLocator)
        assert isinstance(container.travel, StraightLineTravelTime)
    finally:
        await container.shutdown()


async def test_build_for_tests_wires_the_redis_identity_stores_without_a_server(
    neo4j: Neo4jConnection,
) -> None:
    """The stores connect lazily: building a container opens no Redis connection."""
    container = build_for_tests(neo4j=neo4j)
    assert isinstance(container.sessions, RedisSessionStore)
    assert isinstance(container.codes, RedisCodeStore)
    assert isinstance(container.rate_limiter, RedisRateLimiter)


async def test_shutdown_closes_the_redis_client_as_well_as_neo4j() -> None:
    container = build(Settings())
    closed: list[str] = []

    async def close_neo4j() -> None:
        closed.append("neo4j")

    async def close_redis() -> None:
        closed.append("redis")

    object.__setattr__(container.neo4j, "close", close_neo4j)
    object.__setattr__(container.redis, "aclose", close_redis)
    await container.shutdown()
    assert closed == ["neo4j", "redis"]


async def test_build_without_a_centroid_file_locates_nothing_rather_than_guessing(
    neo4j: Neo4jConnection,
) -> None:
    container = build_for_tests(neo4j=neo4j)

    assert container.postcodes.locate("DT4 8XX") is None


async def test_build_wires_the_pilot_terminology_and_no_geocoder_without_a_key() -> None:
    container = build(Settings())
    try:
        record = await container.terminology.ods_lookup("RDY")
        assert record is not None
        assert container.http is None
        assert await container.geocoder.find_addresses("DT1 1AA") == []
    finally:
        await container.shutdown()


async def test_build_wires_the_os_places_geocoder_and_closes_its_client_on_shutdown() -> None:
    from pydantic import SecretStr

    from diucs.adapters.outbound.geocoder_os_places.os_places import OsPlacesGeocoder

    container = build(Settings(os_places_api_key=SecretStr("test-key")))
    assert isinstance(container.geocoder, OsPlacesGeocoder)
    assert container.http is not None
    client = container.http
    await container.shutdown()
    assert client.is_closed


# -- the telemetry query (O07) -------------------------------------------------------------------

WORKSPACE = "00000000-0000-0000-0000-000000000000"


class _EmptyLogsClient:
    """A stand-in logs client that records its calls and answers an empty table."""

    def __init__(self) -> None:
        self.workspaces: list[str] = []

    async def query_workspace(self, workspace_id: str, query: str, **kwargs: Any) -> Any:
        from diucs.adapters.outbound.telemetry.azure_monitor_query import LogsTable

        self.workspaces.append(workspace_id)
        return LogsTable(columns=(), rows=())


async def test_build_for_tests_serves_the_sample_telemetry_from_the_fixture(
    neo4j: Neo4jConnection,
) -> None:
    from diucs.application.ports.outbound.telemetry_query import SessionFilters
    from diucs.application.tenancy import bind_tenant

    container = build_for_tests(neo4j=neo4j)
    with bind_tenant("test-a"):
        sessions = await container.telemetry.search_sessions(SessionFilters())
    assert [session.session_id for session in sessions] == ["s-4c81", "s-7f3a"]


async def test_build_for_tests_passes_a_telemetry_query_that_is_given(
    neo4j: Neo4jConnection,
) -> None:
    from diucs.adapters.outbound.telemetry.result_attributes import result_attributes
    from diucs.adapters.testing.fixture_telemetry import FixtureTelemetryQuery

    other = FixtureTelemetryQuery(Path(container_module.TELEMETRY_FIXTURE), result_attributes)
    container = build_for_tests(neo4j=neo4j, telemetry=other)
    assert container.telemetry is other


async def test_build_with_no_workspace_refuses_every_telemetry_read() -> None:
    from diucs.application.ports.outbound.telemetry_query import (
        SessionFilters,
        TelemetryUnavailable,
    )
    from diucs.application.tenancy import bind_tenant

    container = build(Settings())
    with bind_tenant("test-a"), pytest.raises(TelemetryUnavailable):
        await container.telemetry.search_sessions(SessionFilters())


async def test_build_with_a_workspace_but_no_client_still_refuses_every_read() -> None:
    from diucs.application.ports.outbound.telemetry_query import (
        SessionFilters,
        TelemetryUnavailable,
    )
    from diucs.application.tenancy import bind_tenant

    container = build(Settings(telemetry_workspace_id=WORKSPACE))
    with bind_tenant("test-a"), pytest.raises(TelemetryUnavailable):
        await container.telemetry.search_sessions(SessionFilters())


async def test_build_with_a_workspace_and_a_client_reads_from_that_workspace() -> None:
    from diucs.adapters.outbound.telemetry.azure_monitor_query import AzureMonitorTelemetryQuery
    from diucs.application.ports.outbound.telemetry_query import SessionFilters
    from diucs.application.tenancy import bind_tenant

    client = _EmptyLogsClient()
    container = build(Settings(telemetry_workspace_id=WORKSPACE), telemetry_client=client)
    assert isinstance(container.telemetry, AzureMonitorTelemetryQuery)
    with bind_tenant("test-a"):
        assert await container.telemetry.search_sessions(SessionFilters()) == []
    assert client.workspaces == [WORKSPACE]


async def test_build_for_tests_exposes_the_dispatcher_with_the_ladder_and_booking_kinds(
    neo4j: Neo4jConnection,
) -> None:
    container = build_for_tests(neo4j=neo4j)

    assert container.scheduled_work.kinds == frozenset(
        {
            WorkKind.REMINDER,
            WorkKind.PHONE_TASK,
            WorkKind.ESCALATE_TO_LEAD,
            WorkKind.CRITERIA_REVIEW_REMINDER,
            WorkKind.BOOKING_PHONE_PROMPT,
            WorkKind.BOOKING_EXPIRE,
        }
    )


async def test_build_exposes_the_same_dispatch_table() -> None:
    container = build(Settings())
    try:
        assert container.scheduled_work.kinds == frozenset(
            {
                WorkKind.REMINDER,
                WorkKind.PHONE_TASK,
                WorkKind.ESCALATE_TO_LEAD,
                WorkKind.CRITERIA_REVIEW_REMINDER,
                WorkKind.BOOKING_PHONE_PROMPT,
                WorkKind.BOOKING_EXPIRE,
            }
        )
    finally:
        await container.shutdown()


async def test_start_up_refuses_a_tenant_whose_hash_key_version_does_not_match_its_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection = _FakeConnection(events)

    async def fake_migrate(driver: object) -> list[str]:
        return []

    async def fake_head(driver: object) -> None:
        events.append("head")

    monkeypatch.setattr(container_module, "apply_migrations", fake_migrate)
    monkeypatch.setattr(container_module, "ensure_audit_head", fake_head)
    container = dataclasses.replace(
        build_for_tests(neo4j=cast(Neo4jConnection, connection)),
        tenants=cast(Any, _Tenants(["acme-icb"], {"acme-icb": 0})),
    )

    with pytest.raises(KeyVersionMismatch):
        await container.startup()

    assert "head" not in events
    assert events[-1] == "close"


async def test_start_up_accepts_the_default_tenant_on_the_legacy_key_and_others_on_derived_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    connection = _FakeConnection(events)

    async def fake_migrate(driver: object) -> list[str]:
        return []

    async def fake_head(driver: object) -> None:
        events.append(f"head:{current_scope().value}")

    monkeypatch.setattr(container_module, "apply_migrations", fake_migrate)
    monkeypatch.setattr(container_module, "ensure_audit_head", fake_head)
    container = dataclasses.replace(
        build_for_tests(neo4j=cast(Neo4jConnection, connection)),
        tenants=cast(Any, _Tenants([DEFAULT_TENANT_ID, "acme-icb"], {DEFAULT_TENANT_ID: 0})),
    )

    await container.startup()

    assert [e for e in events if e.startswith("head:")] == ["head:default", "head:acme-icb"]
