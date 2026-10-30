"""The districts offered as chips when a postcode cannot be used (W50, W9H DEC-1045, DEC-1046).

When the locator does not know the case's district, or no service covers it, the advisor is offered the
districts the tenant's services DO cover, to pick one and run the options again. Pure: places in, an
ordered short list out. Nothing here is about a person: a district a service covers is the service's
configuration, never a case's.
"""

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.district_choice import MAX_DISTRICT_CHOICES, candidate_districts

# Dorset-shaped sample places (lat, lon). Distances matter only in order.
PLACES = {
    "DT1": (50.71, -2.44),
    "DT2": (50.72, -2.46),
    "DT4": (50.61, -2.45),
    "BH1": (50.72, -1.88),
    "BH2": (50.72, -1.87),
    "SP1": (51.07, -1.79),
}


def test_with_a_place_the_nearest_district_comes_first() -> None:
    chosen = candidate_districts(PLACES, origin=(50.71, -2.45), case_district="DT9")

    assert chosen[:3] == ("DT1", "DT2", "DT4")
    assert chosen[-1] == "SP1"


def test_equal_distances_are_ordered_by_the_district_name() -> None:
    chosen = candidate_districts(
        {"DT2": (50.0, -2.0), "DT10": (50.0, -2.0), "DT1": (50.0, -2.0)},
        origin=(50.0, -2.0),
        case_district=None,
    )

    assert chosen == ("DT1", "DT2", "DT10")


def test_with_no_place_the_districts_of_the_same_area_come_first_in_natural_order() -> None:
    chosen = candidate_districts(PLACES, origin=None, case_district="DT99")

    assert chosen == ("DT1", "DT2", "DT4", "BH1", "BH2", "SP1")


def test_with_no_place_and_no_case_district_the_order_is_natural() -> None:
    chosen = candidate_districts(
        {"DT10": (1.0, 1.0), "DT2": (1.0, 1.0), "B1": (1.0, 1.0), "BH1": (1.0, 1.0)},
        origin=None,
        case_district=None,
    )

    assert chosen == ("B1", "BH1", "DT2", "DT10")


def test_the_cases_own_district_is_never_offered() -> None:
    assert "DT4" not in candidate_districts(PLACES, origin=(50.61, -2.45), case_district="DT4")
    assert "DT4" not in candidate_districts(PLACES, origin=None, case_district="DT4")


def test_the_list_is_cut_at_the_limit_and_the_limit_is_twelve() -> None:
    many = {f"DT{n}": (50.0 + n / 100, -2.0) for n in range(1, 40)}

    chosen = candidate_districts(many, origin=(50.0, -2.0), case_district=None)

    assert MAX_DISTRICT_CHOICES == 12
    assert len(chosen) == 12
    assert chosen[0] == "DT1"


def test_no_places_is_no_choices() -> None:
    assert candidate_districts({}, origin=(50.0, -2.0), case_district="DT1") == ()


@pytest.mark.parametrize("district", ["dt4", "DT 4", "DT4X9", "1DT", "DT4-1"])
def test_a_district_that_is_not_one_is_refused_and_not_echoed(district: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        candidate_districts({district: (1.0, 1.0)}, origin=None, case_district=None)

    assert district not in str(refused.value)


def test_a_place_that_is_not_a_pair_of_numbers_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        candidate_districts({"DT1": ("north", "west")}, origin=None, case_district=None)  # type: ignore[dict-item]
