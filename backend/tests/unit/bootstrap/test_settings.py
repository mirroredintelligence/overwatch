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
