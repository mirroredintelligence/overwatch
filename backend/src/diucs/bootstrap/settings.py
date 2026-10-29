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
    # I09 (DEC-110): SMTP relay for role-inbox email. Unset in tests; real values come from the
    # environment or a secret manager and are never committed.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    email_from: str = "DIUCS Capacity <capacity@diucs.example>"
    # R16: the Pathways Dx file the score picker searches. The default is the pilot sample, whose
    # codes are not real. The licensed NHS Pathways list is a configuration change to this path.
    pathways_dx_file: Path = (
        Path(__file__).resolve().parents[3] / "data" / "pathways_dx_sample.json"
    )
