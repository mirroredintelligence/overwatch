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
    guessed: the summary shows [x] until the owner sets it (fragments/U35.md)."""
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
    # DEC-002, I06: Twilio credentials and sender. Unset in tests; real values come from the
    # environment or a secret manager and are never committed.
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from: str | None = None
    # I09 (DEC-110): SMTP relay for role-inbox email. Unset in tests; real values come from the
    # environment or a secret manager and are never committed.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    email_from: str = "DIUCS Capacity <capacity@diucs.example>"
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
    # O07: the Log Analytics workspace the support console reads raw telemetry from. Unset: the
    # telemetry query refuses every read (fail closed). The workspace id is not a secret.
    telemetry_workspace_id: str | None = None
