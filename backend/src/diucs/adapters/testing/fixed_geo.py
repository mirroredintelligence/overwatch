"""Fixed-table fakes for the geography ports (P11). External providers only (DEC-002, DEC-004).

Each fake answers from a table the test writes down. None of them calls a network. An answer that
is not in the table is the documented "not found" answer, never a guess.
"""

from collections.abc import Mapping, Sequence

from diucs.application.ports.outbound.geo import AddressCandidate, LatLon, TravelRange


class FixedGeocoder:
    def __init__(self, table: Mapping[str, Sequence[AddressCandidate]]) -> None:
        raise NotImplementedError

    async def find_addresses(self, postcode: str) -> list[AddressCandidate]:
        raise NotImplementedError


class FixedPostcodeLocator:
    def __init__(self, postcodes: Mapping[str, LatLon], districts: Mapping[str, LatLon]) -> None:
        raise NotImplementedError

    def centroid(self, postcode: str) -> LatLon | None:
        raise NotImplementedError

    def district_centroid(self, district: str) -> LatLon | None:
        raise NotImplementedError


class FixedTravelTime:
    def __init__(
        self,
        default: TravelRange,
        table: Mapping[tuple[LatLon, LatLon], TravelRange] | None = None,
    ) -> None:
        raise NotImplementedError

    async def estimate(self, origin: LatLon, destination: LatLon) -> TravelRange:
        raise NotImplementedError
