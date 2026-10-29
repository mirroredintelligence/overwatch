#!/usr/bin/env python3
"""Shared delivery ledger for the DIUCS capacity build.

Every session (chat, subagent, worktree) that works on the plan uses this one tool, so they all see the
same claims, evidence and lessons. State is an append-only event log, so concurrent sessions cannot
overwrite each other and the whole history can be audited. Standard library only.

Usage: python delivery.py <command> [options]      (python delivery.py --help for the list)
Exit codes: 0 done, 2 refused (the message says why), 3 unread lessons must be read first.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

STALE_AFTER = timedelta(minutes=120)  # no heartbeat for this long and a claim can be taken over
SEEN_WINDOW = timedelta(hours=4)  # a session counts as active if it did anything this recently
PRE_REVIEW_EVIDENCE = ("tests-red", "tests-green", "checks", "spec-trace")
COMMIT_EVIDENCE = ("tests-red", "tests-green")  # these must start with the sha of a real commit
OPTIONAL_EVIDENCE = ("privacy-scan", "hazard-note", "mutation", "coverage", "perf", "other")
EVIDENCE_KINDS = PRE_REVIEW_EVIDENCE + OPTIONAL_EVIDENCE
HELD = ("in-progress", "in-review", "blocked")


class Refused(Exception):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- storage

def now_utc() -> datetime:
    raw = os.environ.get("DIUCS_NOW")
    return datetime.fromisoformat(raw) if raw else datetime.now(timezone.utc)


def state_dir() -> Path:
    env = os.environ.get("DIUCS_DELIVERY_DIR")
    if env:
        return Path(env)
    try:
        out = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True, check=True).stdout.strip()
        return (Path.cwd() / out).resolve() / "diucs-delivery"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd() / ".diucs-delivery"


def repo_root() -> Path:
    try:
        return Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


@contextmanager
def locked(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".lock"
    deadline = time.time() + 15
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 30:  # a crashed holder
                    lock.rmdir()
                    continue
            except FileNotFoundError:
                continue
            if time.time() > deadline:
                raise Refused("The ledger is locked by another session. Try again in a few seconds.")
            time.sleep(0.02)
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except FileNotFoundError:
            pass


def read_events(directory: Path) -> list[dict]:
    path = directory / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append(directory: Path, event: dict, now: datetime) -> None:
    event = {"at": now.isoformat(), **event}
    with open(directory / "events.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


# ---------------------------------------------------------------- derived state

def derive(events: list[dict], now: datetime) -> dict:
    seeds = [e for e in events if e["t"] == "seed"]
    if not seeds:
        raise Refused("No ledger yet. Run: python delivery.py init  (from the repo root)")
    defs = {t["id"]: t for t in seeds[-1]["tasks"]}
    stages = seeds[-1].get("stages", [])
    tasks = {
        tid: {
            "id": tid, "title": d["title"], "stage": d["sprint"], "epic": d.get("epic", ""), "hours": d.get("hours", 0),
            "deps": d.get("deps", []), "files": d.get("files", []),
            "status": "not-started", "owner": None, "branch": None, "last_beat": None, "last_note": "",
            "evidence": [], "verification": None, "commit": None,
        }
        for tid, d in defs.items()
    }
    lessons, read, seen = [], {}, {}

    def touch(session, at):
        if session:
            seen[session] = at

    for e in events:
        t, at = e["t"], datetime.fromisoformat(e["at"])
        task = tasks.get(e.get("task"))
        touch(e.get("session") or e.get("verifier"), at)
        if t == "claim" and task:
            if task["owner"] != e["session"]:
                task["evidence"], task["verification"] = [], None
            task.update(status="in-progress", owner=e["session"], branch=e.get("branch") or task["branch"], last_beat=at)
            if e.get("note"):
                task["last_note"] = e["note"]
        elif t == "heartbeat" and task:
            task.update(last_beat=at, last_note=e.get("note", task["last_note"]))
        elif t == "evidence" and task:
            task["evidence"].append({k: e[k] for k in ("kind", "ref", "summary", "session", "at")})
            task["last_beat"] = at
        elif t == "review" and task:
            task.update(status="in-review", last_beat=at)
        elif t == "verify" and task:
            task["last_beat"] = at
            if e["result"] == "pass":
                task["verification"] = {"verifier": e["verifier"], "note": e.get("note", ""), "at": e["at"]}
                task["last_note"] = f"verified by {e['verifier']}: {e.get('note', '')}"
            else:
                task.update(status="in-progress", evidence=[], verification=None,
                            last_note=f"verification failed ({e['verifier']}): {e.get('note', '')}")
        elif t == "deliver" and task:
            task.update(status="delivered", commit=e["commit"], last_beat=at)
        elif t == "block" and task:
            task.update(status="blocked", last_note=e["reason"], last_beat=at)
        elif t == "release" and task:
            task.update(status="not-started", owner=None, evidence=[], verification=None, last_beat=None,
                        last_note=e.get("note", ""))
        elif t == "lesson":
            lessons.append({"id": f"L{len(lessons) + 1}", **{k: e.get(k) for k in ("session", "title", "body", "tasks", "area", "at")}})
            read.setdefault(e["session"], set()).add(lessons[-1]["id"])
        elif t == "ack":
            read.setdefault(e["session"], set()).update(l["id"] for l in lessons if l["at"] <= e["at"])
    for task in tasks.values():
        if task["status"] in HELD and task["last_beat"] and now - task["last_beat"] > STALE_AFTER:
            task["was"], task["status"] = task["status"], "stale"
    return {"tasks": tasks, "stages": stages, "lessons": lessons, "read": read, "seen": seen}


def unread_for(state: dict, session: str) -> list[dict]:
    return [l for l in state["lessons"] if l["id"] not in state["read"].get(session, set())]


def undelivered_deps(state: dict, task: dict) -> list[str]:
    return [d for d in task["deps"] if state["tasks"][d]["status"] != "delivered"]


def need_task(state: dict, tid: str) -> dict:
    if tid not in state["tasks"]:
        raise Refused(f"Unknown task {tid}.")
    return state["tasks"][tid]


def need_owner(task: dict, session: str) -> None:
    if task["status"] == "delivered":
        raise Refused(f"{task['id']} is already delivered (commit {task['commit']}).")
    if task["owner"] != session or task["status"] not in HELD:
        raise Refused(f"{task['id']} is not held by {session} (status {task['status']}, owner {task['owner']}). Claim it first.")


# ---------------------------------------------------------------- commands

def cmd_init(a, d: Path, now: datetime) -> int:
    if a.restore:
        with locked(d):
            if read_events(d):
                raise Refused("A ledger already exists here. Restore only works into an empty one.")
            lines = Path(a.restore).read_text(encoding="utf-8").splitlines()
            (d / "events.jsonl").write_text("\n".join(l for l in lines if l.strip()) + "\n", encoding="utf-8", newline="\n")
        print(f"Restored {len([l for l in lines if l.strip()])} events from {a.restore}.")
        return 0
    plan_path = Path(a.plan) if a.plan else repo_root() / "docs" / "plan" / "tasks.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    with locked(d):
        events = read_events(d)
        seeds = [e for e in events if e["t"] == "seed"]
        if seeds and seeds[-1]["tasks"] == plan["tasks"]:
            print(f"Ledger already up to date ({len(plan['tasks'])} tasks).")
            return 0
        append(d, {"t": "seed", "tasks": plan["tasks"], "stages": plan.get("stages", [])}, now)
    print(f"Ledger seeded with {len(plan['tasks'])} tasks at {d}.")
    return 0


def ledger(d: Path, now: datetime) -> dict:
    return derive(read_events(d), now)


def cmd_status(a, d: Path, now: datetime) -> int:
    s = ledger(d, now)
    tasks = list(s["tasks"].values())
    delivered = [t for t in tasks if t["status"] == "delivered"]
    if a.json:
        print(json.dumps({"summary": {"delivered": len(delivered), "total": len(tasks)},
                          "tasks": [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in t.items()} for t in tasks]}, indent=1))
        return 0
    print(f"Delivered: {len(delivered)}/{len(tasks)} tasks, {sum(t['hours'] for t in delivered)}/{sum(t['hours'] for t in tasks)} hours")
    names = {st["id"]: st["name"] for st in s["stages"]}
    for sid in dict.fromkeys(t["stage"] for t in tasks):
        group = [t for t in tasks if t["stage"] == sid]
        counts = {}
        for t in group:
            counts[t["status"]] = counts.get(t["status"], 0) + 1
        detail = ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        print(f"  {sid} {names.get(sid, '')}: {detail}")
    active = [t for t in tasks if t["status"] in HELD + ("stale",)]
    for t in active:
        print(f"  * {t['id']} {t['status']} ({t['owner']}) {t['title']}" + (f" - {t['last_note']}" if t["last_note"] else ""))
    return 0


def cmd_next(a, d: Path, now: datetime) -> int:
    s = ledger(d, now)
    shown = 0
    for t in s["tasks"].values():
        if t["status"] in ("not-started", "stale") and not undelivered_deps(s, t):
            tag = f"  (stale, last held by {t['owner']}: can be taken over)" if t["status"] == "stale" else ""
            print(f"{t['id']} [{t['stage']}] {t['title']} ({t['hours']}h){tag}")
            shown += 1
            if shown >= a.n:
                break
    if not shown:
        print("Nothing is ready. Check `status` for blocked or in-review tasks, and `lesson list --unread`.")
    return 0


def cmd_claim(a, d: Path, now: datetime) -> int:
    with locked(d):
        s = ledger(d, now)
        task = need_task(s, a.task)
        unread = unread_for(s, a.session)
        if unread:
            ids = ", ".join(l["id"] for l in unread)
            raise Refused(f"Read the lessons first ({ids}): python delivery.py lesson list --unread --session {a.session}, then lesson ack --session {a.session}.", 3)
        if task["status"] == "delivered":
            raise Refused(f"{a.task} is already delivered.")
        missing = undelivered_deps(s, task)
        if missing:
            raise Refused(f"{a.task} depends on tasks that are not delivered yet: {', '.join(missing)}.")
        took_over = ""
        if task["status"] in HELD and task["owner"] != a.session:
            raise Refused(f"{a.task} is held by {task['owner']} ({task['status']}). Pick another task with `next`.")
        if task["status"] == "stale" and task["owner"] != a.session:
            took_over = f" Took over from {task['owner']} (no heartbeat since {task['last_beat'].isoformat()}); their evidence was cleared."
        append(d, {"t": "claim", "task": a.task, "session": a.session, "branch": a.branch}, now)
    print(f"{a.session} claimed {a.task}.{took_over} Prompt: docs/plan/prompts/{a.task}.md")
    return 0


def cmd_heartbeat(a, d, now):
    with locked(d):
        s = ledger(d, now)
        task = need_task(s, a.task)
        need_owner(task, a.session)
        append(d, {"t": "heartbeat", "task": a.task, "session": a.session, "note": a.note}, now)
    print("Heartbeat recorded.")
    unread = unread_for(s, a.session)
    if unread:
        n = len(unread)
        print(f"You have {n} unread lesson{'s' if n != 1 else ''} ({', '.join(l['id'] for l in unread)}). Read them now: python delivery.py lesson list --unread --session {a.session}")
    return 0


def first_token(ref: str) -> str:
    return (ref.split() or [""])[0]


def cmd_evidence(a, d, now):
    if a.kind not in EVIDENCE_KINDS:
        raise Refused(f"Unknown evidence kind '{a.kind}'. Use one of: {', '.join(EVIDENCE_KINDS)}.")
    if a.kind in COMMIT_EVIDENCE and not a.skip_git_check and not commit_exists(first_token(a.ref)):
        raise Refused(f"{a.kind} evidence must start with the sha of a commit that exists in this repository (got '{first_token(a.ref)}'). "
                      "Put the sha first, then any description, for example: --ref \"1a2b3c4 failing run in evidence file\".")
    with locked(d):
        task = need_task(ledger(d, now), a.task)
        need_owner(task, a.session)
        append(d, {"t": "evidence", "task": a.task, "session": a.session, "kind": a.kind, "ref": a.ref, "summary": a.summary}, now)
    print(f"Recorded {a.kind} evidence for {a.task}.")
    return 0


def missing_evidence(task: dict) -> list[str]:
    have = {e["kind"] for e in task["evidence"]}
    return [k for k in PRE_REVIEW_EVIDENCE if k not in have]


def cmd_review(a, d, now):
    with locked(d):
        task = need_task(ledger(d, now), a.task)
        need_owner(task, a.session)
        missing = missing_evidence(task)
        if missing:
            raise Refused(f"Not ready for review. Missing evidence: {', '.join(missing)}.")
        if not a.skip_git_check:
            red = first_token([e for e in task["evidence"] if e["kind"] == "tests-red"][-1]["ref"])
            green = first_token([e for e in task["evidence"] if e["kind"] == "tests-green"][-1]["ref"])
            if red == green or not is_ancestor(red, green):
                raise Refused("The red (failing tests) commit must come before the green (implementation) commit: "
                              f"{red} is not an earlier commit than {green}. Test-first means the tests were committed and seen failing before the code existed.")
        append(d, {"t": "review", "task": a.task, "session": a.session}, now)
    print(f"{a.task} is in review. Another session must now run: python delivery.py verify {a.task} --verifier <their-session> --result pass|fail --note ...")
    return 0


def cmd_verify(a, d, now):
    with locked(d):
        task = need_task(ledger(d, now), a.task)
        if task["status"] != "in-review":
            raise Refused(f"{a.task} is {task['status']}, not in-review.")
        if a.verifier == task["owner"]:
            raise Refused(f"The verifier must be a different session from the builder ({task['owner']}).")
        append(d, {"t": "verify", "task": a.task, "verifier": a.verifier, "result": a.result, "note": a.note}, now)
    print(f"Verification {a.result} recorded for {a.task}." + ("" if a.result == "pass" else " The builder must fix it and redo the evidence."))
    return 0


def commit_exists(sha: str) -> bool:
    if not sha:
        return False
    try:
        return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def is_ancestor(older: str, newer: str) -> bool:
    try:
        return subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def failing_checks(markdown: str):
    """The labels of failing rows in the generated checks table, [] if all pass, None if there is no table.

    record_checks.py writes `| label | `command` | exit | summary |` rows under a heading that starts with
    "Checks (generated". Rows elsewhere in the file are ignored, so a red or green table cannot satisfy the gate."""
    rows, failing, inside = 0, [], False
    for line in markdown.splitlines():
        if line.startswith("#"):
            inside = "Checks (generated" in line
            continue
        if not (inside and line.startswith("|")):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[2].isdigit():
            rows += 1
            if int(cells[2]) != 0:
                failing.append(cells[0])
    return None if rows == 0 else failing


def checks_gate(a):
    """Refuse delivery unless the evidence file at the commit holds a generated checks table with no failures."""
    path = f"docs/delivery/evidence/{a.task}.md"
    shown = subprocess.run(["git", "show", f"{a.commit}:{path}"], capture_output=True, text=True)
    if shown.returncode != 0:
        raise Refused(f"{path} is not in commit {a.commit}; the checks table is the evidence of the checks.")
    failing = failing_checks(shown.stdout)
    if failing is None:
        raise Refused(f"{path} has no generated checks table (record_checks.py) at {a.commit}.")
    if failing:
        raise Refused(f"checks failing at {a.commit}: {', '.join(failing)}. Fix them and re-record before delivery.")


ATTRIBUTION = re.compile(
    r"co-authored-by\s*:|\bclaude[- ](sonnet|haiku|opus|fable)\b|\bclaude-(sonnet|haiku|opus|fable)-"
    r"|\b(sonnet|haiku|opus|fable)\s*5(\.\d)?\b",
    re.IGNORECASE,
)


def attribution_problems(message: str):
    """The lines of a commit message that carry a co-author trailer or a model identifier (CLAUDE system rule:
    no model name and no Co-Authored-By trailer in commits). Product names such as Claude Code are allowed."""
    return [line for line in message.splitlines() if ATTRIBUTION.search(line)]


def unpushed_attribution_problems(base: str = "origin/main"):
    """(sha, lines) for each commit between base and HEAD whose message carries attribution. Empty when base
    does not exist, because there is then no unpushed range to check."""
    out = subprocess.run(["git", "log", "--format=%H%x1f%B%x1e", f"{base}..HEAD"], capture_output=True, text=True)
    if out.returncode != 0:
        return []
    found = []
    for record in out.stdout.split("\x1e"):
        if "\x1f" not in record:
            continue
        sha, body = record.strip().split("\x1f", 1)
        lines = attribution_problems(body)
        if lines:
            found.append((sha[:7], lines))
    return found


def cmd_check_messages(a, d, now):
    found = unpushed_attribution_problems()
    if not found:
        print("No unpushed commit carries a co-author trailer or a model name.")
        return 0
    for sha, lines in found:
        print(f"{sha}: " + "; ".join(lines))
    print("Reword these commits before pushing (git rebase -i on unpushed commits only).")
    return 2


def cmd_deliver(a, d, now):
    with locked(d):
        task = need_task(ledger(d, now), a.task)
        need_owner(task, a.session)
        if task["status"] != "in-review":
            raise Refused(f"{a.task} is {task['status']}; it must be in-review.")
        if not task["verification"]:
            raise Refused(f"{a.task} has no passing verification from a second session yet.")
        if not a.skip_git_check and not commit_exists(a.commit):
            raise Refused(f"Commit {a.commit} was not found in this repository.")
        if not a.skip_git_check:
            checks_gate(a)
            found = unpushed_attribution_problems()
            if found:
                raise Refused(f"attribution in unpushed commits {', '.join(sha for sha, _ in found)}: run check-messages and reword them.")
        append(d, {"t": "deliver", "task": a.task, "session": a.session, "commit": a.commit}, now)
    print(f"{a.task} delivered at {a.commit}. Run `next`, and add a lesson if anything surprised you.")
    return 0


def cmd_block(a, d, now):
    with locked(d):
        task = need_task(ledger(d, now), a.task)
        need_owner(task, a.session)
        append(d, {"t": "block", "task": a.task, "session": a.session, "reason": a.reason}, now)
    print(f"{a.task} marked blocked.")
    return 0


def cmd_release(a, d, now):
    with locked(d):
        task = need_task(ledger(d, now), a.task)
        need_owner(task, a.session)
        append(d, {"t": "release", "task": a.task, "session": a.session, "note": a.note or ""}, now)
    print(f"{a.task} released.")
    return 0


def cmd_show(a, d, now):
    task = need_task(ledger(d, now), a.task)
    print(f"{task['id']} {task['title']} [{task['stage']}, {task['hours']}h] status={task['status']} owner={task['owner']}")
    print(f"deps: {', '.join(task['deps']) or 'none'}  commit: {task['commit'] or '-'}")
    print(f"prompt: docs/plan/prompts/{task['id']}.md")
    for e in task["evidence"]:
        print(f"  evidence {e['kind']}: {e['ref']} - {e['summary']} ({e['session']})")
    if task["verification"]:
        print(f"  verified by {task['verification']['verifier']}: {task['verification']['note']}")
    if task["last_note"]:
        print(f"note: {task['last_note']}")
    return 0


def cmd_sessions(a, d, now):
    s = ledger(d, now)
    rows = []
    for sess, at in sorted(s["seen"].items(), key=lambda kv: kv[1], reverse=True):
        if now - at <= SEEN_WINDOW:
            held = [t["id"] for t in s["tasks"].values() if t["owner"] == sess and t["status"] in HELD]
            rows.append(f"{sess}  last seen {at.isoformat()}  holding: {', '.join(held) or 'nothing'}")
    print("\n".join(rows) if rows else "No active sessions in the last 4 hours.")
    return 0


def cmd_lesson(a, d, now):
    if a.action == "add":
        tasks = [t.strip() for t in (a.tasks or "").split(",") if t.strip()]
        with locked(d):
            s = ledger(d, now)
            append(d, {"t": "lesson", "session": a.session, "title": a.title, "body": a.body, "tasks": tasks, "area": a.area or ""}, now)
            n = len(s["lessons"]) + 1
        print(f"Lesson L{n} published. Now notify the other active sessions (python delivery.py sessions, then SendMessage each one a one-line pointer to L{n}).")
        return 0
    if a.action == "ack":
        with locked(d):
            append(d, {"t": "ack", "session": a.session}, now)
        print(f"{a.session} is up to date with all lessons.")
        return 0
    s = ledger(d, now)
    lessons = unread_for(s, a.session) if a.unread else s["lessons"]
    if a.unread and not a.session:
        raise Refused("--unread needs --session.")
    if not lessons:
        print("No unread lessons." if a.unread else "No lessons yet.")
    for l in lessons:
        scope = f"  applies to: {', '.join(l['tasks'])}" if l["tasks"] else ""
        print(f"{l['id']} [{l['session']}] {l['title']}\n  {l['body']}{scope}")
    return 0


def cmd_render(a, d, now):
    s = ledger(d, now)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tasks = list(s["tasks"].values())
    delivered = [t for t in tasks if t["status"] == "delivered"]
    names = {st["id"]: st["name"] for st in s["stages"]}
    lines = ["# Delivery status", "", f"Generated {now.isoformat()}. Source of truth: the shared ledger (python delivery.py status). Delivered {len(delivered)}/{len(tasks)} tasks.", ""]
    for sid in dict.fromkeys(t["stage"] for t in tasks):
        lines += [f"## {sid} {names.get(sid, '')}", "", "| Task | Title | Status | Owner | Commit | Evidence |", "|---|---|---|---|---|---|"]
        for t in (x for x in tasks if x["stage"] == sid):
            ev = ", ".join(sorted({e["kind"] for e in t["evidence"]})) or "-"
            ver = f"; verified by {t['verification']['verifier']}" if t["verification"] else ""
            lines.append(f"| {t['id']} | {t['title']} | {t['status']} | {t['owner'] or '-'} | {t['commit'] or '-'} | {ev}{ver} |")
        lines.append("")
    (out / "STATUS.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    ll = ["# Lessons learnt", "", "Newest last. Add one with: python delivery.py lesson add ...", ""]
    for l in s["lessons"]:
        ll += [f"## {l['id']} {l['title']}", "", f"By {l['session']} on {l['at']}." + (f" Applies to: {', '.join(l['tasks'])}." if l["tasks"] else ""), "", l["body"], ""]
    (out / "LESSONS.md").write_text("\n".join(ll), encoding="utf-8", newline="\n")
    (out / "ledger.jsonl").write_text((d / "events.jsonl").read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    print(f"Wrote {out / 'STATUS.md'}, {out / 'LESSONS.md'} and the audit backup {out / 'ledger.jsonl'}.")
    return 0


# ---------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="delivery.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    sp = add("init", cmd_init, "seed or refresh the ledger from docs/plan/tasks.json")
    sp.add_argument("--plan")
    sp.add_argument("--restore", help="rebuild an empty ledger from a ledger.jsonl backup written by render")
    sp = add("status", cmd_status, "progress by stage, and what is held")
    sp.add_argument("--json", action="store_true")
    sp = add("next", cmd_next, "tasks that are ready: dependencies delivered, nobody holds them")
    sp.add_argument("--n", type=int, default=5)
    sp = add("claim", cmd_claim, "take a ready task (refused if you have unread lessons)")
    sp.add_argument("task"); sp.add_argument("--session", required=True); sp.add_argument("--branch")
    sp = add("heartbeat", cmd_heartbeat, "say you are still working (at least hourly)")
    sp.add_argument("task"); sp.add_argument("--session", required=True); sp.add_argument("--note", default="")
    sp = add("evidence", cmd_evidence, "record a piece of delivery evidence")
    sp.add_argument("task"); sp.add_argument("--session", required=True); sp.add_argument("--kind", required=True)
    sp.add_argument("--ref", required=True, help="for tests-red and tests-green: the commit sha first, then any description; otherwise a file, section or output location")
    sp.add_argument("--summary", required=True); sp.add_argument("--skip-git-check", action="store_true", help="tests of this tool only; never on real work")
    sp = add("review", cmd_review, "move to review once the required evidence exists")
    sp.add_argument("task"); sp.add_argument("--session", required=True); sp.add_argument("--skip-git-check", action="store_true", help="tests of this tool only; never on real work")
    sp = add("verify", cmd_verify, "independent check by a different session")
    sp.add_argument("task"); sp.add_argument("--verifier", required=True); sp.add_argument("--result", required=True, choices=["pass", "fail"]); sp.add_argument("--note", default="")
    add("check-messages", cmd_check_messages, "list unpushed commits whose messages carry a co-author trailer or a model name")
    sp = add("deliver", cmd_deliver, "mark delivered once verified (--skip-git-check is for tests of this tool only)")
    sp.add_argument("task"); sp.add_argument("--session", required=True); sp.add_argument("--commit", required=True); sp.add_argument("--skip-git-check", action="store_true")
    sp = add("block", cmd_block, "mark a task blocked, with the reason")
    sp.add_argument("task"); sp.add_argument("--session", required=True); sp.add_argument("--reason", required=True)
    sp = add("release", cmd_release, "give a task back")
    sp.add_argument("task"); sp.add_argument("--session", required=True); sp.add_argument("--note")
    sp = add("show", cmd_show, "one task with its evidence")
    sp.add_argument("task")
    add("sessions", cmd_sessions, "sessions seen in the last 4 hours (who to notify)")
    sp = add("lesson", cmd_lesson, "add, list or acknowledge shared lessons")
    sp.add_argument("action", choices=["add", "list", "ack"])
    sp.add_argument("--session"); sp.add_argument("--title"); sp.add_argument("--body"); sp.add_argument("--tasks"); sp.add_argument("--area")
    sp.add_argument("--unread", action="store_true")
    sp = add("render", cmd_render, "write STATUS.md and LESSONS.md for committing")
    sp.add_argument("--out", default="docs/delivery")
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        a = build_parser().parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    if a.cmd == "lesson":
        if a.action in ("add", "ack") and not a.session:
            print("--session is required.", file=sys.stderr)
            return 2
        if a.action == "add" and not (a.title and a.body):
            print("A lesson needs --title and --body.", file=sys.stderr)
            return 2
    try:
        return a.fn(a, state_dir(), now_utc())
    except Refused as e:
        print(f"Refused: {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
