"""Value objects of the geography port (P11). TravelRange validates its bounds (DEC-057)."""

from dataclasses import FrozenInstanceError

import pytest

from diucs.application.ports.outbound.geo import LatLon, TravelRange
from diucs.domain.errors import ValidationFailed


def test_range_keeps_its_bounds_and_source() -> None:
    travel = TravelRange(35, 50, "fixed")
    assert (travel.low_minutes, travel.high_minutes, travel.source) == (35, 50, "fixed")


def test_equal_bounds_are_a_valid_range() -> None:
    assert TravelRange(20, 20, "same-day").low_minutes == 20


def test_zero_minutes_is_a_valid_range() -> None:
    assert TravelRange(0, 0, "same-site").high_minutes == 0


def test_low_above_high_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        TravelRange(50, 35, "x")


def test_low_above_high_for_small_values_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        TravelRange(1, 0, "x")


def test_negative_low_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        TravelRange(-1, 5, "x")


def test_travel_range_is_immutable() -> None:
    travel = TravelRange(35, 50, "fixed")
    with pytest.raises(FrozenInstanceError):
        travel.low_minutes = 1  # type: ignore[misc]


def test_lat_lon_compares_by_value() -> None:
    assert LatLon(50.61, -2.46) == LatLon(50.61, -2.46)
