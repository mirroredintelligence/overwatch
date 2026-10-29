"""The scenario a registered statement carries, and the rules that reject a bad one (TEN-004).

A scenario is the seed for two tenants that share their keys, the parameters, and the effect the
statement must have for the caller. `validate_scenario` is the gate: a scenario whose keys do not
collide across the tenants proves nothing, so it is refused. All values are synthetic.
"""

import re

import pytest

from diucs.adapters.outbound.graph_store import migrations
from diucs.adapters.outbound.graph_store.queries import Scenario as ScenarioFromQueries
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
    collision_blocked,
    constraints_used,
    render,
    validate_scenario,
)

QID = "Q-X-THING"


def _thing(**props: object) -> SeedNode:
    return SeedNode("t", ("Resource", "Thing"), {"id": Unique("thing-1", "resource_id"), **props})


def _sound() -> Scenario:
    """A read by a key that both tenants share (the key is not unique-constrained today)."""
    return Scenario(
        "read a thing by its key",
        seed=TenantSeed(
            nodes=(
                _thing(key="Thing/1", note=Marked("note")),
                SeedNode("d", ("Detail",), {"text": Marked("detail")}),
            ),
            rels=(SeedRel("d", "OF", "t"),),
        ),
        params={"key": "Thing/1"},
        lookup=("key",),
        expect=Expect(rows=({"note": Marked("note")},)),
    )


# Rendering


def test_a_marked_value_renders_per_tenant_slot() -> None:
    assert render(Marked("note"), "A") == "note-A"
    assert render(Marked("note"), "B") == "note-B"


def test_a_unique_value_renders_plain_for_a_and_suffixed_for_b() -> None:
    value = Unique("thing-1", "resource_id")
    assert render(value, "A") == "thing-1"
    assert render(value, "B") == "thing-1-B"


def test_render_walks_mappings_lists_and_tuples_and_leaves_other_values_alone() -> None:
    value = {"a": [Marked("x"), 3, None], "b": (Unique("u", "resource_id"), True), "c": {"d": "e"}}
    assert render(value, "B") == {"a": ["x-B", 3, None], "b": ["u-B", True], "c": {"d": "e"}}


# The type


def test_the_placeholder_form_of_a_scenario_still_builds_and_is_the_same_type() -> None:
    assert ScenarioFromQueries is Scenario
    plain = Scenario("placeholder")
    assert plain == Scenario("placeholder")
    assert hash(plain) == hash(Scenario("placeholder"))
    assert hash(_sound()) == hash(_sound())
    assert _sound() != Scenario("read a thing by its key")


def test_the_mappings_of_a_scenario_are_read_only() -> None:
    scenario = _sound()
    with pytest.raises(TypeError):
        scenario.params["key"] = "other"  # type: ignore[index]
    with pytest.raises(TypeError):
        scenario.seed.nodes[0].props["key"] = "other"  # type: ignore[index]
    with pytest.raises(TypeError):
        NodeSpec(("Thing",), {"a": 1}).props["a"] = 2  # type: ignore[index]
    with pytest.raises(TypeError):
        Expect(nodes={"Thing": 1}).nodes["Thing"] = 2  # type: ignore[index]
    with pytest.raises(TypeError):
        Expect(rels={"OF": 1}).rels["OF"] = 2  # type: ignore[index]


# What a sound scenario looks like


def test_a_sound_scenario_has_no_problem_and_is_not_collision_blocked() -> None:
    assert validate_scenario(QID, _sound()) == []
    assert collision_blocked(_sound()) is False


def test_a_scenario_whose_every_lookup_is_unique_is_valid_and_collision_blocked() -> None:
    """The record key is unique-constrained today (migration 0030), so the two tenants cannot
    share it. That is the one exemption, and it is stated by the value type, not by a flag."""
    scenario = Scenario(
        "mark a message",
        seed=TenantSeed(
            nodes=(
                SeedNode("p", ("Processed",), {"key": Unique("c:m-1", "processed_key")}),
                SeedNode("q", ("Processed",), {"key": Unique("c:m-2", "processed_key"), "n": 1}),
            )
        ),
        params={"key": Unique("c:m-1", "processed_key")},
        lookup=("key",),
    )
    assert validate_scenario(QID, scenario) == []
    assert collision_blocked(scenario) is True


def test_a_scenario_with_no_lookup_needs_a_value_both_tenants_share() -> None:
    scenario = Scenario(
        "list the pending messages",
        seed=TenantSeed(
            nodes=(
                SeedNode("a", ("Outbox",), {"id": Unique("m-1", "outbox_message_id"), "s": "up"}),
            )
        ),
        params={"limit": 10},
    )
    assert validate_scenario(QID, scenario) == []
    assert collision_blocked(scenario) is False


def test_constraints_used_lists_every_constraint_a_scenario_leans_on() -> None:
    scenario = Scenario(
        "mark a message",
        seed=TenantSeed(
            nodes=(
                SeedNode("p", ("Processed",), {"key": Unique("c:m-1", "processed_key")}),
                SeedNode(
                    "r", ("Resource", "T"), {"id": Unique("r-1", "resource_id"), "n": Marked("n")}
                ),
            )
        ),
        params={
            "key": Unique("c:m-1", "processed_key"),
            "nested": [{"id": Unique("x", "device_id")}],
        },
        lookup=("key",),
        expect=Expect(
            rows=({"id": Unique("r-1", "resource_id")},),
            after=(NodeSpec(("T",), {"id": Unique("y", "outbox_message_id")}),),
            gone=(NodeSpec(("T",), {"id": Unique("z", "report_flag_id")}),),
        ),
    )
    assert constraints_used(scenario) == {
        "processed_key",
        "resource_id",
        "device_id",
        "outbox_message_id",
        "report_flag_id",
    }
    assert (
        constraints_used(_with(_sound(), seed=TenantSeed(nodes=(SeedNode("a", ("A",), {"k": 1}),))))
        == frozenset()
    )


# What is refused


def _with(scenario: Scenario, **changes: object) -> Scenario:
    fields = {
        "description": scenario.description,
        "seed": scenario.seed,
        "params": scenario.params,
        "lookup": scenario.lookup,
        "expect": scenario.expect,
        "insert": scenario.insert,
    }
    fields.update(changes)
    return Scenario(**fields)  # type: ignore[arg-type]


def _problems(scenario: Scenario) -> list[str]:
    return validate_scenario(QID, scenario)


def _assert_refused(scenario: Scenario, fragment: str) -> None:
    problems = _problems(scenario)
    assert problems, "the scenario was accepted"
    assert any(fragment in problem for problem in problems), problems
    assert all(QID in problem for problem in problems), problems


def test_an_empty_seed_is_refused() -> None:
    _assert_refused(_with(_sound(), seed=TenantSeed()), "no nodes")


def test_a_duplicate_ref_is_refused() -> None:
    nodes = (SeedNode("t", ("Thing",), {"key": "Thing/1", "n": Marked("n")}),) * 2
    _assert_refused(_with(_sound(), seed=TenantSeed(nodes=nodes)), "twice")


@pytest.mark.parametrize("end", ["start", "end"])
def test_a_relationship_to_an_unknown_ref_is_refused(end: str) -> None:
    rel = SeedRel("zz", "OF", "t") if end == "start" else SeedRel("t", "OF", "zz")
    seed = TenantSeed(nodes=_sound().seed.nodes, rels=(rel,))
    _assert_refused(_with(_sound(), seed=seed), "unknown ref")


@pytest.mark.parametrize(
    "node",
    [
        SeedNode("t", ("bad label",), {"key": "Thing/1", "n": Marked("n")}),
        SeedNode("t", (), {"key": "Thing/1", "n": Marked("n")}),
        SeedNode("t", ("Thing",), {"bad prop": "Thing/1", "n": Marked("n")}),
    ],
)
def test_a_bad_label_or_property_name_is_refused(node: SeedNode) -> None:
    _assert_refused(_with(_sound(), seed=TenantSeed(nodes=(node,))), "name")


def test_a_bad_relationship_type_is_refused() -> None:
    seed = TenantSeed(nodes=_sound().seed.nodes, rels=(SeedRel("d", "bad type", "t"),))
    _assert_refused(_with(_sound(), seed=seed), "name")


@pytest.mark.parametrize("reserved", ["tenantId", "seedMarker"])
def test_a_seed_may_not_set_the_tenant_or_the_marker(reserved: str) -> None:
    node = SeedNode("t", ("Thing",), {"key": "Thing/1", "n": Marked("n"), reserved: "x"})
    _assert_refused(_with(_sound(), seed=TenantSeed(nodes=(node,))), "reserved")


@pytest.mark.parametrize("reserved", ["tenant", "parameters"])
def test_the_parameters_may_not_name_the_tenant(reserved: str) -> None:
    _assert_refused(_with(_sound(), params={"key": "Thing/1", reserved: "x"}), "reserved")


def test_an_expectation_may_not_name_the_tenant() -> None:
    expect = Expect(after=(NodeSpec(("Thing",), {"tenantId": "x"}),))
    _assert_refused(_with(_sound(), expect=expect), "reserved")


def test_a_lookup_must_name_a_parameter() -> None:
    _assert_refused(_with(_sound(), lookup=("missing",)), "not a parameter")


def test_a_lookup_value_that_the_seed_does_not_hold_selects_nothing() -> None:
    """The keys do not collide, because nothing in the seed carries this one."""
    _assert_refused(_with(_sound(), params={"key": "Thing/other"}), "collide")


def test_a_lookup_value_that_differs_between_the_tenants_is_refused() -> None:
    seed = TenantSeed(nodes=(_thing(key=Marked("Thing/1")),))
    scenario = _with(_sound(), seed=seed, params={"key": Marked("Thing/1")})
    _assert_refused(scenario, "differs between the tenants")


def test_a_unique_value_must_name_a_known_single_property_constraint() -> None:
    node = SeedNode("t", ("Thing",), {"key": Unique("Thing/1", "no_such_constraint")})
    scenario = _with(
        _sound(),
        seed=TenantSeed(nodes=(node, SeedNode("m", ("M",), {"x": Marked("x")}))),
        params={"key": Unique("Thing/1", "no_such_constraint")},
    )
    _assert_refused(scenario, "constraint")


def test_a_unique_value_must_sit_on_the_label_and_property_of_its_constraint() -> None:
    wrong_label = SeedNode("t", ("Thing",), {"key": Unique("c:m-1", "processed_key")})
    wrong_prop = SeedNode("t", ("Processed",), {"other": Unique("c:m-1", "processed_key")})
    for node in (wrong_label, wrong_prop):
        scenario = _with(
            _sound(),
            seed=TenantSeed(nodes=(node, SeedNode("m", ("M",), {"x": Marked("x")}))),
            params={"key": Unique("c:m-1", "processed_key")},
        )
        _assert_refused(scenario, "constraint")


def test_a_seed_with_no_per_tenant_value_cannot_tell_the_tenants_apart() -> None:
    seed = TenantSeed(nodes=(SeedNode("t", ("Thing",), {"key": "Thing/1", "note": "same"}),))
    _assert_refused(_with(_sound(), seed=seed), "tell the tenants apart")


def test_with_no_lookup_a_seed_of_only_per_tenant_values_shares_nothing() -> None:
    seed = TenantSeed(nodes=(SeedNode("t", ("Thing",), {"note": Marked("n")}),))
    _assert_refused(_with(_sound(), seed=seed, lookup=(), params={}), "share no value")


def test_a_marked_or_unique_value_must_be_text() -> None:
    node = SeedNode("t", ("Thing",), {"key": "Thing/1", "n": Marked(3)})  # type: ignore[arg-type]
    _assert_refused(_with(_sound(), seed=TenantSeed(nodes=(node,))), "text")
    node = SeedNode("t", ("Thing",), {"key": "Thing/1", "n": Unique(3, "resource_id")})  # type: ignore[arg-type]
    _assert_refused(_with(_sound(), seed=TenantSeed(nodes=(node,))), "text")


def test_every_problem_names_the_query_and_never_a_value() -> None:
    node = SeedNode("t", ("Thing",), {"secret": "SYNTHETIC-VALUE", "tenantId": "SYNTHETIC-TENANT"})
    scenario = _with(_sound(), seed=TenantSeed(nodes=(node,)), params={"key": "SYNTHETIC-KEY"})
    problems = _problems(scenario)
    assert problems
    text = " ".join(problems)
    assert QID in text
    for value in ("SYNTHETIC-VALUE", "SYNTHETIC-TENANT", "SYNTHETIC-KEY"):
        assert value not in text


# The constraint table


_SINGLE = re.compile(
    r"CREATE CONSTRAINT (\w+) IF NOT EXISTS FOR \(n:(\w+)\) REQUIRE n\.(\w+) IS UNIQUE"
)


def test_the_constraint_table_is_the_single_property_unique_constraints_of_the_migrations() -> None:
    """A single-property unique key is what stops two tenants sharing a value today. The table
    names each, so a `Unique` value can only stand where a constraint really forces it. TEN-005
    replaces them with composite keys and empties the table (the live schema is checked in
    tests/integration/graph_store/test_tenant_isolation.py)."""
    found = {
        name: (label, prop)
        for _, statement in migrations.MIGRATIONS
        for name, label, prop in _SINGLE.findall(statement)
    }
    assert found, "the scan found no constraint: it is not looking at the migrations"
    assert dict(SINGLE_PROPERTY_UNIQUE) == found
