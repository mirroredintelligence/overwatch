"""The generated two-tenant isolation test over the query registry (TEN-004, DEC-142 item 5).

For every registered statement that has a scenario, on a real Neo4j: seed tenant A alone and run
the statement as A; seed tenant B (the same keys, other text) and run it as A again; the rows, A's
own data and B's data must be what they were without B, and nothing anywhere may be unstamped or
join two tenants. Then the same with B and A swapped. The run uses the real schema of the harness
(no constraint is dropped, DEC-150), so a value a single-property unique key covers cannot be shared
by two tenants yet; a scenario says so with `Unique` and the test also runs the statement with the
other tenant's value (the foreign-id run).

The rest proves the test itself: sound test-only statements pass, each kind of leak is caught by a
leaky twin, and taking `tenantId: $tenant` out of each converted statement makes the test fail for
it. All values are synthetic.
"""

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery, QueryRegistry
from diucs.adapters.outbound.graph_store.scenario import (
    SINGLE_PROPERTY_UNIQUE,
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
    Unique,
    validate_scenario,
)
from diucs.adapters.outbound.graph_store.unconverted import UNCONVERTED
from tests.support.neo4j import read_tx, write_tx
from tests.support.predicate_removal import mutant_of, predicate_count
from tests.support.query_probes import (
    Finding,
    FindingKind,
    format_findings,
    production_statements,
    registry_problems,
    run_isolation,
    scenario_gaps,
    universe_problems,
)
from tests.support.tenant_seed import seed_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Test-only statements, in a private registry. The label has no constraint, so two tenants share
# every key; `Resource` and `Unique` are used where the real schema forbids sharing.
THING = ("ProbeThing",)
SEED = TenantSeed(
    nodes=(
        SeedNode("t1", THING, {"id": "thing-1", "note": Marked("one"), "rank": 1}),
        SeedNode("t2", THING, {"id": "thing-2", "note": Marked("two"), "rank": 2}),
        SeedNode(
            "r1",
            ("Resource", "ProbeThing"),
            {"id": Unique("res-1", "resource_id"), "note": Marked("res"), "rank": 3},
        ),
    ),
    rels=(SeedRel("t1", "NEXT", "t2"),),
)
GET_ROWS = Expect(rows=({"id": "thing-1", "note": Marked("one")},))

_GET = "MATCH (n:ProbeThing {id: $id, tenantId: $tenant}) RETURN n.id AS id, n.note AS note"
_THING_PARAMS = {"id": "thing-1"}


def _scenario(
    description: str,
    cypher_params: dict[str, object],
    expect: Expect,
    lookup: tuple[str, ...] = ("id",),
    *,
    seed: TenantSeed = SEED,
    insert: str = "",
    new: tuple[str, ...] = (),
) -> Scenario:
    return Scenario(
        description,
        seed=seed,
        params=cypher_params,
        lookup=lookup,
        new=new,
        expect=expect,
        insert=insert,
    )


SOUND: dict[str, tuple[str, str, Scenario]] = {
    "Q-TEST-THING-GET": (_GET, "read", _scenario("get one", _THING_PARAMS, GET_ROWS)),
    "Q-TEST-THING-LIST": (
        "MATCH (n:ProbeThing {tenantId: $tenant}) RETURN n.id AS id ORDER BY n.rank",
        "read",
        _scenario(
            "list all",
            {},
            Expect(
                rows=({"id": "thing-1"}, {"id": "thing-2"}, {"id": Unique("res-1", "resource_id")})
            ),
            lookup=(),
        ),
    ),
    "Q-TEST-THING-NEXT": (
        "MATCH (a:ProbeThing {id: $id, tenantId: $tenant})-[:NEXT]->"
        "(b:ProbeThing {tenantId: $tenant}) RETURN b.id AS id",
        "read",
        _scenario("follow a link", _THING_PARAMS, Expect(rows=({"id": "thing-2"},))),
    ),
    "Q-TEST-THING-SET": (
        "MATCH (n:ProbeThing {id: $id, tenantId: $tenant}) SET n.note = $note "
        "RETURN count(n) AS changed",
        "write",
        _scenario(
            "change a note",
            {"id": "thing-1", "note": "changed"},
            Expect(
                rows=({"changed": 1},),
                after=(NodeSpec(THING, {"id": "thing-1", "note": "changed"}),),
            ),
            new=("note",),
        ),
    ),
    "Q-TEST-THING-ADD": (
        "MERGE (n:ProbeThing {id: $id, tenantId: $tenant}) ON CREATE SET n.note = $note "
        "RETURN count(n) AS merged",
        "write",
        _scenario(
            "merge a new thing",
            {"id": "thing-new", "note": "fresh"},
            Expect(
                rows=({"merged": 1},),
                nodes={"ProbeThing": 1},
                after=(NodeSpec(THING, {"id": "thing-new", "note": "fresh"}),),
            ),
            lookup=(),
            new=("id", "note"),
        ),
    ),
    "Q-TEST-THING-DROP": (
        "MATCH (n:ProbeThing {id: $id, tenantId: $tenant}) DETACH DELETE n",
        "write",
        _scenario(
            "delete a thing",
            {"id": "thing-2"},
            Expect(
                nodes={"ProbeThing": -1},
                rels={"NEXT": -1},
                gone=(NodeSpec(THING, {"id": "thing-2"}),),
            ),
        ),
    ),
    "Q-TEST-THING-UNIQUE": (
        "MATCH (n:ProbeThing {id: $id, tenantId: $tenant}) SET n.id = n.id RETURN n.note AS note",
        "write",
        _scenario(
            "lock a thing by a value two tenants cannot share",
            {"id": Unique("res-1", "resource_id")},
            Expect(rows=({"note": Marked("res")},)),
        ),
    ),
}

# Each leaky twin names the kind of finding it must produce. The expectation of its scenario is
# what the sound statement would do, so the twin differs from it only by the leak.
LEAKY: dict[str, tuple[str, str, Scenario, FindingKind]] = {
    "Q-TEST-LEAK-LABEL-ONLY": (
        "MATCH (n:ProbeThing {id: $id}) RETURN n.id AS id, n.note AS note",
        "read",
        _scenario("label only", _THING_PARAMS, GET_ROWS),
        FindingKind.ROWS_DIFFER,
    ),
    "Q-TEST-LEAK-AGGREGATE": (
        "MATCH (n:ProbeThing) RETURN count(n) AS total",
        "read",
        _scenario("count them all", {}, Expect(rows=({"total": 3},)), lookup=()),
        FindingKind.ROWS_DIFFER,
    ),
    "Q-TEST-LEAK-UNSTAMPED-MERGE": (
        "MERGE (n:ProbeThing {id: $id}) ON CREATE SET n.note = $note RETURN count(n) AS merged",
        "write",
        _scenario(
            "merge with no tenant",
            {"id": "thing-new", "note": "fresh"},
            Expect(rows=({"merged": 1},), nodes={"ProbeThing": 1}),
            lookup=(),
        ),
        FindingKind.UNSTAMPED_NODE,
    ),
    "Q-TEST-LEAK-SET-REPLACE": (
        "MATCH (n:ProbeThing {id: $id, tenantId: $tenant}) SET n = $props "
        "RETURN count(n) AS changed",
        "write",
        _scenario(
            "replace the whole node",
            {"id": "thing-1", "props": {"id": "thing-1", "note": "changed"}},
            Expect(rows=({"changed": 1},), after=(NodeSpec(THING, {"note": "changed"}),)),
        ),
        FindingKind.UNSTAMPED_NODE,
    ),
    "Q-TEST-LEAK-WRITE-OTHER": (
        "MATCH (n:ProbeThing {id: $id}) SET n.note = $note RETURN count(n) AS changed",
        "write",
        _scenario(
            "write to every match",
            {"id": "thing-1", "note": "changed"},
            Expect(
                rows=({"changed": 1},),
                after=(NodeSpec(THING, {"id": "thing-1", "note": "changed"}),),
            ),
        ),
        FindingKind.OTHER_TENANT_CHANGED,
    ),
    "Q-TEST-LEAK-CROSS-LINK": (
        "MATCH (a:ProbeThing {id: $id, tenantId: $tenant}) "
        "MATCH (b:ProbeThing {id: $other}) WHERE b.tenantId <> $tenant "
        "CREATE (a)-[:LINKS]->(b) RETURN count(b) AS linked",
        "write",
        _scenario(
            "link to the other tenant",
            {"id": "thing-1", "other": "thing-2"},
            Expect(rows=({"linked": 0},)),
        ),
        FindingKind.CROSS_SCOPE_RELATIONSHIP,
    ),
    "Q-TEST-LEAK-FOREIGN-ID": (
        "MATCH (n:ProbeThing {id: $id}) RETURN n.note AS note",
        "read",
        _scenario(
            "read by an id the other tenant owns",
            {"id": Unique("res-1", "resource_id")},
            Expect(rows=({"note": Marked("res")},)),
        ),
        FindingKind.FOREIGN_ID_EFFECT,
    ),
    "Q-TEST-LEAK-FOREIGN-COPY": (
        "MATCH (n:ProbeThing {id: $id}) "
        "MATCH (m:ProbeThing {id: 'thing-1', tenantId: $tenant}) "
        "SET m.note = n.note RETURN count(m) AS copied",
        "write",
        _scenario(
            "copy a note from the node of an id the other tenant owns",
            {"id": Unique("res-1", "resource_id")},
            Expect(
                rows=({"copied": 1},),
                after=(NodeSpec(THING, {"id": "thing-1", "note": Marked("res")}),),
            ),
        ),
        FindingKind.FOREIGN_ID_EFFECT,
    ),
    "Q-TEST-LEAK-OWN-STATE": (
        "MATCH (n:ProbeThing {id: $id, tenantId: $tenant}) "
        "OPTIONAL MATCH (o:ProbeThing {id: $id}) WHERE o.tenantId <> $tenant "
        "SET n.note = coalesce(o.note, 'alone') RETURN count(n) AS changed",
        "write",
        _scenario(
            "set a note from the other tenant's node, returning only a count",
            _THING_PARAMS,
            Expect(
                rows=({"changed": 1},),
                after=(NodeSpec(THING, {"id": "thing-1", "note": "alone"}),),
            ),
        ),
        FindingKind.OWN_STATE_DIFFERS,
    ),
    "Q-TEST-LEAK-WRONG-ROWS": (
        _GET,
        "read",
        _scenario(
            "a scenario that expects other rows", _THING_PARAMS, Expect(rows=({"id": "nope"},))
        ),
        FindingKind.UNEXPECTED_ROWS,
    ),
    "Q-TEST-LEAK-HIDDEN-WRITE": (
        "MATCH (n:ProbeThing {id: $id, tenantId: $tenant}) SET n.note = 'touched' "
        "RETURN n.id AS id",
        "read",
        _scenario("a read that writes", _THING_PARAMS, Expect(rows=({"id": "thing-1"},))),
        FindingKind.UNEXPECTED_EFFECT,
    ),
    "Q-TEST-LEAK-NOT-VALID": (
        "MATCH (n:ProbeThing {id: $id, tenantId: $tenant}) RETURN n.id AS id, nope(",
        "read",
        _scenario("a statement the server refuses", _THING_PARAMS, GET_ROWS),
        FindingKind.PROBE_ERROR,
    ),
    # The shapes the registration check cannot see (TEN-001 verification): each mentions $tenant,
    # and each leaks.
    "Q-TEST-LEAK-REBOUND": (
        "MATCH (a:ProbeThing {id: $id, tenantId: $tenant}) WITH count(a) AS c "
        "MATCH (b:ProbeThing {id: $id}) RETURN c AS found, b.note AS note",
        "read",
        _scenario(
            "re-bound after WITH",
            _THING_PARAMS,
            Expect(rows=({"found": 1, "note": Marked("one")},)),
        ),
        FindingKind.ROWS_DIFFER,
    ),
    "Q-TEST-LEAK-SUBQUERY": (
        "MATCH (a:ProbeThing {id: $id, tenantId: $tenant}) "
        "CALL { MATCH (x:ProbeThing {id: $id}) RETURN x.note AS note } RETURN a.id AS id, note",
        "read",
        _scenario("a subquery with its own unstamped variable", _THING_PARAMS, GET_ROWS),
        FindingKind.ROWS_DIFFER,
    ),
    "Q-TEST-LEAK-UNION": (
        "MATCH (n:ProbeThing {id: $id, tenantId: $tenant}) RETURN n.note AS note "
        "UNION MATCH (n:ProbeThing {id: $id}) RETURN n.note AS note",
        "read",
        _scenario(
            "a union branch with no tenant", _THING_PARAMS, Expect(rows=({"note": Marked("one")},))
        ),
        FindingKind.ROWS_DIFFER,
    ),
    "Q-TEST-LEAK-OR-TRUE": (
        "MATCH (n:ProbeThing {id: $id}) WHERE n.tenantId = $tenant OR true RETURN n.note AS note",
        "read",
        _scenario(
            "a predicate that is true for every tenant",
            _THING_PARAMS,
            Expect(rows=({"note": Marked("one")},)),
        ),
        FindingKind.ROWS_DIFFER,
    ),
    "Q-TEST-LEAK-NESTED-MAP": (
        "MATCH (n:ProbeThing {id: $id}) RETURN {tenantId: $tenant, note: n.note} AS row",
        "read",
        _scenario(
            "a stamp inside a nested map",
            _THING_PARAMS,
            Expect(rows=({"row": {"note": Marked("one")}},)),
        ),
        FindingKind.ROWS_DIFFER,
    ),
    # A scenario must observe something (round 2): these two return nothing and change nothing.
    "Q-TEST-LEAK-VACUOUS-WRITE": (
        "MATCH (n:ProbeThing {id: $id, tenantId: $tenant}) WITH n LIMIT 0 SET n.note = 'touched'",
        "write",
        _scenario("a write that changes nothing", _THING_PARAMS, Expect()),
        FindingKind.VACUOUS_SCENARIO,
    ),
    "Q-TEST-LEAK-VACUOUS-READ": (
        "MATCH (n:ProbeThing {id: $id, tenantId: $tenant}) WHERE n.rank = 99 RETURN n.id AS id",
        "read",
        _scenario("a read that never matches", _THING_PARAMS, Expect()),
        FindingKind.VACUOUS_SCENARIO,
    ),
    "Q-TEST-LEAK-NEGATED": (
        "MATCH (n:ProbeThing {id: $id}) WHERE n.tenantId <> $tenant RETURN n.note AS note",
        "read",
        _scenario(
            "a negated tenant predicate", _THING_PARAMS, Expect(rows=({"note": Marked("one")},))
        ),
        FindingKind.ROWS_DIFFER,
    ),
}


def _private_registry() -> QueryRegistry:
    registry = QueryRegistry(unconverted=frozenset(LEAKY))
    for query_id, (cypher, mode, scenario) in SOUND.items():
        registry.register(NamedQuery(id=query_id, cypher=cypher, mode=mode, scenario=scenario))  # type: ignore[arg-type]
    for query_id, (cypher, mode, scenario, _) in LEAKY.items():
        registry.register(NamedQuery(id=query_id, cypher=cypher, mode=mode, scenario=scenario))  # type: ignore[arg-type]
    return registry


@pytest.fixture(scope="module")
def private() -> QueryRegistry:
    return _private_registry()


def _statements(registry: QueryRegistry, ids: list[str]) -> dict[str, NamedQuery]:
    return {i: registry.get(i) for i in ids}


async def _run(
    driver: AsyncDriver,
    registry: QueryRegistry,
    ids: list[str],
    tenant_id: str,
    other_tenant_id: str,
) -> list[Finding]:
    return await run_isolation(
        driver,
        _statements(registry, ids),
        registry=registry,
        tenant_a=tenant_id,
        tenant_b=other_tenant_id,
    )


async def _nodes(driver: AsyncDriver) -> list[dict[str, object]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, object]]:
        query = (
            "MATCH (n:ProbeThing) RETURN labels(n) AS labels, n.id AS id, n.note AS note, "
            "n.tenantId AS tenant, n.seedMarker AS marker"
        )
        return await (await tx.run(query)).data()

    return await read_tx(driver, work)


# The seed


async def test_the_seed_gives_both_tenants_the_same_keys_and_distinct_text(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await seed_tenant(neo4j_driver, tenant_id, "A", SEED)
    await seed_tenant(neo4j_driver, other_tenant_id, "B", SEED)
    rows = await _nodes(neo4j_driver)
    mine = {r["id"]: r for r in rows if r["tenant"] == tenant_id}
    theirs = {r["id"]: r for r in rows if r["tenant"] == other_tenant_id}
    assert len(rows) == 6
    # The key is shared, except where a unique constraint of the real schema forbids it.
    assert {"thing-1", "thing-2"} <= set(mine) & set(theirs)
    assert set(mine) - set(theirs) == {"res-1"}
    assert set(theirs) - set(mine) == {"res-1-B"}
    for key in ("thing-1", "thing-2"):
        assert mine[key]["note"] != theirs[key]["note"]
    assert {r["marker"] for r in mine.values()} == {"A"}
    assert {r["marker"] for r in theirs.values()} == {"B"}
    assert mine["thing-1"]["note"] == "one-A"
    assert theirs["thing-1"]["note"] == "one-B"


async def test_the_real_schema_refuses_a_value_two_tenants_cannot_share(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """Why `Unique` exists: the same `Resource` id for two tenants is refused by the real schema."""
    plain = TenantSeed(nodes=(SeedNode("r", ("Resource", "ProbeThing"), {"id": "res-1"}),))
    await seed_tenant(neo4j_driver, tenant_id, "A", plain)
    with pytest.raises(Exception, match="already exists"):
        await seed_tenant(neo4j_driver, other_tenant_id, "B", plain)


async def test_a_seed_that_leaves_a_node_unstamped_is_refused(
    neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    """The seeder checks its own work: every node it made carries the tenant and the marker."""

    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run("CREATE (:ProbeThing {id: 'stray'})")

    await write_tx(neo4j_driver, work)
    with pytest.raises(AssertionError, match="unstamped"):
        await seed_tenant(neo4j_driver, tenant_id, "A", SEED)


# The test accepts what is sound and catches what leaks


async def test_the_harness_accepts_the_sound_statements(
    neo4j_driver: AsyncDriver, private: QueryRegistry, tenant_id: str, other_tenant_id: str
) -> None:
    findings = await _run(neo4j_driver, private, list(SOUND), tenant_id, other_tenant_id)
    assert findings == [], format_findings(findings)


@pytest.mark.parametrize("query_id", sorted(LEAKY))
async def test_the_harness_flags_each_leaky_statement(
    query_id: str,
    neo4j_driver: AsyncDriver,
    private: QueryRegistry,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    expected = LEAKY[query_id][3]
    findings = await _run(neo4j_driver, private, [query_id], tenant_id, other_tenant_id)
    assert findings, f"{query_id} leaks and the generated test found nothing"
    assert expected in {f.kind for f in findings}, format_findings(findings)
    assert {f.query_id for f in findings} == {query_id}


async def test_every_sound_scenario_of_the_corpus_is_a_valid_scenario() -> None:
    for query_id, (_, _, scenario) in SOUND.items():
        assert validate_scenario(query_id, scenario) == [], query_id


_FRESH_MERGE = (
    "MERGE (n:ProbeThing {id: $id}) ON CREATE SET n.tenantId = $tenant "
    "ON MATCH SET n.note = $note RETURN count(n) AS merged"
)


async def test_a_merge_that_stamps_only_on_create_is_refused_when_run_with_a_fresh_id() -> None:
    """The verifier's 6b. With `lookup=()` and an id the seed does not hold, the other tenant never
    holds the id either, so the leaking branch (ON MATCH) is never reached and the runner finds
    nothing: the validator is what refuses the scenario."""
    scenario = _scenario(
        "merge a fresh id",
        {"id": "thing-fresh", "note": "changed"},
        Expect(rows=({"merged": 1},), nodes={"ProbeThing": 1}),
        lookup=(),
        new=("note",),
    )
    problems = validate_scenario("Q-TEST-LEAK-FRESH-MERGE", scenario)
    assert any("'id'" in problem for problem in problems), problems


async def test_the_same_merge_with_an_id_the_seed_holds_is_caught(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    scenario = _scenario(
        "merge an id both tenants hold",
        {"id": "thing-1", "note": "changed"},
        Expect(
            rows=({"merged": 1},),
            after=(NodeSpec(THING, {"id": "thing-1", "note": "changed"}),),
        ),
        new=("note",),
    )
    assert validate_scenario("Q-TEST-LEAK-HELD-MERGE", scenario) == []
    registry = QueryRegistry(unconverted=frozenset({"Q-TEST-LEAK-HELD-MERGE"}))
    registry.register(
        NamedQuery(
            id="Q-TEST-LEAK-HELD-MERGE", cypher=_FRESH_MERGE, mode="write", scenario=scenario
        )
    )
    findings = await _run(
        neo4j_driver, registry, ["Q-TEST-LEAK-HELD-MERGE"], tenant_id, other_tenant_id
    )
    assert FindingKind.OTHER_TENANT_CHANGED in {f.kind for f in findings}, format_findings(findings)


async def test_a_leak_that_shows_in_one_direction_is_found_in_the_other_too(
    neo4j_driver: AsyncDriver, private: QueryRegistry, tenant_id: str, other_tenant_id: str
) -> None:
    findings = await _run(
        neo4j_driver, private, ["Q-TEST-LEAK-LABEL-ONLY"], tenant_id, other_tenant_id
    )
    assert {f.phase for f in findings} == {"A-then-B", "B-then-A"}


async def test_a_statement_with_no_scenario_is_not_run_by_the_runner(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """`scenario_gaps` and the ratchet refuse it; the runner has nothing to run for it."""
    registry = QueryRegistry(unconverted=frozenset({"Q-TEST-BARE"}))
    bare = NamedQuery(id="Q-TEST-BARE", cypher="MATCH (n:ProbeThing) RETURN n", mode="read")
    registry.register(bare)
    findings = await run_isolation(
        neo4j_driver,
        {"Q-TEST-BARE": bare},
        registry=registry,
        tenant_a=tenant_id,
        tenant_b=other_tenant_id,
    )
    assert findings == []
    assert scenario_gaps({"Q-TEST-BARE": bare}, frozenset()) != []


async def test_a_probe_error_names_the_exception_class_and_never_the_text_or_a_value(
    neo4j_driver: AsyncDriver, private: QueryRegistry, tenant_id: str, other_tenant_id: str
) -> None:
    findings = await _run(
        neo4j_driver, private, ["Q-TEST-LEAK-NOT-VALID"], tenant_id, other_tenant_id
    )
    assert findings
    for finding in findings:
        assert finding.kind is FindingKind.PROBE_ERROR
        assert finding.detail == "CypherSyntaxError"
        assert "nope" not in format_findings([finding])
        assert tenant_id not in format_findings([finding])


async def test_the_runner_never_prints_a_tenant_id_or_a_value(
    neo4j_driver: AsyncDriver, private: QueryRegistry, tenant_id: str, other_tenant_id: str
) -> None:
    findings = await _run(neo4j_driver, private, sorted(LEAKY), tenant_id, other_tenant_id)
    text = format_findings(findings)
    assert text
    for secret in (tenant_id, other_tenant_id, "one-A", "one-B", "thing-1"):
        assert secret not in text


async def test_a_template_scenario_runs_its_instance(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """A template with a scenario is run through its `insert`, as the resource store will."""
    from diucs.adapters.outbound.graph_store.queries import QueryTemplate

    registry = QueryRegistry()
    registry.register_template(
        QueryTemplate(
            id="Q-TPL-PROBE-GET",
            cypher=(
                "MATCH (n{insert} {id: $id, tenantId: $tenant}) RETURN n.id AS id, n.note AS note"
            ),
            mode="read",
            scenario=_scenario("a template", _THING_PARAMS, GET_ROWS, insert=":ProbeThing"),
        )
    )
    statements = production_statements(registry)
    assert list(statements) == ["Q-TPL-PROBE-GET"]
    findings = await run_isolation(
        neo4j_driver, statements, registry=registry, tenant_a=tenant_id, tenant_b=other_tenant_id
    )
    assert findings == [], format_findings(findings)


# The proof over the registry


async def test_every_converted_statement_is_isolated(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    statements = production_statements(REGISTRY)
    assert registry_problems(REGISTRY) == []
    assert universe_problems(REGISTRY, statements) == []
    assert scenario_gaps(statements, UNCONVERTED) == []
    with_scenario = {i: q for i, q in statements.items() if q.scenario is not None}
    assert len(with_scenario) >= 8
    findings = await run_isolation(
        neo4j_driver,
        with_scenario,
        registry=REGISTRY,
        tenant_a=tenant_id,
        tenant_b=other_tenant_id,
    )
    assert findings == [], "\n" + format_findings(findings)


_SNEAK_TEXT = (
    "MATCH (n:ProbeThing {id: $id}) WHERE n.tenantId = $tenant OR true "
    "RETURN n.id AS id, n.note AS note"
)


async def test_a_leaky_statement_named_q_test_in_the_production_registry_is_caught(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """The verifier's Q-TEST-SNEAK (round 1, B1): a name must not hide a statement from the proof.
    In a scratch copy of the production registry it is refused by the hygiene check, it is in the
    universe the generated test runs, and the run finds its leak."""
    sneak = NamedQuery(
        id="Q-TEST-SNEAK",
        cypher=_SNEAK_TEXT,
        mode="read",
        scenario=_scenario("get one", _THING_PARAMS, GET_ROWS),
    )
    REGISTRY.register(sneak)
    try:
        assert any("Q-TEST-SNEAK" in p for p in registry_problems(REGISTRY))
        statements = production_statements(REGISTRY)
        assert statements["Q-TEST-SNEAK"] == sneak
        assert universe_problems(REGISTRY, statements) == []
        findings = await run_isolation(
            neo4j_driver,
            {"Q-TEST-SNEAK": statements["Q-TEST-SNEAK"]},
            registry=REGISTRY,
            tenant_a=tenant_id,
            tenant_b=other_tenant_id,
        )
    finally:
        del REGISTRY._queries["Q-TEST-SNEAK"]  # noqa: SLF001
    assert FindingKind.ROWS_DIFFER in {f.kind for f in findings}, format_findings(findings)


async def test_the_converted_statements_are_exactly_those_with_a_scenario() -> None:
    """The loop above runs `with_scenario`; this shows it cannot silently skip a converted id."""
    statements = production_statements(REGISTRY)
    converted = {i for i, q in statements.items() if i not in UNCONVERTED}
    with_scenario = {i for i, q in statements.items() if q.scenario is not None}
    assert converted == with_scenario


async def test_removing_the_tenant_predicate_makes_the_generated_test_fail(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """The predicate-removal check, for every converted statement: a scratch copy with every
    `tenantId: $tenant` taken out is caught by the generated test, and the original is clean."""
    statements = production_statements(REGISTRY)
    converted = sorted(i for i in statements if i not in UNCONVERTED)
    assert len(converted) >= 8
    survivors: list[str] = []
    for query_id in converted:
        original = statements[query_id]
        assert predicate_count(original.cypher) >= 1, query_id
        registry, mutant = mutant_of(original)
        found = await run_isolation(
            neo4j_driver,
            {query_id: mutant},
            registry=registry,
            tenant_a=tenant_id,
            tenant_b=other_tenant_id,
        )
        if not found:
            survivors.append(query_id)
        clean = await run_isolation(
            neo4j_driver,
            {query_id: original},
            registry=REGISTRY,
            tenant_a=tenant_id,
            tenant_b=other_tenant_id,
        )
        assert clean == [], format_findings(clean)
    assert survivors == [], f"these ran without their tenant predicate unnoticed: {survivors}"


# The schema the scenarios lean on


async def test_the_constraint_table_is_the_live_schema(neo4j_driver: AsyncDriver) -> None:
    """`Unique` is allowed only where a single-property unique constraint really exists. When
    TEN-005 replaces one with a composite key this fails until the table loses it."""

    async def work(tx: AsyncManagedTransaction) -> list[dict[str, object]]:
        query = (
            "SHOW CONSTRAINTS YIELD name, type, entityType, labelsOrTypes, properties "
            "WHERE type = 'UNIQUENESS' AND entityType = 'NODE' AND size(properties) = 1 "
            "RETURN name, labelsOrTypes[0] AS label, properties[0] AS property"
        )
        return await (await tx.run(query)).data()

    rows = await read_tx(neo4j_driver, work)
    live = {str(r["name"]): (str(r["label"]), str(r["property"])) for r in rows}
    assert live == dict(SINGLE_PROPERTY_UNIQUE)
