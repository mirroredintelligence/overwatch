# ruff: noqa: E501
"""Mutant evidence for the guards of the tenancy seam (TEN-030, TEN-031).

Each mutant removes or weakens one guard of the seam in a scratch copy of `src` and runs the test
that is named for it. The guard is needed only if that test fails with the guard gone, and passes
with it in place. Nothing in the real tree is changed: the copy is put first on `PYTHONPATH`.

Run from `backend/`:  uv run python scripts/guard_mutants.py            (all)
                      uv run python scripts/guard_mutants.py M04 M07    (some)

The architecture rule against a ratchet name in `src` is proved by its own probe (a module that
names `UNCONVERTED` must be flagged: test_a_probe_module_outside_the_query_packages_fails_every_rule
in tests/architecture/test_single_execution_point.py), because that test scans the real tree and
not a copy.

The predicate removal of every registered statement (`tenantId: $tenant` taken out of each, the
generated two-tenant test must fail for it) is a test on a real Neo4j, not a source mutant:
tests/integration/graph_store/test_tenant_isolation.py
::test_removing_the_tenant_predicate_makes_the_generated_test_fail.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SRC = BACKEND / "src"
GRAPH = "diucs/adapters/outbound/graph_store"

UNIT = "tests/unit/adapters/outbound/graph_store"


@dataclass(frozen=True)
class Mutant:
    id: str
    guard: str
    file: str
    old: str
    new: str
    tests: tuple[str, ...]


MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        "M01",
        "the registry refuses a tenant statement with no `tenantId: $tenant` entry",
        f"{GRAPH}/queries.py",
        "        if _TENANT_ENTRY.search(_blank(query_id, cypher)) is None:",
        "        if False:",
        (
            f"{UNIT}/test_tenant_predicate.py::test_a_statement_without_the_tenant_is_refused_whatever_its_id",
        ),
    ),
    Mutant(
        "M02",
        "the registry refuses a tenant statement with no scenario",
        f"{GRAPH}/queries.py",
        '        if scenario is None:\n            raise ScenarioMissing(f"query {query_id}: no scenario")',
        '        if False:\n            raise ScenarioMissing(f"query {query_id}: no scenario")',
        (
            f"{UNIT}/test_tenant_predicate.py::test_a_statement_with_no_scenario_is_refused_whatever_its_id",
        ),
    ),
    Mutant(
        "M03",
        "the predicate is looked for outside comments and strings only",
        f"{GRAPH}/queries.py",
        "        if _TENANT_ENTRY.search(_blank(query_id, cypher)) is None:",
        "        if _TENANT_ENTRY.search(cypher) is None:",
        (
            f"{UNIT}/test_tenant_predicate.py::test_a_statement_that_only_mentions_the_tenant_is_refused",
        ),
    ),
    Mutant(
        "M04",
        "run_query refuses a transaction that does not carry a scope",
        f"{GRAPH}/driver.py",
        "    if not isinstance(tx, ScopedTx):\n        raise RawTransactionRefused\n",
        "",
        (
            f"{UNIT}/test_enforced_execution.py::test_a_raw_transaction_is_refused_even_with_a_scope_bound",
            f"{UNIT}/test_driver.py::test_a_raw_transaction_is_refused_before_any_cypher_bound_or_not",
        ),
    ),
    Mutant(
        "M05",
        "run_query refuses a global statement",
        f"{GRAPH}/driver.py",
        '    if query.scope == "global":\n        raise GlobalStatementMisuse\n    if not isinstance(tx, ScopedTx):',
        "    if not isinstance(tx, ScopedTx):",
        (f"{UNIT}/test_driver.py::test_run_query_refuses_a_global_statement_bound_or_not",),
    ),
    Mutant(
        "M06",
        "run_query refuses a caller-supplied `tenant`",
        f"{GRAPH}/driver.py",
        '    _refuse_tenant_parameter(params)\n    if query.scope == "global":\n        raise GlobalStatementMisuse',
        '    if query.scope == "global":\n        raise GlobalStatementMisuse',
        (f"{UNIT}/test_driver.py::test_the_refusal_does_not_depend_on_the_value_given",),
    ),
    Mutant(
        "M07",
        "run_query runs only the statement that was registered",
        f"{GRAPH}/driver.py",
        '    if not lookup.is_registered(query):\n        raise QueryNotRegistered\n    _refuse_tenant_parameter(params)\n    if query.scope == "global":',
        '    _refuse_tenant_parameter(params)\n    if query.scope == "global":',
        (f"{UNIT}/test_driver.py::test_a_query_object_that_was_never_registered_is_refused",),
    ),
    Mutant(
        "M08",
        "the tenant that runs is the one the scoped transaction carries",
        f"{GRAPH}/driver.py",
        '{"tenant": tx.scope.value, **params}',
        '{"tenant": "a1", **params}',
        (f"{UNIT}/test_driver.py::test_the_bound_value_is_what_is_passed_not_a_constant",),
    ),
    Mutant(
        "M09",
        "a scoped transaction cannot be made with no scope",
        f"{GRAPH}/driver.py",
        "        if self.scope is None:\n            raise TenantNotBound\n",
        "        pass\n",
        (
            f"{UNIT}/test_enforced_execution.py::test_a_scoped_transaction_cannot_be_made_without_a_scope",
        ),
    ),
    Mutant(
        "M10",
        "a unit of work, or any code that opens its own transaction, refuses to open with no scope",
        "diucs/application/tenancy.py",
        "    return current_scope()\n",
        "    return current_scope_or_none()  # type: ignore[return-value]\n",
        (
            f"{UNIT}/test_enforced_execution.py::test_a_new_unit_with_no_scope_bound_is_refused",
            f"{UNIT}/test_enforced_execution.py::test_a_unit_of_work_with_no_scope_bound_opens_no_session_and_claims_nothing",
        ),
    ),
    Mutant(
        "M11",
        "the audit chain refuses a transaction that carries no scope",
        "diucs/adapters/outbound/audit_neo4j/audit_log.py",
        "    if not isinstance(tx, ScopedTx):\n        raise RawTransactionRefused\n    return tx.scope",
        "    return tx.scope",
        (
            "tests/unit/adapters/outbound/audit_neo4j/test_audit_log_queries.py"
            "::test_reading_the_chain_on_a_raw_transaction_is_refused_before_cypher",
        ),
    ),
    Mutant(
        "M12",
        "a global statement registers only when the digest of its text is the pinned one",
        f"{GRAPH}/queries.py",
        "            if statement_digest(cypher) != pinned:",
        "            if False:",
        (
            f"{UNIT}/test_global_allowlist.py::test_a_pinned_id_with_altered_text_is_refused_by_the_pin",
        ),
    ),
    Mutant(
        "M13",
        "a global statement is checked structurally behind the pin",
        f"{GRAPH}/queries.py",
        "            _check_global_text(query_id, cypher)\n",
        "",
        (
            f"{UNIT}/test_global_allowlist.py"
            "::test_the_structural_check_alone_refuses_every_bypass_even_when_the_text_is_pinned",
        ),
    ),
    Mutant(
        "M14",
        "a whole-graph count may return only a label set or a type and a count",
        f"{GRAPH}/queries.py",
        "        or _WHOLE_GRAPH_RETURN.search(text) is None",
        "        or False",
        (
            f"{UNIT}/test_global_allowlist.py"
            "::test_a_whole_graph_statement_that_could_return_a_value_or_write_is_refused",
        ),
    ),
    Mutant(
        "M15",
        "the process does not start while a node has no tenantId",
        "diucs/bootstrap/container.py",
        "            if not report.ok:\n                raise TenantInvariantViolated(report)\n",
        "",
        (
            "tests/unit/bootstrap/test_container.py"
            "::test_start_up_refuses_to_start_when_a_node_has_no_tenant_and_closes_the_connection",
        ),
    ),
    Mutant(
        "M16",
        "the unstamped count leaves out the registry labels and no others",
        f"{GRAPH}/invariants.py",
        "registryLabels=list(REGISTRY_LABELS)",
        "registryLabels=[]",
        (
            f"{UNIT}/test_tenant_invariants.py::test_the_unstamped_count_is_sent_the_registry_labels_and_nothing_else",
        ),
    ),
)


def _run(tests: tuple[str, ...], src: Path) -> tuple[int, str]:
    env = {**os.environ, "PYTHONPATH": f"{src}{os.pathsep}{BACKEND}"}
    command = [
        sys.executable,
        "-m",
        "pytest",
        *tests,
        "-q",
        "-p",
        "no:cacheprovider",
        "--no-header",
    ]
    done = subprocess.run(
        command, cwd=BACKEND, env=env, capture_output=True, text=True, check=False
    )
    return done.returncode, done.stdout + done.stderr


def _failed(output: str) -> list[str]:
    return [
        line.split(" ")[1].split("::")[-1]
        for line in output.splitlines()
        if line.startswith("FAILED ")
    ]


def main(selected: list[str]) -> int:
    chosen = [m for m in MUTANTS if not selected or m.id in selected]
    survivors: list[str] = []
    with tempfile.TemporaryDirectory() as scratch:
        for mutant in chosen:
            copy = Path(scratch) / mutant.id
            shutil.copytree(SRC, copy, ignore=shutil.ignore_patterns("__pycache__"))
            target = copy / mutant.file
            text = target.read_text(encoding="utf-8")
            if text.count(mutant.old) != 1:
                print(f"{mutant.id}: the text to remove is not in {mutant.file} exactly once")
                survivors.append(mutant.id)
                continue
            clean_code, clean_out = _run(mutant.tests, SRC)
            target.write_text(text.replace(mutant.old, mutant.new), encoding="utf-8")
            code, out = _run(mutant.tests, copy)
            killed = code != 0 and bool(_failed(out))
            names = ", ".join(sorted(set(_failed(out)))[:3])
            print(
                f"{mutant.id} {'KILLED' if killed else 'SURVIVED'} (clean run {'passes' if clean_code == 0 else 'FAILS'}): {mutant.guard}"
            )
            if killed:
                print(f"      failing: {names}")
            if not killed or clean_code != 0:
                survivors.append(mutant.id)
                print(clean_out[-600:] if clean_code != 0 else out[-600:])
    print(f"{len(chosen) - len(survivors)} of {len(chosen)} mutants killed")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
