"""The interim straight-line travel estimate (I11). No Docker and no network.

Road distance is the straight line times 1.3. The low end of the range uses 50 km/h and the high end
30 km/h. Each end is widened outward to a 5-minute step and is never under 5 minutes. The source is
"straight-line estimate". The worked example in the prompt is 20 km straight, 26 km by road, 30 to
55 minutes.
"""

import math
import socket

import pytest

from diucs.adapters.outbound.travel_time.straight_line import (
    EARTH_RADIUS_KM,
    SOURCE,
    StraightLineTravelTime,
    haversine_km,
)
from diucs.application.ports.outbound.geo import LatLon
from diucs.domain.errors import ValidationFailed

WHOLE_LONDON = LatLon(51.5074, -0.1278)
NEW_YORK = LatLon(40.7128, -74.0060)


def _north_of(origin: LatLon, km: float) -> LatLon:
    """The point km due north of origin on the same meridian (the great circle is the meridian)."""
    return LatLon(origin.lat + math.degrees(km / EARTH_RADIUS_KM), origin.lon)


def _reference_km(a: LatLon, b: LatLon) -> float:
    """The great-circle distance by the spherical law of cosines, a different formula from the
    haversine the adapter uses, so the test does not check the code against itself."""
    la, lb = math.radians(a.lat), math.radians(b.lat)
    dl = math.radians(b.lon - a.lon)
    central = math.acos(
        min(1.0, math.sin(la) * math.sin(lb) + math.cos(la) * math.cos(lb) * math.cos(dl))
    )
    return EARTH_RADIUS_KM * central


# --- 4: haversine --------------------------------------------------------------------------------


def test_haversine_matches_an_independent_reference_within_a_hundred_metres() -> None:
    assert abs(haversine_km(WHOLE_LONDON, NEW_YORK) - _reference_km(WHOLE_LONDON, NEW_YORK)) < 0.1


def test_haversine_is_symmetric_and_zero_for_the_same_point() -> None:
    assert haversine_km(WHOLE_LONDON, NEW_YORK) == pytest.approx(
        haversine_km(NEW_YORK, WHOLE_LONDON)
    )
    assert haversine_km(WHOLE_LONDON, WHOLE_LONDON) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("point", [LatLon(91.0, 0.0), LatLon(0.0, 181.0), LatLon(math.nan, 0.0)])
def test_haversine_refuses_a_point_outside_the_globe(point: LatLon) -> None:
    with pytest.raises(ValidationFailed):
        haversine_km(point, WHOLE_LONDON)


# --- 5: the worked example -----------------------------------------------------------------------


async def test_twenty_km_straight_is_twenty_six_km_by_road_and_thirty_to_fifty_five_minutes() -> (
    None
):
    origin = LatLon(50.7, -2.4)
    destination = _north_of(origin, 20.0)

    travel = await StraightLineTravelTime().estimate(origin, destination)

    assert (travel.low_minutes, travel.high_minutes) == (30, 55)


# --- 6: short distances and the source -----------------------------------------------------------


async def test_a_very_short_distance_is_at_least_five_minutes_at_both_ends() -> None:
    origin = LatLon(50.7, -2.4)

    same = await StraightLineTravelTime().estimate(origin, origin)
    short = await StraightLineTravelTime().estimate(origin, _north_of(origin, 0.1))

    assert (same.low_minutes, same.high_minutes) == (5, 5)
    assert (short.low_minutes, short.high_minutes) == (5, 5)


async def test_the_source_says_it_is_a_straight_line_estimate_and_the_range_is_a_range() -> None:
    origin = LatLon(50.7, -2.4)
    travel = await StraightLineTravelTime().estimate(origin, _north_of(origin, 12.0))

    assert travel.source == "straight-line estimate" == SOURCE
    assert travel.low_minutes <= travel.high_minutes
    assert travel.low_minutes % 5 == 0
    assert travel.high_minutes % 5 == 0


@pytest.mark.parametrize(("km", "low", "high"), [(10.0, 15, 30), (5.0, 5, 15), (40.0, 60, 105)])
async def test_the_ends_are_widened_to_five_minute_steps(km: float, low: int, high: int) -> None:
    origin = LatLon(50.7, -2.4)

    travel = await StraightLineTravelTime().estimate(origin, _north_of(origin, km))

    assert (travel.low_minutes, travel.high_minutes) == (low, high)


async def test_the_estimate_makes_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("a travel estimate must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)

    travel = await StraightLineTravelTime().estimate(WHOLE_LONDON, NEW_YORK)

    assert travel.high_minutes >= travel.low_minutes
