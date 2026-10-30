"""The markers of the shared-Neo4j harness and the conventions that keep it honest (TEN-034).

`schema`: the test changes or asserts the schema, so it uses a private container (`own_neo4j`).
`lifecycle`: the test stops, starts or removes a container, so it uses a private one too.
`exclusive`: the test cannot share the machine with another run (it asserts something about the
whole database, or needs the compose stack or the Service Bus emulator); it runs in a session of its
own, after the parallel one. A test that needs a private container says so with a marker, so the
parallel phase can leave it to the serial one if it wants to, and the reader knows why.
"""

import ast
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.support.harness_mode import (
    ExclusiveUnderParallel,
    exclusive_selected,
    refuse_exclusive_under_parallel,
)

BACKEND = Path(__file__).resolve().parents[3]
TESTS = BACKEND / "tests"
INTEGRATION = TESTS / "integration"
NEEDS_A_PRIVATE_CONTAINER = ("own_neo4j", "throwaway_driver")
PRIVATE_MARKERS = {"schema", "lifecycle"}


def _item(*markers: str) -> SimpleNamespace:
    return SimpleNamespace(
        get_closest_marker=lambda name: object() if name in markers else None,
        nodeid="tests/x.py::test_x",
    )


def test_the_markers_are_registered_with_what_they_mean() -> None:
    config = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    registered = {
        entry.split(":", 1)[0]: entry
        for entry in config["tool"]["pytest"]["ini_options"]["markers"]
    }

    for name in ("schema", "lifecycle", "exclusive"):
        assert name in registered, f"marker {name} is not registered in pyproject.toml"
        assert len(registered[name].split(":", 1)[1].strip()) > 20, f"{name} has no description"


def test_a_selection_with_an_exclusive_test_is_an_exclusive_run() -> None:
    assert exclusive_selected([_item(), _item("exclusive")]) is True


def test_a_selection_with_no_exclusive_test_shares_the_instance() -> None:
    assert exclusive_selected([_item(), _item("schema"), _item("lifecycle")]) is False


def test_an_empty_selection_shares_the_instance() -> None:
    assert exclusive_selected([]) is False


def test_an_exclusive_test_under_parallel_workers_is_refused_with_the_command_to_use() -> None:
    with pytest.raises(ExclusiveUnderParallel) as failure:
        refuse_exclusive_under_parallel([_item("exclusive")], workers=4)

    message = str(failure.value)
    assert "-m exclusive" in message
    assert "not exclusive" in message


def test_parallel_workers_with_no_exclusive_test_are_fine() -> None:
    refuse_exclusive_under_parallel([_item(), _item("schema")], workers=4)


@pytest.mark.parametrize("workers", [0, 1, None])
def test_an_exclusive_test_in_a_session_with_no_workers_is_fine(workers: int | None) -> None:
    refuse_exclusive_under_parallel([_item("exclusive")], workers=workers)


def _integration_modules() -> list[Path]:
    return sorted(INTEGRATION.rglob("test_*.py"))


def _marker_names(tree: ast.AST) -> set[str]:
    """Every `pytest.mark.<name>` the module mentions: pytestmark lines and decorators."""
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
    }


def _names_used(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.rsplit(".", 1)[-1])
    return names


def test_a_test_module_that_starts_its_own_container_says_why_with_a_marker() -> None:
    unmarked = []
    for module in _integration_modules():
        tree = ast.parse(module.read_text(encoding="utf-8"))
        if _names_used(tree) & set(NEEDS_A_PRIVATE_CONTAINER) and not (
            _marker_names(tree) & PRIVATE_MARKERS
        ):
            unmarked.append(str(module.relative_to(TESTS)))

    assert unmarked == [], f"these modules use a private container without a marker: {unmarked}"


def test_the_contracted_container_is_retired() -> None:
    """The shared schema is the contracted schema since TEN-032, so no module needs a second
    container only to drop keys that are gone (TEN-034)."""
    users = []
    for module in sorted(TESTS.rglob("*.py")):
        if module == Path(__file__):
            continue
        if "contracted_container" in module.read_text(encoding="utf-8"):
            users.append(str(module.relative_to(TESTS)))

    assert users == [], f"contracted_container is still named in: {users}"


def test_no_integration_test_wipes_the_whole_database_of_the_shared_instance() -> None:
    """`wipe_all` is for a database this run owns; a module that calls it on the harness driver
    would empty other runs' tenants. The modules that may call it use a private container."""
    offenders = []
    for module in _integration_modules():
        text = module.read_text(encoding="utf-8")
        tree = ast.parse(text)
        if "wipe_all" not in _names_used(tree):
            continue
        if (
            not (_marker_names(tree) & PRIVATE_MARKERS)
            and module.name != "test_tenant_scope_harness.py"
        ):
            offenders.append(str(module.relative_to(TESTS)))

    assert offenders == [], f"wipe_all outside a marked private-container module: {offenders}"
