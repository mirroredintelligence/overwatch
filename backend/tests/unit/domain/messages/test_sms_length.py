"""Tests for diucs.domain.messages.sms_length: SMS segment counting (D15).

GSM-7 basic set: 160 characters for one segment, 153 per segment after that. Extension
characters ^ { } \\ [ ~ ] | and the euro sign count as two. Any character outside GSM-7 switches
the whole message to UCS-2: 70 code units for one segment, 67 per segment after that.
"""

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.messages.sms_length import sms_segments


@pytest.mark.parametrize(
    ("text", "segments"),
    [
        ("a" * 160, 1),
        ("a" * 161, 2),
        ("a" * 306, 2),
        ("a" * 307, 3),
    ],
)
def test_gsm_segment_boundaries(text: str, segments: int) -> None:
    assert sms_segments(text) == segments


def test_euro_sign_counts_as_two_characters() -> None:
    assert sms_segments("€" * 80) == 1
    assert sms_segments("€" * 81) == 2


@pytest.mark.parametrize("char", ["^", "{", "}", "\\", "[", "~", "]", "|", "\f"])
def test_every_extension_character_counts_as_two(char: str) -> None:
    assert sms_segments(char * 80) == 1
    assert sms_segments(char * 81) == 2


def test_non_gsm_character_switches_to_ucs2() -> None:
    assert sms_segments("ł" * 70) == 1
    assert sms_segments("ł" * 71) == 2


def test_ucs2_later_segments_hold_67_units() -> None:
    # A concatenated UCS-2 message carries 67 units per segment, so 2 segments hold 134.
    assert sms_segments("ł" * 134) == 2
    assert sms_segments("ł" * 135) == 3


def test_one_non_gsm_character_makes_the_whole_text_ucs2() -> None:
    # 100 GSM characters plus one "ł" would be 1 GSM segment, but UCS-2 gives 2.
    assert sms_segments("a" * 100 + "ł") == 2


def test_non_bmp_character_counts_as_two_ucs2_units() -> None:
    assert sms_segments("😀" * 35) == 1
    assert sms_segments("😀" * 36) == 2


def test_empty_text_is_one_segment() -> None:
    assert sms_segments("") == 1


@given(st.text(alphabet=st.sampled_from("abcXYZ 0123456789.,:"), min_size=161, max_size=600))
def test_gsm_only_text_segments_follow_153_per_segment(text: str) -> None:
    assert sms_segments(text) == math.ceil(len(text) / 153)
