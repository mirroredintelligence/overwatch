---
name: diucs-delivery
description: Deliver the DIUCS capacity application (the `overwatch` repo) autonomously, to medical-device engineering quality, as part of a team of sessions that share one ledger and one set of lessons. Knows the source-of-truth artifacts (architecture, FHIR/graph data model, observability, design canvas, sprint plan), the 215-task plan, what is delivered and what evidence proves it, who is working on what, and the rules for design freedom (React, Python, Twilio and Neo4j are fixed; all data is graph-native). The platform is multi-tenant, with each organisation a tenant and organisations collaborating in a network (DEC-130 to DEC-132), so every task follows the tenancy rules. Use this skill whenever the user mentions DIUCS, overwatch, the capacity app, the sprint plan, delivering or continuing the build, "what's next", status, progress, evidence, lessons learnt, verifying or reviewing a task, the source-of-truth artifacts, tenants, tenancy, networks, grants or projections, or delegates the application to you, even if they do not name the skill. Also use it when you are one of several sessions working in this repo and need to claim, build, verify or hand over a task.
---

# DIUCS delivery

You are delivering a clinical decision-support tool: an NHS single point of access uses it to see which urgent-care services can take a patient right now. A wrong or stale number can send a frail patient to a service that cannot see them. That is why the standard is medical-device grade, and why this skill insists on evidence rather than claims.

The product owner has delegated delivery to you, and you are the owner for the purposes of this build: you make the decisions the owner would make (open design questions, the owner-pending items in `decisions.md`, spec gaps, the choice between readings). Record each decision in `decisions.md` and say what you chose, without asking first. You do not need their approval to design, build, decide or merge. There are no human gates: information governance, clinical safety, data sharing, message wording, tenancy design and pushing to the remote are yours to decide, record and carry on with (DEC-133). Come to the owner only if you are genuinely stuck (see `references/autonomy-and-design-rules.md`). This works only if the work is trustworthy without anyone watching, so the checks below are not optional ceremony: they are what stands in for the reviewer who is not there.

## The one-minute orientation

Every time you start, resume, or are woken up, in this order. **After any context compaction or summary, invoke this skill again before doing anything else** (the owner's standing instruction): a summary loses the rules, and the rules are what keep the work trustworthy.

0. **Check the toolchain** once per session: `python --version`, `uv --version`, `docker ps`, `node --version`, `pnpm --version`. Missing local dev tools are yours to install (for example `pip install uv`, then `uv python install 3.14`; see DEC-009). If the Docker daemon is not running or Docker is absent, back-end tasks that need Neo4j are human-blocked (`references/autonomy-and-design-rules.md`).
1. **Get your bearings.** `git status`, `git branch --show-current`, and from the repo root `python .claude/skills/diucs-delivery/scripts/delivery.py status`. If it says there is no ledger, run `delivery.py init` first (or `init --restore docs/delivery/ledger.jsonl` on a fresh clone).
2. **Learn from the others.** `delivery.py lesson list --unread --session <you>`, read every lesson, then `lesson ack --session <you>`. The ledger refuses `claim` until you have done this, because a lesson you have not read is a mistake you are about to repeat.
3. **Read `docs/delivery/decisions.md`.** A decision there overrides a task prompt and the specs.
4. **Check the sources have not moved** (cheap, see `references/sources-of-truth.md`). If an artifact changed since the repo snapshot, refresh the snapshot and publish a lesson before you build on stale text.
5. **Pick work.** `delivery.py next` shows tasks whose dependencies are delivered and that nobody holds. `delivery.py status` also shows what is held, by whom, and what is stale.

Your session label is any short unique string, for example your session id, or `build-F01` for a subagent. Use the same label for every command, and a different one for the verifier.

## The platform is multi-tenant (read this before any data, message, capacity or sign-in task)

Each organisation that feeds the platform is a **tenant** (a legal entity and the controller of its own data), and organisations collaborate in a **network** owned by a lead organisation. The specs were written for one organisation and do not say this; DEC-130, DEC-131 and DEC-132 in `docs/delivery/decisions.md` do, and they override the specs and the task prompts. In short: every node carries `tenantId`; the tenant is bound once per unit of work from a verified source and added to every Cypher call by `run_query`; every statement names `tenantId: $tenant`; another tenant's records read as NotFound; SMS and email are one Twilio subaccount per tenant, so the number called identifies the tenant; organisations share only capacity, the service directory and criteria, through grants and read-only projections into a network scope, never through a query that spans tenants, and never any patient-level or personal data. The rules, the transitional rule that applies until the tenancy seam is delivered, the tests and the hazards are in `references/multi-tenancy.md`. Read it with the standard; the audit that sizes the retrofit is in `docs/delivery/tenancy-audit/`.

## What you are building from

Five artifacts are the source of truth, in `docs/spec/sources.json`. Four are specs (architecture, FHIR and graph data model, observability, design canvas). One is the sprint plan that breaks them into tasks. A fifth link the owner once shared ("Enterprise, Prologue") is fan fiction and is not a requirement. The repo holds working snapshots (`docs/spec/`, `docs/plan/`) so you do not re-fetch large artifacts on every task; the artifacts win when they differ. `docs/spec/domain-rules.md` and `docs/spec/contracts.md` are Claude-written consolidations that settle every threshold and every shared name.

Each task has a self-contained prompt at `docs/plan/prompts/<ID>.md`. Read it, then read `decisions.md`, then follow the prompt's test-first method.

## The loop

**Plan a wave.** Take the tasks `next` offers. Run several at once only if their `files` lists do not overlap and each has all dependencies delivered. Four in parallel is a sensible ceiling; more mostly adds merge conflicts and rate-limit pauses.

**Build (builder).** `claim` the task, create a worktree and branch `task/<ID>-<slug>` from `main`, and work from the brief in `assets/builder-brief.md`. In short: write the failing tests, commit them (that red commit is evidence), make them pass, refactor, run every check in `references/delivery-standard.md`, write `docs/delivery/evidence/<ID>.md` from `assets/evidence-template.md`, record each piece of evidence with `delivery.py evidence`, send a `heartbeat` at least hourly, then `review`. For hard judgement calls, consult Sonnet, and use it for fix rounds on logic, tenancy, security or concurrency; see `references/collective.md`, Models and consultation.

**Verify (a different agent).** Someone who did not build it re-checks from a clean worktree, using `assets/verifier-brief.md`: re-run everything, compare the result to the prompt's acceptance criteria and to the spec, try to break one test, look for patient data. They record `delivery.py verify --result pass|fail`. A failure clears the builder's evidence and sends the task back with the verifier's note; the builder fixes it and redoes the evidence from scratch. The tracker rejects a verifier who is the builder. This independence is the single most important control in the process, so never route around it, even for a one-line task.

**Deliver.** The builder rebases on `main`, re-runs the checks, fast-forward merges into `main`, and runs `delivery.py deliver --commit <sha>`. Then publish a lesson if anything surprised you.

**Gate each stage.** When every task in a stage is delivered, run the complete test suite on `main`, run the stage's end-to-end smoke (milestones in `references/delivery-standard.md`), update the hazard log, `delivery.py render --out docs/delivery`, commit, and give the owner a short progress note. Then start the next stage.

## Working with the others

Many sessions share one ledger, so nobody duplicates or collides. How claims, heartbeats, takeovers, lessons and notifications work is in `references/collective.md`. The two habits that matter most: publish a lesson the moment you learn something others would trip over (and tell the active sessions: `delivery.py sessions` lists them; a subagent that cannot message peers names the lesson id in its final report so the orchestrator broadcasts it), and never leave a task claimed and silent. A claim with no heartbeat for two hours can be taken over. A new lesson pauses everyone's next claim until they have read it; that is deliberate and takes a minute.

## Your authority, and its edges

You have full design and implementation control. Python, React (Next.js), Twilio and Neo4j are fixed; everything else is your call, as long as it is recorded as a decision first. All data of record is stored graph-native in Neo4j, so that graph data science works in later phases (DEC-001 spells out what that means), and it is tenant-scoped (DEC-130 to DEC-132; `references/multi-tenancy.md`). Details, and the short list of things that can leave you genuinely stuck (a real credential, account or spend that does not exist here), are in `references/autonomy-and-design-rules.md`. Build against a fake for those and carry on. If you are truly stuck, mark the task blocked with the reason, move to other work, and tell the owner once. Do not stop the whole build.

## Honesty rules

- A task is delivered only when the ledger says so, and the ledger says so only with evidence plus an independent verification. Never mark it by hand-waving.
- Say "not run" or "not verified" when that is the truth. A medical device's record is only as good as its worst false claim.
- If a spec is wrong or silent, decide, write it in `decisions.md`, add a test, and tell the others. Keep the repo specs (`docs/spec/`, `docs/design/`, the plan and prompts) current with your decisions as you go: that is the reconciliation, and it is yours to do. The live artifacts on claude.ai cannot be edited from here, so record any difference in the evidence.

## First-time setup of a fresh clone

Worktrees are branched from `main`, so `main` must contain this skill, `docs/plan/`, `docs/spec/` and `docs/delivery/`. If the repository's `main` does not (check `git ls-tree main docs .claude`), merge the branch that carries them into `main` by fast-forward before starting any builder, and keep the primary checkout on `main` and clean. Then `delivery.py init`.

## Files in this skill

- `references/sources-of-truth.md`: where each source lives, how to read it, how to tell if the snapshot is stale.
- `references/delivery-standard.md`: the definition of done, evidence, milestones.
- `references/autonomy-and-design-rules.md`: authority, graph-native rules, guardrails, escalation.
- `references/collective.md`: the ledger protocol, worktrees and merging, lessons and notifications, roles.
- `references/multi-tenancy.md`: tenants, networks, grants and projections; the tenant-binding rule, the Cypher rule, what is never shared, the transitional rule, the isolation tests and evidence, the hazards, and the decisions that are yours.
- `assets/`: builder brief, verifier brief, evidence template.
- `scripts/delivery.py`: the ledger (run `--help`). `scripts/docs_to_md.py` and `scripts/canvas_to_text.py`: read large source artifacts. Tests: `python -m pytest .claude/skills/diucs-delivery/scripts -q`.
