"""Checks on .github/workflows/ci.yml. They parse the YAML so that a typo fails locally."""

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.support.neo4j import NEO4J_IMAGE

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


def _backend_pytest_runs(jobs: dict[str, Any]) -> list[str]:
    runs = [r for r in _run_steps(jobs["backend"]) if "pytest" in r]
    assert runs, "backend job has no pytest step"
    return runs


def test_backend_job_runs_every_test_in_two_phases(jobs: dict[str, Any]) -> None:
    """Parallel workers for everything that can share the Neo4j, then the tests that cannot, alone
    (TEN-035). Nothing is dropped by a path: only markers select, and they are named."""
    runs = _backend_pytest_runs(jobs)
    parallel = [r for r in runs if '-m "not exclusive"' in r]
    alone = [r for r in runs if '-m "exclusive' in r]

    assert len(parallel) == 1 and len(alone) == 1, runs
    assert "-n " in parallel[0] and "--dist loadfile" in parallel[0]
    for directory in ("tests/unit", "tests/architecture", "tests/integration", "tests/contract"):
        assert directory in parallel[0], f"the parallel phase leaves out {directory}"
    assert "-n " not in alone[0]
    for run in runs:
        assert "--deselect" not in run
        assert "--ignore" not in run
        assert "not integration" not in run


def test_the_only_tests_ci_leaves_out_need_the_compose_stack_and_are_named_by_marker(
    jobs: dict[str, Any],
) -> None:
    """CI has no Service Bus emulator and no compose stack, so the exclusive phase leaves out the
    two markers that need them, and says so. Both markers are registered."""
    runs = _backend_pytest_runs(jobs)
    alone = next(r for r in runs if '-m "exclusive' in r)
    expression = re.search(r'-m "([^"]*)"', alone)
    assert expression is not None
    left_out = set(re.findall(r"not (\w+)", expression.group(1)))

    assert left_out == {"servicebus", "infra"}
    pyproject = tomllib.loads((REPO_ROOT / "backend" / "pyproject.toml").read_text("utf-8"))
    registered = {m.split(":", 1)[0] for m in pyproject["tool"]["pytest"]["ini_options"]["markers"]}
    assert left_out | {"exclusive"} <= registered


def test_an_empty_exclusive_phase_is_not_a_failure(jobs: dict[str, Any]) -> None:
    runs = _backend_pytest_runs(jobs)
    alone = next(r for r in runs if '-m "exclusive' in r)

    assert "-ne 5" in alone, "exit code 5 (no test selected) must not fail the job"


def test_backend_job_has_a_neo4j_and_a_redis_service_on_the_pinned_images(
    jobs: dict[str, Any],
) -> None:
    services = jobs["backend"]["services"]
    compose = yaml.safe_load((REPO_ROOT / "infra" / "docker-compose.yml").read_text("utf-8"))

    assert services["neo4j"]["image"] == NEO4J_IMAGE == compose["services"]["neo4j"]["image"]
    assert services["redis"]["image"] == compose["services"]["redis"]["image"]
    assert "6379:6379" in [str(p) for p in services["redis"]["ports"]]


def test_the_harness_attaches_to_the_service_not_to_the_compose_port(jobs: dict[str, Any]) -> None:
    job = jobs["backend"]
    env = job["env"]
    published = [str(p) for p in job["services"]["neo4j"]["ports"]]

    assert env["DIUCS_TEST_NEO4J_URI"] == "bolt://localhost:7690"
    assert "7690:7687" in published
    assert env["DIUCS_TEST_NEO4J_USER"] == "neo4j"
    # The attach refuses localhost:7687 (the compose stack of the owner) unless told otherwise.
    assert "7687" not in env["DIUCS_TEST_NEO4J_URI"]


def test_the_service_password_is_made_per_run_and_is_the_one_the_harness_uses(
    jobs: dict[str, Any],
) -> None:
    job = jobs["backend"]
    service_auth = job["services"]["neo4j"]["env"]["NEO4J_AUTH"]
    harness_password = job["env"]["DIUCS_TEST_NEO4J_PASSWORD"]

    assert service_auth == f"neo4j/{harness_password}"
    assert "github.run_id" in harness_password


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


def test_triggers_are_manual_only_by_the_owners_request(workflow: dict[str, Any]) -> None:
    # The owner disabled push and pull-request runs on 2026-10-28 (pushes were billing Actions).
    # The workflow still runs when started by hand. To turn it back on, change this test too.
    triggers = workflow.get(True, workflow.get("on"))
    assert triggers is not None
    assert set(triggers) == {"workflow_dispatch"}


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
