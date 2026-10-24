# Autonomy and design rules

Contents: what you decide, what is fixed, the graph-native rule, guardrails, what is human-only, how to escalate.

## What you decide

The product owner's instruction: full design and implementation control, no approval needed, outside four fixed technologies. In practice you decide and record, without asking:

- Architecture details, libraries, test tools, CI, hosting shape, queue and cache choices, UI structure and components, file layout, naming (subject to `contracts.md`), task order within a stage, how to split or add tasks, and whether a spec instruction is wrong.
- Merging to `main` once a task is verified.

Record any decision that changes what a task prompt or spec says in `docs/delivery/decisions.md` first (next `DEC-n`), then build to it, then publish a lesson. Decisions are how the other sessions learn that the ground moved.

## What is fixed

- **Python** for the back end. **React** (Next.js) for the front end. **Twilio** for SMS. **Neo4j** as the database.
- **All data of record is stored graph-native.** The purpose is that Neo4j Graph Data Science can run on this data in later phases (finding where capacity runs out, how patients flow between services, which criteria correlate with declines). That only works if the structure is in the graph, not hidden in strings.

Everything else the specs name (Redis, Azure Service Bus, Entra ID, Azure Monitor, FastAPI, OpenTelemetry) is a default you may replace, subject to DEC-003.

## The graph-native rule

DEC-001 is the full text. In short:

- Nodes, relationships and typed properties only. No JSON string, serialised resource or map-valued property holds data. No duplicate "canonical" copy.
- References are relationships, coded values are shared `Concept` nodes, repeating elements are child nodes, times are real datetimes. One relationship type, one direction, one meaning.
- Design for projection: a graph projection (nodes of a label, relationships of a type, numeric properties) should be possible without cleaning. Do not encode numbers or dates as text. Keep relationship types specific and consistent so you can project, for example, `(:Observation)-[:FOCUS]->(:HealthcareService)` and `(:Task)-[:OWNER]->(:HealthcareService)` separately.
- A schema test fails the build if any stored property is a map, a list of maps or a JSON-looking string, or if a datetime is stored as text.
- The round trip from FHIR JSON to the graph and back must be lossless for the published profiles, and must work from the graph alone.
- Aggregates and analytics tables are graph nodes too. Transient data (cache, counters, locks) may live in Redis because losing it loses no fact.

## Guardrails (autonomy never covers these)

1. **No real patient data**, in the repo, tests, logs, fixtures, evidence, or messages to other sessions.
2. **No real messages.** Tests and local runs never send a real text or email. Use mocked HTTP, Twilio's test credentials and magic numbers, and a recording sender.
3. **No secrets in git.** Credentials come from environment variables or a secret store. If a task needs a real credential you do not have, mark it blocked (human-required) and carry on with other tasks.
4. **No spending and no accounts.** Do not create paid resources or sign up to services.
5. **No production or live environments.** Delivering software is not the same as going live. Do not deploy to a clinical environment.
6. **Git safety.** Work on task branches in worktrees; never force-push or rewrite history that others rely on; never delete another session's branch or worktree; fast-forward only into `main`. Do not push to a remote or open a pull request until the owner asks (DEC-006); local commits are fine.
7. **Do not edit the source-of-truth artifacts.** They are shared documents owned by others. Record disagreements in `decisions.md` and the evidence, and let the owner reconcile. (You may refresh the repo snapshots.)
8. **Destructive actions outside the repository** (deleting files or data elsewhere, changing system or security settings) are out of scope.
9. **Never claim a human-only item is done:** clinical safety sign-off, DPIA, DTAC, regulatory classification, penetration test, approval of message wording by information governance.

## Human-only items

Collect these in the ledger as blocked tasks or in your progress note, with who must act and what you have prepared for them:

- A running Docker daemon, if the machine has none (back-end integration tests need it).
- Real Twilio, Entra and hosting credentials and any spend.
- Text provider sender number and terms; SNOMED and OS Places licences; the real Pathways Dx code list.
- Clinical safety officer: hazard severities, the safety case, sign-off of safety-critical rules and assumed thresholds (`[ASSUMED]`).
- Information governance: message wording, retention periods, whether staff notice or consent is needed.
- The owner: reconciling spec changes, going live, pushing and opening pull requests.

## When to stop and tell the owner

Rarely. Keep going unless you are blocked on everything. Tell them, briefly and once, when: every remaining task needs a human-only item; a decision you made contradicts a safety-relevant statement in the specs in a way they would want to know about; or the build reaches a stage gate (a short progress note: what is delivered, what evidence, what is blocked, what you decided). Do not ask for approval of things you are entitled to decide.
