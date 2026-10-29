"""The scenario a registered statement carries (DEC-142 item 5, DEC-150).

STUB (DEC-010, red commit): the types exist so the tests can build scenarios; `render` and
`validate_scenario` do nothing yet.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

Slot = Literal["A", "B"]


@dataclass(frozen=True, slots=True)
class Marked:
    base: str


@dataclass(frozen=True, slots=True)
class Unique:
    base: str
    constraint: str


@dataclass(frozen=True, slots=True)
class SeedNode:
    ref: str
    labels: tuple[str, ...]
    props: Mapping[str, Any] = field(default_factory=dict, hash=False)


@dataclass(frozen=True, slots=True)
class SeedRel:
    start: str
    type: str
    end: str


@dataclass(frozen=True, slots=True)
class TenantSeed:
    nodes: tuple[SeedNode, ...] = ()
    rels: tuple[SeedRel, ...] = ()


@dataclass(frozen=True, slots=True)
class NodeSpec:
    labels: tuple[str, ...]
    props: Mapping[str, Any] = field(default_factory=dict, hash=False)


@dataclass(frozen=True, slots=True)
class Expect:
    rows: tuple[Mapping[str, Any], ...] = ()
    after: tuple[NodeSpec, ...] = ()
    gone: tuple[NodeSpec, ...] = ()
    nodes: Mapping[str, int] = field(default_factory=dict, hash=False)
    rels: Mapping[str, int] = field(default_factory=dict, hash=False)


@dataclass(frozen=True, slots=True)
class Scenario:
    description: str
    seed: TenantSeed = TenantSeed()
    params: Mapping[str, Any] = field(default_factory=dict, hash=False)
    lookup: tuple[str, ...] = ()
    expect: Expect = Expect()
    insert: str = ""


SINGLE_PROPERTY_UNIQUE: Final[Mapping[str, tuple[str, str]]] = {}


def render(value: Any, slot: Slot) -> Any:
    raise NotImplementedError


def validate_scenario(query_id: str, scenario: Scenario) -> list[str]:
    raise NotImplementedError


def collision_blocked(scenario: Scenario) -> bool:
    raise NotImplementedError


def constraints_used(scenario: Scenario) -> frozenset[str]:
    raise NotImplementedError
