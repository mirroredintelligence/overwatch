"""The generated two-tenant isolation test over the query registry (TEN-004, DEC-142, DEC-150).

`run_isolation` runs every statement that has a scenario on a real Neo4j, as tenant A and as tenant
B, in two phases (A first, then B first):

1. Wipe, seed the first tenant alone, run the statement as that tenant, keep the rows and the
   tenant's data afterwards (the baseline: what the statement does when the other tenant does not
   exist). The baseline must also be what the scenario expects.
2. Seed the second tenant on top (the same keys, other text) and run the statement as the first
   tenant again. The rows, the first tenant's data afterwards and the second tenant's data must be
   what they were, and no node may lack a tenant or join two tenants.
3. When the scenario has a value the real schema stops two tenants sharing (`Unique`), run the
   statement a third time with the other tenant's value: it must read, change and see nothing.

Each probe runs in an explicit transaction on a `ScopedTx` and is rolled back, so no reseed is
needed between probes. A finding names the statement, the phase and the kind, and only counts or
names in its detail: never a value, a Cypher text or a tenant id.
"""

import importlib
import pkgutil
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from neo4j import AsyncDriver

import diucs.adapters.outbound.audit_neo4j as audit_package
import diucs.adapters.outbound.graph_store as graph_store_package
from diucs.adapters.outbound.graph_store.driver import ScopedTx, run_query
from diucs.adapters.outbound.graph_store.queries import (
    PLACEHOLDER,
    REGISTRY,
    NamedQuery,
    QueryRegistry,
)
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    NodeSpec,
    Scenario,
    Slot,
    render,
)
from diucs.application.tenancy import ScopeId
from tests.support.neo4j import wipe
from tests.support.tenant_seed import (
    Snapshot,
    canonical,
    digest,
    invariant_breaks,
    seed_tenant,
    snapshot,
)

_ENTRY: Final = re.compile(r"\btenantId\s*:\s*\$tenant\b")
_ID_CONVENTION: Final = re.compile(r"Q-[A-Z0-9]+(?:-[A-Z0-9]+)*")
_INSTANCE_SEPARATOR: Final = ":"
# Ids with this prefix belong to the private registries the tests build for their own corpus. The
# production registry holds none (`registry_problems`), so the prefix is no way out of the proof.
TEST_PREFIX: Final = "Q-TEST-"


class FindingKind(StrEnum):
    ROWS_DIFFER = "rows-differ"
    OWN_STATE_DIFFERS = "own-state-differs"
    OTHER_TENANT_CHANGED = "other-tenant-changed"
    UNSTAMPED_NODE = "unstamped-node"
    CROSS_SCOPE_RELATIONSHIP = "cross-scope-relationship"
    FOREIGN_ID_EFFECT = "foreign-id-effect"
    UNEXPECTED_ROWS = "unexpected-rows"
    UNEXPECTED_EFFECT = "unexpected-effect"
    PROBE_ERROR = "probe-error"
    VACUOUS_SCENARIO = "vacuous-scenario"


@dataclass(frozen=True, slots=True)
class Finding:
    query_id: str
    phase: str
    kind: FindingKind
    detail: str


def format_findings(findings: list[Finding]) -> str:
    """One line per finding: the statement, the phase, the kind and the detail (counts and names
    only)."""
    return "\n".join(f"{f.query_id} [{f.phase}] {f.kind}: {f.detail}" for f in findings)


# The statement universe, the gaps and the ratchet


def _load_every_statement() -> None:
    """Import every module of the two packages that register statements, so the module registry
    holds all of them whatever the test session has imported so far."""
    for package in (graph_store_package, audit_package):
        for module in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
            importlib.import_module(module.name)


def production_statements(registry: QueryRegistry = REGISTRY) -> dict[str, NamedQuery]:
    """Every tenant statement of the registry, keyed by base id: the eager statements, and one
    entry per template (the instance its scenario names, or a stand-in with the place emptied when
    it has none). Global statements and run-time instances are left out. A private registry that a
    test builds for its own corpus also leaves out its `Q-TEST-` statements; the production
    registry never does, whatever a statement is called. For the module registry every statement
    module is imported first."""
    if registry is REGISTRY:
        _load_every_statement()
    universe: dict[str, NamedQuery] = {}
    for query_id in registry.ids():
        query = registry.get(query_id)
        if ":" in query_id or _private_test_statement(registry, query_id):
            continue
        if query.scope != "tenant":
            continue
        universe[query_id] = query
    for template_id in registry.template_ids():
        template = registry.template(template_id)
        if _private_test_statement(registry, template_id) or template.scope != "tenant":
            continue
        if template.scenario is not None:
            universe[template_id] = registry.instance(template_id, template.scenario.insert)
        else:
            universe[template_id] = NamedQuery(
                id=template_id,
                cypher=template.cypher.replace(PLACEHOLDER, ""),
                mode=template.mode,
                scope=template.scope,
            )
    return universe


def _private_test_statement(registry: QueryRegistry, query_id: str) -> bool:
    """A `Q-TEST-` statement of a private registry: the only kind the universe leaves out by name.
    The production registry has no such thing."""
    return registry is not REGISTRY and query_id.startswith(TEST_PREFIX)


def registry_problems(registry: QueryRegistry) -> list[str]:
    """Ids the production registry may not hold: a `Q-TEST-` id (those are for the private
    registries of tests, and the name must never be a way out of the generated test) and an id
    outside the naming convention. Run-time instances (`<template>:<insert>`) are judged by their
    template. Empty means fine."""
    problems: list[str] = []
    for query_id in sorted({*registry.ids(), *registry.template_ids()}):
        if _INSTANCE_SEPARATOR in query_id:
            continue
        if query_id.startswith(TEST_PREFIX):
            problems.append(
                f"{query_id}: an id starting with {TEST_PREFIX} belongs to the private registry of "
                "a test, never the production registry; rename the statement"
            )
        if _ID_CONVENTION.fullmatch(query_id) is None:
            problems.append(f"{query_id}: not in the naming convention Q-<WORD>-<WORD>")
    return problems


def universe_problems(registry: QueryRegistry, statements: Mapping[str, NamedQuery]) -> list[str]:
    """The registered tenant statements and templates that the generated test would not run:
    every one of them must be in the universe, whatever its name. Empty means fine."""
    registered = [
        query_id
        for query_id in registry.ids()
        if _INSTANCE_SEPARATOR not in query_id and registry.get(query_id).scope == "tenant"
    ]
    registered += [t for t in registry.template_ids() if registry.template(t).scope == "tenant"]
    return [
        f"{query_id}: registered, and not in the universe the generated test runs"
        for query_id in sorted(set(registered))
        if query_id not in statements and not _private_test_statement(registry, query_id)
    ]


def is_vacuous(rows: list[dict[str, Any]], before: Snapshot, after: Snapshot) -> bool:
    """A run that returns no rows and changes nothing in the caller's data observes nothing, so
    its scenario proves nothing: a no-op write, or a read that never matches."""
    return not rows and digest(before) == digest(after)


def scenario_gaps(statements: Mapping[str, NamedQuery]) -> list[str]:
    """The statements that have no scenario: the generated test fails for each of them, so a
    statement cannot be added without proof. There is no ratchet to excuse one (TEN-030)."""
    return [
        f"{query_id}: no scenario; give it a Scenario"
        for query_id, query in sorted(statements.items())
        if query.scenario is None
    ]


def predicate_problems(statements: Mapping[str, NamedQuery]) -> list[str]:
    """The statements that have no `tenantId: $tenant` entry. The registry refuses one at
    registration; this is the same look over a universe a test hands in."""
    return [
        f"{query_id}: no tenantId: $tenant entry; it needs the tenant predicate"
        for query_id, query in sorted(statements.items())
        if _ENTRY.search(query.cypher) is None
    ]


# Rows and effects


def normalised(rows: list[dict[str, Any]], *, mask_times: bool = False) -> list[str]:
    """The rows as sorted canonical JSON, a multiset. With `mask_times` a time is written as a
    fixed word, for comparing two runs: a statement that stamps `datetime()` writes another time
    each run, and that is not a difference between tenants."""
    return sorted(canonical(row, mask_times=mask_times) for row in rows)


def _subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and all(
            key in actual and _subset(value, actual[key]) for key, value in expected.items()
        )
    return canonical(expected) == canonical(actual)


def row_problems(
    expected: tuple[Mapping[str, Any], ...], actual: list[dict[str, Any]], slot: Slot
) -> list[str]:
    """The expected rows against the rows the statement returned, as a multiset of subsets: each
    expected row names some keys (nested maps too) and each must find its own actual row."""
    if len(expected) != len(actual):
        return [f"expected {len(expected)} rows, got {len(actual)}"]
    unused = list(actual)
    problems: list[str] = []
    for position, row in enumerate(expected):
        wanted = render(dict(row), slot)
        for index, candidate in enumerate(unused):
            if _subset(wanted, candidate):
                unused.pop(index)
                break
        else:
            problems.append(f"row {position} is not the expected row")
    return problems


def _matches(spec: NodeSpec, node: Any, slot: Slot) -> bool:
    return set(spec.labels) <= set(node.labels) and all(
        name in node.props and canonical(render(value, slot)) == canonical(node.props[name])
        for name, value in spec.props.items()
    )


def _deltas(
    before: Counter[str], after: Counter[str], expected: Mapping[str, int]
) -> list[tuple[str, int, int]]:
    """(name, expected change, measured change) for every name where the two differ."""
    wanted = {name: count for name, count in expected.items() if count != 0}
    measured = {name: after[name] - before[name] for name in set(before) | set(after)}
    measured = {name: count for name, count in measured.items() if count != 0}
    return [
        (name, wanted.get(name, 0), measured.get(name, 0))
        for name in sorted(set(wanted) | set(measured))
        if wanted.get(name, 0) != measured.get(name, 0)
    ]


def effect_problems(before: Snapshot, after: Snapshot, expect: Expect, slot: Slot) -> list[str]:
    """What the statement did to the caller's data, against what the scenario says it must do."""
    problems: list[str] = []
    labels_before = Counter(label for node in before.nodes for label in node.labels)
    labels_after = Counter(label for node in after.nodes for label in node.labels)
    for name, wanted, got in _deltas(labels_before, labels_after, expect.nodes):
        problems.append(f"nodes {name}: expected {wanted:+d}, got {got:+d}")
    types_before = Counter(rel.type for rel in before.rels)
    types_after = Counter(rel.type for rel in after.rels)
    for name, wanted, got in _deltas(types_before, types_after, expect.rels):
        problems.append(f"relationships {name}: expected {wanted:+d}, got {got:+d}")
    for spec in expect.after:
        if not any(_matches(spec, node, slot) for node in after.nodes):
            problems.append(f"no node matches the expected state {':'.join(spec.labels)}")
    for spec in expect.gone:
        name = ":".join(spec.labels)
        if not any(_matches(spec, node, slot) for node in before.nodes):
            problems.append(f"a node that should be gone was not there to begin with: {name}")
        elif any(_matches(spec, node, slot) for node in after.nodes):
            problems.append(f"a node that should be gone is still there: {name}")
    declared = expect.after or expect.gone or expect.nodes or expect.rels
    if not declared and digest(before) != digest(after):
        problems.append(
            "the statement changed the caller's data, and the scenario expects no change"
        )
    return problems


# The runner


@dataclass(frozen=True, slots=True)
class _Outcome:
    rows: list[dict[str, Any]]
    first_before: Snapshot
    first_after: Snapshot
    second_before: Snapshot
    second_after: Snapshot
    unstamped: list[str]
    crossing: list[str]


async def _probe(
    driver: AsyncDriver,
    query: NamedQuery,
    registry: QueryRegistry,
    first: str,
    second: str,
    params: dict[str, Any],
) -> _Outcome:
    """Run the statement once as `first`, in a transaction that is rolled back."""
    async with driver.session() as session:
        tx = await session.begin_transaction()
        try:
            first_before = await snapshot(tx, first)
            second_before = await snapshot(tx, second)
            rows = await run_query(
                ScopedTx(tx, ScopeId.tenant(first)), query, registry=registry, **params
            )
            first_after = await snapshot(tx, first)
            second_after = await snapshot(tx, second)
            unstamped, crossing = await invariant_breaks(tx)
        finally:
            await tx.close()
    return _Outcome(
        rows, first_before, first_after, second_before, second_after, unstamped, crossing
    )


def _same_run(left: _Outcome, right: _Outcome) -> list[str]:
    """How two outcomes of one statement differ, ignoring times a statement stamps itself."""
    differences: list[str] = []
    if normalised(left.rows, mask_times=True) != normalised(right.rows, mask_times=True):
        differences.append(
            f"{len(right.rows)} rows, against {len(left.rows)} without the other tenant"
        )
    if digest(left.first_after, mask_times=True) != digest(right.first_after, mask_times=True):
        differences.append("the caller's data afterwards differs")
    if digest(right.second_before) != digest(right.second_after):
        differences.append("the other tenant's data changed")
    return differences


async def _phase(
    driver: AsyncDriver,
    query_id: str,
    query: NamedQuery,
    scenario: Scenario,
    registry: QueryRegistry,
    tenants: tuple[str, str],
    slots: tuple[Slot, Slot],
) -> list[Finding]:
    first, second = tenants
    phase = f"{slots[0]}-then-{slots[1]}"
    found: list[Finding] = []

    def add(kind: FindingKind, detail: str) -> None:
        found.append(Finding(query_id, phase, kind, detail))

    own = render(dict(scenario.params), slots[0])
    other = render(dict(scenario.params), slots[1])
    await wipe(driver)
    await seed_tenant(driver, first, slots[0], scenario.seed)
    try:
        base = await _probe(driver, query, registry, first, second, own)
        foreign_base = (
            await _probe(driver, query, registry, first, second, other) if other != own else None
        )
        await seed_tenant(driver, second, slots[1], scenario.seed)
        again = await _probe(driver, query, registry, first, second, own)
        foreign = (
            await _probe(driver, query, registry, first, second, other) if other != own else None
        )
    except Exception as error:
        add(FindingKind.PROBE_ERROR, type(error).__name__)
        return found
    if is_vacuous(base.rows, base.first_before, base.first_after):
        add(
            FindingKind.VACUOUS_SCENARIO,
            "the statement returns no rows and changes nothing for the caller, so the scenario "
            "observes nothing",
        )
    for problem in row_problems(scenario.expect.rows, base.rows, slots[0]):
        add(FindingKind.UNEXPECTED_ROWS, problem)
    for problem in effect_problems(base.first_before, base.first_after, scenario.expect, slots[0]):
        add(FindingKind.UNEXPECTED_EFFECT, problem)
    if normalised(base.rows, mask_times=True) != normalised(again.rows, mask_times=True):
        add(
            FindingKind.ROWS_DIFFER,
            f"{len(again.rows)} rows with the other tenant, {len(base.rows)} without",
        )
    if digest(base.first_after, mask_times=True) != digest(again.first_after, mask_times=True):
        add(
            FindingKind.OWN_STATE_DIFFERS,
            "the caller's data afterwards differs when the other tenant exists",
        )
    if digest(again.second_before) != digest(again.second_after):
        add(FindingKind.OTHER_TENANT_CHANGED, "the other tenant's data changed")
    unstamped = base.unstamped or again.unstamped
    if unstamped:
        add(FindingKind.UNSTAMPED_NODE, f"nodes with no tenant: {', '.join(unstamped)}")
    crossing = base.crossing or again.crossing
    if crossing:
        add(
            FindingKind.CROSS_SCOPE_RELATIONSHIP,
            f"relationships between tenants: {', '.join(crossing)}",
        )
    if foreign_base is not None and foreign is not None:
        for difference in _same_run(foreign_base, foreign):
            add(FindingKind.FOREIGN_ID_EFFECT, difference)
    return found


async def run_isolation(
    driver: AsyncDriver,
    statements: Mapping[str, NamedQuery],
    *,
    registry: QueryRegistry,
    tenant_a: str,
    tenant_b: str,
) -> list[Finding]:
    """Run the scenario of every statement that has one, both ways round. A statement with no
    scenario is not run here: `scenario_gaps` and the ratchet are what refuse it."""
    findings: list[Finding] = []
    for query_id, query in sorted(statements.items()):
        scenario = query.scenario
        if scenario is None:
            continue
        for tenants, slots in (
            ((tenant_a, tenant_b), ("A", "B")),
            ((tenant_b, tenant_a), ("B", "A")),
        ):
            findings += await _phase(driver, query_id, query, scenario, registry, tenants, slots)
    return findings
