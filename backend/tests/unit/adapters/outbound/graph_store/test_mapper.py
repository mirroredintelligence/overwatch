"""Pure tests for the FHIR-to-graph mapper (G02): resources, primitives and references.

DEC-001: no node or relationship carries a serialised resource, so there is no `json` property.
The prompt's "json equals the canonical resource" tests are replaced by the round-trip and
graph-safety tests below.
"""

import ast
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.adapters.outbound.graph_store import mapper as mapper_module
from diucs.adapters.outbound.graph_store.extensions import TENANT_OWNED_NAMES
from diucs.adapters.outbound.graph_store.mapper import (
    GraphFragment,
    InvalidReference,
    NodeSpec,
    RelSpec,
    UnsupportedElement,
    from_graph,
    to_graph,
    upper_snake,
)
from diucs.domain.codes import BASE_URL
from diucs.domain.errors import DomainError, NotFound, ValidationFailed

ORG_ID = "6b1f0c2e-3a4d-4e5f-8a9b-0c1d2e3f4a5b"
LOC_ID = "7c2a1d3f-4b5e-4f60-9b0c-1d2e3f4a5b6c"
SVC_ID = "8d3b2e4a-5c6f-4071-8c1d-2e3f4a5b6c7d"

ORGANIZATION: dict[str, Any] = {
    "resourceType": "Organization",
    "id": ORG_ID,
    "active": True,
    "name": "Dorset HealthCare",
    "alias": ["DHC", "Dorset HC"],
}

LOCATION: dict[str, Any] = {
    "resourceType": "Location",
    "id": LOC_ID,
    "status": "active",
    "name": "Example Site",
    "partOf": {"reference": "Location/l0", "display": "Site"},
}

HEALTHCARE_SERVICE: dict[str, Any] = {
    "resourceType": "HealthcareService",
    "id": SVC_ID,
    "active": True,
    "name": "Example Service",
    "location": [{"reference": "Location/l1"}, {"reference": "Location/l2", "display": "Second"}],
}

GRAPH_SAFE_SAMPLES = [ORGANIZATION, LOCATION, HEALTHCARE_SERVICE]


def _node(fragment: GraphFragment, key: str) -> NodeSpec:
    matches = [node for node in fragment.nodes if node.key == key]
    assert len(matches) == 1, f"expected one node {key}, found {len(matches)}"
    return matches[0]


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
                assert not value.lstrip().startswith(("{", "[")), f"{name} looks like JSON"


# 1. upper_snake


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("providedBy", "PROVIDED_BY"),
        ("partOf", "PART_OF"),
        ("managingOrganization", "MANAGING_ORGANIZATION"),
        ("valueQuantity", "VALUE_QUANTITY"),
        ("id", "ID"),
    ],
)
def test_upper_snake_converts_lower_camel_case(name: str, expected: str) -> None:
    assert upper_snake(name) == expected


# 2. An Organization is one node with its primitives


def test_organization_is_one_node_with_resource_and_type_labels() -> None:
    fragment = to_graph(ORGANIZATION)

    assert fragment.root_key == f"Organization/{ORG_ID}"
    assert len(fragment.nodes) == 1
    node = _node(fragment, f"Organization/{ORG_ID}")
    assert node.labels == ("Resource", "Organization")
    assert node.properties["active"] is True
    assert node.properties["name"] == "Dorset HealthCare"
    assert node.properties["alias"] == ["DHC", "Dorset HC"]
    assert node.properties["id"] == ORG_ID
    assert node.properties["iri"] == f"{BASE_URL}fhir/Organization/{ORG_ID}"
    assert node.properties["iri"].endswith(f"fhir/Organization/{ORG_ID}")
    assert fragment.rels == ()


# 3. A Reference becomes a relationship with fhirPath and display


def test_part_of_reference_becomes_part_of_relationship_with_display() -> None:
    fragment = to_graph(LOCATION)

    assert fragment.rels == (
        RelSpec(
            type="PART_OF",
            start=f"Location/{LOC_ID}",
            end="Location/l0",
            properties={"fhirPath": "Location.partOf", "display": "Site"},
        ),
    )


def test_target_of_a_reference_is_not_created_as_a_node() -> None:
    fragment = to_graph(LOCATION)

    assert all(node.key != "Location/l0" for node in fragment.nodes)


# 4. Repeating references carry order


def test_repeating_reference_gets_zero_based_order() -> None:
    fragment = to_graph(HEALTHCARE_SERVICE)
    locations = [rel for rel in fragment.rels if rel.type == "LOCATION"]

    assert [rel.end for rel in locations] == ["Location/l1", "Location/l2"]
    assert [rel.properties["order"] for rel in locations] == [0, 1]
    assert all(rel.properties["fhirPath"] == "HealthcareService.location" for rel in locations)
    assert "display" not in locations[0].properties
    assert locations[1].properties["display"] == "Second"


def test_single_valued_reference_has_no_order() -> None:
    fragment = to_graph(LOCATION)

    assert "order" not in fragment.rels[0].properties


# 5. from_graph(to_graph(r)) == r


@pytest.mark.parametrize("resource", GRAPH_SAFE_SAMPLES, ids=lambda r: r["resourceType"])
def test_round_trip_rebuilds_the_resource_from_the_fragment(resource: dict[str, Any]) -> None:
    assert from_graph(to_graph(resource)) == resource


def test_round_trip_keeps_meta_and_zoned_datetimes_as_written() -> None:
    resource = {
        **LOCATION,
        "meta": {"versionId": "3", "lastUpdated": "2026-10-25T01:55:00+01:00"},
    }
    fragment = to_graph(resource)

    node = _node(fragment, f"Location/{LOC_ID}")
    assert node.properties["versionId"] == "3"
    assert node.properties["lastUpdated"] == "2026-10-25T01:55:00+01:00"
    assert from_graph(fragment) == resource


# 6. Key order does not change the fragment (DEC-001 replaces the canonical-json test)


def test_dicts_with_different_key_order_give_the_same_fragment() -> None:
    reordered = dict(reversed(list(HEALTHCARE_SERVICE.items())))

    assert list(reordered) != list(HEALTHCARE_SERVICE)
    assert to_graph(reordered) == to_graph(HEALTHCARE_SERVICE)


def test_no_node_or_relationship_carries_a_json_property() -> None:
    for resource in GRAPH_SAFE_SAMPLES:
        _assert_graph_safe(to_graph(resource))


# 7. Unmapped elements are refused, not dropped


def test_codeable_concept_with_an_unmapped_element_raises_unsupported_element() -> None:
    resource = {
        "resourceType": "Organization",
        "id": ORG_ID,
        "type": [{"coding": [{"system": "https://example.test/cs", "code": "x"}], "extension": []}],
    }

    with pytest.raises(UnsupportedElement) as raised:
        to_graph(resource)

    assert raised.value.path == "Organization.type"


@pytest.mark.parametrize(
    ("element", "value"),
    [
        ("contact", [{"name": {"text": "x"}}]),
        ("extension", [{"url": "https://example.test/ext", "valueString": "x"}]),
        ("telecom", None),
        ("meta", {"tag": [{"code": "x"}]}),
    ],
)
def test_other_unmapped_shapes_are_refused(element: str, value: Any) -> None:
    resource = {"resourceType": "Organization", "id": ORG_ID, element: value}

    with pytest.raises(UnsupportedElement):
        to_graph(resource)


def test_empty_list_is_refused() -> None:
    with pytest.raises(UnsupportedElement) as raised:
        to_graph({"resourceType": "Organization", "id": ORG_ID, "alias": []})

    assert raised.value.path == "Organization.alias"


def test_a_list_mixing_primitives_and_references_is_refused() -> None:
    resource = {
        "resourceType": "HealthcareService",
        "id": SVC_ID,
        "location": [{"reference": "Location/l1"}, "not-a-reference"],
    }

    with pytest.raises(UnsupportedElement):
        to_graph(resource)


@pytest.mark.parametrize("target", ["Location", "Location/", "/l1", "Location/l1/_history/2"])
def test_a_reference_that_is_not_relative_type_and_id_is_refused(target: str) -> None:
    resource = {"resourceType": "Location", "id": LOC_ID, "partOf": {"reference": target}}

    with pytest.raises(InvalidReference):
        to_graph(resource)


def test_a_resource_without_an_id_is_refused_with_a_field_name_only() -> None:
    with pytest.raises(ValidationFailed) as raised:
        to_graph({"resourceType": "Organization", "name": "Dorset HealthCare"})

    assert raised.value.field == "id"


# 8. Graph-safety schema (DEC-001) for every sample


@pytest.mark.parametrize("resource", GRAPH_SAFE_SAMPLES, ids=lambda r: r["resourceType"])
def test_samples_hold_no_map_no_list_of_maps_and_no_json_string(resource: dict[str, Any]) -> None:
    _assert_graph_safe(to_graph(resource))


# 9. The mapper does no I/O and imports nothing from neo4j


def test_mapper_module_imports_nothing_from_neo4j() -> None:
    source = (
        Path(__file__).resolve().parents[5] / "src/diucs/adapters/outbound/graph_store/mapper.py"
    ).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not [name for name in imported if name.split(".")[0] == "neo4j"]


# 10. Error paths and the one skip path, covered after green (branch coverage for the mapper)


def test_a_resource_whose_id_is_not_text_is_refused() -> None:
    with pytest.raises(ValidationFailed) as raised:
        to_graph({"resourceType": "Organization", "id": 42})

    assert raised.value.field == "id"


def test_meta_with_a_non_primitive_value_is_refused() -> None:
    resource = {"resourceType": "Organization", "id": ORG_ID, "meta": {"versionId": {"x": 1}}}

    with pytest.raises(UnsupportedElement) as raised:
        to_graph(resource)

    assert raised.value.path == "Organization.meta"


def test_a_reference_display_that_is_not_text_is_refused() -> None:
    resource = {
        "resourceType": "Location",
        "id": LOC_ID,
        "partOf": {"reference": "Location/l0", "display": 7},
    }

    with pytest.raises(UnsupportedElement) as raised:
        to_graph(resource)

    assert raised.value.path == "Location.partOf"


def test_from_graph_refuses_a_fragment_whose_root_is_absent() -> None:
    fragment = to_graph(LOCATION)
    orphan = GraphFragment(root_key="Location/missing", nodes=fragment.nodes, rels=fragment.rels)

    with pytest.raises(NotFound):
        from_graph(orphan)


def test_from_graph_ignores_relationships_that_start_elsewhere() -> None:
    fragment = to_graph(LOCATION)
    other = RelSpec(
        type="PART_OF",
        start="Location/other",
        end="Location/l9",
        properties={"fhirPath": "Location.partOf"},
    )
    mixed = GraphFragment(
        root_key=fragment.root_key, nodes=fragment.nodes, rels=(*fragment.rels, other)
    )

    assert from_graph(mixed) == LOCATION


def test_from_graph_refuses_two_references_for_a_single_valued_element() -> None:
    fragment = to_graph(LOCATION)
    duplicate = RelSpec(
        type="PART_OF",
        start=fragment.root_key,
        end="Location/l5",
        properties={"fhirPath": "Location.partOf"},
    )
    broken = GraphFragment(
        root_key=fragment.root_key, nodes=fragment.nodes, rels=(*fragment.rels, duplicate)
    )

    with pytest.raises(ValidationFailed) as raised:
        from_graph(broken)

    assert raised.value.field == "partOf"


def test_a_resource_without_a_resource_type_is_refused() -> None:
    with pytest.raises(ValidationFailed) as raised:
        to_graph({"id": ORG_ID, "name": "Dorset HealthCare"})

    assert raised.value.field == "resourceType"


# 11. F1 (verifier, 65f622d): the round trip must be exact or refused, never lossy.


def test_an_empty_meta_object_is_refused_not_dropped() -> None:
    with pytest.raises(ValidationFailed) as raised:
        to_graph({"resourceType": "Organization", "id": ORG_ID, "meta": {}})

    assert raised.value.field == "meta"


@pytest.mark.parametrize("element", ["iri", "versionId", "lastUpdated"])
def test_a_top_level_name_the_node_already_uses_is_refused(element: str) -> None:
    resource = {"resourceType": "Organization", "id": ORG_ID, element: "2026-10-25T01:55:00+01:00"}

    with pytest.raises(ValidationFailed) as raised:
        to_graph(resource)

    assert raised.value.field == element


def test_a_top_level_iri_is_never_overwritten_or_dropped() -> None:
    resource = {"resourceType": "Organization", "id": ORG_ID, "iri": "https://example.test/x"}

    with pytest.raises(ValidationFailed):
        to_graph(resource)


def test_a_top_level_version_id_does_not_move_into_meta() -> None:
    resource = {"resourceType": "Organization", "id": ORG_ID, "versionId": "3"}

    with pytest.raises(ValidationFailed) as raised:
        to_graph(resource)

    assert raised.value.field == "versionId"


_LOSSY_OR_EXACT_CASES: list[dict[str, Any]] = [
    {"resourceType": "Organization", "id": ORG_ID, "meta": {}},
    {"resourceType": "Organization", "id": ORG_ID, "iri": "https://example.test/x"},
    {"resourceType": "Organization", "id": ORG_ID, "versionId": "3"},
    {"resourceType": "Organization", "id": ORG_ID, "lastUpdated": "2026-10-25T01:55:00Z"},
    {"resourceType": "Organization", "id": ORG_ID, "meta": {"versionId": "3"}},
    {"resourceType": "Organization", "id": ORG_ID, "meta": {"lastUpdated": "2026-10-25T01:55:00Z"}},
    {"resourceType": "Organization", "id": ORG_ID, "alias": ["DHC"], "active": False},
    {"resourceType": "Location", "id": LOC_ID, "partOf": {"reference": "Location/l0"}},
    {
        "resourceType": "Location",
        "id": LOC_ID,
        "partOf": {"reference": "Location/l0", "display": ""},
    },
]


@pytest.mark.parametrize("resource", _LOSSY_OR_EXACT_CASES)
def test_round_trip_is_exact_or_refused_for_each_known_edge(resource: dict[str, Any]) -> None:
    try:
        fragment = to_graph(resource)
    except DomainError:
        return
    assert from_graph(fragment) == resource


_NAMES = st.sampled_from(
    [
        "name",
        "active",
        "alias",
        "status",
        "partOf",
        "location",
        "iri",
        "versionId",
        "lastUpdated",
        "meta",
        "extra",
        "type",
    ]
)
_PRIMITIVE = st.one_of(st.text(max_size=12), st.booleans(), st.integers(-1000, 1000))
_REFERENCE = st.fixed_dictionaries(
    {
        "reference": st.tuples(
            st.sampled_from(["Location", "Organization"]),
            st.from_regex(r"[a-z0-9]{1,6}", fullmatch=True),
        ).map(lambda pair: f"{pair[0]}/{pair[1]}")
    },
    optional={"display": st.text(max_size=8)},
)
_META = st.dictionaries(
    st.sampled_from(["versionId", "lastUpdated", "tag"]),
    st.text(max_size=12),
    max_size=3,
)
_VALUE = st.one_of(
    _PRIMITIVE,
    st.lists(_PRIMITIVE, min_size=1, max_size=3),
    _REFERENCE,
    st.lists(_REFERENCE, min_size=1, max_size=3),
    _META,
    st.none(),
)


@settings(max_examples=400, deadline=None)
@given(
    resource_type=st.sampled_from(["Organization", "Location", "HealthcareService"]),
    resource_id=st.from_regex(r"[a-z0-9-]{1,12}", fullmatch=True),
    body=st.dictionaries(_NAMES, _VALUE, max_size=5),
)
def test_round_trip_is_exact_or_refused_for_any_generated_resource(
    resource_type: str, resource_id: str, body: dict[str, Any]
) -> None:
    resource = {**body, "resourceType": resource_type, "id": resource_id}
    try:
        fragment = to_graph(resource)
    except DomainError:
        return
    assert from_graph(fragment) == resource


# 12. TEN-008 (DEC-162): `tenantId` and `sourceTenantId` belong to the tenancy seam. A resource
# cannot carry them, so it cannot forge, move or overwrite the tenant stamp the store writes.

TENANT_NAMES = ("tenantId", "sourceTenantId")


def _stamped(fragment: GraphFragment, tenant: str = "tenant-a") -> GraphFragment:
    """The fragment as the store hands it back: every node carries the stamp."""
    nodes = tuple(
        NodeSpec(node.key, node.labels, {**node.properties, "tenantId": tenant})
        for node in fragment.nodes
    )
    return GraphFragment(fragment.root_key, nodes, fragment.rels)


def _all_property_names(fragment: GraphFragment) -> set[str]:
    return {name for node in fragment.nodes for name in node.properties} | {
        name for rel in fragment.rels for name in rel.properties
    }


def test_the_tenant_owned_names_are_exactly_tenant_id_and_source_tenant_id() -> None:
    assert frozenset(TENANT_NAMES) == TENANT_OWNED_NAMES


@pytest.mark.parametrize("element", TENANT_NAMES)
@pytest.mark.parametrize(
    "value",
    [
        "tenant-b",
        7,
        True,
        ["tenant-b"],
        {"reference": "Organization/o1"},
        {"coding": [{"system": "https://diucs.example/CodeSystem/x", "code": "y"}]},
        {"start": "2026-10-25T09:00:00Z"},
        {"value": 3, "unit": "referral"},
        {"nested": {"tenantId": "tenant-b"}},
    ],
)
def test_a_resource_with_a_tenant_element_of_any_shape_is_refused(element: str, value: Any) -> None:
    resource = {"resourceType": "Organization", "id": ORG_ID, element: value}

    with pytest.raises(ValidationFailed) as raised:
        to_graph(resource)

    assert raised.value.field == element
    assert "reserved" in str(raised.value)


@pytest.mark.parametrize("element", TENANT_NAMES)
def test_a_tenant_element_is_refused_even_when_the_rest_of_the_resource_is_valid(
    element: str,
) -> None:
    resource = {**ORGANIZATION, element: "tenant-b"}

    with pytest.raises(ValidationFailed):
        to_graph(resource)


@pytest.mark.parametrize("element", TENANT_NAMES)
def test_a_tenant_name_inside_meta_is_refused(element: str) -> None:
    resource = {"resourceType": "Organization", "id": ORG_ID, "meta": {element: "tenant-b"}}

    with pytest.raises(UnsupportedElement):
        to_graph(resource)


@pytest.mark.parametrize("name", TENANT_NAMES)
def test_a_tenant_name_is_refused_by_name_only_never_as_a_value(name: str) -> None:
    resource = {
        "resourceType": "Organization",
        "id": ORG_ID,
        "name": name,
        "alias": [name],
        "partOf": {"reference": "Organization/o0", "display": name},
    }

    assert from_graph(to_graph(resource)) == resource


@pytest.mark.parametrize("element", TENANT_NAMES)
def test_a_resource_that_would_use_a_reserved_name_via_a_configured_copy_is_refused(
    element: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A copied filter code writes a property of its own. Should one ever be named for the stamp,
    # to_graph refuses the whole resource instead of letting it reach the writer.
    monkeypatch.setitem(mapper_module.FILTER_CODE_PROPERTIES, ("Observation", "code"), element)
    resource = {
        "resourceType": "Observation",
        "id": "obs-1",
        "code": {"coding": [{"system": "https://diucs.example/CodeSystem/m", "code": "c"}]},
    }

    with pytest.raises(ValidationFailed) as raised:
        to_graph(resource)

    assert raised.value.field == element


@pytest.mark.parametrize("element", TENANT_NAMES)
def test_a_relationship_property_cannot_carry_a_tenant_name_either(
    element: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Relationships carry no tenant (DEC-130 item 1): the guard covers them too.
    original = mapper_module._reference_rel

    def forged(*args: Any, **kwargs: Any) -> RelSpec:
        rel = original(*args, **kwargs)
        return RelSpec(rel.type, rel.start, rel.end, {**rel.properties, element: "tenant-b"})

    monkeypatch.setattr(mapper_module, "_reference_rel", forged)

    with pytest.raises(ValidationFailed) as raised:
        to_graph(LOCATION)

    assert raised.value.field == element


@pytest.mark.parametrize("element", TENANT_NAMES)
def test_from_graph_strips_a_stored_tenant_name_so_it_is_never_a_fhir_element(
    element: str,
) -> None:
    fragment = to_graph(ORGANIZATION)
    root = fragment.nodes[0]
    stored = GraphFragment(
        fragment.root_key,
        (NodeSpec(root.key, root.labels, {**root.properties, element: "tenant-a"}),),
        fragment.rels,
    )

    assert from_graph(stored) == ORGANIZATION


def test_a_round_trip_through_a_stamped_fragment_gives_back_the_resource_exactly() -> None:
    for resource in (ORGANIZATION, LOCATION, HEALTHCARE_SERVICE):
        stamped = _stamped(to_graph(resource))

        assert from_graph(stamped) == resource
        assert all(node.properties["tenantId"] == "tenant-a" for node in stamped.nodes)


def test_stripping_the_stamp_does_not_change_the_fragment_it_was_given() -> None:
    stamped = _stamped(to_graph(ORGANIZATION))
    before = [dict(node.properties) for node in stamped.nodes]

    from_graph(stamped)

    assert [dict(node.properties) for node in stamped.nodes] == before


def test_to_graph_gives_a_fragment_that_names_no_tenant_and_the_same_one_for_any_tenant() -> None:
    names = _all_property_names(to_graph(HEALTHCARE_SERVICE))

    assert not names & set(TENANT_NAMES)
    assert to_graph(HEALTHCARE_SERVICE) == to_graph(dict(HEALTHCARE_SERVICE))


_TENANT_ELEMENTS = st.sampled_from([*TENANT_NAMES, "name", "active", "alias", "status", "meta"])


@settings(max_examples=300, deadline=None)
@given(
    resource_type=st.sampled_from(["Organization", "Location", "HealthcareService"]),
    resource_id=st.from_regex(r"[a-z0-9-]{1,12}", fullmatch=True),
    body=st.dictionaries(_TENANT_ELEMENTS, _VALUE, max_size=5),
)
def test_no_generated_resource_puts_a_tenant_name_on_any_node_or_relationship(
    resource_type: str, resource_id: str, body: dict[str, Any]
) -> None:
    resource = {**body, "resourceType": resource_type, "id": resource_id}
    try:
        fragment = to_graph(resource)
    except DomainError:
        return
    # A resource that carries a tenant name must have been refused above.
    assert not set(body) & set(TENANT_NAMES)
    assert not _all_property_names(fragment) & set(TENANT_NAMES)
    assert from_graph(_stamped(fragment)) == resource
