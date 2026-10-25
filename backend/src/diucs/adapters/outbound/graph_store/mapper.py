"""FHIR R4B resource to property-graph mapper (rules R1 to R3, R5 to R7, R11 of fhir-data-model.md).

Pure: no I/O, no neo4j import. G05 writes the fragment to Neo4j.

DEC-001: no `json` property. A resource is rebuilt from its decomposed properties and
relationships, never from a serialised copy. Every value is a primitive, a list of primitives
or a relationship, so the fragment is always storable as Neo4j properties.

DEC-049 and DEC-051: lossless or refused. Each element either round-trips exactly or raises a
DomainError. Nothing is dropped, overwritten or moved.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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
_CODEABLE_KEYS = frozenset({"coding", "text"})
_CODING_KEYS = frozenset({"system", "code", "display", "version", "userSelected"})
_IDENTIFIER_KEYS = frozenset({"system", "value", "use"})
_PERIOD_KEYS = frozenset({"start", "end"})
_RANGE_KEYS = frozenset({"low", "high"})
_QUANTITY_KEYS = frozenset({"value", "unit", "system", "code"})
_START, _END = "Start", "End"


class UnsupportedElement(DomainError):
    """An element the mapper does not represent yet. Rejected, never dropped."""

    def __init__(self, path: str) -> None:
        super().__init__(f"unsupported element: {path}")
        self.path = path


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


@dataclass(slots=True)
class _Mapping:
    """Accumulates one resource's root properties, relationships and shared nodes."""

    root_key: str
    resource_type: str
    properties: dict[str, Any]
    rels: list[RelSpec] = field(default_factory=list)
    shared: dict[str, NodeSpec] = field(default_factory=dict)

    def path(self, element: str) -> str:
        return f"{self.resource_type}.{element}"

    def share(self, node: NodeSpec, field_name: str) -> None:
        """Keep one copy of a shared node; the same key with other details is refused."""
        existing = self.shared.get(node.key)
        if existing is None:
            self.shared[node.key] = node
        elif existing != node:
            raise ValidationFailed(field_name, "the same code or identifier is given two ways")

    def set_ods_code(self, value: str) -> None:
        current = self.properties.get(_ODS_CODE_PROPERTY)
        if current is not None and current != value:
            raise ValidationFailed(_IDENTIFIER_ELEMENT, "more than one ODS organisation code")
        self.properties[_ODS_CODE_PROPERTY] = value


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
    mapping = _Mapping(
        root_key=root_key,
        resource_type=resource_type,
        properties={
            "id": resource_id,
            "iri": f"{BASE_URL}fhir/{resource_type}/{resource_id}",
        },
    )

    # Sorted, so two dicts that differ only in key order give equal fragments.
    for element, value in sorted(resource.items()):
        if element in _ROOT_KEYS:
            continue
        _check_element_name(element)
        if element == "meta":
            mapping.properties.update(_meta(mapping.path(element), value))
        else:
            _map_element(mapping, element, value)

    node = NodeSpec(key=root_key, labels=("Resource", resource_type), properties=mapping.properties)
    return GraphFragment(
        root_key=root_key,
        nodes=(node, *mapping.shared.values()),
        rels=tuple(mapping.rels),
    )


def from_graph(fragment: GraphFragment) -> dict[str, Any]:
    """Rebuild the FHIR resource from the root node's properties and its relationships."""
    root = next((node for node in fragment.nodes if node.key == fragment.root_key), None)
    if root is None:
        raise NotFound(fragment.root_key)
    nodes = {node.key: node for node in fragment.nodes}

    resource_type = next(label for label in root.labels if label != "Resource")
    props = dict(root.properties)
    props.pop("iri", None)
    resource: dict[str, Any] = {"resourceType": resource_type, "id": props.pop("id")}

    meta = {key: props.pop(key) for key in sorted(_META_KEYS) if key in props}
    if meta:
        resource["meta"] = meta

    for name in _COPIED_NAMES:
        props.pop(name, None)
    for name, value in props.items():
        _rebuild_property(resource, name, value)

    by_element: dict[str, list[RelSpec]] = {}
    for rel in fragment.rels:
        if rel.start == fragment.root_key:
            element = rel.properties["fhirPath"].split(".", 1)[1]
            by_element.setdefault(element, []).append(rel)

    for element, rels in by_element.items():
        resource[element] = _rebuild_element(element, rels, nodes)

    return resource


# Checks and classification


def _check_element_name(element: str) -> None:
    if element in _NODE_OWNED_NAMES:
        # The node already uses this name; storing it too would overwrite or move it.
        raise ValidationFailed(element, "reserved: the mapper stores this on the node itself")
    if element in _COPIED_NAMES:
        raise ValidationFailed(element, "reserved: a copied property")
    if "_" in element:
        raise ValidationFailed(element, "reserved: underscore is used by flattened names")
    if element.endswith((_START, _END)):
        raise ValidationFailed(element, "reserved: Start and End are used by periods")


def _map_element(mapping: _Mapping, element: str, value: Any) -> None:
    path = mapping.path(element)
    if isinstance(value, list):
        _map_list(mapping, element, path, value)
    else:
        _map_single(mapping, element, path, value)
    _copy_filter_code(mapping, element, value)


def _map_list(mapping: _Mapping, element: str, path: str, value: list[Any]) -> None:
    if not value:
        raise UnsupportedElement(path)
    if all(_is_primitive(item) for item in value):
        mapping.properties[element] = list(value)
    elif all(_is_reference(item) for item in value):
        for order, item in enumerate(value):
            mapping.rels.append(_reference_rel(mapping.root_key, path, element, item, order))
    elif all(_is_codeable(item) for item in value):
        for concept_order, item in enumerate(value):
            _concept_rels(mapping, element, path, item, concept_order)
    elif element == _IDENTIFIER_ELEMENT and all(isinstance(item, dict) for item in value):
        for order, item in enumerate(value):
            _identifier_rel(mapping, path, item, order)
    else:
        raise UnsupportedElement(path)


def _map_single(mapping: _Mapping, element: str, path: str, value: Any) -> None:
    if _is_primitive(value):
        mapping.properties[element] = value
    elif _is_reference(value):
        mapping.rels.append(_reference_rel(mapping.root_key, path, element, value, None))
    elif _is_codeable(value):
        _concept_rels(mapping, element, path, value, None)
    elif element == _IDENTIFIER_ELEMENT and isinstance(value, dict):
        _identifier_rel(mapping, path, value, None)
    elif _is_shape(value, _PERIOD_KEYS):
        _flatten_period(mapping, element, path, value)
    elif _is_shape(value, _RANGE_KEYS):
        _flatten_range(mapping, element, path, value)
    elif _is_shape(value, _QUANTITY_KEYS):
        _flatten_quantity(mapping, path, element, value)
    else:
        raise UnsupportedElement(path)


def _copy_filter_code(mapping: _Mapping, element: str, value: Any) -> None:
    """R11: copy the first code of a frequently filtered CodeableConcept to a property."""
    property_name = FILTER_CODE_PROPERTIES.get((mapping.resource_type, element))
    if property_name is None:
        return
    concept = value[0] if isinstance(value, list) and value else value
    if _is_codeable(concept):
        mapping.properties[property_name] = concept["coding"][0]["code"]


# Concepts (R5), identifiers (R6), periods, quantities and ranges (R7)


def _concept_rels(
    mapping: _Mapping, element: str, path: str, concept: Any, concept_order: int | None
) -> None:
    codings = concept.get("coding")
    if not isinstance(codings, list) or not codings:
        raise UnsupportedElement(path)
    text = concept.get("text")
    if "text" in concept and not isinstance(text, str):
        raise UnsupportedElement(path)
    for order, coding in enumerate(codings):
        _coding_rel(mapping, element, path, coding, order, concept_order, text)


def _coding_rel(
    mapping: _Mapping,
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
    mapping.rels.append(RelSpec(upper_snake(element), mapping.root_key, concept_key, rel_props))


def _identifier_rel(mapping: _Mapping, path: str, identifier: Any, order: int | None) -> None:
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
    mapping.rels.append(RelSpec("IDENTIFIED_BY", mapping.root_key, key, rel_props))
    if system == ODS_ORG_SYSTEM:
        mapping.set_ods_code(value)


def _flatten_period(mapping: _Mapping, element: str, path: str, period: dict[str, Any]) -> None:
    for name, suffix in (("start", _START), ("end", _END)):
        if name in period:
            mapping.properties[f"{element}{suffix}"] = _text(path, period[name])


def _flatten_range(mapping: _Mapping, element: str, path: str, value: dict[str, Any]) -> None:
    for name in ("low", "high"):
        if name in value:
            if not _is_shape(value[name], _QUANTITY_KEYS):
                raise UnsupportedElement(path)
            _flatten_quantity(mapping, path, f"{element}_{name}", value[name])


def _flatten_quantity(mapping: _Mapping, path: str, prefix: str, quantity: dict[str, Any]) -> None:
    for name, item in quantity.items():
        if not _is_primitive(item):
            raise UnsupportedElement(path)
        mapping.properties[f"{prefix}_{name}"] = item


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


def _rebuild_property(resource: dict[str, Any], name: str, value: Any) -> None:
    if name.endswith(_START):
        resource.setdefault(name[: -len(_START)], {})["start"] = value
    elif name.endswith(_END):
        resource.setdefault(name[: -len(_END)], {})["end"] = value
    elif "_" in name:
        parts = name.split("_")
        if len(parts) == 2:
            resource.setdefault(parts[0], {})[parts[1]] = value
        elif len(parts) == 3:
            resource.setdefault(parts[0], {}).setdefault(parts[1], {})[parts[2]] = value
        else:
            raise ValidationFailed(name, "unknown flattened property")
    else:
        resource[name] = list(value) if isinstance(value, list) else value


def _rebuild_element(element: str, rels: list[RelSpec], nodes: dict[str, NodeSpec]) -> Any:
    kinds = {_kind(rel.end) for rel in rels}
    if len(kinds) > 1:
        raise ValidationFailed(element, "mixed kinds of value")
    kind = kinds.pop()
    if kind == "concept":
        return _rebuild_concepts(element, rels, nodes)
    if kind == "identifier":
        return _ordered_or_single(
            element, rels, lambda rel: _identifier_dict(rel, _node_for(nodes, rel.end))
        )
    return _ordered_or_single(element, rels, _reference_dict)


def _kind(end: str) -> str:
    if end.startswith(_CONCEPT_PREFIX):
        return "concept"
    if end.startswith(_IDENTIFIER_PREFIX):
        return "identifier"
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
    root_key: str, path: str, element: str, reference: dict[str, Any], order: int | None
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
    return RelSpec(type=upper_snake(element), start=root_key, end=target, properties=properties)


def _target_key(path: str, reference: Any) -> str:
    if not isinstance(reference, str) or reference.count("/") != 1:
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
