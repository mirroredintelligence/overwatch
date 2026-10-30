"""Raw Cypher in integration tests and their support code names the run's tenant (TEN-035).

On a Neo4j that other runs share, a statement such as `MATCH (m:OutboxMessage) RETURN count(m)`
counts every run's messages, and `MATCH (s:Snapshot) ... SET s.json = '{}'` damages them. A test
statement therefore says `tenantId: $tenant` on every node it matches or creates (the bound tenant
is passed as `tenant` by the test transaction, `tests/support/scoped.py`) or names the run's scope
ids (`IN $scopes`). The modules that run on a private container (markers `schema` and `lifecycle`)
and the harness's own tests, which are about the whole database, are exempt.

The check reads the string literals of the modules (an implicit concatenation is one statement) and
looks for a node pattern with a label, a property map or no content, that has no `tenantId`. The
registry nodes (`Tenant`, `TenantNumber`, `Network`, `Migration`) carry no `tenantId`.
"""

import ast
import re
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[2]
PRIVATE_MARKERS = {"schema", "lifecycle"}
# The harness's own modules look at the whole database on purpose, and the seed mirror writes
# whatever tenant it is given.
EXEMPT = {
    "integration/support/test_tenant_scope_harness.py",
    "integration/support/test_shared_mode.py",
    "integration/support/test_neo4j_harness.py",
    "integration/support/test_harness_protection.py",
    "integration/support/test_harness_restart.py",
    "integration/test_infra_up.py",
    "integration/test_collector_allowlist.py",
    "support/neo4j.py",
    "support/sweeper.py",
    "support/tenant_seed.py",
    "support/query_probes.py",
    "support/api.py",
}
# Stubs and rigs with no database: a fixed tenant id there is only a label.
NO_DATABASE = {"support/registration_rig.py"}
REGISTRY = {"Tenant", "TenantNumber", "Network", "Migration"}
# `WHERE n.tenantId IN $scopes` or `n.tenantId = $tenant`: the statement is limited in its WHERE.
WHERE_SCOPED = re.compile(r"\.tenantId\s*(?:IN|=)\s*\$")
CYPHER = re.compile(r"\b(?:MATCH|CREATE|MERGE)\s*\(")
NODE = re.compile(
    r"(?<![\w`$])\(\s*(?P<var>\w*)\s*(?P<labels>(?::[\w`|]+)+)?\s*(?P<props>\{[^{}]*\})?\s*\)"
)


def _is_private(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and node.attr in PRIVATE_MARKERS
        for node in ast.walk(tree)
    )


def _texts(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            text = "".join(
                part.value if isinstance(part, ast.Constant) else "{}" for part in node.values
            )
            found.append((node.lineno, text))
    return found


def unscoped_patterns(text: str) -> list[str]:
    """The node patterns of a Cypher statement that name no tenant. Empty for anything that is not a
    statement, and for a statement that names `tenantId` in its WHERE or a scope list."""
    if CYPHER.search(text) is None or WHERE_SCOPED.search(text):
        return []
    bad = []
    for match in NODE.finditer(text):
        labels = re.findall(r"\w+", match["labels"] or "")
        if any(label in REGISTRY for label in labels):
            continue
        if not labels and not match["props"] and match["var"]:
            continue  # a bare variable bound earlier
        if "tenantId" not in (match["props"] or ""):
            bad.append(match.group(0))
    return bad


def _modules() -> list[Path]:
    paths = [
        *sorted((TESTS / "integration").rglob("*.py")),
        *sorted((TESTS / "support").glob("*.py")),
    ]
    return [path for path in paths if str(path.relative_to(TESTS)) not in EXEMPT]


def test_the_guard_sees_an_unscoped_statement_and_a_scoped_one() -> None:
    assert unscoped_patterns("MATCH (m:OutboxMessage) RETURN count(m) AS n") == [
        "(m:OutboxMessage)"
    ]
    assert unscoped_patterns("MATCH ()-[r:T]->() RETURN count(r)") == ["()", "()"]
    assert unscoped_patterns("MATCH (m:OutboxMessage {tenantId: $tenant}) RETURN count(m)") == []
    assert unscoped_patterns("MATCH (n) WHERE n.tenantId IN $scopes RETURN n") == []
    # Reading the property is not limiting by it.
    assert unscoped_patterns("MATCH (p:Processed) RETURN p.tenantId AS t") == ["(p:Processed)"]
    assert unscoped_patterns("MATCH (t:Tenant {id: $id}) SET t += $props") == []
    assert unscoped_patterns("a sentence (with a parenthesis) and no statement") == []


def test_no_raw_statement_in_an_integration_test_reads_or_writes_outside_the_run() -> None:
    offenders = []
    for module in _modules():
        tree = ast.parse(module.read_text(encoding="utf-8"))
        if _is_private(tree):
            continue
        for line, text in _texts(tree):
            bad = unscoped_patterns(text)
            if bad:
                offenders.append(f"{module.relative_to(TESTS)}:{line} {bad[:2]}")

    assert offenders == [], "raw Cypher without tenantId: \n" + "\n".join(offenders)


@pytest.mark.parametrize("name", ["tenant-a", "tenant-b", "default", "a1", "b1"])
def test_no_integration_module_binds_a_fixed_tenant_id(name: str) -> None:
    """A tenant the run did not make is not removed by the wipe between tests, and two runs on one
    Neo4j would write to it together (`tenant_id` and `other_tenant_id` are the run's)."""
    pattern = re.compile(
        rf"(?:bind_tenant|as_tenant|ScopeId\.tenant)\(\s*[\"']{re.escape(name)}[\"']"
    )
    offenders = []
    for module in _modules():
        tree = ast.parse(module.read_text(encoding="utf-8"))
        if _is_private(tree) or str(module.relative_to(TESTS)) in NO_DATABASE:
            continue
        if pattern.search(module.read_text(encoding="utf-8")):
            offenders.append(str(module.relative_to(TESTS)))

    assert offenders == [], f"modules that bind the fixed tenant {name!r}: {offenders}"
