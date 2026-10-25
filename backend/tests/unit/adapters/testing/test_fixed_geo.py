"""Fixed-table geography fakes (P11). Answers come only from the table; no network (DEC-004)."""

import pytest

from diucs.adapters.testing.fixed_geo import FixedGeocoder, FixedPostcodeLocator, FixedTravelTime
from diucs.application.ports.outbound.geo import AddressCandidate, LatLon, TravelRange
from diucs.domain.errors import ValidationFailed

DT4_8XX = LatLon(50.61, -2.46)
DT4_CENTRE = LatLon(50.62, -2.47)
SITE = AddressCandidate(
    uprn="100000000001",
    line="1 Example Road",
    town="Exampletown",
    postcode="DT4 8XX",
    position=DT4_8XX,
)
FIXED = TravelRange(35, 50, "fixed")


def _locator() -> FixedPostcodeLocator:
    return FixedPostcodeLocator({"DT4 8XX": DT4_8XX}, {"DT4": DT4_CENTRE})


def test_known_postcode_has_its_centroid() -> None:
    assert _locator().centroid("DT4 8XX") == DT4_8XX


def test_postcode_is_normalised_before_lookup() -> None:
    assert _locator().centroid("  dt48xx ") == DT4_8XX


def test_unknown_postcode_has_no_centroid() -> None:
    assert _locator().centroid("DT4 9ZZ") is None


def test_malformed_postcode_has_no_centroid() -> None:
    assert _locator().centroid("not a code") is None


def test_known_district_has_its_centroid() -> None:
    assert _locator().district_centroid("DT4") == DT4_CENTRE


def test_district_is_trimmed_at_the_ends_only() -> None:
    assert _locator().district_centroid(" dt4 ") == DT4_CENTRE


def test_partly_spaced_district_is_not_found() -> None:
    assert _locator().district_centroid("DT4 8") is None


def test_unknown_district_has_no_centroid() -> None:
    assert _locator().district_centroid("DT9") is None


def test_malformed_table_postcode_is_refused_without_echoing_it() -> None:
    with pytest.raises(ValidationFailed) as info:
        FixedPostcodeLocator({"DT4 8X": DT4_8XX}, {})
    assert "DT4 8X" not in str(info.value)


def test_malformed_table_district_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        FixedPostcodeLocator({}, {"DT4 8": DT4_CENTRE})


async def test_known_postcode_returns_its_candidates() -> None:
    assert await FixedGeocoder({"DT4 8XX": [SITE]}).find_addresses("DT4 8XX") == [SITE]


async def test_postcode_is_normalised_before_geocoding() -> None:
    assert await FixedGeocoder({"DT4 8XX": [SITE]}).find_addresses("dt4 8xx") == [SITE]


async def test_unknown_postcode_returns_no_candidates() -> None:
    assert await FixedGeocoder({"DT4 8XX": [SITE]}).find_addresses("DT4 9ZZ") == []


async def test_returned_candidates_are_a_copy() -> None:
    geocoder = FixedGeocoder({"DT4 8XX": [SITE]})
    found = await geocoder.find_addresses("DT4 8XX")
    found.clear()
    assert await geocoder.find_addresses("DT4 8XX") == [SITE]


def test_malformed_table_postcode_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        FixedGeocoder({"bad": [SITE]})


async def test_default_range_is_returned_without_a_table() -> None:
    assert await FixedTravelTime(FIXED).estimate(DT4_8XX, DT4_CENTRE) == FIXED


async def test_default_range_is_returned_when_the_pair_is_not_in_the_table() -> None:
    travel = FixedTravelTime(FIXED, {(DT4_CENTRE, DT4_8XX): TravelRange(5, 10, "other")})
    assert await travel.estimate(DT4_8XX, DT4_CENTRE) == FIXED


async def test_table_entry_overrides_the_default() -> None:
    entry = TravelRange(10, 15, "table")
    travel = FixedTravelTime(FIXED, {(DT4_8XX, DT4_CENTRE): entry})
    assert await travel.estimate(DT4_8XX, DT4_CENTRE) == entry


async def test_table_is_directional() -> None:
    # Patient to site and site to patient are two numbers (architecture F8), so the reverse
    # pair is looked up separately and falls back to the default.
    travel = FixedTravelTime(FIXED, {(DT4_8XX, DT4_CENTRE): TravelRange(10, 15, "table")})
    assert await travel.estimate(DT4_CENTRE, DT4_8XX) == FIXED


async def test_table_is_copied_at_construction() -> None:
    table = {(DT4_8XX, DT4_CENTRE): TravelRange(10, 15, "table")}
    travel = FixedTravelTime(FIXED, table)
    table.clear()
    assert (await travel.estimate(DT4_8XX, DT4_CENTRE)).source == "table"
