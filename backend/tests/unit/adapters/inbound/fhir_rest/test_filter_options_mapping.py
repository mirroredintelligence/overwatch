"""The `$filter-options` answer with the parts the options list (W13) and the map (W50) read
(W7A-A6). Pure: the result is built by hand.

Parts per option: category, overBy, unitLabel, lat and lon (a fixed site's place), the travel range
and its source. At the top: patientLat and patientLon (the postcode district's centre), and the
flags notFound and outOfArea, each sent only when true. What the domain does not hold is not sent:
a service phone (only a hash is stored), a coverage radius, travel legs and a network organisation.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from diucs.adapters.inbound.fhir_rest.case_mapping import filter_result_to_fhir
from diucs.application.ports.outbound.geo import LatLon, TravelRange
from diucs.application.use_cases.filter_options import (
    Coverage,
    FilterOptionsResult,
    NotSuitable,
    Option,
    TravelLeg,
)
from diucs.domain.codes import ServiceCategory, Status

NOW = datetime(2026, 10, 23, 13, 13, tzinfo=UTC)
SITE = LatLon(lat=50.73, lon=-2.45)
PATIENT = LatLon(lat=50.72, lon=-2.44)


def option(**changes: Any) -> Option:
    fields: dict[str, Any] = {
        "service_id": "svc-1",
        "name": "UCR West",
        "status": Status.OVER_CAPACITY,
        "effective_available": 0,
        "over_by": 2,
        "unit_label": "referrals",
        "data_age": timedelta(minutes=9),
        "travel": TravelRange(12, 18, "fixed"),
        "fits": ("Covers this postcode",),
        "warnings": ("Over capacity now. Phone to confirm before offering.",),
        "criteria_id": "crit-1",
        "criteria_version": 3,
        "category": ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        "position": SITE,
    }
    fields.update(changes)
    return Option(**fields)


def result(
    *options: Option,
    patient: LatLon | None = PATIENT,
    not_found: bool = False,
    out_of_area: bool = False,
    districts: tuple[str, ...] = (),
) -> FilterOptionsResult:
    return FilterOptionsResult(
        options=options,
        not_suitable=(NotSuitable("svc-2", "Ward B", "not accepting"),),
        generated_at=NOW,
        patient=patient,
        not_found=not_found,
        out_of_area=out_of_area,
        districts=districts,
    )


def parts(resource: dict[str, Any], which: str = "option") -> list[dict[str, Any]]:
    return [item for item in resource["parameter"] if item["name"] == which]


def named(items: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [part for part in items if part["name"] == name]


def test_an_option_carries_its_category_over_by_unit_and_place() -> None:
    resource = filter_result_to_fhir(result(option()))

    flat = parts(resource)[0]["part"]
    assert named(flat, "category") == [
        {"name": "category", "valueCode": "urgent-community-response"}
    ]
    assert named(flat, "overBy") == [{"name": "overBy", "valueInteger": 2}]
    assert named(flat, "unitLabel") == [{"name": "unitLabel", "valueString": "referrals"}]
    assert named(flat, "lat") == [{"name": "lat", "valueDecimal": 50.73}]
    assert named(flat, "lon") == [{"name": "lon", "valueDecimal": -2.45}]
    assert named(flat, "travelLow") == [{"name": "travelLow", "valueInteger": 12}]
    assert named(flat, "travelSource") == [{"name": "travelSource", "valueString": "fixed"}]


def test_a_service_with_no_place_and_not_over_capacity_sends_neither() -> None:
    resource = filter_result_to_fhir(
        result(option(position=None, over_by=None, travel=None, status=Status.ACCEPTING))
    )

    flat = parts(resource)[0]["part"]
    assert named(flat, "lat") == []
    assert named(flat, "lon") == []
    assert named(flat, "overBy") == []
    assert named(flat, "travelLow") == []


def test_the_patients_area_is_sent_when_the_postcode_is_found() -> None:
    resource = filter_result_to_fhir(result(option()))

    top = resource["parameter"]
    assert named(top, "patientLat") == [{"name": "patientLat", "valueDecimal": 50.72}]
    assert named(top, "patientLon") == [{"name": "patientLon", "valueDecimal": -2.44}]
    assert named(top, "notFound") == []
    assert named(top, "outOfArea") == []


def test_a_postcode_that_is_not_found_sends_the_flag_and_no_area() -> None:
    resource = filter_result_to_fhir(result(option(), patient=None, not_found=True))

    top = resource["parameter"]
    assert named(top, "notFound") == [{"name": "notFound", "valueBoolean": True}]
    assert named(top, "patientLat") == []
    assert named(top, "patientLon") == []


def test_a_postcode_outside_every_service_area_sends_the_flag() -> None:
    resource = filter_result_to_fhir(result(option(), out_of_area=True))

    assert named(resource["parameter"], "outOfArea") == [
        {"name": "outOfArea", "valueBoolean": True}
    ]


def test_the_not_suitable_services_are_unchanged() -> None:
    resource = filter_result_to_fhir(result(option()))

    assert parts(resource, "notSuitable") == [
        {
            "name": "notSuitable",
            "part": [
                {"name": "serviceId", "valueString": "svc-2"},
                {"name": "name", "valueString": "Ward B"},
                {"name": "reason", "valueString": "not accepting"},
            ],
        }
    ]


def test_the_districts_to_choose_from_are_sent_one_part_each_in_order() -> None:
    resource = filter_result_to_fhir(
        result(patient=None, not_found=True, districts=("DT1", "DT2", "BH1"))
    )

    assert named(resource["parameter"], "district") == [
        {"name": "district", "valueString": "DT1"},
        {"name": "district", "valueString": "DT2"},
        {"name": "district", "valueString": "BH1"},
    ]


def test_no_districts_sends_no_district_part() -> None:
    resource = filter_result_to_fhir(result(option()))

    assert named(resource["parameter"], "district") == []


# KI-626, KI-627, KI-801: the service phone, the coverage circle and the travel legs.


def test_a_service_with_a_phone_sends_it_as_a_part_and_one_without_sends_none() -> None:
    with_phone = filter_result_to_fhir(result(option(phone="01305 900100")))
    without = filter_result_to_fhir(result(option()))

    assert named(parts(with_phone)[0]["part"], "phone") == [
        {"name": "phone", "valueString": "01305 900100"}
    ]
    assert named(parts(without)[0]["part"], "phone") == []


def test_a_visiting_service_sends_its_circle_as_lat_lon_and_a_radius() -> None:
    visiting = option(position=None, travel=None, coverage=Coverage(50.1, -2.0, 12))

    flat = parts(filter_result_to_fhir(result(visiting)))[0]["part"]

    assert named(flat, "lat") == [{"name": "lat", "valueDecimal": 50.1}]
    assert named(flat, "lon") == [{"name": "lon", "valueDecimal": -2.0}]
    assert named(flat, "coverageRadiusKm") == [{"name": "coverageRadiusKm", "valueDecimal": 12.0}]


def test_a_fixed_site_sends_no_radius() -> None:
    flat = parts(filter_result_to_fhir(result(option())))[0]["part"]

    assert named(flat, "coverageRadiusKm") == []


def test_the_travel_legs_are_sent_as_leg_parts_in_the_shape_the_screen_reads() -> None:
    leg = TravelLeg("Patient to UCR West, by road", 35, 50, "Typical weekday afternoon.", "Routing")

    flat = parts(filter_result_to_fhir(result(option(legs=(leg,)))))[0]["part"]

    assert named(flat, "leg") == [
        {
            "name": "leg",
            "part": [
                {"name": "label", "valueString": "Patient to UCR West, by road"},
                {"name": "low", "valueInteger": 35},
                {"name": "high", "valueInteger": 50},
                {"name": "how", "valueString": "Typical weekday afternoon."},
                {"name": "source", "valueString": "Routing"},
            ],
        }
    ]
