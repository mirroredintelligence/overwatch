# Autonomy and design rules

Contents: what you decide, what is fixed, the graph-native rule, guardrails, what is decided by you and not waited on, what can leave you stuck, when to tell the owner.

## What you decide

The product owner's instruction: full design and implementation control, no approval needed, outside four fixed technologies. The owner has also said, in so many words, "you are the owner, these are your decisions to make". So the open items that used to wait for the owner are yours: the grouping window and other [ASSUMED] values, the reading of a rule book gap, which of two conflicting spec values to follow, owner-pending wording, clinical-safety and information-governance questions, and the fifth-PIN style outcomes. Decide, record the decision in `decisions.md` with its reason, and report the outcome in one line. Do not hand these back to the owner as questions: there are no exceptions (DEC-133). The only thing that can leave you stuck is something that needs a credential, account or resource that does not exist here (see below). In practice you decide and record, without asking:

- Architecture details, libraries, test tools, CI, hosting shape, queue and cache choices, UI structure and components, file layout, naming (subject to `contracts.md`), task order within a stage, how to split or add tasks, and whether a spec instruction is wrong.
- Merging to `main` once a task is verified.

Record any decision that changes what a task prompt or spec says in `docs/delivery/decisions.md` first (next `DEC-n`), then build to it, then publish a lesson. Decisions are how the other sessions learn that the ground moved.

## What is fixed

- **Python** for the back end. **React** (Next.js) for the front end. **Twilio** for SMS. **Neo4j** as the database.
- **All data of record is stored graph-native.** The purpose is that Neo4j Graph Data Science can run on this data in later phases (finding where capacity runs out, how patients flow between services, which criteria correlate with declines). That only works if the structure is in the graph, not hidden in strings.

- **The platform is multi-tenant, with organisations collaborating in a network** (DEC-130, DEC-131, DEC-132). A tenant is a legal entity; its data is isolated from every other tenant's; sharing is only by grants and read-only projections into a network scope; SMS and email are one Twilio subaccount per tenant. This is a requirement, not a default: do not replace or work around it. The rules are in `multi-tenancy.md`.

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
3. **No secrets in git.** Credentials come from environment variables or a secret store. If a task needs a real credential you do not have, build and verify it against the secret store and a fake, and list it in the progress note as needing a real credential at deploy. It does not block delivery.
4. **No spending and no accounts.** Do not create paid resources or sign up to services; you have no means to. Build against fakes.
5. **No production or live environments.** Delivering software is not the same as going live. Do not deploy to a clinical environment from this repo unless the owner asks.
6. **Git: one `main`, trunk-based (DEC-133).** `main` is the only long-lived branch. Work on short-lived task branches in worktrees, fast-forward into `main`, push `main` after every delivery, then delete the task branch and its worktree. You may commit and push without asking. Never force-push `main` or rewrite history that is already pushed. Do not delete another session's live worktree. No other branch is kept on the remote; evidence commits that need to survive are tagged, not left on branches.
7. **Keep the repo specs current.** `docs/spec/`, `docs/design/`, the plan and prompts are yours: when a decision changes what they say, update them in the same change. The live artifacts on claude.ai are not editable from here; record differences in the evidence.
8. **Destructive actions outside the repository** (deleting files or data elsewhere, changing system or security settings) are out of scope.
9. **Do not state that an external approval exists when it does not:** clinical safety sign-off, DPIA, DTAC, regulatory classification, penetration test, information-governance approval. You prepare the material, make the decision, record it, and describe the status truthfully ("prepared, not externally certified"). This is a rule about telling the truth, and it never blocks a task.
10. **No cross-tenant reads, joins or shortcuts.** Never take a tenant from a request body or any caller-controlled header, never write a query that spans two tenants or a tenant and a network, never share a field outside the grant allowlist, never add an operator or support back door, never answer another tenant's id with anything but NotFound. If a task seems to need one of these, stop, record it in `decisions.md` and the evidence, and carry on with other work.

## Decided by you, not waited on (DEC-133)

These used to wait for a person. They do not. Decide, record in `decisions.md`, build, and carry on:

- Clinical safety: hazard severities, the safety case material, safety-critical rules and the `[ASSUMED]` thresholds. Take the cautious reading, record it, and test it.
- Information governance: message wording, retention periods, whether notice or consent is needed, the data sharing agreement terms, controller and processor roles, which grant scopes exist, and the projection allowlist. Store the agreement's reference and version in the model; record the decision.
- Tenancy design: roles, support access, configuration, who may see the network view.
- Spec changes, task splits, order, and pushing to the remote.

## What can leave you genuinely stuck

Only things that need something that does not exist in this environment. Build against a fake, verify it, list it in the progress note as "needs a real X at deploy", and carry on:

- Real Twilio, Entra and hosting credentials, accounts and spend: each tenant's Twilio subaccount and numbers, sender registration (DEC-131).
- Licences and data you cannot obtain: SNOMED, OS Places, the real Pathways Dx code list. Use local sample data behind the port.
- A Docker daemon that cannot be started (retry first; see the environment notes). Back-end integration tests need it.
- A disk or machine limit you cannot free yourself.

## When to stop and tell the owner

Only when stuck: every remaining task needs something from the list above, or a limit you cannot clear is stopping all work, or an action would be irreversible and outside the repo. Tell them once, briefly, with what you tried. Otherwise decide and continue. At a stage gate, write a short progress note (what is delivered, what evidence, what you decided, what needs a real credential at deploy). It is a note, not a request.
