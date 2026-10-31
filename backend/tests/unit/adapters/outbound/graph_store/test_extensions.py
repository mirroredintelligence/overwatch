"""Pure tests for the extension registry and extension mapping (G04, rule R8).

R8: an extension becomes the property `ext_<shortName>`, from a registry that maps its URL to a
short name and a value type. An unregistered URL is refused with UnknownExtension (DEC-049: refuse,
never drop). Extension order is kept in `extensionOrder` so the rebuilt list is exactly the input.
All values are synthetic.
"""

from typing import Any

import pytest

from diucs.adapters.outbound.graph_store.extensions import (
    EXTENSIONS,
    TENANT_OWNED_NAMES,
    ExtensionDef,
    register_extension,
)
from diucs.adapters.outbound.graph_store.mapper import (
    GraphFragment,
    NodeSpec,
    RelSpec,
    UnknownExtension,
    UnsupportedElement,
    from_graph,
    to_graph,
)
from diucs.domain.codes import BASE_URL
from diucs.domain.errors import DomainError, ValidationFailed

ORG_ID = "6b1f0c2e-3a4d-4e5f-8a9b-0c1d2e3f4a5b"
LOC_ID = "7c2a1d3f-4b5e-4f60-9b0c-1d2e3f4a5b6c"
SVC_ID = "8d3b2e4a-5c6f-4071-8c1d-2e3f4a5b6c7d"
OBS_ID = "9e4c3f5b-6d7a-4182-8d2e-3f4a5b6c7d8e"
SVC_KEY = f"HealthcareService/{SVC_ID}"

# The registry as the product needs it (R8, fhir-data-model.md), with its value types.
REGISTERED_TYPES: dict[str, str] = {
    "smsShortName": "string",
    "establishedCapacity": "integer",
    "canExceedEstablished": "boolean",
    "usualRangeMin": "integer",
    "usualRangeMax": "integer",
    "reportCadence": "string",
    "limitedLevelPercent": "integer",
    "geocodeSource": "string",
    "geocodedAt": "dateTime",
    "uprn": "string",
    "reportType": "string",
    "referrerType": "string",
    "measure": "string",
    "unitLabel": "string",
    "channel": "string",
    "coveredBy": "string",
    "coveredUntil": "dateTime",
    "ageBand": "string",
    "urgency": "string",
    "closedAt": "dateTime",
    "outcome": "string",
    "bestFitNotUsed": "string",
    "scoreCorrections": "integer",
    # P13: a registration's four approval checks (domain-rules 6.2). checkScope holds the scope
    # flag, and is left out until the scope is decided.
    "checkAutomatic": "boolean",
    "checkCallback": "boolean",
    "checkScope": "string",
    "checkCriteria": "boolean",
    "alertKind": "string",
    "escalationDueAt": "dateTime",
    "acknowledgedAt": "dateTime",
    "why": "string",
    "snapshotRef": "string",
    "takenAt": "dateTime",
}

_VALUE_KEY = {
    "string": "valueString",
    "integer": "valueInteger",
    "boolean": "valueBoolean",
    "dateTime": "valueDateTime",
    "decimal": "valueDecimal",
}

_SAMPLE_VALUE: dict[str, Any] = {
    "string": "example",
    "integer": 8,
    "boolean": True,
    "dateTime": "2026-10-25T09:30:00+01:00",
    "decimal": 2.5,
}


def _url(short_name: str) -> str:
    return f"{BASE_URL}StructureDefinition/{short_name}"


def _extension(short_name: str, value: Any) -> dict[str, Any]:
    value_type = REGISTERED_TYPES[short_name]
    return {"url": _url(short_name), _VALUE_KEY[value_type]: value}


def _service_with(*extensions: dict[str, Any]) -> dict[str, Any]:
    return {"resourceType": "HealthcareService", "id": SVC_ID, "extension": list(extensions)}


def _root(fragment: GraphFragment) -> dict[str, Any]:
    matches = [node for node in fragment.nodes if node.key == fragment.root_key]
    assert len(matches) == 1
    return matches[0].properties


# The registry


def test_registry_holds_the_twenty_six_named_extensions() -> None:
    assert {defn.short_name for defn in EXTENSIONS.values()} == set(REGISTERED_TYPES)


@pytest.mark.parametrize(("short_name", "value_type"), sorted(REGISTERED_TYPES.items()))
def test_each_registered_extension_has_its_url_and_value_type(
    short_name: str, value_type: str
) -> None:
    defn = EXTENSIONS[_url(short_name)]

    assert defn == ExtensionDef(url=_url(short_name), short_name=short_name, value_type=value_type)


def test_registering_an_extension_is_one_line_and_it_is_mapped() -> None:
    defn = ExtensionDef(url=_url("testFlag"), short_name="testFlag", value_type="boolean")
    try:
        register_extension(defn)
        fragment = to_graph(_service_with({"url": _url("testFlag"), "valueBoolean": True}))
    finally:
        EXTENSIONS.pop(_url("testFlag"), None)

    assert _root(fragment)["ext_testFlag"] is True


def test_registering_the_same_url_twice_is_refused() -> None:
    defn = ExtensionDef(url=_url("twiceFlag"), short_name="twiceFlag", value_type="string")
    try:
        register_extension(defn)
        with pytest.raises(ValueError):
            register_extension(defn)
    finally:
        EXTENSIONS.pop(_url("twiceFlag"), None)


def test_a_url_that_does_not_match_its_short_name_is_refused() -> None:
    with pytest.raises(ValueError):
        register_extension(
            ExtensionDef(
                url="https://example.test/other", short_name="wrongUrl", value_type="string"
            )
        )


@pytest.mark.parametrize("short_name", ["under_score", "with-dash", "9starts", ""])
def test_a_short_name_must_be_a_plain_identifier(short_name: str) -> None:
    with pytest.raises(ValueError):
        register_extension(
            ExtensionDef(url=_url(short_name), short_name=short_name, value_type="string")
        )


# Mapping an extension to ext_<shortName>


@pytest.mark.parametrize("short_name", sorted(REGISTERED_TYPES))
def test_an_extension_becomes_an_ext_property_and_round_trips(short_name: str) -> None:
    value = _SAMPLE_VALUE[REGISTERED_TYPES[short_name]]
    resource = _service_with(_extension(short_name, value))

    fragment = to_graph(resource)

    assert _root(fragment)[f"ext_{short_name}"] == value
    assert from_graph(fragment) == resource


def test_establishedcapacity_eight_is_stored_as_the_integer_eight() -> None:
    fragment = to_graph(_service_with(_extension("establishedCapacity", 8)))

    assert _root(fragment)["ext_establishedCapacity"] == 8


def test_an_unregistered_extension_url_is_refused_and_names_the_url() -> None:
    url = "https://example.test/StructureDefinition/notRegistered"

    with pytest.raises(UnknownExtension) as raised:
        to_graph(
            {
                "resourceType": "HealthcareService",
                "id": SVC_ID,
                "extension": [{"url": url, "valueString": "x"}],
            }
        )

    assert raised.value.url == url
    assert isinstance(raised.value, UnsupportedElement)


def test_a_complex_extension_value_is_refused_not_dropped() -> None:
    resource = {
        "resourceType": "HealthcareService",
        "id": SVC_ID,
        "extension": [{"url": _url("establishedCapacity"), "valueCodeableConcept": {"text": "8"}}],
    }

    with pytest.raises(UnsupportedElement):
        to_graph(resource)


def test_an_extension_with_an_extra_key_is_refused() -> None:
    extension = {**_extension("establishedCapacity", 8), "id": "x"}

    with pytest.raises(UnsupportedElement):
        to_graph(_service_with(extension))


@pytest.mark.parametrize(
    ("short_name", "value"),
    [
        ("establishedCapacity", "8"),
        ("establishedCapacity", True),
        ("canExceedEstablished", "false"),
        ("canExceedEstablished", 1),
        ("limitedLevelPercent", False),
        ("geocodedAt", 20261025),
    ],
)
def test_an_extension_value_of_the_wrong_registered_type_is_refused(
    short_name: str, value: Any
) -> None:
    extension = {"url": _url(short_name), _VALUE_KEY[REGISTERED_TYPES[short_name]]: value}

    with pytest.raises(ValidationFailed):
        to_graph(_service_with(extension))


def test_a_value_key_that_does_not_match_the_registered_type_is_refused() -> None:
    extension = {"url": _url("establishedCapacity"), "valueString": "8"}

    with pytest.raises(DomainError):
        to_graph(_service_with(extension))


def test_the_same_extension_twice_is_refused() -> None:
    resource = _service_with(
        _extension("establishedCapacity", 8), _extension("establishedCapacity", 9)
    )

    with pytest.raises(ValidationFailed):
        to_graph(resource)


@pytest.mark.parametrize("value", [[], {"url": _url("establishedCapacity"), "valueInteger": 8}])
def test_extension_must_be_a_non_empty_list(value: Any) -> None:
    with pytest.raises(UnsupportedElement):
        to_graph({"resourceType": "HealthcareService", "id": SVC_ID, "extension": value})


def test_several_extensions_keep_their_order_exactly() -> None:
    resource = _service_with(
        _extension("usualRangeMax", 6),
        _extension("establishedCapacity", 8),
        _extension("smsShortName", "UCRW"),
    )

    fragment = to_graph(resource)

    assert _root(fragment)["extensionOrder"] == [
        "usualRangeMax",
        "establishedCapacity",
        "smsShortName",
    ]
    assert from_graph(fragment) == resource


def test_a_single_extension_has_no_extension_order_property() -> None:
    assert "extensionOrder" not in _root(
        to_graph(_service_with(_extension("uprn", "100000000001")))
    )


def test_rebuild_refuses_an_extension_property_that_is_not_registered() -> None:
    fragment = to_graph(_service_with(_extension("establishedCapacity", 8)))
    root = fragment.nodes[0]
    tampered = NodeSpec(
        key=root.key, labels=root.labels, properties={**root.properties, "ext_notRegistered": 1}
    )
    broken = GraphFragment(
        root_key=fragment.root_key, nodes=(tampered, *fragment.nodes[1:]), rels=fragment.rels
    )

    with pytest.raises(ValidationFailed):
        from_graph(broken)


def test_rebuild_refuses_several_extensions_without_an_order() -> None:
    fragment = to_graph(
        _service_with(_extension("establishedCapacity", 8), _extension("usualRangeMin", 2))
    )
    root = fragment.nodes[0]
    without_order = {k: v for k, v in root.properties.items() if k != "extensionOrder"}
    broken = GraphFragment(
        root_key=fragment.root_key,
        nodes=(
            NodeSpec(key=root.key, labels=root.labels, properties=without_order),
            *fragment.nodes[1:],
        ),
        rels=fragment.rels,
    )

    with pytest.raises(ValidationFailed):
        from_graph(broken)


# Names the extension mapping reserves


@pytest.mark.parametrize(
    ("element", "value"),
    [
        ("ext", {"value": 1}),
        ("extensionOrder", ["establishedCapacity"]),
        ("positionLatitude", 50.61),
        ("positionLongitude", -2.45),
    ],
)
def test_a_top_level_name_the_extension_mapping_uses_is_refused(element: str, value: Any) -> None:
    resource = {"resourceType": "Location", "id": LOC_ID, element: value}

    with pytest.raises(ValidationFailed) as raised:
        to_graph(resource)

    assert raised.value.field == element


# Extensions used by the registration flow, and graph safety


def test_a_location_with_geocoding_extensions_round_trips() -> None:
    resource = {
        "resourceType": "Location",
        "id": LOC_ID,
        "status": "active",
        "name": "Example Site",
        "position": {"latitude": 50.61, "longitude": -2.45},
        "extension": [
            _extension("geocodeSource", "postcode-centroid"),
            _extension("geocodedAt", "2026-10-25T09:30:00+01:00"),
            _extension("uprn", "100000000001"),
        ],
    }

    fragment = to_graph(resource)

    assert from_graph(fragment) == resource


def test_observation_report_type_and_referrer_type_round_trip() -> None:
    observation = {
        "resourceType": "Observation",
        "id": OBS_ID,
        "status": "final",
        "extension": [_extension("reportType", "confirmed")],
    }
    referral = {
        "resourceType": "ServiceRequest",
        "id": "a1b2c3d4-0000-4000-8000-00000000000a",
        "status": "active",
        "extension": [_extension("referrerType", "gp")],
    }

    assert from_graph(to_graph(observation)) == observation
    assert from_graph(to_graph(referral)) == referral


def test_extension_values_are_primitives_and_the_order_list_holds_strings() -> None:
    fragment = to_graph(
        _service_with(_extension("usualRangeMax", 6), _extension("establishedCapacity", 8))
    )

    props = _root(fragment)
    assert all(isinstance(value, str) for value in props["extensionOrder"])
    assert not any(isinstance(value, dict) for value in props.values())


def test_an_extension_on_a_backbone_child_is_kept_on_that_child() -> None:
    resource = {
        "resourceType": "HealthcareService",
        "id": SVC_ID,
        "availableTime": [
            {
                "daysOfWeek": ["mon"],
                "extension": [_extension("usualRangeMin", 1)],
            }
        ],
    }

    fragment = to_graph(resource)

    child = next(node for node in fragment.nodes if node.key == f"{SVC_KEY}#availableTime[0]")
    assert child.properties["ext_usualRangeMin"] == 1
    assert from_graph(fragment) == resource


@pytest.mark.parametrize(
    "entry",
    [
        "not-an-object",
        {"url": 5, "valueInteger": 1},
        {"valueInteger": 1},
        {"url": ["https://example.test/x"], "valueInteger": 1},
    ],
)
def test_an_extension_entry_without_an_object_and_text_url_is_refused(entry: Any) -> None:
    with pytest.raises(UnsupportedElement) as raised:
        to_graph(_service_with(entry))

    # Exact type: UnknownExtension is a subclass, so a plain isinstance check would hide a guard
    # that has been removed. Without the text-url guard, the list url raises TypeError and
    # the integer and missing urls raise UnknownExtension.
    assert type(raised.value) is UnsupportedElement


def test_a_decimal_extension_accepts_numbers_and_refuses_text_and_booleans() -> None:
    url = f"{BASE_URL}StructureDefinition/decimalTest"
    try:
        register_extension(ExtensionDef(url=url, short_name="decimalTest", value_type="decimal"))
        ok = _service_with({"url": url, "valueDecimal": 2.5})
        assert from_graph(to_graph(ok)) == ok
        for bad in ("2.5", True):
            with pytest.raises(ValidationFailed):
                to_graph(_service_with({"url": url, "valueDecimal": bad}))
    finally:
        EXTENSIONS.pop(url, None)


def test_rebuild_refuses_an_order_that_names_other_extensions() -> None:
    fragment = to_graph(
        _service_with(_extension("establishedCapacity", 8), _extension("uprn", "100000000001"))
    )
    root = fragment.nodes[0]
    wrong_order = {**root.properties, "extensionOrder": ["establishedCapacity", "smsShortName"]}
    broken = GraphFragment(
        root_key=fragment.root_key,
        nodes=(
            NodeSpec(key=root.key, labels=root.labels, properties=wrong_order),
            *fragment.nodes[1:],
        ),
        rels=fragment.rels,
    )

    with pytest.raises(ValidationFailed):
        from_graph(broken)


def test_rebuild_refuses_an_unregistered_extension_when_there_is_no_order() -> None:
    fragment = to_graph(_service_with(_extension("uprn", "100000000001")))
    root = fragment.nodes[0]
    renamed = {"ext_notRegistered": root.properties["ext_uprn"], "id": root.properties["id"]}
    broken = GraphFragment(
        root_key=fragment.root_key,
        nodes=(NodeSpec(key=root.key, labels=root.labels, properties=renamed), *fragment.nodes[1:]),
        rels=fragment.rels,
    )

    with pytest.raises(ValidationFailed):
        from_graph(broken)


def test_rebuild_refuses_an_order_without_any_extension() -> None:
    broken = GraphFragment(
        root_key="HealthcareService/r1",
        nodes=(
            NodeSpec(
                key="HealthcareService/r1",
                labels=("Resource", "HealthcareService"),
                properties={"id": "r1", "extensionOrder": ["uprn"]},
            ),
        ),
        rels=(),
    )

    with pytest.raises(ValidationFailed):
        from_graph(broken)


def test_rebuild_refuses_a_property_that_is_also_a_relationship() -> None:
    fragment = to_graph({"resourceType": "HealthcareService", "id": SVC_ID})
    root = fragment.nodes[0]
    clash = GraphFragment(
        root_key=fragment.root_key,
        nodes=(
            NodeSpec(
                key=root.key,
                labels=root.labels,
                properties={**root.properties, "location": ["x"]},
            ),
            *fragment.nodes[1:],
        ),
        rels=(
            RelSpec(
                type="LOCATION",
                start=root.key,
                end="Location/l1",
                properties={"fhirPath": "HealthcareService.location"},
            ),
        ),
    )

    with pytest.raises(ValidationFailed):
        from_graph(clash)


# TEN-008 (DEC-162): an extension cannot stand in for the tenant stamp.

_TENANT_NAMES = ("tenantId", "sourceTenantId")


@pytest.mark.parametrize("short_name", _TENANT_NAMES)
def test_an_extension_may_not_be_registered_under_a_tenant_name(short_name: str) -> None:
    try:
        with pytest.raises(ValueError, match="reserved"):
            register_extension(
                ExtensionDef(url=_url(short_name), short_name=short_name, value_type="string")
            )
    finally:
        # Even a failing run must not leave the name registered for the tests that follow.
        EXTENSIONS.pop(_url(short_name), None)


def test_the_registry_holds_no_extension_named_for_a_tenant() -> None:
    assert not {defn.short_name for defn in EXTENSIONS.values()} & TENANT_OWNED_NAMES
    assert not {defn.property_name for defn in EXTENSIONS.values()} & TENANT_OWNED_NAMES


@pytest.mark.parametrize("short_name", _TENANT_NAMES)
@pytest.mark.parametrize(
    ("value_key", "value"),
    [("valueString", "tenant-b"), ("valueInteger", 7), ("valueBoolean", True)],
)
def test_a_resource_with_a_tenant_extension_is_refused_and_nothing_is_mapped(
    short_name: str, value_key: str, value: Any
) -> None:
    resource = _service_with({"url": _url(short_name), value_key: value})

    with pytest.raises(UnknownExtension) as raised:
        to_graph(resource)

    assert raised.value.url == _url(short_name)


@pytest.mark.parametrize("short_name", _TENANT_NAMES)
def test_a_tenant_extension_beside_valid_ones_still_refuses_the_whole_resource(
    short_name: str,
) -> None:
    resource = _service_with(
        _extension("smsShortName", "UCRW"),
        {"url": _url(short_name), "valueString": "tenant-b"},
    )

    with pytest.raises(UnknownExtension):
        to_graph(resource)


@pytest.mark.parametrize("short_name", _TENANT_NAMES)
def test_a_stored_ext_property_named_for_a_tenant_is_refused_on_rebuild(short_name: str) -> None:
    fragment = to_graph(_service_with(_extension("smsShortName", "UCRW")))
    root = fragment.nodes[0]
    stored = GraphFragment(
        fragment.root_key,
        (NodeSpec(root.key, root.labels, {**root.properties, f"ext_{short_name}": "tenant-b"}),),
        fragment.rels,
    )

    with pytest.raises(ValidationFailed):
        from_graph(stored)


def test_a_stamped_node_with_extensions_rebuilds_the_extensions_and_not_the_stamp() -> None:
    resource = _service_with(
        _extension("smsShortName", "UCRW"), _extension("establishedCapacity", 8)
    )
    fragment = to_graph(resource)
    root = fragment.nodes[0]
    stamped = GraphFragment(
        fragment.root_key,
        (NodeSpec(root.key, root.labels, {**root.properties, "tenantId": "tenant-a"}),),
        fragment.rels,
    )

    assert from_graph(stamped) == resource
