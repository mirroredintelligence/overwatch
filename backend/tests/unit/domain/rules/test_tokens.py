"""Tests for diucs.domain.rules.tokens: link tokens, pairing codes and support codes (D26).

Rule: docs/spec/domain-rules.md section 7, and the D26 prompt. Pure: randomness is injected and
time is an argument, so every test is deterministic. Errors must never echo a token or a code;
the echo tests check that. The secret used here is a sample value, not a key.
"""

import hashlib
import hmac
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.tokens import (
    PAIRING_CODE_VALID_FOR,
    SUPPORT_CODE_ALPHABET,
    LinkCheck,
    LinkTokenRecord,
    check_link,
    format_pairing_code,
    hash_token,
    new_link_token,
    new_pairing_code,
    new_support_code,
    pairing_code_expired,
)

SECRET: Final = b"sample-server-secret"
NOW: Final = datetime(2026, 10, 25, 14, 0, tzinfo=UTC)
LATER: Final = NOW + timedelta(hours=2)
LINK_TOKEN: Final = re.compile(r"[A-Za-z]{23}")  # DEC-152: letters only, 23 characters
SUPPORT_CODE: Final = re.compile(
    r"[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}"
)
LONDON: Final = ZoneInfo("Europe/London")


def _record(
    expires_at: datetime = LATER,
    used_at: datetime | None = None,
) -> LinkTokenRecord:
    return LinkTokenRecord(
        token_hash="sample-hash",
        purpose="booking-response",
        about_id="booking-4821",
        phone_hash="ab" * 32,
        expires_at=expires_at,
        used_at=used_at,
    )


def _fixed_indexes(values: list[int]) -> Callable[[int], int]:
    remaining = iter(values)
    return lambda n: next(remaining)


# Link tokens


def test_a_fixed_rng_gives_the_expected_letters_only_token() -> None:
    # The 128 bits as a base-52 number of 23 letters (A to Z then a to z), most significant first.
    token = new_link_token(lambda n: bytes(range(n)))
    assert token == "AAANBIwkBaxtDAmhYpkjeHD"
    assert len(token) == 23
    assert LINK_TOKEN.fullmatch(token)


def test_the_token_source_asks_for_sixteen_bytes() -> None:
    asked: list[int] = []

    def rng(n: int) -> bytes:
        asked.append(n)
        return bytes(n)

    new_link_token(rng)
    assert asked == [16]


def test_two_default_tokens_differ() -> None:
    first = new_link_token()
    assert LINK_TOKEN.fullmatch(first)
    assert first != new_link_token()


@pytest.mark.parametrize("raw", [b"", bytes(15), bytes(17)])
def test_the_rng_must_give_exactly_128_bits(raw: bytes) -> None:
    with pytest.raises(ValidationFailed) as info:
        new_link_token(lambda n: raw)
    assert info.value.field == "token"


def test_the_rng_must_give_bytes() -> None:
    with pytest.raises(ValidationFailed) as info:
        new_link_token(lambda n: "x" * n)  # type: ignore[arg-type, return-value]
    assert info.value.field == "token"


# Hashing


def test_the_hash_is_hmac_sha256_in_hex() -> None:
    expected = hmac.new(b"k", b"abc", hashlib.sha256).hexdigest()
    assert hash_token("abc", b"k") == expected


def test_a_different_secret_gives_a_different_hash() -> None:
    assert hash_token("abc", b"k") != hash_token("abc", b"j")


def test_a_different_token_gives_a_different_hash() -> None:
    assert hash_token("abd", b"k") != hash_token("abc", b"k")


def test_an_empty_secret_is_refused() -> None:
    with pytest.raises(ValidationFailed) as info:
        hash_token("abc", b"")
    assert info.value.field == "secret"


@pytest.mark.parametrize("token", ["", "ab c", "abcé"])
def test_a_token_outside_the_url_safe_alphabet_is_refused(token: str) -> None:
    with pytest.raises(ValidationFailed) as info:
        hash_token(token, SECRET)
    assert info.value.field == "token"


def test_a_refused_token_is_never_echoed() -> None:
    with pytest.raises(ValidationFailed) as info:
        hash_token("ab c-secretlike", SECRET)
    assert "secretlike" not in str(info.value)
    assert "ab c" not in str(info.value)


# Checking a link


def test_an_unused_link_before_expiry_is_ok() -> None:
    assert check_link(_record(expires_at=LATER), NOW) is LinkCheck.OK


def test_a_link_is_expired_at_the_expiry_instant() -> None:
    assert check_link(_record(expires_at=NOW), NOW) is LinkCheck.EXPIRED


def test_a_link_one_microsecond_before_expiry_is_ok() -> None:
    assert check_link(_record(expires_at=NOW), NOW - timedelta(microseconds=1)) is LinkCheck.OK


def test_used_takes_precedence_over_expired() -> None:
    record = _record(expires_at=NOW, used_at=NOW - timedelta(minutes=1))
    assert check_link(record, LATER) is LinkCheck.USED


def test_a_used_link_before_expiry_is_used() -> None:
    record = _record(expires_at=LATER, used_at=NOW)
    assert check_link(record, NOW) is LinkCheck.USED


def test_instants_are_compared_in_utc_across_the_autumn_change() -> None:
    # 01:50 GMT (second occurrence, fold=1) is 01:50Z; 01:55 BST (fold=0) is 00:55Z.
    # 00:55Z is before 01:50Z, so the link is still ok. Comparing wall clocks would say expired.
    expires_at = datetime(2026, 10, 25, 1, 50, tzinfo=LONDON, fold=1)
    now = datetime(2026, 10, 25, 1, 55, tzinfo=LONDON, fold=0)
    assert check_link(_record(expires_at=expires_at), now) is LinkCheck.OK


@pytest.mark.parametrize(
    "bad",
    [datetime(2026, 10, 25, 14, 0), datetime(2026, 10, 25, 14, 0, tzinfo=None)],
)
def test_a_naive_now_is_refused(bad: datetime) -> None:
    with pytest.raises(ValidationFailed) as info:
        check_link(_record(), bad)
    assert info.value.field == "now"


def test_a_record_refuses_a_naive_expiry() -> None:
    with pytest.raises(ValidationFailed) as info:
        _record(expires_at=datetime(2026, 10, 25, 16, 0))
    assert info.value.field == "expires_at"


def test_a_record_refuses_a_naive_used_at() -> None:
    with pytest.raises(ValidationFailed) as info:
        _record(used_at=datetime(2026, 10, 25, 14, 0))
    assert info.value.field == "used_at"


# Pairing codes


def test_a_fixed_rng_gives_six_repeated_digits() -> None:
    assert new_pairing_code(lambda n: 7) == "777777"


def test_leading_zeros_are_kept() -> None:
    assert new_pairing_code(lambda n: 0) == "000000"


def test_each_digit_is_drawn_from_ten_values() -> None:
    asked: list[int] = []

    def rng(n: int) -> int:
        asked.append(n)
        return 1

    assert new_pairing_code(rng) == "111111"
    assert asked == [10] * 6


@pytest.mark.parametrize("value", [-1, 10, True, 1.0])
def test_a_pairing_rng_result_must_be_a_digit(value: object) -> None:
    with pytest.raises(ValidationFailed) as info:
        new_pairing_code(lambda n: value)  # type: ignore[arg-type, return-value]
    assert info.value.field == "code"


def test_a_pairing_code_is_shown_in_two_halves() -> None:
    assert format_pairing_code("482913") == "482 913"


@pytest.mark.parametrize("bad", ["12345", "1234567", "48 2913", "48291A", ""])
def test_a_malformed_pairing_code_is_refused_without_echo(bad: str) -> None:
    with pytest.raises(ValidationFailed) as info:
        format_pairing_code(bad)
    assert info.value.field == "code"
    if bad:
        assert bad not in str(info.value)


@given(st.lists(st.integers(min_value=0, max_value=9), min_size=6, max_size=6))
def test_any_six_digits_give_a_code_that_keeps_its_digits(digits: list[int]) -> None:
    code = new_pairing_code(_fixed_indexes(digits))
    assert code == "".join(str(d) for d in digits)
    assert format_pairing_code(code) == f"{code[:3]} {code[3:]}"


def test_a_pairing_code_is_valid_for_ten_minutes() -> None:
    assert timedelta(minutes=10) == PAIRING_CODE_VALID_FOR


def test_a_pairing_code_issued_at_1400_is_not_expired_at_1409_59() -> None:
    issued = datetime(2026, 10, 25, 14, 0, tzinfo=UTC)
    assert pairing_code_expired(issued, datetime(2026, 10, 25, 14, 9, 59, tzinfo=UTC)) is False


def test_a_pairing_code_issued_at_1400_is_expired_at_1410() -> None:
    issued = datetime(2026, 10, 25, 14, 0, tzinfo=UTC)
    assert pairing_code_expired(issued, datetime(2026, 10, 25, 14, 10, tzinfo=UTC)) is True


def test_pairing_expiry_compares_instants_across_the_autumn_change() -> None:
    # Issued 01:50 BST (00:50Z); checked 01:55 GMT (01:55Z): 65 minutes later, so expired.
    issued = datetime(2026, 10, 25, 1, 50, tzinfo=LONDON, fold=0)
    now = datetime(2026, 10, 25, 1, 55, tzinfo=LONDON, fold=1)
    assert pairing_code_expired(issued, now) is True


def test_a_pairing_issue_time_in_the_future_is_refused() -> None:
    with pytest.raises(ValidationFailed) as info:
        pairing_code_expired(LATER, NOW)
    assert info.value.field == "issued_at"


def test_a_naive_pairing_time_is_refused() -> None:
    with pytest.raises(ValidationFailed) as info:
        pairing_code_expired(datetime(2026, 10, 25, 14, 0), NOW)
    assert info.value.field == "issued_at"


# Support codes


def test_the_support_alphabet_has_31_unambiguous_characters() -> None:
    assert SUPPORT_CODE_ALPHABET == "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    assert len(SUPPORT_CODE_ALPHABET) == 31
    assert not set("0O1IL") & set(SUPPORT_CODE_ALPHABET)


def test_a_fixed_rng_gives_the_formatted_support_code() -> None:
    assert new_support_code(_fixed_indexes([0, 1, 2, 3, 4, 5, 6, 7])) == "ABCD-EFGH"


def test_the_support_rng_is_asked_for_the_alphabet_size_each_time() -> None:
    asked: list[int] = []

    def rng(n: int) -> int:
        asked.append(n)
        return 0

    new_support_code(rng)
    assert asked == [31] * 8


def test_the_last_alphabet_character_is_chosen_by_index_30() -> None:
    assert new_support_code(lambda n: 30) == "9999-9999"


@pytest.mark.parametrize("value", [-1, 31, True])
def test_a_support_rng_result_outside_the_alphabet_is_refused(value: object) -> None:
    with pytest.raises(ValidationFailed) as info:
        new_support_code(lambda n: value)  # type: ignore[arg-type, return-value]
    assert info.value.field == "code"


def test_a_thousand_random_support_codes_avoid_ambiguous_characters() -> None:
    for _ in range(1000):
        code = new_support_code()
        assert SUPPORT_CODE.fullmatch(code), "support code is not XXXX-XXXX from the alphabet"
        assert not set("0O1IL") & set(code)


@given(st.lists(st.integers(min_value=0, max_value=30), min_size=8, max_size=8))
def test_any_indexes_give_a_support_code_from_the_alphabet(indexes: list[int]) -> None:
    code = new_support_code(_fixed_indexes(indexes))
    assert SUPPORT_CODE.fullmatch(code)
    assert code.replace("-", "") == "".join(SUPPORT_CODE_ALPHABET[i] for i in indexes)
