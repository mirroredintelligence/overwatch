"""Per-tenant keys for hashes and tokens (TEN-023, domain).

The key of a tenant is derived from the platform's secret with HKDF (RFC 5869, HMAC-SHA256), with
the tenant and the purpose as the context, so a key made for one tenant never verifies what
another tenant's key made, and the key of one purpose is not the key of another.
"""

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from diucs.application.tenancy import DEFAULT_TENANT_ID
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.tenant_keys import (
    HASH_KEY_VERSION_DERIVED,
    HASH_KEY_VERSION_LEGACY,
    KEY_BYTES,
    LEGACY_KEY_TENANT,
    PER_TENANT_KEY_NAMES,
    KeyVersionMismatch,
    check_key_version,
    derive_tenant_key,
    hkdf_sha256,
    key_version_for,
    uses_legacy_key,
)

PLATFORM = b"platform-secret-0123456789abcdef0123"


def test_hkdf_matches_rfc_5869_test_case_1() -> None:
    okm = hkdf_sha256(
        bytes([0x0B] * 22),
        salt=bytes(range(13)),
        info=bytes(range(0xF0, 0xFA)),
        length=42,
    )
    assert okm.hex() == (
        "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"
    )


def test_hkdf_matches_rfc_5869_test_case_3_with_no_salt_and_no_info() -> None:
    okm = hkdf_sha256(bytes([0x0B] * 22), salt=b"", info=b"", length=42)
    assert okm.hex() == (
        "8da4e775a563c18f715f802a063c5a31b8a11f5c5ee1879ec3454e5f3c738d2d9d201395faa4b61a96c8"
    )


@pytest.mark.parametrize("length", [0, -1, 255 * 32 + 1])
def test_hkdf_refuses_a_length_it_cannot_give(length: int) -> None:
    with pytest.raises(ValueError):
        hkdf_sha256(b"k" * 32, salt=b"", info=b"", length=length)


def test_hkdf_gives_the_longest_length_the_rfc_allows() -> None:
    assert len(hkdf_sha256(b"k" * 32, salt=b"s", info=b"i", length=255 * 32)) == 255 * 32


def test_a_derived_key_is_32_bytes_and_is_never_the_platform_key() -> None:
    key = derive_tenant_key(PLATFORM, "tenant-a", "phone-hash")
    assert isinstance(key, bytes)
    assert len(key) == KEY_BYTES == 32
    assert key != PLATFORM


def test_the_same_tenant_and_purpose_always_give_the_same_key() -> None:
    assert derive_tenant_key(PLATFORM, "tenant-a", "phone-hash") == derive_tenant_key(
        PLATFORM, "tenant-a", "phone-hash"
    )


def test_two_tenants_never_share_a_key() -> None:
    assert derive_tenant_key(PLATFORM, "tenant-a", "phone-hash") != derive_tenant_key(
        PLATFORM, "tenant-b", "phone-hash"
    )


def test_two_purposes_of_one_tenant_never_share_a_key() -> None:
    keys = {derive_tenant_key(PLATFORM, "tenant-a", name) for name in PER_TENANT_KEY_NAMES}
    assert len(keys) == len(PER_TENANT_KEY_NAMES)


def test_another_platform_secret_gives_another_key() -> None:
    other = b"another-platform-secret-0123456789ab"
    assert derive_tenant_key(PLATFORM, "tenant-a", "link-token") != derive_tenant_key(
        other, "tenant-a", "link-token"
    )


def test_every_tenant_and_purpose_pair_has_its_own_key() -> None:
    tenants = ["tenant-a", "tenant-b", "tenant-a-b", "a1", "link-token"]
    keys = {
        derive_tenant_key(PLATFORM, tenant, purpose)
        for tenant in tenants
        for purpose in PER_TENANT_KEY_NAMES
    }
    assert len(keys) == len(tenants) * len(PER_TENANT_KEY_NAMES)


def test_the_key_is_the_hkdf_of_the_platform_secret_with_the_tenant_as_context() -> None:
    # An independent implementation of the same construction (the cryptography library) agrees,
    # so the derivation is the standard one and not a private variant.
    expected = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"diucs/tenant-key/v1",
        info=b"phone-hash\x00tenant-a",
    ).derive(PLATFORM)
    assert derive_tenant_key(PLATFORM, "tenant-a", "phone-hash") == expected


@pytest.mark.parametrize(
    "tenant", ["", "Tenant-A", "net-members", "platform", "a:b", "x" * 40, "tenant a"]
)
def test_a_tenant_that_is_not_a_tenant_id_is_refused_without_naming_it(tenant: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        derive_tenant_key(PLATFORM, tenant, "phone-hash")
    assert tenant not in str(refused.value) or tenant == ""


@pytest.mark.parametrize("tenant", [None, 7, b"tenant-a"])
def test_a_tenant_that_is_not_text_is_refused(tenant: object) -> None:
    with pytest.raises(ValidationFailed):
        derive_tenant_key(PLATFORM, tenant, "phone-hash")  # type: ignore[arg-type]


@pytest.mark.parametrize("purpose", ["", "phone\x00hash", "Phone-Hash", "unknown-purpose"])
def test_a_purpose_that_is_not_a_known_key_name_is_refused(purpose: str) -> None:
    with pytest.raises(ValidationFailed):
        derive_tenant_key(PLATFORM, "tenant-a", purpose)


@pytest.mark.parametrize("platform", [b"", "text", None])
def test_a_platform_key_that_is_empty_or_not_bytes_is_refused_without_showing_it(
    platform: object,
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        derive_tenant_key(platform, "tenant-a", "phone-hash")  # type: ignore[arg-type]
    assert "text" not in str(refused.value)


def test_only_the_default_tenant_keeps_the_legacy_key() -> None:
    assert uses_legacy_key(DEFAULT_TENANT_ID) is True
    assert uses_legacy_key("tenant-a") is False
    assert key_version_for(DEFAULT_TENANT_ID) == HASH_KEY_VERSION_LEGACY == 0
    assert key_version_for("tenant-a") == HASH_KEY_VERSION_DERIVED == 1


def test_the_domain_copy_of_the_default_tenant_matches_the_kernel() -> None:
    assert LEGACY_KEY_TENANT == DEFAULT_TENANT_ID


def test_the_keyed_purposes_are_the_seven_hash_and_token_secrets() -> None:
    expected = {
        "phone-hash",
        "link-token",
        "link-csrf",
        "code-hmac",
        "pin-hmac",
        "device-token",
        "support-code",
    }
    assert set(PER_TENANT_KEY_NAMES) == expected


@pytest.mark.parametrize(
    ("tenant", "version"),
    [(DEFAULT_TENANT_ID, 0), ("tenant-a", 1), ("acme-icb", 1)],
)
def test_a_record_whose_version_matches_its_key_rule_passes(tenant: str, version: int) -> None:
    check_key_version(tenant, version)


@pytest.mark.parametrize(
    ("tenant", "version"),
    [(DEFAULT_TENANT_ID, 1), ("tenant-a", 0), ("tenant-a", 2), ("tenant-a", -1)],
)
def test_a_record_whose_version_does_not_match_is_refused_with_a_fixed_message(
    tenant: str, version: int
) -> None:
    with pytest.raises(KeyVersionMismatch) as refused:
        check_key_version(tenant, version)
    assert str(refused.value) == "a tenant record's hash key version does not match its key rule"
