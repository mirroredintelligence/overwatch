from pathlib import Path

from overwatch.adapters.outbound.postcodes_local.centroids import CsvPostcodeLocator

# The pilot image ships this file (DEC-1312): it loads through the real loader.
SHIPPED = Path(__file__).resolve().parents[5] / "data" / "postcodes" / "centroids-dt-bh.csv"


def test_the_shipped_file_loads_and_places_a_dorchester_and_a_bournemouth_postcode() -> None:
    locator = CsvPostcodeLocator(SHIPPED)

    dorchester = locator.locate("DT1 1AA")
    bournemouth = locator.locate("BH1 1AA")

    assert dorchester is not None and not dorchester.approximate
    assert 50.6 < dorchester.lat_lon.lat < 50.8 and -2.6 < dorchester.lat_lon.lon < -2.3
    assert bournemouth is not None and not bournemouth.approximate
    assert 50.7 < bournemouth.lat_lon.lat < 50.8 and -1.95 < bournemouth.lat_lon.lon < -1.75


def test_a_postcode_outside_the_shipped_areas_is_not_placed() -> None:
    assert CsvPostcodeLocator(SHIPPED).locate("SW1A 1AA") is None


def test_the_nearest_postcode_gives_the_district_of_a_site() -> None:
    locator = CsvPostcodeLocator(SHIPPED)

    assert locator.district_at(50.6144, -2.4570) == "DT4"  # Weymouth
    assert locator.district_at(50.6087, -1.9577) == "BH19"  # Swanage
    assert locator.district_at(50.727909, -1.863623) == "BH1"  # the point of BH1 1AA


def test_a_site_far_from_every_postcode_in_the_file_has_no_district() -> None:
    locator = CsvPostcodeLocator(SHIPPED)

    assert locator.district_at(51.5074, -0.1278) is None  # London
    assert locator.district_at(0.0, 0.0) is None
