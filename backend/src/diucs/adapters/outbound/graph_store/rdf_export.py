"""RDF (Turtle) export of the mapper fragments (G13): the query projection of fhir-data-model.md.

The triples come from the same `GraphFragment`s the graph is written from, so the export cannot
drift from the stored data. Each element is written as the data model describes it:

- a primitive is a typed literal (`xsd:dateTime`, `xsd:date`, `xsd:time`, `xsd:integer`,
  `xsd:boolean`, `xsd:decimal`, otherwise a plain string);
- a reference is an IRI; a concept is an IRI in its code system, with `skos:notation` and
  `skos:prefLabel`;
- a backbone child is a blank node; a quantity (the mapper's flattened `valueQuantity_*`
  properties) is a blank node typed `fhir:Quantity`;
- a relationship with qualifiers is a `prov:qualifiedAssociation`; `ext_<name>` is `diucs:<name>`.

NOT VALIDATED. This is a query projection, not the official FHIR RDF serialisation (which wraps
primitives in value nodes), and it has not been checked against the FHIR ShEx schemas. Do not claim
conformance with either. Order (list position, codeable concept order) is not represented: RDF sets
are unordered. The graph keeps the order.

Tenancy (DEC-130, DEC-162). Instance IRIs and local code-system IRIs are namespaced per tenant:
`res:` is `{BASE}fhir/<tenant>/` and `cs:` is `{BASE}CodeSystem/<tenant>/`. Resource ids and Concept
nodes are only unique within a tenant, so without the namespace two tenants' exports would collide.
The tenant is the one bound at the edge (`current_tenant()`), and the exporter takes no tenant as an
argument (an architecture test refuses one in the graph store). With no tenant bound, or a network
scope, the export is refused. The `diucs:` ontology and `fhir:` are global.
"""

import hashlib
import re
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from urllib.parse import quote

from rdflib import RDF, XSD, BNode, Graph, Literal, Namespace, URIRef

from diucs.adapters.outbound.graph_store.mapper import GraphFragment, RelSpec
from diucs.application.tenancy import current_tenant
from diucs.domain.codes import BASE_URL
from diucs.domain.errors import ValidationFailed

FHIR: Final = Namespace("http://hl7.org/fhir/")
DIUCS: Final = Namespace(f"{BASE_URL}def#")
SKOS: Final = Namespace("http://www.w3.org/2004/02/skos/core#")
PROV: Final = Namespace("http://www.w3.org/ns/prov#")
_LOCAL_SYSTEM_PREFIX: Final = f"{BASE_URL}CodeSystem/"

_TENANT: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_ROLE: Final = re.compile(r"[A-Za-z][A-Za-z0-9]*")

# Relationship types whose predicate is a diucs term, not the FHIR element (the data model's table).
_DIUCS_PREDICATES: Final[dict[str, str]] = {
    "CURRENT_CRITERIA": "currentCriteria",
    "ACCEPTS_NEED": "acceptsNeed",
    "EXCLUDES_NEED": "excludesNeed",
    "SUPERSEDES": "supersedes",
}
# Relationship properties the mapper writes for ordering. They are not qualifiers.
_STRUCTURAL_REL_PROPS: Final = frozenset({"fhirPath", "order", "conceptOrder"})
# The qualifiers a relationship property may carry, as in APPROVED_BY {role, at}.
_QUALIFIER_PROPS: Final = frozenset({"role", "at"})
# Node properties that are not FHIR elements: the resource id and iri, the json the store does not
# hold (DEC-001), and the copied filter codes (R11).
_SKIPPED_NODE_PROPS: Final = frozenset({"id", "iri", "key", "json", "measureCode", "odsCode"})
# A mapper property `<element>_<part>` is one part of a complex element; this table names its type.
_FLATTENED_TYPES: Final[dict[str, str]] = {"valueQuantity": "Quantity"}
_EXTENSION_PREFIX: Final = "ext_"

# Task codes that make a Task a booking request or a registration (fhir-data-model.md).
_BOOKING_CODE: Final = "booking-request"
_REGISTRATION_CODE: Final = "register-service"

_DATE_TIME: Final = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})")
_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME: Final = re.compile(r"\d{2}:\d{2}:\d{2}")

_ONTOLOGY: Final = """
@prefix diucs: <https://diucs.example/def#> .
@prefix fhir:  <http://hl7.org/fhir/> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos:  <http://www.w3.org/2004/02/skos/core#> .

diucs:CapacityReport a owl:Class ;
    rdfs:subClassOf fhir:Observation ; rdfs:label "Capacity report" .
diucs:ServiceCriteria a owl:Class ;
    rdfs:subClassOf fhir:Basic ; rdfs:label "Service criteria version" .
diucs:ServiceFlag a owl:Class ;
    rdfs:subClassOf fhir:Basic ; rdfs:label "Service flag" .
diucs:BookingRequest a owl:Class ;
    rdfs:subClassOf fhir:Task ; rdfs:label "Booking request" .
diucs:Registration a owl:Class ;
    rdfs:subClassOf fhir:Task ; rdfs:label "Service registration" .
diucs:Case a owl:Class ;
    rdfs:subClassOf fhir:ServiceRequest ; rdfs:label "Case" .
diucs:AlertAcknowledgement a owl:Class ;
    rdfs:subClassOf fhir:Task .

diucs:StatusScheme a skos:ConceptScheme ; skos:prefLabel "Service status"@en .
diucs:Accepting a skos:Concept ;
    skos:inScheme diucs:StatusScheme ; skos:prefLabel "Accepting"@en .
diucs:Limited a skos:Concept ;
    skos:inScheme diucs:StatusScheme ; skos:prefLabel "Limited"@en .
diucs:NotAccepting a skos:Concept ;
    skos:inScheme diucs:StatusScheme ; skos:prefLabel "Not accepting"@en .
diucs:OverCapacity a skos:Concept ;
    skos:inScheme diucs:StatusScheme ; skos:prefLabel "Over capacity"@en .
diucs:NotUpdated a skos:Concept ;
    skos:inScheme diucs:StatusScheme ; skos:prefLabel "Not updated"@en .
diucs:OutOfHours a skos:Concept ;
    skos:inScheme diucs:StatusScheme ; skos:prefLabel "Out of hours"@en .

diucs:currentCriteria a owl:ObjectProperty ;
    rdfs:domain fhir:HealthcareService ; rdfs:range diucs:ServiceCriteria .
diucs:acceptsNeed a owl:ObjectProperty ;
    rdfs:domain diucs:ServiceCriteria ; rdfs:range skos:Concept .
diucs:excludesNeed a owl:ObjectProperty ;
    rdfs:domain diucs:ServiceCriteria ; rdfs:range skos:Concept .
diucs:supersedes a owl:ObjectProperty ;
    rdfs:domain diucs:ServiceCriteria ; rdfs:range diucs:ServiceCriteria .
diucs:reportType a owl:DatatypeProperty ;
    rdfs:domain diucs:CapacityReport .
diucs:version a owl:DatatypeProperty ;
    rdfs:domain diucs:ServiceCriteria .
"""


def ontology_turtle() -> str:
    """The diucs: ontology block of fhir-data-model.md, as Turtle."""
    return _ONTOLOGY


def _bound_tenant() -> str:
    """The tenant bound at the edge. current_tenant refuses no binding and a network scope. The
    value is checked before it enters an IRI, and is never echoed in the error."""
    tenant = current_tenant()
    if _TENANT.fullmatch(tenant) is None:
        raise ValidationFailed("tenant", "must be a plain tenant id")
    return tenant


def _blank(name: str) -> BNode:
    """A blank node named from a fragment key, so the same child is always the same node."""
    return BNode("n" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:24])


def _concept_parts(key: str) -> tuple[str, str]:
    """The system and the code of a Concept key `Concept|<system>|<code>`."""
    system, _, code = key[len("Concept|") :].rpartition("|")
    return system, code


def _local_name(system: str) -> str | None:
    """A local code system's name, or None for a code system from outside this platform."""
    if system.startswith(_LOCAL_SYSTEM_PREFIX):
        name = system[len(_LOCAL_SYSTEM_PREFIX) :]
        if name and "/" not in name:
            return name
    return None


def _concept_iri(system: str, code: str, cs: Namespace) -> URIRef:
    local = quote(code, safe="-_.")
    name = _local_name(system)
    if name is None:
        return URIRef(f"{system}#{local}")
    return URIRef(f"{cs}{name}#{local}")


def _term(key: str, res: Namespace, cs: Namespace) -> URIRef | BNode | None:
    """The RDF term of a fragment key, or None for a key that has no term (a code system)."""
    if key.startswith("CodeSystem|"):
        return None
    if key.startswith("Concept|"):
        system, code = _concept_parts(key)
        return _concept_iri(system, code, cs)
    if key.startswith("Identifier|"):
        return URIRef(f"{res}Identifier/{quote(key[len('Identifier|') :], safe='')}")
    if "#" in key:
        return _blank(key)
    return URIRef(f"{res}{quote(key, safe='/')}")


def _literal(value: Any) -> Literal:
    if isinstance(value, bool):
        return Literal(value)
    if isinstance(value, int):
        return Literal(value, datatype=XSD.integer)
    if isinstance(value, float):
        return Literal(Decimal(repr(value)), datatype=XSD.decimal)
    if isinstance(value, str):
        if _DATE_TIME.fullmatch(value):
            return Literal(value, datatype=XSD.dateTime)
        if _DATE.fullmatch(value):
            return Literal(value, datatype=XSD.date)
        if _TIME.fullmatch(value):
            return Literal(value, datatype=XSD.time)
        return Literal(value)
    raise ValidationFailed("value", "must be a primitive value")


def _resource_type(labels: tuple[str, ...]) -> str | None:
    return next((label for label in labels if label != "Resource"), None)


def _classes(labels: tuple[str, ...], props: dict[str, Any], rels: list[RelSpec]) -> list[URIRef]:
    """The rdf:type of a resource beyond its FHIR type, from the profile it was written to."""
    kind = _resource_type(labels)
    if kind == "Observation" and _EXTENSION_PREFIX + "reportType" in props:
        return [DIUCS.CapacityReport]
    if kind == "Basic" and "ageMin" in props:
        return [DIUCS.ServiceCriteria]
    if kind == "Basic" and "code" in props and "actor" in props:
        return [DIUCS.ServiceFlag]
    if kind == "ServiceRequest":
        return [DIUCS.Case]
    if kind == "Task":
        for rel in rels:
            if rel.type == "CODE" and rel.end.startswith("Concept|"):
                _, code = _concept_parts(rel.end)
                if code == _BOOKING_CODE:
                    return [DIUCS.BookingRequest]
                if code == _REGISTRATION_CODE:
                    return [DIUCS.Registration]
    return []


def _element_paths(fragment: GraphFragment) -> dict[str, str]:
    """The FHIR element path of each backbone child, from the relationship that reaches it."""
    paths: dict[str, str] = {}
    for rel in fragment.rels:
        if "#" in rel.end and "fhirPath" in rel.properties:
            paths[rel.end] = str(rel.properties["fhirPath"])
    return paths


def _add_values(graph: Graph, subject: Any, predicate: URIRef, value: Any) -> None:
    items = value if isinstance(value, list | tuple) else [value]
    for item in items:
        graph.add((subject, predicate, _literal(item)))


def _write_node(
    graph: Graph,
    node_labels: tuple[str, ...],
    key: str,
    props: dict[str, Any],
    rels: list[RelSpec],
    paths: dict[str, str],
    res: Namespace,
    cs: Namespace,
) -> None:
    subject = _term(key, res, cs)
    if subject is None:
        return
    classes: list[URIRef] = []
    if "Resource" in node_labels:
        kind = _resource_type(node_labels)
        if kind is None:
            raise ValidationFailed("resource", "has no resource type")
        path = kind
        graph.add((subject, RDF.type, FHIR[kind]))
        classes = _classes(node_labels, props, rels)
        for extra in classes:
            graph.add((subject, RDF.type, extra))
    elif key.startswith("Identifier|"):
        path = "Identifier"
        graph.add((subject, RDF.type, FHIR.Identifier))
    else:
        path = paths.get(key, "")
    flattened: dict[str, dict[str, Any]] = {}
    for name, value in props.items():
        if value is None or name in _SKIPPED_NODE_PROPS:
            continue
        if name.startswith(_EXTENSION_PREFIX):
            _add_values(graph, subject, DIUCS[name[len(_EXTENSION_PREFIX) :]], value)
            continue
        head, _, part = name.partition("_")
        if part and head in _FLATTENED_TYPES:
            flattened.setdefault(head, {})[part] = value
            continue
        if not path:
            raise ValidationFailed("node", "has no FHIR element path to name its properties")
        if name == "version" and DIUCS.ServiceCriteria in classes:
            _add_values(graph, subject, DIUCS.version, value)
            continue
        _add_values(graph, subject, FHIR[f"{path}.{name}"], value)
    for head, parts in flattened.items():
        element = _blank(f"{key}#{head}")
        graph.add((subject, FHIR[f"{path}.{head}"], element))
        graph.add((element, RDF.type, FHIR[_FLATTENED_TYPES[head]]))
        for part, value in parts.items():
            _add_values(graph, element, FHIR[f"{_FLATTENED_TYPES[head]}.{part}"], value)


def _write_concept(graph: Graph, key: str, props: dict[str, Any], cs: Namespace) -> None:
    system, code = _concept_parts(key)
    subject = _concept_iri(system, code, cs)
    name = _local_name(system)
    scheme = URIRef(f"{cs}{name}") if name is not None else URIRef(system)
    graph.add((subject, RDF.type, SKOS.Concept))
    graph.add((subject, SKOS.inScheme, scheme))
    graph.add((subject, SKOS.notation, Literal(code)))
    display = props.get("display")
    if isinstance(display, str) and display:
        graph.add((subject, SKOS.prefLabel, Literal(display, lang="en")))


def _write_qualified(
    graph: Graph, rel: RelSpec, subject: Any, obj: Any, qualifiers: dict[str, Any]
) -> None:
    if set(qualifiers) - _QUALIFIER_PROPS:
        raise ValidationFailed("relationship", "has a property the export does not know")
    association = _blank(f"{rel.start}|{rel.type}|{rel.end}")
    graph.add((subject, PROV.qualifiedAssociation, association))
    graph.add((association, RDF.type, PROV.Association))
    graph.add((association, PROV.agent, obj))
    if "role" in qualifiers:
        role = qualifiers["role"]
        if not isinstance(role, str) or _ROLE.fullmatch(role) is None:
            raise ValidationFailed("role", "must be a role name")
        graph.add((association, PROV.hadRole, DIUCS[role]))
    if "at" in qualifiers:
        at = qualifiers["at"]
        if not isinstance(at, str):
            raise ValidationFailed("at", "must be a time")
        try:
            datetime.fromisoformat(at)
        except ValueError:
            raise ValidationFailed("at", "must be a time") from None
        graph.add((association, PROV.atTime, Literal(at, datatype=XSD.dateTime)))


def _write_relationship(graph: Graph, rel: RelSpec, res: Namespace, cs: Namespace) -> None:
    if rel.type == "IN_SYSTEM" or rel.end.startswith("CodeSystem|"):
        return
    subject = _term(rel.start, res, cs)
    obj = _term(rel.end, res, cs)
    if subject is None or obj is None:
        return
    predicate: URIRef | None
    if rel.type in _DIUCS_PREDICATES:
        predicate = DIUCS[_DIUCS_PREDICATES[rel.type]]
    elif "fhirPath" in rel.properties:
        predicate = FHIR[str(rel.properties["fhirPath"])]
    else:
        predicate = None
    if predicate is not None:
        graph.add((subject, predicate, obj))
    qualifiers = {k: v for k, v in rel.properties.items() if k not in _STRUCTURAL_REL_PROPS}
    if qualifiers:
        _write_qualified(graph, rel, subject, obj, qualifiers)


def fragment_to_graph(fragment: GraphFragment) -> Graph:
    """The triples of one mapper fragment, in the bound tenant's namespaces. It refuses no tenant
    binding, a value it cannot type, a node with no element path and a relationship property it
    does not know, rather than dropping them."""
    tenant = _bound_tenant()
    res = Namespace(f"{BASE_URL}fhir/{tenant}/")
    cs = Namespace(f"{BASE_URL}CodeSystem/{tenant}/")
    graph = Graph()
    graph.bind("fhir", FHIR)
    graph.bind("diucs", DIUCS)
    graph.bind("res", res)
    graph.bind("cs", cs)
    graph.bind("skos", SKOS)
    graph.bind("prov", PROV)
    graph.bind("xsd", XSD)
    paths = _element_paths(fragment)
    rels = list(fragment.rels)
    for node in fragment.nodes:
        if node.key.startswith("Concept|"):
            _write_concept(graph, node.key, node.properties, cs)
            continue
        own = [rel for rel in rels if rel.start == node.key]
        _write_node(graph, node.labels, node.key, node.properties, own, paths, res, cs)
    for rel in rels:
        _write_relationship(graph, rel, res, cs)
    return graph


def to_turtle(fragments: Iterable[GraphFragment]) -> str:
    """The Turtle of several fragments of the bound tenant, merged into one graph."""
    merged = Graph()
    for fragment in fragments:
        merged += fragment_to_graph(fragment)
    return merged.serialize(format="turtle")
