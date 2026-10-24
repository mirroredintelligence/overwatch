"""Architecture tests: the hexagonal import rules fail the build when crossed.

The real rules live in backend/.importlinter. Each negative test builds a throwaway
package named diucs_probe in tmp_path, copies the real contracts with the package name
swapped, plants one illegal import, and asserts that lint-imports fails on that contract.
"""

from __future__ import annotations

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
    assert DOMAIN_CONTRACT in output, output
    assert "BROKEN" in output, output


def test_adapter_importing_sibling_adapter_breaks_independence(tmp_path: Path) -> None:
    config = _probe_config(tmp_path)
    src = _build_probe(
        tmp_path,
        {"diucs_probe/adapters/outbound/a.py": "import diucs_probe.adapters.outbound.b\n"},
    )
    result = _lint(config, cwd=tmp_path, pythonpath=src)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert INDEPENDENCE_CONTRACT in output, output
    assert "BROKEN" in output, output


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
    assert contract in output, output
