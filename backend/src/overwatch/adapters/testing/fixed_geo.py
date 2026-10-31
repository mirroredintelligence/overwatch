"""Fixed-table fakes for the geography ports (P11). External providers only (DEC-002, DEC-004).

Each fake answers from a table the test writes down. None of them calls a network. An answer that
is not in the table is the documented "not found" answer, never a guess.

Postcode and district keys are normalised with the D19 rules (DEC-019, DEC-028), so a test can
write a table key in any spacing or case. A table key that is not a postcode or district is
refused when the fake is built, with the field name only: the value is never echoed (DEC-047).
"""

from collections.abc import Mapping, Sequence

from diucs.application.ports.outbound.geo import AddressCandidate, LatLon, Located, TravelRange
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.postcode import (
    normalise_district,
    normalise_postcode,
    partial_district,
    postcode_district,
)


def _postcode_key(postcode: str) -> str:
    key = normalise_postcode(postcode)
    if key is None:
        raise ValidationFailed("postcode", "table key must be a normalised full postcode")
    return key


def _district_key(district: str) -> str:
    key = normalise_district(district)
    if key is None:
        raise ValidationFailed("district", "table key must be a district")
    return key


class FixedGeocoder:
    """Answers geocoding from a table keyed by postcode. An unknown postcode has no candidates."""

    def __init__(self, table: Mapping[str, Sequence[AddressCandidate]]) -> None:
        self._table: dict[str, tuple[AddressCandidate, ...]] = {
            _postcode_key(postcode): tuple(candidates) for postcode, candidates in table.items()
        }

    async def find_addresses(self, postcode: str) -> list[AddressCandidate]:
        key = normalise_postcode(postcode)
        if key is None:
            return []
        return list(self._table.get(key, ()))


class FixedPostcodeLocator:
    """Answers centroids from two tables: full postcodes and districts. Unknown is None."""

    def __init__(self, postcodes: Mapping[str, LatLon], districts: Mapping[str, LatLon]) -> None:
        self._postcodes: dict[str, LatLon] = {
            _postcode_key(postcode): position for postcode, position in postcodes.items()
        }
        self._districts: dict[str, LatLon] = {
            _district_key(district): position for district, position in districts.items()
        }

    def centroid(self, postcode: str) -> LatLon | None:
        key = normalise_postcode(postcode)
        return None if key is None else self._postcodes.get(key)

    def district_centroid(self, district: str) -> LatLon | None:
        key = normalise_district(district)
        return None if key is None else self._districts.get(key)

    def locate(self, postcode: str) -> Located | None:
        """Exact when the full postcode is in the table; otherwise its district's position, marked
        approximate, for a full postcode or a partial one ('DT4 8X') whose district is in the table.
        An unknown value is None (the table holds no guess)."""
        key = normalise_postcode(postcode)
        if key is not None:
            exact = self._postcodes.get(key)
            if exact is not None:
                return Located(exact, approximate=False)
            district = postcode_district(key)
        else:
            named = partial_district(postcode)
            if named is None:
                return None
            district = named
        centre = self._districts.get(district)
        return None if centre is None else Located(centre, approximate=True)


class FixedTravelTime:
    """Answers travel time with a default range, overridden by a table keyed by (origin, dest).

    The table is directional: patient to site and site to patient are separate numbers
    (architecture F8), so the reverse pair falls back to the default unless it is in the table.
    """

    def __init__(
        self,
        default: TravelRange,
        table: Mapping[tuple[LatLon, LatLon], TravelRange] | None = None,
    ) -> None:
        self._default = default
        self._table: dict[tuple[LatLon, LatLon], TravelRange] = dict(table or {})

    async def estimate(self, origin: LatLon, destination: LatLon) -> TravelRange:
        return self._table.get((origin, destination), self._default)
