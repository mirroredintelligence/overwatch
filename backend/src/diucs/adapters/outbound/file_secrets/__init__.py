"""Development-only secret store: a file per secret (B8, DEC-1304 addendum)."""

from diucs.adapters.outbound.file_secrets.file_secret_store import (
    FileSecretStore,
    SecretsDirectoryError,
)

__all__ = ["FileSecretStore", "SecretsDirectoryError"]
