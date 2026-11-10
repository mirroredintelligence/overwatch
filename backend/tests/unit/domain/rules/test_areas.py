"""Named areas over postcode districts (DEC-1375): how a service is placed, how a table is read, and
that the table the pilot ships is a usable one. Pure: no Neo4j, no network."""

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from overwatch.domain.rules.areas import NETWORK, AreaTable, load_area_table, parse_area_table

SHIPPED = Path(__file__).resolve().parents[4] / "data" / "areas" / "dorset.json"
CENTROIDS = Path(__file__).resolve().parents[4] / "data" / "postcodes" / "centroids-dt-bh.csv"


def _table(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": "Test",
        "areas": [
            {"id": "north", "name": "North", "places": "A · B"},
            {"id": "south", "name": "South", "places": "C"},
        ],
        "network": {"id": "network", "name": "Everywhere", "places": "Across areas"},
        "districts": {"DT1": "north", "DT2": "north", "DT3": "south"},
    }
    data.update(changes)
    return data


def _built(**changes: Any) -> AreaTable:
    return parse_area_table(_table(**changes))


def test_a_service_in_one_area_is_placed_there_whatever_districts_it_covers_in_it() -> None:
    assert _built().place(["DT1", "DT2"]) == "north"
    assert _built().place(["dt3"]) == "south"


def test_a_service_that_covers_districts_of_two_areas_is_network_wide() -> None:
    assert _built().place(["DT1", "DT3"]) == NETWORK


def test_a_service_that_covers_no_district_is_placed_by_its_site() -> None:
    table = _built()
    assert table.place([], "DT3") == "south"
    assert table.place(["DT1"], "DT3") == "north"  # the districts it covers win over its site
    assert table.place([], None) is None


def test_districts_the_table_leaves_out_do_not_place_a_service() -> None:
    table = _built()
    assert table.place(["BH24"]) is None
    assert table.place(["BH24", "DT1"]) == "north"  # only the districts the table holds count


def test_with_no_network_group_a_service_across_areas_is_not_placed() -> None:
    assert _built(network=None).place(["DT1", "DT3"]) is None


def test_the_areas_are_listed_in_order_with_the_network_group_last() -> None:
    assert [area.id for area in _built().ordered()] == ["north", "south", "network"]
    assert [area.id for area in _built(network=None).ordered()] == ["north", "south"]


@pytest.mark.parametrize(
    "changes",
    [
        {"areas": [{"id": "North", "name": "N", "places": "x"}]},  # id not lower case
        {"areas": [{"id": "a", "name": "", "places": "x"}]},  # no name
        {"areas": [{"id": "a", "name": "N", "places": "x"}] * 2},  # the same id twice
        {"network": {"id": "other", "name": "N", "places": "x"}},  # the network id is fixed
        {"districts": {}},  # no districts
        {"districts": {"dt1": "north"}},  # not written as a district
        {"districts": {"DT1": "missing"}},  # names an area the table lacks
    ],
)
def test_a_table_that_is_not_usable_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        parse_area_table(_table(**changes))


def test_the_shipped_table_loads_and_every_area_holds_districts() -> None:
    table = load_area_table(SHIPPED)

    held = set(table.district_area.values())
    assert held == {area.id for area in table.areas}
    assert table.network is not None and table.network.id == NETWORK
    assert len(table.areas) == 5


def test_the_shipped_districts_are_districts_of_the_shipped_postcode_file() -> None:
    table = load_area_table(SHIPPED)
    with open(CENTROIDS, newline="", encoding="utf-8") as handle:
        file_districts = {row["postcode"].split(" ")[0] for row in csv.DictReader(handle)}

    assert set(table.district_area) <= file_districts
    # Two districts lie mostly in Hampshire and are left out on purpose.
    assert file_districts - set(table.district_area) == {"BH24", "BH25"}


@pytest.mark.parametrize(
    ("district", "area"),
    [
        ("BH1", "bcp"),
        ("BH21", "east-dorset"),
        ("BH19", "purbeck"),
        ("DT11", "north-dorset"),
        ("DT4", "south-west-dorset"),
    ],
)
def test_the_shipped_table_places_known_districts(district: str, area: str) -> None:
    assert load_area_table(SHIPPED).area_of(district) == area


def test_the_shipped_table_is_plain_json_text() -> None:
    assert isinstance(json.loads(SHIPPED.read_text(encoding="utf-8")), dict)
