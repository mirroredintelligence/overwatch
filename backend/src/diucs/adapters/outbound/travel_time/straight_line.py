"""Interim straight-line travel-time estimate (I11). STUB for the red commit: names only."""

from typing import Final

from diucs.application.ports.outbound.geo import LatLon, TravelRange

EARTH_RADIUS_KM: Final = 6371.0088
ROAD_DISTANCE_FACTOR: Final = 1.3
FAST_SPEED_KMH: Final = 50.0
SLOW_SPEED_KMH: Final = 30.0
ROUND_TO_MINUTES: Final = 5
MINIMUM_MINUTES: Final = 5
SOURCE: Final = "straight-line estimate"


def haversine_km(a: LatLon, b: LatLon) -> float:
    raise NotImplementedError


class StraightLineTravelTime:
    async def estimate(self, origin: LatLon, destination: LatLon) -> TravelRange:
        raise NotImplementedError
