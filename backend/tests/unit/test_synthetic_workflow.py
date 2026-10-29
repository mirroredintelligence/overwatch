"""Checks on .github/workflows/synthetic.yml (O09). They parse the YAML so a typo fails locally."""

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "synthetic.yml"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    assert WORKFLOW.is_file(), f"missing {WORKFLOW.relative_to(REPO_ROOT)}"
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


def _steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    (job,) = workflow["jobs"].values()
    return job["steps"]


def test_it_is_started_by_hand_and_its_schedule_is_off_until_the_owner_turns_it_on(
    workflow: dict[str, Any],
) -> None:
    # The owner has asked that scheduled Actions runs are not billed (CLAUDE.md, ci.yml). The
    # ten-minute schedule stays in a comment until the owner turns it on.
    # PyYAML reads the key `on` as the boolean True.
    triggers = workflow.get(True, workflow.get("on"))
    assert set(triggers) == {"workflow_dispatch"}
    assert WORKFLOW.read_text(encoding="utf-8").count("cron:") == 1


def test_the_schedule_comment_asks_for_every_ten_minutes() -> None:
    assert '"*/10 * * * *"' in WORKFLOW.read_text(encoding="utf-8")


def test_the_checks_run_only_the_synthetic_project(workflow: dict[str, Any]) -> None:
    runs = [step["run"] for step in _steps(workflow) if "run" in step]
    assert any("playwright test --project synthetic" in run for run in runs)
    assert not any("pnpm e2e" in run for run in runs)


def test_the_target_and_the_secrets_come_from_settings_not_the_file(
    workflow: dict[str, Any],
) -> None:
    (job,) = workflow["jobs"].values()
    env = job["env"]
    assert env["SYNTHETIC_BASE_URL"] == "${{ vars.SYNTHETIC_BASE_URL }}"
    assert env["SYNTHETIC_ALLOWED_HOSTS"] == "${{ vars.SYNTHETIC_ALLOWED_HOSTS }}"
    assert env["SYNTHETIC_HOOK_TOKEN"] == "${{ secrets.SYNTHETIC_HOOK_TOKEN }}"
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "https://" not in text.replace("https://github.com", "")


def test_the_staff_session_is_written_to_a_private_temporary_file(
    workflow: dict[str, Any],
) -> None:
    step = next(s for s in _steps(workflow) if s.get("name") == "Write the staff session file")
    assert "umask 077" in step["run"]
    assert "$RUNNER_TEMP" in step["run"]
    assert step["env"]["STAFF_STATE"] == "${{ secrets.SYNTHETIC_STAFF_STORAGE_STATE }}"
