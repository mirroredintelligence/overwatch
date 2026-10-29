"""Tests for delivery.py. Run: python -m pytest .claude/skills/diucs-delivery/scripts -q"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import delivery  # noqa: E402

PLAN = {
    "stages": [{"id": "S0", "name": "Foundations"}, {"id": "S1", "name": "Rules"}],
    "tasks": [
        {"id": "A01", "sprint": "S0", "epic": "F", "hours": 2, "deps": [], "title": "First", "files": []},
        {"id": "B01", "sprint": "S1", "epic": "D", "hours": 3, "deps": ["A01"], "title": "Second", "files": []},
        {"id": "C01", "sprint": "S1", "epic": "D", "hours": 3, "deps": ["A01"], "title": "Third", "files": []},
        {"id": "D01", "sprint": "S1", "epic": "D", "hours": 2, "deps": ["B01", "C01"], "title": "Fourth", "files": []},
    ],
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    plan = tmp_path / "tasks.json"
    plan.write_text(json.dumps(PLAN), encoding="utf-8")
    monkeypatch.setenv("DIUCS_DELIVERY_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("DIUCS_NOW", "2026-10-26T09:00:00+00:00")
    return {"plan": str(plan), "tmp": tmp_path}


def run(capsys, *argv, now=None, monkeypatch=None):
    if now and monkeypatch:
        monkeypatch.setenv("DIUCS_NOW", now)
    code = delivery.main(list(argv))
    out = capsys.readouterr()
    return code, out.out + out.err


def status_json(capsys):
    code, out = run(capsys, "status", "--json")
    assert code == 0
    return {t["id"]: t for t in json.loads(out)["tasks"]}


def init(capsys, env):
    code, _ = run(capsys, "init", "--plan", env["plan"])
    assert code == 0


def do_all_evidence(capsys, task, session="s1"):
    for kind in ("tests-red", "tests-green", "checks", "spec-trace"):
        code, out = run(capsys, "evidence", task, "--session", session, "--kind", kind, "--ref", f"{kind}-ref", "--summary", f"{kind} ok", "--skip-git-check")
        assert code == 0, out


def deliver_flow(capsys, task, claimer="s1", verifier="s2"):
    assert run(capsys, "claim", task, "--session", claimer)[0] == 0
    do_all_evidence(capsys, task, claimer)
    assert run(capsys, "review", task, "--session", claimer, "--skip-git-check")[0] == 0
    assert run(capsys, "verify", task, "--verifier", verifier, "--result", "pass", "--note", "reran")[0] == 0
    code, out = run(capsys, "deliver", task, "--session", claimer, "--commit", "abc1234", "--skip-git-check")
    assert code == 0, out


# ---- init and status ----

def test_init_seeds_tasks_as_not_started(capsys, env):
    init(capsys, env)
    st = status_json(capsys)
    assert set(st) == {"A01", "B01", "C01", "D01"}
    assert all(t["status"] == "not-started" for t in st.values())


def test_init_twice_does_not_duplicate_and_adds_new_tasks(capsys, env):
    init(capsys, env)
    PLAN2 = json.loads(json.dumps(PLAN))
    PLAN2["tasks"].append({"id": "E01", "sprint": "S1", "epic": "D", "hours": 1, "deps": ["D01"], "title": "Fifth", "files": []})
    Path(env["plan"]).write_text(json.dumps(PLAN2), encoding="utf-8")
    init(capsys, env)
    assert set(status_json(capsys)) == {"A01", "B01", "C01", "D01", "E01"}


def test_commands_before_init_explain_what_to_do(capsys, env):
    code, out = run(capsys, "status")
    assert code != 0 and "init" in out


# ---- next ----

def test_next_returns_only_tasks_whose_dependencies_are_delivered(capsys, env):
    init(capsys, env)
    code, out = run(capsys, "next")
    assert code == 0 and "A01" in out and "B01" not in out
    deliver_flow(capsys, "A01")
    code, out = run(capsys, "next")
    assert "B01" in out and "C01" in out and "D01" not in out


def test_next_skips_tasks_claimed_by_a_live_session(capsys, env):
    init(capsys, env)
    deliver_flow(capsys, "A01")
    assert run(capsys, "claim", "B01", "--session", "s3")[0] == 0
    code, out = run(capsys, "next")
    assert "C01" in out and "B01" not in out


# ---- claim ----

def test_claim_refused_when_dependencies_not_delivered(capsys, env):
    init(capsys, env)
    code, out = run(capsys, "claim", "B01", "--session", "s1")
    assert code == 2 and "A01" in out


def test_claim_refused_when_live_session_holds_it(capsys, env):
    init(capsys, env)
    assert run(capsys, "claim", "A01", "--session", "s1")[0] == 0
    code, out = run(capsys, "claim", "A01", "--session", "s2")
    assert code == 2 and "s1" in out


def test_same_session_can_reclaim_its_own_task(capsys, env):
    init(capsys, env)
    assert run(capsys, "claim", "A01", "--session", "s1")[0] == 0
    assert run(capsys, "claim", "A01", "--session", "s1")[0] == 0


def test_stale_claim_can_be_taken_over(capsys, env, monkeypatch):
    init(capsys, env)
    assert run(capsys, "claim", "A01", "--session", "s1")[0] == 0
    monkeypatch.setenv("DIUCS_NOW", "2026-10-26T12:30:00+00:00")  # 3.5 h later, no heartbeat
    assert status_json(capsys)["A01"]["status"] == "stale"
    code, out = run(capsys, "claim", "A01", "--session", "s2")
    assert code == 0 and "took over" in out.lower()
    assert status_json(capsys)["A01"]["owner"] == "s2"


def test_heartbeat_keeps_a_claim_live(capsys, env, monkeypatch):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    monkeypatch.setenv("DIUCS_NOW", "2026-10-26T10:30:00+00:00")
    assert run(capsys, "heartbeat", "A01", "--session", "s1", "--note", "tests green")[0] == 0
    monkeypatch.setenv("DIUCS_NOW", "2026-10-26T12:00:00+00:00")
    assert status_json(capsys)["A01"]["status"] == "in-progress"


def test_heartbeat_from_a_different_session_is_refused(capsys, env):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    code, _ = run(capsys, "heartbeat", "A01", "--session", "s2", "--note", "x")
    assert code == 2


# ---- evidence, review, verify, deliver ----

def test_review_requires_the_four_pre_review_evidence_kinds(capsys, env):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    run(capsys, "evidence", "A01", "--session", "s1", "--kind", "tests-red", "--ref", "r", "--summary", "red", "--skip-git-check")
    code, out = run(capsys, "review", "A01", "--session", "s1", "--skip-git-check")
    assert code == 2 and "tests-green" in out and "checks" in out and "spec-trace" in out


def test_evidence_kind_must_be_known(capsys, env):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    code, out = run(capsys, "evidence", "A01", "--session", "s1", "--kind", "vibes", "--ref", "r", "--summary", "s")
    assert code == 2 and "tests-red" in out


def test_only_the_owner_can_add_evidence(capsys, env):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    code, _ = run(capsys, "evidence", "A01", "--session", "s2", "--kind", "checks", "--ref", "r", "--summary", "s")
    assert code == 2


def test_verifier_must_not_be_the_builder(capsys, env):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    do_all_evidence(capsys, "A01")
    run(capsys, "review", "A01", "--session", "s1", "--skip-git-check")
    code, out = run(capsys, "verify", "A01", "--verifier", "s1", "--result", "pass", "--note", "me")
    assert code == 2 and "different" in out.lower()


def test_failed_verification_returns_task_to_in_progress_and_clears_review_evidence(capsys, env):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    do_all_evidence(capsys, "A01")
    run(capsys, "review", "A01", "--session", "s1", "--skip-git-check")
    assert run(capsys, "verify", "A01", "--verifier", "s2", "--result", "fail", "--note", "AC3 not met")[0] == 0
    t = status_json(capsys)["A01"]
    assert t["status"] == "in-progress" and "AC3 not met" in t["last_note"]
    code, out = run(capsys, "review", "A01", "--session", "s1", "--skip-git-check")
    assert code == 2  # evidence has to be redone after a failed verification


def test_deliver_requires_passing_verification(capsys, env):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    do_all_evidence(capsys, "A01")
    run(capsys, "review", "A01", "--session", "s1", "--skip-git-check")
    code, out = run(capsys, "deliver", "A01", "--session", "s1", "--commit", "abc1234", "--skip-git-check")
    assert code == 2 and "verification" in out


def test_deliver_requires_a_commit(capsys, env):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    do_all_evidence(capsys, "A01")
    run(capsys, "review", "A01", "--session", "s1", "--skip-git-check")
    run(capsys, "verify", "A01", "--verifier", "s2", "--result", "pass", "--note", "ok")
    code, _ = run(capsys, "deliver", "A01", "--session", "s1", "--skip-git-check")
    assert code != 0


def test_full_flow_delivers_and_unblocks_dependents(capsys, env):
    init(capsys, env)
    deliver_flow(capsys, "A01")
    st = status_json(capsys)
    assert st["A01"]["status"] == "delivered" and st["A01"]["commit"] == "abc1234"
    assert run(capsys, "claim", "B01", "--session", "s1")[0] == 0


def test_deliver_checks_the_commit_exists_in_git(capsys, env, monkeypatch):
    repo = env["tmp"] / "repo"
    repo.mkdir()
    (repo / "docs/delivery/evidence").mkdir(parents=True)
    (repo / "docs/delivery/evidence/A01.md").write_text(CHECKS_PASS, encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    for cmd in (["git", "init", "-q"], git + ["add", "-A"], git + ["commit", "-q", "-m", "x"]):
        subprocess.run(cmd, cwd=repo, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    monkeypatch.chdir(repo)
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    do_all_evidence(capsys, "A01")
    run(capsys, "review", "A01", "--session", "s1", "--skip-git-check")
    run(capsys, "verify", "A01", "--verifier", "s2", "--result", "pass", "--note", "ok")
    code, out = run(capsys, "deliver", "A01", "--session", "s1", "--commit", "deadbeef")
    assert code == 2 and "commit" in out.lower()
    assert run(capsys, "deliver", "A01", "--session", "s1", "--commit", sha)[0] == 0


# ---- block and release ----

def test_block_and_release(capsys, env):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    assert run(capsys, "block", "A01", "--session", "s1", "--reason", "Docker not available")[0] == 0
    t = status_json(capsys)["A01"]
    assert t["status"] == "blocked" and "Docker" in t["last_note"]
    assert run(capsys, "release", "A01", "--session", "s1", "--note", "handing back")[0] == 0
    assert status_json(capsys)["A01"]["status"] == "not-started"


def test_block_requires_a_reason(capsys, env):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    code, _ = run(capsys, "block", "A01", "--session", "s1")
    assert code != 0


# ---- lessons ----

def test_lesson_is_visible_to_other_sessions_as_unread(capsys, env):
    init(capsys, env)
    assert run(capsys, "lesson", "add", "--session", "s1", "--title", "Neo4j needs UTC", "--body", "Store datetimes as UTC datetime values.", "--tasks", "G05,P01")[0] == 0
    code, out = run(capsys, "lesson", "list", "--unread", "--session", "s2")
    assert "Neo4j needs UTC" in out and "G05" in out
    code, out = run(capsys, "lesson", "list", "--unread", "--session", "s1")
    assert "Neo4j needs UTC" not in out  # the author has read their own


def test_claim_is_refused_until_lessons_are_acknowledged(capsys, env):
    init(capsys, env)
    run(capsys, "lesson", "add", "--session", "s1", "--title", "T", "--body", "B")
    code, out = run(capsys, "claim", "A01", "--session", "s2")
    assert code == 3 and "lesson" in out.lower()
    assert run(capsys, "lesson", "ack", "--session", "s2")[0] == 0
    assert run(capsys, "claim", "A01", "--session", "s2")[0] == 0


def test_lesson_requires_title_and_body(capsys, env):
    init(capsys, env)
    code, _ = run(capsys, "lesson", "add", "--session", "s1", "--title", "only title")
    assert code != 0


def test_list_without_unread_shows_every_lesson_with_numbers(capsys, env):
    init(capsys, env)
    run(capsys, "lesson", "add", "--session", "s1", "--title", "One", "--body", "b1")
    run(capsys, "lesson", "add", "--session", "s2", "--title", "Two", "--body", "b2")
    code, out = run(capsys, "lesson", "list")
    assert "L1" in out and "L2" in out and "One" in out and "Two" in out


# ---- sessions and rendering ----

def test_sessions_lists_live_claim_holders_only(capsys, env, monkeypatch):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    monkeypatch.setenv("DIUCS_NOW", "2026-10-26T11:00:00+00:00")
    run(capsys, "claim", "A01", "--session", "s1")  # refresh
    run(capsys, "lesson", "add", "--session", "s9", "--title", "x", "--body", "y")  # known session, no task
    code, out = run(capsys, "sessions")
    assert code == 0 and "s1" in out
    monkeypatch.setenv("DIUCS_NOW", "2026-10-26T16:00:00+00:00")
    code, out = run(capsys, "sessions")
    assert "s1" not in out


def test_render_writes_status_and_lessons_files(capsys, env):
    init(capsys, env)
    deliver_flow(capsys, "A01")
    run(capsys, "lesson", "add", "--session", "s1", "--title", "Keep tests serial", "--body", "One Community database.")
    out_dir = env["tmp"] / "docs-delivery"
    assert run(capsys, "render", "--out", str(out_dir))[0] == 0
    status = (out_dir / "STATUS.md").read_text(encoding="utf-8")
    lessons = (out_dir / "LESSONS.md").read_text(encoding="utf-8")
    assert "A01" in status and "delivered" in status and "abc1234" in status
    assert "Keep tests serial" in lessons and "One Community database." in lessons


def test_status_summary_counts_and_hours(capsys, env):
    init(capsys, env)
    deliver_flow(capsys, "A01")
    code, out = run(capsys, "status")
    assert "1/4" in out or "1 of 4" in out
    assert "S0" in out and "S1" in out


def test_concurrent_appends_do_not_lose_events(capsys, env):
    init(capsys, env)
    state = Path(env["tmp"] / "state" / "events.jsonl")
    before = len(state.read_text(encoding="utf-8").splitlines())
    import threading

    def add(i):
        delivery.main(["lesson", "add", "--session", f"s{i}", "--title", f"T{i}", "--body", "b"])

    threads = [threading.Thread(target=add, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    capsys.readouterr()
    after = state.read_text(encoding="utf-8").splitlines()
    assert len(after) == before + 8
    assert all(json.loads(line) for line in after)


def test_show_lists_evidence_and_prompt_path(capsys, env):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    do_all_evidence(capsys, "A01")
    code, out = run(capsys, "show", "A01")
    assert code == 0 and "docs/plan/prompts/A01.md" in out and "tests-red" in out and "tests-green" in out


def test_heartbeat_warns_about_unread_lessons(capsys, env):
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    run(capsys, "lesson", "add", "--session", "s2", "--title", "Heads up", "--body", "b")
    code, out = run(capsys, "heartbeat", "A01", "--session", "s1", "--note", "working")
    assert code == 0 and "1 unread lesson" in out


def test_render_also_writes_a_ledger_backup_and_init_can_restore_it(capsys, env, monkeypatch):
    init(capsys, env)
    deliver_flow(capsys, "A01")
    out_dir = env["tmp"] / "docs-delivery"
    run(capsys, "render", "--out", str(out_dir))
    backup = out_dir / "ledger.jsonl"
    assert backup.exists() and len(backup.read_text(encoding="utf-8").splitlines()) > 5
    monkeypatch.setenv("DIUCS_DELIVERY_DIR", str(env["tmp"] / "fresh-state"))
    code, out = run(capsys, "init", "--restore", str(backup))
    assert code == 0
    assert status_json(capsys)["A01"]["status"] == "delivered"


def test_restore_refuses_to_overwrite_an_existing_ledger(capsys, env):
    init(capsys, env)
    backup = env["tmp"] / "b.jsonl"
    backup.write_text("{}\n", encoding="utf-8")
    code, out = run(capsys, "init", "--restore", str(backup))
    assert code == 2 and "already" in out.lower()


# ---- commit checks on evidence ----

def make_repo(tmp):
    repo = tmp / "repo2"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    shas = []
    for i in range(2):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", f"c{i}"], cwd=repo, check=True)
        shas.append(subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip())
    return repo, shas


def test_red_and_green_evidence_must_name_a_real_commit(capsys, env, monkeypatch):
    repo, (first, _second) = make_repo(env["tmp"])
    monkeypatch.chdir(repo)
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    code, out = run(capsys, "evidence", "A01", "--session", "s1", "--kind", "tests-red", "--ref", "deadbeef failing", "--summary", "red")
    assert code == 2 and "commit" in out.lower()
    code, out = run(capsys, "evidence", "A01", "--session", "s1", "--kind", "tests-red", "--ref", f"{first} failing output in evidence file", "--summary", "red")
    assert code == 0, out


def test_other_evidence_kinds_do_not_need_a_commit(capsys, env, monkeypatch):
    repo, _ = make_repo(env["tmp"])
    monkeypatch.chdir(repo)
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    code, out = run(capsys, "evidence", "A01", "--session", "s1", "--kind", "checks", "--ref", "evidence file section 3", "--summary", "ok")
    assert code == 0, out


def test_review_requires_the_red_commit_to_come_before_the_green_one(capsys, env, monkeypatch):
    repo, (first, second) = make_repo(env["tmp"])
    monkeypatch.chdir(repo)
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    for kind, ref in (("tests-red", second), ("tests-green", first), ("checks", "x"), ("spec-trace", "y")):
        assert run(capsys, "evidence", "A01", "--session", "s1", "--kind", kind, "--ref", ref, "--summary", "s")[0] == 0
    code, out = run(capsys, "review", "A01", "--session", "s1")
    assert code == 2 and "before" in out.lower()
    # record them the right way round and review succeeds
    run(capsys, "evidence", "A01", "--session", "s1", "--kind", "tests-red", "--ref", first, "--summary", "s")
    run(capsys, "evidence", "A01", "--session", "s1", "--kind", "tests-green", "--ref", second, "--summary", "s")
    assert run(capsys, "review", "A01", "--session", "s1")[0] == 0


def test_deliver_after_delivery_says_already_delivered(capsys, env):
    init(capsys, env)
    deliver_flow(capsys, "A01")
    code, out = run(capsys, "deliver", "A01", "--session", "s1", "--commit", "abc1234", "--skip-git-check")
    assert code == 2 and "already delivered" in out.lower()


CHECKS_PASS = """# A01 evidence

## Checks (generated)

| Check | Command | Exit | Summary |
|---|---|---|---|
| unit | `pytest tests/unit` | 0 | 12 passed |
| lint | `ruff check .` | 0 | All checks passed |
"""

CHECKS_FAIL = CHECKS_PASS.replace("| 12 passed", "| 1 failed").replace("| unit | `pytest tests/unit` | 0", "| unit | `pytest tests/unit` | 1")


def test_failing_checks_reads_only_the_generated_checks_table():
    assert delivery.failing_checks(CHECKS_PASS) == []
    assert delivery.failing_checks(CHECKS_FAIL) == ["unit"]
    assert delivery.failing_checks("# A01\n\n| x | `y` | 1 | red table elsewhere |\n") is None
    assert delivery.failing_checks("## Checks (generated)\n\nno rows here\n") is None


def test_deliver_refused_when_the_checks_table_shows_a_failure(capsys, env, monkeypatch):
    sha = commit_evidence(env, monkeypatch, CHECKS_FAIL)
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    do_all_evidence(capsys, "A01")
    run(capsys, "review", "A01", "--session", "s1", "--skip-git-check")
    run(capsys, "verify", "A01", "--verifier", "s2", "--result", "pass", "--note", "ok")
    code, out = run(capsys, "deliver", "A01", "--session", "s1", "--commit", sha)
    assert code == 2 and "checks failing" in out and "unit" in out


def test_deliver_accepted_when_the_checks_table_passes(capsys, env, monkeypatch):
    sha = commit_evidence(env, monkeypatch, CHECKS_PASS)
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    do_all_evidence(capsys, "A01")
    run(capsys, "review", "A01", "--session", "s1", "--skip-git-check")
    run(capsys, "verify", "A01", "--verifier", "s2", "--result", "pass", "--note", "ok")
    code, _ = run(capsys, "deliver", "A01", "--session", "s1", "--commit", sha)
    assert code == 0


def commit_evidence(env, monkeypatch, text, message="evidence"):
    repo = env["tmp"] / "gate-repo"
    (repo / "docs/delivery/evidence").mkdir(parents=True, exist_ok=True)
    (repo / "docs/delivery/evidence/A01.md").write_text(text, encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(git + ["add", "-A"], cwd=repo, check=True)
    subprocess.run(git + ["commit", "-q", "-m", message], cwd=repo, check=True)
    monkeypatch.chdir(repo)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


ATTRIBUTION = [
    "Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>",
    "co-authored-by: someone",
    "Built with claude-sonnet-5-5",
    "Model: claude-opus-5-5",
    "Written by Sonnet 5.5",
    "Haiku 5.5 did the mapping",
    "Fable 5.1 review",
]


@pytest.mark.parametrize("line", ATTRIBUTION)
def test_attribution_problems_flags_trailers_and_model_names(line):
    assert delivery.attribution_problems(f"TEN-1: subject\n\nbody\n\n{line}\n")


def test_attribution_problems_allows_a_plain_message_and_the_product_name():
    assert delivery.attribution_problems("TEN-1: subject\n\nClaude Code reads the ledger.\n") == []


def test_check_messages_reports_unpushed_commits_with_attribution(capsys, tmp_path, monkeypatch):
    repo = tmp_path / "msg-repo"
    repo.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=repo, check=True)
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "clean\n\nplain body"], cwd=repo, check=True)
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "bad\n\nCo-Authored-By: Claude Haiku 5.5"], cwd=repo, check=True)
    monkeypatch.chdir(repo)
    problems = delivery.unpushed_attribution_problems()
    assert len(problems) == 1 and "Co-Authored-By" in problems[0][1][0]
    code = delivery.main(["check-messages"])
    assert code == 2 and "Co-Authored-By" in capsys.readouterr().out


def test_deliver_refused_when_an_unpushed_commit_carries_attribution(capsys, env, monkeypatch):
    base = commit_evidence(env, monkeypatch, CHECKS_PASS, message="base")
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", base], check=True)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "A01\n\nCo-Authored-By: Claude Haiku 5.5"], check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    init(capsys, env)
    run(capsys, "claim", "A01", "--session", "s1")
    do_all_evidence(capsys, "A01")
    run(capsys, "review", "A01", "--session", "s1", "--skip-git-check")
    run(capsys, "verify", "A01", "--verifier", "s2", "--result", "pass", "--note", "ok")
    code, out = run(capsys, "deliver", "A01", "--session", "s1", "--commit", sha)
    assert code == 2 and "attribution" in out.lower()
