"""Unit tests for phone hashing (P10, H-09). A phone number is stored only as an HMAC of its
normalised UK mobile form, so "+44 7700 900123" and "07700 900123" are the same subscriber."""

import re

import pytest

from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.identity import HmacPhoneHasher, normalise_uk_mobile
from diucs.domain.errors import ValidationFailed

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
