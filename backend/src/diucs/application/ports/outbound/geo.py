"""Outbound ports for geography (P11): geocoding, postcode centroids and travel time.

Geocoding (OS Places), the local postcode centroid file and the travel-time engine are external
providers, so each port has a fixed-table fake in diucs.adapters.testing (DEC-002, DEC-004). The
real adapters come later (I11, I12, I15).

Postcodes given to these ports are normalised by the caller or by the adapter using the D19 rules
(diucs.domain.rules.postcode). Nothing here logs or echoes a postcode (DEC-047).
"""

from dataclasses import dataclass
from typing import Protocol

from diucs.domain.errors import ValidationFailed


@dataclass(frozen=True, slots=True)
class LatLon:
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class AddressCandidate:
    uprn: str
    line: str
    town: str
    postcode: str
    position: LatLon


@dataclass(frozen=True, slots=True)
class TravelRange:
    """A travel time as a range, never a promise. `source` says where the range came from."""

    low_minutes: int
    high_minutes: int
    source: str

    def __post_init__(self) -> None:
        if not 0 <= self.low_minutes <= self.high_minutes:
            raise ValidationFailed("minutes", "must satisfy 0 <= low <= high")


class Geocoder(Protocol):
    async def find_addresses(self, postcode: str) -> list[AddressCandidate]: ...


@dataclass(frozen=True, slots=True)
class Located:
    """A position for a postcode. `approximate` is True when it is a district's mean, not the
    postcode's own point (I11): the advisor is then shown the district, not a house."""

    lat_lon: LatLon
    approximate: bool


class PostcodeLocator(Protocol):
    """Local centroid lookups. Read from a file held in memory, so the methods are synchronous."""

    def centroid(self, postcode: str) -> LatLon | None: ...

    def district_centroid(self, district: str) -> LatLon | None: ...

    def locate(self, postcode: str) -> Located | None:
        """The position of a full or partial postcode, or of a district: exact when the postcode
        is known, otherwise its district's position with approximate=True, else None."""
        ...


class TravelTime(Protocol):
    async def estimate(self, origin: LatLon, destination: LatLon) -> TravelRange: ...
