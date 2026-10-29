# Build-wave rules (build first, verify after)

Adopted 2026-10-29. The one-task-one-verifier loop kept the application waiting on tests for a week. In a build wave, builders build and unit-test; verification happens afterwards, in batches, in dependency order. These rules replace the builder brief for build-wave bundles. Everything not mentioned here (the safety, privacy, tenancy and secret rules, DEC-001 graph-native data, DEC-130 to DEC-134 tenancy) still applies.

## What a builder does

1. You build one bundle: the tasks the orchestrator names, in dependency order. Read each task's prompt `docs/plan/prompts/<ID>.md` (if there is none, scope comes from `docs/plan/tasks.json`, `docs/plan/tenancy-plan.md` and `docs/delivery/tenancy-audit/`), the lessons (`python .claude/skills/diucs-delivery/scripts/delivery.py lesson list --session <you>` then `lesson ack`), and `docs/delivery/decisions.md` for the decisions it names.
2. Work in your own worktree and branch, created from the integration branch the orchestrator names: `git worktree add /home/user/overwatch-wt/<bundle> -b task/build-<bundle> <integration branch>`.
3. Per task: write the failing unit tests first and commit them alone (`<ID>: failing tests (red)`), run them and confirm they fail for the right reason; then write the least code that passes and commit (`<ID>: implement`). Every task has unit tests that pin its acceptance criteria and its edge cases.
4. Run only fast checks, on what you changed: `uv run pytest <your test files> -q -p no:cacheprovider`, `uv run ruff check <changed files>`, `uv run ruff format <changed files>`, `uv run mypy <changed source files>`. Start each run once and wait for its completion notice. No polling loops and no watchers.
5. Do not run Neo4j, Docker, any whole directory, the whole suite, or `record_checks.py`. Do not take the Neo4j lock. Do not write evidence, run `claim`, `evidence`, `review`, `verify` or `deliver`, or push. Those happen in the verification stage.
6. Commit messages: `<ID>: failing tests (red)` and `<ID>: implement`, no model name, no Co-Authored-By trailer. `python .claude/skills/diucs-delivery/scripts/delivery.py check-messages` must print the clean line before you report.

## Shared documents: use a fragment, never the shared file

Do not edit `docs/delivery/decisions.md`, `hazard-log.md`, `known-issues.md` or `docs/spec/contracts.md`. They are the reason merges conflict. Write one file per task, `docs/delivery/fragments/<ID>.md`, with these sections (omit one that is empty):

- `## Decision`: a title line, then the body (what you decided and why; items numbered). No DEC number: the orchestrator numbers it when folding.
- `## Hazards`: table rows `| id | hazard | source | control | tasks | verified by | status |`, with a placeholder id `H-NEW-<n>`.
- `## Known issues`: table rows `| <ID> | what | where | trigger |`.
- `## Contracts`: the names you added (ports, classes, routes, files), one bullet each.
- `## Tenant pending`: every statement the task uses that is not yet converted, and what swaps in later.
- `## Assumed`: every [ASSUMED] constant or rule, with its value.

## Tenancy and safety in a build wave

- Any new Cypher is a registered `NamedQuery` with `tenantId: $tenant` on every node it matches, merges or creates, and a `Scenario`; no raw driver use; no Cypher built from pieces. The tenant comes only from the unit of work. Unit-test the statement text and the scenario shape; the generated two-tenant test proves isolation in the verification stage.
- The `UNCONVERTED` ratchet only shrinks. A conversion task removes its ids and lowers the cap in `tests/unit/adapters/outbound/graph_store/test_queries.py` in the same commit.
- Patient-facing rules (a figure's age, a Y confirming only a current figure, flags, the missed-report ladder, privacy guard) are not relaxed because verification comes later: write their unit tests to the boundary values.
- External services (Twilio, Entra, email, Service Bus, maps) are built against recording fakes. No real credential, no real send. No patient data anywhere: use the sample values in the prompts.
- Do not run the formatter outside the files you changed, and never from the repo root.

## Finishing

Report in under 150 words: your branch tip, each task built (built, partly built, or blocked and why), the unit-test count, anything assumed, and anything that needs a decision. A task that cannot be built without a real credential or account is built against a fake and marked so.
