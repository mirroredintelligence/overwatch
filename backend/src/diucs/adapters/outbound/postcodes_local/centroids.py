"""Local postcode centroids (I11). STUB for the red commit: names only."""

from dataclasses import dataclass
from pathlib import Path

from diucs.application.ports.outbound.geo import LatLon


@dataclass(frozen=True, slots=True)
class Located:
    lat_lon: LatLon
    approximate: bool


class CsvPostcodeLocator:
    def __init__(self, path: Path | str) -> None:
        raise NotImplementedError

    def centroid(self, postcode: str) -> LatLon | None:
        raise NotImplementedError

    def district_centroid(self, district: str) -> LatLon | None:
        raise NotImplementedError

    def locate(self, postcode: str) -> Located | None:
        raise NotImplementedError
