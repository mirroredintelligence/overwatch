"""Unit tests for phone hashing (P10, H-09). A phone number is stored only as an HMAC of its
normalised UK mobile form, so "+44 7700 900123" and "07700 900123" are the same subscriber."""

import re

import pytest

from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.identity import (
    DEVICE_TOKEN_SECRET,
    PHONE_HASH_SECRET,
    HmacPhoneHasher,
    TenantKeyedSecrets,
    normalise_uk_mobile,
    secret_is_configured,
)
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.tenancy import (
    DEFAULT_TENANT_ID,
    ScopeId,
    TenantNotBound,
    bind_scope,
    bind_tenant,
)
from diucs.application.use_cases.link_access import LINK_CSRF_SECRET
from diucs.application.use_cases.pin import PIN_HMAC_SECRET
from diucs.application.use_cases.text_code import CODE_HMAC_SECRET
from diucs.domain.codes import Role
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.rules.support import SUPPORT_CODE_SECRET
from diucs.domain.rules.tenant_keys import PER_TENANT_KEY_NAMES, derive_tenant_key

PHONE_SECRET = b"phone-hash-test-secret-0123456789abcdef"


def _hasher(secret: bytes = PHONE_SECRET) -> HmacPhoneHasher:
    return HmacPhoneHasher(FixedSecretStore({"phone-hash": secret}))


def test_the_international_and_national_forms_hash_the_same() -> None:
    hasher = _hasher()
    assert hasher.hash("+44 7700 900123") == hasher.hash("07700 900123")


@pytest.mark.parametrize(
    "number",
    ["+44 7700 900123", "07700 900123", "0044 7700 900123", "+44 (0)7700 900123", "07700900123"],
)
def test_every_accepted_form_normalises_to_the_national_digits(number: str) -> None:
    assert normalise_uk_mobile(number) == "07700900123"


def test_the_hash_is_a_64_character_hex_digest() -> None:
    digest = _hasher().hash("07700 900123")
    assert len(digest) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_a_different_secret_gives_a_different_hash() -> None:
    assert _hasher(b"a" * 32).hash("07700 900123") != _hasher(b"b" * 32).hash("07700 900123")


@pytest.mark.parametrize(
    "number",
    ["", "07700 90012", "07700 9001234", "+1 555 0100", "020 7946 0000", "07700 900 12a"],
)
def test_a_number_that_is_not_a_uk_mobile_is_refused_and_not_echoed(number: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        normalise_uk_mobile(number)
    assert refused.value.field == "phone"
    if number:
        assert number not in str(refused.value)


def test_a_number_that_is_not_text_is_refused() -> None:
    with pytest.raises(ValidationFailed, match="phone"):
        normalise_uk_mobile(7700900123)  # type: ignore[arg-type]


# -- per-tenant keys (TEN-023) -------------------------------------------------------------------

PLATFORM = {
    "phone-hash": b"phone-hash-platform-secret-0123456789",
    "link-token": b"link-token-platform-secret-0123456789",
    "twilio/tenant-a/auth-token": b"twilio-test-only-token",
}


def _keyed() -> tuple[TenantKeyedSecrets, FixedSecretStore]:
    platform = FixedSecretStore(PLATFORM)
    return TenantKeyedSecrets(platform), platform


def test_every_keyed_name_in_the_application_is_a_keyed_purpose() -> None:
    names = {
        PHONE_HASH_SECRET,
        LINK_TOKEN_SECRET,
        LINK_CSRF_SECRET,
        CODE_HMAC_SECRET,
        PIN_HMAC_SECRET,
        DEVICE_TOKEN_SECRET,
        SUPPORT_CODE_SECRET,
    }
    assert names == PER_TENANT_KEY_NAMES
    assert Role.REPORTER  # the module under test imports the domain codes, nothing more


def test_a_keyed_secret_is_the_tenants_derived_key_not_the_platform_secret() -> None:
    secrets, _ = _keyed()
    with bind_tenant("tenant-a"):
        key = secrets.get("phone-hash")
    assert key == derive_tenant_key(PLATFORM["phone-hash"], "tenant-a", "phone-hash")
    assert key != PLATFORM["phone-hash"]


def test_two_tenants_get_two_keys_for_one_name() -> None:
    secrets, _ = _keyed()
    with bind_tenant("tenant-a"):
        key_a = secrets.get("link-token")
    with bind_tenant("tenant-b"):
        key_b = secrets.get("link-token")
    assert key_a != key_b


def test_the_default_tenant_keeps_the_legacy_platform_key() -> None:
    secrets, _ = _keyed()
    with bind_tenant(DEFAULT_TENANT_ID):
        assert secrets.get("phone-hash") == PLATFORM["phone-hash"]
        assert secrets.get("link-token") == PLATFORM["link-token"]


def test_a_keyed_secret_with_no_tenant_bound_fails_closed() -> None:
    secrets, _ = _keyed()
    with pytest.raises(TenantNotBound):
        secrets.get("phone-hash")


def test_a_network_scope_is_not_a_tenant_for_a_key() -> None:
    secrets, _ = _keyed()
    with bind_scope(ScopeId.network("net-members")), pytest.raises(TenantNotBound):
        secrets.get("phone-hash")


def test_a_name_that_is_not_keyed_passes_through_with_or_without_a_tenant() -> None:
    secrets, platform = _keyed()
    assert secrets.get("twilio/tenant-a/auth-token") == PLATFORM["twilio/tenant-a/auth-token"]
    with bind_tenant("tenant-b"):
        assert secrets.get("twilio/tenant-a/auth-token") == PLATFORM["twilio/tenant-a/auth-token"]
    assert platform.requested == ("twilio/tenant-a/auth-token",) * 2


def test_a_keyed_name_the_platform_does_not_hold_is_not_found() -> None:
    secrets, _ = _keyed()
    with bind_tenant("tenant-a"), pytest.raises(NotFound):
        secrets.get("code-hmac")


def test_a_platform_secret_that_is_empty_is_refused_rather_than_derived_from() -> None:
    secrets = TenantKeyedSecrets(FixedSecretStore({"phone-hash": b""}))
    with bind_tenant("tenant-a"), pytest.raises(ValidationFailed):
        secrets.get("phone-hash")


def test_the_store_shows_no_key_in_its_repr_or_vars() -> None:
    secrets, _ = _keyed()
    with bind_tenant("tenant-a"):
        key = secrets.get("phone-hash")
    shown = repr(secrets) + repr(vars(secrets))
    assert key.hex() not in shown
    assert PLATFORM["phone-hash"].decode() not in shown


def test_the_same_number_hashes_differently_in_each_tenant() -> None:
    secrets, _ = _keyed()
    hasher = HmacPhoneHasher(secrets)
    with bind_tenant("tenant-a"):
        in_a = hasher.hash("07700 900123")
        again = hasher.hash("+44 7700 900123")
    with bind_tenant("tenant-b"):
        in_b = hasher.hash("07700 900123")
    assert in_a == again
    assert in_a != in_b


def test_a_hash_made_for_one_tenant_is_not_found_by_another_tenants_key() -> None:
    secrets, _ = _keyed()
    hasher = HmacPhoneHasher(secrets)
    with bind_tenant("tenant-a"):
        stored = hasher.hash("07700 900123")
    with bind_tenant("tenant-b"):
        assert hasher.hash("07700 900123") != stored


def test_the_default_tenant_hash_is_the_legacy_hash_so_stored_hashes_stay_valid() -> None:
    secrets, platform = _keyed()
    with bind_tenant(DEFAULT_TENANT_ID):
        keyed = HmacPhoneHasher(secrets).hash("07700 900123")
    assert keyed == HmacPhoneHasher(platform).hash("07700 900123")


def test_the_hasher_refuses_a_number_before_it_asks_for_a_key() -> None:
    secrets, platform = _keyed()
    with bind_tenant("tenant-a"), pytest.raises(ValidationFailed):
        HmacPhoneHasher(secrets).hash("020 7946 0000")
    assert platform.requested == ()


def test_is_configured_asks_without_a_tenant_and_reads_no_key() -> None:
    secrets, platform = _keyed()
    assert secrets.is_configured("phone-hash") is True
    assert secrets.is_configured("code-hmac") is False
    assert secrets.is_configured("twilio/tenant-a/auth-token") is True
    assert platform.requested == ("phone-hash", "code-hmac", "twilio/tenant-a/auth-token")


def test_secret_is_configured_works_on_a_plain_store_too() -> None:
    plain = FixedSecretStore({"phone-hash": b"k" * 32})
    assert secret_is_configured(plain, "phone-hash") is True
    assert secret_is_configured(plain, "link-token") is False
    secrets, _ = _keyed()
    assert secret_is_configured(secrets, "phone-hash") is True
    assert secret_is_configured(secrets, "code-hmac") is False
