"""A random link token must never look like patient data (D17 privacy guard, H-09).

The defect: the link token was 22 characters of base64url. The alphabet includes digits, "-" and
letters, and "-" is a word boundary for the guard's regular expressions, so about 0.19 percent of
random tokens contained a segment shaped like a postcode or an NHS number. `render` then refused
the whole message (ValidationFailed "link: a patient-data shape is not allowed") and the capacity
prompt was never sent.

These tests use a seeded random source, so every run sees the same tokens. They run the real
guard (`find_patient_data`, and `render` for the whole message) over the real generator.
"""

import base64
import random
import re
from typing import Final

import pytest

from diucs.domain.codes import Channel
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.privacy_guard import find_patient_data
from diucs.domain.messages.templates import render
from diucs.domain.rules.tokens import (
    SUPPORT_CODE_ALPHABET,
    format_pairing_code,
    new_link_token,
    new_pairing_code,
    new_support_code,
)

SEED: Final = 20261029
SAMPLE_SIZE: Final = 300_000
LINK_BASE: Final = "diucs.example"

# Tokens as they were before the fix, for the reproduction only.
_NHS_SHAPE: Final = re.compile(r"[0-9 -]+")


def _legacy_token(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _legacy_raw(token: str) -> bytes:
    """The 16 bytes whose legacy (base64url, 22 character) form is `token`."""
    assert len(token) == 22
    return base64.urlsafe_b64decode(token + "==")


# 22-character legacy tokens that contain a postcode or an NHS-number shape, found by the
# verifier's sampling and made by hand here so they are certain. Each is a real base64url token
# (the last character is one of A, Q, g, w, so no stray bits), and so a value the old generator
# could produce.
FORCED_LEGACY_TOKENS: Final = {
    "postcode-in-the-middle": "AAAA-SW1A2AA-AAAAAAAAg",
    "postcode-at-the-start": "AB12CD-AAAAAAAAAAAAAAg",
    "nhs-number-contiguous": "AAAA-1234567890-AAAAAg",
    "nhs-number-grouped": "943-476-5919-AAAAAAAAg",
}


def _seeded_tokens(count: int) -> list[str]:
    source = random.Random(SEED)
    return [new_link_token(source.randbytes) for _ in range(count)]


def _c1(link: str) -> str:
    return render(
        MessageId.C1,
        Channel.TEXT,
        service="UCR West",
        value=3,
        unit="referrals",
        as_of="23 Oct 08:15",
        link=link,
        reply_by="10:30",
    ).text


# 1. Reproduction: the defect, measured on the legacy encoding with the same seeded bytes.


def test_the_legacy_encoding_matches_the_guard_at_the_reported_rate() -> None:
    source = random.Random(SEED)
    matches = [
        fragment
        for _ in range(SAMPLE_SIZE)
        for fragment in [find_patient_data(f"{LINK_BASE}/{_legacy_token(source.randbytes(16))}")]
        if fragment
    ]
    # The verifier saw 556 of 300000 (0.19 percent). This seed gives its own deterministic count:
    # 544 of 300000 (0.18 percent).
    assert len(matches) == 544  # all of them postcode shapes; none was an NHS number
    assert any(not _NHS_SHAPE.fullmatch(hit) for found in matches for hit in found)  # postcodes


@pytest.mark.parametrize("name", sorted(FORCED_LEGACY_TOKENS))
def test_each_forced_legacy_token_really_matches_the_guard(name: str) -> None:
    # The precondition of the forced tests below: these are tokens the old generator could make.
    legacy = FORCED_LEGACY_TOKENS[name]
    assert _legacy_token(_legacy_raw(legacy)) == legacy
    assert find_patient_data(f"{LINK_BASE}/{legacy}")


# 2. The fix: no guard match, over 300000 seeded tokens.


def test_no_seeded_token_matches_the_guard_in_a_link() -> None:
    offenders = [
        token
        for token in _seeded_tokens(SAMPLE_SIZE)
        if find_patient_data(f"{LINK_BASE}/{token}")
        or find_patient_data(f"https://{LINK_BASE}/r/{token}")
        or find_patient_data(token)
    ]
    assert offenders == []


def test_the_seeded_tokens_are_distinct() -> None:
    # A degenerate generator would pass the test above. 300000 draws from 2**128 never collide.
    tokens = _seeded_tokens(SAMPLE_SIZE)
    assert len(set(tokens)) == SAMPLE_SIZE


def test_whole_c1_messages_with_seeded_tokens_render() -> None:
    source = random.Random(SEED + 1)
    for _ in range(20_000):
        link = f"{LINK_BASE}/{new_link_token(source.randbytes)}"
        assert link in _c1(link)


@pytest.mark.parametrize("name", sorted(FORCED_LEGACY_TOKENS))
def test_bytes_that_made_a_matching_legacy_token_now_give_a_clean_link(name: str) -> None:
    # The same 128 random bits, which the old generator turned into a patient-data shape.
    raw = _legacy_raw(FORCED_LEGACY_TOKENS[name])
    token = new_link_token(lambda n: raw)
    link = f"{LINK_BASE}/{token}"
    assert find_patient_data(link) == []
    assert link in _c1(link)  # the whole prompt text is accepted by render, as in SendPrompts


@pytest.mark.parametrize("raw", [bytes(16), bytes([255] * 16), bytes(range(16))])
def test_the_extreme_inputs_give_clean_links(raw: bytes) -> None:
    link = f"{LINK_BASE}/{new_link_token(lambda n: raw)}"
    assert find_patient_data(link) == []
    assert link in _c1(link)


# 3. The same hazard for the other random identifiers.


def test_every_pairing_code_is_clean_in_both_forms() -> None:
    # Exhaustive: there are only a million codes.
    for number in range(1_000_000):
        code = f"{number:06d}"
        assert find_patient_data(code) == []
        assert find_patient_data(f"Code {format_pairing_code(code)}.") == []


def test_the_pairing_code_generator_gives_clean_codes() -> None:
    source = random.Random(SEED + 4)
    for _ in range(SAMPLE_SIZE):
        assert find_patient_data(format_pairing_code(new_pairing_code(source.randrange))) == []


def test_no_seeded_support_code_matches_the_guard() -> None:
    # XXXX-XXXX: each half is four characters, and a postcode needs five or more in one word.
    source = random.Random(SEED + 5)
    for _ in range(SAMPLE_SIZE):
        assert find_patient_data(new_support_code(source.randrange)) == []
    assert len(SUPPORT_CODE_ALPHABET) == 31
