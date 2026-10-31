"""Process entry for the HTTP API (B1, N3): `python -m diucs.bootstrap.api_main`, or
`uvicorn diucs.bootstrap.api_main:app_factory --factory`.

Until this module nothing called `create_app`, so no process served the FHIR routes, the platform
and tenant routes, the network routes, the token exchange, the link pages or the Twilio webhook. It
is in bootstrap, the one layer that may name both the inbound adapters and the outbound ones. It
builds the container, calls `create_app`, and sets every `app.state` collaborator a route family
reads, so a route that finds one missing (a 500 by design) finds it here:

    container            create_app
    secrets              the platform's secret store (`bff-jwt` and `account-ref`, read by the edge
                         and the exchange; the keyed names are read through the container)
    cache                the container's Redis cache (write concurrency, the live streams)
    token_exchange       the identity verifier, the operator directory and the platform chain
    link_pages           the one-tap capacity link pages (cache and sealer)
    sms_webhook          Twilio's replies and receipts, over `DirectoryInboundLines`
    network_services     the network read routes (`bootstrap/network_services.py`)
    network_admin        the network administration routes
    platform_services    the operator's and support person's routes (`install_platform_routes`)
    tenant_admin_services the tenant administrator's routes (the same call)

It refuses to start, and does not answer 404 for what it cannot do, when a secret the API reads is
missing or shorter than 32 bytes (`check_secrets`), when the settings are wrong for production
(`check_settings`) or when the proxy settings do not parse (`edge_for`). Messages name a setting or
a secret, never a value. It starts, and says so at WARNING (`startup_warnings`), without a postcode
file, an address key, telemetry, an operator directory or an identity verifier: each of those fails
closed in use (nothing located, no address offered, no telemetry shown, no operator sign-in, no
staff sign-in).

The request's client address and original host are taken from Cloudflare's headers only when the
request comes from Cloudflare (`adapters/inbound/edge_proxy/cloudflare.py`, deployment-plan item
5); uvicorn's own forwarded-header handling is OFF, so nothing else decides who the client is. The
access log hides link tokens (`RedactLinkTokens`).

Not built here, because each needs a credential or a service that does not exist yet: the secret
store of the process (Key Vault: `load_secret_store`) and the Entra identity verifier
(`RefusingIdentityVerifier` stands in). Until the first exists the process exits at start-up with
a message; until the second does, every sign-in is refused.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol

import uvicorn
from azure.servicebus.aio import ServiceBusClient
from fastapi import FastAPI
from opentelemetry.sdk.trace import TracerProvider

from diucs.adapters.inbound.edge_proxy.cloudflare import (
    CLOUDFLARE_RANGES,
    CloudflareEdge,
    CloudflareEdgeMiddleware,
    IPNetwork,
    parse_ranges,
)
from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.inbound.fhir_rest.routes_auth import ExchangeDeps
from diucs.adapters.inbound.link_pages.capacity_links import (
    LinkPagesDeps,
    install_log_redaction,
)
from diucs.adapters.inbound.sms_webhook.routes import SmsWebhookDeps
from diucs.adapters.outbound.bus_servicebus.service_bus import ServiceBusEventBus
from diucs.adapters.outbound.telemetry.azure_monitor_query import LogsQueryClient
from diucs.adapters.outbound.telemetry.otel import configure_telemetry
from diucs.application.ports.outbound.event_bus import EventBus
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.ports.outbound.identity_verifier import (
    Audience,
    IdentityRejected,
    IdentityVerifier,
    VerifiedIdentity,
)
from diucs.application.ports.outbound.tenants import normalise_directory_id
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.tenant_resolution import DirectoryInboundLines
from diucs.application.use_cases.exchange_token import ACCOUNT_REF_SECRET, SIGNING_SECRET
from diucs.bootstrap.container import (
    Container,
    NoGeocoder,
    NoPostcodes,
    NoTelemetry,
    build,
)
from diucs.bootstrap.network_services import build_network_admin_services, build_network_services
from diucs.bootstrap.platform_services import install_platform_routes
from diucs.bootstrap.settings import Settings
from diucs.bootstrap.telemetry import api_instrumentation
from diucs.domain.errors import NotFound
from diucs.domain.rules.tenant_keys import PER_TENANT_KEY_NAMES

log = logging.getLogger(__name__)

REQUIRED_SECRETS: Final[tuple[str, ...]] = tuple(
    sorted({SIGNING_SECRET, ACCOUNT_REF_SECRET, PHONE_HASH_SECRET, *PER_TENANT_KEY_NAMES})
)
"""Every secret the API reads: the token signing key and account reference of the platform, and the
seven keys each tenant's own is derived from (`TenantKeyedSecrets`)."""

EDGE_ORIGIN_SECRET: Final = "edge-origin"
"""The optional secret Cloudflare adds to a request in `X-Edge-Auth` (the origin secret)."""

MIN_SECRET_BYTES: Final = 32
SERVICE_BUS_MISSING: Final = "DIUCS_SERVICEBUS_CONNECTION must be set for the API"
SECRET_STORE_MISSING: Final = (
    "no secret store is configured for the API: the Key Vault adapter is not built, and the "
    "process will not start without the secrets it reads"
)


class ApiConfigError(Exception):
    """The API cannot start with this configuration. The text names a setting or a secret and never
    repeats a value."""


class RefusingIdentityVerifier:
    """The verifier of a process with no Entra adapter: every sign-in is refused, for both doors, so
    no one signs in rather than anyone being let in (fail closed; the real verifier is B8)."""

    async def verify(self, credential: str, audience: Audience) -> VerifiedIdentity:
        raise IdentityRejected


@dataclass(frozen=True)
class ApiParts:
    """What the process supplies that the settings cannot: the external adapters. `closers` are run
    in reverse order when the process stops."""

    secrets: SecretStore
    verifier: IdentityVerifier
    event_bus: EventBus
    closers: tuple[Callable[[], Awaitable[None]], ...] = field(default=())


def _short(store: SecretStore, name: str) -> bool:
    return len(store.get(name)) < MIN_SECRET_BYTES


def check_secrets(store: SecretStore) -> None:
    """Refuse to start when a secret the API reads is missing or weak. Names only in the message."""
    missing: list[str] = []
    weak: list[str] = []
    for name in REQUIRED_SECRETS:
        try:
            if _short(store, name):
                weak.append(name)
        except NotFound:
            missing.append(name)
    if missing or weak:
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if weak:
            parts.append(f"shorter than {MIN_SECRET_BYTES} bytes: " + ", ".join(weak))
        raise ApiConfigError(
            "the secret store does not hold what the API reads (" + "; ".join(parts) + ")"
        )


def check_settings(settings: Settings) -> None:
    """The settings that would make a running process wrong without it knowing."""
    if settings.profile == "production":
        url = settings.base_url
        placeholder = "diucs.example" in url
        if not url.startswith("https://") or placeholder:
            raise ApiConfigError(
                "DIUCS_BASE_URL must be the public https URL of the API: Twilio's signature of "
                "an inbound text is checked against it"
            )
    if settings.synthetic_enabled:
        raise ApiConfigError(
            "DIUCS_SYNTHETIC_ENABLED is set but no synthetic link issuer is built: the hook "
            "would answer 404 to every check"
        )
    if settings.operator_directory_id is not None and (
        normalise_directory_id(settings.operator_directory_id) is None
    ):
        raise ApiConfigError("DIUCS_OPERATOR_DIRECTORY_ID must be a directory id (a GUID)")


def _ranges_from_file(path: Path) -> tuple[IPNetwork, ...]:
    try:
        lines = [
            line
            for line in path.read_text(encoding="ascii").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        return parse_ranges(lines)
    except OSError, UnicodeDecodeError, ValueError:
        raise ApiConfigError(
            "DIUCS_EDGE_CLOUDFLARE_RANGES_FILE cannot be read as one network range for each line"
        ) from None


def edge_for(settings: Settings, secrets: SecretStore) -> CloudflareEdge:
    """Who counts as the edge, from the settings and the optional origin secret."""
    ranges = (
        CLOUDFLARE_RANGES
        if settings.edge_cloudflare_ranges_file is None
        else _ranges_from_file(settings.edge_cloudflare_ranges_file)
    )
    try:
        extra = parse_ranges(settings.edge_trusted_peers)
    except ValueError:
        raise ApiConfigError(
            "DIUCS_EDGE_TRUSTED_PEERS holds a value that is not a network"
        ) from None
    origin: bytes | None
    try:
        origin = secrets.get(EDGE_ORIGIN_SECRET)
    except NotFound:
        origin = None
    if origin is not None and len(origin) < MIN_SECRET_BYTES:
        raise ApiConfigError(
            f"the secret {EDGE_ORIGIN_SECRET} is shorter than {MIN_SECRET_BYTES} bytes"
        )
    return CloudflareEdge(
        ranges=ranges,
        extra_peers=extra,
        origin_secret=origin,
        trust_cloudflare=settings.edge == "cloudflare",
    )


def startup_warnings(settings: Settings, container: Container, parts: ApiParts) -> list[str]:
    """What the process starts without. Each one fails closed in use, so none stops the process."""
    found: list[str] = []
    if isinstance(container.postcodes, NoPostcodes):
        found.append(
            "no postcode centroid file (DIUCS_POSTCODE_CENTROIDS_PATH): no position is located"
        )
    if isinstance(container.geocoder, NoGeocoder):
        found.append(
            "no address lookup key (DIUCS_OS_PLACES_API_KEY): registration offers no address"
        )
    if isinstance(container.telemetry, NoTelemetry):
        found.append("no telemetry workspace or client: the support console shows no telemetry")
    if settings.operator_directory_id is None:
        found.append("no operator directory (DIUCS_OPERATOR_DIRECTORY_ID): no operator signs in")
    if isinstance(parts.verifier, RefusingIdentityVerifier):
        found.append("no identity verifier is built: every staff and operator sign-in is refused")
    if settings.edge == "none":
        found.append("DIUCS_EDGE is none: forwarded client addresses and hosts are ignored")
    return found


class Lifecycle(Protocol):
    async def startup(self) -> None: ...

    async def shutdown(self) -> None: ...


def serving_lifespan(
    container: Lifecycle,
    closers: Sequence[Callable[[], Awaitable[None]]],
    warnings: Callable[[], list[str]],
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """The app's lifespan: open the container (it refuses to start when Neo4j cannot be reached or
    a node has no tenant, DEC-012, TEN-031), log what the process starts without, and on the way
    out close the parts in reverse order and then the container, whatever happened."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await container.startup()
            for warning in warnings():
                log.warning("start-up: %s", warning)
            yield
        finally:
            for close in reversed(closers):
                try:
                    await close()
                except Exception as error:
                    log.error("a part did not close: %s", type(error).__name__)
            await container.shutdown()

    return lifespan


def build_api(
    settings: Settings,
    container: Container,
    parts: ApiParts,
    *,
    provider: TracerProvider | None = None,
) -> FastAPI:
    """The app, with every collaborator its routes read, behind the trusted edge."""
    edge = edge_for(settings, parts.secrets)
    install_log_redaction()
    app = create_app(container, instrument=api_instrumentation(settings, provider))
    app.state.secrets = parts.secrets
    app.state.cache = container.cache
    app.state.token_exchange = ExchangeDeps(
        verifier=parts.verifier,
        operator_directory_id=settings.operator_directory_id,
        platform_audit=container.platform_audit,
    )
    app.state.link_pages = LinkPagesDeps(cache=container.cache, sealer=container.sealer)
    app.state.sms_webhook = SmsWebhookDeps(
        cache=container.cache,
        event_bus=parts.event_bus,
        hasher=HmacPhoneHasher(container.secrets),
        secrets=container.secrets,
        lines=DirectoryInboundLines(container.tenants),
        public_base_url=settings.base_url,
    )
    app.state.network_services = build_network_services(container)
    app.state.network_admin = build_network_admin_services(container)
    install_platform_routes(app, container)
    app.router.lifespan_context = serving_lifespan(
        container, parts.closers, lambda: startup_warnings(settings, container, parts)
    )
    # Added last, so it is the outermost layer: nothing sees a request before the edge has decided
    # who its client is.
    app.add_middleware(CloudflareEdgeMiddleware, edge=edge)
    return app


def create_serving_app(
    settings: Settings,
    parts: ApiParts,
    *,
    telemetry_client: LogsQueryClient | None = None,
    provider: TracerProvider | None = None,
) -> FastAPI:
    """Check the configuration, build the container and the app. Nothing connects until the app
    starts (the lifespan opens the container)."""
    check_settings(settings)
    check_secrets(parts.secrets)
    container = build(settings, secrets=parts.secrets, telemetry_client=telemetry_client)
    return build_api(settings, container, parts, provider=provider)


def load_secret_store(settings: Settings) -> SecretStore | None:
    """The process's secret store, or None when none is built. The production store is Azure Key
    Vault behind a managed identity (deployment-plan item 3, B8); it needs a vault, so none is
    built here, and the process stops at start-up rather than serving with every secret missing."""
    return None


def _service_bus_connection(settings: Settings) -> str:
    secret = settings.servicebus_connection
    if secret is None:
        raise ApiConfigError(SERVICE_BUS_MISSING)
    return secret.get_secret_value()


def _production_parts(settings: Settings) -> ApiParts:
    connection = _service_bus_connection(settings)
    store = load_secret_store(settings)
    if store is None:
        raise ApiConfigError(SECRET_STORE_MISSING)
    client = ServiceBusClient.from_connection_string(connection)
    bus = ServiceBusEventBus(client)
    return ApiParts(
        secrets=store,
        verifier=RefusingIdentityVerifier(),
        event_bus=bus,
        closers=(client.close, bus.close),
    )


def app_factory() -> FastAPI:
    """The app of this process, for `uvicorn --factory`. Raises ApiConfigError when the
    configuration is wrong, which stops uvicorn before it listens."""
    settings = Settings()
    provider = configure_telemetry(settings)
    return create_serving_app(settings, _production_parts(settings), provider=provider)


def main() -> None:
    try:
        settings = Settings()
        app = create_serving_app(
            settings, _production_parts(settings), provider=configure_telemetry(settings)
        )
    except ApiConfigError as error:
        raise SystemExit(str(error)) from None
    # Forwarded headers are Cloudflare's to give and the edge's to check: uvicorn trusts none.
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        proxy_headers=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
