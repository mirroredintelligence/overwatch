"""The circle a visiting service is drawn with on the options map (KI-626, 627, 801, DEC-1175).

A visiting service has no site: the domain holds the districts it covers and nothing else. The map
draws one circle that holds the centre of each covered district: the mean of those centres, and the
distance to the farthest of them, rounded up to a whole number of kilometres and never under one.
It is a picture of where the service goes, never a boundary: the options list and the service's
criteria decide who is covered. Pure.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from diucs.domain.errors import ValidationFailed

EARTH_RADIUS_KM: Final = 6371.0088
MIN_RADIUS_KM: Final = 1


@dataclass(frozen=True, slots=True)
class CoverageCircle:
    lat: float
    lon: float
    radius_km: int


def _checked(lat: float, lon: float) -> None:
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValidationFailed("position", "must be a finite latitude and longitude")
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise ValidationFailed("position", "is outside the globe")


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat_a, lat_b = math.radians(a[0]), math.radians(b[0])
    d_lat = lat_b - lat_a
    d_lon = math.radians(b[1] - a[1])
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def coverage_circle(points: Sequence[tuple[float, float]]) -> CoverageCircle | None:
    """The circle for these (lat, lon) district centres, or None when there are none. A position
    that cannot be a place raises: a bad coordinate never draws a circle."""
    if not points:
        return None
    for lat, lon in points:
        _checked(lat, lon)
    centre = (
        sum(lat for lat, _ in points) / len(points),
        sum(lon for _, lon in points) / len(points),
    )
    reach = max(_km(centre, point) for point in points)
    return CoverageCircle(
        lat=centre[0], lon=centre[1], radius_km=max(MIN_RADIUS_KM, math.ceil(reach - 1e-9))
    )
