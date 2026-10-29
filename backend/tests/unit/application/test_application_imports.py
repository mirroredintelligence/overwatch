"""The application layer does not import OpenTelemetry (O01): the adapter supplies the tracer."""

import ast
from pathlib import Path

APPLICATION = Path(__file__).resolve().parents[3] / "src" / "diucs" / "application"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_no_application_module_imports_opentelemetry() -> None:
    offenders = {
        str(path.relative_to(APPLICATION))
        for path in APPLICATION.rglob("*.py")
        if any(
            name == "opentelemetry" or name.startswith("opentelemetry.")
            for name in _imported_modules(path)
        )
    }

    assert offenders == set()
