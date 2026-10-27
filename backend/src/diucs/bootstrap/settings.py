"""Settings read from environment variables prefixed DIUCS_.

A settings value swaps an adapter without a code change. Secrets are SecretStr and
never appear in repr. Profiles differ only in external providers; both use Neo4j for
everything Neo4j stores.
"""

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DIUCS_")

    profile: Literal["test", "production"] = "test"
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
    servicebus_connection: SecretStr | None = None
    sms_provider: Literal["twilio", "govuk-notify", "none"] = "none"
    # DEC-002, I06: Twilio credentials and sender. Unset in tests; real values come from the
    # environment or a secret manager and are never committed.
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from: str | None = None
