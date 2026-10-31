"""Per-tenant keys for hashes and tokens (TEN-023, DEC-350).

A phone hash, a link-token hash, a CSRF token, a text-code hash, a PIN hash, a device-token hash and
a support-code hash are keyed with a secret. One secret for the whole platform would give one
person one hash in every tenant, which links two tenants' records in any database dump, and a key
that opened one tenant's hashes would open all of them. So each tenant has its own key for each
purpose, derived from the platform secret with HKDF (RFC 5869, HMAC-SHA256), the tenant and the
purpose being the context:

    key = HKDF(ikm = platform secret, salt = "diucs/tenant-key/v1", info = purpose NUL tenant id)

The same number therefore hashes differently in each tenant, a key for one tenant never produces
(or verifies) another tenant's hash, and the key of one purpose is not the key of another. The
platform secret stays the only secret in the store: nothing derived is stored, and no derived key
is ever logged or put in an error.

The one exception is the tenant `default` (the development data that TEN-005 stamped): it keeps
the platform secret itself as its key, so every hash already stored stays valid (hash key version
0). Every other tenant is on derived keys (version 1). A tenant record whose version disagrees
with its id is refused when the process starts (`check_key_version`).

Pure: standard library only, no I/O.
"""

import hashlib
import hmac
from typing import Final

from diucs.domain.errors import DomainError, ValidationFailed
from diucs.domain.model.tenant import check_tenant_id

HASH_KEY_VERSION_LEGACY: Final = 0
HASH_KEY_VERSION_DERIVED: Final = 1
KEY_BYTES: Final = 32
# The tenant that keeps the platform secret as its key. A copy of the kernel's DEFAULT_TENANT_ID
# (the domain cannot import the application), pinned equal by a test.
LEGACY_KEY_TENANT: Final = "default"
# The secrets that are keys of hashes and tokens: the only names that are derived per tenant.
# Anything else in the secret store (a Twilio token, the BFF secret, a push key) is read as it is.
PER_TENANT_KEY_NAMES: Final[frozenset[str]] = frozenset(
    {
        "phone-hash",
        "link-token",
        "link-csrf",
        "code-hmac",
        "pin-hmac",
        "device-token",
        "support-code",
    }
)

_SALT: Final = b"diucs/tenant-key/v1"
_HASH_BYTES: Final = hashlib.sha256().digest_size
_MAX_LENGTH: Final = 255 * _HASH_BYTES
KEY_VERSION_MESSAGE: Final = "a tenant record's hash key version does not match its key rule"


class KeyVersionMismatch(DomainError):
    """A tenant record's hash key version is not the one its id allows. The text is fixed and
    holds no value."""


def hkdf_sha256(key_material: bytes, *, salt: bytes, info: bytes, length: int) -> bytes:
    """HKDF with HMAC-SHA256 (RFC 5869): extract with the salt, then expand with the info. An empty
    salt is a salt of 32 zero bytes, as the RFC says. `length` is 1 to 255 * 32 bytes."""
    if not 1 <= length <= _MAX_LENGTH:
        raise ValueError("the length is out of range")
    pseudo_random_key = hmac.new(salt or bytes(_HASH_BYTES), key_material, hashlib.sha256).digest()
    okm = b""
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(
            pseudo_random_key, block + info + bytes([counter]), hashlib.sha256
        ).digest()
        okm += block
        counter += 1
    return okm[:length]


def derive_tenant_key(platform_key: bytes, tenant_id: str, purpose: str) -> bytes:
    """The key of one tenant for one purpose: 32 bytes. A tenant that is not a plain tenant id (a
    network id, the reserved platform id, anything else) and a purpose that is not one of
    `PER_TENANT_KEY_NAMES` are refused, and a platform key that is empty or not bytes is refused;
    no refusal holds a value."""
    check_tenant_id(tenant_id)
    if type(purpose) is not str or purpose not in PER_TENANT_KEY_NAMES:
        raise ValidationFailed("purpose", "is not a keyed purpose")
    if type(platform_key) is not bytes or not platform_key:
        raise ValidationFailed("secret", "must be non-empty bytes")
    info = purpose.encode("ascii") + b"\x00" + tenant_id.encode("ascii")
    return hkdf_sha256(platform_key, salt=_SALT, info=info, length=KEY_BYTES)


def uses_legacy_key(tenant_id: str) -> bool:
    """True for the default tenant only: its hashes were made with the platform secret itself."""
    return tenant_id == LEGACY_KEY_TENANT


def key_version_for(tenant_id: str) -> int:
    return HASH_KEY_VERSION_LEGACY if uses_legacy_key(tenant_id) else HASH_KEY_VERSION_DERIVED


def check_key_version(tenant_id: str, version: int) -> None:
    """Refuse a tenant record whose `hashKeyVersion` is not the one its id takes: version 0 only for
    the default tenant, version 1 for every other. A record that disagrees would hash with a key
    other than the one its stored hashes were made with."""
    if type(version) is not int or version != key_version_for(tenant_id):
        raise KeyVersionMismatch(KEY_VERSION_MESSAGE)
