"""The serving process of the HTTP API (B1, N3, KI-243, KI-537, KI-527, KI-587, KI-852, KI-845):
`create_app` has a production caller. It refuses to start (and does not answer 404) when a secret
the API reads is missing or weak, sets every `app.state` collaborator a route family reads, trusts
Cloudflare for the client address and host only, and says what it started without. Synthetic
secrets and hosts only; nothing connects (the container is built and not opened)."""

import dataclasses
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from diucs.adapters.inbound.edge_proxy.cloudflare import CloudflareEdgeMiddleware
from diucs.adapters.testing.fake_identity_verifier import FakeIdentityVerifier
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_event_bus import ManualEventBus
from diucs.application.ports.outbound.identity_verifier import Audience, IdentityRejected
from diucs.application.tenancy import bind_tenant
from diucs.bootstrap import api_main
from diucs.bootstrap.api_main import (
    EDGE_ORIGIN_SECRET,
    REQUIRED_SECRETS,
    ApiConfigError,
    ApiParts,
    RefusingIdentityVerifier,
    build_api,
    check_secrets,
    check_settings,
    create_serving_app,
    edge_for,
    serving_lifespan,
    startup_warnings,
)
from diucs.bootstrap.container import build
from diucs.bootstrap.settings import Settings

GOOD = b"synthetic-secret-for-the-api-tests-0123456789ab"
CLOUDFLARE_PEER = "173.245.48.10"
OTHER_PEER = "203.0.113.9"
VISITOR = "198.51.100.77"


def _secrets(**missing: object) -> FixedSecretStore:
    return FixedSecretStore({name: GOOD for name in REQUIRED_SECRETS if name not in missing})


def _parts(secrets: FixedSecretStore | None = None) -> ApiParts:
    return ApiParts(
        secrets=_secrets() if secrets is None else secrets,
        verifier=FakeIdentityVerifier(),
        event_bus=ManualEventBus(_clock()),
    )


def _clock() -> Any:
    from datetime import UTC, datetime

    from diucs.adapters.testing.fixed_clock import FixedClock

    return FixedClock(datetime(2026, 10, 31, 9, 0, tzinfo=UTC))


# ---- the secrets: a missing or weak one stops start-up


def test_every_secret_the_api_reads_is_required() -> None:
    assert {"bff-jwt", "account-ref", "link-token", "phone-hash", "device-token"} <= set(
        REQUIRED_SECRETS
    )
    assert {"link-csrf", "code-hmac", "pin-hmac", "support-code"} <= set(REQUIRED_SECRETS)


def test_a_store_that_holds_every_secret_passes() -> None:
    check_secrets(_secrets())


@pytest.mark.parametrize("name", sorted(REQUIRED_SECRETS))
def test_a_missing_secret_stops_start_up_and_is_named_without_a_value(name: str) -> None:
    with pytest.raises(ApiConfigError) as stopped:
        check_secrets(FixedSecretStore({n: GOOD for n in REQUIRED_SECRETS if n != name}))

    assert name in str(stopped.value)
    assert GOOD.decode() not in str(stopped.value)


def test_a_store_with_no_secrets_names_each_missing_secret() -> None:
    with pytest.raises(ApiConfigError) as stopped:
        check_secrets(FixedSecretStore({}))

    for name in REQUIRED_SECRETS:
        assert name in str(stopped.value)


@pytest.mark.parametrize("name", ["bff-jwt", "link-token", "account-ref"])
def test_a_weak_secret_stops_start_up(name: str) -> None:
    store = FixedSecretStore({**{n: GOOD for n in REQUIRED_SECRETS}, name: b"weakvalue"})

    with pytest.raises(ApiConfigError) as stopped:
        check_secrets(store)

    assert name in str(stopped.value)
    assert "weakvalue" not in str(stopped.value)


def test_preparing_the_process_with_a_missing_secret_stops_before_anything_is_built() -> None:
    with pytest.raises(ApiConfigError):
        create_serving_app(Settings(), _parts(_secrets(**{"bff-jwt": 1})))


# ---- the settings


def test_the_production_profile_refuses_the_placeholder_public_url() -> None:
    with pytest.raises(ApiConfigError, match="DIUCS_BASE_URL"):
        check_settings(Settings(profile="production"))


def test_the_production_profile_refuses_a_public_url_that_is_not_https() -> None:
    with pytest.raises(ApiConfigError, match="DIUCS_BASE_URL"):
        check_settings(Settings(profile="production", base_url="http://capacity.example.org"))


def test_the_production_profile_accepts_an_https_public_url() -> None:
    check_settings(Settings(profile="production", base_url="https://capacity.example.org"))


def test_the_test_profile_accepts_the_default_url() -> None:
    check_settings(Settings())


def test_an_enabled_synthetic_hook_is_refused_until_an_issuer_is_built() -> None:
    settings = Settings(
        synthetic_enabled=True, synthetic_hook_token=SecretStr("t" * 32), synthetic_tenant_id="x-1"
    )

    with pytest.raises(ApiConfigError, match="synthetic"):
        check_settings(settings)


def test_an_operator_directory_that_is_not_a_guid_is_refused() -> None:
    with pytest.raises(ApiConfigError, match="DIUCS_OPERATOR_DIRECTORY_ID"):
        check_settings(Settings(operator_directory_id="not-a-guid"))


def test_an_operator_directory_guid_is_accepted() -> None:
    check_settings(Settings(operator_directory_id="11111111-2222-3333-4444-555555555555"))


# ---- the app: every route family has its collaborators


STATE_NAMES = (
    "container",
    "secrets",
    "cache",
    "token_exchange",
    "link_pages",
    "sms_webhook",
    "network_services",
    "network_admin",
    "platform_services",
    "tenant_admin_services",
)


async def _app(settings: Settings | None = None, parts: ApiParts | None = None) -> FastAPI:
    resolved = Settings() if settings is None else settings
    container = build(resolved, secrets=(parts or _parts()).secrets)
    return build_api(resolved, container, parts or _parts())


async def test_every_route_family_has_its_app_state_set() -> None:
    app = await _app()

    missing = [name for name in STATE_NAMES if getattr(app.state, name, None) is None]

    assert missing == []


async def test_the_app_state_is_the_containers_own_cache_and_the_platform_secret_store() -> None:
    parts = _parts()
    app = await _app(parts=parts)

    assert app.state.cache is app.state.container.cache
    assert app.state.secrets is parts.secrets


async def test_the_exchange_is_given_the_verifier_directory_and_platform_chain() -> None:
    parts = _parts()
    settings = Settings(operator_directory_id="11111111-2222-3333-4444-555555555555")
    app = await _app(settings, parts)

    deps = app.state.token_exchange

    assert deps.verifier is parts.verifier
    assert deps.operator_directory_id == "11111111-2222-3333-4444-555555555555"
    assert deps.platform_audit is app.state.container.platform_audit


async def test_the_sms_webhook_reads_its_lines_from_the_tenant_directory() -> None:
    from diucs.application.tenant_resolution import DirectoryInboundLines

    app = await _app(Settings(base_url="https://capacity.example.org/"))

    deps = app.state.sms_webhook

    assert isinstance(deps.lines, DirectoryInboundLines)
    assert deps.public_base_url == "https://capacity.example.org/"
    assert deps.event_bus is not None


async def test_the_synthetic_hook_is_not_mounted_open() -> None:
    app = await _app()

    assert app.state.synthetic is None


async def test_the_health_route_answers_with_no_secret_and_no_store() -> None:
    app = await _app()
    transport = ASGITransport(app=app, client=(OTHER_PEER, 1))

    async with AsyncClient(transport=transport, base_url="http://internal") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---- the edge


async def _probe_app(settings: Settings, parts: ApiParts | None = None) -> FastAPI:
    app = await _app(settings, parts)

    @app.get("/probe")
    async def probe(request: Request) -> dict[str, Any]:
        return {
            "client": None if request.client is None else request.client.host,
            "host": request.headers.get("host"),
        }

    return app


async def _probe(app: FastAPI, peer: str, headers: dict[str, str]) -> dict[str, Any]:
    transport = ASGITransport(app=app, client=(peer, 1))
    async with AsyncClient(transport=transport, base_url="http://internal:8000") as client:
        response = await client.get("/probe", headers=headers)
    body: dict[str, Any] = response.json()
    return body


async def test_the_app_trusts_cloudflare_for_the_client_address_and_host() -> None:
    app = await _probe_app(Settings())

    body = await _probe(
        app,
        CLOUDFLARE_PEER,
        {"CF-Connecting-IP": VISITOR, "X-Forwarded-Host": "alpha.example.org"},
    )

    assert body == {"client": VISITOR, "host": "alpha.example.org"}


async def test_the_app_does_not_trust_a_forged_header_from_another_peer() -> None:
    app = await _probe_app(Settings())

    body = await _probe(
        app, OTHER_PEER, {"CF-Connecting-IP": VISITOR, "X-Forwarded-Host": "alpha.example.org"}
    )

    assert body == {"client": OTHER_PEER, "host": "internal:8000"}


async def test_the_app_has_the_edge_as_its_outermost_layer() -> None:
    app = await _app()

    assert app.user_middleware[0].cls is CloudflareEdgeMiddleware


def test_the_edge_defaults_to_cloudflare() -> None:
    edge = edge_for(Settings(), FixedSecretStore({}))

    assert edge.trust_cloudflare is True
    assert edge.origin_secret is None


def test_an_edge_of_none_trusts_no_published_range() -> None:
    edge = edge_for(Settings(edge="none"), FixedSecretStore({}))

    assert edge.trust_cloudflare is False


def test_the_origin_secret_is_read_from_the_secret_store() -> None:
    edge = edge_for(Settings(), FixedSecretStore({EDGE_ORIGIN_SECRET: GOOD}))

    assert edge.origin_secret == GOOD


def test_a_weak_origin_secret_stops_start_up() -> None:
    with pytest.raises(ApiConfigError, match=EDGE_ORIGIN_SECRET):
        edge_for(Settings(), FixedSecretStore({EDGE_ORIGIN_SECRET: b"weakvalue"}))


def test_trusted_peers_are_parsed_and_a_bad_one_stops_start_up() -> None:
    edge = edge_for(Settings(edge_trusted_peers=["10.0.0.0/8"]), FixedSecretStore({}))

    assert edge.peer_is_trusted("10.2.3.4")
    with pytest.raises(ApiConfigError, match="DIUCS_EDGE_TRUSTED_PEERS"):
        edge_for(Settings(edge_trusted_peers=["nonsense"]), FixedSecretStore({}))


def test_the_published_ranges_can_be_replaced_from_a_file(tmp_path: Path) -> None:
    ranges = tmp_path / "ranges.txt"
    ranges.write_text("# refreshed 2026-12-01\n192.0.2.0/24\n\n2001:db8::/32\n")

    edge = edge_for(Settings(edge_cloudflare_ranges_file=ranges), FixedSecretStore({}))

    assert edge.peer_is_trusted("192.0.2.7")
    assert edge.peer_is_trusted("2001:db8::1")
    assert not edge.peer_is_trusted(CLOUDFLARE_PEER)


def test_an_unreadable_or_bad_ranges_file_stops_start_up(tmp_path: Path) -> None:
    bad = tmp_path / "bad.txt"
    bad.write_text("not a range\n")

    with pytest.raises(ApiConfigError, match="DIUCS_EDGE_CLOUDFLARE_RANGES_FILE"):
        edge_for(Settings(edge_cloudflare_ranges_file=bad), FixedSecretStore({}))
    with pytest.raises(ApiConfigError, match="DIUCS_EDGE_CLOUDFLARE_RANGES_FILE"):
        edge_for(
            Settings(edge_cloudflare_ranges_file=tmp_path / "missing.txt"), FixedSecretStore({})
        )


# ---- the identity verifier that is not built yet


async def test_the_refusing_verifier_refuses_every_sign_in_for_both_audiences() -> None:
    verifier = RefusingIdentityVerifier()

    for audience in Audience:
        with pytest.raises(IdentityRejected):
            await verifier.verify("any-credential", audience)


def test_the_refusing_verifier_is_reported_at_start_up() -> None:
    container = build(Settings(), secrets=_secrets())
    parts = dataclasses.replace(_parts(), verifier=RefusingIdentityVerifier())

    warnings = startup_warnings(Settings(), container, parts)

    assert any("sign-in" in warning for warning in warnings)


# ---- what the process starts without


def test_a_process_with_no_centroids_key_telemetry_or_operator_says_so() -> None:
    container = build(Settings(), secrets=_secrets())

    warnings = startup_warnings(Settings(), container, _parts())

    text = " ".join(warnings)
    for word in ("postcode", "address", "telemetry", "operator"):
        assert word in text


def test_a_fully_configured_process_has_no_warnings(tmp_path: Path) -> None:
    centroids = tmp_path / "centroids.csv"
    centroids.write_text("postcode,latitude,longitude\nDT4 8XX,50.6,-2.4\n")
    settings = Settings(
        postcode_centroids_path=centroids,
        os_places_api_key=SecretStr("k" * 20),
        telemetry_workspace_id="workspace-1",
        operator_directory_id="11111111-2222-3333-4444-555555555555",
    )
    container = build(settings, secrets=_secrets())
    parts = _parts()

    class _Client:
        pass

    from diucs.adapters.outbound.telemetry.azure_monitor_query import AzureMonitorTelemetryQuery

    container = dataclasses.replace(
        container,
        telemetry=AzureMonitorTelemetryQuery(_Client(), "workspace-1", container.clock),  # type: ignore[arg-type]
    )

    assert startup_warnings(settings, container, parts) == []


# ---- the lifespan


class _Lifecycle:
    def __init__(self, events: list[str], fail: bool = False) -> None:
        self._events = events
        self._fail = fail

    async def startup(self) -> None:
        self._events.append("startup")
        if self._fail:
            raise RuntimeError("neo4j down")

    async def shutdown(self) -> None:
        self._events.append("shutdown")


def _closer(events: list[str], name: str) -> Callable[[], Awaitable[None]]:
    async def close() -> None:
        events.append(name)

    return close


async def test_the_lifespan_starts_the_container_and_closes_everything_on_exit() -> None:
    events: list[str] = []
    lifespan = serving_lifespan(
        _Lifecycle(events), (_closer(events, "bus"), _closer(events, "client")), lambda: ["w"]
    )

    async with lifespan(FastAPI()):
        events.append("serving")

    assert events == ["startup", "serving", "client", "bus", "shutdown"]


async def test_the_lifespan_closes_what_it_opened_when_the_container_will_not_start() -> None:
    events: list[str] = []
    lifespan = serving_lifespan(
        _Lifecycle(events, fail=True), (_closer(events, "bus"),), lambda: []
    )

    with pytest.raises(RuntimeError):
        async with lifespan(FastAPI()):
            events.append("serving")  # pragma: no cover

    assert "serving" not in events
    assert "bus" in events


async def test_the_lifespan_logs_each_warning_once(caplog: pytest.LogCaptureFixture) -> None:
    events: list[str] = []
    lifespan = serving_lifespan(_Lifecycle(events), (), lambda: ["no thing", "no other thing"])

    with caplog.at_level(logging.WARNING, logger=api_main.log.name):
        async with lifespan(FastAPI()):
            pass

    assert [r.getMessage() for r in caplog.records] == [
        "start-up: no thing",
        "start-up: no other thing",
    ]


# ---- the entry point


def test_the_entry_point_stops_when_the_process_has_no_secret_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_SERVICEBUS_CONNECTION", "Endpoint=sb://x/;SharedAccessKey=y")
    monkeypatch.setattr(api_main, "load_secret_store", lambda settings: None)

    with pytest.raises(SystemExit) as stopped:
        api_main.main()

    assert "secret store" in str(stopped.value)


def test_the_entry_point_stops_without_a_service_bus_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DIUCS_SERVICEBUS_CONNECTION", raising=False)

    with pytest.raises(SystemExit) as stopped:
        api_main.main()

    assert "DIUCS_SERVICEBUS_CONNECTION" in str(stopped.value)


def test_with_no_vault_and_no_directory_no_secret_store_is_built() -> None:
    assert api_main.load_secret_store(Settings()) is None


async def test_the_container_of_the_app_is_not_opened_by_building_it() -> None:
    app = await _app()
    container = app.state.container

    with bind_tenant("tenant-api-a"):
        assert container.neo4j.open_session_count == 0
