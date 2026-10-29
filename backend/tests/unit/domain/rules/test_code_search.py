"""Search over a code list (R16): trimmed, case-insensitive, code order, at most 20, 2 chars."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.rules.code_search import MIN_SEARCH_LENGTH, search_codes

ENTRIES = [
    ("DxSAMPLE02", "Breathing check (not a real code)"),
    ("DxSAMPLE10", "Chest pain (not a real code)"),
    ("DxSAMPLE01", "Sample disposition 1 (not a real code)"),
]


def test_the_minimum_length_is_two() -> None:
    assert MIN_SEARCH_LENGTH == 2


def test_text_matches_a_part_of_the_display_ignoring_case() -> None:
    assert search_codes(ENTRIES, "BREATH", 20) == [
        ("DxSAMPLE02", "Breathing check (not a real code)")
    ]


def test_text_matches_a_part_of_the_code_ignoring_case() -> None:
    assert search_codes(ENTRIES, "sample01", 20) == [
        ("DxSAMPLE01", "Sample disposition 1 (not a real code)")
    ]


def test_results_are_in_code_order_whatever_the_input_order() -> None:
    codes = [code for code, _ in search_codes(ENTRIES, "samp", 20)]
    assert codes == ["DxSAMPLE01", "DxSAMPLE02", "DxSAMPLE10"]


def test_surrounding_spaces_are_ignored() -> None:
    assert search_codes(ENTRIES, "   breath  ", 20) == search_codes(ENTRIES, "breath", 20)


@pytest.mark.parametrize("text", ["", " ", "c", "  c  "])
def test_text_shorter_than_two_characters_finds_nothing(text: str) -> None:
    assert search_codes(ENTRIES, text, 20) == []


def test_no_match_is_an_empty_list() -> None:
    assert search_codes(ENTRIES, "zzz", 20) == []


def test_at_most_the_limit_is_returned_in_code_order() -> None:
    many = [(f"DxT{n:02d}", f"Test disposition {n}") for n in range(25)]
    result = search_codes(many, "test", 20)
    assert len(result) == 20
    assert result == many[:20]


@given(
    entries=st.lists(
        st.tuples(st.text(min_size=1, max_size=12), st.text(min_size=1, max_size=40)),
        max_size=30,
        unique_by=lambda entry: entry[0],
    ),
    text=st.text(max_size=6),
    limit=st.integers(min_value=1, max_value=25),
)
def test_every_result_matches_and_the_result_is_sorted_and_bounded(
    entries: list[tuple[str, str]], text: str, limit: int
) -> None:
    result = search_codes(entries, text, limit)
    needle = text.strip().casefold()
    assert len(result) <= limit
    assert [code for code, _ in result] == sorted(code for code, _ in result)
    if len(needle) < MIN_SEARCH_LENGTH:
        assert result == []
    for code, display in result:
        assert needle in code.casefold() or needle in display.casefold()
