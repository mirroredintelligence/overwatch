"""Architecture tests for the tenancy seam (TEN-001, DEC-142): one execution point, statements that
are fixed text in the two adapter query packages, one place that creates the tenant context, named
binding sites, and no `tenant` argument anywhere in the graph store.

Every rule scans the real source under backend/src/diucs with `ast` (the style of
test_import_rules.py). Each scanner is also run on small source strings, and the whole check is run
on the real tree plus a probe module that breaks every rule, so a scanner that stops seeing what it
should fails here instead of passing vacuously.

The earlier sections (the execution point, the context variable, the binding sites, the tenant
parameter) are reused from the verified earlier branch. Sections 5 to 9 are new.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
SRC_ROOT = BACKEND / "src"
PACKAGE_ROOT = SRC_ROOT / "diucs"
GRAPH_STORE = "adapters/outbound/graph_store"

# Modules that may execute Cypher. The migration runner is not application Cypher: it runs raw
# schema statements and records Migration nodes (audit A 7.1).
EXECUTION_POINT = f"{GRAPH_STORE}/driver.py"
# Named, not a glob (known issue of TEN-001, closed in TEN-005): a new `migrations_x.py` that calls
# `tx.run` is flagged until it is listed here. `migrations.py` runs the steps and the record,
# `migration_loop.py` the batched data steps, `migrations_tenant.py` the invariant queries;
# `migrations_network.py` and `migration_types.py` hold data and run nothing.
MIGRATION_RUNNER_FILES = frozenset(
    {
        f"{GRAPH_STORE}/migrations.py",
        f"{GRAPH_STORE}/migration_loop.py",
        f"{GRAPH_STORE}/migrations_tenant.py",
    }
)

# Receivers whose `run` is not a database call.
NOT_A_DATABASE_ROOTS = frozenset({"asyncio", "subprocess", "anyio", "trio"})
EXECUTING_ATTRIBUTES = frozenset({"run", "execute_query"})

# The kernel module: the only place the context variable is created and set.
TENANCY_KERNEL = "application/tenancy.py"

# Modules, as dotted names, that may call bind_scope or bind_tenant besides the kernel: the edges
# that bind a verified tenant once per unit of work. Empty in TEN-001; the edge tasks (TEN-018,
# TEN-025, TEN-041 and later) add their module in their own commit. I07 adds the inbound SMS
# webhook, which binds the tenant of a request whose Twilio signature verified (DEC-131, DEC-149).
# I03 adds the outbox relay worker, which binds each tenant the directory lists, in turn, before it
# opens a unit of work for that tenant (DEC-134 item 9, DEC-157). I08 adds the consumers' binder,
# which binds the tenant a message carries once the directory lists it as active (DEC-165).
BINDING_MODULES: frozenset[str] = frozenset(
    {
        "diucs.adapters.inbound.link_pages.capacity_links",
        "diucs.adapters.inbound.sms_webhook.routes",
        "diucs.adapters.inbound.workers.outbox_relay",
        "diucs.adapters.inbound.workers.tenant_binding",
        # O09: the synthetic test hook binds the one tenant its configuration names, never one the
        # request sends, and is mounted only when the hook is configured.
        "diucs.adapters.inbound.fhir_rest.routes_synthetic",
        # TEN-017: the start-up is an edge of its own: it binds each active tenant in turn to make
        # that tenant's audit head. No request or message is in it.
        "diucs.bootstrap.container",
    }
)

# Modules, as dotted names, under adapters/outbound/graph_store that may define a function with a
# `tenant` or `tenant_id` parameter. Empty in TEN-001; the tenant registry (TEN-007) names its
# module here: the directory looks a tenant up by the id it is asked about, on the global path, and
# never sends a tenant to a statement. This is the "callers never pass a tenant" rule made visible.
TENANT_PARAMETER_MODULES: frozenset[str] = frozenset(
    {"diucs.adapters.outbound.graph_store.tenant_directory"}
)

BINDING_NAMES = frozenset({"bind_scope", "bind_tenant"})
PRIVATE_SCOPE_NAME = "_SCOPE"
# TEN-002: the kernel's second context variable, the claim that keeps one unit of work open per
# context, and the two functions that take and give it back.
PRIVATE_UNIT_NAME = "_UNIT"
CLAIM_NAMES = frozenset({"claim_unit", "release_unit"})
CLAIM_MODULES: frozenset[str] = frozenset({"diucs.adapters.outbound.graph_store.unit_of_work"})
KERNEL_CONTEXT_VARIABLES = 2
TENANT_PARAMETER_NAMES = frozenset({"tenant", "tenant_id"})


def _source_files() -> list[Path]:
    files = sorted(PACKAGE_ROOT.rglob("*.py"))
    assert len(files) > 50, "the scan found too few files: it is not looking at backend/src/diucs"
    return files


def _relative(path: Path) -> str:
    return path.relative_to(PACKAGE_ROOT).as_posix()


def _module_name(relative: str) -> str:
    parts = ["diucs", *relative.removesuffix(".py").split("/")]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _parse(source: str) -> ast.AST:
    return ast.parse(source)


# 1. Application Cypher runs only in the execution point


def _root_name(node: ast.expr) -> str | None:
    """The leftmost name of an attribute chain, looking through calls and subscripts."""
    current: ast.expr = node
    while True:
        if isinstance(current, ast.Attribute):
            current = current.value
        elif isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Subscript):
            current = current.value
        elif isinstance(current, ast.Name):
            return current.id
        else:
            return None


def executing_attribute_lines(source: str) -> list[int]:
    """Lines of every attribute named run or execute_query (called or merely referenced), and of
    every getattr(x, "run") that reaches one by name, except on receivers that are not a database.
    """
    lines: list[int] = []
    for node in ast.walk(_parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in EXECUTING_ATTRIBUTES:
            if _root_name(node.value) not in NOT_A_DATABASE_ROOTS:
                lines.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in EXECUTING_ATTRIBUTES
            and _root_name(node.args[0]) not in NOT_A_DATABASE_ROOTS
        ):
            lines.append(node.lineno)
    return lines


def _is_allowed_executor(relative: str) -> bool:
    return relative == EXECUTION_POINT or relative in MIGRATION_RUNNER_FILES


def test_application_cypher_runs_only_in_the_execution_point_and_the_migration_runner() -> None:
    offenders = {
        _relative(path): lines
        for path in _source_files()
        if (lines := executing_attribute_lines(path.read_text(encoding="utf-8")))
        and not _is_allowed_executor(_relative(path))
    }
    assert offenders == {}, f"Cypher is executed outside the execution point: {offenders}"


def test_the_execution_point_and_the_migration_runner_are_where_the_scan_expects_them() -> None:
    containing = {
        _relative(path)
        for path in _source_files()
        if executing_attribute_lines(path.read_text(encoding="utf-8"))
    }
    assert EXECUTION_POINT in containing
    assert containing >= MIGRATION_RUNNER_FILES
    assert all(_is_allowed_executor(name) for name in containing), sorted(containing)


def test_a_migrations_module_that_is_not_listed_may_not_run_cypher() -> None:
    source = "async def f(tx):\n    await tx.run('MATCH (n) RETURN n')\n"
    for name in ("migrations_extra.py", "migration_types.py", "migrations_network.py"):
        found = violations({f"{GRAPH_STORE}/{name}": source})
        assert any(v.startswith(f"raw-run: {GRAPH_STORE}/{name}") for v in found), name
    for name in sorted(MIGRATION_RUNNER_FILES):
        found = violations({name: source})
        assert not any(v.startswith("raw-run:") for v in found), name


@pytest.mark.parametrize(
    "source",
    [
        'async def f(tx):\n    await tx.run("MATCH (n) RETURN n")\n',
        "async def f(self, q):\n    await self._tx.run(q)\n",
        "async def f(session, q):\n    await session.run(q)\n",
        "async def f(scoped, q):\n    await scoped.tx.run(q)\n",
        "async def f(driver, q):\n    await driver.execute_query(q)\n",
        "def f(tx):\n    return tx.run\n",
        "def f(tx):\n    runner = tx.run\n    return runner\n",
        "def f(tx, q):\n    return make().tx.run(q)\n",
        "def f(a):\n    return a['k'].run('q')\n",
        "def f(tx):\n    return getattr(tx, 'run')\n",
        "def f(tx):\n    return getattr(tx, 'execute_query')\n",
        "import asyncio\ndef f(tx):\n    return asyncio.other.run, tx.run\n",
    ],
)
def test_the_scanner_flags_every_way_of_running_cypher(source: str) -> None:
    assert executing_attribute_lines(source), source


@pytest.mark.parametrize(
    "source",
    [
        "import asyncio\nasyncio.run(main())\n",
        "import subprocess\nsubprocess.run(['ls'])\n",
        "import anyio\nanyio.run(main)\n",
        "import trio\ntrio.run(main)\n",
        "import asyncio\nasyncio.get_event_loop().run(x)\n",
        "async def f(conn):\n    return await conn.run_read(work)\n",
        "def f(tx):\n    return tx.runner\n",
        "def f(x):\n    return getattr(x, 'name')\n",
        "def f(x):\n    return getattr(x)\n",
        "import asyncio\ndef f():\n    return getattr(asyncio, 'run')\n",
    ],
)
def test_the_scanner_ignores_what_is_not_a_database_call(source: str) -> None:
    assert executing_attribute_lines(source) == [], source


# 2. The context variable is created only in the kernel


def contextvar_creation_lines(source: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(_parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == "ContextVar") or (
                isinstance(func, ast.Attribute) and func.attr == "ContextVar"
            ):
                lines.append(node.lineno)
    return lines


def test_a_context_variable_is_created_only_in_the_tenancy_kernel() -> None:
    offenders = {
        _relative(path): lines
        for path in _source_files()
        if (lines := contextvar_creation_lines(path.read_text(encoding="utf-8")))
        and _relative(path) != TENANCY_KERNEL
    }
    assert offenders == {}, f"a ContextVar is created outside {TENANCY_KERNEL}: {offenders}"
    kernel = (PACKAGE_ROOT / TENANCY_KERNEL).read_text(encoding="utf-8")
    assert len(contextvar_creation_lines(kernel)) == KERNEL_CONTEXT_VARIABLES, (
        "the kernel creates exactly two ContextVars: the scope and the unit-of-work claim"
    )


@pytest.mark.parametrize(
    "source",
    [
        "from contextvars import ContextVar\nV = ContextVar('v')\n",
        "import contextvars\nV = contextvars.ContextVar('v', default=None)\n",
        "import contextvars as cv\nV: cv.ContextVar[int] = cv.ContextVar('v')\n",
    ],
)
def test_the_context_variable_scanner_flags_creation(source: str) -> None:
    assert contextvar_creation_lines(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "from contextvars import ContextVar\nV: ContextVar[int]\n",
        "import contextvars\nc = contextvars.copy_context()\n",
        "def ContextVarFactory():\n    return 1\nx = ContextVarFactory()\n",
    ],
)
def test_the_context_variable_scanner_ignores_a_mere_mention(source: str) -> None:
    assert contextvar_creation_lines(source) == []


# 3. Binding sites are listed, and the private variable stays private


def reference_lines(source: str, names: Iterable[str]) -> list[int]:
    """Lines where one of the names is imported, read as a name or read as an attribute."""
    wanted = frozenset(names)
    lines: list[int] = []
    for node in ast.walk(_parse(source)):
        if isinstance(node, ast.Name):
            found = node.id in wanted
        elif isinstance(node, ast.Attribute):
            found = node.attr in wanted
        elif isinstance(node, ast.ImportFrom | ast.Import):
            found = any(alias.name.split(".")[-1] in wanted for alias in node.names)
        else:
            found = False
        if found:
            lines.append(node.lineno)
    return lines


def _binding_offenders() -> dict[str, list[int]]:
    offenders: dict[str, list[int]] = {}
    for path in _source_files():
        relative = _relative(path)
        if relative == TENANCY_KERNEL or _module_name(relative) in BINDING_MODULES:
            continue
        if lines := reference_lines(path.read_text(encoding="utf-8"), BINDING_NAMES):
            offenders[relative] = lines
    return offenders


def test_bind_scope_and_bind_tenant_are_referenced_only_in_the_kernel_and_the_listed_modules() -> (
    None
):
    assert _binding_offenders() == {}


def test_the_listed_binding_modules_exist() -> None:
    existing = {_module_name(_relative(path)) for path in _source_files()}
    assert existing >= BINDING_MODULES, sorted(BINDING_MODULES - existing)
    assert isinstance(BINDING_MODULES, frozenset)


def test_the_private_scope_variable_is_not_referenced_outside_the_kernel() -> None:
    offenders = {
        _relative(path): lines
        for path in _source_files()
        if _relative(path) != TENANCY_KERNEL
        and (lines := reference_lines(path.read_text(encoding="utf-8"), {PRIVATE_SCOPE_NAME}))
    }
    assert offenders == {}
    kernel = (PACKAGE_ROOT / TENANCY_KERNEL).read_text(encoding="utf-8")
    assert reference_lines(kernel, {PRIVATE_SCOPE_NAME}), "the kernel no longer defines _SCOPE"
    defined = {node.name for node in ast.walk(_parse(kernel)) if isinstance(node, ast.FunctionDef)}
    assert defined >= BINDING_NAMES, "the kernel no longer defines the binders"


def test_the_private_unit_claim_is_not_referenced_outside_the_kernel() -> None:
    offenders = {
        _relative(path): lines
        for path in _source_files()
        if _relative(path) != TENANCY_KERNEL
        and (lines := reference_lines(path.read_text(encoding="utf-8"), {PRIVATE_UNIT_NAME}))
    }
    assert offenders == {}
    kernel = (PACKAGE_ROOT / TENANCY_KERNEL).read_text(encoding="utf-8")
    assert reference_lines(kernel, {PRIVATE_UNIT_NAME}), "the kernel no longer defines _UNIT"


def test_the_claim_functions_are_referenced_only_in_the_kernel_and_the_unit_of_work() -> None:
    offenders = {
        _relative(path): lines
        for path in _source_files()
        if _relative(path) != TENANCY_KERNEL
        and _module_name(_relative(path)) not in CLAIM_MODULES
        and (lines := reference_lines(path.read_text(encoding="utf-8"), CLAIM_NAMES))
    }
    assert offenders == {}
    existing = {_module_name(_relative(path)) for path in _source_files()}
    assert existing >= CLAIM_MODULES, sorted(CLAIM_MODULES - existing)
    kernel = (PACKAGE_ROOT / TENANCY_KERNEL).read_text(encoding="utf-8")
    defined = {node.name for node in ast.walk(_parse(kernel)) if isinstance(node, ast.FunctionDef)}
    assert defined >= CLAIM_NAMES, "the kernel no longer defines the claim functions"
    unit = (PACKAGE_ROOT / "adapters/outbound/graph_store/unit_of_work.py").read_text(
        encoding="utf-8"
    )
    assert reference_lines(unit, CLAIM_NAMES), "the unit of work no longer takes the claim"


@pytest.mark.parametrize(
    ("source", "names"),
    [
        ("from diucs.application.tenancy import claim_unit\n", CLAIM_NAMES),
        ("from diucs.application import tenancy\ntenancy.release_unit(o)\n", CLAIM_NAMES),
        ("from diucs.application.tenancy import _UNIT\n", {PRIVATE_UNIT_NAME}),
        ("from diucs.application import tenancy\nv = tenancy._UNIT\n", {PRIVATE_UNIT_NAME}),
    ],
)
def test_the_claim_scanner_finds_the_claim_names(source: str, names: Iterable[str]) -> None:
    assert reference_lines(source, names) != []


@pytest.mark.parametrize(
    ("source", "names"),
    [
        ("from diucs.application.tenancy import bind_tenant\n", BINDING_NAMES),
        ("from diucs.application.tenancy import bind_scope as bs\n", BINDING_NAMES),
        (
            "from diucs.application import tenancy\nwith tenancy.bind_tenant('a1'):\n    pass\n",
            BINDING_NAMES,
        ),
        ("import bind_scope\n", BINDING_NAMES),
        ("x = bind_scope\n", BINDING_NAMES),
        ("from diucs.application.tenancy import _SCOPE\n", {PRIVATE_SCOPE_NAME}),
        ("from diucs.application import tenancy\nv = tenancy._SCOPE\n", {PRIVATE_SCOPE_NAME}),
    ],
)
def test_the_reference_scanner_finds_imports_names_and_attributes(
    source: str, names: Iterable[str]
) -> None:
    assert reference_lines(source, names) != []


def test_the_reference_scanner_ignores_other_names() -> None:
    source = "from diucs.application.tenancy import current_tenant\nx = current_tenant()\n"
    assert reference_lines(source, BINDING_NAMES | {PRIVATE_SCOPE_NAME}) == []


# 4. No function in the graph store takes a tenant


def tenant_parameter_lines(source: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(_parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            arguments = node.args
            every = [
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
                *([arguments.vararg] if arguments.vararg else []),
                *([arguments.kwarg] if arguments.kwarg else []),
            ]
            if any(arg.arg in TENANT_PARAMETER_NAMES for arg in every):
                lines.append(node.lineno)
    return lines


def test_no_graph_store_function_takes_a_tenant_parameter() -> None:
    offenders: dict[str, list[int]] = {}
    scanned = 0
    for path in _source_files():
        relative = _relative(path)
        if not relative.startswith(f"{GRAPH_STORE}/"):
            continue
        scanned += 1
        if _module_name(relative) in TENANT_PARAMETER_MODULES:
            continue
        if lines := tenant_parameter_lines(path.read_text(encoding="utf-8")):
            offenders[relative] = lines
    assert scanned > 10, "the scan found too few graph store files"
    assert offenders == {}, f"a graph store function takes a tenant argument: {offenders}"


def test_the_listed_tenant_parameter_modules_exist_and_are_in_the_graph_store() -> None:
    existing = {_module_name(_relative(path)) for path in _source_files()}
    assert existing >= TENANT_PARAMETER_MODULES, sorted(TENANT_PARAMETER_MODULES - existing)
    graph_store = _module_name(GRAPH_STORE)
    assert all(name.startswith(f"{graph_store}.") for name in TENANT_PARAMETER_MODULES)
    assert isinstance(TENANT_PARAMETER_MODULES, frozenset)


@pytest.mark.parametrize(
    "source",
    [
        "def f(tenant):\n    pass\n",
        "def f(a, tenant_id):\n    pass\n",
        "async def f(a, *, tenant=None):\n    pass\n",
        "def f(tenant, /, a):\n    pass\n",
        "def f(*tenant):\n    pass\n",
        "def f(**tenant_id):\n    pass\n",
        "class C:\n    def m(self, tenant):\n        pass\n",
        "f = lambda tenant: tenant\n",
    ],
)
def test_the_parameter_scanner_flags_every_way_of_taking_a_tenant(source: str) -> None:
    assert tenant_parameter_lines(source) != [], source


@pytest.mark.parametrize(
    "source",
    [
        "def f(tenants):\n    pass\n",
        "def f(a, **params):\n    pass\n",
        "def f(tenantId):\n    pass\n",
        "def f(scope, tenant_name):\n    pass\n",
        "x = {'tenant': 1}\n",
    ],
)
def test_the_parameter_scanner_ignores_other_names(source: str) -> None:
    assert tenant_parameter_lines(source) == [], source


# 5. Only the two adapter query packages may use the execution point

# The two adapter query packages: the Neo4j graph store and the Neo4j audit and outbox adapter.
# Statements live in them, and only they call run_query and run_global_query.
QUERY_PACKAGES = (f"{GRAPH_STORE}/", "adapters/outbound/audit_neo4j/")
QUERY_RUNNERS = frozenset({"run_query", "run_global_query"})
STATEMENT_TYPES = frozenset({"NamedQuery", "QueryTemplate"})


def _in_query_packages(relative: str) -> bool:
    return relative.startswith(QUERY_PACKAGES)


def runner_reference_lines(source: str) -> list[int]:
    return reference_lines(source, QUERY_RUNNERS)


def statement_construction_lines(source: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(_parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in STATEMENT_TYPES:
                lines.append(node.lineno)
    return lines


@pytest.mark.parametrize(
    "source",
    [
        "from diucs.adapters.outbound.graph_store.driver import run_query\n",
        "from x import run_global_query as g\n",
        "from diucs.adapters.outbound.graph_store import driver\nrows = driver.run_query(tx, q)\n",
        "async def f(tx, q):\n    return await run_query(tx, q)\n",
    ],
)
def test_the_runner_scanner_finds_every_way_of_naming_the_execution_point(source: str) -> None:
    assert runner_reference_lines(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "NamedQuery(id='Q-X', cypher='RETURN 1', mode='read')\n",
        "from x import queries\nqueries.NamedQuery(id='Q-X', cypher='RETURN 1', mode='read')\n",
        "QueryTemplate(id='Q-X', cypher='RETURN 1', mode='read')\n",
    ],
)
def test_the_construction_scanner_finds_a_statement_being_built(source: str) -> None:
    assert statement_construction_lines(source) != []
    assert statement_construction_lines("x: NamedQuery\nimport NamedQuery\n") == []


# 6. A statement is a fixed text in the code: nothing builds Cypher from pieces

# The Cypher words that tell a string is a statement. Upper case only: that is how every statement
# in this code base is written, and prose in a log message rarely has them.
CYPHER_WORDS = re.compile(r"\b(?:MATCH|MERGE|UNWIND|CREATE|DETACH DELETE|OPTIONAL MATCH)\b")

# The statements that splice a constant into another today (an f-string with a module constant, or
# `"..." + _READ`), by module and number. This is a ratchet: a conversion bundle lowers a number
# in the commit that makes the statement one literal, and nothing raises one or adds a module.
BUILT_CYPHER_RATCHET: dict[str, int] = {
    f"{GRAPH_STORE}/capacity_repository.py": 2,
    f"{GRAPH_STORE}/communication_repository.py": 3,
    f"{GRAPH_STORE}/scheduled_work_repository.py": 2,
}


def _constant_text(node: ast.AST) -> str:
    return " ".join(
        n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    )


def _is_string_building(node: ast.AST) -> bool:
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Mod):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"format", "join"}
    )


def cypher_building_lines(source: str) -> list[int]:
    """Lines of every f-string, `+`, `%`, `.format` and `.join` that builds text with a Cypher word
    in it, and of every `+=` of such text. The outermost expression counts once."""
    lines: list[int] = []

    def visit(node: ast.AST) -> None:
        building = _is_string_building(node) or isinstance(node, ast.AugAssign)
        if building and CYPHER_WORDS.search(_constant_text(node)):
            lines.append(getattr(node, "lineno", 0))
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(_parse(source))
    return lines


@pytest.mark.parametrize(
    "source",
    [
        'def f(label):\n    return f"MATCH (n:{label}) RETURN n"\n',
        'def f(a):\n    return "MATCH (n) WHERE n.k = " + a\n',
        'def f(a):\n    return "MATCH (n) " + a + " RETURN n"\n',
        'def f(a):\n    return "MATCH (n:{}) RETURN n".format(a)\n',
        'def f(a):\n    return "MATCH (n:%s) RETURN n" % a\n',
        'def f(a):\n    return " ".join(["MATCH (n)", a])\n',
        'def f(a):\n    q = "RETURN n"\n    q += " MERGE (m)"\n    return q\n',
        'x = f"UNWIND $rows AS row {tail}"\n',
        'x = "CREATE (n)" "-[:R]->" + tail\n',
    ],
)
def test_the_building_scanner_flags_cypher_built_from_pieces(source: str) -> None:
    assert cypher_building_lines(source) != [], source


@pytest.mark.parametrize(
    "source",
    [
        'Q = "MATCH (n:Marker {key: $key}) RETURN n"\n',
        'Q = ("MATCH (n:Marker {key: $key}) " "RETURN n")\n',
        'def f(a):\n    return f"the id is {a}"\n',
        'def f(a):\n    return "id " + a\n',
        'def f(a):\n    return "a, b".join(a)\n',
        'LOG = "could not CREATE the thing"\n',
        'def f(a):\n    return "match " + a\n',
    ],
)
def test_the_building_scanner_ignores_a_fixed_statement_and_ordinary_text(source: str) -> None:
    result = cypher_building_lines(source)
    # "could not CREATE the thing" is a plain constant, not built: never flagged.
    assert result == [], source


def test_a_nested_expression_counts_once() -> None:
    source = 'def f(a, b):\n    return "MATCH (n) " + a + " WHERE " + b\n'
    assert len(cypher_building_lines(source)) == 1


def test_the_ratchet_modules_are_graph_store_modules_and_the_numbers_are_whole() -> None:
    assert all(name.startswith(f"{GRAPH_STORE}/") for name in BUILT_CYPHER_RATCHET)
    assert all(isinstance(count, int) and count > 0 for count in BUILT_CYPHER_RATCHET.values())


# 7. Statements are run by registered objects, never by a literal id or text


def runner_call_problems(source: str) -> list[int]:
    """Lines of a run_query or run_global_query call whose statement argument is a literal (a
    string, an f-string, a concatenation or a format), or that passes `registry=`: the registry is
    the module one in production code."""
    lines: list[int] = []
    for node in ast.walk(_parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name not in QUERY_RUNNERS:
            continue
        literal = len(node.args) > 1 and (
            (isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str))
            or _is_string_building(node.args[1])
        )
        if literal or any(keyword.arg == "registry" for keyword in node.keywords):
            lines.append(node.lineno)
    return lines


@pytest.mark.parametrize(
    "source",
    [
        'async def f(tx):\n    return await run_query(tx, "Q-X")\n',
        'async def f(tx, a):\n    return await run_query(tx, f"Q-{a}")\n',
        'async def f(tx, a):\n    return await run_global_query(tx, "Q-" + a)\n',
        "async def f(tx, r):\n    return await run_query(tx, REGISTRY.get('Q-X'), registry=r)\n",
        'async def f(tx):\n    return await driver.run_query(tx, "Q-X", id=1)\n',
    ],
)
def test_the_call_scanner_flags_a_literal_statement_and_a_private_registry(source: str) -> None:
    assert runner_call_problems(source) != [], source


@pytest.mark.parametrize(
    "source",
    [
        'async def f(tx):\n    return await run_query(tx, REGISTRY.get("Q-X"), id=1)\n',
        "async def f(tx, query):\n    return await run_query(tx, query)\n",
        "async def f(tx):\n    return await run_global_query(tx, _PING)\n",
        "def f(tx):\n    return other(tx, 'Q-X')\n",
    ],
)
def test_the_call_scanner_accepts_a_statement_object(source: str) -> None:
    assert runner_call_problems(source) == [], source


# 8. The whole check, on a tree


def load_tree(root: Path) -> dict[str, str]:
    files = {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.py"))
    }
    assert len(files) > 50, "the scan found too few files: it is not looking at backend/src/diucs"
    return files


def violations(files: Mapping[str, str]) -> list[str]:
    """Every breach of the rules of this file, as 'rule: path:line', for a tree given as
    {path relative to src/diucs: source}."""
    found: list[str] = []
    built: dict[str, int] = {}
    for relative, source in sorted(files.items()):
        if not _is_allowed_executor(relative):
            found += [f"raw-run: {relative}:{n}" for n in executing_attribute_lines(source)]
        if not _in_query_packages(relative):
            found += [
                f"runner-outside-packages: {relative}:{n}" for n in runner_reference_lines(source)
            ]
        if not _in_query_packages(relative):
            found += [
                f"statement-outside-packages: {relative}:{n}"
                for n in statement_construction_lines(source)
            ]
        found += [f"literal-statement-call: {relative}:{n}" for n in runner_call_problems(source)]
        if lines := cypher_building_lines(source):
            built[relative] = len(lines)
    for relative, count in sorted(built.items()):
        allowed = BUILT_CYPHER_RATCHET.get(relative, 0)
        if count != allowed:
            found.append(f"built-cypher: {relative} has {count}, the ratchet says {allowed}")
    for relative, allowed in sorted(BUILT_CYPHER_RATCHET.items()):
        if relative not in built:
            found.append(f"built-cypher: {relative} has 0, the ratchet says {allowed}")
    return found


def test_the_real_tree_follows_every_rule() -> None:
    assert violations(load_tree(PACKAGE_ROOT)) == []


def test_the_real_tree_has_the_things_the_scan_looks_for() -> None:
    files = load_tree(PACKAGE_ROOT)
    defined = {
        node.name
        for node in ast.walk(_parse(files[f"{GRAPH_STORE}/driver.py"]))
        if isinstance(node, ast.AsyncFunctionDef)
    }
    assert defined >= QUERY_RUNNERS, "driver.py defines the runners"
    assert statement_construction_lines(files[f"{GRAPH_STORE}/health.py"])
    assert any(
        runner_reference_lines(source)
        for name, source in files.items()
        if name.startswith(QUERY_PACKAGES[1])
    )
    assert sum(BUILT_CYPHER_RATCHET.values()) == sum(
        len(cypher_building_lines(source)) for source in files.values()
    )


# 9. The probe: a module that breaks the rules makes the check fail

PROBE_OUTSIDE = '''"""A probe that does everything the rules forbid."""
from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import NamedQuery

LABEL = "Organization"
Q = NamedQuery(id="Q-PROBE", cypher="MATCH (n) RETURN n", mode="read")


async def leak(session, tx, driver, name):
    await session.run("MATCH (n) RETURN n")
    await tx.run(f"MATCH (n:{name}) RETURN n")
    await driver.execute_query("MATCH (n) RETURN n" + name)
    return await run_query(tx, "Q-PROBE")
'''

PROBE_INSIDE = '''"""A probe inside a query package: raw run and string-built Cypher."""


async def leak(tx, label):
    return await tx.run("MATCH (n:%s) RETURN n" % label)
'''


def test_a_probe_module_outside_the_query_packages_fails_every_rule() -> None:
    files = {**load_tree(PACKAGE_ROOT), "adapters/inbound/fhir_rest/probe.py": PROBE_OUTSIDE}
    found = [line for line in violations(files) if "probe.py" in line]
    rules = {line.split(":")[0] for line in found}
    assert rules == {
        "raw-run",
        "runner-outside-packages",
        "statement-outside-packages",
        "literal-statement-call",
        "built-cypher",
    }, found
    assert len([line for line in found if line.startswith("raw-run")]) == 3


def test_a_probe_module_in_a_query_package_still_fails_raw_run_and_built_cypher() -> None:
    files = {**load_tree(PACKAGE_ROOT), f"{GRAPH_STORE}/probe.py": PROBE_INSIDE}
    found = [line for line in violations(files) if "probe.py" in line]
    assert {line.split(":")[0] for line in found} == {"raw-run", "built-cypher"}, found


def test_a_probe_in_the_audit_package_fails_raw_run() -> None:
    files = {
        **load_tree(PACKAGE_ROOT),
        "adapters/outbound/audit_neo4j/probe.py": PROBE_INSIDE,
    }
    assert any(
        line.startswith("raw-run") and "audit_neo4j/probe.py" in line for line in violations(files)
    )


def test_raising_a_ratchet_number_or_lowering_a_source_count_is_a_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = load_tree(PACKAGE_ROOT)
    monkeypatch.setitem(BUILT_CYPHER_RATCHET, f"{GRAPH_STORE}/capacity_repository.py", 3)
    assert any(line.startswith("built-cypher") for line in violations(files))
    monkeypatch.setitem(BUILT_CYPHER_RATCHET, f"{GRAPH_STORE}/capacity_repository.py", 2)
    monkeypatch.setitem(BUILT_CYPHER_RATCHET, f"{GRAPH_STORE}/queries.py", 1)
    assert any("queries.py has 0" in line for line in violations(files))
