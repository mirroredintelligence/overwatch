"""Postcode normalisation and district rules (D19, docs/spec/domain-rules.md section 4.1).

Fixtures are synthetic or public sample values from the D19 prompt (SW1A 1AA and M1 1AE are
public, non-personal postcodes used there as examples). No patient postcode appears here.
"""

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.postcode import (
    normalise_district,
    normalise_postcode,
    partial_district,
    postcode_district,
)

FULL_PATTERN = r"[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}"
DISTRICT_PATTERN = r"[A-Z]{1,2}[0-9][A-Z0-9]?"
FULL_RE = re.compile(FULL_PATTERN)
DISTRICT_RE = re.compile(DISTRICT_PATTERN)


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("dt48xx", "DT4 8XX"),
        (" DT4  8XX ", "DT4 8XX"),
        ("sw1a1aa", "SW1A 1AA"),
        ("M11AE", "M1 1AE"),
        ("DT4\t8XX", "DT4 8XX"),
        ("SS1 1AA", "SS1 1AA"),
    ],
)
def test_normalise_postcode_canonical_form(typed: str, expected: str) -> None:
    assert normalise_postcode(typed) == expected


@pytest.mark.parametrize("typed", ["DT4 8X", "DT4", "", "12345", "DT4 8XXX", "DT4 8XX1", "DT48X"])
def test_normalise_postcode_rejects_partial_or_invalid(typed: str) -> None:
    assert normalise_postcode(typed) is None


def test_normalise_postcode_rejects_non_ascii_look_alikes() -> None:
    # 'ß' upper-cases to 'SS', which would otherwise make a valid-looking postcode.
    assert normalise_postcode("ß1 1AA") is None
    assert normalise_postcode("ß1 1aa") is None


@pytest.mark.parametrize(
    ("postcode", "district"),
    [("DT4 8XX", "DT4"), ("SW1A 1AA", "SW1A"), ("M1 1AE", "M1")],
)
def test_postcode_district_is_the_outward_code(postcode: str, district: str) -> None:
    assert postcode_district(postcode) == district


def test_postcode_district_rejects_unnormalised_input() -> None:
    with pytest.raises(ValidationFailed) as info:
        postcode_district("dt48xx")
    assert info.value.field == "postcode"


def test_postcode_district_error_never_echoes_the_input() -> None:
    with pytest.raises(ValidationFailed) as info:
        postcode_district("dt48xx")
    assert "dt48xx" not in str(info.value)
    assert "DT48XX" not in str(info.value)
    assert "dt48xx" not in info.value.message


@pytest.mark.parametrize(
    ("typed", "expected"),
    [("dt4", "DT4"), (" DT4 ", "DT4"), ("m1", "M1"), ("sw1a", "SW1A")],
)
def test_normalise_district_accepts_a_district(typed: str, expected: str) -> None:
    assert normalise_district(typed) == expected


@pytest.mark.parametrize("typed", ["DT4 8XX", "D", "", "DT4 8", "dt 4", "1DT4", "ß1"])
def test_normalise_district_rejects_non_districts(typed: str) -> None:
    assert normalise_district(typed) is None


@given(st.from_regex(FULL_PATTERN, fullmatch=True))
def test_canonical_postcode_survives_case_and_spacing_noise(canonical: str) -> None:
    assert normalise_postcode(canonical) == canonical
    assert normalise_postcode(canonical.lower().replace(" ", "")) == canonical
    assert postcode_district(canonical) == canonical.split(" ")[0]


@given(st.text())
def test_normalise_postcode_output_is_canonical_or_none(text: str) -> None:
    result = normalise_postcode(text)
    if result is not None:
        assert FULL_RE.fullmatch(result)
        assert normalise_postcode(result) == result


@given(st.text())
def test_normalise_district_output_is_canonical_or_none(text: str) -> None:
    result = normalise_district(text)
    if result is not None:
        assert DISTRICT_RE.fullmatch(result)
        assert normalise_district(result) == result


@given(st.from_regex(FULL_PATTERN, fullmatch=True))
def test_full_postcode_is_never_a_district(canonical: str) -> None:
    assert normalise_district(canonical) is None


@pytest.mark.parametrize(
    ("text", "district"),
    [
        ("DT4 8X", "DT4"),
        ("dt4 8x", "DT4"),
        ("DT4 8", "DT4"),
        ("DT4 8XY", "DT4"),
        ("DT4", "DT4"),
        ("dt1", "DT1"),
        ("  DT4 8X  ", "DT4"),
    ],
)
def test_a_partial_postcode_or_bare_district_names_its_district(text: str, district: str) -> None:
    assert partial_district(text) == district


@pytest.mark.parametrize(
    "text",
    ["", "   ", "DT4 8XXX", "DT4 ABC", "DT4 8 X", "DT48X", "ZZ", "1A 2B", "DT4 8\u00d8"],
)
def test_text_that_names_no_district_is_none(text: str) -> None:
    assert partial_district(text) is None
