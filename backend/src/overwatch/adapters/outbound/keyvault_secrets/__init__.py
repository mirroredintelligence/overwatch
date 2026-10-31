"""Azure Key Vault secret store (B8, DEC-1304): `SecretStore` over a `SecretClient`."""

from diucs.adapters.outbound.keyvault_secrets.key_vault_store import (
    DEFAULT_CACHE_SECONDS,
    DEFAULT_STALE_SECONDS,
    STALE_RETRY_SECONDS,
    KeyVaultSecretStore,
)
from diucs.domain.rules.secret_names import vault_secret_name

__all__ = [
    "DEFAULT_CACHE_SECONDS",
    "DEFAULT_STALE_SECONDS",
    "STALE_RETRY_SECONDS",
    "KeyVaultSecretStore",
    "vault_secret_name",
]
