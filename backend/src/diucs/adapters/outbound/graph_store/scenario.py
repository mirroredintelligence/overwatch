"""The scenario a registered statement carries (DEC-142 item 5, DEC-150).

A scenario is what the generated two-tenant test needs to run one statement on a real Neo4j, as
tenant A and as tenant B:

- `seed`: the world each tenant gets. Both tenants get the same nodes with the same keys, so a
  statement that forgets `tenantId: $tenant` finds the other tenant's node by key. Text that
  should differ between the tenants is `Marked`, so a row that came from the wrong tenant looks
  different. The seed never carries `tenantId` or `seedMarker`: the seeder stamps them.
- `params`: the parameters the statement is run with, never `tenant`.
- `lookup`: the parameters that pick the node or nodes the statement works on. At least one must
  collide across the tenants (the seed holds that value for both), or the scenario is refused.
- `new`: the parameters that are new data, not a key the statement finds: a value to write, a
  limit, a time, or the key of a node the statement creates. Every other parameter must be held
  by the seed (a fresh key that is not declared is refused: no tenant holds it, so a statement
  that matches on it and leaks only when it matches would never be run on a match).
- `expect`: the rows the caller gets and the change to the caller's own data.

Every key a tenant can hold is composite with the tenant (migration 0031, TEN-005), so a scenario
shares its ids and keys between the two tenants and needs no `Unique`. The one key that stays
unique across tenants is a `LinkToken`'s `tokenHash` (`link_token_hash`): the hash is looked up
without a scope (DEC-131 item 5), so two tenants cannot hold one. A value such a constraint covers
is a `Unique`: the seeder writes it as is for tenant A and with a suffix for tenant B, and the
value names the constraint, which must sit on that label and property. The generated test then
also runs each statement with the other tenant's value (the foreign-id run). `constraints_used`
lists the constraints a scenario leans on, and a test pins the list, which is empty today.

This module is pure: no Neo4j, no tenant context. The scenario is data and holds no Cypher.
"""

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Literal

Slot = Literal["A", "B"]

_IDENTIFIER: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
RESERVED_PROPERTIES: Final = frozenset({"tenantId", "seedMarker"})
RESERVED_PARAMETERS: Final = frozenset({"tenant", "parameters"})

# The single-property unique constraints that two tenants still cannot share, on the schema the
# platform has after TEN-032 (the superseded keys dropped). TEN-005 made every other key composite
# with the tenant; `link_token_hash` stays globally unique by design (DEC-131 item 5, a hash lookup
# yields the tenant). A value one of them covers is a `Unique`. The test
# tests/integration/graph_store/test_tenant_isolation.py compares this table with the schema of a
# container that has the superseded keys dropped, so the table and the schema cannot drift.
SINGLE_PROPERTY_UNIQUE: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {"link_token_hash": ("LinkToken", "tokenHash")}
)


@dataclass(frozen=True, slots=True)
class Marked:
    """Text that differs between the tenants: `<base>-A` for tenant A, `<base>-B` for tenant B."""

    base: str


@dataclass(frozen=True, slots=True)
class Unique:
    """A value that a single-property unique constraint stops two tenants sharing (today only a
    link token hash): `<base>` for tenant A and `<base>-B` for tenant B. `constraint` names it."""

    base: str
    constraint: str


def render(value: Any, slot: Slot) -> Any:
    """The value for one tenant's slot: `Marked` and `Unique` resolved, mappings and sequences
    walked (a tuple becomes a list), anything else unchanged."""
    if isinstance(value, Marked):
        return f"{value.base}-{slot}"
    if isinstance(value, Unique):
        return value.base if slot == "A" else f"{value.base}-{slot}"
    if isinstance(value, Mapping):
        return {key: render(item, slot) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [render(item, slot) for item in value]
    return value


def _frozen(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True, slots=True)
class SeedNode:
    """A node of the seed. `ref` names it for the relationships; every tenant gets its own copy."""

    ref: str
    labels: tuple[str, ...]
    props: Mapping[str, Any] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "props", _frozen(self.props))


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
    """A node the caller's data must hold (or must no longer hold) after the statement: it has all
    these labels and these properties. The tenant is implied: only the caller's nodes count."""

    labels: tuple[str, ...]
    props: Mapping[str, Any] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "props", _frozen(self.props))


@dataclass(frozen=True, slots=True)
class Expect:
    """The effect for the caller. `rows`: the rows it gets (each a subset: the keys named must be
    there with these values, as a multiset). `nodes` and `rels`: the net change in the caller's
    node count per label and relationship count per type (anything not named must not change).
    `after`: nodes that exist afterwards. `gone`: nodes that existed before and no longer do. When
    none of `after`, `gone`, `nodes`, `rels` is given, the statement must change nothing."""

    rows: tuple[Mapping[str, Any], ...] = field(default=(), hash=False)
    after: tuple[NodeSpec, ...] = ()
    gone: tuple[NodeSpec, ...] = ()
    nodes: Mapping[str, int] = field(default_factory=dict, hash=False)
    rels: Mapping[str, int] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", _frozen(self.nodes))
        object.__setattr__(self, "rels", _frozen(self.rels))


@dataclass(frozen=True, slots=True)
class Scenario:
    description: str
    seed: TenantSeed = TenantSeed()
    params: Mapping[str, Any] = field(default_factory=dict, hash=False)
    lookup: tuple[str, ...] = ()
    new: tuple[str, ...] = ()
    expect: Expect = Expect()
    # For a template (`Q-RES-*`): the label chain or relationship type the statement is run with.
    insert: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", _frozen(self.params))


def _walk(value: Any) -> Iterator[Any]:
    """Every value inside `value`, `value` first: mapping values, list and tuple items."""
    yield value
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _walk(item)


def _scenario_values(scenario: Scenario) -> Iterator[Any]:
    """Every value the scenario holds: seed properties, parameters, expected rows and specs."""
    for node in scenario.seed.nodes:
        yield from _walk(dict(node.props))
    yield from _walk(dict(scenario.params))
    for row in scenario.expect.rows:
        yield from _walk(dict(row))
    for spec in (*scenario.expect.after, *scenario.expect.gone):
        yield from _walk(dict(spec.props))


def constraints_used(scenario: Scenario) -> frozenset[str]:
    """The constraints a scenario leans on: every `Unique` in its seed, parameters and
    expectations. A test pins this per statement; it is empty for every statement (TEN-005)."""
    return frozenset(v.constraint for v in _scenario_values(scenario) if isinstance(v, Unique))


def collision_blocked(scenario: Scenario) -> bool:
    """True when every lookup value is one a unique constraint stops the tenants sharing, so no
    key the statement is called with collides."""
    if not scenario.lookup:
        return False
    return all(
        any(isinstance(v, Unique) for v in _walk(scenario.params.get(name)))
        for name in scenario.lookup
    )


def validate_scenario(query_id: str, scenario: Scenario) -> list[str]:
    """The problems with a scenario, as messages that name the query and never a value. Empty means
    the scenario is usable. The rule that matters most: the keys must collide across the tenants,
    or the scenario proves nothing."""
    problems: list[str] = []

    def add(text: str) -> None:
        problems.append(f"{query_id}: {text}")

    _check_structure(scenario, add)
    _check_reserved(scenario, add)
    _check_values(scenario, add)
    _check_lookup(scenario, add)
    return problems


def _check_structure(scenario: Scenario, add: Callable[[str], None]) -> None:
    nodes = scenario.seed.nodes
    if not nodes:
        add("the seed has no nodes")
    refs = [node.ref for node in nodes]
    if len(set(refs)) != len(refs):
        add("a ref of the seed appears twice")
    for node in nodes:
        if not node.labels:
            add("a seed node has no label (a label name is required)")
        if any(_IDENTIFIER.fullmatch(label) is None for label in node.labels):
            add("a label name is not a plain identifier")
        if any(_IDENTIFIER.fullmatch(name) is None for name in node.props):
            add("a property name is not a plain identifier")
    for rel in scenario.seed.rels:
        if rel.start not in refs or rel.end not in refs:
            add("a relationship names an unknown ref")
        if _IDENTIFIER.fullmatch(rel.type) is None:
            add("a relationship type name is not a plain identifier")


def _check_reserved(scenario: Scenario, add: Callable[[str], None]) -> None:
    if any(RESERVED_PROPERTIES & set(node.props) for node in scenario.seed.nodes):
        add("a seed node sets a reserved property (the seeder sets the tenant and the marker)")
    specs = (*scenario.expect.after, *scenario.expect.gone)
    if any(RESERVED_PROPERTIES & set(spec.props) for spec in specs):
        add("an expectation names a reserved property (only the caller's nodes are looked at)")
    if RESERVED_PARAMETERS & set(scenario.params):
        add("the parameters name a reserved parameter (the tenant is bound, never given)")


def _check_values(scenario: Scenario, add: Callable[[str], None]) -> None:
    values = list(_scenario_values(scenario))
    marked = [v for v in values if isinstance(v, Marked)]
    unique = [v for v in values if isinstance(v, Unique)]
    per_tenant: list[Marked | Unique] = [*marked, *unique]
    if any(not isinstance(v.base, str) for v in per_tenant):
        add("a per-tenant value must be text")
    if any(v.constraint not in SINGLE_PROPERTY_UNIQUE for v in unique):
        add("a unique value names no known single-property constraint")
    for node in scenario.seed.nodes:
        for name, value in node.props.items():
            if not isinstance(value, Unique) or value.constraint not in SINGLE_PROPERTY_UNIQUE:
                continue
            label, prop = SINGLE_PROPERTY_UNIQUE[value.constraint]
            if label not in node.labels or prop != name:
                add("a unique value sits where its constraint does not apply")
    seed_values = [v for node in scenario.seed.nodes for p in node.props.values() for v in _walk(p)]
    if not any(isinstance(v, Marked | Unique) for v in seed_values):
        add("the seed has no per-tenant value, so it cannot tell the tenants apart")


def _key_values(value: Any) -> list[Any]:
    """The values inside a parameter that can be a key: text, numbers (not booleans), `Marked` and
    `Unique`, looking inside mappings and sequences."""
    return [
        v
        for v in _walk(value)
        if isinstance(v, str | int | float | Marked | Unique) and not isinstance(v, bool)
    ]


def _check_new(scenario: Scenario, seed_values: list[Any], add: Callable[[str], None]) -> None:
    """Every parameter is a lookup, declared new, or held by the seed: a key the seed does not hold
    is one no tenant holds, so a statement that leaks only on a match would never be run on one."""
    for name in scenario.new:
        if name not in scenario.params:
            add("`new` names something that is not a parameter")
        elif name in scenario.lookup:
            add(f"parameter '{name}' is a lookup, so it cannot be declared new: it must collide")
        else:
            keys = _key_values(scenario.params[name])
            if keys and all(k in seed_values for k in keys):
                add(f"parameter '{name}' is declared new, but the seed holds it")
    for name, value in scenario.params.items():
        if name in scenario.lookup or name in scenario.new:
            continue
        if any(k not in seed_values for k in _key_values(value)):
            add(
                f"parameter '{name}' is not held by the seed: declare it in `new` if it is new "
                "data, or name it in `lookup` if it picks a node"
            )


def _check_lookup(scenario: Scenario, add: Callable[[str], None]) -> None:
    seed_values = [v for node in scenario.seed.nodes for p in node.props.values() for v in _walk(p)]
    plain = [v for v in seed_values if not isinstance(v, Marked | Unique | Mapping | list | tuple)]
    _check_new(scenario, seed_values, add)
    if not scenario.lookup:
        if not plain:
            add("the two tenants share no value in this seed")
        return
    for name in scenario.lookup:
        if name not in scenario.params:
            add("the lookup names something that is not a parameter")
            continue
        value = scenario.params[name]
        inner = list(_walk(value))
        if any(isinstance(v, Marked) for v in inner):
            add("a lookup value differs between the tenants, so it cannot collide")
        elif any(isinstance(v, Unique) for v in inner):
            if not all(v in seed_values for v in inner if isinstance(v, Unique)):
                add("a lookup value is not held by the seed, so the keys do not collide")
        elif value not in plain:
            add("a lookup value is not held by the seed, so the keys do not collide")
