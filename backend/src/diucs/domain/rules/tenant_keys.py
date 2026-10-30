"""Per-tenant keys for hashes and tokens (TEN-023). Stub for the red commit."""

from typing import Final

from diucs.domain.errors import DomainError

HASH_KEY_VERSION_LEGACY: Final = 0
HASH_KEY_VERSION_DERIVED: Final = 1
KEY_BYTES: Final = 32
LEGACY_KEY_TENANT: Final = "default"
PER_TENANT_KEY_NAMES: Final[frozenset[str]] = frozenset()


def hkdf_sha256(key_material: bytes, *, salt: bytes, info: bytes, length: int) -> bytes:
    raise NotImplementedError


def derive_tenant_key(platform_key: bytes, tenant_id: str, purpose: str) -> bytes:
    raise NotImplementedError


def uses_legacy_key(tenant_id: str) -> bool:
    raise NotImplementedError


def key_version_for(tenant_id: str) -> int:
    raise NotImplementedError


class KeyVersionMismatch(DomainError):
    """A tenant record's hash key version is not the one its id allows. Fixed text, no value."""


def check_key_version(tenant_id: str, version: int) -> None:
    raise NotImplementedError
