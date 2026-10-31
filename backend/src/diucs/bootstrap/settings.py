"""Settings read from environment variables prefixed DIUCS_.

A settings value swaps an adapter without a code change. Secrets are SecretStr and
never appear in repr. Profiles differ only in external providers; both use Neo4j for
everything Neo4j stores.
"""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DIUCS_")

    profile: Literal["test", "production"] = "test"
    minutes_per_avoided_call: int | None = None
    """Minutes one phone call takes, for the week summary's time-back estimate (U35). Unset is not
    guessed: the summary shows [x] until the owner sets it (DEC-245)."""
    base_url: str = "https://diucs.example/"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("diucs-test-password")
    # DEC-012 pool bounds. Values are [ASSUMED] until measured.
    neo4j_max_connection_lifetime_s: float = 1800.0
    neo4j_liveness_check_timeout_s: float = 30.0
    neo4j_connection_acquisition_timeout_s: float = 30.0
    neo4j_max_connection_pool_size: int = 50
    redis_url: str = "redis://localhost:6379/0"
    # O01: the build id put on every span and event (`release`). The OTLP endpoint is the
    # collector (O04). Empty means no exporter: telemetry is off and nothing fails.
    release: str = "dev"
    otlp_endpoint: str = ""
    # O06/O01: instrument the FHIR app's requests (one server span each, under the route template).
    # Off by default: the instrumentation runs only where the owner turns it on.
    otel_instrument_http: bool = False
    # I15: the self-hosted routing engine, speaking the OSRM route API. Unset in tests. The URL is
    # a deployment setting, not a credential. The timeout is [ASSUMED] (I15 prompt said 2 s; the
    # owner set 3 s). The extract date names the map data in the travel range's source.
    routing_base_url: str | None = None
    routing_timeout_s: float = 3.0
    routing_extract_date: str | None = None
    servicebus_connection: SecretStr | None = None
    sms_provider: Literal["twilio", "govuk-notify", "none"] = "none"
    # TEN-042 (DEC-131 item 4): no Twilio credential, SMTP login or sender identity is a process
    # setting. A tenant's text number and account come from the tenant directory, its email sender
    # address from its channel record, and every credential is a network secret the secret store
    # holds under the reference of the tenant's own record (`<kind>/<tenant>/<name>`, TEN-026).
    # Only the SMTP relay's endpoint is shared by the platform (I09, DEC-110): where mail is handed
    # in. It is unset in tests, and with no host nothing is sent.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_starttls: bool = True
    # I14: the VAPID subject (a mailto: address) that push services may contact about the platform's
    # key. A placeholder here; the operations inbox is set in the environment at deploy.
    webpush_subject: str = "mailto:operations@diucs.example"
    # R16: the Pathways Dx file the score picker searches. The default is the pilot sample, whose
    # codes are not real. The licensed NHS Pathways list is a configuration change to this path.
    pathways_dx_file: Path = (
        Path(__file__).resolve().parents[3] / "data" / "pathways_dx_sample.json"
    )
    # O09 (TEN-G04): the synthetic test hook, POST /test/synthetic/prompt. Off by default. When it
    # is on, the hook answers only to the bearer hook token and only for this one tenant, which the
    # edge binds (a request never names a tenant). Real values come from the environment.
    synthetic_enabled: bool = False
    synthetic_hook_token: SecretStr | None = None
    synthetic_tenant_id: str | None = None
    # I11 (DEC-047): the local postcode-centroid CSV (postcode,latitude,longitude, WGS84). Patient
    # postcodes are looked up in this file and never leave the Trust. Unset: nothing is located.
    postcode_centroids_path: Path | None = None
    # I12 (DEC-047): the OS Places key, read by the geocoder for a service's site postcode only.
    # Unset: no address is found (fail closed). Real values come from the environment.
    os_places_api_key: SecretStr | None = None
    # I12: the pilot ODS sample and the local CodeSystem files. The default is the repo's folder.
    terminology_dir: Path = Path(__file__).resolve().parents[3] / "terminology"
    # U28 (DEC-317): the area of each tenant, for the registration review's address check, as the
    # tenant id and its districts and runs: {"example-icb": "DT1-DT11,BH1-BH31"}. No default: a
    # tenant with no entry has an empty area, which fails every address check.
    tenant_areas: dict[str, str] = {}
    # O07: the Log Analytics workspace the support console reads raw telemetry from. Unset: the
    # telemetry query refuses every read (fail closed). The workspace id is not a secret.
    telemetry_workspace_id: str | None = None
    # B1 (the serving process): where the API binds, and what it trusts about the proxy in front of
    # it. Behind Cloudflare (deployment-plan item 5) the client address and the original host come
    # from the edge's headers only when the request comes from Cloudflare: its published ranges
    # (built in; `edge_cloudflare_ranges_file` replaces them, one range for each line), an extra
    # trusted peer range (`edge_trusted_peers`, for the ingress that accepts only Cloudflare) or the
    # origin secret `edge-origin` in the secret store. `none` trusts no published range, and every
    # forwarded header is then ignored.
    api_host: str = "0.0.0.0"  # noqa: S104 (a container binds all its interfaces; the ingress is the door)
    api_port: int = 8000
    edge: Literal["cloudflare", "none"] = "cloudflare"
    edge_cloudflare_ranges_file: Path | None = None
    edge_trusted_peers: list[str] = []
    # TEN-043: the Entra directory of the platform operator's own staff (a GUID). Unset leaves the
    # operator sign-in unconfigured (it answers as a server with no exchange configuration).
    operator_directory_id: str | None = None
