"""The link token's alphabet and layout cannot match a privacy-guard pattern, and keep 128 bits.

The guard (domain/messages/privacy_guard.py) has three patterns. A postcode needs a digit and a
word boundary on both sides, so inside a token it can only match a whole word of 5 to 7
characters. An NHS number needs ten digits. A titled name needs whitespace. A token of letters
only, with no "-", "_", digit or space, and 23 characters long, can match none of them (DEC-152).
The 128 bits that domain-rules 7 and DEC-115 require are kept: 52 ** 23 is more than 2 ** 128.
"""

import math
import random
import re
import string
from typing import Final

from diucs.domain.rules.tokens import (
    LINK_TOKEN_ALPHABET,
    LINK_TOKEN_BYTES,
    LINK_TOKEN_LENGTH,
    new_link_token,
)

SEED: Final = 20261029
DEC_115_MINIMUM_BITS: Final = 128  # domain-rules 7: at least 128 bits of randomness


# Why it cannot match: the alphabet and the layout, proved from what the guard's patterns need.


def test_the_alphabet_is_letters_only_so_no_pattern_can_match() -> None:
    # Postcode: needs a digit, and a word boundary on both sides, so only a whole-word run of 5 to
    # 7 characters can match. A token with no "-" has no boundary inside it. NHS number: needs ten
    # digits. Titled name: needs whitespace. A letters-only token with no separator has none of the
    # three, whatever its text.
    assert set(LINK_TOKEN_ALPHABET) == set(string.ascii_letters)
    assert set(LINK_TOKEN_ALPHABET).isdisjoint(string.digits)
    assert set(LINK_TOKEN_ALPHABET).isdisjoint(string.whitespace)
    assert set(LINK_TOKEN_ALPHABET).isdisjoint("-_")
    assert LINK_TOKEN_LENGTH > 7  # longer than the longest whitespace-free postcode (7)


def test_every_token_is_one_unbroken_word_of_the_fixed_length() -> None:
    source = random.Random(SEED + 2)
    for _ in range(5_000):
        token = new_link_token(source.randbytes)
        assert len(token) == LINK_TOKEN_LENGTH
        assert re.fullmatch(r"[A-Za-z]+", token)
        assert re.fullmatch(rf"\w{{{LINK_TOKEN_LENGTH}}}", token)  # no word boundary inside


# Entropy: not reduced below the 128 bits that domain-rules 7 and DEC-115 require.


def test_the_token_space_holds_at_least_128_bits() -> None:
    assert len(LINK_TOKEN_ALPHABET) == 52
    assert LINK_TOKEN_LENGTH == 23
    assert len(set(LINK_TOKEN_ALPHABET)) == len(LINK_TOKEN_ALPHABET)
    assert len(LINK_TOKEN_ALPHABET) ** LINK_TOKEN_LENGTH >= 2**DEC_115_MINIMUM_BITS
    bits = LINK_TOKEN_LENGTH * math.log2(len(LINK_TOKEN_ALPHABET))
    assert bits >= DEC_115_MINIMUM_BITS
    assert LINK_TOKEN_BYTES * 8 == DEC_115_MINIMUM_BITS


def test_different_random_bytes_never_give_the_same_token() -> None:
    # The mapping is a fixed-length base-52 number, so it is one to one: all 128 bits survive.
    source = random.Random(SEED + 3)
    raws = {source.randbytes(16) for _ in range(50_000)}
    tokens = {new_link_token(lambda n, raw=raw: raw) for raw in raws}
    assert len(tokens) == len(raws)


def test_the_largest_input_fits_in_the_token_length() -> None:
    top = new_link_token(lambda n: bytes([255] * 16))
    assert top == "GBIWTpZqojFGQPQPXtvbJAv"
    assert new_link_token(lambda n: bytes(16)) == "A" * LINK_TOKEN_LENGTH
    assert new_link_token(lambda n: bytes(15) + b"\x01") == "A" * 22 + "B"
