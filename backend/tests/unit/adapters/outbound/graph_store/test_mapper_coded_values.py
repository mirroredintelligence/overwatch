"""Pure tests for the FHIR-to-graph mapper (G03): concepts, identifiers, periods and quantities.

Rules R5 (CodeableConcept and Coding become shared Concept nodes), R6 (Identifier nodes),
R7 (Period, Quantity and Range flattened onto the owner) and R11 (filter-code copies).

DEC-049: every case either round-trips exactly or is refused with a DomainError. Nothing is
silently dropped, overwritten or moved. All values are synthetic.
"""

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.adapters.outbound.graph_store.mapper import (
    FILTER_CODE_PROPERTIES,
    ODS_ORG_SYSTEM,
    ODS_SITE_SYSTEM,
    GraphFragment,
    InvalidReference,
    NodeSpec,
    RelSpec,
    UnsupportedElement,
    from_graph,
    to_graph,
)
from diucs.domain.errors import DomainError, NotFound, ValidationFailed

OBS_ID = "9e4c3f5b-6d7a-4182-8d2e-3f4a5b6c7d8e"
ORG_ID = "6b1f0c2e-3a4d-4e5f-8a9b-0c1d2e3f4a5b"
SVC_ID = "8d3b2e4a-5c6f-4071-8c1d-2e3f4a5b6c7d"

CAPACITY_MEASURE = "https://diucs.example/CodeSystem/capacity-measure"
REPORT_SOURCE = "https://diucs.example/CodeSystem/report-source"
STATUS = "https://diucs.example/CodeSystem/status"
SERVICE_CATEGORY = "https://diucs.example/CodeSystem/service-category"
ORGANIZATION_TYPE = "https://diucs.example/CodeSystem/organization-type"
UCUM = "http://unitsofmeasure.org"

CAPACITY_REPORT: dict[str, Any] = {
    "resourceType": "Observation",
    "id": OBS_ID,
    "status": "final",
    "code": {"coding": [{"system": CAPACITY_MEASURE, "code": "referrals-acceptable"}]},
    "focus": [{"reference": f"HealthcareService/{SVC_ID}"}],
    "effectiveDateTime": "2026-10-25T09:30:00+01:00",
    "issued": "2026-10-25T09:30:02+01:00",
    "valueQuantity": {"value": 3, "unit": "referral", "system": UCUM, "code": "{referral}"},
    "method": {"coding": [{"system": REPORT_SOURCE, "code": "text"}]},
    "interpretation": [{"coding": [{"system": STATUS, "code": "accepting"}]}],
}

ORGANIZATION_WITH_TYPE: dict[str, Any] = {
    "resourceType": "Organization",
    "id": ORG_ID,
    "active": True,
    "name": "Dorset HealthCare",
    "type": [
        {
            "coding": [{"system": ORGANIZATION_TYPE, "code": "nhs-trust"}],
            "text": "NHS trust",
        }
    ],
    "identifier": [{"system": ODS_ORG_SYSTEM, "value": "X1A"}],
}

SERVICE_TWO_CATEGORIES: dict[str, Any] = {
    "resourceType": "HealthcareService",
    "id": SVC_ID,
    "category": [
        {
            "coding": [
                {
                    "system": SERVICE_CATEGORY,
                    "code": "urgent-community-response",
                    "display": "Urgent community response",
                },
                {"system": SERVICE_CATEGORY, "code": "virtual-ward"},
            ],
            "text": "Services",
        }
    ],
}

GRAPH_SAFE_SAMPLES: list[dict[str, Any]] = [
    CAPACITY_REPORT,
    ORGANIZATION_WITH_TYPE,
    SERVICE_TWO_CATEGORIES,
]


def _nodes(fragment: GraphFragment, key: str) -> list[NodeSpec]:
    return [node for node in fragment.nodes if node.key == key]


def _one_node(fragment: GraphFragment, key: str) -> NodeSpec:
    matches = _nodes(fragment, key)
    assert len(matches) == 1, f"expected one node {key}, found {len(matches)}"
    return matches[0]


def _rels(fragment: GraphFragment, rel_type: str) -> list[RelSpec]:
    return [rel for rel in fragment.rels if rel.type == rel_type]


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


# R5: a coded value is a relationship to a shared Concept node


def test_coding_becomes_code_relationship_to_a_concept_with_an_in_system_link() -> None:
    fragment = to_graph(CAPACITY_REPORT)

    code_rels = _rels(fragment, "CODE")
    assert len(code_rels) == 1
    concept_key = "Concept|" + CAPACITY_MEASURE + "|referrals-acceptable"
    assert code_rels[0].start == f"Observation/{OBS_ID}"
    assert code_rels[0].end == concept_key
    assert code_rels[0].properties == {"fhirPath": "Observation.code", "order": 0}

    concept = _one_node(fragment, concept_key)
    assert concept.labels == ("Concept",)
    assert concept.properties == {"system": CAPACITY_MEASURE, "code": "referrals-acceptable"}

    in_system = _rels(fragment, "IN_SYSTEM")
    assert sorted((rel.start, rel.end) for rel in in_system) == sorted(
        [
            (concept_key, f"CodeSystem|{CAPACITY_MEASURE}"),
            (f"Concept|{REPORT_SOURCE}|text", f"CodeSystem|{REPORT_SOURCE}"),
            (f"Concept|{STATUS}|accepting", f"CodeSystem|{STATUS}"),
        ]
    )
    code_system = _one_node(fragment, f"CodeSystem|{CAPACITY_MEASURE}")
    assert code_system.labels == ("CodeSystem",)
    assert code_system.properties == {"url": CAPACITY_MEASURE}


def test_filter_code_is_copied_to_measure_code_on_the_observation() -> None:
    fragment = to_graph(CAPACITY_REPORT)

    root = _one_node(fragment, f"Observation/{OBS_ID}")
    assert root.properties["measureCode"] == "referrals-acceptable"
    assert FILTER_CODE_PROPERTIES == {("Observation", "code"): "measureCode"}


def test_codings_keep_display_text_user_selected_and_version_where_given() -> None:
    resource = {
        "resourceType": "HealthcareService",
        "id": SVC_ID,
        "category": [
            {
                "coding": [
                    {
                        "system": SERVICE_CATEGORY,
                        "code": "virtual-ward",
                        "display": "Virtual ward",
                        "version": "1",
                        "userSelected": True,
                    }
                ],
                "text": "Virtual",
            }
        ],
    }

    fragment = to_graph(resource)

    concept = _one_node(fragment, f"Concept|{SERVICE_CATEGORY}|virtual-ward")
    assert concept.properties == {
        "system": SERVICE_CATEGORY,
        "code": "virtual-ward",
        "display": "Virtual ward",
        "version": "1",
    }
    (rel,) = _rels(fragment, "CATEGORY")
    assert rel.properties["text"] == "Virtual"
    assert rel.properties["userSelected"] is True
    assert from_graph(fragment) == resource


# R5: two codings in one CodeableConcept give two relationships with order, text on both


def test_two_codings_in_one_concept_give_two_category_relationships_with_order() -> None:
    fragment = to_graph(SERVICE_TWO_CATEGORIES)

    category = _rels(fragment, "CATEGORY")
    assert [rel.properties["order"] for rel in category] == [0, 1]
    assert [rel.end for rel in category] == [
        f"Concept|{SERVICE_CATEGORY}|urgent-community-response",
        f"Concept|{SERVICE_CATEGORY}|virtual-ward",
    ]
    assert all(rel.properties["text"] == "Services" for rel in category)
    assert all(rel.properties["fhirPath"] == "HealthcareService.category" for rel in category)
    assert all(rel.properties["conceptOrder"] == 0 for rel in category)


def test_a_single_concept_that_is_not_in_a_list_has_no_concept_order() -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "method": {"coding": [{"system": REPORT_SOURCE, "code": "text"}]},
    }

    (rel,) = _rels(to_graph(resource), "METHOD")

    assert rel.properties == {"fhirPath": "Observation.method", "order": 0}


def test_a_list_of_one_concept_is_kept_distinct_from_a_single_concept() -> None:
    single = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "method": {"coding": [{"system": REPORT_SOURCE, "code": "text"}]},
    }
    listed = {**single, "method": [single["method"]]}

    assert to_graph(listed) != to_graph(single)
    assert from_graph(to_graph(listed)) == listed
    assert from_graph(to_graph(single)) == single


def test_several_concepts_in_a_list_keep_their_own_codings_and_text() -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "interpretation": [
            {
                "coding": [
                    {"system": STATUS, "code": "accepting"},
                    {"system": STATUS, "code": "limited"},
                ],
                "text": "first",
            },
            {"coding": [{"system": STATUS, "code": "not-accepting"}]},
        ],
    }

    assert from_graph(to_graph(resource)) == resource


def test_a_shared_concept_is_one_node_even_when_two_elements_use_it() -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "code": {"coding": [{"system": STATUS, "code": "accepting"}]},
        "interpretation": [{"coding": [{"system": STATUS, "code": "accepting"}]}],
    }

    fragment = to_graph(resource)

    assert len(_nodes(fragment, f"Concept|{STATUS}|accepting")) == 1
    assert len(_rels(fragment, "CODE")) == 1
    assert len(_rels(fragment, "INTERPRETATION")) == 1
    assert from_graph(fragment) == resource


# R5: the same concept used by two resources has the same key


def test_two_resources_using_the_same_concept_produce_the_same_concept_key() -> None:
    observation_key = f"Concept|{CAPACITY_MEASURE}|referrals-acceptable"
    other = {
        "resourceType": "Observation",
        "id": "0a1b2c3d-4e5f-4061-8172-8394a5b6c7d8",
        "status": "final",
        "code": {"coding": [{"system": CAPACITY_MEASURE, "code": "referrals-acceptable"}]},
    }

    first = _one_node(to_graph(CAPACITY_REPORT), observation_key)
    second = _one_node(to_graph(other), observation_key)

    assert first == second


def test_the_same_code_with_two_different_displays_in_one_resource_is_refused() -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "code": {"coding": [{"system": STATUS, "code": "accepting", "display": "Accepting"}]},
        "interpretation": [{"coding": [{"system": STATUS, "code": "accepting"}]}],
    }

    with pytest.raises(ValidationFailed) as raised:
        to_graph(resource)

    assert raised.value.field == "code"


# R5: codings that cannot be represented are refused


@pytest.mark.parametrize(
    ("coding", "field"),
    [
        ({"system": STATUS}, "code"),
        ({"code": "accepting"}, "system"),
        ({"system": STATUS, "code": ""}, "code"),
        ({"system": "", "code": "accepting"}, "system"),
        ({"system": STATUS, "code": "a|b"}, "code"),
        ({"system": "a|b", "code": "accepting"}, "system"),
    ],
)
def test_a_coding_without_a_system_or_code_or_with_the_key_separator_is_refused(
    coding: dict[str, Any], field: str
) -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "code": {"coding": [coding]},
    }

    with pytest.raises(ValidationFailed) as raised:
        to_graph(resource)

    assert raised.value.field == field


def test_a_coding_with_an_unmapped_element_is_refused_with_its_path() -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "code": {"coding": [{"system": STATUS, "code": "accepting", "extension": []}]},
    }

    with pytest.raises(UnsupportedElement) as raised:
        to_graph(resource)

    assert raised.value.path == "Observation.code"


@pytest.mark.parametrize(
    "concept",
    [
        {"text": "no codings"},
        {"coding": []},
        {"coding": [{"system": STATUS, "code": "accepting"}], "extension": []},
        {"coding": [{"system": STATUS, "code": "accepting"}], "text": 7},
    ],
)
def test_a_codeable_concept_that_cannot_be_kept_exactly_is_refused(concept: dict[str, Any]) -> None:
    resource = {"resourceType": "Observation", "id": OBS_ID, "status": "final", "code": concept}

    with pytest.raises(UnsupportedElement) as raised:
        to_graph(resource)

    assert raised.value.path == "Observation.code"


def test_a_concept_relationship_to_a_missing_concept_node_is_refused_on_rebuild() -> None:
    fragment = to_graph(CAPACITY_REPORT)
    without_concepts = GraphFragment(
        root_key=fragment.root_key,
        nodes=tuple(node for node in fragment.nodes if "Concept" not in node.labels),
        rels=fragment.rels,
    )

    with pytest.raises(NotFound):
        from_graph(without_concepts)


# R6: identifiers become shared Identifier nodes


def test_an_ods_organisation_identifier_becomes_identifier_node_and_ods_code() -> None:
    fragment = to_graph(ORGANIZATION_WITH_TYPE)

    identifier_key = f"Identifier|{ODS_ORG_SYSTEM}|X1A"
    identifier = _one_node(fragment, identifier_key)
    assert identifier.labels == ("Identifier",)
    assert identifier.properties == {"system": ODS_ORG_SYSTEM, "value": "X1A"}

    (rel,) = _rels(fragment, "IDENTIFIED_BY")
    assert rel.start == f"Organization/{ORG_ID}"
    assert rel.end == identifier_key
    assert rel.properties == {"fhirPath": "Organization.identifier", "order": 0}

    root = _one_node(fragment, f"Organization/{ORG_ID}")
    assert root.properties["odsCode"] == "X1A"


def test_an_identifier_use_lives_on_the_relationship_so_one_identifier_can_have_two_uses() -> None:
    resource = {
        "resourceType": "Organization",
        "id": ORG_ID,
        "identifier": [
            {"system": ODS_ORG_SYSTEM, "value": "X1A", "use": "official"},
            {"system": ODS_ORG_SYSTEM, "value": "X1A", "use": "secondary"},
        ],
    }

    fragment = to_graph(resource)

    assert len(_nodes(fragment, f"Identifier|{ODS_ORG_SYSTEM}|X1A")) == 1
    uses = [rel.properties["use"] for rel in _rels(fragment, "IDENTIFIED_BY")]
    assert uses == ["official", "secondary"]
    assert from_graph(fragment) == resource


def test_an_ods_site_identifier_is_an_identifier_node_but_does_not_set_ods_code() -> None:
    resource = {
        "resourceType": "Location",
        "id": "7c2a1d3f-4b5e-4f60-9b0c-1d2e3f4a5b6c",
        "identifier": [{"system": ODS_SITE_SYSTEM, "value": "S9Z"}],
    }

    fragment = to_graph(resource)

    assert f"Identifier|{ODS_SITE_SYSTEM}|S9Z" in {node.key for node in fragment.nodes}
    assert "odsCode" not in fragment.nodes[0].properties
    assert from_graph(fragment) == resource


def test_two_different_ods_organisation_codes_on_one_resource_are_refused() -> None:
    resource = {
        "resourceType": "Organization",
        "id": ORG_ID,
        "identifier": [
            {"system": ODS_ORG_SYSTEM, "value": "X1A"},
            {"system": ODS_ORG_SYSTEM, "value": "X2B"},
        ],
    }

    with pytest.raises(ValidationFailed) as raised:
        to_graph(resource)

    assert raised.value.field == "identifier"


@pytest.mark.parametrize(
    ("identifier", "field"),
    [
        ({"value": "X1A"}, "system"),
        ({"system": ODS_ORG_SYSTEM}, "value"),
        ({"system": ODS_ORG_SYSTEM, "value": "a|b"}, "value"),
    ],
)
def test_an_identifier_without_a_system_or_value_is_refused(
    identifier: dict[str, Any], field: str
) -> None:
    with pytest.raises(ValidationFailed) as raised:
        to_graph({"resourceType": "Organization", "id": ORG_ID, "identifier": [identifier]})

    assert raised.value.field == field


@pytest.mark.parametrize(
    "extra",
    [{"type": {"text": "x"}}, {"period": {"start": "2026-10-25T09:00:00+01:00"}}, {"assigner": {}}],
)
def test_an_identifier_with_an_unmapped_element_is_refused(extra: dict[str, Any]) -> None:
    identifier = {"system": ODS_ORG_SYSTEM, "value": "X1A", **extra}

    with pytest.raises(UnsupportedElement) as raised:
        to_graph({"resourceType": "Organization", "id": ORG_ID, "identifier": [identifier]})

    assert raised.value.path == "Organization.identifier"


# R7: Period, Quantity and Range are flattened onto the owner


def test_a_quantity_flattens_to_four_value_quantity_properties() -> None:
    root = _one_node(to_graph(CAPACITY_REPORT), f"Observation/{OBS_ID}")

    assert root.properties["valueQuantity_value"] == 3
    assert root.properties["valueQuantity_unit"] == "referral"
    assert root.properties["valueQuantity_system"] == UCUM
    assert root.properties["valueQuantity_code"] == "{referral}"
    assert "valueQuantity" not in root.properties


@pytest.mark.parametrize(
    ("element", "start", "end"),
    [
        ("effectivePeriod", "effectivePeriodStart", "effectivePeriodEnd"),
        ("period", "periodStart", "periodEnd"),
    ],
)
def test_a_period_flattens_to_start_and_end_with_the_element_as_prefix(
    element: str, start: str, end: str
) -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        element: {"start": "2026-10-25T08:00:00+01:00", "end": "2026-10-25T20:00:00+01:00"},
    }

    root = _one_node(to_graph(resource), f"Observation/{OBS_ID}")

    assert root.properties[start] == "2026-10-25T08:00:00+01:00"
    assert root.properties[end] == "2026-10-25T20:00:00+01:00"
    assert element not in root.properties
    assert from_graph(to_graph(resource)) == resource


def test_a_period_with_only_an_end_keeps_only_that_end() -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "effectivePeriod": {"end": "2026-10-25T20:00:00+01:00"},
    }

    root = _one_node(to_graph(resource), f"Observation/{OBS_ID}")

    assert "effectivePeriodStart" not in root.properties
    assert from_graph(to_graph(resource)) == resource


def test_a_range_flattens_low_and_high_quantities_onto_the_owner() -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "valueRange": {
            "low": {"value": 1, "unit": "referral"},
            "high": {"value": 4, "unit": "referral"},
        },
    }

    root = _one_node(to_graph(resource), f"Observation/{OBS_ID}")

    assert root.properties == {
        "id": OBS_ID,
        "iri": root.properties["iri"],
        "status": "final",
        "valueRange_low_value": 1,
        "valueRange_low_unit": "referral",
        "valueRange_high_value": 4,
        "valueRange_high_unit": "referral",
    }
    assert from_graph(to_graph(resource)) == resource


def test_flattened_quantities_round_trip_when_only_some_fields_are_given() -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "valueQuantity": {"value": 0},
    }

    assert from_graph(to_graph(resource)) == resource


def test_a_capacity_report_round_trips_exactly() -> None:
    assert from_graph(to_graph(CAPACITY_REPORT)) == CAPACITY_REPORT


def test_an_organization_with_type_and_identifier_round_trips_exactly() -> None:
    assert from_graph(to_graph(ORGANIZATION_WITH_TYPE)) == ORGANIZATION_WITH_TYPE


def test_copied_properties_never_come_back_in_the_rebuilt_resource() -> None:
    rebuilt = from_graph(to_graph(CAPACITY_REPORT))

    assert "measureCode" not in rebuilt
    assert "odsCode" not in from_graph(to_graph(ORGANIZATION_WITH_TYPE))


@pytest.mark.parametrize(
    "quantity",
    [{}, {"comparator": "<", "value": 3}, {"value": {"x": 1}}, {"value": None}],
)
def test_a_quantity_that_cannot_be_flattened_exactly_is_refused(quantity: dict[str, Any]) -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "valueQuantity": quantity,
    }

    with pytest.raises(UnsupportedElement) as raised:
        to_graph(resource)

    assert raised.value.path == "Observation.valueQuantity"


@pytest.mark.parametrize(
    "period", [{}, {"start": 7}, {"start": "2026-10-25T08:00:00+01:00", "x": 1}]
)
def test_a_period_that_cannot_be_flattened_exactly_is_refused(period: dict[str, Any]) -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "effectivePeriod": period,
    }

    with pytest.raises(UnsupportedElement) as raised:
        to_graph(resource)

    assert raised.value.path == "Observation.effectivePeriod"


@pytest.mark.parametrize(
    "element", ["odsCode", "measureCode", "periodStart", "fooEnd", "value_x", "valueQuantity_value"]
)
def test_a_top_level_name_that_collides_with_a_copied_or_flattened_property_is_refused(
    element: str,
) -> None:
    resource = {"resourceType": "Observation", "id": OBS_ID, "status": "final", element: "x"}

    with pytest.raises(ValidationFailed) as raised:
        to_graph(resource)

    assert raised.value.field == element


def test_a_reference_target_whose_type_contains_the_key_separator_is_refused() -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "focus": [{"reference": "Concept|x/y"}],
    }

    with pytest.raises(InvalidReference):
        to_graph(resource)


# Graph safety (DEC-001) for every new sample


@pytest.mark.parametrize("resource", GRAPH_SAFE_SAMPLES, ids=lambda r: r["resourceType"])
def test_new_samples_hold_no_map_no_list_of_maps_and_no_json_string(
    resource: dict[str, Any],
) -> None:
    _assert_graph_safe(to_graph(resource))


def test_the_ods_uris_appear_only_as_the_two_constants() -> None:
    source = (
        Path(__file__).resolve().parents[5] / "src/diucs/adapters/outbound/graph_store/mapper.py"
    ).read_text(encoding="utf-8")
    literals = [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "fhir.nhs.uk" in node.value
    ]

    assert sorted(literals) == sorted([ODS_ORG_SYSTEM, ODS_SITE_SYSTEM])


# Property: generated coded values, identifiers, periods and quantities are exact or refused


_TEXT = st.text(alphabet=st.characters(blacklist_characters="|", min_codepoint=32), max_size=10)
_SYSTEM = st.sampled_from([CAPACITY_MEASURE, REPORT_SOURCE, STATUS, UCUM])
_CODING = st.fixed_dictionaries(
    {"system": _SYSTEM, "code": _TEXT.filter(lambda text: text != "")},
    optional={"display": _TEXT, "userSelected": st.booleans()},
)
_CONCEPT = st.fixed_dictionaries(
    {"coding": st.lists(_CODING, min_size=1, max_size=3)}, optional={"text": _TEXT}
)
_QUANTITY = st.dictionaries(
    st.sampled_from(["value", "unit", "system", "code"]),
    st.one_of(st.integers(-5, 5), _TEXT),
    min_size=1,
    max_size=4,
)
_PERIOD = st.dictionaries(
    st.sampled_from(["start", "end"]),
    st.sampled_from(["2026-03-29T01:30:00+00:00", "2026-10-25T01:55:00+01:00"]),
    min_size=1,
)


@settings(max_examples=300, deadline=None)
@given(
    concept=_CONCEPT,
    quantity=_QUANTITY,
    period=_PERIOD,
    as_list=st.booleans(),
)
def test_generated_coded_quantity_and_period_values_round_trip_exactly(
    concept: dict[str, Any], quantity: dict[str, Any], period: dict[str, Any], as_list: bool
) -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "method": [concept] if as_list else concept,
        "valueQuantity": quantity,
        "effectivePeriod": period,
    }
    try:
        fragment = to_graph(resource)
    except DomainError:
        return
    assert from_graph(fragment) == resource


# Coverage of the refusal paths and of corrupt fragments (G05 reads these back from Neo4j)


def test_a_single_identifier_round_trips_with_and_without_use() -> None:
    with_use = {
        "resourceType": "Organization",
        "id": ORG_ID,
        "identifier": {"system": ODS_ORG_SYSTEM, "value": "X1A", "use": "official"},
    }
    without_use = {
        "resourceType": "Organization",
        "id": ORG_ID,
        "identifier": {"system": ODS_ORG_SYSTEM, "value": "X1A"},
    }

    for resource in (with_use, without_use):
        fragment = to_graph(resource)
        (rel,) = _rels(fragment, "IDENTIFIED_BY")
        assert "order" not in rel.properties
        assert from_graph(fragment) == resource


def test_a_code_that_is_not_a_codeable_concept_is_kept_and_not_copied_as_a_filter_code() -> None:
    resource = {"resourceType": "Observation", "id": OBS_ID, "status": "final", "code": "x"}

    fragment = to_graph(resource)

    assert "measureCode" not in fragment.nodes[0].properties
    assert from_graph(fragment) == resource


@pytest.mark.parametrize(
    "coding_extra", [{"userSelected": "yes"}, {"display": 7}, {"version": None}]
)
def test_a_coding_with_a_non_text_or_non_boolean_detail_is_refused(
    coding_extra: dict[str, Any],
) -> None:
    coding = {"system": STATUS, "code": "accepting", **coding_extra}
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "code": {"coding": [coding]},
    }

    with pytest.raises(UnsupportedElement) as raised:
        to_graph(resource)

    assert raised.value.path == "Observation.code"


@pytest.mark.parametrize("low", [{}, {"comparator": "<", "value": 1}])
def test_a_range_part_that_cannot_be_flattened_exactly_is_refused(low: dict[str, Any]) -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "valueRange": {"low": low},
    }

    with pytest.raises(UnsupportedElement) as raised:
        to_graph(resource)

    assert raised.value.path == "Observation.valueRange"


def _fragment_with(extra_props: dict[str, Any] | None = None) -> GraphFragment:
    base = to_graph(CAPACITY_REPORT)
    root = _one_node(base, f"Observation/{OBS_ID}")
    props = {**root.properties, **(extra_props or {})}
    return GraphFragment(
        root_key=base.root_key,
        nodes=(NodeSpec(root.key, root.labels, props), *base.nodes[1:]),
        rels=base.rels,
    )


def test_from_graph_refuses_a_flattened_property_with_too_many_parts() -> None:
    fragment = _fragment_with({"valueQuantity_a_b_c": 1})

    with pytest.raises(ValidationFailed) as raised:
        from_graph(fragment)

    assert raised.value.field == "valueQuantity_a_b_c"


def test_from_graph_refuses_a_fragment_whose_element_mixes_reference_and_concept() -> None:
    base = to_graph(CAPACITY_REPORT)
    reference = RelSpec(
        type="CODE",
        start=base.root_key,
        end="Location/l9",
        properties={"fhirPath": "Observation.code", "order": 1},
    )
    fragment = GraphFragment(base.root_key, base.nodes, (*base.rels, reference))

    with pytest.raises(ValidationFailed) as raised:
        from_graph(fragment)

    assert raised.value.field == "code"


def test_from_graph_refuses_a_concept_list_mixed_with_a_single_concept() -> None:
    base = to_graph(SERVICE_TWO_CATEGORIES)
    first, second = _rels(base, "CATEGORY")
    unlisted_first = RelSpec(
        type=first.type,
        start=first.start,
        end=first.end,
        properties={key: value for key, value in first.properties.items() if key != "conceptOrder"},
    )
    other_rels = [rel for rel in base.rels if rel.type != "CATEGORY"]
    mixed = GraphFragment(base.root_key, base.nodes, (*other_rels, unlisted_first, second))

    with pytest.raises(ValidationFailed) as raised:
        from_graph(mixed)

    assert raised.value.field == "category"


def test_from_graph_refuses_codings_of_one_concept_that_disagree_on_text() -> None:
    base = to_graph(SERVICE_TWO_CATEGORIES)
    first, second = _rels(base, "CATEGORY")
    second_other_text = RelSpec(
        type=second.type,
        start=second.start,
        end=second.end,
        properties={**second.properties, "text": "Other"},
    )
    other_rels = [rel for rel in base.rels if rel.type != "CATEGORY"]
    disagreeing = GraphFragment(base.root_key, base.nodes, (*other_rels, first, second_other_text))

    with pytest.raises(ValidationFailed) as raised:
        from_graph(disagreeing)

    assert raised.value.field == "category"


@pytest.mark.parametrize("part", ["low", "high"])
def test_a_range_with_only_one_end_round_trips(part: str) -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "valueRange": {part: {"value": 2, "unit": "referral"}},
    }

    fragment = to_graph(resource)

    assert from_graph(fragment) == resource
    assert f"valueRange_{part}_value" in fragment.nodes[0].properties


def test_rebuild_restores_the_original_order_whatever_order_the_relationships_arrive_in() -> None:
    resource = {
        "resourceType": "Organization",
        "id": ORG_ID,
        "type": [
            {
                "coding": [
                    {"system": ORGANIZATION_TYPE, "code": "nhs-trust"},
                    {"system": ORGANIZATION_TYPE, "code": "community"},
                ],
                "text": "Trust and community",
            },
            {"coding": [{"system": ORGANIZATION_TYPE, "code": "hospice"}]},
        ],
        "identifier": [
            {"system": ODS_ORG_SYSTEM, "value": "X1A"},
            {"system": ODS_SITE_SYSTEM, "value": "S9Z", "use": "secondary"},
        ],
    }
    fragment = to_graph(resource)
    reversed_rels = GraphFragment(fragment.root_key, fragment.nodes, tuple(reversed(fragment.rels)))

    assert reversed_rels.rels != fragment.rels
    assert from_graph(reversed_rels) == resource


# Graph-safety helper: the exemption for UCUM annotations is narrow (DEC-051 item 13).


def _fragment_with_property(name: str, value: str) -> GraphFragment:
    key = f"Observation/{OBS_ID}"
    return GraphFragment(
        root_key=key,
        nodes=(NodeSpec(key, ("Resource", "Observation"), {"id": OBS_ID, name: value}),),
        rels=(),
    )


@pytest.mark.parametrize("value", ['{"a":1}', '["a","b"]', "[1,2]", "{}", "[]"])
def test_a_code_property_holding_json_is_refused(value: str) -> None:
    with pytest.raises(AssertionError):
        _assert_graph_safe(_fragment_with_property("valueQuantity_code", value))


@pytest.mark.parametrize("value", ["{bad", "[x", "{not ucum}", "{a b}"])
def test_a_code_property_holding_a_bracketed_non_ucum_value_is_refused(value: str) -> None:
    with pytest.raises(AssertionError):
        _assert_graph_safe(_fragment_with_property("valueQuantity_code", value))


@pytest.mark.parametrize("value", ["{referral}", "[in_i]"])
def test_a_real_ucum_annotation_in_a_code_property_passes(value: str) -> None:
    _assert_graph_safe(_fragment_with_property("valueQuantity_code", value))


@pytest.mark.parametrize(
    ("name", "value"),
    [("valueQuantity_unit", "{referral}"), ("valueQuantity_system", "[in_i]")],
)
def test_a_ucum_looking_value_outside_a_code_property_is_refused(name: str, value: str) -> None:
    with pytest.raises(AssertionError):
        _assert_graph_safe(_fragment_with_property(name, value))


# TEN-008 (DEC-162): Concept, CodeSystem and Identifier are tenant-scoped like every other node.
# The mapper stays pure: a shared node is plain data with no tenant and no "shared" flag, and the
# store stamps it. Reading back a stamped one must not turn the stamp into a FHIR element.

_SHARED_LABELS = ("Concept", "CodeSystem", "Identifier")
_TENANT_NAMES = ("tenantId", "sourceTenantId")


def _shared_nodes(fragment: GraphFragment) -> list[NodeSpec]:
    return [node for node in fragment.nodes if node.labels[0] in _SHARED_LABELS]


def test_a_shared_node_is_plain_data_with_no_tenant_and_no_shared_flag() -> None:
    fragment = to_graph(ORGANIZATION_WITH_TYPE)

    shared = _shared_nodes(fragment)
    assert {node.labels for node in shared} == {("Concept",), ("CodeSystem",), ("Identifier",)}
    allowed = {
        ("Concept",): {"system", "code", "display", "version"},
        ("CodeSystem",): {"url"},
        ("Identifier",): {"system", "value"},
    }
    for node in shared:
        assert set(node.properties) <= allowed[node.labels]
    assert [field for field in NodeSpec.__dataclass_fields__] == ["key", "labels", "properties"]


def test_a_coding_system_or_code_that_spells_a_tenant_name_is_a_value_not_a_property() -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "code": {
            "coding": [{"system": "tenantId", "code": "sourceTenantId", "display": "tenantId"}]
        },
        "identifier": [{"system": "tenantId", "value": "sourceTenantId"}],
    }

    fragment = to_graph(resource)

    assert from_graph(fragment) == resource
    for node in _shared_nodes(fragment):
        assert not set(node.properties) & set(_TENANT_NAMES)


@pytest.mark.parametrize("resource", [CAPACITY_REPORT, ORGANIZATION_WITH_TYPE])
def test_a_stamped_concept_codesystem_and_identifier_do_not_change_the_rebuilt_resource(
    resource: dict[str, Any],
) -> None:
    fragment = to_graph(resource)
    stamped = GraphFragment(
        fragment.root_key,
        tuple(
            NodeSpec(node.key, node.labels, {**node.properties, "tenantId": "tenant-a"})
            for node in fragment.nodes
        ),
        fragment.rels,
    )

    assert from_graph(stamped) == resource
    assert _shared_nodes(stamped), "the sample must hold shared nodes for this to prove anything"


def test_the_same_coding_in_two_resources_gives_equal_shared_nodes_for_any_tenant() -> None:
    first = to_graph(CAPACITY_REPORT)
    second = to_graph({**CAPACITY_REPORT, "id": "9e4c3f5b-6d7a-4182-8d2e-3f4a5b6c7d99"})

    assert sorted(
        (n.key, tuple(sorted(n.properties.items()))) for n in _shared_nodes(first)
    ) == sorted((n.key, tuple(sorted(n.properties.items()))) for n in _shared_nodes(second))


@pytest.mark.parametrize("element", _TENANT_NAMES)
def test_a_period_range_or_quantity_named_for_a_tenant_is_refused(element: str) -> None:
    for value in (
        {"start": "2026-10-25T09:00:00Z"},
        {"low": {"value": 1}, "high": {"value": 2}},
        {"value": 3, "unit": "referral"},
    ):
        with pytest.raises(ValidationFailed):
            to_graph({"resourceType": "Observation", "id": OBS_ID, element: value})


def test_an_identifier_that_carries_a_tenant_key_is_refused_not_dropped() -> None:
    resource = {
        "resourceType": "Organization",
        "id": ORG_ID,
        "identifier": [{"system": ODS_ORG_SYSTEM, "value": "X1A", "tenantId": "tenant-b"}],
    }

    with pytest.raises(UnsupportedElement):
        to_graph(resource)


def test_a_coding_that_carries_a_tenant_key_is_refused_not_dropped() -> None:
    resource = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "code": {"coding": [{"system": STATUS, "code": "accepting", "tenantId": "tenant-b"}]},
    }

    with pytest.raises(UnsupportedElement):
        to_graph(resource)
