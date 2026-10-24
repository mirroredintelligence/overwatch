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
    redis_url: str = "redis://localhost:6379/0"
    servicebus_connection: SecretStr | None = None
    sms_provider: Literal["twilio", "govuk-notify", "none"] = "none"
