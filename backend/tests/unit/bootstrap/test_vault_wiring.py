"""Key Vault in the three serving processes (B8, DEC-1304 items 1, 5, 6 and 8).

With `DIUCS_KEY_VAULT_URL` set the API, the workers and the outbox relay read the Neo4j password,
the Redis URL and the Service Bus connection from the vault at start-up, and refuse to start when
the same secret is also in the plain environment. The workers read the vault themselves. A fake
`SecretClient` stands in for the service: no network.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from diucs.adapters.outbound.keyvault_secrets import KeyVaultSecretStore
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.bootstrap import api_main, outbox_relay_main, workers_main
from diucs.bootstrap.api_main import (
    API_OPTIONAL_SECRETS,
    REQUIRED_SECRETS,
    ApiConfigError,
    check_secrets,
    optional_secret_warnings,
)
from diucs.bootstrap.secret_store import (
    SecretConfigError,
    load_secret_store,
    settings_from_vault,
)
from diucs.bootstrap.settings import Settings
from diucs.bootstrap.workers_main import (
    WORKER_REQUIRED_SECRETS,
    WorkersConfigError,
    check_worker_secrets,
)
from tests.support.fake_key_vault import FakeKeyVaultClient, FakeMonotonic

VAULT_URL = "https://kv-diucs-pilot-test.vault.azure.net/"
NEO4J_PASSWORD = "VAULT-neo4j-password-canary"
REDIS_URL = "rediss://:VAULT-redis-key-canary@redis.example:10000/0"
SERVICE_BUS = (
    "Endpoint=sb://sb-test.servicebus.windows.net/;SharedAccessKeyName=k;"
    "SharedAccessKey=VAULT-bus-key-canary"
)
GOOD = "synthetic-secret-for-the-vault-tests-0123456789ab"
PLAIN = "PLAIN-env-canary-value"

SETTING_SECRETS = {
    "neo4j-password": NEO4J_PASSWORD,
    "redis-url": REDIS_URL,
    "servicebus-connection": SERVICE_BUS,
}
PLAIN_VARIABLES = {
    "DIUCS_NEO4J_PASSWORD": "neo4j-password",
    "DIUCS_REDIS_URL": "redis-url",
    "DIUCS_SERVICEBUS_CONNECTION": "servicebus-connection",
    "DIUCS_OS_PLACES_API_KEY": "os-places-api-key",
}


def _vault(
    extra: dict[str, str | None] | None = None, *, platform: bool = True
) -> FakeKeyVaultClient:
    held: dict[str, str | None] = dict(SETTING_SECRETS)
    if platform:
        held.update({name: GOOD for name in REQUIRED_SECRETS})
    held.update(extra or {})
    return FakeKeyVaultClient(held)


def _settings(**values: Any) -> Settings:
    return Settings(key_vault_url=VAULT_URL, **values)


def _store(client: FakeKeyVaultClient) -> KeyVaultSecretStore:
    return KeyVaultSecretStore(client, clock=FakeMonotonic())


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        *PLAIN_VARIABLES,
        "DIUCS_KEY_VAULT_URL",
        "DIUCS_SECRET_CACHE_SECONDS",
        "DIUCS_SECRET_STALE_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


# ---- the settings


def test_the_vault_settings_default_to_no_vault_ten_minutes_and_an_hour() -> None:
    settings = Settings()

    assert settings.key_vault_url is None
    assert (settings.secret_cache_seconds, settings.secret_stale_seconds) == (600, 3600)


def test_the_vault_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIUCS_KEY_VAULT_URL", VAULT_URL)
    monkeypatch.setenv("DIUCS_SECRET_CACHE_SECONDS", "120")
    monkeypatch.setenv("DIUCS_SECRET_STALE_SECONDS", "900")

    settings = Settings()

    assert settings.key_vault_url == VAULT_URL
    assert (settings.secret_cache_seconds, settings.secret_stale_seconds) == (120, 900)


def test_the_redis_url_is_not_in_the_repr_of_the_settings() -> None:
    assert "redis" not in repr(Settings(redis_url=REDIS_URL)).lower()


# ---- the store of a process


def test_without_a_vault_url_no_store_is_built() -> None:
    assert load_secret_store(Settings()) is None


@pytest.mark.parametrize("url", ["", "kv-name", "http://kv.vault.azure.net/", "ftp://x/"])
def test_a_vault_url_that_is_not_https_stops_start_up(url: str) -> None:
    with pytest.raises(SecretConfigError, match="DIUCS_KEY_VAULT_URL"):
        load_secret_store(Settings(key_vault_url=url))


def test_with_a_vault_url_the_store_is_the_key_vault_adapter_over_the_given_client() -> None:
    client = _vault()
    clock = FakeMonotonic()

    store = load_secret_store(_settings(), client=client, clock=clock)

    assert isinstance(store, KeyVaultSecretStore)
    assert store.get("redis-url") == REDIS_URL.encode()
    assert client.calls == ["redis-url"]


def test_the_cache_windows_of_the_settings_reach_the_store() -> None:
    client = _vault()
    clock = FakeMonotonic()
    store = load_secret_store(
        _settings(secret_cache_seconds=60, secret_stale_seconds=0), client=client, clock=clock
    )
    assert store is not None
    store.get("redis-url")
    clock.advance(59)
    store.get("redis-url")
    assert client.calls == ["redis-url"]
    clock.advance(1)
    store.get("redis-url")

    assert client.calls == ["redis-url", "redis-url"]


# ---- no secret in the plain environment (DEC-1304 item 8)


@pytest.mark.parametrize("variable", sorted(PLAIN_VARIABLES))
def test_a_secret_in_the_plain_environment_stops_start_up_when_the_vault_is_set(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv("DIUCS_KEY_VAULT_URL", VAULT_URL)
    monkeypatch.setenv(variable, PLAIN)
    client = _vault()

    with pytest.raises(SecretConfigError) as refused:
        load_secret_store(Settings(), client=client)

    text = str(refused.value)
    assert variable in text and PLAIN_VARIABLES[variable] in text
    assert PLAIN not in text
    assert client.calls == [], "refused before the vault is asked for anything"


def test_a_plain_secret_in_lower_case_is_found_too(monkeypatch: pytest.MonkeyPatch) -> None:
    # pydantic-settings matches environment names without regard to case.
    monkeypatch.setenv("DIUCS_KEY_VAULT_URL", VAULT_URL)
    monkeypatch.setenv("diucs_redis_url", PLAIN)

    with pytest.raises(SecretConfigError, match="DIUCS_REDIS_URL"):
        load_secret_store(Settings(), client=_vault())


def test_a_plain_secret_given_to_the_settings_directly_is_found_too() -> None:
    with pytest.raises(SecretConfigError, match="DIUCS_NEO4J_PASSWORD"):
        settings_from_vault(_settings(neo4j_password=SecretStr(PLAIN)), _store(_vault()))


def test_every_plain_secret_is_named_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIUCS_KEY_VAULT_URL", VAULT_URL)
    monkeypatch.setenv("DIUCS_NEO4J_PASSWORD", PLAIN)
    monkeypatch.setenv("DIUCS_REDIS_URL", PLAIN)

    with pytest.raises(SecretConfigError) as refused:
        load_secret_store(Settings(), client=_vault())

    assert "DIUCS_NEO4J_PASSWORD" in str(refused.value)
    assert "DIUCS_REDIS_URL" in str(refused.value)


def test_without_a_vault_the_plain_environment_works_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_PASSWORD", PLAIN)
    monkeypatch.setenv("DIUCS_REDIS_URL", "redis://localhost:6379/1")
    monkeypatch.setenv("DIUCS_SERVICEBUS_CONNECTION", SERVICE_BUS)

    settings = Settings()

    assert load_secret_store(settings) is None
    assert settings.neo4j_password.get_secret_value() == PLAIN
    assert settings.redis_url == "redis://localhost:6379/1"


# ---- the settings read from the vault


def test_the_three_settings_come_from_the_vault_names() -> None:
    client = _vault()

    settings = settings_from_vault(_settings(), _store(client))

    assert settings.neo4j_password.get_secret_value() == NEO4J_PASSWORD
    assert settings.redis_url == REDIS_URL
    assert settings.servicebus_connection is not None
    assert settings.servicebus_connection.get_secret_value() == SERVICE_BUS
    assert set(client.calls) >= {"neo4j-password", "redis-url", "servicebus-connection"}


def test_the_other_settings_are_kept() -> None:
    settings = settings_from_vault(
        _settings(neo4j_uri="neo4j+s://example.databases.neo4j.io", api_port=9000),
        _store(_vault()),
    )

    assert settings.neo4j_uri == "neo4j+s://example.databases.neo4j.io"
    assert settings.api_port == 9000
    assert settings.key_vault_url == VAULT_URL


def test_the_resolved_settings_show_no_value() -> None:
    text = repr(settings_from_vault(_settings(), _store(_vault())))

    for canary in ("VAULT-neo4j", "VAULT-redis", "VAULT-bus"):
        assert canary not in text


@pytest.mark.parametrize("name", sorted(SETTING_SECRETS))
def test_a_missing_setting_secret_stops_start_up_naming_the_secret(name: str) -> None:
    client = _vault()
    del client.secrets[name]

    with pytest.raises(SecretConfigError) as refused:
        settings_from_vault(_settings(), _store(client))

    assert name in str(refused.value)
    for canary in ("VAULT-neo4j", "VAULT-redis", "VAULT-bus"):
        assert canary not in str(refused.value)


@pytest.mark.parametrize("name", sorted(SETTING_SECRETS))
def test_an_unreadable_setting_secret_stops_start_up_naming_the_secret(name: str) -> None:
    client = _vault()
    client.fail()

    with pytest.raises(SecretConfigError) as refused:
        settings_from_vault(_settings(), _store(client))

    assert "could not be read" in str(refused.value)
    assert any(n in str(refused.value) for n in SETTING_SECRETS)


def test_an_empty_setting_secret_is_refused() -> None:
    with pytest.raises(SecretConfigError, match="neo4j-password"):
        settings_from_vault(_settings(), _store(_vault({"neo4j-password": ""})))


def test_a_setting_secret_that_is_not_text_is_refused_without_its_bytes() -> None:
    class _Binary:
        def get(self, name: str) -> bytes:
            return b"\xff\xfe\xfd"

    with pytest.raises(SecretConfigError, match="neo4j-password") as refused:
        settings_from_vault(_settings(), _Binary())

    assert "xff" not in str(refused.value).lower()


def test_the_address_key_is_read_when_the_vault_holds_it_and_skipped_when_not() -> None:
    held = settings_from_vault(_settings(), _store(_vault({"os-places-api-key": "fake-os-key"})))
    absent = settings_from_vault(_settings(), _store(_vault()))

    assert held.os_places_api_key is not None
    assert held.os_places_api_key.get_secret_value() == "fake-os-key"
    assert absent.os_places_api_key is None


# ---- the API


def _api_start(monkeypatch: pytest.MonkeyPatch, client: FakeKeyVaultClient) -> Any:
    monkeypatch.setattr(api_main, "load_secret_store", lambda settings: _store(client))
    return api_main.prepare_process(_settings())


def test_the_api_reads_its_settings_from_the_vault_and_serves_the_vault_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _vault()

    settings, parts = _api_start(monkeypatch, client)

    assert settings.neo4j_password.get_secret_value() == NEO4J_PASSWORD
    assert settings.redis_url == REDIS_URL
    assert isinstance(parts.secrets, KeyVaultSecretStore)
    assert parts.event_bus is not None


def test_the_api_stops_when_a_plain_secret_is_set_beside_the_vault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_KEY_VAULT_URL", VAULT_URL)
    monkeypatch.setenv("DIUCS_NEO4J_PASSWORD", PLAIN)

    with pytest.raises(SystemExit) as stopped:
        api_main.main()

    assert "DIUCS_NEO4J_PASSWORD" in str(stopped.value)
    assert PLAIN not in str(stopped.value)


def test_the_api_stops_with_the_secret_name_when_the_vault_lacks_one_it_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _vault()
    del client.secrets["bff-jwt"]
    settings, parts = _api_start(monkeypatch, client)

    with pytest.raises(ApiConfigError) as stopped:
        api_main.create_serving_app(settings, parts)

    assert "bff-jwt" in str(stopped.value)
    assert GOOD not in str(stopped.value)


def test_the_api_names_a_secret_it_cannot_read_and_not_a_value() -> None:
    client = _vault()
    client.fail()

    with pytest.raises(ApiConfigError) as stopped:
        check_secrets(_store(client))

    text = str(stopped.value)
    assert "could not be read" in text
    assert "bff-jwt" in text


def test_the_api_reads_the_secrets_of_decision_1304_item_5() -> None:
    named = set(REQUIRED_SECRETS) | set(API_OPTIONAL_SECRETS)

    assert named >= {
        "bff-jwt",
        "link-token",
        "link-csrf",
        "phone-hash",
        "device-token",
        "code-hmac",
        "pin-hmac",
        "account-ref",
        "support-code",
        "telemetry-markers",
        "edge-origin",
        "webpush-vapid-private-key",
        "webpush-vapid-public-key",
        "os-places-api-key",
    }
    assert "telemetry-markers" in REQUIRED_SECRETS
    assert "edge-origin" not in REQUIRED_SECRETS  # optional today (DEC-1303 item 3 explains why)
    assert not named & {"session-secret"}  # the web tier's own


def test_an_optional_secret_the_vault_lacks_is_a_warning_naming_it_and_not_a_stop() -> None:
    client = _vault()

    warnings = optional_secret_warnings(_store(client))

    text = " ".join(warnings)
    for name in ("edge-origin", "webpush-vapid-private-key"):
        assert name in text


def test_an_optional_secret_the_vault_holds_is_not_warned_about() -> None:
    held = {name: GOOD for name in API_OPTIONAL_SECRETS if name != "os-places-api-key"}

    assert optional_secret_warnings(_store(_vault(held))) == []


def test_an_outage_while_looking_for_optional_secrets_is_a_warning_and_not_a_stop() -> None:
    client = _vault()
    client.fail()

    warnings = optional_secret_warnings(_store(client))

    assert warnings and all("could not be read" in warning for warning in warnings)


# ---- the workers


def test_the_workers_read_the_vault_themselves_and_never_call_the_api() -> None:
    source = Path(workers_main.__file__).read_text(encoding="utf-8")

    assert "api_main" not in source
    assert "load_secret_store" in source


def test_the_workers_list_holds_nothing_the_web_tier_holds() -> None:
    assert not set(WORKER_REQUIRED_SECRETS) & {"session-secret", "edge-origin"}
    assert "link-token" in WORKER_REQUIRED_SECRETS  # the key of the sealed message content


def test_the_workers_start_check_names_what_the_vault_lacks() -> None:
    client = _vault(platform=False)

    with pytest.raises(WorkersConfigError) as stopped:
        check_worker_secrets(_store(client))

    assert "link-token" in str(stopped.value)


def test_the_workers_start_check_passes_when_the_vault_holds_the_names() -> None:
    check_worker_secrets(_store(_vault()))


def test_the_workers_start_check_refuses_a_weak_secret_and_an_outage() -> None:
    with pytest.raises(WorkersConfigError, match="shorter than 32 bytes"):
        check_worker_secrets(_store(_vault({"link-token": "short"})))
    down = _vault()
    down.fail()
    with pytest.raises(WorkersConfigError, match="could not be read"):
        check_worker_secrets(_store(down))


def test_the_workers_read_their_settings_from_the_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _vault()
    monkeypatch.setattr(workers_main, "load_secret_store", lambda settings: _store(client))

    settings, store = workers_main.prepare_process(_settings())

    assert settings.neo4j_password.get_secret_value() == NEO4J_PASSWORD
    assert settings.servicebus_connection is not None
    assert settings.servicebus_connection.get_secret_value() == SERVICE_BUS
    assert isinstance(store, KeyVaultSecretStore)


def test_the_workers_stop_when_the_vault_lacks_a_secret_they_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _vault()
    del client.secrets["link-token"]
    monkeypatch.setattr(workers_main, "load_secret_store", lambda settings: _store(client))

    with pytest.raises(WorkersConfigError, match="link-token"):
        workers_main.prepare_process(_settings())


def test_the_workers_stop_when_a_plain_secret_is_set_beside_the_vault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_KEY_VAULT_URL", VAULT_URL)
    monkeypatch.setenv("DIUCS_REDIS_URL", PLAIN)

    with pytest.raises(SystemExit) as stopped:
        workers_main.main()

    assert "DIUCS_REDIS_URL" in str(stopped.value)
    assert PLAIN not in str(stopped.value)


def test_without_a_vault_the_workers_need_the_plain_connection_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(WorkersConfigError, match="DIUCS_SERVICEBUS_CONNECTION"):
        workers_main.prepare_process(Settings())


def test_the_workers_without_a_vault_have_no_store() -> None:
    settings, store = workers_main.prepare_process(Settings(servicebus_connection=SecretStr("x")))

    assert store is None
    assert settings.servicebus_connection is not None


class _Reached(Exception):
    pass


async def test_the_workers_give_the_container_the_vault_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_build(settings: Settings, **kwargs: object) -> object:
        seen.update(kwargs)
        raise _Reached

    monkeypatch.setattr(workers_main, "build", fake_build)
    store: SecretStore = _store(_vault())

    with pytest.raises(_Reached):
        await workers_main.serve(
            Settings(servicebus_connection=SecretStr(SERVICE_BUS)), asyncio.Event(), store
        )

    assert seen["secrets"] is store


async def test_the_workers_run_closes_the_store(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _vault()
    store = _store(client)

    async def fake_serve(settings: Settings, stop: Any, secrets: SecretStore | None = None) -> None:
        assert secrets is store

    monkeypatch.setattr(workers_main, "serve", fake_serve)
    monkeypatch.setattr(workers_main, "start_telemetry", lambda settings: None)
    monkeypatch.setattr(
        asyncio.get_running_loop(), "add_signal_handler", lambda name, callback: None
    )

    await workers_main._run(Settings(), store)

    assert client.closed


# ---- the outbox relay


def test_the_relay_reads_its_settings_from_the_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _vault(platform=False)
    monkeypatch.setattr(outbox_relay_main, "load_secret_store", lambda settings: _store(client))

    settings = outbox_relay_main.prepare_settings(_settings())

    assert settings.neo4j_password.get_secret_value() == NEO4J_PASSWORD
    assert settings.redis_url == REDIS_URL
    assert client.closed, "the relay reads three names and then needs the vault no more"


def test_the_relay_stops_when_a_plain_secret_is_set_beside_the_vault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_KEY_VAULT_URL", VAULT_URL)
    monkeypatch.setenv("DIUCS_SERVICEBUS_CONNECTION", SERVICE_BUS)

    with pytest.raises(SystemExit) as stopped:
        outbox_relay_main.main()

    assert "DIUCS_SERVICEBUS_CONNECTION" in str(stopped.value)
    assert SERVICE_BUS not in str(stopped.value)


# ---- the real client is built with short timeouts, over the managed identity


def test_the_real_client_is_built_with_bounded_waits_and_closes_its_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import azure.identity
    import azure.keyvault.secrets as secrets_module

    built: dict[str, Any] = {}
    closed: list[str] = []

    class _Credential:
        def close(self) -> None:
            closed.append("credential")

    class _Client(FakeKeyVaultClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__({})
            built.update(kwargs)

    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", _Credential)
    monkeypatch.setattr(secrets_module, "SecretClient", _Client)

    store = load_secret_store(_settings())
    assert store is not None
    store.close()  # type: ignore[attr-defined]

    assert built["vault_url"] == VAULT_URL
    assert 0 < built["connection_timeout"] <= 10
    assert 0 < built["read_timeout"] <= 15
    assert built["retry_total"] <= 3
    assert closed == ["credential"]
