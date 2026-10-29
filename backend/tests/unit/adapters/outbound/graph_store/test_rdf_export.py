"""Unit tests for the RDF (Turtle) export of the mapper fragments (G13).

The fixtures are the mapper's own output (to_graph), so the export is tested on what the graph
really holds. Sample values only. The export is a query projection and is not validated against
the FHIR ShEx schemas (see the module docstring of rdf_export.py).
"""

import contextvars
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from rdflib import RDF, BNode, Graph, Literal, Namespace
from rdflib.compare import isomorphic

from diucs.adapters.outbound.graph_store.capacity_repository import report_to_fhir
from diucs.adapters.outbound.graph_store.criteria_repository import criteria_to_fhir
from diucs.adapters.outbound.graph_store.mapper import GraphFragment, RelSpec, to_graph
from diucs.adapters.outbound.graph_store.rdf_export import (
    fragment_to_graph,
    ontology_turtle,
    to_turtle,
)
from diucs.application.tenancy import ScopeId, TenantNotBound, bind_scope, bind_tenant
from diucs.domain.codes import BASE_URL, code_system_url
from diucs.domain.errors import ValidationFailed
from tests.unit.adapters.outbound.graph_store.test_capacity_repository import NUMBER_REPORT
from tests.unit.adapters.outbound.graph_store.test_criteria_mapping import UCR_WEST_V3

TENANT = "tt-sample-a"
OTHER = "tt-sample-b"
FHIR = Namespace("http://hl7.org/fhir/")
DIUCS = Namespace(f"{BASE_URL}def#")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
PROV = Namespace("http://www.w3.org/ns/prov#")
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")


@pytest.fixture(autouse=True)
def bound_tenant() -> Iterator[None]:
    """The export reads the tenant bound at the edge. The test binds the sample tenant."""
    with bind_tenant(TENANT):
        yield


def _res(tenant: str = TENANT) -> Namespace:
    return Namespace(f"{BASE_URL}fhir/{tenant}/")


def _cs(tenant: str = TENANT) -> Namespace:
    return Namespace(f"{BASE_URL}CodeSystem/{tenant}/")


RES = _res()
CS = _cs()

UCR_WEST: dict[str, Any] = {
    "resourceType": "HealthcareService",
    "id": "a1",
    "active": True,
    "name": "UCR West",
    "providedBy": {"reference": "Organization/o1"},
    "category": [
        {
            "coding": [
                {
                    "system": code_system_url("service-category"),
                    "code": "urgent-community-response",
                }
            ]
        }
    ],
    "coverageArea": [{"reference": "Location/d3"}, {"reference": "Location/d4"}],
    "referralMethod": [
        {"coding": [{"system": code_system_url("referral-method"), "code": "phone"}]}
    ],
}


def _location(location_id: str, name: str) -> dict[str, Any]:
    return {
        "resourceType": "Location",
        "id": location_id,
        "name": name,
        "mode": "kind",
        "type": [
            {
                "coding": [
                    {
                        "system": code_system_url("location-type"),
                        "code": "postcode-district",
                    }
                ]
            }
        ],
    }


def _service_fragment() -> GraphFragment:
    """UCR West with its two districts, and the link to its current criteria, which the criteria
    repository writes (not the mapper), so the test adds that one relationship."""
    service = to_graph(UCR_WEST)
    locations = [to_graph(_location("d3", "DT3")), to_graph(_location("d4", "DT4"))]
    nodes = [node for fragment in (service, *locations) for node in fragment.nodes]
    rels = [rel for fragment in (service, *locations) for rel in fragment.rels]
    rels.append(RelSpec("CURRENT_CRITERIA", "HealthcareService/a1", "Basic/c3", {}))
    return GraphFragment(root_key=service.root_key, nodes=tuple(nodes), rels=tuple(rels))


def _criteria_fragment(supersedes: str | None = "crit-ucr-west-v2") -> GraphFragment:
    criteria = replace(UCR_WEST_V3, id="c3", supersedes_id=supersedes)
    return to_graph(criteria_to_fhir(criteria))


# Full IRIs, not prefixed names: a prefixed name cannot hold "/" or "#" in Turtle, so the
# worked example's `res:Type/id` form is not valid Turtle (see the fragment's known issues).
EXPECTED_SERVICE = """
@prefix fhir: <http://hl7.org/fhir/> .
@prefix diucs: <https://diucs.example/def#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

<@R@HealthcareService/a1> a fhir:HealthcareService ;
    fhir:HealthcareService.active true ;
    fhir:HealthcareService.name "UCR West" ;
    fhir:HealthcareService.providedBy <@R@Organization/o1> ;
    fhir:HealthcareService.category <@C@service-category#urgent-community-response> ;
    fhir:HealthcareService.coverageArea <@R@Location/d3>, <@R@Location/d4> ;
    fhir:HealthcareService.referralMethod <@C@referral-method#phone> ;
    diucs:currentCriteria <@R@Basic/c3> .

<@R@Location/d3> a fhir:Location ;
    fhir:Location.name "DT3" ;
    fhir:Location.mode "kind" ;
    fhir:Location.type <@C@location-type#postcode-district> .

<@R@Location/d4> a fhir:Location ;
    fhir:Location.name "DT4" ;
    fhir:Location.mode "kind" ;
    fhir:Location.type <@C@location-type#postcode-district> .

<@C@service-category#urgent-community-response> a skos:Concept ;
    skos:inScheme <@C@service-category> ;
    skos:notation "urgent-community-response" .

<@C@referral-method#phone> a skos:Concept ;
    skos:inScheme <@C@referral-method> ;
    skos:notation "phone" .

<@C@location-type#postcode-district> a skos:Concept ;
    skos:inScheme <@C@location-type> ;
    skos:notation "postcode-district" .
""".replace("@R@", f"{BASE_URL}fhir/{TENANT}/").replace("@C@", f"{BASE_URL}CodeSystem/{TENANT}/")


def _parse(text: str) -> Graph:
    graph = Graph()
    graph.parse(data=text, format="turtle")
    return graph


def test_the_ucr_west_worked_example_is_isomorphic_to_the_export() -> None:
    exported = fragment_to_graph(_service_fragment())
    expected = _parse(EXPECTED_SERVICE)
    assert isomorphic(exported, expected)


def test_the_capacity_report_is_a_capacity_report_with_its_time_and_quantity() -> None:
    graph = fragment_to_graph(to_graph(report_to_fhir(NUMBER_REPORT)))
    subject = RES[f"Observation/{NUMBER_REPORT.id}"]
    assert (subject, RDF.type, FHIR.Observation) in graph
    assert (subject, RDF.type, DIUCS.CapacityReport) in graph
    assert (
        subject,
        FHIR["Observation.effectiveDateTime"],
        Literal("2026-10-25T09:12:00Z", datatype=XSD.dateTime),
    ) in graph
    quantities = list(graph.objects(subject, FHIR["Observation.valueQuantity"]))
    assert len(quantities) == 1
    quantity = quantities[0]
    assert isinstance(quantity, BNode)
    assert (quantity, RDF.type, FHIR.Quantity) in graph
    assert (quantity, FHIR["Quantity.value"], Literal(NUMBER_REPORT.value)) in graph
    assert (quantity, FHIR["Quantity.code"], Literal("{referral}")) in graph
    assert (subject, DIUCS.reportType, Literal("number")) in graph


def test_the_criteria_version_has_two_accepted_needs_and_its_predecessor() -> None:
    graph = fragment_to_graph(_criteria_fragment())
    criteria = RES["Basic/c3"]
    assert (criteria, RDF.type, FHIR.Basic) in graph
    assert (criteria, RDF.type, DIUCS.ServiceCriteria) in graph
    accepted = set(graph.objects(criteria, DIUCS.acceptsNeed))
    assert accepted == {
        CS["need-category#fall-no-injury"],
        CS["need-category#frailty"],
    }
    assert (criteria, DIUCS.supersedes, RES["Basic/crit-ucr-west-v2"]) in graph
    assert (criteria, DIUCS.version, Literal(3)) in graph


def test_no_json_is_ever_a_predicate() -> None:
    graph = fragment_to_graph(_service_fragment())
    for fragment in (_criteria_fragment(), to_graph(report_to_fhir(NUMBER_REPORT))):
        graph += fragment_to_graph(fragment)
    predicates = {str(predicate) for predicate in graph.predicates()}
    assert not [predicate for predicate in predicates if predicate.lower().endswith("json")]


def test_the_ontology_parses_and_defines_the_limited_status() -> None:
    graph = _parse(ontology_turtle())
    assert (DIUCS.Limited, RDF.type, SKOS.Concept) in graph


def test_a_need_is_accepted_by_the_service_whose_current_criteria_accept_it() -> None:
    graph = fragment_to_graph(_service_fragment())
    graph += fragment_to_graph(_criteria_fragment())
    derived = graph.query(
        """
        CONSTRUCT { ?need diucs:acceptedBy ?svc . }
        WHERE {
          ?svc diucs:currentCriteria ?c .
          ?c   diucs:acceptsNeed ?need .
        }
        """,
        initNs={"diucs": DIUCS},
    ).graph
    assert set(derived.triples((None, DIUCS.acceptedBy, None))) == {
        (CS["need-category#fall-no-injury"], DIUCS.acceptedBy, RES["HealthcareService/a1"]),
        (CS["need-category#frailty"], DIUCS.acceptedBy, RES["HealthcareService/a1"]),
    }


def test_the_same_key_in_two_tenants_is_two_iris() -> None:
    first = fragment_to_graph(_service_fragment())
    with bind_tenant(OTHER):
        second = fragment_to_graph(_service_fragment())
    assert (RES["HealthcareService/a1"], RDF.type, FHIR.HealthcareService) in first
    assert (_res(OTHER)["HealthcareService/a1"], RDF.type, FHIR.HealthcareService) in second
    assert not set(first.subjects()) & set(second.subjects())


def test_with_no_tenant_bound_the_export_is_refused() -> None:
    # A fresh context has no binding, as a worker started without one has none.
    with pytest.raises(TenantNotBound):
        contextvars.Context().run(fragment_to_graph, _service_fragment())


def test_a_network_scope_is_not_a_tenant_and_is_refused() -> None:
    with bind_scope(ScopeId.network("net-sample")), pytest.raises(TenantNotBound):
        to_turtle([_service_fragment()])


def test_a_backbone_child_is_a_blank_node_reached_from_its_parent() -> None:
    service = dict(UCR_WEST)
    service["availableTime"] = [{"daysOfWeek": ["mon", "tue"], "availableStartTime": "08:00:00"}]
    graph = fragment_to_graph(to_graph(service))
    children = list(
        graph.objects(RES["HealthcareService/a1"], FHIR["HealthcareService.availableTime"])
    )
    assert len(children) == 1
    assert isinstance(children[0], BNode)
    start = (children[0], FHIR["HealthcareService.availableTime.availableStartTime"], None)
    assert [o for _, _, o in graph.triples(start)] == [Literal("08:00:00", datatype=XSD.time)]


def test_a_relationship_property_is_a_qualified_association() -> None:
    fragment = GraphFragment(
        root_key="Task/b1",
        nodes=(),
        rels=(
            RelSpec(
                "APPROVED_BY",
                "Task/b1",
                "Practitioner/p1",
                {"role": "SecondApprover", "at": "2026-10-23T13:16:00Z"},
            ),
        ),
    )
    graph = fragment_to_graph(fragment)
    associations = list(graph.objects(RES["Task/b1"], PROV.qualifiedAssociation))
    assert len(associations) == 1
    association = associations[0]
    assert (association, RDF.type, PROV.Association) in graph
    assert (association, PROV.agent, RES["Practitioner/p1"]) in graph
    assert (association, PROV.hadRole, DIUCS.SecondApprover) in graph
    assert (
        association,
        PROV.atTime,
        Literal("2026-10-23T13:16:00Z", datatype=XSD.dateTime),
    ) in graph


def test_an_unknown_relationship_property_is_refused_not_dropped() -> None:
    fragment = GraphFragment(
        root_key="Task/b1",
        nodes=(),
        rels=(RelSpec("APPROVED_BY", "Task/b1", "Practitioner/p1", {"mood": "calm"}),),
    )
    with pytest.raises(ValidationFailed):
        fragment_to_graph(fragment)
