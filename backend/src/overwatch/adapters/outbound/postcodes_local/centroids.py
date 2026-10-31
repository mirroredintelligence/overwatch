"""Local postcode centroids (I11): the position of a patient's postcode, from a file on the Trust's
own hosting. Patient postcodes never leave the Trust, so this adapter makes no network call.

The file is a CSV with the columns `postcode,latitude,longitude` (WGS84). Its source (ONS Postcode
Directory or OS Code-Point Open) and its licence for NHS use are an open decision; a one-off script
that converts the source is out of scope. The file is read once, when the locator is built, and
every row is checked then: a malformed file stops the start-up, and no value from it is put in an
error message (DEC-047).

Lookups normalise the text with the D19 rules, so 'dt48xx', 'DT4 8XX' and ' DT4  8XX ' are one
postcode. A full postcode that is not in the file is placed at its district's mean, and the answer
says so (approximate=True). A partial postcode such as 'DT4 8X', or a district on its own, is placed
at its district. Anything else is None: nothing is guessed.
"""

import csv
import math
from pathlib import Path
from typing import Final

from diucs.application.ports.outbound.geo import LatLon, Located
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.postcode import (
    normalise_district,
    normalise_postcode,
    partial_district,
    postcode_district,
)

COLUMNS: Final = ("postcode", "latitude", "longitude")

# A bounding box around the United Kingdom, in WGS84 degrees [ASSUMED]. A row outside it has its
# latitude and longitude the wrong way round, or is not a UK postcode, so the file is refused.
LATITUDE_RANGE: Final = (49.5, 61.0)
LONGITUDE_RANGE: Final = (-8.7, 2.0)


class CsvPostcodeLocator:
    """The PostcodeLocator of the production profile, loaded once from the CSV file."""

    def __init__(self, path: Path | str) -> None:
        self._postcodes: dict[str, LatLon] = {}
        self._districts: dict[str, LatLon] = {}
        self._load(Path(path))

    def _load(self, path: Path) -> None:
        sums: dict[str, tuple[float, float, int]] = {}
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or tuple(reader.fieldnames) != COLUMNS:
                raise ValidationFailed("header", "must be postcode,latitude,longitude")
            for line, row in enumerate(reader, start=2):
                key, position = self._row(row, line)
                if key in self._postcodes:
                    raise ValidationFailed("postcode", f"row {line} repeats an earlier postcode")
                self._postcodes[key] = position
                district = postcode_district(key)
                lat_sum, lon_sum, count = sums.get(district, (0.0, 0.0, 0))
                sums[district] = (lat_sum + position.lat, lon_sum + position.lon, count + 1)
        for district, (lat_sum, lon_sum, count) in sums.items():
            self._districts[district] = LatLon(lat_sum / count, lon_sum / count)

    @staticmethod
    def _row(row: dict[str, str | None], line: int) -> tuple[str, LatLon]:
        if None in row or any(value is None for value in row.values()):
            raise ValidationFailed("row", f"row {line} has a missing or extra field")
        key = normalise_postcode(row["postcode"] or "")
        if key is None:
            raise ValidationFailed("postcode", f"row {line} is not a full postcode")
        try:
            lat = float(row["latitude"] or "")
            lon = float(row["longitude"] or "")
        except ValueError:
            raise ValidationFailed("latitude", f"row {line} is not a number") from None
        if not (math.isfinite(lat) and math.isfinite(lon)):
            raise ValidationFailed("latitude", f"row {line} is not a finite number")
        if not (LATITUDE_RANGE[0] <= lat <= LATITUDE_RANGE[1]):
            raise ValidationFailed("latitude", f"row {line} is outside the United Kingdom")
        if not (LONGITUDE_RANGE[0] <= lon <= LONGITUDE_RANGE[1]):
            raise ValidationFailed("longitude", f"row {line} is outside the United Kingdom")
        return key, LatLon(lat, lon)

    def centroid(self, postcode: str) -> LatLon | None:
        """The point of this full postcode in the file, or None (no district fallback here)."""
        key = normalise_postcode(postcode)
        return None if key is None else self._postcodes.get(key)

    def district_centroid(self, district: str) -> LatLon | None:
        """The mean of the file's postcodes in this district, or None."""
        key = normalise_district(district)
        return None if key is None else self._districts.get(key)

    def locate(self, postcode: str) -> Located | None:
        """The position for a full or partial postcode, or a district. Exact when the postcode is
        in the file; otherwise its district's mean, approximate. None when nothing is known."""
        full = normalise_postcode(postcode)
        if full is not None:
            exact = self._postcodes.get(full)
            if exact is not None:
                return Located(exact, approximate=False)
            district = postcode_district(full)
        else:
            named = partial_district(postcode)
            if named is None:
                return None
            district = named
        centre = self._districts.get(district)
        return None if centre is None else Located(centre, approximate=True)
