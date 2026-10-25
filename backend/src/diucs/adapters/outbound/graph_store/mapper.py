"""FHIR R4B resource to property-graph mapper (rules R1 to R3 of fhir-data-model.md).

DEC-010 red stub: the types below are the real shapes; the functions raise NotImplementedError.
"""

from dataclasses import dataclass
from typing import Any

from diucs.domain.errors import DomainError


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
    raise NotImplementedError


def to_graph(resource: dict[str, Any]) -> GraphFragment:
    raise NotImplementedError


def from_graph(fragment: GraphFragment) -> dict[str, Any]:
    raise NotImplementedError
