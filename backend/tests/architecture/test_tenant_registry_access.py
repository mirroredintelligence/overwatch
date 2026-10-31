"""Who may read the tenant registry (TEN-007, DEC-130 item 3, DEC-134 item 9).

The registry nodes (`Tenant`, `TenantNumber`) carry no tenant, so a statement that matches them
needs no scope. That is safe only while one module owns every such statement and runs it on the
global path. These rules scan the real source under backend/src/diucs; the scanners are also run on
small strings, so a scanner that stops seeing what it should fails here and does not pass vacuously.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = BACKEND / "src" / "diucs"
GRAPH_STORE = "adapters/outbound/graph_store"
DIRECTORY = f"{GRAPH_STORE}/tenant_directory.py"
REGISTRY_WRITES = f"{GRAPH_STORE}/tenant_registry.py"
# The only files that name a registry label in Cypher: the directory's statements, the registry's
# writes (TEN-028), and the schema and the default record of the tenant migrations.
REGISTRY_CYPHER_FILES = frozenset(
    {DIRECTORY, REGISTRY_WRITES, f"{GRAPH_STORE}/migrations_tenant.py"}
)
INVARIANTS = f"{GRAPH_STORE}/invariants.py"
# TEN-051: the network registry (`Network`, `NetworkMembership`, `Grant`, `Listing`) is the second
# module that runs global statements, and the only one that runs global writes (GLOBAL_WRITE_IDS).
NETWORK_REGISTRY = f"{GRAPH_STORE}/network_registry.py"
# The files that run a global statement (the ping, the directory, and the invariant check of
# TEN-031, which counts over the whole graph and returns label names and counts only).
GLOBAL_RUNNERS = frozenset(
    {
        f"{GRAPH_STORE}/driver.py",
        f"{GRAPH_STORE}/health.py",
        DIRECTORY,
        INVARIANTS,
        NETWORK_REGISTRY,
    }
)
BINDING_NAMES = frozenset({"bind_scope", "bind_tenant", "run_query"})

_REGISTRY_LABEL = re.compile(r"\(\s*\w*\s*:\s*`?(?:Tenant|TenantNumber)`?\b")


def _files() -> list[Path]:
    files = sorted(PACKAGE_ROOT.rglob("*.py"))
    assert len(files) > 50, "the scan found too few files: it is not looking at backend/src/diucs"
    return files


def _relative(path: Path) -> str:
    return path.relative_to(PACKAGE_ROOT).as_posix()


def names_registry_label(source: str) -> bool:
    """True when a string constant holds a node pattern with a registry label."""
    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _REGISTRY_LABEL.search(node.value) is not None
        for node in ast.walk(ast.parse(source))
    )


def referenced_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
    return names


def test_only_the_directory_and_the_tenant_migrations_name_a_registry_label_in_cypher() -> None:
    offenders = [
        _relative(path)
        for path in _files()
        if _relative(path) not in REGISTRY_CYPHER_FILES
        and names_registry_label(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_the_directory_and_the_migrations_do_name_them_so_the_scan_sees_something() -> None:
    for relative in REGISTRY_CYPHER_FILES:
        assert names_registry_label((PACKAGE_ROOT / relative).read_text(encoding="utf-8")), relative


def test_only_the_ping_the_directory_and_the_invariant_check_run_a_global_statement() -> None:
    offenders = [
        _relative(path)
        for path in _files()
        if _relative(path) not in GLOBAL_RUNNERS
        and "run_global_query" in referenced_names(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_the_network_registry_binds_nothing_and_runs_no_tenant_statement() -> None:
    names = referenced_names((PACKAGE_ROOT / NETWORK_REGISTRY).read_text(encoding="utf-8"))
    assert names.isdisjoint(BINDING_NAMES)
    assert "run_global_query" in names


def test_the_directory_binds_nothing_and_runs_no_tenant_statement() -> None:
    names = referenced_names((PACKAGE_ROOT / DIRECTORY).read_text(encoding="utf-8"))
    assert names.isdisjoint(BINDING_NAMES)
    assert "run_global_query" in names


def test_the_invariant_check_binds_nothing_and_names_no_registry_label() -> None:
    source = (PACKAGE_ROOT / INVARIANTS).read_text(encoding="utf-8")
    names = referenced_names(source)
    assert names.isdisjoint(BINDING_NAMES)
    assert "run_global_query" in names
    # The registry labels it leaves out come in as a parameter, never as text in a statement.
    assert not names_registry_label(source)


def test_only_the_composition_root_builds_the_invariant_check() -> None:
    offenders = [
        _relative(path)
        for path in _files()
        if _relative(path) not in {INVARIANTS, "bootstrap/container.py"}
        and "Neo4jTenantInvariants" in referenced_names(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_only_the_composition_root_builds_the_directory() -> None:
    offenders = [
        _relative(path)
        for path in _files()
        if _relative(path) not in {DIRECTORY, "bootstrap/container.py"}
        and "Neo4jTenantDirectory" in referenced_names(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


# The platform statements write the registry (TEN-028, DEC-503). They run through one function, from
# one module, and only the operator use cases hold that module's port.
# TEN-075: the platform's own records (the platform audit chain and the support-access tickets) are
# platform statements too, each run from a module of its own that binds nothing.
PLATFORM_AUDIT = f"{GRAPH_STORE}/platform_audit.py"
SUPPORT_TICKETS = f"{GRAPH_STORE}/support_ticket_store.py"
PLATFORM_RECORD_MODULES = frozenset({PLATFORM_AUDIT, SUPPORT_TICKETS})
PLATFORM_RUNNERS = frozenset(
    {f"{GRAPH_STORE}/driver.py", REGISTRY_WRITES, *PLATFORM_RECORD_MODULES}
)
OPERATOR_USE_CASES = frozenset(
    {
        "application/use_cases/tenant_admin.py",
        "application/use_cases/tenant_suspend.py",
        # TEN-075: starting an offboarding and the operator's tenant list and detail are operator
        # use cases too, and the services of the operator's routes hold them.
        "application/use_cases/tenant_offboarding.py",
        "application/use_cases/platform_tenants.py",
        # TEN-074: the rest of the offboarding (memberships, export, completion) and the purge are
        # the platform operator's, for one tenant, by compare and set.
        "application/use_cases/tenant_offboard.py",
        "application/use_cases/tenant_purge.py",
        "application/ports/outbound/tenant_registry.py",
        "bootstrap/container.py",
        "bootstrap/provisioning.py",
        REGISTRY_WRITES,
    }
)


def test_only_the_registry_writes_run_a_platform_statement() -> None:
    offenders = [
        _relative(path)
        for path in _files()
        if _relative(path) not in PLATFORM_RUNNERS
        and "run_platform_query" in referenced_names(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_the_registry_writes_bind_nothing_run_no_tenant_or_global_statement() -> None:
    names = referenced_names((PACKAGE_ROOT / REGISTRY_WRITES).read_text(encoding="utf-8"))
    assert names.isdisjoint(BINDING_NAMES)
    assert "run_global_query" not in names
    assert "run_platform_query" in names


def test_the_platform_record_modules_bind_nothing_and_run_only_platform_statements() -> None:
    for relative in PLATFORM_RECORD_MODULES:
        names = referenced_names((PACKAGE_ROOT / relative).read_text(encoding="utf-8"))
        assert names.isdisjoint(BINDING_NAMES), relative
        assert "run_global_query" not in names, relative
        assert "run_platform_query" in names, relative


def test_the_platform_record_modules_name_no_tenant_registry_label() -> None:
    for relative in PLATFORM_RECORD_MODULES:
        source = (PACKAGE_ROOT / relative).read_text(encoding="utf-8")
        assert not names_registry_label(source), relative


def test_only_the_composition_root_builds_the_platform_record_adapters() -> None:
    for name, home in (
        ("Neo4jPlatformAudit", PLATFORM_AUDIT),
        ("Neo4jSupportTickets", SUPPORT_TICKETS),
    ):
        offenders = [
            _relative(path)
            for path in _files()
            if _relative(path) not in {home, "bootstrap/container.py"}
            and name in referenced_names(path.read_text(encoding="utf-8"))
        ]
        assert offenders == [], name


def test_only_the_composition_root_builds_the_registry_writes() -> None:
    offenders = [
        _relative(path)
        for path in _files()
        if _relative(path) not in {REGISTRY_WRITES, "bootstrap/container.py"}
        and "Neo4jTenantRegistry" in referenced_names(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_only_the_operator_use_cases_name_the_registry_port() -> None:
    offenders = [
        _relative(path)
        for path in _files()
        if _relative(path) not in OPERATOR_USE_CASES
        and "TenantRegistry" in referenced_names(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


@pytest.mark.parametrize(
    "source",
    [
        'Q = "MATCH (t:Tenant) RETURN t"\n',
        'Q = "MATCH (n:TenantNumber {e164: $x}) RETURN n"\n',
        'Q = "MATCH (t :`Tenant`) RETURN t"\n',
        'def f():\n    return "MATCH (x:Tenant {id: $id}) RETURN x"\n',
    ],
)
def test_the_label_scanner_sees_a_registry_label(source: str) -> None:
    assert names_registry_label(source)


@pytest.mark.parametrize(
    "source",
    [
        'Q = "MATCH (t:TenantSetting) RETURN t"\n',
        'Q = "MATCH (t:Observation) RETURN t"\n',
        'Q = "MATCH (t:Resource {tenantId: $tenant}) RETURN t"\n',
        'Q = "no node pattern here: Tenant"\n',
    ],
)
def test_the_label_scanner_ignores_other_labels(source: str) -> None:
    assert not names_registry_label(source)


def test_the_name_scanner_sees_a_call_an_import_and_an_attribute() -> None:
    assert "run_global_query" in referenced_names("run_global_query(tx, q)\n")
    assert "run_global_query" in referenced_names("from a import run_global_query\n")
    assert "run_global_query" in referenced_names("driver.run_global_query(tx)\n")
