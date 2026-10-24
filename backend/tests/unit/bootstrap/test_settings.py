import os

import pytest
from pydantic import ValidationError

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

