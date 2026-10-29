"""Interim travel-time estimate from the straight line (I11), until a routing engine (I15).

Road distance is the great-circle distance times ROAD_DISTANCE_FACTOR. Travel time is that road
distance at FAST_SPEED_KMH (the low end of the range) and at SLOW_SPEED_KMH (the high end). Each end
is widened outward to the next ROUND_TO_MINUTES step: the low end rounds down and the high end
rounds up, so the range never claims more precision than the estimate has. Each end is at least
MINIMUM_MINUTES. The worked example in the prompt (20 km straight, 26 km by road) gives 30 to 55
minutes: 31.2 rounds down to 30 and 52 rounds up to 55.

No network call is made. The source is "straight-line estimate", so a caller can tell it from a
routed time. The answer is always a range, never a promise (ui-screens "MapWeb").
"""

import math
from typing import Final

from diucs.application.ports.outbound.geo import LatLon, TravelRange
from diucs.domain.errors import ValidationFailed

EARTH_RADIUS_KM: Final = 6371.0088
ROAD_DISTANCE_FACTOR: Final = 1.3  # [ASSUMED] road distance is 30% longer than the straight line
FAST_SPEED_KMH: Final = 50.0  # [ASSUMED] the low end of the range
SLOW_SPEED_KMH: Final = 30.0  # [ASSUMED] the high end of the range
ROUND_TO_MINUTES: Final = 5
MINIMUM_MINUTES: Final = 5
SOURCE: Final = "straight-line estimate"
_EPSILON: Final = 1e-9  # keeps an exact multiple of five from rounding the wrong way on float error


def _checked(point: LatLon) -> None:
    if not (math.isfinite(point.lat) and math.isfinite(point.lon)):
        raise ValidationFailed("position", "must be a finite latitude and longitude")
    if not -90.0 <= point.lat <= 90.0 or not -180.0 <= point.lon <= 180.0:
        raise ValidationFailed("position", "is outside the globe")


def haversine_km(a: LatLon, b: LatLon) -> float:
    """The great-circle distance between two WGS84 points, in kilometres."""
    _checked(a)
    _checked(b)
    lat_a, lat_b = math.radians(a.lat), math.radians(b.lat)
    d_lat = lat_b - lat_a
    d_lon = math.radians(b.lon - a.lon)
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def _minutes(distance_km: float, speed_kmh: float) -> float:
    return distance_km * ROAD_DISTANCE_FACTOR / speed_kmh * 60.0


def _round_down(minutes: float) -> int:
    steps = math.floor(minutes / ROUND_TO_MINUTES + _EPSILON)
    return max(MINIMUM_MINUTES, steps * ROUND_TO_MINUTES)


def _round_up(minutes: float) -> int:
    steps = math.ceil(minutes / ROUND_TO_MINUTES - _EPSILON)
    return max(MINIMUM_MINUTES, steps * ROUND_TO_MINUTES)


class StraightLineTravelTime:
    """The TravelTime port over the straight line. Always a range; never a single promised time."""

    async def estimate(self, origin: LatLon, destination: LatLon) -> TravelRange:
        distance = haversine_km(origin, destination)
        low = _round_down(_minutes(distance, FAST_SPEED_KMH))
        high = _round_up(_minutes(distance, SLOW_SPEED_KMH))
        return TravelRange(low_minutes=low, high_minutes=high, source=SOURCE)
