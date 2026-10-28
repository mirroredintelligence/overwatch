# Delivery standard: medical-device grade engineering

Contents: principles, definition of done, evidence, safety-critical code, stage milestones, what this standard is not.

## Principles

1. **Fail safe.** When the system is unsure, it must say so and hand the decision to a person: Not updated, Last known, phone to confirm, refuse the request, ask again. A confident wrong answer is the worst outcome. Never fill a gap with a plausible default in a patient-facing path.
2. **Prove it, do not claim it.** Every behaviour is pinned by a test that was seen to fail first. Every claim of done is backed by evidence another agent re-checked.
3. **Traceable.** A requirement leads to code and a test, and back. You can answer "which test proves this rule?" for any rule in `docs/spec/domain-rules.md`.
4. **No patient data, anywhere.** Not in code, fixtures, logs, messages, telemetry, errors or evidence files.
5. **One source of truth per fact.** No duplicate copies that can disagree (DEC-001).
6. **Change is controlled.** Deviations are written down (`decisions.md`) before they are built, and tested.
7. **Tenants are isolated.** One organisation's data is never readable, changeable or detectable by another's. Sharing is only through grants and read-only projections of an allowlisted minimum (DEC-130 to DEC-132, `multi-tenancy.md`). A leak between tenants is a patient-safety and information-governance failure, not a bug to fix later.

## Definition of done (every task)

A task is done only when all of these hold. The tracker enforces the evidence kinds in bold.

1. **Red first** (**tests-red**). The tests from the prompt's "Tests to write first" were committed alone, in a commit named `<ID>: failing tests (red)`, and seen to fail for the right reason (the assertion, not an import error). Put the failing run's tail in the evidence file.
2. **Green** (**tests-green**). The implementation commit makes them pass. Behaviour you added beyond the prompt has its own tests, written first.
3. **All checks pass** (**checks**), for the parts you touched. Back end, from `backend/` with Docker up: `uv run pytest` (unit and integration), `uv run ruff check . && uv run ruff format --check .`, `uv run mypy src` (strict), `uv run lint-imports`. Front end, from `frontend/`: `pnpm test`, `pnpm lint`, `pnpm typecheck`, and `pnpm e2e` where the task says. Record the commands and the pass counts. If a check cannot run (no Docker, no network), the task is blocked, not delivered.
4. **Traced to the spec** (**spec-trace**). The evidence file lists each requirement the task satisfies (a section of `domain-rules.md`, a data-flow step, a screen, a hazard id) beside the test that proves it. Wording on screens matches `docs/spec/ui-screens.md` exactly.
5. **Hazards updated.** If the task builds or changes a control listed in `docs/delivery/hazard-log.md`, add the test reference in the "Verified by" column in the same commit. A new hazard you notice goes in the log at once.
6. **Privacy scan** (**privacy-scan**, when the task renders, stores, logs or sends text). The privacy guard (D17) passes, and a search of the diff for UK postcodes, NHS-number-shaped strings and names finds only the sample values already in the specs (for example `DT4 8XX`).
7. **Tenant isolation** (when the task reads, writes, sends, receives, caches, queues, authenticates or shows data; register as `other` with a summary starting `tenant-isolation:`). Every statement, key, channel, queue and message the task adds is tenant-scoped as `multi-tenancy.md` requires; the task has a two-tenant test showing tenant A cannot read, change, delete or detect tenant B's records; any cross-scope read it would need is written in the evidence. While the tenancy seam is not yet delivered, follow the transitional rule in `multi-tenancy.md` and list tenant-pending statements.
8. **Independent verification** (**verification**, recorded by `delivery.py verify`). A different agent re-ran the work in a clean worktree and passed it.
9. **Merged to `main` by fast-forward**, then `delivery.py deliver --commit <sha>`. Check the merge's exit code before `deliver`; never chain them through a pipe (L148).

Also expected, not tracked by the tool: no skipped or xfail tests without a decision; no network in unit tests; no `print` debugging; no secrets; dependency versions pinned in the lock file; names and paths exactly as `docs/spec/contracts.md`.

## Evidence

Evidence is a record someone else can re-check. The builder writes `docs/delivery/evidence/<ID>.md` (template: `assets/evidence-template.md`) and registers each piece with `delivery.py evidence <ID> --kind <kind> --ref <where> --summary <one line>`.

| Kind | Required | `--ref` points at |
|---|---|---|
| `tests-red` | yes | The red commit sha first (the tool checks it exists), then the evidence-file section with the failing output |
| `tests-green` | yes | The green commit sha first. The red commit must be an earlier commit than this one |
| `checks` | yes | The evidence-file section listing each command and its result |
| `spec-trace` | yes | The requirement-to-test table in the evidence file |
| `privacy-scan` | when relevant | The scan output |
| `hazard-note` | when relevant | The hazard-log rows changed |
| `coverage`, `mutation`, `perf`, `other` | when relevant | The report or number. Tenant isolation is registered as `other` with a summary starting `tenant-isolation:` and a ref to the evidence file's "Tenant isolation" section |

The verification record (`verify`) is the eighth piece, written by the verifier, with a note saying what they re-ran and what they tried to break.

## Safety-critical code

These carry the clinical risk. In addition to the rules above they need **100% line and branch coverage**, **property-based tests** (Hypothesis on the back end) for anything with a range of inputs, and **mutation checks**:

- Back end: `domain/rules/` (status, freshness, availability, schedule, opening hours, reply parser, reply policy, booking state and rules, criteria filter and workflow, registration gate, alerts, identity policy, tokens, multi-service), `domain/messages/` (templates and privacy guard), and the use cases `ReportCapacity`, `ConfirmCapacity`, `HandleInboundText`, `FilterOptions`, `RequestBooking`, `RespondToBooking`, the booking timers, `ApproveRegistration`, `ApproveCriteria`.
- Front end: the status badge and tile, the options list and its not-suitable reasons, the booking card states, the criteria dialogs.
- Tenancy: the tenant context and its binding in `run_query` and the unit of work, the registration-time `$tenant` check, tenant resolution at each edge (token, session, inbound number, link token, pairing, message properties), the grant rules and the projector, and the projection allowlist. Their mutants include removing the tenant predicate, ignoring the bound tenant, trusting a caller-supplied tenant, and letting a non-allowlisted field through.

Mutation checking: run a mutation tool for the module with a killed-mutant target of 90% or better. Tools such as `mutmut` do not run natively on Windows; run them in a Linux container (`docker run --rm -v <worktree>:/w -w /w python:3.14 ...`). If no tool runs, the verifier does it by hand: change at least three decisive lines (a comparison, a boundary, a branch) and confirm a test fails each time. A test suite that survives obvious mutants is not evidence.

Property tests worth having: the schedule is monotonic and lands on the right London local time across 2026-03-29 and 2026-10-25; the reply parser never raises and never returns a number outside what was typed; status never reads Accepting when the figure is overdue; a booking never leaves a terminal state; the criteria filter never passes a service whose exclusions match; no template ever contains a postcode.

## Milestones (stage gates)

Each gate is a real run on `main` with Docker up, written up in `docs/delivery/evidence/stage-<n>.md`.

- **Stage 0**: both projects build and test in CI; the Neo4j harness wipes and round-trips.
- **Stage 1**: every rule has tests; a FHIR resource round-trips through the graph and back from the graph alone.
- **Stage 2**: report, confirm, prompt and missed-report flows pass on real Neo4j; Redis and bus contracts pass.
- **Milestone A (stage 3)**: a text reply, and a link reply, each change the wall board within 3 seconds at the 95th percentile on real Neo4j; an overdue service shows Not updated; killing the stream shows Last known.
- **Milestone B (stage 4)**: a scripted advisor call (needs, options with data age, I phoned, outcome, summary copy) passes in Playwright; the shift lead sees and chases a late reporter; no postcode remains after close.
- **Stage 5**: booking by text and link, expiry at 10 minutes, withdrawal and cancel.
- **Stage 6**: invitation to live, with every gate of the approval enforced.
- **Stage 7**: installed app with PIN and push; an alert escalates through the ladder.
- **Stage 8 and 9**: suspend and removal, clinical queue, safety concern; telemetry contains no values and support sessions need a code.
- At every gate: whole-suite run, axe checks, hazard log reviewed, `delivery.py render --out docs/delivery` committed. Once tenancy is enforced, the generated two-tenant isolation test over the whole query registry also runs at every gate, and any statement not covered by it is a gate failure. The whole-suite run is a single serial run by the orchestrator, not one per agent.

## What this standard is not

It is engineering rigour. It is not regulatory approval. Whether this is a medical device in law, the clinical safety case (DCB0129 and DCB0160), the DPIA, DTAC and penetration testing are decisions for the owner, the clinical safety officer and information governance. Prepare the material they need (hazard log, traceability, evidence, decisions), never write that any of them is complete, and list them as human-required in progress notes.
