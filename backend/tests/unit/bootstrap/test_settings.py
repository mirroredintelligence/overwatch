import os

import pytest
from pydantic import SecretStr, ValidationError

from diucs.bootstrap.settings import Settings

SECRET = "diucs-test-password"


@pytest.fixture(autouse=True)
def _no_diucs_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from an environment with no DIUCS_ settings set."""
    for name in list(os.environ):
        if name.startswith("DIUCS_"):
            monkeypatch.delenv(name, raising=False)


def test_defaults_with_no_environment() -> None:
    settings = Settings()
    assert settings.profile == "test"
    assert settings.sms_provider == "none"
    assert settings.neo4j_uri == "bolt://localhost:7687"


def test_values_are_read_from_diucs_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIUCS_PROFILE", "production")
    monkeypatch.setenv("DIUCS_NEO4J_URI", "bolt://graph:7687")
    settings = Settings()
    assert settings.profile == "production"
    assert settings.neo4j_uri == "bolt://graph:7687"


def test_unknown_profile_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIUCS_PROFILE", "memory")
    with pytest.raises(ValidationError):
        Settings()


def test_repr_does_not_reveal_the_neo4j_password() -> None:
    assert SECRET not in repr(Settings())


def test_secret_value_is_available_only_through_get_secret_value() -> None:
    settings = Settings()
    assert settings.neo4j_password.get_secret_value() == SECRET


SERVICEBUS_CANARY = "Endpoint=sb://canary.invalid/;SharedAccessKey=canary-sb-7f3a9c"
NEO4J_CANARY = "canary-neo4j-4d8e1b"


def test_servicebus_connection_is_a_secret_and_hidden_from_repr_and_str(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_SERVICEBUS_CONNECTION", SERVICEBUS_CANARY)
    settings = Settings()
    assert isinstance(settings.servicebus_connection, SecretStr)
    assert settings.servicebus_connection.get_secret_value() == SERVICEBUS_CANARY
    assert SERVICEBUS_CANARY not in repr(settings)
    assert SERVICEBUS_CANARY not in str(settings)


def test_neo4j_password_from_environment_is_hidden_from_repr_and_str(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_PASSWORD", NEO4J_CANARY)
    settings = Settings()
    assert isinstance(settings.neo4j_password, SecretStr)
    assert settings.neo4j_password.get_secret_value() == NEO4J_CANARY
    assert NEO4J_CANARY not in repr(settings)
    assert NEO4J_CANARY not in str(settings)


TWILIO_CANARY = "canary-twilio-token-5b2c"
SMTP_CANARY = "canary-smtp-password-7d1e"

# TEN-042 (DEC-131 item 4): a tenant's Twilio and email credentials are network secrets read from
# the secret store by the reference its own channel record holds. No process-wide setting holds one.
GONE = (
    "twilio_account_sid",
    "twilio_auth_token",
    "twilio_from",
    "smtp_user",
    "smtp_password",
    "email_from",
)


@pytest.mark.parametrize("name", GONE)
def test_no_global_twilio_or_email_credential_or_identity_is_a_setting(name: str) -> None:
    assert name not in Settings.model_fields
    assert not hasattr(Settings(), name)


def test_an_environment_variable_that_once_set_a_global_credential_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_TWILIO_AUTH_TOKEN", TWILIO_CANARY)
    monkeypatch.setenv("DIUCS_SMTP_PASSWORD", SMTP_CANARY)
    monkeypatch.setenv("DIUCS_EMAIL_FROM", "someone@example.test")

    settings = Settings()

    assert TWILIO_CANARY not in repr(settings) + str(settings.model_dump())
    assert SMTP_CANARY not in repr(settings) + str(settings.model_dump())
    assert "someone@example.test" not in str(settings.model_dump())


def test_the_email_relay_endpoint_is_still_a_platform_setting() -> None:
    settings = Settings()

    assert settings.smtp_host is None
    assert settings.smtp_port == 587
    assert settings.smtp_starttls is True


def test_the_pathways_dx_file_defaults_to_the_repo_sample() -> None:
    settings = Settings()
    assert settings.pathways_dx_file.name == "pathways_dx_sample.json"
    assert settings.pathways_dx_file.is_file()


def test_the_synthetic_hook_is_off_by_default_and_its_token_is_hidden() -> None:
    settings = Settings()
    assert settings.synthetic_enabled is False
    assert settings.synthetic_hook_token is None
    assert settings.synthetic_tenant_id is None


def test_the_synthetic_hook_token_is_read_from_the_environment_and_never_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_SYNTHETIC_ENABLED", "true")
    monkeypatch.setenv("DIUCS_SYNTHETIC_HOOK_TOKEN", "test-only-hook-token")
    monkeypatch.setenv("DIUCS_SYNTHETIC_TENANT_ID", "synthetic")
    settings = Settings()
    assert settings.synthetic_enabled is True
    assert settings.synthetic_tenant_id == "synthetic"
    assert settings.synthetic_hook_token is not None
    assert settings.synthetic_hook_token.get_secret_value() == "test-only-hook-token"
    assert "test-only-hook-token" not in repr(settings)


def test_the_telemetry_workspace_is_unset_by_default_and_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().telemetry_workspace_id is None
    monkeypatch.setenv("DIUCS_TELEMETRY_WORKSPACE_ID", "00000000-0000-0000-0000-000000000000")
    assert Settings().telemetry_workspace_id == "00000000-0000-0000-0000-000000000000"
