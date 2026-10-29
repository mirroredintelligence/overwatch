"""A formatter run from the repo root must not rewrap files outside the back end.

Some agent ran `ruff format` at the root: it used ruff's default line length (88) and rewrote the
delivery scripts, the evidence scripts and a prompt. The root config now excludes everything that is
not back-end code, and `force-exclude` keeps the exclusion when a path is named on the command line.
"""

import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXCLUDED = {".claude", "docs", "frontend", "infra"}


def _config() -> dict[str, Any]:
    return tomllib.loads((ROOT / "ruff.toml").read_text(encoding="utf-8"))


def test_the_root_config_exists_and_forces_its_exclusions() -> None:
    config = _config()
    assert config.get("force-exclude") is True


def test_the_root_config_excludes_every_directory_that_is_not_back_end_code() -> None:
    excluded = {str(item).rstrip("/") for item in _config()["extend-exclude"]}
    assert excluded >= EXCLUDED


def test_the_root_config_keeps_the_project_line_length() -> None:
    assert _config().get("line-length") == 100
