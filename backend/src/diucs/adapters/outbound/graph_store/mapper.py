"""FHIR R4B resource to property-graph mapper (rules R1 to R3 of fhir-data-model.md).

Pure: no I/O, no neo4j import. G05 writes the fragment to Neo4j.

DEC-001: no `json` property. A resource is rebuilt from its decomposed properties and
relationships, never from a serialised copy. Every value is a primitive, a list of primitives
or a relationship, so the fragment is always storable as Neo4j properties.
"""

import re
from dataclasses import dataclass
from typing import Any

from diucs.domain.codes import BASE_URL
from diucs.domain.errors import DomainError, NotFound, ValidationFailed

_PRIMITIVE_TYPES = (str, bool, int, float)
_REFERENCE_KEYS = frozenset({"reference", "display"})
_META_KEYS = frozenset({"versionId", "lastUpdated"})
_ROOT_KEYS = frozenset({"resourceType", "id"})
_NODE_OWNED_NAMES = frozenset({"iri", "versionId", "lastUpdated"})
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


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


def upper_snake(name: str) -> str:
    """providedBy -> PROVIDED_BY, partOf -> PART_OF."""
    return _CAMEL_BOUNDARY.sub("_", name).upper()


def to_graph(resource: dict[str, Any]) -> GraphFragment:
    """Decompose one FHIR resource into a node and one relationship per reference."""
    resource_type = resource.get("resourceType")
    resource_id = resource.get("id")
    if not isinstance(resource_type, str) or not resource_type:
        raise ValidationFailed("resourceType", "required")
    if not isinstance(resource_id, str) or not resource_id:
        raise ValidationFailed("id", "required")

    root_key = f"{resource_type}/{resource_id}"
    properties: dict[str, Any] = {
        "id": resource_id,
        "iri": f"{BASE_URL}fhir/{resource_type}/{resource_id}",
    }
    rels: list[RelSpec] = []

    # Sorted, so two dicts that differ only in key order give equal fragments.
    for element, value in sorted(resource.items()):
        if element in _ROOT_KEYS:
            continue
        if element in _NODE_OWNED_NAMES:
            # The node already uses this name; storing it too would overwrite or move it.
            raise ValidationFailed(element, "reserved: the mapper stores this on the node itself")
        path = f"{resource_type}.{element}"
        if element == "meta":
            properties.update(_meta(path, value))
        elif isinstance(value, list):
            if not value:
                raise UnsupportedElement(path)
            if all(_is_primitive(item) for item in value):
                properties[element] = list(value)
            elif all(_is_reference(item) for item in value):
                for order, item in enumerate(value):
                    rels.append(_reference_rel(root_key, path, element, item, order))
            else:
                raise UnsupportedElement(path)
        elif _is_primitive(value):
            properties[element] = value
        elif _is_reference(value):
            rels.append(_reference_rel(root_key, path, element, value, None))
        else:
            raise UnsupportedElement(path)

    node = NodeSpec(key=root_key, labels=("Resource", resource_type), properties=properties)
    return GraphFragment(root_key=root_key, nodes=(node,), rels=tuple(rels))


def from_graph(fragment: GraphFragment) -> dict[str, Any]:
    """Rebuild the FHIR resource from the root node's properties and its relationships."""
    root = next((node for node in fragment.nodes if node.key == fragment.root_key), None)
    if root is None:
        raise NotFound(fragment.root_key)

    resource_type = next(label for label in root.labels if label != "Resource")
    props = dict(root.properties)
    props.pop("iri", None)
    resource: dict[str, Any] = {"resourceType": resource_type, "id": props.pop("id")}

    meta = {key: props.pop(key) for key in sorted(_META_KEYS) if key in props}
    if meta:
        resource["meta"] = meta

    for element, value in props.items():
        resource[element] = list(value) if isinstance(value, list) else value

    by_element: dict[str, list[RelSpec]] = {}
    for rel in fragment.rels:
        if rel.start == fragment.root_key:
            element = rel.properties["fhirPath"].split(".", 1)[1]
            by_element.setdefault(element, []).append(rel)

    for element, rels in by_element.items():
        if any("order" in rel.properties for rel in rels):
            ordered = sorted(rels, key=lambda rel: rel.properties["order"])
            resource[element] = [_reference_dict(rel) for rel in ordered]
        else:
            if len(rels) != 1:
                raise ValidationFailed(element, "single-valued element has several references")
            resource[element] = _reference_dict(rels[0])

    return resource


def _is_primitive(value: Any) -> bool:
    return isinstance(value, _PRIMITIVE_TYPES)


def _is_reference(value: Any) -> bool:
    return isinstance(value, dict) and "reference" in value and set(value) <= _REFERENCE_KEYS


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
    if not target_type or not target_id:
        raise InvalidReference(path)
    return f"{target_type}/{target_id}"


def _reference_dict(rel: RelSpec) -> dict[str, Any]:
    reference: dict[str, Any] = {"reference": rel.end}
    if "display" in rel.properties:
        reference["display"] = rel.properties["display"]
    return reference
