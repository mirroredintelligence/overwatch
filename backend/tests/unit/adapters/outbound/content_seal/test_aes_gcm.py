"""Unit tests for the AES-256-GCM content seal (U03, DEC-116): the associated data (the outbox
message id, the tenant id and the recipient role id), the nonce, the key, and strict decoding.
Pure: no Neo4j, no clock. Synthetic values only."""

import base64

import pytest

from diucs.adapters.outbound.content_seal.aes_gcm import derive_key, seal_content, unseal_content
from diucs.domain.errors import ValidationFailed

SECRET = b"s" * 40
OTHER_SECRET = b"t" * 40
AAD = {"message_id": "msg-1", "tenant_id": "tenant-a", "recipient_role_id": "role-1"}
TEXT = (
    "DIUCS: UCR West. We have 3 referrals in the next 2 hrs (as of 23 Oct 08:15). "
    "Confirm or update: diucs.example/k3F9a Or reply Y, or a new number. By 10:30."
)
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


@pytest.fixture
def key() -> bytes:
    return derive_key(SECRET)


def _raw(sealed: str) -> bytes:
    body = sealed.removeprefix("v2.")
    return base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))


def _sealed(raw: bytes) -> str:
    return "v2." + base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def test_round_trip_returns_the_text(key: bytes) -> None:
    sealed = seal_content(TEXT, key, **AAD)
    assert unseal_content(sealed, key, **AAD) == TEXT


def test_the_sealed_text_does_not_show_its_plain_words(key: bytes) -> None:
    sealed = seal_content(TEXT, key, **AAD)
    assert "UCR West" not in sealed
    assert "diucs.example" not in sealed


def test_two_seals_of_one_text_differ(key: bytes) -> None:
    assert seal_content(TEXT, key, **AAD) != seal_content(TEXT, key, **AAD)


def test_each_seal_has_its_own_nonce(key: bytes) -> None:
    first = _raw(seal_content(TEXT, key, **AAD))
    second = _raw(seal_content(TEXT, key, **AAD))
    assert first[:12] != second[:12]
    assert len(first[:12]) == 12


def test_a_flipped_bit_anywhere_is_refused(key: bytes) -> None:
    raw = _raw(seal_content(TEXT, key, **AAD))
    for index in range(len(raw)):
        for bit in (0, 7):
            changed = bytearray(raw)
            changed[index] ^= 1 << bit
            with pytest.raises(ValidationFailed):
                unseal_content(_sealed(bytes(changed)), key, **AAD)


def test_a_truncated_tail_is_refused(key: bytes) -> None:
    raw = _raw(seal_content(TEXT, key, **AAD))
    for cut in (1, 16):
        with pytest.raises(ValidationFailed):
            unseal_content(_sealed(raw[:-cut]), key, **AAD)


def test_an_appended_byte_is_refused(key: bytes) -> None:
    raw = _raw(seal_content(TEXT, key, **AAD))
    with pytest.raises(ValidationFailed):
        unseal_content(_sealed(raw + b"\x00"), key, **AAD)


@pytest.mark.parametrize("suffix", ["=", "=="])
def test_padded_base64_is_refused(key: bytes, suffix: str) -> None:
    sealed = seal_content(TEXT, key, **AAD)
    with pytest.raises(ValidationFailed):
        unseal_content(sealed + suffix, key, **AAD)


def test_non_canonical_base64_is_refused(key: bytes) -> None:
    # One byte of content gives 29 bytes in all (12 nonce, 1 text, 16 tag). 29 is 2 mod 3, so the
    # last character holds two unused bits, and changing them keeps the decoded bytes the same.
    sealed = seal_content("x", key, **AAD)
    assert len(_raw(sealed)) % 3 == 2
    last = ALPHABET.index(sealed[-1])
    variant = sealed[:-1] + ALPHABET[last ^ 1]
    assert _raw(variant) == _raw(sealed)
    with pytest.raises(ValidationFailed):
        unseal_content(variant, key, **AAD)


def test_a_wrong_key_is_refused(key: bytes) -> None:
    sealed = seal_content(TEXT, key, **AAD)
    with pytest.raises(ValidationFailed):
        unseal_content(sealed, derive_key(OTHER_SECRET), **AAD)


def test_a_swapped_nonce_is_refused(key: bytes) -> None:
    first = _raw(seal_content(TEXT, key, **AAD))
    second = _raw(seal_content(TEXT, key, **AAD))
    with pytest.raises(ValidationFailed):
        unseal_content(_sealed(second[:12] + first[12:]), key, **AAD)


@pytest.mark.parametrize(
    ("field", "value"),
    [("message_id", "msg-2"), ("tenant_id", "tenant-b"), ("recipient_role_id", "role-2")],
)
def test_content_moved_to_another_message_tenant_or_recipient_is_refused(
    key: bytes, field: str, value: str
) -> None:
    sealed = seal_content(TEXT, key, **AAD)
    moved = {**AAD, field: value}
    with pytest.raises(ValidationFailed):
        unseal_content(sealed, key, **moved)


def test_a_seal_of_another_version_is_refused(key: bytes) -> None:
    body = seal_content(TEXT, key, **AAD).removeprefix("v2.")
    with pytest.raises(ValidationFailed):
        unseal_content("v1." + body, key, **AAD)


def test_a_secret_shorter_than_32_bytes_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        derive_key(b"s" * 31)


def test_a_32_byte_secret_gives_a_32_byte_key() -> None:
    assert len(derive_key(b"s" * 32)) == 32


def test_a_key_that_is_not_32_bytes_is_refused(key: bytes) -> None:
    with pytest.raises(ValidationFailed):
        seal_content(TEXT, key[:16], **AAD)
    sealed = seal_content(TEXT, key, **AAD)
    with pytest.raises(ValidationFailed):
        unseal_content(sealed, key[:16], **AAD)


def test_a_character_outside_the_base64_alphabet_is_refused(key: bytes) -> None:
    sealed = seal_content(TEXT, key, **AAD)
    with pytest.raises(ValidationFailed):
        unseal_content(sealed[:5] + "!" + sealed[6:], key, **AAD)


def test_a_non_ascii_character_is_refused(key: bytes) -> None:
    sealed = seal_content(TEXT, key, **AAD)
    with pytest.raises(ValidationFailed):
        unseal_content(sealed[:5] + "é" + sealed[6:], key, **AAD)


def test_a_body_shorter_than_nonce_and_tag_is_refused(key: bytes) -> None:
    short = _sealed(b"x" * 10)
    with pytest.raises(ValidationFailed):
        unseal_content(short, key, **AAD)
