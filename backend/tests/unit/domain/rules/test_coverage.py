"""The circle a visiting service is drawn with (KI-626, KI-627, KI-801, DEC-1175).

A visiting service has no site, only the districts it covers. The map draws a circle that holds the
centre of each of them: the mean of their centres, and the distance to the farthest one, rounded up
to a whole number of kilometres and never under one. It is a picture of where the service goes, not
a boundary: the options list and the criteria decide who is covered.
"""

import math

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.coverage import CoverageCircle, coverage_circle

DEGREE_KM = 111.195  # one degree of latitude on the earth sphere the rule uses


def test_no_district_with_a_place_gives_no_circle() -> None:
    assert coverage_circle([]) is None


def test_one_district_is_a_circle_of_one_kilometre_around_its_centre() -> None:
    circle = coverage_circle([(50.7, -2.4)])

    assert circle == CoverageCircle(lat=50.7, lon=-2.4, radius_km=1)


def test_the_circle_is_centred_on_the_mean_and_reaches_the_farthest_district() -> None:
    circle = coverage_circle([(50.0, -2.0), (50.2, -2.0)])

    assert circle is not None
    assert circle.lat == pytest.approx(50.1)
    assert circle.lon == pytest.approx(-2.0)
    assert circle.radius_km == math.ceil(0.1 * DEGREE_KM)


def test_the_radius_is_a_whole_number_rounded_up_never_down() -> None:
    near = coverage_circle([(50.0, -2.0), (50.0 + 2.0 / DEGREE_KM, -2.0)])

    assert near is not None
    assert near.radius_km == 1


def test_a_circle_holds_every_district_centre_it_was_made_from() -> None:
    points = [(50.7, -2.4), (50.62, -2.2), (50.8, -2.1), (50.55, -2.5)]

    circle = coverage_circle(points)

    assert circle is not None
    for lat, lon in points:
        flat = math.hypot((lat - circle.lat) * DEGREE_KM, (lon - circle.lon) * DEGREE_KM * 0.64)
        assert flat <= circle.radius_km + 1


@pytest.mark.parametrize(
    "points",
    [
        [(float("nan"), -2.0)],
        [(50.0, float("inf"))],
        [(91.0, -2.0)],
        [(50.0, 181.0)],
        [(50.0, -2.0), (-95.0, 0.0)],
    ],
)
def test_a_position_that_cannot_be_a_place_never_draws_a_circle(
    points: list[tuple[float, float]],
) -> None:
    with pytest.raises(ValidationFailed):
        coverage_circle(points)
