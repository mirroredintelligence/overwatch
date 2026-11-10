#!/usr/bin/env python3
"""Self-check for docs/design/workspaces. Standard library only. Run from the repo root:

    python docs/design/workspaces/check.py

It is also an executable reading of the spec: the dialog renderer below is the reference the TypeScript
implementation (frontend/lib/workspace/dialog.ts) must match, example for example.
Exit code 0: every check passed. Otherwise the failures are printed and the exit code is 1.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
failures: list[str] = []


def fail(message: str) -> None:
    failures.append(message)


def load(name: str):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------- registry
registry = load("registry.json")
dialog = load("dialog.json")

personas = set(registry["personas"])
flags = set(registry["flags"])
layouts = set(registry["layouts"])
adapter = {row["sessionRole"]: row for row in registry["adapter"]}
intents = {}
for intent in registry["intents"]:
    if intent["id"] in intents:
        fail(f"registry: duplicate intent {intent['id']}")
    intents[intent["id"]] = intent

for row in registry["adapter"]:
    if row["persona"] not in personas:
        fail(f"registry: adapter {row['sessionRole']} names unknown persona {row['persona']}")
    for flag in row["flags"]:
        if flag not in flags:
            fail(f"registry: adapter {row['sessionRole']} names unknown flag {flag}")

for intent in intents.values():
    where = f"registry: intent {intent['id']}"
    if intent["kind"] not in ("view", "action", "nav"):
        fail(f"{where}: unknown kind {intent['kind']}")
    for persona in intent["personas"]:
        if persona not in personas:
            fail(f"{where}: unknown persona {persona}")
    if intent["requires"] is not None and intent["requires"] not in flags:
        fail(f"{where}: unknown flag {intent['requires']}")
    for role in intent.get("sessionRoles", []):
        if role not in adapter:
            fail(f"{where}: unknown session role {role}")
    if intent["layout"] is not None and intent["layout"] not in layouts:
        fail(f"{where}: unknown layout {intent['layout']}")
    if intent["dataClass"] not in registry["dataClasses"]:
        fail(f"{where}: unknown data class {intent['dataClass']}")
    persona_class = registry["personas"][intent["personas"][0]]["dataClass"]
    rank = {"none": 0, "aggregate": 1, "patient": 2}
    if rank[intent["dataClass"]] > rank[persona_class] and intent["requires"] is None:
        fail(f"{where}: needs {intent['dataClass']} data but persona {intent['personas'][0]} holds {persona_class}, and no flag lifts it")


def may_open(session_role: str, intent: dict, live_phase: int) -> bool:
    """The reading of registry.json that lib/workspace/registry.ts canOpen must implement."""
    row = adapter.get(session_role)
    if row is None or intent["phase"] > live_phase:
        return False
    if row["persona"] not in intent["personas"]:
        return False
    if intent["requires"] is not None and intent["requires"] not in row["flags"]:
        return False
    if "sessionRoles" in intent and session_role not in intent["sessionRoles"]:
        return False
    if intent["kind"] != "nav" and not row["workspace"]:
        return False
    return True


# The route guard, read from frontend/lib/auth/access.ts (the table the proxy uses).
access = (ROOT / "frontend" / "lib" / "auth" / "access.ts").read_text(encoding="utf-8")
prefix_roles = {m.group(1): re.findall(r"'([\w-]+)'", m.group(2)) for m in re.finditer(r"\['([\w-]+)',\s*\[([^\]]*)\]\]", access)}
v2_match = re.search(r"ADVISOR_V2_ROLES[^=]*=\s*\[([^\]]*)\]", access)
v2_roles = re.findall(r"'([\w-]+)'", v2_match.group(1)) if v2_match else []
if not prefix_roles or not v2_roles:
    fail("access.ts: could not read the route table (the checker's regex needs updating)")


def guard_allows(session_role: str, route: str) -> bool:
    segments = [s for s in route.split("/") if s]
    first = segments[0].lower() if segments else ""
    if first == "advisor" and len(segments) > 1 and segments[1].lower() == "v2":
        return session_role in v2_roles
    allowed = prefix_roles.get(first)
    return True if allowed is None else session_role in allowed


for intent in intents.values():
    for session_role in adapter:
        if may_open(session_role, intent, 99) and not guard_allows(session_role, intent["route"]):
            fail(f"registry: intent {intent['id']} would be offered to session role {session_role}, but the route guard denies {intent['route']}")
    if not any(may_open(r, intent, 99) for r in adapter):
        fail(f"registry: intent {intent['id']} is offered to no session role")

# ---------------------------------------------------------------------------------------------- dialog
DERIVED = dialog["derived"]


def lookup(name: str, ctx: dict) -> str:
    if name in ctx and ctx[name] is not None:
        return str(ctx[name])
    if name in DERIVED:
        rule = DERIVED[name]
        n = ctx.get(rule["from"])
        if isinstance(n, (int, float)) and not isinstance(n, bool):
            return rule["one"] if n == 1 else rule["other"]
    raise ValueError("dialog: missing {%s}" % name)


def fill(template: str, ctx: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: lookup(m.group(1), ctx), template)


def holds(when: dict, ctx: dict) -> bool:
    for key, want in when.items():
        have = ctx.get(key)
        if isinstance(want, dict):
            if "gt" in want:
                if not (isinstance(have, (int, float)) and not isinstance(have, bool) and have > want["gt"]):
                    return False
            elif "present" in want:
                is_present = isinstance(have, str) and have != ""
                if is_present != want["present"]:
                    return False
            else:
                return False
        elif have is None or have != want or isinstance(have, bool) != isinstance(want, bool):
            return False
    return True


def render(intent_id: str, ctx: dict, with_echo: bool = True):
    turn = dialog["turns"][intent_id]
    if turn is None:
        return None
    echo = fill(turn["echo"], ctx) if (turn["echo"] and with_echo) else None
    variant = next(v for v in turn["variants"] if holds(v["when"], ctx))
    reply = fill(variant["reply"], ctx)
    chips = [(fill(c["label"], ctx), c["intent"]) for c in turn["chips"] if holds(c.get("when", {}), ctx)]
    return {"echo": echo, "reply": reply, "chips": [c[0] for c in chips], "chipIntents": [c[1] for c in chips]}


for intent in intents.values():
    if intent["kind"] in ("view", "action") and intent["phase"] <= registry["livePhase"] and intent["id"] not in dialog["turns"]:
        fail(f"dialog: no turn for intent {intent['id']}")
for turn_id, turn in dialog["turns"].items():
    if turn_id not in intents:
        fail(f"dialog: turn {turn_id} is not an intent")
        continue
    if turn is None:
        continue
    if turn["variants"][-1]["when"] != {}:
        fail(f"dialog: turn {turn_id}: the last variant must have an empty 'when'")
    for chip in turn["chips"]:
        if chip["intent"] not in intents:
            fail(f"dialog: turn {turn_id}: chip {chip['label']!r} targets unknown intent {chip['intent']}")

seen_ids = set()
for ex in dialog["examples"]:
    if ex["id"] in seen_ids:
        fail(f"dialog: duplicate example id {ex['id']}")
    seen_ids.add(ex["id"])
    try:
        got = render(ex["intent"], ex["context"], ex.get("withEcho", True))
    except Exception as exc:  # noqa: BLE001
        fail(f"dialog: example {ex['id']} raised {exc}")
        continue
    want = {k: ex[k] for k in ("echo", "reply", "chips", "chipIntents")}
    if got != want:
        fail(f"dialog: example {ex['id']} ({ex['intent']}):\n    expected {want}\n    got      {got}")
for err in dialog["errors"]:
    try:
        render(err["intent"], err["context"])
        fail(f"dialog: error example {err['id']} did not throw")
    except ValueError as exc:
        if str(exc) != err["throws"]:
            fail(f"dialog: error example {err['id']} threw {exc!s}, expected {err['throws']}")
covered = {ex["intent"] for ex in dialog["examples"]}
for turn_id, turn in dialog["turns"].items():
    if turn is not None and turn_id not in covered:
        fail(f"dialog: no example covers turn {turn_id}")

# ---------------------------------------------------------------------------------------------- screens and units
screens_path = HERE / "screens.md"
units_path = HERE / "units.json"
if screens_path.exists() and units_path.exists():
    screens = screens_path.read_text(encoding="utf-8")
    units = json.loads(units_path.read_text(encoding="utf-8"))
    anchors = set(re.findall(r"^#{2,4} (WS-[A-Z0-9-]+)\b", screens, re.M))
    case_ids = re.findall(r"^- `(WS-[A-Z0-9]+-T\d+)`", screens, re.M)
    if len(case_ids) != len(set(case_ids)):
        fail("screens.md: duplicate test case ids")
    by_id = {}
    for unit in units:
        if unit["id"] in by_id:
            fail(f"units: duplicate id {unit['id']}")
        by_id[unit["id"]] = unit
    claimed: dict[str, str] = {}
    for unit in units:
        where = f"units: {unit['id']}"
        if unit["model"] not in ("haiku", "sonnet"):
            fail(f"{where}: model must be haiku or sonnet")
        for dep in unit["depends_on"]:
            if dep not in by_id:
                fail(f"{where}: depends on unknown unit {dep}")
        if unit.get("spec") and unit["spec"] not in anchors:
            fail(f"{where}: spec anchor {unit['spec']} is not a heading in screens.md")
        for case in unit["cases"]:
            if case not in case_ids:
                fail(f"{where}: test case {case} is not defined in screens.md")
            if case in claimed:
                fail(f"{where}: test case {case} is already assigned to {claimed[case]}")
            claimed[case] = unit["id"]
        if unit["model"] == "haiku":
            for field in ("add", "tests", "spec", "why_model", "forbidden"):
                if not unit.get(field):
                    fail(f"{where}: a haiku unit needs a non-empty '{field}'")
            if not unit["cases"] and not unit.get("table_tests"):
                fail(f"{where}: a haiku unit needs 'cases' or 'table_tests'")
        for board in unit.get("boards", []):
            if not (HERE / "boards" / board).exists():
                fail(f"{where}: board {board} is missing from docs/design/workspaces/boards")
    for case in case_ids:
        if case not in claimed:
            fail(f"screens.md: test case {case} is assigned to no unit")
    # No two units that can run at the same time may add or modify the same file.
    def can_overlap(a: str, b: str) -> bool:
        def ancestors(x: str, seen=None):
            seen = seen or set()
            for d in by_id[x]["depends_on"]:
                if d in by_id and d not in seen:
                    seen.add(d)
                    ancestors(d, seen)
            return seen
        return a not in ancestors(b) and b not in ancestors(a)
    owners: dict[str, list[str]] = {}
    for unit in units:
        for path in unit["add"] + unit["modify"]:
            owners.setdefault(path, []).append(unit["id"])
    for path, ids in owners.items():
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                if can_overlap(ids[i], ids[j]):
                    fail(f"units: {ids[i]} and {ids[j]} both write {path} and are not ordered by depends_on")
else:
    print("note: screens.md or units.json not written yet; skipped those checks")

# ---------------------------------------------------------------------------------------------- result
if failures:
    print(f"{len(failures)} problem(s):")
    for message in failures:
        print(" -", message)
    sys.exit(1)
print(
    f"ok: {len(intents)} intents, {len(adapter)} session roles, {len(dialog['examples'])} dialog examples"
    + (f", {len(units)} units, {len(case_ids)} test cases" if screens_path.exists() and units_path.exists() else "")
)
