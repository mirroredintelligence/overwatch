"""The pure parts of the generated two-tenant test (TEN-004): the statement universe, the gaps and
the ratchet, row and effect comparison, and how findings are written. All values are synthetic.
"""

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store.queries import (
    NamedQuery,
    QueryRegistry,
    QueryTemplate,
)
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    Unique,
)
from tests.support.query_probes import (
    Finding,
    FindingKind,
    effect_problems,
    format_findings,
    normalised,
    production_statements,
    ratchet_problems,
    row_problems,
    scenario_gaps,
)
from tests.support.tenant_seed import Node, Rel, Snapshot

SC = Scenario("a scenario")
TENANT_CYPHER = "MATCH (n:X {tenantId: $tenant}) RETURN n"
OLD_CYPHER = "MATCH (n:X) RETURN n"


def _registry() -> QueryRegistry:
    registry = QueryRegistry(unconverted=frozenset({"Q-OLD", "Q-TPL-OLD", "Q-TEST-OLD"}))
    registry.register(NamedQuery(id="Q-OLD", cypher=OLD_CYPHER, mode="read"))
    registry.register(NamedQuery(id="Q-NEW", cypher=TENANT_CYPHER, mode="read", scenario=SC))
    registry.register(NamedQuery(id="Q-TEST-OLD", cypher=OLD_CYPHER, mode="read"))
    registry.register(
        NamedQuery(id="Q-NEO4J-PING", cypher="RETURN 1 AS ok", mode="read", scope="global")
    )
    registry.register_template(
        QueryTemplate(id="Q-TPL-OLD", cypher="MATCH (n{insert}) RETURN n", mode="read")
    )
    registry.register_template(
        QueryTemplate(
            id="Q-TPL-NEW",
            cypher="MATCH (n{insert} {tenantId: $tenant}) RETURN n",
            mode="read",
            scenario=Scenario("a template", insert=":Lbl"),
        )
    )
    registry.register_template(
        QueryTemplate(
            id="Q-TEST-TPL",
            cypher="MATCH (n{insert} {tenantId: $tenant}) RETURN n",
            mode="read",
            scenario=Scenario("a test template"),
        )
    )
    registry.instance("Q-TPL-OLD", ":Other")  # a run-time instance
    return registry


# The universe


def test_the_universe_is_every_tenant_statement_and_one_entry_per_template() -> None:
    registry = _registry()
    statements = production_statements(registry)
    assert sorted(statements) == ["Q-NEW", "Q-OLD", "Q-TPL-NEW", "Q-TPL-OLD"]


def test_the_universe_leaves_out_global_statements_test_statements_and_instances() -> None:
    statements = production_statements(_registry())
    assert "Q-NEO4J-PING" not in statements
    assert not any(i.startswith("Q-TEST-") for i in statements)
    assert not any(":" in i for i in statements)


def test_a_template_with_a_scenario_stands_for_its_instance_and_one_without_for_its_text() -> None:
    registry = _registry()
    statements = production_statements(registry)
    new = statements["Q-TPL-NEW"]
    assert new.id == "Q-TPL-NEW:Lbl"
    assert registry.is_registered(new)
    assert new.scenario == Scenario("a template", insert=":Lbl")
    old = statements["Q-TPL-OLD"]
    assert old.id == "Q-TPL-OLD"
    assert old.scenario is None
    assert "{insert}" not in old.cypher


def test_the_universe_of_the_real_registry_holds_the_eager_ids_and_the_templates() -> None:
    from diucs.adapters.outbound.graph_store.queries import REGISTRY

    statements = production_statements()
    templates = set(REGISTRY.template_ids())
    # A template with no `{insert}` place is also registered under its own id once it has been
    # asked for, so it is one statement of the universe, not two.
    eager = [
        i
        for i in REGISTRY.ids()
        if ":" not in i
        and not i.startswith("Q-TEST-")
        and REGISTRY.get(i).scope == "tenant"
        and i not in templates
    ]
    assert len(statements) == len(eager) + len(templates)
    assert "Q-NEO4J-PING" not in statements
    assert "Q-RES-UPSERT-ROOT" in statements


def test_the_universe_is_complete_in_a_fresh_interpreter() -> None:
    """Nothing but this call imports the statement modules, as in a run of this one test file."""
    code = (
        "from tests.support.query_probes import production_statements as p; s = p(); "
        "print(len(s), 'Q-OUTBOX-ADD' in s, 'Q-RES-UPSERT-ROOT' in s, 'Q-CRED-SET' in s)"
    )
    backend = Path(__file__).resolve().parents[3]
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=backend, capture_output=True, text=True, check=True
    )
    count, *present = done.stdout.split()
    assert int(count) >= 126
    assert present == ["True", "True", "True"]


# Gaps and the ratchet


def test_a_statement_with_no_scenario_that_is_not_on_the_ratchet_is_a_gap() -> None:
    statements = {"Q-OLD": NamedQuery(id="Q-OLD", cypher=OLD_CYPHER, mode="read")}
    gaps = scenario_gaps(statements, frozenset())
    assert len(gaps) == 1
    assert "Q-OLD" in gaps[0]
    assert "no scenario" in gaps[0]


def test_a_statement_on_the_ratchet_or_with_a_scenario_is_no_gap() -> None:
    statements = production_statements(_registry())
    assert scenario_gaps(statements, frozenset({"Q-OLD", "Q-TPL-OLD"})) == []


def _real_like() -> tuple[dict[str, NamedQuery], frozenset[str], frozenset[str]]:
    statements = production_statements(_registry())
    return (
        statements,
        frozenset({"Q-OLD", "Q-TPL-OLD"}),
        frozenset({"Q-OLD", "Q-TPL-OLD", "Q-GONE"}),
    )


def test_a_clean_state_has_no_ratchet_problem() -> None:
    statements, unconverted, initial = _real_like()
    assert ratchet_problems(statements, unconverted, initial) == []


def test_an_id_added_to_the_ratchet_is_a_problem() -> None:
    statements, unconverted, initial = _real_like()
    problems = ratchet_problems(statements, unconverted | {"Q-NEW"}, initial)
    assert any("Q-NEW" in p and "not on the initial list" in p for p in problems)


def test_a_converted_statement_left_on_the_ratchet_is_a_problem() -> None:
    statements, unconverted, initial = _real_like()
    problems = ratchet_problems(statements, unconverted | {"Q-NEW"}, initial | {"Q-NEW"})
    assert any("Q-NEW" in p and "remove it from UNCONVERTED" in p for p in problems)


def test_a_ratchet_id_that_is_not_a_statement_is_a_problem() -> None:
    statements, unconverted, initial = _real_like()
    problems = ratchet_problems(statements, unconverted | {"Q-GONE"}, initial)
    assert any("Q-GONE" in p and "no such statement" in p for p in problems)


def test_a_statement_with_neither_conversion_nor_a_place_on_the_ratchet_is_a_problem() -> None:
    statements, unconverted, initial = _real_like()
    problems = ratchet_problems(statements, frozenset({"Q-TPL-OLD"}), initial)
    assert any("Q-OLD" in p and "$tenant and a scenario" in p for p in problems)


def test_a_converted_text_without_a_scenario_is_a_problem() -> None:
    statements, unconverted, initial = _real_like()
    statements["Q-HALF"] = NamedQuery(id="Q-HALF", cypher=TENANT_CYPHER, mode="read")
    problems = ratchet_problems(statements, unconverted, initial)
    assert any("Q-HALF" in p and "$tenant and a scenario" in p for p in problems)


# Rows


def test_normalised_rows_are_canonical_sorted_and_keep_duplicates() -> None:
    at = datetime(2026, 10, 25, 11, 0, tzinfo=UTC)
    rows: list[dict[str, Any]] = [{"b": 2, "a": at}, {"a": 1}, {"a": 1}]
    assert normalised(rows) == sorted(
        ['{"a":"2026-10-25T11:00:00+00:00","b":2}', '{"a":1}', '{"a":1}']
    )


def test_masked_rows_ignore_the_times_a_statement_stamps_itself() -> None:
    first = [{"at": datetime(2026, 10, 25, 11, 0, tzinfo=UTC), "n": 1}]
    second = [{"at": datetime(2026, 10, 25, 11, 0, 7, tzinfo=UTC), "n": 1}]
    assert normalised(first) != normalised(second)
    assert normalised(first, mask_times=True) == normalised(second, mask_times=True)
    assert normalised(first, mask_times=True) != normalised([{"at": None, "n": 1}], mask_times=True)


def test_the_expected_rows_are_matched_as_a_set_of_subsets_for_the_slot() -> None:
    expected = ({"id": Unique("a-C", "resource_id")}, {"props": {"note": Marked("n")}})
    assert row_problems(expected, [{"id": "a-C"}], "B") == ["expected 2 rows, got 1"]
    both = [{"id": "a-C-B"}, {"id": "x", "props": {"note": "n-B", "tenantId": "t"}}]
    assert row_problems(expected, both, "B") == []


def test_a_missing_row_and_a_surplus_row_are_both_named() -> None:
    expected = ({"n": 1},)
    assert row_problems(expected, [], "A") == ["expected 1 rows, got 0"]
    assert row_problems((), [{"n": 1}], "A") == ["expected 0 rows, got 1"]
    problems = row_problems(expected, [{"n": 2}], "A")
    assert problems == ["row 0 is not the expected row"]


def test_a_value_that_differs_is_not_a_match_even_when_the_keys_agree() -> None:
    assert row_problems(({"n": 1, "m": 2},), [{"n": 1, "m": 3}], "A") == [
        "row 0 is not the expected row"
    ]
    assert row_problems(({"n": 1, "m": 2},), [{"n": 1}], "A") == ["row 0 is not the expected row"]
    assert row_problems(({"p": {"a": 1}},), [{"p": 5}], "A") == ["row 0 is not the expected row"]


def test_rows_with_a_neo4j_datetime_match_the_python_value() -> None:
    at = datetime(2026, 10, 25, 11, 0, tzinfo=UTC)
    neo = DateTime(2026, 10, 25, 11, 0, 0, 0, tzinfo=UTC)
    assert row_problems(({"at": at},), [{"at": neo}], "A") == []


# Effects


def _snap(*nodes: Node, rels: tuple[Rel, ...] = ()) -> Snapshot:
    return Snapshot(nodes, rels)


A = Node(("Thing",), {"id": "t-1", "note": "n-A"})
B = Node(("Thing",), {"id": "t-2", "note": "n-A"})
D = Node(("Detail",), {"text": "d-A"})


def test_no_change_is_the_expected_effect_of_a_read() -> None:
    assert effect_problems(_snap(A), _snap(A), Expect(), "A") == []


def test_a_change_to_a_read_is_a_problem() -> None:
    message = "the statement changed the caller's data, and the scenario expects no change"
    assert message in effect_problems(_snap(A), _snap(A, B), Expect(), "A")
    changed = Node(("Thing",), {"id": "t-1", "note": "other"})
    assert effect_problems(_snap(A), _snap(changed), Expect(), "A") == [message]


def test_a_create_is_checked_by_count_and_by_the_node_that_appears() -> None:
    expect = Expect(
        nodes={"Thing": 1},
        rels={"NEXT": 1},
        after=(NodeSpec(("Thing",), {"id": Unique("t-2", "resource_id")}),),
    )
    after = _snap(A, B, rels=(Rel(A, "NEXT", B),))
    assert effect_problems(_snap(A), after, expect, "A") == []
    # Slot B expects the unique id as written for B.
    assert effect_problems(_snap(A), after, expect, "B") == [
        "no node matches the expected state Thing"
    ]


def test_a_count_that_differs_or_an_unexpected_label_or_type_is_named() -> None:
    expect = Expect(nodes={"Thing": 1})
    assert effect_problems(_snap(A), _snap(A, B, D), expect, "A") == [
        "nodes Detail: expected +0, got +1"
    ]
    assert effect_problems(_snap(A), _snap(A), expect, "A") == ["nodes Thing: expected +1, got +0"]
    rels = (Rel(A, "NEXT", B), Rel(B, "NEXT", A))
    assert effect_problems(_snap(A, B), _snap(A, B, rels=rels), Expect(rels={"NEXT": 1}), "A") == [
        "relationships NEXT: expected +1, got +2"
    ]
    assert effect_problems(
        _snap(A, B), _snap(A, B, rels=(Rel(A, "LINKS", B),)), Expect(rels={"NEXT": 1}), "A"
    ) == ["relationships LINKS: expected +0, got +1", "relationships NEXT: expected +1, got +0"]


def test_an_update_is_checked_by_the_property_it_sets() -> None:
    changed = Node(("Thing",), {"id": "t-1", "note": "changed"})
    expect = Expect(after=(NodeSpec(("Thing",), {"id": "t-1", "note": "changed"}),))
    assert effect_problems(_snap(A), _snap(changed), expect, "A") == []
    assert effect_problems(_snap(A), _snap(A), expect, "A") == [
        "no node matches the expected state Thing"
    ]


def test_a_delete_is_checked_by_the_node_that_goes() -> None:
    expect = Expect(nodes={"Thing": -1}, gone=(NodeSpec(("Thing",), {"id": "t-2"}),))
    assert effect_problems(_snap(A, B), _snap(A), expect, "A") == []
    assert effect_problems(_snap(A, B), _snap(A, B), expect, "A") == [
        "nodes Thing: expected -1, got +0",
        "a node that should be gone is still there: Thing",
    ]
    assert effect_problems(
        _snap(A), _snap(A), Expect(gone=(NodeSpec(("Thing",), {"id": "t-2"}),)), "A"
    ) == ["a node that should be gone was not there to begin with: Thing"]


def test_a_label_the_scenario_does_not_name_counts_as_a_change() -> None:
    assert effect_problems(
        _snap(A), _snap(A, D), Expect(after=(NodeSpec(("Thing",), {"id": "t-1"}),)), "A"
    ) == ["nodes Detail: expected +0, got +1"]


# Findings


def test_findings_are_written_with_the_query_the_phase_and_the_kind_only() -> None:
    findings = [
        Finding("Q-A", "A-then-B", FindingKind.ROWS_DIFFER, "2 rows, expected 1"),
        Finding("Q-B", "B-then-A", FindingKind.PROBE_ERROR, "ClientError"),
    ]
    text = format_findings(findings)
    assert (
        "Q-A" in text
        and "A-then-B" in text
        and "rows-differ" in text
        and "2 rows, expected 1" in text
    )
    assert "Q-B" in text and "probe-error" in text and "ClientError" in text
    assert text.count("\n") == 1
    assert format_findings([]) == ""


def test_every_finding_kind_has_its_text() -> None:
    assert {kind.value for kind in FindingKind} == {
        "rows-differ",
        "own-state-differs",
        "other-tenant-changed",
        "unstamped-node",
        "cross-scope-relationship",
        "foreign-id-effect",
        "unexpected-rows",
        "unexpected-effect",
        "probe-error",
    }
