"""Architecture tests: the hexagonal import rules fail the build when crossed.

The real rules live in backend/.importlinter. Each negative test builds a throwaway
package named diucs_probe in tmp_path, copies the real contracts with the package name
swapped, plants one illegal import, and asserts that lint-imports fails on that contract.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
CONFIG = BACKEND / ".importlinter"

DOMAIN_CONTRACT = "Domain stays pure"
APPLICATION_CONTRACT = "Application stays pure"
INDEPENDENCE_CONTRACT = "Adapters are independent"
LAYERS_CONTRACT = "Layers"

# A clean probe tree: every package the real contracts name, with no violations.
PROBE_TREE: dict[str, str] = {
    "diucs_probe/__init__.py": "",
    "diucs_probe/domain/__init__.py": "",
    "diucs_probe/domain/ok.py": "import datetime\n",
    "diucs_probe/application/__init__.py": "",
    "diucs_probe/application/use_case.py": "from diucs_probe.domain import ok\n",
    "diucs_probe/bootstrap/__init__.py": "",
    "diucs_probe/adapters/__init__.py": "",
    "diucs_probe/adapters/x.py": "",
    "diucs_probe/adapters/inbound/__init__.py": "",
    "diucs_probe/adapters/outbound/__init__.py": "",
    "diucs_probe/adapters/outbound/a.py": "",
    "diucs_probe/adapters/outbound/b.py": "",
    # The two modules named in .importlinter's ignore_imports (DEC-055), so the ignore has a target.
    "diucs_probe/adapters/outbound/graph_store/__init__.py": "",
    "diucs_probe/adapters/outbound/graph_store/driver.py": "",
    "diucs_probe/adapters/outbound/graph_store/queries.py": "",
    "diucs_probe/adapters/outbound/audit_neo4j/__init__.py": "",
    "diucs_probe/adapters/outbound/audit_neo4j/audit_log.py": (
        "import diucs_probe.adapters.outbound.graph_store.driver\n"
        "import diucs_probe.adapters.outbound.graph_store.queries\n"
    ),
    "diucs_probe/adapters/testing/__init__.py": "",
}


def _lint(
    config: Path, cwd: Path, pythonpath: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from importlinter.cli import lint_imports_command; lint_imports_command()",
            "--no-cache",
            "--config",
            str(config),
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )


def _probe_config(tmp_path: Path) -> Path:
    assert CONFIG.is_file(), "backend/.importlinter is missing: no import contracts exist"
    text = CONFIG.read_text(encoding="utf-8")
    probe_text = re.sub(r"\bdiucs\b", "diucs_probe", text)
    target = tmp_path / "probe.importlinter"
    target.write_text(probe_text, encoding="utf-8")
    return target


def _build_probe(tmp_path: Path, extra: dict[str, str]) -> Path:
    root = tmp_path / "src"
    for relpath, source in {**PROBE_TREE, **extra}.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return root


def test_real_tree_passes_every_contract() -> None:
    assert CONFIG.is_file(), "backend/.importlinter is missing: no import contracts exist"
    result = _lint(CONFIG, cwd=BACKEND)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "4 kept, 0 broken" in output, output


def test_probe_with_clean_domain_passes(tmp_path: Path) -> None:
    config = _probe_config(tmp_path)
    src = _build_probe(tmp_path, {})
    result = _lint(config, cwd=tmp_path, pythonpath=src)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "0 broken" in output, output


def test_domain_importing_adapter_breaks_domain_contract(tmp_path: Path) -> None:
    config = _probe_config(tmp_path)
    src = _build_probe(tmp_path, {"diucs_probe/domain/bad.py": "import diucs_probe.adapters.x\n"})
    result = _lint(config, cwd=tmp_path, pythonpath=src)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert f"{DOMAIN_CONTRACT} BROKEN" in output, output


def test_adapter_importing_sibling_adapter_breaks_independence(tmp_path: Path) -> None:
    config = _probe_config(tmp_path)
    src = _build_probe(
        tmp_path,
        {"diucs_probe/adapters/outbound/a.py": "import diucs_probe.adapters.outbound.b\n"},
    )
    result = _lint(config, cwd=tmp_path, pythonpath=src)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert f"{INDEPENDENCE_CONTRACT} BROKEN" in output, output


@pytest.mark.parametrize(
    ("relpath", "source", "contract"),
    [
        (
            "diucs_probe/application/bad.py",
            "import diucs_probe.adapters.x\n",
            APPLICATION_CONTRACT,
        ),
        (
            "diucs_probe/application/bad.py",
            "import diucs_probe.bootstrap\n",
            APPLICATION_CONTRACT,
        ),
        (
            "diucs_probe/domain/bad.py",
            "import neo4j\n",
            DOMAIN_CONTRACT,
        ),
        (
            "diucs_probe/application/bad.py",
            "import fastapi\n",
            APPLICATION_CONTRACT,
        ),
    ],
)
def test_forbidden_import_breaks_named_contract(
    tmp_path: Path, relpath: str, source: str, contract: str
) -> None:
    config = _probe_config(tmp_path)
    src = _build_probe(tmp_path, {relpath: source})
    result = _lint(config, cwd=tmp_path, pythonpath=src)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert f"{contract} BROKEN" in output, output


def _swapped_layers_config(tmp_path: Path) -> Path:
    """The probe config with the layer order reversed, to show the Layers contract bites."""
    text = _probe_config(tmp_path).read_text(encoding="utf-8")
    old = "    bootstrap\n    adapters\n    application\n    domain\n"
    assert old in text, "layers block not found in backend/.importlinter"
    target = tmp_path / "swapped.importlinter"
    target.write_text(
        text.replace(old, "    domain\n    application\n    adapters\n    bootstrap\n"),
        encoding="utf-8",
    )
    return target


def test_adapter_importing_bootstrap_breaks_layers_contract(tmp_path: Path) -> None:
    config = _probe_config(tmp_path)
    src = _build_probe(
        tmp_path,
        {"diucs_probe/adapters/outbound/a.py": "import diucs_probe.bootstrap\n"},
    )
    result = _lint(config, cwd=tmp_path, pythonpath=src)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "Layers BROKEN" in output, output


def test_adapter_importing_application_passes_layers_contract(tmp_path: Path) -> None:
    config = _probe_config(tmp_path)
    src = _build_probe(
        tmp_path,
        {"diucs_probe/adapters/outbound/a.py": "import diucs_probe.application.use_case\n"},
    )
    result = _lint(config, cwd=tmp_path, pythonpath=src)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Layers KEPT" in output, output


def test_swapped_layer_order_rejects_adapter_importing_application(tmp_path: Path) -> None:
    config = _swapped_layers_config(tmp_path)
    src = _build_probe(
        tmp_path,
        {"diucs_probe/adapters/outbound/a.py": "import diucs_probe.application.use_case\n"},
    )
    result = _lint(config, cwd=tmp_path, pythonpath=src)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "Layers BROKEN" in output, output


# Allowlist rules (prompt F02, "Rules you need"). The import-linter contracts above are
# blacklists; these tests state what the domain and application may import, so an unlisted
# third-party package fails the build. Only direct imports are read: fhir.resources pulls
# in pydantic internally, and that indirect path is not a violation.
DOMAIN_INTERNAL = ("diucs.domain",)
DOMAIN_EXTERNAL = ("fhir.resources",)
APPLICATION_INTERNAL = ("diucs.application", "diucs.domain")
APPLICATION_EXTERNAL: tuple[str, ...] = ()

SRC_ROOT = BACKEND / "src"


def _imports_of(path: Path, package: list[str]) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                names.append(node.module or "")
            else:
                base = package[: len(package) - (node.level - 1)]
                names.append(".".join([*base, *([node.module] if node.module else [])]))
    return names


def _allowed(name: str, internal: tuple[str, ...], external: tuple[str, ...]) -> bool:
    if name.split(".")[0] in sys.stdlib_module_names:
        return True
    return any(name == prefix or name.startswith(prefix + ".") for prefix in (*internal, *external))


def _allowlist_violations(
    src_root: Path, layer: str, internal: tuple[str, ...], external: tuple[str, ...]
) -> list[str]:
    found: list[str] = []
    for path in sorted((src_root / Path(*layer.split("."))).rglob("*.py")):
        rel = path.relative_to(src_root)
        for name in _imports_of(path, list(rel.parent.parts)):
            if not _allowed(name, internal, external):
                found.append(f"{rel.as_posix()} imports {name}")
    return found


def test_real_domain_imports_are_on_the_allowlist() -> None:
    assert any((SRC_ROOT / "diucs" / "domain").rglob("*.py")), "no domain files were scanned"
    assert _allowlist_violations(SRC_ROOT, "diucs.domain", DOMAIN_INTERNAL, DOMAIN_EXTERNAL) == []


def test_real_application_imports_are_on_the_allowlist() -> None:
    assert any((SRC_ROOT / "diucs" / "application").rglob("*.py")), "no application files scanned"
    assert (
        _allowlist_violations(
            SRC_ROOT, "diucs.application", APPLICATION_INTERNAL, APPLICATION_EXTERNAL
        )
        == []
    )


def _layer_file(tmp_path: Path, layer: str, relpath: str, source: str) -> Path:
    src = tmp_path / "src"
    target = src / "diucs" / layer / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return src


@pytest.mark.parametrize(
    "source",
    [
        "import datetime\nfrom typing import Protocol\n",
        "from fhir.resources.patient import Patient\n",
        "from diucs.domain import errors\nfrom . import errors as same\n",
    ],
)
def test_domain_allowlist_accepts_permitted_imports(tmp_path: Path, source: str) -> None:
    src = _layer_file(tmp_path, "domain", "ok.py", source)
    assert _allowlist_violations(src, "diucs.domain", DOMAIN_INTERNAL, DOMAIN_EXTERNAL) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import pydantic\n", "pydantic"),
        ("from pydantic import BaseModel\n", "pydantic"),
        ("import httpx\n", "httpx"),
        ("import diucs.adapters.x\n", "diucs.adapters.x"),
        ("from ..adapters import x\n", "diucs.adapters"),
    ],
)
def test_domain_allowlist_rejects_unlisted_imports(
    tmp_path: Path, source: str, expected: str
) -> None:
    src = _layer_file(tmp_path, "domain", "bad.py", source)
    found = _allowlist_violations(src, "diucs.domain", DOMAIN_INTERNAL, DOMAIN_EXTERNAL)
    assert any(f"imports {expected}" in line for line in found), found


def test_application_allowlist_rejects_fhir_and_adapters(tmp_path: Path) -> None:
    src = _layer_file(tmp_path, "application", "bad.py", "import fhir.resources\n")
    found = _allowlist_violations(
        src, "diucs.application", APPLICATION_INTERNAL, APPLICATION_EXTERNAL
    )
    assert any("imports fhir.resources" in line for line in found), found

    src = _layer_file(tmp_path, "application", "worse.py", "import diucs.adapters.x\n")
    found = _allowlist_violations(
        src, "diucs.application", APPLICATION_INTERNAL, APPLICATION_EXTERNAL
    )
    assert any("imports diucs.adapters.x" in line for line in found), found
