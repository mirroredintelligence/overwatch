"""FHIR R4B resource to property-graph mapper (rules R1 to R8, R11 of fhir-data-model.md).

Pure: no I/O, no neo4j import. G05 writes the fragment to Neo4j.

DEC-001: no `json` property. A resource is rebuilt from its decomposed properties and
relationships, never from a serialised copy. Every value is a primitive, a list of primitives
or a relationship, so the fragment is always storable as Neo4j properties.

DEC-049 and DEC-051: lossless or refused. Each element either round-trips exactly or raises a
DomainError. Nothing is dropped, overwritten or moved.

G04 (rules R4 and R8): a repeating or multi-part backbone element is a child node keyed
`<parentKey>#<element>[<index>]`; a registered extension is the property `ext_<shortName>`.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from diucs.adapters.outbound.graph_store.extensions import (
    EXTENSIONS,
    PROPERTY_PREFIX,
    by_short_name,
)
from diucs.domain.codes import BASE_URL
from diucs.domain.errors import DomainError, NotFound, ValidationFailed

_PRIMITIVE_TYPES = (str, bool, int, float)
_REFERENCE_KEYS = frozenset({"reference", "display"})
_META_KEYS = frozenset({"versionId", "lastUpdated"})
_ROOT_KEYS = frozenset({"resourceType", "id"})
_NODE_OWNED_NAMES = frozenset({"iri", "versionId", "lastUpdated"})
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# VERIFY against NHS England FHIR docs: the ODS system URIs are unverified (see G03 prompt).
ODS_ORG_SYSTEM = "https://fhir.nhs.uk/Id/ods-organization-code"
ODS_SITE_SYSTEM = "https://fhir.nhs.uk/Id/ods-site-code"
# Frequently filtered codes, copied to a property (R11): (resource type, element) -> property.
FILTER_CODE_PROPERTIES: dict[tuple[str, str], str] = {("Observation", "code"): "measureCode"}

_ODS_CODE_PROPERTY = "odsCode"
_COPIED_NAMES = frozenset({_ODS_CODE_PROPERTY, *FILTER_CODE_PROPERTIES.values()})
_IDENTIFIER_ELEMENT = "identifier"
_CONCEPT_PREFIX = "Concept|"
_IDENTIFIER_PREFIX = "Identifier|"
_CODE_SYSTEM_PREFIX = "CodeSystem|"
_KEY_SEPARATOR = "|"
_CHILD_SEPARATOR = "#"
_CODEABLE_KEYS = frozenset({"coding", "text"})
_CODING_KEYS = frozenset({"system", "code", "display", "version", "userSelected"})
_IDENTIFIER_KEYS = frozenset({"system", "value", "use"})
_PERIOD_KEYS = frozenset({"start", "end"})
_RANGE_KEYS = frozenset({"low", "high"})
_QUANTITY_KEYS = frozenset({"value", "unit", "system", "code"})
_START, _END = "Start", "End"

_EXTENSION_ELEMENT = "extension"
_EXTENSION_URL = "url"
_EXTENSION_ORDER = "extensionOrder"
_POSITION_ELEMENT = "position"
_POSITION_PROPERTIES: dict[str, str] = {
    "latitude": "positionLatitude",
    "longitude": "positionLongitude",
}
_POSITION_ELEMENTS: dict[str, str] = {prop: name for name, prop in _POSITION_PROPERTIES.items()}
# Top-level names the mapper uses for its own properties. A FHIR element with one of these names
# would be read back as an extension, a position or the order list, so it is refused.
_MAPPER_NAMES = frozenset({"ext", _EXTENSION_ORDER, *_POSITION_PROPERTIES.values()})


class UnsupportedElement(DomainError):
    """An element the mapper does not represent yet. Rejected, never dropped."""

    def __init__(self, path: str) -> None:
        super().__init__(f"unsupported element: {path}")
        self.path = path


class UnknownExtension(UnsupportedElement):
    """An extension URL that is not in the registry. Rejected, never dropped."""

    def __init__(self, url: str, path: str = "extension") -> None:
        super().__init__(path)
        self.url = url


class InvalidReference(DomainError):
    """A reference that is not a relative Type/id reference."""

    def __init__(self, path: str) -> None:
        super().__init__(f"invalid reference: {path}")
        self.path = path


@dataclass(frozen=True, slots=True)
class NodeSpec:
    key: str
    labels: tuple[str, ...]
    properties: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RelSpec:
    type: str
    start: str
    end: str
    properties: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GraphFragment:
    root_key: str
    nodes: tuple[NodeSpec, ...]
    rels: tuple[RelSpec, ...]


@dataclass(frozen=True, slots=True)
class BackboneDef:
    """A backbone element (R4): the child node's label and the catalogue relationship to it."""

    label: str
    relation: str


# Keyed by (FHIR path of the owner, element). "Organization.contact" is the contact child of an
# Organization. An element not listed here is refused, never guessed.
_BACKBONE: dict[tuple[str, str], BackboneDef] = {
    ("HealthcareService", "availableTime"): BackboneDef(
        "HealthcareService_AvailableTime", "HAS_AVAILABLE_TIME"
    ),
    ("HealthcareService", "notAvailable"): BackboneDef(
        "HealthcareService_NotAvailable", "HAS_NOT_AVAILABLE"
    ),
    ("HealthcareService", "eligibility"): BackboneDef(
        "HealthcareService_Eligibility", "HAS_ELIGIBILITY"
    ),
    ("HealthcareService", "telecom"): BackboneDef("ContactPoint", "HAS_TELECOM"),
    ("Location", "address"): BackboneDef("Address", "HAS_ADDRESS"),
    ("Location", "hoursOfOperation"): BackboneDef("Location_HoursOfOperation", "HAS_HOURS"),
    ("Location", "telecom"): BackboneDef("ContactPoint", "HAS_TELECOM"),
    ("Organization", "address"): BackboneDef("Address", "HAS_ADDRESS"),
    ("Organization", "contact"): BackboneDef("Organization_Contact", "HAS_CONTACT"),
    ("Organization", "telecom"): BackboneDef("ContactPoint", "HAS_TELECOM"),
    ("Organization.contact", "address"): BackboneDef("Address", "HAS_ADDRESS"),
    ("Organization.contact", "telecom"): BackboneDef("ContactPoint", "HAS_TELECOM"),
}


@dataclass(slots=True)
class _Owner:
    """A node being mapped: the resource itself, or one backbone child of it."""

    key: str
    path: str
    properties: dict[str, Any]
    is_root: bool

    def set_ods_code(self, value: str) -> None:
        current = self.properties.get(_ODS_CODE_PROPERTY)
        if current is not None and current != value:
            raise ValidationFailed(_IDENTIFIER_ELEMENT, "more than one ODS organisation code")
        self.properties[_ODS_CODE_PROPERTY] = value


@dataclass(slots=True)
class _Mapping:
    """Accumulates one resource's relationships, backbone children and shared concept nodes."""

    rels: list[RelSpec] = field(default_factory=list)
    children: list[NodeSpec] = field(default_factory=list)
    shared: dict[str, NodeSpec] = field(default_factory=dict)

    def share(self, node: NodeSpec, field_name: str) -> None:
        """Keep one copy of a shared node; the same key with other details is refused."""
        existing = self.shared.get(node.key)
        if existing is None:
            self.shared[node.key] = node
        elif existing != node:
            raise ValidationFailed(field_name, "the same code or identifier is given two ways")


def upper_snake(name: str) -> str:
    """providedBy -> PROVIDED_BY, partOf -> PART_OF."""
    return _CAMEL_BOUNDARY.sub("_", name).upper()


def to_graph(resource: dict[str, Any]) -> GraphFragment:
    """Decompose one FHIR resource into a node, relationships and shared concept nodes."""
    resource_type = resource.get("resourceType")
    resource_id = resource.get("id")
    if not isinstance(resource_type, str) or not resource_type:
        raise ValidationFailed("resourceType", "required")
    if not isinstance(resource_id, str) or not resource_id:
        raise ValidationFailed("id", "required")

    root_key = f"{resource_type}/{resource_id}"
    mapping = _Mapping()
    root = _Owner(
        key=root_key,
        path=resource_type,
        properties={
            "id": resource_id,
            "iri": f"{BASE_URL}fhir/{resource_type}/{resource_id}",
        },
        is_root=True,
    )

    # Sorted, so two dicts that differ only in key order give equal fragments.
    for element, value in sorted(resource.items()):
        if element in _ROOT_KEYS:
            continue
        _check_element_name(element)
        if element == "meta":
            root.properties.update(_meta(f"{resource_type}.meta", value))
        else:
            _map_element(mapping, root, element, value)

    node = NodeSpec(key=root_key, labels=("Resource", resource_type), properties=root.properties)
    return GraphFragment(
        root_key=root_key,
        nodes=(node, *mapping.children, *mapping.shared.values()),
        rels=tuple(mapping.rels),
    )


def from_graph(fragment: GraphFragment) -> dict[str, Any]:
    """Rebuild the FHIR resource from the root node's properties and its relationships."""
    nodes = {node.key: node for node in fragment.nodes}
    root = nodes.get(fragment.root_key)
    if root is None:
        raise NotFound(fragment.root_key)

    by_start: dict[str, list[RelSpec]] = {}
    for rel in fragment.rels:
        by_start.setdefault(rel.start, []).append(rel)

    resource_type = next(label for label in root.labels if label != "Resource")
    props = dict(root.properties)
    props.pop("iri", None)
    resource: dict[str, Any] = {"resourceType": resource_type, "id": props.pop("id")}

    meta = {key: props.pop(key) for key in sorted(_META_KEYS) if key in props}
    if meta:
        resource["meta"] = meta
    for name in _COPIED_NAMES:
        props.pop(name, None)

    resource.update(_rebuild_owner(root.key, props, by_start, nodes))
    return resource


# Checks and classification


def _check_element_name(element: str) -> None:
    if element in _NODE_OWNED_NAMES:
        # The node already uses this name; storing it too would overwrite or move it.
        raise ValidationFailed(element, "reserved: the mapper stores this on the node itself")
    if element in _COPIED_NAMES:
        raise ValidationFailed(element, "reserved: a copied property")
    if element in _MAPPER_NAMES:
        raise ValidationFailed(element, "reserved: the mapper uses this name for its properties")
    if "_" in element:
        raise ValidationFailed(element, "reserved: underscore is used by flattened names")
    if element.endswith((_START, _END)):
        raise ValidationFailed(element, "reserved: Start and End are used by periods")


def _map_element(mapping: _Mapping, owner: _Owner, element: str, value: Any) -> None:
    path = f"{owner.path}.{element}"
    if element == _EXTENSION_ELEMENT:
        _map_extensions(owner, path, value)
        return
    if owner.path == "Location" and element == _POSITION_ELEMENT:
        _map_position(owner, path, value)
        return
    if (owner.path, element) in _BACKBONE:
        _map_backbone(mapping, owner, element, path, value)
        return
    if isinstance(value, list):
        _map_list(mapping, owner, element, path, value)
    else:
        _map_single(mapping, owner, element, path, value)
    _copy_filter_code(owner, element, value)


def _map_list(mapping: _Mapping, owner: _Owner, element: str, path: str, value: list[Any]) -> None:
    if not value:
        raise UnsupportedElement(path)
    if all(_is_primitive(item) for item in value):
        owner.properties[element] = list(value)
    elif all(_is_reference(item) for item in value):
        for order, item in enumerate(value):
            mapping.rels.append(_reference_rel(owner.key, path, element, item, order))
    elif all(_is_codeable(item) for item in value):
        for concept_order, item in enumerate(value):
            _concept_rels(mapping, owner, element, path, item, concept_order)
    elif (
        owner.is_root
        and element == _IDENTIFIER_ELEMENT
        and all(isinstance(item, dict) for item in value)
    ):
        for order, item in enumerate(value):
            _identifier_rel(mapping, owner, path, item, order)
    else:
        raise UnsupportedElement(path)


def _map_single(mapping: _Mapping, owner: _Owner, element: str, path: str, value: Any) -> None:
    if _is_primitive(value):
        owner.properties[element] = value
    elif _is_reference(value):
        mapping.rels.append(_reference_rel(owner.key, path, element, value, None))
    elif _is_codeable(value):
        _concept_rels(mapping, owner, element, path, value, None)
    elif owner.is_root and element == _IDENTIFIER_ELEMENT and isinstance(value, dict):
        _identifier_rel(mapping, owner, path, value, None)
    elif _is_shape(value, _PERIOD_KEYS):
        _flatten_period(owner, element, path, value)
    elif _is_shape(value, _RANGE_KEYS):
        _flatten_range(owner, element, path, value)
    elif _is_shape(value, _QUANTITY_KEYS):
        _flatten_quantity(owner, path, element, value)
    else:
        raise UnsupportedElement(path)


def _copy_filter_code(owner: _Owner, element: str, value: Any) -> None:
    """R11: copy the first code of a frequently filtered CodeableConcept to a property."""
    if not owner.is_root:
        return
    property_name = FILTER_CODE_PROPERTIES.get((owner.path, element))
    if property_name is None:
        return
    concept = value[0] if isinstance(value, list) and value else value
    if _is_codeable(concept):
        owner.properties[property_name] = concept["coding"][0]["code"]


# Backbone elements (R4)


def _map_backbone(mapping: _Mapping, owner: _Owner, element: str, path: str, value: Any) -> None:
    """A repeating or multi-part element becomes one child node per entry, keyed by its index."""
    definition = _BACKBONE[(owner.path, element)]
    if isinstance(value, list) and not value:
        raise UnsupportedElement(path)
    entries = value if isinstance(value, list) else [value]
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise UnsupportedElement(path)
        if not entry:
            raise ValidationFailed(element, "empty; omit the element instead")
        key = f"{owner.key}{_CHILD_SEPARATOR}{element}[{index}]"
        child = _Owner(key=key, path=path, properties={}, is_root=False)
        for name, item in sorted(entry.items()):
            _check_element_name(name)
            _map_element(mapping, child, name, item)
        mapping.children.append(NodeSpec(key, (definition.label,), child.properties))
        rel_props: dict[str, Any] = {"fhirPath": path}
        if isinstance(value, list):
            rel_props["order"] = index
        mapping.rels.append(RelSpec(definition.relation, owner.key, key, rel_props))


# Extensions (R8)


def _map_extensions(owner: _Owner, path: str, value: Any) -> None:
    """Each registered extension becomes ext_<shortName>. Several keep their list order."""
    if not isinstance(value, list) or not value:
        raise UnsupportedElement(path)
    names: list[str] = []
    for entry in value:
        if not isinstance(entry, dict):  # TEMPORARY: text-url guard removed for red
            raise UnsupportedElement(path)
        url = entry[_EXTENSION_URL]
        defn = EXTENSIONS.get(url)
        if defn is None:
            raise UnknownExtension(url, path)
        if set(entry) != {_EXTENSION_URL, defn.value_key}:
            raise UnsupportedElement(path)
        extension_value = entry[defn.value_key]
        if not _matches_value_type(defn.value_type, extension_value):
            raise ValidationFailed(defn.property_name, "value does not match its registered type")
        if defn.short_name in names:
            raise ValidationFailed(_EXTENSION_ELEMENT, "the same extension appears twice")
        names.append(defn.short_name)
        owner.properties[defn.property_name] = extension_value
    if len(names) > 1:
        owner.properties[_EXTENSION_ORDER] = names


def _matches_value_type(value_type: str, value: Any) -> bool:
    if value_type in ("string", "dateTime"):
        return isinstance(value, str)
    if value_type == "boolean":
        return isinstance(value, bool)
    if value_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, int | float) and not isinstance(value, bool)


def _map_position(owner: _Owner, path: str, value: Any) -> None:
    """Location.position keeps its latitude and longitude as properties (G04)."""
    if not isinstance(value, dict) or not value or not set(value) <= set(_POSITION_PROPERTIES):
        raise UnsupportedElement(path)
    for name, prop in _POSITION_PROPERTIES.items():
        if name in value:
            coordinate = value[name]
            if isinstance(coordinate, bool) or not isinstance(coordinate, int | float):
                raise UnsupportedElement(path)
            owner.properties[prop] = coordinate


# Concepts (R5), identifiers (R6), periods, quantities and ranges (R7)


def _concept_rels(
    mapping: _Mapping,
    owner: _Owner,
    element: str,
    path: str,
    concept: Any,
    concept_order: int | None,
) -> None:
    codings = concept.get("coding")
    if not isinstance(codings, list) or not codings:
        raise UnsupportedElement(path)
    text = concept.get("text")
    if "text" in concept and not isinstance(text, str):
        raise UnsupportedElement(path)
    for order, coding in enumerate(codings):
        _coding_rel(mapping, owner, element, path, coding, order, concept_order, text)


def _coding_rel(
    mapping: _Mapping,
    owner: _Owner,
    element: str,
    path: str,
    coding: Any,
    order: int,
    concept_order: int | None,
    text: str | None,
) -> None:
    if not isinstance(coding, dict) or not set(coding) <= _CODING_KEYS:
        raise UnsupportedElement(path)
    system = _key_part("system", coding.get("system"))
    code = _key_part("code", coding.get("code"))

    concept_props: dict[str, Any] = {"system": system, "code": code}
    for name in ("display", "version"):
        if name in coding:
            concept_props[name] = _text(path, coding[name])
    concept_key = f"{_CONCEPT_PREFIX}{system}{_KEY_SEPARATOR}{code}"
    mapping.share(NodeSpec(concept_key, ("Concept",), concept_props), "code")

    code_system_key = f"{_CODE_SYSTEM_PREFIX}{system}"
    mapping.share(NodeSpec(code_system_key, ("CodeSystem",), {"url": system}), "system")
    mapping.rels.append(RelSpec("IN_SYSTEM", concept_key, code_system_key, {}))

    rel_props: dict[str, Any] = {"fhirPath": path, "order": order}
    if concept_order is not None:
        rel_props["conceptOrder"] = concept_order
    if text is not None:
        rel_props["text"] = text
    if "userSelected" in coding:
        rel_props["userSelected"] = _boolean(path, coding["userSelected"])
    mapping.rels.append(RelSpec(upper_snake(element), owner.key, concept_key, rel_props))


def _identifier_rel(
    mapping: _Mapping, owner: _Owner, path: str, identifier: Any, order: int | None
) -> None:
    if not isinstance(identifier, dict) or not set(identifier) <= _IDENTIFIER_KEYS:
        raise UnsupportedElement(path)
    system = _key_part("system", identifier.get("system"))
    value = _key_part("value", identifier.get("value"))

    rel_props: dict[str, Any] = {"fhirPath": path}
    if order is not None:
        rel_props["order"] = order
    if "use" in identifier:
        rel_props["use"] = _text(path, identifier["use"])

    key = f"{_IDENTIFIER_PREFIX}{system}{_KEY_SEPARATOR}{value}"
    mapping.share(NodeSpec(key, ("Identifier",), {"system": system, "value": value}), "value")
    mapping.rels.append(RelSpec("IDENTIFIED_BY", owner.key, key, rel_props))
    if system == ODS_ORG_SYSTEM:
        owner.set_ods_code(value)


def _flatten_period(owner: _Owner, element: str, path: str, period: dict[str, Any]) -> None:
    for name, suffix in (("start", _START), ("end", _END)):
        if name in period:
            owner.properties[f"{element}{suffix}"] = _text(path, period[name])


def _flatten_range(owner: _Owner, element: str, path: str, value: dict[str, Any]) -> None:
    for name in ("low", "high"):
        if name in value:
            if not _is_shape(value[name], _QUANTITY_KEYS):
                raise UnsupportedElement(path)
            _flatten_quantity(owner, path, f"{element}_{name}", value[name])


def _flatten_quantity(owner: _Owner, path: str, prefix: str, quantity: dict[str, Any]) -> None:
    for name, item in quantity.items():
        if not _is_primitive(item):
            raise UnsupportedElement(path)
        owner.properties[f"{prefix}_{name}"] = item


def _key_part(field_name: str, value: Any) -> str:
    """A system or code that becomes part of a node key: text, not empty, no key separator."""
    if not isinstance(value, str) or not value or _KEY_SEPARATOR in value:
        raise ValidationFailed(field_name, "required: text without the | character")
    return value


def _text(path: str, value: Any) -> str:
    if not isinstance(value, str):
        raise UnsupportedElement(path)
    return value


def _boolean(path: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise UnsupportedElement(path)
    return value


# Rebuild


def _rebuild_owner(
    owner_key: str,
    props: dict[str, Any],
    by_start: dict[str, list[RelSpec]],
    nodes: dict[str, NodeSpec],
) -> dict[str, Any]:
    """The FHIR fields of one node: from its own properties, then from its relationships."""
    body: dict[str, Any] = {}
    _rebuild_extensions_and_positions(body, props)
    for name, value in props.items():
        _rebuild_property(body, name, value)

    groups: dict[str, list[RelSpec]] = {}
    for rel in by_start.get(owner_key, []):
        groups.setdefault(rel.properties["fhirPath"].rsplit(".", 1)[1], []).append(rel)
    for element, rels in groups.items():
        if element in body:
            raise ValidationFailed(element, "stored both as a property and as a relationship")
        body[element] = _rebuild_element(element, rels, by_start, nodes)
    return body


def _rebuild_extensions_and_positions(body: dict[str, Any], props: dict[str, Any]) -> None:
    """Pops the mapper's own properties (extensions, their order and positions) from props."""
    order = props.pop(_EXTENSION_ORDER, None)
    prefix_length = len(PROPERTY_PREFIX)
    extensions = {
        name[prefix_length:]: props.pop(name)
        for name in list(props)
        if name.startswith(PROPERTY_PREFIX)
    }
    if extensions:
        if order is None and len(extensions) > 1:
            raise ValidationFailed(_EXTENSION_ELEMENT, "several extensions without an order")
        names = list(order) if order is not None else list(extensions)
        if sorted(names) != sorted(extensions):
            raise ValidationFailed(_EXTENSION_ELEMENT, "order does not match the extensions")
        entries: list[dict[str, Any]] = []
        for short_name in names:
            defn = by_short_name(short_name)
            if defn is None:
                raise ValidationFailed(f"{PROPERTY_PREFIX}{short_name}", "not registered")
            entries.append({_EXTENSION_URL: defn.url, defn.value_key: extensions[short_name]})
        body[_EXTENSION_ELEMENT] = entries
    elif order is not None:
        raise ValidationFailed(_EXTENSION_ELEMENT, "an order without extensions")

    for prop, element_name in _POSITION_ELEMENTS.items():
        if prop in props:
            body.setdefault(_POSITION_ELEMENT, {})[element_name] = props.pop(prop)


def _rebuild_property(body: dict[str, Any], name: str, value: Any) -> None:
    if name.endswith(_START):
        body.setdefault(name[: -len(_START)], {})["start"] = value
    elif name.endswith(_END):
        body.setdefault(name[: -len(_END)], {})["end"] = value
    elif "_" in name:
        parts = name.split("_")
        if len(parts) == 2:
            body.setdefault(parts[0], {})[parts[1]] = value
        elif len(parts) == 3:
            body.setdefault(parts[0], {}).setdefault(parts[1], {})[parts[2]] = value
        else:
            raise ValidationFailed(name, "unknown flattened property")
    else:
        body[name] = list(value) if isinstance(value, list) else value


def _rebuild_element(
    element: str,
    rels: list[RelSpec],
    by_start: dict[str, list[RelSpec]],
    nodes: dict[str, NodeSpec],
) -> Any:
    kinds = {_kind(rel) for rel in rels}
    if len(kinds) > 1:
        raise ValidationFailed(element, "mixed kinds of value")
    kind = kinds.pop()
    if kind == "concept":
        return _rebuild_concepts(element, rels, nodes)
    if kind == "identifier":
        return _ordered_or_single(
            element, rels, lambda rel: _identifier_dict(rel, _node_for(nodes, rel.end))
        )
    if kind == "child":
        return _ordered_or_single(
            element,
            rels,
            lambda rel: _rebuild_owner(
                rel.end, dict(_node_for(nodes, rel.end).properties), by_start, nodes
            ),
        )
    return _ordered_or_single(element, rels, _reference_dict)


def _kind(rel: RelSpec) -> str:
    if rel.end.startswith(_CONCEPT_PREFIX):
        return "concept"
    if rel.end.startswith(_IDENTIFIER_PREFIX):
        return "identifier"
    if rel.end.startswith(f"{rel.start}{_CHILD_SEPARATOR}"):
        return "child"
    return "reference"


def _rebuild_concepts(element: str, rels: list[RelSpec], nodes: dict[str, NodeSpec]) -> Any:
    if not any("conceptOrder" in rel.properties for rel in rels):
        return _codeable(element, rels, nodes)
    if not all("conceptOrder" in rel.properties for rel in rels):
        raise ValidationFailed(element, "a list and a single concept are mixed")
    groups: dict[int, list[RelSpec]] = {}
    for rel in rels:
        groups.setdefault(rel.properties["conceptOrder"], []).append(rel)
    return [_codeable(element, groups[key], nodes) for key in sorted(groups)]


def _codeable(element: str, rels: list[RelSpec], nodes: dict[str, NodeSpec]) -> dict[str, Any]:
    ordered = sorted(rels, key=lambda rel: rel.properties["order"])
    texts = {rel.properties.get("text") for rel in ordered}
    if len(texts) != 1:
        raise ValidationFailed(element, "codings of one concept disagree on text")
    codings: list[dict[str, Any]] = []
    for rel in ordered:
        node = _node_for(nodes, rel.end)
        coding: dict[str, Any] = {
            "system": node.properties["system"],
            "code": node.properties["code"],
        }
        for name in ("display", "version"):
            if name in node.properties:
                coding[name] = node.properties[name]
        if "userSelected" in rel.properties:
            coding["userSelected"] = rel.properties["userSelected"]
        codings.append(coding)
    concept: dict[str, Any] = {"coding": codings}
    text = texts.pop()
    if text is not None:
        concept["text"] = text
    return concept


def _identifier_dict(rel: RelSpec, node: NodeSpec) -> dict[str, Any]:
    identifier: dict[str, Any] = {
        "system": node.properties["system"],
        "value": node.properties["value"],
    }
    if "use" in rel.properties:
        identifier["use"] = rel.properties["use"]
    return identifier


def _ordered_or_single(
    element: str, rels: list[RelSpec], build: Callable[[RelSpec], dict[str, Any]]
) -> Any:
    if any("order" in rel.properties for rel in rels):
        return [build(rel) for rel in sorted(rels, key=lambda rel: rel.properties["order"])]
    if len(rels) != 1:
        raise ValidationFailed(element, "single-valued element has several values")
    return build(rels[0])


def _node_for(nodes: dict[str, NodeSpec], key: str) -> NodeSpec:
    node = nodes.get(key)
    if node is None:
        raise NotFound(key)
    return node


# Shared checks


def _is_primitive(value: Any) -> bool:
    return isinstance(value, _PRIMITIVE_TYPES)


def _is_reference(value: Any) -> bool:
    return isinstance(value, dict) and "reference" in value and set(value) <= _REFERENCE_KEYS


def _is_codeable(value: Any) -> bool:
    return isinstance(value, dict) and "coding" in value and set(value) <= _CODEABLE_KEYS


def _is_shape(value: Any, keys: frozenset[str]) -> bool:
    return isinstance(value, dict) and bool(value) and set(value) <= keys


def _meta(path: str, meta: Any) -> dict[str, Any]:
    if not isinstance(meta, dict) or not set(meta) <= _META_KEYS:
        raise UnsupportedElement(path)
    if not meta:
        raise ValidationFailed("meta", "empty; omit the element instead")
    if not all(_is_primitive(value) for value in meta.values()):
        raise UnsupportedElement(path)
    return {key: meta[key] for key in _META_KEYS if key in meta}


def _reference_rel(
    owner_key: str, path: str, element: str, reference: dict[str, Any], order: int | None
) -> RelSpec:
    target = _target_key(path, reference["reference"])
    properties: dict[str, Any] = {"fhirPath": path}
    if order is not None:
        properties["order"] = order
    if "display" in reference:
        display = reference["display"]
        if not isinstance(display, str):
            raise UnsupportedElement(path)
        properties["display"] = display
    return RelSpec(type=upper_snake(element), start=owner_key, end=target, properties=properties)


def _target_key(path: str, reference: Any) -> str:
    # '#' is the child separator in node keys, so a reference that contains it is refused.
    if not isinstance(reference, str) or reference.count("/") != 1 or _CHILD_SEPARATOR in reference:
        raise InvalidReference(path)
    target_type, target_id = reference.split("/")
    if not target_type or not target_id or _KEY_SEPARATOR in target_type:
        raise InvalidReference(path)
    return f"{target_type}/{target_id}"


def _reference_dict(rel: RelSpec) -> dict[str, Any]:
    reference: dict[str, Any] = {"reference": rel.end}
    if "display" in rel.properties:
        reference["display"] = rel.properties["display"]
    return reference
