"""Checks on .github/workflows/ci.yml. They parse the YAML so that a typo fails locally."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
EXPECTED_JOBS = {"backend-static", "backend", "frontend", "e2e"}


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    assert WORKFLOW.is_file(), f"missing {WORKFLOW.relative_to(REPO_ROOT)}"
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    return doc


@pytest.fixture(scope="module")
def jobs(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow["jobs"]


def _run_steps(job: dict[str, Any]) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def _index_of(runs: list[str], needle: str) -> int:
    matches = [i for i, run in enumerate(runs) if needle in run]
    assert matches, f"no step runs {needle!r}; steps were {runs}"
    return matches[0]


def test_jobs_exist(jobs: dict[str, Any]) -> None:
    assert EXPECTED_JOBS.issubset(jobs)


def test_backend_static_runs_py314_and_py315_and_only_315_may_fail(jobs: dict[str, Any]) -> None:
    job = jobs["backend-static"]
    versions = job["strategy"]["matrix"]["python-version"]
    assert versions == ["3.14", "3.15"]
    assert all(isinstance(v, str) for v in versions)
    assert job["continue-on-error"] == "${{ matrix.python-version == '3.15' }}"


def test_backend_static_steps_run_in_order(jobs: dict[str, Any]) -> None:
    runs = _run_steps(jobs["backend-static"])
    order = [
        "ruff check",
        "ruff format --check",
        "mypy",
        "lint-imports",
        "pytest tests/unit",
    ]
    positions = [_index_of(runs, needle) for needle in order]
    assert positions == sorted(positions), f"wrong order: {positions}"
    assert positions[0] < positions[-1]
    assert len(set(positions)) == len(positions)


def test_backend_job_runs_full_suite_without_deselecting_integration(jobs: dict[str, Any]) -> None:
    runs = _run_steps(jobs["backend"])
    pytest_runs = [r for r in runs if "pytest" in r]
    assert pytest_runs, "backend job has no pytest step"
    for run in pytest_runs:
        assert "-m" not in run.split(), f"pytest step deselects tests: {run!r}"
        assert "not integration" not in run
        assert "--deselect" not in run
        assert "--ignore" not in run


def test_backend_job_does_not_use_compose_for_tests(jobs: dict[str, Any]) -> None:
    # DEC-008: the test harness starts its own Neo4j per pytest session. The compose file is for
    # local runs only, so CI must not start it, and nothing shares a fixed port with the harness.
    runs = _run_steps(jobs["backend"])
    assert not any("docker compose" in run for run in runs)


def test_backend_job_runs_on_python_314(jobs: dict[str, Any]) -> None:
    job = jobs["backend"]
    assert "3.14" in job.get("env", {}).get("UV_PYTHON", "")


def test_frontend_runs_lint_typecheck_test_build(jobs: dict[str, Any]) -> None:
    runs = _run_steps(jobs["frontend"])
    order = ["lint", "typecheck", "test", "build"]
    positions = [_index_of(runs, f"pnpm {name}") for name in order]
    assert positions == sorted(positions), f"wrong order: {positions}"


def test_e2e_needs_frontend_and_runs_e2e(jobs: dict[str, Any]) -> None:
    needs = jobs["e2e"]["needs"]
    needs_list = [needs] if isinstance(needs, str) else list(needs)
    assert "frontend" in needs_list
    assert any("pnpm e2e" in r for r in _run_steps(jobs["e2e"]))


def test_e2e_uploads_report_on_failure(jobs: dict[str, Any]) -> None:
    uploads = [
        s
        for s in jobs["e2e"]["steps"]
        if str(s.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert uploads, "e2e job does not upload a report"
    assert any(s.get("if") == "failure()" for s in uploads)


def test_top_level_permissions_are_read_only(workflow: dict[str, Any]) -> None:
    assert workflow["permissions"] == {"contents": "read"}


def test_triggers_are_push_and_pull_request(workflow: dict[str, Any]) -> None:
    # PyYAML reads the bare key `on` as the boolean True.
    triggers = workflow.get(True, workflow.get("on"))
    assert triggers is not None
    assert "push" in triggers
    assert "pull_request" in triggers


def test_concurrency_cancels_superseded_runs_per_ref(workflow: dict[str, Any]) -> None:
    concurrency = workflow["concurrency"]
    assert "github.ref" in concurrency["group"]
    assert concurrency["cancel-in-progress"] is True


def test_every_action_is_pinned_to_a_major_tag(jobs: dict[str, Any]) -> None:
    pinned = re.compile(r"^[\w.-]+/[\w.-]+@v\d+$")
    uses = [step["uses"] for job in jobs.values() for step in job["steps"] if "uses" in step]
    assert uses, "no actions used"
    bad = [u for u in uses if not pinned.match(u)]
    assert not bad, f"actions not pinned to a major tag: {bad}"
