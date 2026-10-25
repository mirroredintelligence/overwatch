# Decisions

Standing design decisions for the DIUCS capacity build. **Where a decision here disagrees with a task prompt in `docs/plan/prompts/` or with `docs/spec/`, the decision wins.** A task that a decision changes still has to be delivered as the decision says; note the difference in the task's evidence file.

To add a decision: append a new entry with the next number, commit it on the task branch that needs it, and publish a lesson pointing at it (`delivery.py lesson add`). Never edit an old entry's meaning. Supersede it with a new entry and mark the old one `Superseded by DEC-n`.

Authority behind these: the product owner delegated full design and implementation control, except that the build uses React (Next.js), Python, Twilio and Neo4j, and that all data of record is stored graph-native so that Neo4j Graph Data Science can be used in later phases.

---

## DEC-001 Graph-native storage is authoritative, with no JSON copy
Status: accepted · Affects: G02 to G05, P01 to P04, P13, P14, P17 to P21, anything that reads or writes resources.

Every piece of data of record lives in Neo4j as nodes, relationships and typed properties, as described in `docs/spec/fhir-data-model.md` (mapping rules R1 to R11). The spec's recommendation to keep a canonical `json` property on every node is **not followed**: two copies of one fact can disagree, which is a hazard in a clinical tool, and an opaque string cannot be projected into a graph for data science.

Rules:
- No node stores a serialised resource or a JSON string. No property holds a map or a list of maps. Lists of primitives are fine.
- Datetimes are Neo4j `datetime` values (UTC), dates are `date`, numbers are numbers, flags are booleans. Never strings.
- A reference is a relationship. A coded value is a relationship to a shared `Concept` node. Repeating backbone elements are child nodes. One relationship type has one direction and one meaning everywhere.
- The mapper (G02 to G04) must be lossless for every profile we publish: FHIR JSON to graph and back gives equal JSON after normalising key order and whitespace. An element the mapper cannot represent is rejected at validation (fail closed), never dropped.
- Test replacements: wherever a prompt says "the node's `json` equals the canonical resource", instead assert "the resource rebuilt from the graph equals the original", plus a schema test that fails if any property is a map, a JSON-looking string or a list of maps.
- Platform nodes (outbox, scheduled work, link tokens, credentials, sessions, aggregates) follow the same rules.
- Redis and any queue hold only transient data that can be lost without losing a fact (cache, counters, locks, live fan-out).

## DEC-002 Twilio is the SMS provider
Status: accepted · Affects: I06, I07, I16, configuration.

Twilio is fixed. Task I16 (GOV.UK Notify adapter) is cancelled and has been removed from `docs/plan/tasks.json`. Keep the `SmsSender` port. Tests never send real messages: use mocked HTTP and Twilio's test credentials and magic numbers. Real credentials are never committed.

## DEC-003 Infrastructure outside the four fixed technologies is a free choice
Status: accepted · Affects: F04, I01 to I05, I13, W09, O01 to O08, hosting.

Python, React (Next.js), Twilio and Neo4j are fixed. Everything else the specs name (Redis, Azure Service Bus, Entra ID, Azure Monitor, FastAPI, OpenTelemetry, the choice of UI libraries) is a default, not a mandate. Replace a default when it is blocking or when something simpler meets the requirement, and record the replacement here first. Before replacing anything, check that the replacement keeps these properties: durable scheduled work that survives a restart; at-least-once delivery with idempotent consumers; ordered events per service; no patient data in telemetry. Keep the choice reversible behind the existing port.

## DEC-004 Neo4j in Docker is the only store in tests
Status: accepted · Affects: every back-end task.

As in the "Testing and persistence" section of `docs/spec/contracts.md`. No in-memory repository, unit of work, audit log, outbox or token store.

## DEC-005 Quality standard: medical-device grade engineering
Status: accepted · Affects: every task.

The standard is in `.claude/skills/diucs-delivery/references/delivery-standard.md`. This is engineering rigour, not regulatory approval. Clinical safety sign-off, DPIA, DTAC and regulatory classification are human decisions and are tracked as human-required items, never claimed as done.

## DEC-006 Delivery process
Status: accepted · Affects: everyone.

One ledger (`.claude/skills/diucs-delivery/scripts/delivery.py`), trunk branch `main`, one branch per task named `task/<ID>-<slug>` in its own git worktree, test-first, independent verification by a different agent in a clean worktree, fast-forward merge to `main` only after verification passes. Nothing is pushed to a remote and no pull request is opened until the product owner asks.

## DEC-007 Working assumptions carried from the rule book
Status: accepted until changed · Affects: D-tasks, U-tasks.

Values marked `[ASSUMED]` in `docs/spec/domain-rules.md` (for example Limited at 80% used, the 15-minute correction window, 4-digit booking references) are in force. They are named constants. Changing one needs a new decision and a test update.

## DEC-008 Each test run gets its own throwaway Neo4j
Status: accepted · Affects: F04, F05, F10, and every integration test.

Several sessions run integration tests at the same time, and the harness wipes the graph before every test, so a Neo4j shared between runs would corrupt them. The harness (F10) therefore starts its own Neo4j container for each pytest session, on a random free port, with a unique container name, and removes it at the end (the `testcontainers` Neo4j module, or `docker run` with the same properties). `NEO4J_URI` can still point at a given instance for debugging. `infra/docker-compose.yml` is for people running the application locally, not for the test suite. CI does the same. Redis and the Service Bus emulator follow the same pattern when their contract tests need them. Where a prompt says "start `docker compose up -d neo4j` for tests", follow this decision instead. Until F10 is delivered, only one session at a time runs anything that needs Neo4j.

## DEC-009 Toolchain on a developer machine
Status: accepted · Affects: F01, F03, F05 and every task that runs checks.

The prompts assume Python 3.14 managed with `uv`. A machine may have neither. Installing local development tools is within your authority: `pip install uv`, then `uv python install 3.14`; `pnpm` and Node come with the machine or `corepack enable`. If Python 3.14 cannot be installed or a pinned dependency has no wheel for it, use the newest Python that works (3.12 or later), record the version in `pyproject.toml` and in a lesson, and avoid features newer than that version so the code runs on both. F01 and F03 pin and record the real versions found. Docker must be provided by a human; without a running daemon the Neo4j-dependent tasks are blocked.

## DEC-010 A red commit may hold a minimal stub so failures are assertions, not import errors
Status: accepted · Affects: every task whose tests import new names.

The red commit must hold tests only (delivery-standard.md, item 1), but a test that imports a name that does not exist fails with an ImportError, which proves nothing about behaviour. A red commit may therefore include the smallest stub that lets the tests import and run: a class or function with the right name and signature whose body raises NotImplementedError, or returns nothing. A stub must contain no behaviour. The evidence file states exactly which stub files the red commit holds, and the verifier checks that the red run fails on assertions, not on import errors. Re-cutting a red commit only to keep it test-only is not required.

## DEC-011 Allowlist for domain and application imports, enforced by a test
Status: accepted · Affects: F02, every task that adds domain or application code.

The prompt for F02 states the purity rules as allowlists: the domain imports only the standard library, `diucs.domain` and `fhir.resources`; the application imports only the domain and itself. import-linter's `forbidden` contract is a blacklist, so on its own it would let an unlisted package through. Decision:

- `backend/tests/architecture/test_import_rules.py` reads the direct imports of every file under `diucs/domain` and `diucs/application` (with `ast`, relative imports resolved) and fails on anything not on the allowlist.
- Domain allowlist: standard library, `diucs.domain`, `fhir.resources`. Pydantic reached only through `fhir.resources` is not a direct import and is not a violation.
- Application allowlist: standard library, `diucs.domain`, `diucs.application`. The standard library is included because the prompt itself requires `typing.Protocol` for ports; a literal "domain and itself only" would forbid it. `fhir.resources` is not allowed in the application: if a use case needs FHIR types it must go through the domain.
- The `.importlinter` blacklist contracts stay as well, so the import-linter output still names the broken contract for the forbidden cases.

Any change to these lists needs a new decision entry and a test update.

## DEC-012 Neo4j connections are owned, bounded, health-checked and recoverable
Status: accepted · Affects: G01, G14 (new), F10, P06, I03, I05, I08, R01 and every task that opens a session.

Connections to Neo4j must never go stale silently, and the system must recover fully when a connection drops, the server restarts or the network fails. These rules apply to every task that touches the driver.

Ownership and closing:
- One `AsyncDriver` per process, created once in the composition root (F08) and closed on shutdown. Never create a driver per request, per use case or per test.
- A session is short-lived and belongs to one unit of work (P06). It is always closed, with a context manager.
- A unit of work holds one explicit transaction. It commits on success and rolls back in a `finally` on any other path, so a failed operation never leaves a partial write.

Staleness prevention (values in settings, all `[ASSUMED]` until measured):
- `max_connection_lifetime`: 1800 s, so connections are recycled before the server or a middlebox drops them.
- `liveness_check_timeout`: 30 s, so an idle connection is verified before it is used.
- `connection_acquisition_timeout`: 30 s, so a dead pool fails fast with a clear error.
- `max_connection_pool_size`: bounded (default 50). Check the exact option names against the installed driver version and record them in evidence.

Health and startup:
- `verify_connectivity()` runs at startup. If Neo4j is unreachable the process refuses to start, with a message that names the URI host and port, but no credentials.
- A health function runs `RETURN 1` with a timeout and reports `ok` or `degraded`. It never crashes the process.

Recovery:
- Driver managed transactions (`execute_read` / `execute_write`) retry transient errors with backoff. Every write they retry must be idempotent, using the keys from P15.
- Background workers (outbox relay I03, scheduler consumer I05, reply processor I08) never exit on connection loss. They retry with capped exponential backoff and resume from durable state: the outbox `published` flag and the scheduled-work status. Nothing is lost, and at-least-once delivery with idempotent consumers means nothing is duplicated in effect.
- The driver is not recreated after an outage. The pool reconnects on next use, and health reports recovery.
- Connection logs carry no patient data and no credentials.

Proof: integration tests (G14) stop and restart the Neo4j container, assert that an in-flight operation fails with a retryable error and leaves no partial write, assert that operations succeed again after recovery within a stated time, and assert that closing the driver leaves zero open connections.

## DEC-015 Two design-system values that conflict with its own rules (X02)
Status: accepted (builder decision, owner to reconcile) · Affects: X02, every front-end task using `--dur-sheet` or `--type-caption-*`.

The design system (docs/design/design-system.md) contradicts itself in two places. X02 copies the token tables exactly and records the conflicts here rather than changing either value:

1. Motion. Section 5.2 says "UI motion is under 300 ms, except onboarding", but its table gives `--dur-sheet` 320 ms, for dialogs, sheets and drawers. Decision: `--dur-sheet` stays at 320 ms. It is the only UI duration above 300 ms, and the token tests (`tokens.test.ts`) pin that exception. `--dur-onboard` (480 ms) is the onboarding exception.
2. Type. Section 3 says anything under 16 px is forbidden, but its Caption role is 14 px. Decision: `--type-caption-size` stays at 14 px as tabled. Any caption use must be reviewed against the 16 px rule before it ships, and the owner decides whether the rule or the table changes. The root font size (16 px) and the body size (18 px) are unaffected.

Reduced motion (section 5.5) zeroes the movement durations: `--dur-press`, `--dur-tip`, `--dur-menu`, `--dur-sheet` and `--dur-onboard`. `--dur-state` keeps 240 ms. Opacity fades in those five roles are therefore instant under reduced motion, which the design system's "zero for movement tokens" rule implies. Owner may reverse this for onboarding if it loses meaning.

## DEC-014 Community Overwatch design system, motion rules and component library
Status: accepted · Affects: every front-end task (W*, F09, X02) and the copy on every screen.

1. The design system is `docs/design/design-system.md` (Community Overwatch). It is the source for colour, type, spacing, motion, status, components, voice and accessibility. Where the design canvas wording differs, the canvas wording wins for text, and the design system wins for everything else (including the "Dorset" wording, which is replaced by configured area names).
2. Motion is in scope and is governed by the gate and review checklist in the design system (section 5). Motion is rare on frequently used controls and absent on keyboard actions and on data. Reduced motion keeps meaning and drops movement.
3. Interactive primitives (dialogs, menus, selects, tabs, switches, toasts) come from React Aria Components. Visual components are ours, on the tokens in `frontend/app/tokens.css`.
4. Motion, spacing and type values are tokens. Components never hard-code durations, easing curves or spacing values.
5. The community and product name is "Community Overwatch". No copy names an area, service or telephone number; those come from configuration.
6. The skills reviewed for this decision are from emilkowalski/skills (MIT, read as summaries) and the taste-skill review. Their rules were paraphrased into the design system. Their files are not installed or executed.

## DEC-013 The harness owns its container and overrides NEO4J_URI for the session
Status: accepted · Affects: F10, G01 and F04 tests, every integration test. Clarifies DEC-008 and the F10 prompt, which disagree on NEO4J_URI.

Decision:
- Each pytest session that needs Neo4j starts its own container (`neo4j:5.26.32-community`, the image pinned in `infra/docker-compose.yml`), on a free localhost port, with a unique name and label, and removes it at the end. It uses the `docker` command directly, not testcontainers, so no dependency is added.
- The harness sets `NEO4J_URI`, `NEO4J_USER` and `NEO4J_PASSWORD` in the process environment for that session, so modules that read them (the G01 driver tests) reach only this container.
- A `NEO4J_URI` already in the environment is not used by the harness. A developer cannot point a wiping test run at diucs-local, or any other stack, by setting the variable. Debugging against a named instance is not supported by the harness.
- `clean_graph` wipes only the harness driver (`harness_driver`), never the name `neo4j_driver`, which a test module may override. `tests/integration/test_infra_up.py` (F04) keeps its own driver on the compose stack and is not wiped.
- Timing: the container must answer `cypher-shell` within 120 s, because a Neo4j container takes tens of seconds to start. The 5 s limit in the prompt applies to `connect_or_fail`, the connection check that follows.
- When Docker cannot start the container, the session fails at once with a message saying Docker could not start the Neo4j test container. It does not use the docker-compose start message, because that message points at the shared stack.

## DEC-016 Reply references are accepted as 3 to 8 digits, and matched exactly (D09)
- domain-rules.md (line 165) and DEC-007 generate 4-digit references. The D09 prompt accepts 3 to 8 digits, so the parser follows the prompt.
- Decision: the parser accepts the wider range so that references issued before the 4-digit rule are not rejected. Matching in D14 must be exact, never by prefix, so a short reference cannot match a longer one.
- Replies are recognised as ASCII only, after whitespace normalisation (D09). This fails safe against look-alike characters. It goes beyond the prompt and is accepted here.

## DEC-017 usual_range is one (minimum, maximum) tuple, not two fields
Status: accepted · Affects: D01 (`ServiceProfile`), D11 (`PromptState.usual_range` in the reply policy), and any task that stores or maps the profile.

`docs/spec/domain-rules.md` section 1.1 lists two profile fields, `usual_range_min` and `usual_range_max`. `docs/spec/contracts.md` (the `model/service.py` (D01) entry) and the D01 prompt define one field, `usual_range: tuple[int, int]`, and the prompt says it wins where the two differ.

Decision: `ServiceProfile.usual_range` is a single `tuple[int, int]` of (minimum, maximum). It is validated as a pair of whole numbers with 0 <= minimum <= maximum, and a failure raises `ValidationFailed("usual_range", ...)`. The two-field form in `domain-rules.md` 1.1 is not built. Nothing else changes: the range check meaning is the same, and the tuple cannot hold a minimum without a maximum.

Deviation: this differs from `domain-rules.md` 1.1 (the two-field form). The rule book is not edited here; the owner should update section 1.1 to match, or supersede this entry. Until then this entry governs.

## DEC-018 Keep the two defensive guards for a missing window start or end (D01)
Status: accepted · Affects: D01 (`AvailableTime.__post_init__`, the timed-window start and end checks).

`AvailableTime.__post_init__` raises `ValidationFailed("start", "a timed window needs a start time")` and the matching `end` message before it calls `_check_time`. The later `_check_time` call would also reject `None` with the same field name, so the earlier guards only make the message clearer. Removing them changes no field, no accepted value and no rejected value; it changes only the message text.

Decision: keep both guards. They are defensive and cost one line each, and the message names the missing time, which the owner or an engineer reading an error will need.

Test: `test_timed_window_missing_a_time_says_which_time_is_needed` (commit `48aa423`) pins both messages. Written after the implementation, not test-first. It passes on the current code, and it fails when either guard is removed (evidence entries G09 and G10 in `docs/delivery/evidence/D01.md`). So the guards are covered by a test that can fail.

## DEC-019 Resolve the design-system conflicts from DEC-015 in favour of the stricter rule (X02)
Status: accepted · Affects: X02 (`frontend/app/tokens.css`, `tokens.test.ts`), every component that uses the sheet, caption or reduced-motion tokens. Decided by the orchestrator on the owner's standing instruction to decide open items.

Three values in `docs/design/design-system.md` conflict with its own rules. The device is used by advisors under time pressure and by people with reduced vision, so the stricter rule wins:

- **Sheet duration.** `--dur-sheet` becomes **280 ms** (was 320 ms). Section 5.2 says UI motion is under 300 ms; 280 ms keeps the sheet inside that limit.
- **Caption size.** `--type-caption-size` becomes **16px** (was 14px). Section 3 says nothing is below 16 px.
- **Reduced motion.** Opacity fades keep their own durations, as section 5.5 requires ("keep opacity"). Only movement tokens (press, tip, menu, sheet, onboard) are set to zero. `--dur-state` already keeps its duration.

The design-system document is not edited; it is a shared source. The owner should reconcile it with these values.

Follow-up: task X03 applies these values test-first, with `tokens.test.ts` updated to expect them.

## DEC-020 next_opening counts a window start only where the service was closed just before (D03)
Status: accepted · Affects: D03 (`next_opening`), and any task that shows or schedules the next opening (D04 due times, D07 out-of-hours status).

The D03 prompt says "the next moment strictly after now when a window starts". Read literally, that makes two cases wrong. An all-day window starts at 00:00 each day, so an every-day all-day service would report midnight, which the prompt says must be None. Two adjacent windows (08:00 to 12:00, then 12:00 to 20:00) would report 12:00 as an opening, though the service never closes.

Decision: an opening is a window start at instant s, with s after now and within 8 days, where the instant just before s (s minus one microsecond) is not in hours. All-day windows follow the same rule. An all-day service that is open every day never opens (None). A Monday-only all-day service opens at Monday 00:00 London.

Deviation: this reads "a window starts" as "the service opens". The prompt's own None rule for all-day services requires it. Covered by tests in tests/unit/domain/rules/test_opening_hours.py (adjacent windows, all-day every day, all-day Monday).

## DEC-021 Task.statusReason carries only expired and withdrawn in the booking state mapping (D13)
Status: accepted · Affects: D13, the booking mapper (G02 to G05, P02), the booking tasks that record decline, cancel and withdraw reasons.

The sources disagree. `domain-rules.md` 3.1 gives statusReason only for Expired (`expired`) and Withdrawn (`withdrawn`). `fhir-data-model.md` line 238 says the STATUS_REASON edge carries "Expired, withdrawn, and reasons from the decline, cancel and withdraw code systems". Decline, cancel and withdraw reasons are not in the state table.

Decision: follow `domain-rules.md` 3.1. `booking_state.to_fhir` sets `status_reason` only for `expired` and `withdrawn`. Decline, cancel and withdraw reason codes are not written into `Task.statusReason` by the state mapping. They are carried as the reason Concept on the decision output (the `OUTPUT` edge, fhir-data-model.md 229 to 241) by the mapper and the booking tasks. The owner should reconcile line 238 with the rule book. Tests: `test_to_fhir_follows_the_spec_table`.

## DEC-022 A lettered reply returns one item per service; the D09 single-item invariant is narrowed (D10)
Status: accepted · Affects: D10 (`reply_parser.parse_reply`), D11 and later reply consumers, `test_reply_parser.py`.

`parse_reply` returns a tuple. A single-service reply still returns one item. A lettered reply (`Y A`, `A 4`, `A 4, B 2`) returns one item per service, in the order written, and is either all items or one `Unrecognised`. The D09 property test asserted `len(replies) == 1` for every text, which is wrong for lettered input. The test now checks each item, requires one item only when the reply is `Unrecognised`, and checks that letters are in `SERVICE_LETTERS` and not repeated.

Consumers must iterate the tuple and must never assume one item. Commas separate items only, so `A,4` is refused. A message takes the lettered path only when it contains a service letter token, so D09 replies are unchanged.

Evidence: `docs/delivery/evidence/D10.md`.

## DEC-025 Report flag windows and the phoned comparison (D12)
Status: accepted · Affects: D12 (`rules/report_flags.py`), and U07 and W42 where flags are saved and shown.

`docs/spec/domain-rules.md` 2.3 gives the two report flags with [ASSUMED] windows. D12 decides three points the rule book leaves open:

1. **Edges are inclusive.** A report exactly 5 minutes before the new one counts towards `many-changes`, and one exactly 60 minutes before counts towards `differs-from-phoned`. Only reports strictly outside the window are ignored.
2. **Any phoned figure in the window can trigger `differs-from-phoned`.** If two advisor-phoned figures fall in the previous 60 minutes and either differs from the new text figure, the flag is raised, even when the later phoned figure matches. This is the literal reading of 2.3 ("differs from an advisor-phoned figure") and the safer direction: the lead checks by phone. The alternative (compare only with the latest phoned figure) is not built; the owner may choose it.
3. **Time is measured between instants, in UTC.** Every datetime is converted to UTC before it is compared or subtracted. Two London-zoned datetimes share one tzinfo object (ZoneInfo is cached), so Python subtracts and compares their wall-clock fields: 00:58 GMT to 02:02 BST reads as 1h04, not 4 minutes, and a fold=1 time sorts before a fold=0 time it follows. Found after the verifier passed b5dba5a: a DST defect, not a boundary defect. The 2026-03-29 and 2026-10-25 changes are tested with London-zoned pairs in `test_report_flags.py`. Lesson L4 applies here as well as to schedules.

Reports for other services, and reports later than the new one, are ignored. A report in `recent` with the same id as the new report is counted once.

Evidence: `docs/delivery/evidence/D12.md`. Tests: `backend/tests/unit/domain/rules/test_report_flags.py`.

## DEC-023 current_due looks back up to 8 days, not only today and yesterday (D04)
Status: accepted · Affects: D04 (`current_due`), and every consumer of "was due" (D05 reports, D07 board, 1.5 overdue).

- The D04 prompt says `current_due` looks at today's and yesterday's due lists. A service that is due only on weekdays, with its last due time on Friday 19:00, would then have no current due time on Sunday or before 08:00 on Monday. The overdue rule in domain-rules 1.5 would lose the missed Friday report, and the board would show the service without "was due". That is the wrong answer for a patient-facing display.
- Decision: `current_due` searches back over the same 8-day window as `next_due`, and returns the latest due time at or before `now`. Any valid profile has a due time within 7 days, so the result is never None for a valid profile.
- Tests: `test_current_due_on_monday_morning_finds_friday_evening` and the weekend cases in `backend/tests/unit/domain/rules/test_schedule.py`.

## DEC-024 Twice-a-day 14:00 is due unless the service opens after 14:00 (D04)
Status: accepted · Affects: D04 (`due_times_on` for `twice-a-day`), D05 (reports due), D07 (board overdue), and any task that shows a due time.

- domain-rules 1.4 says: due at the opening time and at 14:00, and "if the service opens after 14:00, only the opening time". That is the only exception in the rule book.
- The D04 prompt added a second exception: "or closes at or before 14:00". The rule book has no such exception. The prompt also tested the opening after 14:00 only.
- Decision: follow the rule book. 14:00 is due whenever the window opens at or before 14:00, including windows that end at or before 14:00 and overnight windows that are open across 14:00 (for example 10:00 to 06:00). The 14:00 due is not kept only when the opening is after 14:00.
- Reading the rule book this way gives a due at 14:00 for a window that ends at 12:00 (the service is closed at 14:00). This is the cost of the rule book's wording. Missing a due is worse than an extra one. If the owner wants the closed case removed, that is a rule-book change, not a code change.
- Tests: `test_twice_a_day_*` in `backend/tests/unit/domain/rules/test_schedule.py`, and the property `test_twice_a_day_has_1400_exactly_when_the_window_does_not_open_after_it`.
- The number is DEC-024 on this branch. The orchestrator may renumber at delivery, since DEC-023 is also taken on another branch.

## DEC-026 Lint waiver for the D14 red test file (E501, SIM300)
Status: accepted · Affects: `backend/pyproject.toml` (per-file ignores), `backend/tests/unit/domain/rules/test_booking_rules.py`.

The D14 red test file is kept byte-identical to its red commit, so the test-first record stays honest. Two rules that the file breaks (E501 line length, SIM300 Yoda comparisons) are waived for that one path only. Nothing else is waived.

Condition: remove the waiver in the same change that next edits the red file legitimately, and say so in that change's evidence. Reviewed by the D14 verifier (`verify-D14c`).

## DEC-028 Postcode whitespace is any whitespace, input is ASCII only, and districts are never de-spaced (D19)
Status: accepted · Affects: `backend/src/diucs/domain/rules/postcode.py`, `backend/tests/unit/domain/rules/test_postcode.py`.

The prompt says to remove all spaces before normalising a postcode, but does not say what counts as a space. A no-break space (U+00A0, pasted from web pages) is treated as a space, so "SS1 1AA" with one is accepted. Any other non-ASCII character is refused rather than upper-cased into ASCII ('ß' becomes 'SS' and would otherwise form a valid-looking outward code).

A district is only trimmed at its ends, never de-spaced. "DT4 8" is therefore refused, not read as the district "DT48". Only a full postcode has its internal spacing removed.

Consequence: none of the normalisers or `postcode_district` ever put the input into an error message or log line. `ValidationFailed` carries a fixed message.

Reviewer: the D19 verifier. Owner to confirm the whitespace rule when IG reviews the advisor input.

## DEC-029 No report ever: the prompt's "not overdue before the first due" conflicts with the rule book (D05)
Status: accepted, owner to confirm · Affects: D05 (`assess_freshness`, `test_no_report_ever_before_monday_first_due_is_overdue_from_friday`), D07 (board overdue for a service that has never reported), and the owner's reading of domain-rules 1.5.

- D05 prompt test 7 says: no report ever, now Monday 06:30Z, before the first due, so not overdue. Test 6 says: no report ever, now Monday 07:31Z, so overdue. Between those two instants no due time falls, and the last due before them is Friday 19:00Z, whose reply-by passed on Friday. A rule built on due times and reply-by cannot make 06:30Z not overdue and 07:31Z overdue. Only a rule that uses the clock-time of day or a service start date could, and the profile holds neither.
- domain-rules 1.5 says a service is overdue when any due time since its last report has passed its reply-by. With no report ever, every due time in the look-back is "since its last report". So the rule book gives overdue at 06:30Z Monday.
- Decision: follow the rule book and the fail-safe principle (delivery-standard principle 1). Overdue is true, `was_due` is Friday 19:00Z, `age` is None. The board already shows Not updated for a service with no figure, so the visible result does not change. Test 7 is written with this expectation, and the prompt's expectation is not met.
- Owner: confirm this, or say which instant a service's reporting started, so a "not before first due" rule can be designed with the registration date (D13 / P-tasks), which is not in the profile today.

## DEC-030 freshness conventions not stated in the prompt (D05)
- `stale_warning` is False when there is no report at all: the warning is about the age of a figure, and there is no figure. The board shows Not updated for that case.
- A report later than `now` raises ValueError, and a naive datetime raises ValueError. A clock error must not be shown as a fresh figure.
- `was_due` is found with `current_due` only (lesson L30): the latest due at or before `now - REPLY_WINDOW`. Missed means reply-by before `now`, strictly (a due whose reply-by equals now is not yet missed).
- A report at exactly a due time answers that due (the prompt's "at or after").

## DEC-031 Reply policy choices the rule book leaves open (D11)
Status: accepted · Affects: D11 (`rules/reply_policy.py`), U05 and any use case that acts on its decisions, D14 and U22 where a Y follows a late number.

`docs/spec/domain-rules.md` 2.2 does not say these things. Numbered DEC-031 because DEC-027 and DEC-028 are taken (DEC-028 on main by D19, DEC-027 on task/D05-freshness) and DEC-029 and DEC-030 are on task/D05-freshness. The decisions are:

1. **A Y is never a correction.** A Y is judged only against an open prompt. A Y after the prompt has closed is `RejectLate`, even inside the 15-minute correction window. The window applies to figures only.
2. **Correction takes precedence over an open prompt.** A figure inside the correction window is a correction (`is_correction=True`) whether or not the prompt is open. The prompt-open case with a recent report is the one the prompt's test 7 describes.
3. **The correction window is a decision, not a rule-book value.** `domain-rules.md` 2.2 gives a 15-minute window marked [ASSUMED] and does not define its edges. This entry fixes them: the window is inclusive at both ends, and an accepted report stamped after `now` is not a correction (elapsed must be zero or more). The same applies to the 30-minute reply-by window, which comes from `schedule.REPLY_WINDOW`.
4. **Instants, not wall-clock times.** Every datetime is converted to UTC before it is compared or subtracted, because two London-zoned datetimes with the same tzinfo subtract by wall clock and give wrong answers across the 2026-10-25 change (lesson L4).
5. **A late figure is refused before its range is checked.** An out-of-range number that arrives late gets `RejectLate`, not `AskRecheck`. The value is not used either way.
6. **A repeated out-of-range figure inside the correction window** is recorded as a correction with flag `out-of-range-twice`. The rule book's flag rule covers the open window and the correction window alike.
7. **A naive datetime (no UTC offset) for `now`, `reply_by` or `last_accepted_at` raises `ValidationFailed`.** The policy fails closed rather than reading the machine's local time.
8. **A reply must name this prompt's service.** A letter other than the prompt's letter, a letter on a single-service prompt, or a bare figure on a lettered prompt raises `ValidationFailed`. The check runs first, before any timing rule. The policy does not rely on the caller to check letters. A bare Y on a lettered prompt confirms the prompt (domain-rules 2.1).

Caller contract (lesson L27): use cases loop over every item of `parse_reply`'s tuple and call the policy once per item.

Tests: `backend/tests/unit/domain/rules/test_reply_policy.py`. Evidence: `docs/delivery/evidence/D11.md`.

## DEC-032 Approval gate is pure booleans; the approver-differs check lives in the use case (D22)
Status: accepted · Affects: D22 (`rules/registration.py`), U28 and any use case that approves a registration, ApproveRegistration, ApproveCriteria.

`domain-rules.md` 6.2 says Approve needs four checks, and 6.1 says the shift lead and the clinical lead approve in review. The criteria control in `ui-screens.md` (ApprovalStates, F7 and F11) says the criteria owner and a clinical lead both approve. None of these is an identity check inside the registration rule itself, and the D22 prompt fixes `ApprovalChecks` as four booleans and a scope flag, with no actor.

Decision:
- `approve_registration` checks state (only `in-review` may approve) and then the four checks. It does not and cannot check who approved.
- The approver-differs rule (the requester of a criteria change may not be its second approver; the shift lead and the clinical lead are two different people where 6.1 names both) is enforced by the use case that holds the actor, using `Actor` from `application/actor.py`. It must refuse with `NotAllowed` before calling `approve_registration`, and must have its own integration test against the real Neo4j adapters.
- Fail closed: `missing_for_approval` treats anything other than the exact passing value as missing.

Not decided here: whether a registration approval (not criteria) needs two distinct people. The rule book names two approvers in 6.1 but gives no separate second-approval rule for registrations. The owner should confirm. Until then the use case must require two distinct actors if it records both approvals.

## DEC-033 Figures for occupied-patients, and refused reports in compute_status (D07)
Status: accepted · Affects: D07 (`rules/status.py`) and every caller of `compute_status` (U08 board read model, U-tasks that show a service state).

domain-rules 1.2 and 1.3 give the status rule but not the figures a service shows. Decided here:

1. For occupied-patients, `effective_available` is None: there is no free count for occupancy, and `availability.effective_available` refuses that measure. `used` is the effective occupied count (the report plus bookings confirmed since it, see `effective_occupied`). `over_by` is `occupied − established` when occupied is above established, otherwise None.
2. For free-count measures, `used` is `max(0, established − effective_available)`, so an over-reported figure never shows a negative used count.
3. Figures are filled whenever a latest report exists, including for not-updated and out-of-hours, so the board can show the last known figure (prompt, D07 "Numbers are filled in"). With no report they are None.
4. Occupancy status: occupied above established is over-capacity whether or not the service can exceed; occupied equal to established is limited when it can exceed, otherwise not-accepting; otherwise the used share (occupied × 100 ≥ limited_level_percent × established) decides limited or accepting.
5. `compute_status` raises ValueError for a report from another service or with another measure than the profile. A figure that reaches the wrong profile would be a confident wrong answer (delivery-standard principle 1). Tested.
6. A naive `now` or a report after `now` is refused by `assess_freshness` (DEC-030).

All integer arithmetic. Instants are compared as UTC (lesson L4).

## DEC-034 Message template and SMS length choices the prompt leaves open (D15)
Status: accepted · Affects: D15 (`domain/messages/templates.py`, `sms_length.py`), U01 to U06 and any use case that renders a capacity message.

Numbered DEC-034 because DEC-032 is taken on main (D22) and DEC-033 on task/D07-service-status.

`docs/spec/domain-rules.md` section 9 and the D15 prompt give the wording but not these choices:

1. **Accepted fields per id, required fields per channel.** A caller may pass any field listed for the id in `docs/spec/contracts.md` (for example a push C1 also accepts `as_of` and `link`). A field is required only when the channel's template uses it, so a push C1 needs `service`, `value`, `unit` and `reply_by`. A name outside the id's list raises `ValidationFailed` (the extra-field rule in the prompt).
2. **Channels per id.** C1, C2 and C8 render on text, email and push. C3 to C7, C9 to C11 render on text only. Any other channel raises `ValidationFailed`.
3. **Email bodies (OWNER SIGN-OFF PENDING, NOT APPROVED, not IG-approved).** The subject is `{service}: confirm or update by {reply_by}`. The text body is the id's text wording, plus the footer line from the prompt. C1 and C8 already carry the link in their text. C2 has no link in its text, so its email body adds the line `Confirm or update: {link}`. The HTML body repeats the wording, with the link as a button-style anchor. Every field value is HTML-escaped in the HTML body and left as written in the text body.
4. **Push C8 text (OWNER SIGN-OFF PENDING, NOT APPROVED, not IG-approved).** is not given in the spec (C8 has no value). It reads `{service} has not updated. Reply by {reply_by}.`
5. **C9 needs at least two items** (the wording says "2 services" and "both"). One item raises `ValidationFailed`. Three or more items use "all". The reply examples always use the first two items, with value plus 1, as the prompt says.
6. **C10 with no updated and no waiting items** raises `ValidationFailed`. Updated items come first, then waiting items, in the order given.
7. **SMS length.** The extension set is exactly the prompt's `^{}\[~]|` and the euro sign, plus form feed, which GSM 03.38 also places in its extension table. Any other character outside GSM-7, including a non-BMP character, switches the message to UCS-2. Length is counted in UTF-16 code units. An empty text is one segment. A concatenated UCS-2 message holds 67 units per segment.

8. **C2 takes `window` as its own field.** The rule book sample is "How many referrals can you take in the next 2 hrs?" (ui-screens.md line 1002, domain-rules section 9). The unit alone cannot give that order, so C2 takes `unit` ("referrals") and `window` ("in the next 2 hrs"). contracts.md is updated and lesson L46 published. The screen at line 1011 ("in the next 2 hours") is the same template with another window.
9. **Screen texts with no template (open, owner decision).** ui-screens.md line 963 is C1 without the link ("Reply Y if right, or send the new number (0 = closed). By 12:30."). Line 970 is a correction echo ("Thanks. UCR West: updated to 4 referrals, as of 14:10."). Line 3360 is an echo after Y for a lettered prompt ("Thanks. A) UCR West 3 confirmed. Next prompt 12:00."). None of them is a catalogue id, so none is built. The owner decides whether to add ids or to align the screens with C1, C4 and C10.

Tests: `backend/tests/unit/domain/messages/`. The DEC-034 choices 1, 5 and 7 are asserted there. Choices 3 and 4 are the owner's to approve: the prompt says the per-measure C2 phrasing is still awaiting IG approval.

## DEC-035 The criteria filter fails closed on unknown codes, and matches enums by exact type (D20)
Status: accepted · Affects: D20 (`rules/criteria_filter.py`, `model/criteria.py`), D21, D22, U12 and any task that checks a need, age band or criteria status.

domain-rules 4.1 and the D20 prompt say what passes and what fails for known values. They are silent on values that are not codes at all. Decision:

- A need that is not a `NeedCategory` member excludes the service with the fixed reason `Need not recognised`. A plain string with a code's value, or a member of another enum with the same value (for example a `StrEnum` member `frailty` from a different class), is not a need. It is never accepted.
- An age band that is not an `AgeBand` member, including `None`, excludes the service with `Age not recognised`.
- The status gate uses `is not CriteriaStatus.CURRENT`, so only the current version passes.
- `ServiceCriteria` refuses at construction any `accepts` or `excludes` value that is not a `NeedCategory` member, any status that is not a `CriteriaStatus` member, and any district that `normalise_district` would not return unchanged (so `dt4`, `DT4 8` and the empty string are refused, D19 rule).
- Reasons never echo the case value. An unknown need gives one `Need not recognised` reason, without its text.

- A `None` criteria raises `ValidationFailed("criteria", ...)`, and `None` needs (or any non-iterable needs) raises `ValidationFailed("needs", ...)`. These are caller errors, not services to exclude, so the filter refuses them by field name rather than raising `AttributeError` or `TypeError`. The caller must handle a missing criteria version before calling the filter.
- Active and suspended are not checked by the filter. domain-rules 4.1 lists "active, not suspended, and has a `current` criteria version". The D20 prompt lists only the criteria status, district, needs and age, and its out-of-scope list defers graph queries to G11. The split is intentional: G11 (`candidates`) excludes services with `active: false` and services with an active `ServiceFlag` code `suspended` (G11 prompt, lines 59 to 79), and U12 lists suspended services under "not suitable" (U12 prompt, line 49). The filter is only ever called on candidates from G11, so a suspended service never reaches it. Enforcing the check in the filter as well would duplicate the source of truth (delivery-standard principle 5). Owner to confirm.

Reason order is fixed: status, district, excluded needs, needs not accepted, age. Unknown needs come first in the need phase.

Deviation: the reasons `Need not recognised` and `Age not recognised` are new text, not in the rule book. They are the fail-closed form of the rule book's "excluded" outcome for values the rule book does not list. Owner may reword them.

Tests: `backend/tests/unit/domain/rules/test_criteria_filter.py` (`test_an_unrecognised_need...`, `test_a_need_from_another_enum...`, `test_an_unrecognised_age_band...`) and `backend/tests/unit/domain/model/test_criteria.py` (`test_a_need_from_another_enum...`, `test_districts_must_be_upper_case_outward_codes`).

## DEC-038 Criteria workflow: calendar dates, approval guards and version status (D21)
Status: accepted, owner to confirm · Affects: D21 (`rules/criteria_workflow.py`), U30 (`ApproveCriteria`), U31 (criteria review reminders and the `criteria-overdue` flag).

domain-rules 4.2 and the D21 prompt fix the transitions, the review-by arithmetic and the reminder window. They are silent on the points below. Decision:

- **Dates are calendar dates, the London day.** `is_review_overdue`, `review_reminder_due` and `next_review_by` refuse a `datetime` (`ValidationFailed`), because a `datetime` is a `date` and an instant could pass as a day. The caller derives the day with `london_time.to_london(instant).date()` (lesson L4).
- **Enums are checked as members.** `transition_criteria` refuses any value that is not a `CriteriaStatus` member, including a member of another enum with the same value (lessons L3, L38). It raises `ValidationFailed`, not `InvalidTransition`, because that is a caller error.
- **Months are an exact int of 3, 6 or 12.** `True` and `6.0` are refused.
- **`approve` checks the pending version's status through the transition table.** Only `pending-approval` can become `current`; any other status raises `InvalidTransition`.
- **`approve` refuses a pending version of another service** (`ValidationFailed("service_id")`). The prompt does not list this check. Without it, a version of one service could supersede another service's current version.
- **`approve` with no current version applies no version or `supersedes_id` check.** The prompt applies those checks only "when there is a current one". A service whose earlier version was retired may therefore be approved at any version number. The use case (U30) decides whether that is allowed.
- **The current version must be `current` to be superseded.** `approve` calls the transition table for the old version, so a superseded or retired current version raises `InvalidTransition`.
- **Reminder and overdue do not look at the version's status.** `is_review_overdue` is `today > review_by` for any version, as the prompt states. The caller (U31) checks only the current version for the service flag and reminders. A superseded version with a past review-by is therefore "overdue" to this function, and U31 must not read it. Owner to confirm.

Tests: `backend/tests/unit/domain/rules/test_criteria_workflow.py` (64 tests: every transition pair, reminder and overdue boundaries, clamping, and property tests with Hypothesis). Branch coverage of the module is 100%.

## DEC-039 Clinical queue choices the prompt leaves open (D23)
Status: accepted · Affects: U40 (clinical advice use case and 10-minute timer), W44 (advisor screens), any caller of `rules/clinical_queue.py`.

The D23 prompt and domain-rules section 5 leave these points open. They are decided here and tested in `backend/tests/unit/domain/rules/test_clinical_queue.py`.

1. **A lapsed lock refuses advice.** `give_advice` raises `NotAllowed` once the taker's lock is ten minutes old, even when nobody else has taken the request yet. The taker must take it again. Advice under a lapsed lock could race another advisor who has been shown the request.
2. **Re-taking while still locked keeps the original lock.** The same clinician taking a live lock again returns the request unchanged. Only an idle lock is renewed, and only then does `taken_at` move.
3. **Presence is counted only when it is a `Presence` member.** A plain string with the same value, or `None`, is not counted, so an unknown presence under-counts. This follows DEC-035 (fail closed, enums matched by exact type).
4. **Advice is shown as available only when both inputs are known.** `advice_shown_as_available(available, queue_known)` is true only when `available` is an `int` above zero and the queue is known. `None`, zero, a `bool` or an unknown queue all mean advice is not shown as available. The name is added to `docs/spec/contracts.md`.
5. **Constructors validate.** Urgency is `now` or `within-15-min`. `taken_by` and `taken_at` are set together. An advised request has a taker. Every instant must be timezone-aware and is compared in UTC. A blank clinician id is refused.
6. **`release_for_away` returns only the released copies.** The caller merges them back into its list.
7. **Instants are compared in UTC.** Same-zone aware datetimes (for example `ZoneInfo("Europe/London")`) subtract on wall-clock time, so a lock taken at 01:50 BST and checked at 01:55 GMT on 2026-10-25 would look five minutes old. Every instant is converted with `astimezone(UTC)` before any comparison or subtraction. Tests cover both clock-change dates.
8. **Open gap for U40.** `queue_order` keeps the contract signature (no `now`). It leaves out any request that is still locked, including one whose lock is already idle. U40 must run `return_if_idle` on each request before it calls `queue_order`, on every read and on the timer. Otherwise a request stays hidden from the queue until someone runs the timer. Published as a lesson.

## DEC-040 System pressure counts Status members only, and refuses anything else (D08)
Status: accepted · Affects: D08 (`rules/pressure.py`) and every caller of `system_pressure`, `all_limited_or_worse` or `limited_or_worse_count` (D24 pressure alert, U08 board read model, W07 banner, W40 exec home).

domain-rules 1.7 gives the thresholds, the banner rule and the exclusions, but not what a caller may pass. Decision:

- Each element must be exactly a `Status` member (`type(x) is Status`). A plain string with a status value (for example `"limited"`), or a member of another enum with the same value, raises `TypeError` before anything is counted. Lesson L3 and L44 show the same mistake in the other direction, so the count fails closed rather than under-counting a service the caller meant to include.
- Each function reads its input once, so a generator is accepted and gives the same answer as a list.
- In-hours means not `out-of-hours`. The banner needs at least one in-hours service, so an empty or all-out-of-hours board shows no banner.
- `not-updated` is unknown: it does not count towards pressure and it stops the banner, as 1.7 requires.

Tests: `backend/tests/unit/domain/rules/test_pressure.py`, in particular `test_plain_strings_and_other_enums_are_refused` and the `test_iterables_are_read_once...` test.
