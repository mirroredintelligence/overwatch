"""The local postcode-centroid lookup (I11). No Docker and no network.

The fixture is tests/fixtures/postcode_centroids_sample.csv, with made-up DT postcodes. A full
postcode that is not in the file falls back to its district's mean with approximate=True, a partial
postcode resolves at district level, and an unknown district is None. A patient postcode is looked
up here and never sent anywhere (DEC-047).
"""

import builtins
import socket
from pathlib import Path
from typing import Any

import pytest

from diucs.adapters.outbound.postcodes_local import centroids
from diucs.adapters.outbound.postcodes_local.centroids import CsvPostcodeLocator, Located
from diucs.application.ports.outbound.geo import LatLon
from diucs.domain.errors import ValidationFailed

FIXTURE = Path(__file__).resolve().parents[4] / "fixtures" / "postcode_centroids_sample.csv"
DT4_8XX = LatLon(50.6151, -2.4612)


@pytest.fixture
def locator() -> CsvPostcodeLocator:
    return CsvPostcodeLocator(FIXTURE)


def _district_mean(district_rows: list[tuple[float, float]]) -> LatLon:
    lats = [lat for lat, _ in district_rows]
    lons = [lon for _, lon in district_rows]
    return LatLon(sum(lats) / len(lats), sum(lons) / len(lons))


def _close(a: LatLon, b: LatLon) -> bool:
    return abs(a.lat - b.lat) < 1e-9 and abs(a.lon - b.lon) < 1e-9


# --- 1 to 3: lookups -----------------------------------------------------------------------------


def test_a_postcode_in_any_case_and_spacing_gives_the_fixture_coordinates(
    locator: CsvPostcodeLocator,
) -> None:
    assert locator.centroid("dt4 8xx") == DT4_8XX
    assert locator.centroid("DT48XX") == DT4_8XX
    assert locator.centroid(" DT4  8XX ") == DT4_8XX


def test_an_exact_postcode_is_located_and_is_not_approximate(locator: CsvPostcodeLocator) -> None:
    assert locator.locate("dt4 8xx") == Located(DT4_8XX, approximate=False)


def test_an_unknown_full_postcode_in_a_known_district_gives_the_district_mean_and_is_approximate(
    locator: CsvPostcodeLocator,
) -> None:
    located = locator.locate("DT4 8ZQ")

    assert located is not None
    assert located.approximate is True
    assert _close(
        located.lat_lon,
        _district_mean([(50.6151, -2.4612), (50.6160, -2.4590), (50.6240, -2.4480)]),
    )


def test_a_partial_postcode_resolves_at_district_level(locator: CsvPostcodeLocator) -> None:
    partial = locator.locate("DT4 8X")
    district = locator.district_centroid("DT4")

    assert partial is not None
    assert partial.approximate is True
    assert district is not None
    assert _close(partial.lat_lon, district)


def test_a_district_alone_resolves_at_district_level(locator: CsvPostcodeLocator) -> None:
    located = locator.locate("dt1")

    assert located is not None
    assert located.approximate is True


def test_an_unknown_postcode_in_an_unknown_district_is_none(locator: CsvPostcodeLocator) -> None:
    assert locator.centroid("ZZ9 9ZZ") is None
    assert locator.locate("ZZ9 9ZZ") is None
    assert locator.locate("ZZ9 9") is None
    assert locator.district_centroid("ZZ9") is None


@pytest.mark.parametrize("text", ["", "   ", "DT4 8XXX", "DT4 ABC", "not a postcode", "DT48XXX"])
def test_text_that_is_not_a_postcode_or_district_is_none(
    locator: CsvPostcodeLocator, text: str
) -> None:
    assert locator.locate(text) is None
    assert locator.centroid(text) is None


# --- 7: the file is opened once ------------------------------------------------------------------


def test_the_csv_is_opened_once_and_lookups_never_open_it_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[Any] = []
    real_open = builtins.open

    def spy(file: Any, *args: Any, **kwargs: Any) -> Any:
        opened.append(file)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(centroids, "open", spy, raising=False)
    locator = CsvPostcodeLocator(FIXTURE)
    for _ in range(50):
        locator.locate("DT4 8XX")
        locator.locate("DT4 8ZQ")
        locator.district_centroid("DT1")

    assert len(opened) == 1


# --- no network ----------------------------------------------------------------------------------


def test_lookups_make_no_network_call(
    locator: CsvPostcodeLocator, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a postcode lookup must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)

    assert locator.locate("DT4 8ZQ") is not None


# --- the file is checked when it is loaded, and no value is echoed -------------------------------


@pytest.mark.parametrize(
    ("content", "field"),
    [
        ("postcode,lat,lon\nDT4 8XX,50.6,-2.4\n", "header"),
        ("postcode,latitude,longitude\nNOT-A-CODE,50.6,-2.4\n", "postcode"),
        ("postcode,latitude,longitude\nDT4 8XX,north,-2.4\n", "latitude"),
        ("postcode,latitude,longitude\nDT4 8XX,-2.4,50.6\n", "latitude"),
        ("postcode,latitude,longitude\nDT4 8XX,50.6,-2.4\nDT4 8XX,50.7,-2.5\n", "postcode"),
        ("postcode,latitude,longitude\nDT4 8XX,nan,-2.4\n", "latitude"),
        ("postcode,latitude,longitude\nDT4 8XX,50.6\n", "row"),
    ],
)
def test_a_malformed_file_is_refused_on_load_and_names_no_value(
    tmp_path: Path, content: str, field: str
) -> None:
    path = tmp_path / "centroids.csv"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValidationFailed) as refused:
        CsvPostcodeLocator(path)

    assert refused.value.field == field
    assert "DT4 8XX" not in str(refused.value)
    assert "NOT-A-CODE" not in str(refused.value)
