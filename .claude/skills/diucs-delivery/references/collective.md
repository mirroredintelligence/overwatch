# Working as a collective

Contents: shared state, roles, command cheat sheet, claims, worktrees and merging, lessons and notifications, recovery.

Several sessions build at the same time (chats, subagents, worktrees). They cannot see each other's context, so everything they must share goes through two places: the **ledger** (what is claimed, evidenced, verified, delivered) and the **lessons** (what has been learnt). Both are in one tool, `.claude/skills/diucs-delivery/scripts/delivery.py`, run from the repo root. All commands below are `python .claude/skills/diucs-delivery/scripts/delivery.py <command>`; it is shortened to `delivery.py` here.

## Where state lives

- The ledger is an append-only event log at `<git-common-dir>/diucs-delivery/events.jsonl`, inside the repository's `.git` folder. Every git worktree of this repo shares that one folder, so every session on this machine sees the same state. It is not committed (it changes constantly and would conflict between branches).
- `delivery.py render --out docs/delivery` writes `STATUS.md`, `LESSONS.md` and `ledger.jsonl` (a full audit backup). Commit those at stage gates and whenever lessons were added. On a fresh clone, `delivery.py init`, then `init --restore docs/delivery/ledger.jsonl` into an empty ledger brings the history back.
- Append-only means two sessions writing at once cannot overwrite each other, and the whole history is auditable. A mistaken entry is corrected by a later entry, never by editing the file.

## Roles

| Role | Does | Session label |
|---|---|---|
| Orchestrator | Reads status, plans waves, starts builders and verifiers, runs stage gates, writes progress notes. Does not build. | `orch` |
| Builder | Claims one task, builds it test-first in a worktree, records evidence, asks for review, merges and delivers after a pass. | `build-<ID>` |
| Verifier | Re-checks a task in a clean worktree and records pass or fail. Never the builder of that task. | `verify-<ID>` |

One session can play several roles over time, but not builder and verifier of the same task. Start builders and verifiers as subagents (the Agent tool, with `isolation: "worktree"` for builders) or as separate sessions; give each the matching brief from `assets/`, with the task id and label filled in. Hand over the brief, not your conversation: a fresh agent that reads the brief, this skill and the task prompt has everything it needs.

Usage limits can stop agents mid-task. They keep their saved progress; resume them with SendMessage when the limit resets, and do not start a duplicate.

## Models and consultation

The Agent tool takes a `model` argument, and subagents inherit the orchestrator's model unless you set it. Use `model: "sonnet"` for judgement-heavy work. The default model is fine for mechanical work.

- **Consult Sonnet for a second reading** when a decision or a suspected defect is hard to settle alone: a tenancy, security or privacy rule; locking or concurrency; the behaviour of Cypher, Neo4j, cryptography or the Python runtime; a finding you cannot tell is real. Give the consult a self-contained question, the files and commit to read, and what you have already ruled out. Its answer is advice. You decide, record the decision, and make the change yourself.
- **Use Sonnet for fix rounds** whose findings are logic, tenancy, security or concurrency, especially after a FAIL on such a finding. The orchestrator starts that builder with `model: "sonnet"`. A builder does not start its own builders.
- **Keep the default model for mechanical work**: record and documentation fixes, formatting, renames, lint, and re-running checks.
- **A consult is not verification.** The verdict on a task comes only from an agent that did not build it. A verifier may consult Sonnet, but the verdict stays the verifier's, and the consult goes in the verifier's report.
- **Say it in the evidence.** When a consult or a Sonnet builder shaped a change, add one line to the evidence: the question, and what changed because of the answer.
- **Quote, don't paraphrase.** Every sentence in evidence that quotes an earlier commit, a guard line or a spec sentence is checked with `git show <commit>:<path>` and `grep -F` before it is written. Paraphrased quotes are the most common reason a task has failed verification.

## Command cheat sheet

| Command | Purpose |
|---|---|
| `status [--json]` | Progress by stage, what is held, what is stale |
| `next [--n 5]` | Ready tasks (dependencies delivered, nobody holds them; stale ones can be taken over) |
| `show <ID>` | One task with its evidence and prompt path |
| `claim <ID> --session S [--branch B]` | Take a task. Refused if dependencies are not delivered, someone live holds it, or you have unread lessons |
| `heartbeat <ID> --session S --note "..."` | Say you are alive. At least hourly. Also warns you of unread lessons |
| `evidence <ID> --session S --kind K --ref R --summary "..."` | Record evidence (kinds in `delivery-standard.md`) |
| `review <ID> --session S` | Ask for verification. Refused until the four required evidence kinds exist |
| `verify <ID> --verifier V --result pass\|fail --note "..."` | Independent check. Refused if V is the builder. A fail clears the evidence |
| `deliver <ID> --session S --commit SHA` | Mark delivered. Refused without a pass, and checks the commit exists |
| `block <ID> --session S --reason "..."` / `release <ID> --session S` | Park or give back |
| `lesson add --session S --title "..." --body "..." [--tasks A,B] [--area X]` | Publish a lesson |
| `lesson list [--unread --session S]` / `lesson ack --session S` | Read lessons, mark them read |
| `sessions` | Sessions active in the last 4 hours: who to notify |
| `render --out docs/delivery` | Write the status, lessons and audit backup for committing |
| `init [--plan P] [--restore F]` | Seed or refresh from `docs/plan/tasks.json`, or restore a backup |

Exit codes: 0 done; 2 refused (the message says why); 3 you have unread lessons.

Evidence references for `tests-red` and `tests-green` must start with the sha of a commit that exists, then any description (`--ref "1a2b3c4 failing run, evidence file section 2"`). `review` checks that the red commit is an earlier commit than the green one: that is the test-first proof, in the tool. Two switches exist for testing the tool itself and must never be used on real work: `--skip-git-check` (on `evidence`, `review`, `deliver`) and the `DIUCS_DELIVERY_DIR` environment variable, which points the ledger at a scratch folder (use it for dry runs and demos so the real ledger stays clean).

## Claims, heartbeats, takeover

- `claim` before you touch anything. It stops two sessions building the same task. Claiming again with your own label is fine.
- Heartbeat at least every hour, with a note saying where you are ("green on 6 of 9 tests"). The note is how the orchestrator and others see progress.
- A claim with no heartbeat for two hours shows as `stale` and can be taken over by anyone. The new owner starts from the old branch if one exists (`git branch --list "task/<ID>-*"`), reads its commits, and must redo and re-record the evidence, because the old evidence belonged to the old owner.
- If you cannot finish, `release` (or `block` with the reason) so the task is not stuck.

## Worktrees, branches and merging

- Trunk is `main`. The primary checkout (`C:\github\overwatch`) stays on `main` and clean; nobody builds in it.
- One task, one branch, one worktree: `git worktree add ../overwatch-wt/<ID> -b task/<ID>-<slug> main`. Remove the worktree after delivery (`git worktree remove`).
- Commits: `<ID>: failing tests (red)`, `<ID>: implement`, further commits as needed, all prefixed with the task id.
- To deliver: in your worktree run `git rebase main` (the repo is local, there is nothing to fetch), re-run every check, then in the primary checkout run `git merge --ff-only task/<ID>-<slug>`. If the fast-forward is refused because `main` moved, rebase again and re-run the checks. Never merge with a merge commit, never force.
- Parallel integration tests: the harness wipes the graph before every test, so runs must not share a database. DEC-008 makes each pytest session start its own throwaway Neo4j on a random port, but several at once overloaded the machine and filled the disk, so since DEC-135 Neo4j test starts are serialised: the harness takes the lock `/tmp/diucs-neo4j-harness.lock` before it starts a container and holds it until the container is removed (a second session waits, up to an hour, then fails naming the holder's pid). Whole runs also queue on the manual `flock /tmp/diucs-neo4j-tests.lock <command>`, a different file: nest the manual lock first and the harness lock second, never the other way round. A test that hangs fails after 300 s (`DIUCS_TEST_TIMEOUT`, 0 turns it off) and set-up after 900 s (`DIUCS_TEST_SETUP_TIMEOUT`). Unit, architecture and front-end tests take no lock.

## Lessons and notifications

A lesson is a short note that would have saved you time or prevented a defect, written for sessions that have no memory of yours. Publish one when you: hit a trap in a tool or library; find a spec gap or error; make or learn of a decision; change a shared name in `contracts.md`; find a test pattern that worked; or break and fix something that others might break too.

Write the title as the rule ("Neo4j datetimes must be timezone-aware UTC or comparisons silently fail"), the body as what happened, what to do instead, and the task ids it affects (`--tasks`). Keep each lesson to one idea.

Publishing and telling are two steps:

1. `delivery.py lesson add --session S --title "..." --body "..." --tasks G05,P01`
2. Notify the others: `delivery.py sessions` lists who was active; `ListAgents` (where you have it) shows live peers. If you can message peers, `SendMessage` each one line. A subagent usually cannot: put the lesson id and one-line rule at the top of your final report and the orchestrator broadcasts it. Example message: `[DIUCS lesson L7] Neo4j datetimes must be UTC. Read: delivery.py lesson list --unread --session <you>`. Name the lesson id and the one-line rule, not the whole text.

Two safety nets catch anyone who misses the message: `claim` is refused until a session has acknowledged all lessons, and `heartbeat` prints a warning when you have unread ones. The author of a lesson counts as having read it.

At stage gates (and when several lessons have accumulated) the orchestrator runs `render` and commits `docs/delivery/LESSONS.md`, so the lessons survive and new sessions on a fresh clone see them. A lesson that changes how something must be done goes into `docs/delivery/decisions.md` as well, and the affected task prompts are amended.

## Changing shared names

If you must add or change a shared name (a port, a class, a route, a model file), append it to the "Additions" section of `docs/spec/contracts.md` in the same commit that introduces it, and publish a lesson naming the task ids that will touch it. Sessions that have not seen the change would otherwise invent a second name for the same thing.

## Recovery

- A session died: subagents send a completion or failure notice when they stop, so the orchestrator usually knows at once; otherwise `status` shows the task as `stale` after two hours. `next` lists it. Claim it and carry on from the branch.
- Ledger missing: `delivery.py init`, then `init --restore docs/delivery/ledger.jsonl` (only into an empty ledger).
- A delivered task turns out wrong: add a correction task (`X01`, `X02`, ...) to `docs/plan/tasks.json` with the original in `deps`, run `init`, and publish a lesson. Do not rewrite history.
- The plan changed (tasks added, removed or re-ordered): edit `docs/plan/tasks.json` and the prompt files, run `init`. Existing history is kept.

## Bundles, decision blocks and batched runs

Adopted 2026-10-29 after the repository conversions (TEN-010, TEN-011, TEN-015) were built as three separate chains. The cost was ratchet conflicts on every merge, a duplicate decision number, and each agent re-running the same Neo4j directories behind the lock.

- **Conversion work is one bundle, one builder.** Statements that change the same ratchet file and cap test (`graph_store/unconverted.py`, `test_queries.py`) are built as a chain by one builder, in milestone order (`docs/plan/milestones.md`, bundles B3 to B6): one red commit per task, one green commit per task, one cap change per commit. Two builders never lower the cap in parallel.
- **Decision numbers come from a block.** The orchestrator reserves a block of ten numbers per builder before it starts (for example DEC-170 to DEC-179 for one builder) and writes the block into the brief. A builder uses only its block. Two branches with the same number is a merge error the orchestrator fixes, not a reason to renumber silently.
- **Full directories run once per merged batch.** The orchestrator merges the batch, then runs each Neo4j directory once under the lock and records the summary lines. A builder runs its own tests and the generated two-tenant test. A verifier runs the task's own tests, the generated test, and its mutants, and runs a full directory only when the task changes shared schema or a shared statement.
- **Unit, architecture and front-end tests take no lock** and may run at any time, in parallel with the Neo4j work.
- **Parallel limit.** Three builders at once, as before. Verifiers are not counted against the limit but each one takes the Neo4j lock for its own runs.
