"""The configuration that makes the integration tests run in parallel on one shared Neo4j, and the
words of the briefs that tell agents how to run them (TEN-035, DEC-130 item 9).

The old rule, "Neo4j tests run one at a time: flock /tmp/diucs-neo4j-tests.lock", was true while
every run wiped the whole database. It is not true now, and a brief that still says it makes
agents queue for nothing, so the rule is removed from every live instruction and replaced by the
real one.
"""

import re
import tomllib
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
SKILL = REPO / ".claude" / "skills" / "diucs-delivery"
LOCK_NAME = "diucs-neo4j-tests.lock"

# Files an agent reads as instructions. The ledger, the evidence files and decisions.md are
# history and are not edited; plan prompts of tasks that are already delivered are history too.
INSTRUCTIONS = [
    REPO / "CLAUDE.md",
    SKILL / "SKILL.md",
    SKILL / "assets" / "builder-brief.md",
    SKILL / "assets" / "verifier-brief.md",
    SKILL / "references" / "collective.md",
    SKILL / "references" / "delivery-standard.md",
    SKILL / "references" / "multi-tenancy.md",
    SKILL / "scripts" / "record_checks.py",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pyproject() -> dict[str, object]:
    return tomllib.loads(_read(BACKEND / "pyproject.toml"))


@pytest.fixture(scope="module")
def makefile() -> str:
    return _read(BACKEND / "Makefile")


def _recipe(makefile: str, target: str) -> str:
    """The recipe of a target, with the make variables it uses written out."""
    match = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n?)+)", makefile, re.M)
    assert match, f"Makefile has no target {target}"
    recipe = match.group(1)
    for name, value in re.findall(r"^(\w+)\s*\??=\s*(.+)$", makefile, re.M):
        recipe = recipe.replace(f"$({name})", value.strip())
    return recipe


# dependency and pytest options


def test_xdist_is_a_dev_dependency(pyproject: dict[str, object]) -> None:
    dev = pyproject["dependency-groups"]["dev"]  # type: ignore[index]

    assert any(str(entry).startswith("pytest-xdist") for entry in dev)


def test_xdist_is_in_the_lock_file() -> None:
    assert 'name = "pytest-xdist"' in _read(BACKEND / "uv.lock")


def test_a_files_tests_stay_on_one_worker(pyproject: dict[str, object]) -> None:
    """Several modules depend on the order of their own tests (module fixtures, probes)."""
    options = pyproject["tool"]["pytest"]["ini_options"]  # type: ignore[index]

    assert "--dist loadfile" in " ".join(options["addopts"].split())


def test_the_new_markers_for_the_split_are_registered(pyproject: dict[str, object]) -> None:
    markers = {m.split(":", 1)[0] for m in pyproject["tool"]["pytest"]["ini_options"]["markers"]}  # type: ignore[index]

    assert {"servicebus", "redis", "infra", "exclusive", "schema", "lifecycle"} <= markers


# the Makefile


def test_the_parallel_phase_leaves_out_the_exclusive_tests_and_the_serial_phase_runs_them(
    makefile: str,
) -> None:
    recipe = _recipe(makefile, "test-integration")
    lines = [line.strip() for line in recipe.splitlines() if "pytest" in line]

    assert len(lines) == 2
    parallel, serial = lines
    assert "-n " in parallel and '-m "not exclusive"' in parallel
    assert "-n " not in serial and "-m exclusive" in serial
    assert "--dist loadfile" in parallel or "--dist=loadfile" in parallel


def test_the_serial_phase_runs_even_when_the_parallel_one_fails(makefile: str) -> None:
    """A failure in the first phase must not hide the second: both results are reported."""
    recipe = _recipe(makefile, "test-integration")

    assert "status=$$?" in recipe or "||" in recipe or "; exit" in recipe


def test_test_parallel_covers_unit_architecture_integration_and_contract(makefile: str) -> None:
    recipe = _recipe(makefile, "test-parallel")

    for directory in ("tests/unit", "tests/architecture", "tests/integration", "tests/contract"):
        assert directory in recipe


def test_the_shared_neo4j_can_be_started_and_removed_by_make(makefile: str) -> None:
    assert "tests.support.harness_mode" in _recipe(makefile, "neo4j-shared-up")
    assert "tests.support.harness_mode" in _recipe(makefile, "neo4j-shared-down")


def test_the_new_targets_are_phony(makefile: str) -> None:
    phony = re.search(r"^\.PHONY:([^\n]*)", makefile, re.M)
    assert phony
    for target in ("test-integration", "test-parallel", "neo4j-shared-up", "neo4j-shared-down"):
        assert target in phony.group(1).split()


# the briefs


@pytest.mark.parametrize("path", INSTRUCTIONS, ids=lambda p: str(p.relative_to(REPO)))
def test_no_live_instruction_still_tells_an_agent_to_queue_on_the_manual_lock(path: Path) -> None:
    assert LOCK_NAME not in _read(path), f"{path.relative_to(REPO)} still names {LOCK_NAME}"


def test_no_task_prompt_tells_a_builder_to_queue_on_the_manual_lock() -> None:
    """A builder reads its prompt first, and a prompt that says "run Neo4j tests one at a time under
    flock" would be followed. (The ledger, the evidence files and decisions.md record what was
    true when a task was built and are not edited.)"""
    named = [
        prompt.name
        for prompt in sorted((REPO / "docs" / "plan" / "prompts").glob("*.md"))
        if LOCK_NAME in _read(prompt)
    ]

    assert named == [], f"prompts that still name the manual lock: {named}"


@pytest.mark.parametrize(
    "path",
    [
        REPO / "CLAUDE.md",
        SKILL / "assets" / "builder-brief.md",
        SKILL / "assets" / "verifier-brief.md",
        SKILL / "references" / "collective.md",
    ],
    ids=lambda p: p.name,
)
def test_the_briefs_say_how_to_run_the_neo4j_tests_now(path: Path) -> None:
    text = _read(path)

    assert "make test-integration" in text
    assert "exclusive" in text
    assert "parallel" in text.lower()


def test_the_rule_says_what_is_serial_and_why() -> None:
    text = _read(REPO / "CLAUDE.md")

    for word in ("exclusive", "schema", "lifecycle", "Service Bus"):
        assert word in text, f"CLAUDE.md does not say what {word} means for a run"


def test_the_harness_docstring_no_longer_tells_agents_to_wrap_pytest_in_a_lock() -> None:
    text = _read(BACKEND / "tests" / "support" / "neo4j.py")

    assert LOCK_NAME not in text.split('"""', 2)[1]


# the front end's end-to-end port


FRONTEND = REPO / "frontend"


def test_the_e2e_site_port_is_not_fixed_at_3000_so_two_runs_do_not_share_a_dev_server() -> None:
    config = _read(FRONTEND / "playwright.config.ts")
    env = _read(FRONTEND / "e2e" / "support" / "env.ts")

    assert "3000" not in config
    assert "SITE_PORT" in config
    assert "DIUCS_E2E_PORT" in env
    assert "process.pid" in env, "the derived port must differ between two runs"


def test_a_dev_server_is_reused_only_on_a_port_the_person_chose() -> None:
    config = _read(FRONTEND / "playwright.config.ts")

    assert "reuseExistingServer: !process.env.CI" not in config
    assert "PORT_CHOSEN" in config


def test_the_three_e2e_ports_follow_from_one_base() -> None:
    env = _read(FRONTEND / "e2e" / "support" / "env.ts")

    assert "BACKEND_PORT = SITE_PORT + 1" in env
    assert "ENTRA_PORT = SITE_PORT + 2" in env
    assert "4010" not in env and "4011" not in env


def test_no_e2e_spec_names_the_site_by_a_fixed_address() -> None:
    offenders = [
        path.name
        for path in sorted((FRONTEND / "e2e").rglob("*.ts"))
        if "synthetic" not in path.parts and "localhost:3000" in _read(path)
    ]

    assert offenders == []
