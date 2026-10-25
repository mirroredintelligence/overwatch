"""Pure tests for the FHIR-to-graph mapper (G04): backbone elements (rule R4) and the round trips.

R4: a backbone element that repeats or has several parts becomes a child node labelled
`<Type>_<Element>` (or `Address` and `ContactPoint`), keyed `<parentKey>#<element>[<order>]`,
linked from the parent by its catalogue relationship with `fhirPath` and, for a list, `order`.

DEC-049 and DEC-051: every case round-trips exactly or is refused with a DomainError. Nothing is
silently dropped, overwritten or moved. All values are synthetic.
"""

import json
import re
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.adapters.outbound.graph_store.extensions import EXTENSIONS
from diucs.adapters.outbound.graph_store.mapper import (
    GraphFragment,
    InvalidReference,
    NodeSpec,
    RelSpec,
    UnsupportedElement,
    from_graph,
    to_graph,
)
from diucs.domain.codes import BASE_URL
from diucs.domain.errors import DomainError, NotFound, ValidationFailed

ORG_ID = "6b1f0c2e-3a4d-4e5f-8a9b-0c1d2e3f4a5b"
LOC_ID = "7c2a1d3f-4b5e-4f60-9b0c-1d2e3f4a5b6c"
SVC_ID = "8d3b2e4a-5c6f-4071-8c1d-2e3f4a5b6c7d"
AREA_A_ID = "1a2b3c4d-0001-4000-8000-000000000001"
AREA_B_ID = "1a2b3c4d-0002-4000-8000-000000000002"
SVC_KEY = f"HealthcareService/{SVC_ID}"
ORG_KEY = f"Organization/{ORG_ID}"
LOC_KEY = f"Location/{LOC_ID}"

SERVICE_CATEGORY = "https://diucs.example/CodeSystem/service-category"
NEED = "https://diucs.example/CodeSystem/need-category"
REFERRAL_METHOD = "https://diucs.example/CodeSystem/referral-method"
CONTACT_PURPOSE = "https://diucs.example/CodeSystem/contact-purpose"


def _ext(short_name: str, value_key: str, value: Any) -> dict[str, Any]:
    return {"url": f"{BASE_URL}StructureDefinition/{short_name}", value_key: value}


SERVICE_EXTENSIONS: list[dict[str, Any]] = [
    _ext("smsShortName", "valueString", "UCRW"),
    _ext("establishedCapacity", "valueInteger", 8),
    _ext("canExceedEstablished", "valueBoolean", False),
    _ext("usualRangeMin", "valueInteger", 2),
    _ext("usualRangeMax", "valueInteger", 6),
    _ext("reportCadence", "valueString", "every-2-hrs"),
    _ext("limitedLevelPercent", "valueInteger", 80),
]

UCR_WEST: dict[str, Any] = {
    "resourceType": "HealthcareService",
    "id": SVC_ID,
    "active": True,
    "name": "UCR West",
    "category": [
        {
            "coding": [
                {
                    "system": SERVICE_CATEGORY,
                    "code": "urgent-community-response",
                    "display": "Urgent community response",
                }
            ]
        },
        {"coding": [{"system": SERVICE_CATEGORY, "code": "same-day-emergency-care"}]},
    ],
    "providedBy": {"reference": f"Organization/{ORG_ID}"},
    "coverageArea": [
        {"reference": f"Location/{AREA_A_ID}"},
        {"reference": f"Location/{AREA_B_ID}"},
    ],
    "referralMethod": [
        {"coding": [{"system": REFERRAL_METHOD, "code": "phone"}]},
        {"coding": [{"system": REFERRAL_METHOD, "code": "link"}], "text": "Web link"},
    ],
    "telecom": [{"system": "phone", "value": "07700 900000", "use": "work", "rank": 1}],
    "availableTime": [
        {
            "daysOfWeek": ["mon", "tue", "wed", "thu", "fri"],
            "availableStartTime": "08:00:00",
            "availableEndTime": "20:00:00",
        },
        {"daysOfWeek": ["sat", "sun"], "allDay": True},
    ],
    "eligibility": {
        "code": {"coding": [{"system": NEED, "code": "frailty"}]},
        "comment": "Adults in the example district",
    },
    "extension": SERVICE_EXTENSIONS,
}

LOCATION: dict[str, Any] = {
    "resourceType": "Location",
    "id": LOC_ID,
    "status": "active",
    "name": "Example Site",
    "address": {
        "line": ["1 Example Road"],
        "city": "Example Town",
        "district": "EX1",
        "country": "GB",
    },
    "hoursOfOperation": [
        {
            "daysOfWeek": ["mon", "tue"],
            "allDay": False,
            "openingTime": "09:00:00",
            "closingTime": "17:00:00",
        }
    ],
    "position": {"latitude": 50.61, "longitude": -2.45},
    "telecom": [{"system": "phone", "value": "07700 900001"}],
}

ORGANIZATION_WITH_CONTACT: dict[str, Any] = {
    "resourceType": "Organization",
    "id": ORG_ID,
    "active": True,
    "name": "Example Trust",
    "contact": [
        {
            "purpose": {"coding": [{"system": CONTACT_PURPOSE, "code": "spoa"}]},
            "telecom": [{"system": "phone", "value": "07700 900002"}],
        }
    ],
}


def _node(fragment: GraphFragment, key: str) -> NodeSpec:
    matches = [node for node in fragment.nodes if node.key == key]
    assert len(matches) == 1, f"expected one node {key}, found {len(matches)}"
    return matches[0]


def _rels(fragment: GraphFragment, rel_type: str, start: str) -> list[RelSpec]:
    return [rel for rel in fragment.rels if rel.type == rel_type and rel.start == start]


# The DEC-001 and DEC-051 item 13 graph-safety check, copied unchanged from
# test_mapper_coded_values.py.
# A UCUM annotation such as {referral} or [in_i]: the only bracketed string that may be kept,
# and only in a *_code property (DEC-051 item 13). Strict: no braces or brackets inside.
_UCUM_ANNOTATION = re.compile(r"^(\{[A-Za-z][A-Za-z0-9_]*\}|\[[A-Za-z][A-Za-z0-9_]*\])$")


def _parses_as_json_container(text: str) -> bool:
    """A string that parses as a JSON object or array is never allowed (DEC-001)."""
    try:
        return isinstance(json.loads(text), dict | list)
    except ValueError:
        return False


def _is_ucum_annotation_in_a_code_property(name: str, value: str) -> bool:
    return name.endswith("_code") and _UCUM_ANNOTATION.match(value) is not None


def _assert_graph_safe(fragment: GraphFragment) -> None:
    """DEC-001: no map, no list of maps, no JSON-looking string, no json property."""
    for owner in [*fragment.nodes, *fragment.rels]:
        assert "json" not in owner.properties
        for name, value in owner.properties.items():
            assert not isinstance(value, dict), f"{name} holds a map"
            if isinstance(value, list):
                assert not any(isinstance(item, dict) for item in value), (
                    f"{name} is a list of maps"
                )
            if isinstance(value, str):
                assert not _parses_as_json_container(value), f"{name} looks like JSON"
                if not _is_ucum_annotation_in_a_code_property(name, value):
                    assert not value.lstrip().startswith(("{", "[")), (
                        f"{name} starts with a bracket"
                    )


# R4: repeating backbone elements become child nodes


def test_two_available_times_become_two_child_nodes_with_order() -> None:
    fragment = to_graph(UCR_WEST)

    first = _node(fragment, f"{SVC_KEY}#availableTime[0]")
    second = _node(fragment, f"{SVC_KEY}#availableTime[1]")
    assert first.labels == ("HealthcareService_AvailableTime",)
    assert first.properties == {
        "daysOfWeek": ["mon", "tue", "wed", "thu", "fri"],
        "availableStartTime": "08:00:00",
        "availableEndTime": "20:00:00",
    }
    assert second.properties == {"daysOfWeek": ["sat", "sun"], "allDay": True}

    rels = _rels(fragment, "HAS_AVAILABLE_TIME", SVC_KEY)
    assert [(rel.end, rel.properties["order"]) for rel in rels] == [
        (f"{SVC_KEY}#availableTime[0]", 0),
        (f"{SVC_KEY}#availableTime[1]", 1),
    ]
    assert {rel.properties["fhirPath"] for rel in rels} == {"HealthcareService.availableTime"}


def test_a_single_backbone_element_has_no_order_and_rebuilds_as_one_object() -> None:
    resource = {**UCR_WEST, "availableTime": UCR_WEST["availableTime"][0]}

    fragment = to_graph(resource)

    rel = _rels(fragment, "HAS_AVAILABLE_TIME", SVC_KEY)[0]
    assert rel.end == f"{SVC_KEY}#availableTime[0]"
    assert "order" not in rel.properties
    assert from_graph(fragment) == resource


def test_a_list_of_one_backbone_element_keeps_its_list_shape() -> None:
    resource = {**UCR_WEST, "availableTime": [UCR_WEST["availableTime"][0]]}

    fragment = to_graph(resource)

    assert _rels(fragment, "HAS_AVAILABLE_TIME", SVC_KEY)[0].properties["order"] == 0
    assert from_graph(fragment) == resource


def test_eligibility_is_a_child_node_with_comment_and_a_code_relationship() -> None:
    fragment = to_graph(UCR_WEST)

    child_key = f"{SVC_KEY}#eligibility[0]"
    child = _node(fragment, child_key)
    assert child.labels == ("HealthcareService_Eligibility",)
    assert child.properties == {"comment": "Adults in the example district"}

    link = _rels(fragment, "HAS_ELIGIBILITY", SVC_KEY)[0]
    assert link.end == child_key
    assert "order" not in link.properties
    assert link.properties["fhirPath"] == "HealthcareService.eligibility"

    code = _rels(fragment, "CODE", child_key)[0]
    assert code.end == f"Concept|{NEED}|frailty"
    assert code.properties["fhirPath"] == "HealthcareService.eligibility.code"


def test_a_child_concept_shares_the_concept_node_of_the_root() -> None:
    category = UCR_WEST["category"][0]
    resource = {
        **UCR_WEST,
        "eligibility": {"code": {"coding": [category["coding"][0]]}},
    }

    fragment = to_graph(resource)

    concept_key = f"Concept|{SERVICE_CATEGORY}|urgent-community-response"
    assert [node.key for node in fragment.nodes].count(concept_key) == 1
    assert from_graph(fragment) == resource


def test_a_child_concept_with_different_display_for_the_same_code_is_refused() -> None:
    resource = {
        **UCR_WEST,
        "eligibility": {
            "code": {"coding": [{"system": SERVICE_CATEGORY, "code": "urgent-community-response"}]}
        },
    }

    with pytest.raises(ValidationFailed) as raised:
        to_graph(resource)

    assert raised.value.field == "code"


def test_child_nodes_are_labelled_by_type_and_element() -> None:
    fragment = to_graph(LOCATION)

    labels = {
        node.key.split("#", 1)[1].split("[", 1)[0]: node.labels
        for node in fragment.nodes
        if "#" in node.key
    }
    assert labels == {
        "address": ("Address",),
        "hoursOfOperation": ("Location_HoursOfOperation",),
        "telecom": ("ContactPoint",),
    }


# R4 round trips


def test_ucr_west_round_trips_exactly() -> None:
    assert from_graph(to_graph(UCR_WEST)) == UCR_WEST


def test_ucr_west_fragment_holds_no_map_no_list_of_maps_and_no_json_string() -> None:
    _assert_graph_safe(to_graph(UCR_WEST))


def test_the_same_backbone_in_another_key_order_gives_the_same_fragment() -> None:
    reordered_slot = dict(reversed(list(UCR_WEST["availableTime"][0].items())))
    reordered = {**UCR_WEST, "availableTime": [reordered_slot, UCR_WEST["availableTime"][1]]}

    assert to_graph(reordered) == to_graph(UCR_WEST)


def test_location_round_trips_with_address_hours_position_and_telecom() -> None:
    assert from_graph(to_graph(LOCATION)) == LOCATION


def test_location_position_is_stored_as_latitude_and_longitude_properties() -> None:
    root = _node(to_graph(LOCATION), LOC_KEY)

    assert root.properties["positionLatitude"] == 50.61
    assert root.properties["positionLongitude"] == -2.45
    assert "position" not in root.properties


def test_location_address_is_a_child_linked_by_has_address() -> None:
    fragment = to_graph(LOCATION)

    link = _rels(fragment, "HAS_ADDRESS", LOC_KEY)[0]
    address = _node(fragment, link.end)
    assert address.labels == ("Address",)
    assert address.properties == LOCATION["address"]
    assert link.properties["fhirPath"] == "Location.address"


def test_location_hours_are_a_child_linked_by_has_hours() -> None:
    fragment = to_graph(LOCATION)

    link = _rels(fragment, "HAS_HOURS", LOC_KEY)[0]
    assert link.end == f"{LOC_KEY}#hoursOfOperation[0]"
    assert link.properties["order"] == 0
    assert _node(fragment, link.end).properties["openingTime"] == "09:00:00"


def test_organization_contact_is_a_child_with_purpose_and_telecom() -> None:
    fragment = to_graph(ORGANIZATION_WITH_CONTACT)

    contact_key = f"{ORG_KEY}#contact[0]"
    assert _node(fragment, contact_key).labels == ("Organization_Contact",)
    assert _rels(fragment, "HAS_CONTACT", ORG_KEY)[0].end == contact_key

    purpose = _rels(fragment, "PURPOSE", contact_key)[0]
    assert purpose.end == f"Concept|{CONTACT_PURPOSE}|spoa"
    assert purpose.properties["fhirPath"] == "Organization.contact.purpose"

    phone_key = f"{contact_key}#telecom[0]"
    assert _node(fragment, phone_key).labels == ("ContactPoint",)
    phone_link = _rels(fragment, "HAS_TELECOM", contact_key)[0]
    assert phone_link.end == phone_key
    assert phone_link.properties["fhirPath"] == "Organization.contact.telecom"


def test_organization_contact_round_trips_exactly() -> None:
    assert from_graph(to_graph(ORGANIZATION_WITH_CONTACT)) == ORGANIZATION_WITH_CONTACT


# Refusals: nothing is dropped


@pytest.mark.parametrize(
    "value",
    [
        {"daysOfWeek": ["mon"], "name": {"text": "x"}},
        {"daysOfWeek": ["mon"], "extension": [{"url": "https://example.test/x"}]},
    ],
)
def test_a_backbone_child_with_an_unmapped_key_is_refused_with_its_path(
    value: dict[str, Any],
) -> None:
    resource = {**UCR_WEST, "availableTime": [value]}

    with pytest.raises(UnsupportedElement) as raised:
        to_graph(resource)

    assert raised.value.path.startswith("HealthcareService.availableTime.")


@pytest.mark.parametrize("value", [{}, [{}]])
def test_an_empty_backbone_element_is_refused_not_kept(value: Any) -> None:
    resource = {**UCR_WEST, "availableTime": value}

    with pytest.raises(DomainError):
        to_graph(resource)


def test_a_list_mixing_backbone_objects_and_primitives_is_refused() -> None:
    resource = {**UCR_WEST, "availableTime": [UCR_WEST["availableTime"][0], "08:00"]}

    with pytest.raises(UnsupportedElement):
        to_graph(resource)


@pytest.mark.parametrize(
    ("element", "value"),
    [
        ("qualification", [{"code": {"text": "x"}}]),
        ("alias", [{"text": "x"}]),
    ],
)
def test_a_dict_element_the_mapper_does_not_know_is_refused(element: str, value: Any) -> None:
    resource = {"resourceType": "Organization", "id": ORG_ID, element: value}

    with pytest.raises(UnsupportedElement):
        to_graph(resource)


def test_an_organization_contact_with_a_name_is_refused_because_names_are_not_mapped() -> None:
    resource = {
        "resourceType": "Organization",
        "id": ORG_ID,
        "contact": [{"name": {"text": "Example Contact"}}],
    }

    with pytest.raises(UnsupportedElement) as raised:
        to_graph(resource)

    assert raised.value.path == "Organization.contact.name"


@pytest.mark.parametrize(
    "value",
    [
        {"latitude": 50.61, "longitude": -2.45, "altitude": 10},
        {},
        {"latitude": "50.61", "longitude": -2.45},
        {"latitude": True, "longitude": -2.45},
    ],
)
def test_a_position_that_is_not_latitude_and_longitude_numbers_is_refused(value: Any) -> None:
    resource = {**LOCATION, "position": value}

    with pytest.raises(DomainError):
        to_graph(resource)


@pytest.mark.parametrize("target", ["Location/a#b", "Location/a#contact[0]"])
def test_a_reference_target_with_the_child_separator_is_refused(target: str) -> None:
    resource = {"resourceType": "Location", "id": LOC_ID, "partOf": {"reference": target}}

    with pytest.raises(InvalidReference):
        to_graph(resource)


def test_rebuild_refuses_a_child_relationship_whose_node_is_missing() -> None:
    fragment = to_graph(UCR_WEST)
    without_child = GraphFragment(
        root_key=fragment.root_key,
        nodes=tuple(node for node in fragment.nodes if node.key != f"{SVC_KEY}#eligibility[0]"),
        rels=fragment.rels,
    )

    with pytest.raises(NotFound):
        from_graph(without_child)


# Property: generated backbone elements round-trip exactly

_DAYS = st.lists(
    st.sampled_from(["mon", "tue", "wed", "thu", "fri", "sat", "sun"]),
    min_size=1,
    max_size=7,
    unique=True,
)
_CLOCK = st.from_regex(r"[0-2][0-9]:[0-5][0-9]:00", fullmatch=True)
_SLOT = st.fixed_dictionaries(
    {"daysOfWeek": _DAYS},
    optional={"allDay": st.booleans(), "availableStartTime": _CLOCK, "availableEndTime": _CLOCK},
)


@settings(max_examples=200, deadline=None)
@given(slots=st.lists(_SLOT, min_size=1, max_size=3))
def test_generated_available_times_round_trip_exactly(slots: list[dict[str, Any]]) -> None:
    resource = {"resourceType": "HealthcareService", "id": SVC_ID, "availableTime": slots}

    assert from_graph(to_graph(resource)) == resource


# Property: any mix of the backbone and extension elements is exact or refused (DEC-049)

_CONCEPT_SAMPLE = st.fixed_dictionaries(
    {
        "coding": st.lists(
            st.fixed_dictionaries(
                {
                    "system": st.sampled_from([SERVICE_CATEGORY, NEED]),
                    "code": st.sampled_from(["a", "b"]),
                },
                optional={"display": st.sampled_from(["x", "y"])},
            ),
            min_size=1,
            max_size=2,
        )
    },
    optional={"text": st.sampled_from(["t", "u"])},
)
_REFERENCE_SAMPLE = st.fixed_dictionaries(
    {"reference": st.sampled_from(["Location/l1", "Organization/o1", "Location/l#x"])}
)
_TEXT_SAMPLE = st.text(alphabet="abc |#_{}[]", max_size=5)
_PRIMITIVE_SAMPLE = st.one_of(_TEXT_SAMPLE, st.booleans(), st.integers(-3, 3))
_BACKBONE_ITEM = st.dictionaries(
    st.sampled_from(
        ["daysOfWeek", "allDay", "comment", "code", "telecom", "line", "rank", "purpose", "name"]
    ),
    st.one_of(
        _PRIMITIVE_SAMPLE,
        st.lists(_TEXT_SAMPLE, min_size=1, max_size=2),
        _CONCEPT_SAMPLE,
        _REFERENCE_SAMPLE,
        st.lists(_CONCEPT_SAMPLE, min_size=1, max_size=2),
    ),
    max_size=3,
)
_EXTENSION_ENTRY = st.one_of(
    st.fixed_dictionaries(
        {
            "url": st.sampled_from([defn.url for defn in EXTENSIONS.values()]),
            "value": _PRIMITIVE_SAMPLE,
        }
    ),
    st.fixed_dictionaries(
        {"url": st.just("https://example.test/unknown"), "value": _PRIMITIVE_SAMPLE}
    ),
).map(
    lambda entry: {
        "url": entry["url"],
        f"value{type(entry['value']).__name__.capitalize()}": entry["value"],
    }
)
_BACKBONE_VALUE = st.one_of(
    _BACKBONE_ITEM,
    st.lists(_BACKBONE_ITEM, max_size=2),
    st.none(),
    _PRIMITIVE_SAMPLE,
)
_ELEMENT_VALUES: dict[str, st.SearchStrategy[Any]] = {
    "availableTime": _BACKBONE_VALUE,
    "eligibility": _BACKBONE_VALUE,
    "telecom": _BACKBONE_VALUE,
    "contact": _BACKBONE_VALUE,
    "address": _BACKBONE_VALUE,
    "hoursOfOperation": _BACKBONE_VALUE,
    "extension": st.one_of(st.lists(_EXTENSION_ENTRY, max_size=3), _EXTENSION_ENTRY, st.none()),
    "position": st.one_of(
        st.dictionaries(
            st.sampled_from(["latitude", "longitude", "altitude"]),
            st.one_of(st.integers(-90, 90), st.floats(-90, 90, allow_nan=False)),
            max_size=3,
        ),
        st.none(),
    ),
    "name": _PRIMITIVE_SAMPLE,
    "category": st.lists(_CONCEPT_SAMPLE, min_size=1, max_size=2),
}


@settings(max_examples=400, deadline=None)
@given(
    resource_type=st.sampled_from(["HealthcareService", "Location", "Organization"]),
    body=st.fixed_dictionaries({}, optional=_ELEMENT_VALUES),
)
def test_backbone_and_extension_input_is_exact_or_refused(
    resource_type: str, body: dict[str, Any]
) -> None:
    resource = {**body, "resourceType": resource_type, "id": "r1"}
    try:
        fragment = to_graph(resource)
    except DomainError:
        return
    assert from_graph(fragment) == resource


def test_a_position_with_only_latitude_round_trips() -> None:
    resource = {**LOCATION, "position": {"latitude": 50.61}}

    fragment = to_graph(resource)

    assert "positionLongitude" not in _node(fragment, LOC_KEY).properties
    assert from_graph(fragment) == resource
