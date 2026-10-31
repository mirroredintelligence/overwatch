"""The secret store of a process, and the settings that come from it (B8, DEC-1304).

`load_secret_store(settings)` is the one place a process learns where its secrets live:

- `DIUCS_KEY_VAULT_URL` set: Azure Key Vault, read through the app's managed identity
  (`KeyVaultSecretStore`). The only environment values are the vault URL and `AZURE_CLIENT_ID`; a
  secret that is also in the plain environment stops the process (item 8: a secret in plain
  configuration is an error, not a fallback).
- `DIUCS_SECRETS_DIR` set, no vault: the development file store (`FileSecretStore`), refused in the
  production profile, beside a vault URL and when the directory is open to group or others.
- neither: None, as before (tests, and a process that then stops or runs without secrets).

`settings_from_vault` fills the three settings that are secrets (`neo4j_password`, `redis_url`,
`servicebus_connection`, and the optional `os_places_api_key`) from the vault names
`neo4j-password`, `redis-url`, `servicebus-connection` and `os-places-api-key`. Messages name a
setting or a secret and never a value.
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

from pydantic import SecretStr

from diucs.adapters.outbound.file_secrets import FileSecretStore, SecretsDirectoryError
from diucs.adapters.outbound.keyvault_secrets import KeyVaultSecretStore
from diucs.adapters.outbound.keyvault_secrets.key_vault_store import SecretClientLike
from diucs.application.ports.outbound.tokens import SecretStore, SecretStoreUnavailable
from diucs.bootstrap.settings import Settings
from diucs.domain.errors import NotFound

log = logging.getLogger(__name__)

NEO4J_PASSWORD_SECRET: Final = "neo4j-password"
REDIS_URL_SECRET: Final = "redis-url"
SERVICEBUS_CONNECTION_SECRET: Final = "servicebus-connection"
OS_PLACES_API_KEY_SECRET: Final = "os-places-api-key"

SETTING_SECRET_NAMES: Final[tuple[str, ...]] = (
    NEO4J_PASSWORD_SECRET,
    REDIS_URL_SECRET,
    SERVICEBUS_CONNECTION_SECRET,
)
"""The vault names of the settings that must come from the vault when one is configured."""

# The settings that are secrets: the setting, the vault name it is read from, and the plain
# environment variable that must not also be set when a vault is configured.
_SETTING_FIELDS: Final = (
    ("neo4j_password", NEO4J_PASSWORD_SECRET),
    ("redis_url", REDIS_URL_SECRET),
    ("servicebus_connection", SERVICEBUS_CONNECTION_SECRET),
    ("os_places_api_key", OS_PLACES_API_KEY_SECRET),
)
_ENV_PREFIX: Final = "DIUCS_"


class SecretConfigError(Exception):
    """The process cannot get its secrets with this configuration. The text names a setting or a
    secret and never a value."""


def _variable(field: str) -> str:
    return _ENV_PREFIX + field.upper()


def plain_secret_variables(settings: Settings) -> list[tuple[str, str]]:
    """The secret settings that are also given in plain configuration, as (variable, vault name),
    whether through the environment (any letter case, as the settings read it) or directly to the
    settings object. Reads no value."""
    present = {key.upper() for key in os.environ}
    return [
        (_variable(field), name)
        for field, name in _SETTING_FIELDS
        if field in settings.model_fields_set or _variable(field) in present
    ]


def _refuse_plain_secrets(settings: Settings) -> None:
    found = plain_secret_variables(settings)
    if found:
        listed = ", ".join(f"{variable} (the vault holds {name})" for variable, name in found)
        raise SecretConfigError(
            "a secret is set in the plain environment while DIUCS_KEY_VAULT_URL is set, and the "
            f"vault is the only source: remove {listed}"
        )


def _valid_vault_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname)


def _file_store(settings: Settings, directory: Path) -> FileSecretStore:
    if settings.profile == "production":
        raise SecretConfigError(
            "DIUCS_SECRETS_DIR is for development only and is refused when DIUCS_PROFILE is "
            "production: set DIUCS_KEY_VAULT_URL"
        )
    try:
        store = FileSecretStore(directory)
    except SecretsDirectoryError as error:
        raise SecretConfigError(f"DIUCS_SECRETS_DIR: {error}") from None
    log.warning(
        "the secret store is the development file store (DIUCS_SECRETS_DIR): not for production"
    )
    return store


def load_secret_store(
    settings: Settings,
    *,
    client: SecretClientLike | None = None,
    clock: Callable[[], float] | None = None,
) -> SecretStore | None:
    """The process's secret store, or None when none is configured. `client` and `clock` are for
    tests: with no client the Key Vault client is built over `DefaultAzureCredential`, which uses
    the identity named by `AZURE_CLIENT_ID` in Azure and the developer's login elsewhere. Nothing
    connects until the first read."""
    url = settings.key_vault_url
    directory = settings.secrets_dir
    if url is not None and directory is not None:
        raise SecretConfigError(
            "DIUCS_KEY_VAULT_URL and DIUCS_SECRETS_DIR are both set: use the vault, or the "
            "development directory, not both"
        )
    if directory is not None:
        return _file_store(settings, directory)
    if url is None:
        return None
    if not _valid_vault_url(url):
        raise SecretConfigError("DIUCS_KEY_VAULT_URL must be the https URL of a Key Vault")
    _refuse_plain_secrets(settings)
    on_close: Callable[[], None] | None = None
    if client is None:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=url, credential=credential)
        on_close = credential.close
    options: dict[str, object] = {} if clock is None else {"clock": clock}
    return KeyVaultSecretStore(
        client,
        cache_seconds=settings.secret_cache_seconds,
        stale_seconds=settings.secret_stale_seconds,
        on_close=on_close,
        **options,  # type: ignore[arg-type]
    )


def close_store(store: object) -> None:
    """Close a store that holds a client (the vault's); the file store and a fake hold none."""
    close = getattr(store, "close", None)
    if callable(close):
        close()


def _text(
    store: SecretStore, name: str, problems: list[str], *, optional: bool = False
) -> str | None:
    try:
        raw = store.get(name)
    except NotFound:
        if not optional:
            problems.append(f"{name} is not in the vault")
        return None
    except SecretStoreUnavailable:
        problems.append(f"{name} could not be read from the vault")
        return None
    try:
        value = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        value = ""
    if not value:
        problems.append(f"{name} is empty or is not text")
        return None
    return value


def settings_from_vault(
    settings: Settings, store: SecretStore, *, address_key: bool = True
) -> Settings:
    """The settings with the Neo4j password, the Redis URL and the Service Bus connection read from
    the vault (and the address lookup key when `address_key` and the vault holds it). Stops, naming
    each secret and no value, when a plain one is also set, or one is missing, empty or
    unreadable."""
    _refuse_plain_secrets(settings)
    problems: list[str] = []
    values: dict[str, object] = {}
    for field, name in _SETTING_FIELDS[:3]:
        text = _text(store, name, problems)
        if text is not None:
            values[field] = text if field == "redis_url" else SecretStr(text)
    if address_key:
        # Optional: with no key there is no address lookup, which the process says at start-up.
        text = _text(store, OS_PLACES_API_KEY_SECRET, problems, optional=True)
        if text is not None:
            values["os_places_api_key"] = SecretStr(text)
    if problems:
        raise SecretConfigError(
            "the settings cannot be read from the vault: " + "; ".join(problems)
        )
    return settings.model_copy(update=values)


def address_key_from_store(settings: Settings, store: SecretStore) -> Settings:
    """The settings with the address lookup key read from a store that is not the vault (the
    development file store): the file `os-places-api-key` when there is one and the key is not given
    in the environment, which works locally because no vault is configured. No file: unchanged, and
    the process says at start-up that there is no address lookup."""
    if settings.os_places_api_key is not None:
        return settings
    problems: list[str] = []
    text = _text(store, OS_PLACES_API_KEY_SECRET, problems, optional=True)
    if problems:
        raise SecretConfigError("the address key cannot be read: " + "; ".join(problems))
    if text is None:
        return settings
    return settings.model_copy(update={"os_places_api_key": SecretStr(text)})
