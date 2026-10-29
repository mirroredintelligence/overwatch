"""RDF (Turtle) export of the mapper fragments (G13). Stub for the red commit (DEC-010)."""

from collections.abc import Iterable

from rdflib import Graph

from diucs.adapters.outbound.graph_store.mapper import GraphFragment


def fragment_to_graph(fragment: GraphFragment, tenant: str) -> Graph:
    raise NotImplementedError("G13: fragment_to_graph is not built yet")


def to_turtle(fragments: Iterable[GraphFragment], tenant: str) -> str:
    raise NotImplementedError("G13: to_turtle is not built yet")


def ontology_turtle() -> str:
    raise NotImplementedError("G13: ontology_turtle is not built yet")
