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

## DEC-037 Booking, invitation, code and alert message choices the prompt leaves open (D16)
Status: accepted · Affects: D16 (`domain/messages/templates.py`), D17, U01 to U06, U17 to U24 and any use case that sends a B, I, K message.

Numbered DEC-037: DEC-036 is taken on task/D08-system-pressure, task/D21-criteria-workflow and task/D23-clinical-queue (lesson L43). Check again before merge.

`docs/spec/domain-rules.md` section 9 gives the wording of B1, B4, B5, I1 and the id list, and the D16 prompt gives the rest. The prompt's own choices, and the ones it leaves open, are:

1. **Fields per id.** B1 and B2 take `reference`, `service`, `age_band`, `need`, `urgency`, `link`, `reply_by`. B3 takes `reference`, `service`, `reply_by`. B4 takes `reference`, `service`, `confirmed_at`. B5 takes `reference`. B6 takes `reference`, `cancelled_at`. B7 takes `references`. I1 takes `service`, `link`. I2 takes `link`. I3 takes `service`. K1 takes `code`. K2 takes `service`, `review_by`. K3 takes `title`, `body`. K4 takes `service`. The rule of DEC-034 item 1 applies: a name outside the id's list raises `ValidationFailed`.
B6 uses the screen text, not the prompt's form. The prompt gives "DIUCS: booking {reference} was cancelled by the SPOA at {cancelled_at}. No action needed." (marked [ASSUMED]). ui-screens.md line 1276 gives "Booking 4821 was cancelled at 14:40. No action needed." The screen text is used because it is the approved screen wording and the prompt's B6 is [ASSUMED]. Owner decision needed: confirm the screen form for the SMS, or restore the prompt's form, which names the SPOA.
2. **Channels per id.** B1, B4, B5, B6, B7, I1, I2, I3, K1 and K4 render on text. B2 renders on email only. B3 renders on push only. K2 renders on email and push. K3 renders on push only. Any other channel raises `ValidationFailed`.
3. **Not yet IG-approved (same status as DEC-034 items 3 and 4).** domain-rules section 9 says the exact wording of its template examples is to be approved by IG. Every example text the rule book lists is therefore not IG-approved: B1, B4, B5 and I1. Also not IG-approved: I2, whose wording is screen wording from ui-screens.md line 3685 (the rule book has no I2 example). Also not IG-approved: the B2 email subject, text and HTML, the B3 push text and title, and the K2 email and push text and title, which follow the prompt. The owner signs these off, and until then none of them is approved for real sends.
4. **[ASSUMED] wording.** B7, I3, K1 and K4 are marked [ASSUMED] in the prompt. Their text is used as given, and the owner may reword it. K4 open question for the owner: the K4 text does not appear verbatim in ui-screens.md (its suspended screen at line 3532 has no SMS to the service), so the owner must confirm it. B6 is not in this list; see item 1.
5. **B7 takes a list of at least two references.** One reference is a single open request, so the reply does not need the prompt. A bare string is refused: a string is iterable, so `"4821"` would otherwise join as `"4, 8, 2, 1"`. Each reference must be non-empty text. Joined with `", "`. The example uses the first reference.
6. **B2 email body follows the prompt's lines exactly.** It has no footer line. The link is labelled "Review request" in the HTML and as `Review request: {link}` in the text. The HTML escapes every field value, as DEC-034 item 3 does.
7. **K3 has no wording of its own.** `title` becomes the push title and `body` the push text, as the caller gives them. The template adds no words and holds no patient data. Callers must keep patient data out of `body`; the build-time scan of D17 checks the rendered output.
8. **Deviation from the screens.** ui-screens.md line 1078 gives the B1 text as "response within 2 hrs" and "Reply CONFIRMED or DECLINE by 14:26". The prompt's form ("within 2 hrs" and "or open {link} by {reply_by}") is implemented, as the task asks. The prompt's form agrees with domain-rules section 9 and with ui-screens.md lines 1123, 1132 and 1141. Owner decision needed: which B1 form the screens follow.
9. **D15 placeholder test removed.** `test_ids_not_yet_implemented_raise_not_implemented` in `tests/unit/domain/messages/test_templates.py` asserted that B1, I1 and K1 raise `NotImplementedError`. The D16 prompt requires that path to be removed, so the test is removed with it. No other D15 test changed.

Tests: `backend/tests/unit/domain/messages/test_templates_d16.py`. They assert the exact sample text for B1, B4, B5, B6, B7, I1, I2, I3, K1 and K4, the B2 subject and body, the B3 and K2 push wording, the K3 pass-through, the channel and field refusals, the B7 list rules and an SMS length of at most two segments for B1.

## DEC-042 Owner decisions on the open items (2026-10-25)
Status: accepted · Decided by the owner (operations@mirroredintelligence.com) through the orchestrator. Each item below supersedes the open question it answers.

1. **Booking reference and Role on events (DEC-041).** Accepted. A booking reference is the 4-digit number from domain-rules line 165 and DEC-007. An acknowledgement's `by` is a Role, as in ui-screens line 3640. Both refuse names, postcodes and phone numbers. Free-text identifiers stay unchecked and that residual stays recorded in H-09.
2. **Three unmapped screen texts (DEC-034 item 9).** Accepted as follows. The no-link C1 variant (ui-screens 963) goes to a follow-up in D15's template set. The correction echo (970) and the Y echo (3360) go to U05, which renders echoes. None blocks Stage 1.
3. **Email and push wording (DEC-034 items 3 and 4).** Not approved. Information governance sign-off is an external approval and is human-only, so it is not granted here. The wording stays marked IG-pending. No real email or push may use it until IG approves it in writing.
4. **DEC-029 (Monday-overdue reading).** Accepted. A service with no report on a Monday morning is overdue. This follows domain-rules 1.5. A service registered after a missed due with no report is flagged for a prompt it never received; the registration task should mark its first due as not yet due.
5. **DEC-040 (pressure type check).** Accepted. The pressure functions refuse any value that is not exactly a Status member, fail closed, with TypeError. Callers in D24, U08, W07 and W40 must pass Status members.
6. **Active versus suspended split (DEC-035).** Accepted. G11 excludes inactive and suspended services from the candidate list. U12 lists suspended services under not suitable. U12 must depend on G11 so a suspended service is never offered; its prompt must say so.

## DEC-041 Domain event payload and validation choices the prompt leaves open (D25)
Status: accepted · Affects: D25 (`domain/events.py`); every task that publishes or consumes a domain event (U01, U06, U07, U13, U15, U19 to U21, U24, I02, I03).

Numbered DEC-041: DEC-040 is the highest number on main and on every task/* branch when D25 was written. Checked with `git show <branch>:docs/delivery/decisions.md` on each branch.

The prompt for D25 fixes the event names, fields and topics (also in `docs/spec/contracts.md`). It leaves these open, and this decision settles them:

1. **Timestamps.** `at` is UTC. A constructor refuses a naive datetime or any non-zero offset (`ValidationFailed`, field `at`). `to_payload()` writes ISO 8601 with a trailing `Z` and keeps microseconds when they are non-zero. `from_payload()` refuses a timestamp that does not end in `Z`.
2. **Counts.** `value` and `version` must be `int`. `bool` is refused, because `True` is an `int` in Python.
3. **Codes.** Each enum field is parsed with its own enum class through `parse_code`, so a value that belongs to another enum is refused (lessons L3 and L38). A refused code is named by field, never echoed.
4. **Decoding.** An unknown event type, a missing field or a wrong type raises `ValidationFailed`. Extra keys in a payload are ignored. The producer is the outbox, which writes only `to_payload()` output.
5. **Session id.** Only `CapacityReported` and `StatusChanged` (topic `capacity.events`) carry the service id as session id. Every other event has none. Topic names are the `architecture.md` names, exposed as `CAPACITY_EVENTS`, `BOOKING_EVENTS`, `REGISTRATION_EVENTS`, `CRITERIA_EVENTS` and `ALERTS_EVENTS`.
6. **Reference and role values.** `BookingRequested.reference` must be a 4-digit booking reference: `[1-9][0-9]{3}`, so 1000 to 9999 with no leading zero. The source is `docs/spec/domain-rules.md` line 165 (section 3.2: "short numbers ... for example 4821", marked [ASSUMED] as 4 digits, random, retry on collision) and DEC-007, which puts the 4-digit form in force. `booking_rules.new_reference` generates only that form. Refused: a name, a postcode (`Jane Smith DT4 8XX`, `DT4 8XX`), a phone or NHS number (`943 476 5919`, `9434765919`), a leading zero, any other length, and text such as `REF-2K7Q`. The reply parser reads 3 to 8 digits from a typed reply; that is parsing input, not a stored reference, and it is not changed here. `AlertAcknowledged.by` is a `Role`, because `docs/spec/ui-screens.md` line 3640 shows "AlertAcknowledged by [Role]". Refused: any value that is not a Role member, including phone-number-shaped values, names, and a member of another enum with the same value (`DeclineReason.FULL`, value `full`, lesson L3). These two checks cover the fields a name or phone number could most plausibly reach (hazard H-09). They do not cover the other fields (item 8). The owner should still confirm that the screen form `by [Role]` is the intended identity, because the rule book does not name the acknowledging person.
7. **Adding events.** A later task that adds an event class must add it to the `DomainEvent` union, to `_TOPIC_BY_CLASS`, to `_DECODER_BY_NAME`, and to `session_id_for` if it is on `capacity.events`. `test_every_event_class_has_a_topic` fails until the topic is added. A decoder missing from `_DECODER_BY_NAME` is refused as an unknown event type.

8. **Residual: id and free-text fields are not shape-checked.** `booking_id`, `service_id`, `alert_id`, `registration_id`, `criteria_id` and `report_id` are text. The rule book gives no id format to check against, so D25 does not invent one. Ids are minted by the id port, not typed by people, but nothing in the event type enforces that. `BookingRequested.reference` and `AlertAcknowledged.by` are the only shape-checked fields. `test_no_event_has_a_patient_field` checks field names, not values. Before any task puts a free-text value into an event, the owner or a later task must set an id format and add a shape test. This is an open residual for hazard H-09.

Tests: `backend/tests/unit/domain/test_events.py`.

## DEC-045 Link token, pairing code and support code choices the prompt leaves open (D26)
Status: accepted · Affects: D26 (`domain/rules/tokens.py`); P10 (link tokens), U10 (pairing), O06 (support codes), L01 (link endpoints), R15 (screen pairing).

Numbered DEC-045: DEC-043 is claimed by task/D17-template-privacy-guard and task/D24-alert-rules, and DEC-044 by task/D27-identity-policy (all unmerged). Checked on main and every task/* branch with grep for DEC-0NN; DEC-045 was free. Lesson L43.

domain-rules 7 and the D26 prompt fix the lengths, alphabets, expiry and the check order. They leave these points open:

1. **Pairing digits are drawn one at a time.** `new_pairing_code` calls the random source six times, each with bound 10, and each result must be an `int` from 0 to 9 (`bool` is refused). The prompt's expectation that `lambda n: 7` gives "777777" holds only on this reading. Each digit is uniform, so every six-digit code is equally likely.
2. **Support codes draw from the 31-character alphabet.** `new_support_code` calls the random source eight times, each with bound `len(SUPPORT_CODE_ALPHABET)` (31), and refuses any index outside 0 to 30. The output is `XXXX-XXXX`.
3. **The link token source must give exactly 16 bytes.** Any other length, or any non-`bytes` result, raises `ValidationFailed("token", ...)`.
4. **`hash_token` takes only URL-safe text and a non-empty secret.** The token must match `[A-Za-z0-9_-]+`, so the 22-character form and the prompt's test value "abc" both pass. An empty secret is refused, because an HMAC with an empty key is not a keyed hash.
5. **Every instant must be timezone-aware.** A naive or non-datetime value raises `ValidationFailed` by field name (`now`, `expires_at`, `used_at`, `issued_at`). `LinkTokenRecord` checks its times when it is built. All comparisons are made in UTC (DEC-039 item 7, lesson L52).
6. **A pairing code issued after `now` is refused, not reported as valid.** `pairing_code_expired` raises `ValidationFailed("issued_at", ...)`. A skewed clock must not quietly extend a code's life.
7. **Errors never echo a token, a code or a secret.** Each `ValidationFailed` names the field and a fixed message. Tests check this for a malformed token and a malformed pairing code.
8. **Scope.** `check_link` does not look at `phone_hash` or `purpose`. The link endpoint (L01) and the token store (P10) must check both before they act on a link.

Tests: `backend/tests/unit/domain/rules/test_tokens.py` (54 tests, three of them Hypothesis property tests). Branch coverage of the module is 100%.


## DEC-046 Alert rule choices the prompt leaves open (D24)
Status: accepted · Affects: D24 (`domain/rules/alerts.py`); U33 and U34 (subscriptions, alert raising), the worker that polls not-updated, U08 and W07 (pressure callers), and every task that schedules alert escalation (alert-escalate work, P08).

Numbered DEC-046. DEC-043 was first written here, but task/D17-template-privacy-guard already uses DEC-043, task/D27-identity-policy uses DEC-044 and task/D26-link-tokens uses DEC-045 (verify-D24 found the clash). Checked by listing every `^## DEC-` heading in `docs/delivery/decisions.md` on main and on every local and remote branch: highest is DEC-045, so DEC-046 is the first free number.

`docs/spec/domain-rules.md` section 8 gives the alert kinds, the critical set, the quiet-hours options, the acknowledge windows and the defaults. The D24 prompt and the screens (ui-screens.md lines 3696 to 3751) fix the rest. The choices the prompt leaves open:

1. **No prior status counts as another status.** `alerts_for_change` takes `before: Status | None`. `None` (a service with no earlier status) is treated as "any other status", so `service-closed` and `over-capacity` fire on the first known status. This is the fail-safe reading: a closure at registration is not silently dropped. Owner may reverse it.
2. **Which kinds come from which trigger.** `alerts_for_change` raises only `service-closed` and `over-capacity`. `not-updated` is time-based and comes from `not_updated_alert_due`, which a worker calls with the clock. `system-pressure` comes from `alert_for_pressure`, and fires only when the pressure moves to `high` from `normal` or `watch`.
3. **Critical kinds.** `service-closed` and `system-pressure` are critical, as the rule book marks [ASSUMED]. `Alert.critical` must equal "kind is critical", and `AlertPreferences` and `Alert` refuse anything else (`ValidationFailed`).
4. **Quiet hours are only None or 22:00 to 06:00.** ui-screens.md lines 3738 to 3741 offer only these two, and the rule book says "either none or 22:00–06:00". `AlertPreferences` refuses any other tuple, so the field is a `(time, time)` pair only for the contract's signature. A window is checked as instants: for the London dates either side of `now`, 22:00 and 06:00 are converted with `london_to_utc`, and `now` is quiet when it falls in `[start, end)`. Quiet with "critical only" suppresses non-critical kinds; with "everything" nothing is suppressed.
5. **Refusals.** Naive datetimes raise `ValueError`, the convention of `london_time.py`. A `Status` or `Pressure` that is not an exact member of its enum raises `TypeError` (DEC-040, lessons L3 and L38). A blank service id, an unknown kind, an ack window other than 10, 15 or 30 minutes, and a not-updated threshold other than 2 or 4 hours raise `ValidationFailed` with the field name.
6. **No free text in an alert.** `Alert` has four fields: kind, service id, raised time, critical. No message text is carried. The wording is produced by the message templates (D16) and the screens, so no patient or service detail reaches an alert record (H-09).
7. **Escalation.** `escalation_at` is the alert time plus the chosen ack window, in real time. `ESCALATION_LADDER` is `("subscriber", "deputy", "shift-lead")` as strings, matching the contract. `next_escalation_target` returns `None` after `shift-lead`, and refuses an unknown stage with `ValidationFailed`.
8. **Defaults.** `default_preferences()` turns on all four kinds, not-updated after 2 hours, no quiet hours, critical-only during quiet hours, and acknowledge within 15 minutes (domain-rules section 8 defaults).
9. **Out of scope and open.** Snooze (1 hour, ui-screens.md line 3737) is not in D24 and has no function here. The owner should confirm item 1 and the choice in item 4, which narrows the contract's tuple to the two screen options.

Tests: `backend/tests/unit/domain/rules/test_alerts.py`. The red commit holds the DEC-010 stub `alerts.py`, with constants and declarations only.

## DEC-044 Identity policy choices the prompt leaves open (D27)
Status: accepted for items 2, 3, 5, 6 and 7; items 1 (fifth-PIN outcome) and 4 (fail-closed clock rules) are in force but pending owner confirmation, which the owner has not yet given · Affects: D27 (`domain/rules/identity_policy.py`), U25 (sending codes), U32 (PIN use cases), P10 and I13 (code and PIN storage), any task that checks a text code, a PIN or the 30-day re-verification.

1. The fifth wrong PIN gives outcome `locked` (`PinState.locked` is True, `last_outcome` is `locked`). The prompt gives no outcome for the locking attempt. The text-code rule gives `too-many-tries` on its fifth wrong try, and `locked` is the PIN's equivalent.
2. While a PIN is locked, every attempt returns `locked`, right or wrong, and does not change the try count. Only `reset_pin_state()`, called after a verified text code, unlocks it.
3. Once a text code is verified, any further entry against it is `expired` and never counts as a try, right or wrong (prompt rule 3).
4. Fail closed on clocks. A code stamped in the future is `expired`. `can_resend` refuses when the last send is in the future. `needs_reverification` returns True when the last verification is in the future.
5. Every datetime must be timezone-aware, or `ValidationFailed` is raised with the argument name. Instants are converted to UTC before they are compared, subtracted or added to. Same-zone London arithmetic is wrong across the clock change (lesson L52), so the code-expiry and 30-day tests use London-zoned inputs that cross 2026-10-25.
6. The PIN never enters this module. `pin_attempt` takes a boolean the caller computed. `validate_pin_format` refuses by length and ASCII-digit check, and its message never repeats the value.
7. Whether a device is known is an input from the caller (I13 and P10). An unknown device always requires a text code.

Tests: `backend/tests/unit/domain/rules/test_identity_policy.py`. Numbered DEC-044 because DEC-043 is claimed on `task/D24-alert-rules`.

## DEC-047 Privacy guard choices the prompt leaves open, and what it does not cover (D17)
Status: accepted for items 1 to 8 and 10; item 9 is OWNER-PENDING (it changes the printed B1 text and the owner must choose the wording per code) · Affects: D17 (`domain/messages/privacy_guard.py`, `domain/messages/templates.py`) and every template under `domain/messages/`; any task that renders text, email or push (U01 to U06, U17 to U24, O04).

Numbered DEC-047: DEC-046 is the highest number on any branch (task/D24-alert-rules) when this was renumbered; the first round used DEC-043, which task/D24-alert-rules also claimed (lesson L43). Checked with `git show <branch>:docs/delivery/decisions.md` on every branch.

The D17 prompt gives the patterns and the field list. It leaves these open, and this decision settles them:

1. **Postcode whitespace.** Between the two halves there may be no whitespace, or any run of whitespace, as DEC-028 says for the postcode parser; not only a single space. The match is case-insensitive. `DT4` alone never matches. This is stricter than the prompt's ` ?` and flags nothing the prompt names as allowed.
2. **NHS-number shape.** Ten digits, contiguous or grouped 3-3-4. Each join may use a space or a hyphen, and the two joins may differ (`943 476-5919`). A digit run longer than ten is refused by lookaround, so an 11-digit phone number never matches. A 4-digit booking reference never matches.
3. **Personal titles.** The title is matched in any case (`MRS Smith`, `mrs Smith`), and the next word must start with a capital letter followed by lowercase letters, as the prompt says. A title with no following capitalised word (`Mrs`, `Mrs smith`) is not flagged. The prompt's single space becomes `\s`, so a title split by a line break is still found. A full stop after the title is optional.
4. **Output.** `find_patient_data` returns every fragment from every pattern, in the order it appears in the text. A fragment that two patterns both match appears twice.
5. **Where the guard runs.** `render` calls `find_patient_data` on every value the caller passes (lists and tuples are searched inside) and on the rendered text, subject and HTML. Any hit raises `ValidationFailed`. A caller therefore cannot get a postcode, NHS-shaped number or titled name into any message through `render`, whichever field it arrives in. The build-time sweep checks the synthetic samples as well.
6. **Per-field probes.** For every id, every string field and every list element a template takes, the test puts three probes in turn (a full postcode, an NHS-shaped number, a titled name) and expects `ValidationFailed`. The sweep of synthetic samples alone proves only that the samples are clean; the probes prove the guard runs on every field. Each id is probed on one supported channel, which is enough because the guard runs before any channel-specific text is built.
7. **Forbidden field names.** Refusal of `name`, `patient_name`, `nhs_number`, `postcode`, `address`, `dob`, `date_of_birth` and `free_text` in a template call is done by `render` (D15, DEC-034 item 1). The forbidden-field tests pass on the first red commit because of that, and the tests stay to pin the behaviour for every id.
8. **Residual: free text (K3 `body`, DEC-037 item 7).** The render guard covers the shapes in items 1 to 3 wherever a caller puts them, including K3 `body`. It does not cover free text in general: a bare two-word name with no title (`Jane Smith`), since a general name rule would also flag place names such as `UCR West`; NHS-number shapes split by letters or other punctuation; or a name written in lowercase with no title. Callers must keep patient data out of free text. This stays on the open list for H-09 and the owner should decide whether a name-shape rule is needed before any real send (DEC-042 item 3 keeps the wording IG-pending until then).
9. **Constrained fields.** `reference` must be four digits with no leading zero, `[1-9][0-9]{3}` (DEC-041). It applies to B1 to B7, including each B7 list element. `age_band` must be an `AgeBand` value (`0-15`, `16-64`, `65-79`, `80+`). `urgency` must be one of the three `Urgency` wordings: `within 2 hrs` (the printed form of `within-2-hrs`), `today` and `planned`. The rule book names all three (domain-rules section 3, contracts.md `Urgency`). `need` must be a `NeedCategory` code, one of the nine in contracts.md, and free text is refused. The rule book says a case holds "needs (need-category codes)" (domain-rules section 3), so the code is the field's value. Consequence: the B1 text prints the code, for example `Age 80+, frailty, within 2 hrs`, and no longer the rule-book sample `fall and frailty`, which is not a single code. The sample wording is a deviation from DEC-037 item 1 and the owner must decide the printed wording per code (for example `frailty` or a plain-English label). Until then the printed form is the code.
10. **Build failure.** The guard runs inside the unit suite, so a template that fails it fails `pytest tests/unit`. The completeness test (`test_every_message_id_has_a_sample`) fails when a new `MessageId` has no sample. The channel table `EXPECTED_CHANNELS` in the same test file must be updated with any new channel rule, which makes a channel change visible in review.

Tests: `backend/tests/unit/domain/messages/test_no_patient_data_in_templates.py` (guard, sweep, per-field probes, constraints) and `backend/tests/unit/domain/messages/test_templates*.py` (existing wording, unchanged). Mutation checks are in the D17 evidence file.

## DEC-048 Grouped-prompt and phone-load choices the prompt leaves open (D28)
Status: accepted by the builder (build-D28); owner to confirm · Affects: D28 (`domain/rules/multi_service.py`), U04 (sends grouped prompts), U05 and D14 (apply replies per letter), D15 C9 and C10.

Numbered DEC-048: DEC-047 is the highest number on main and on every `task/*` branch (checked with `git show <branch>:docs/delivery/decisions.md`), so this is the next.

1. **Return type.** `group_due` returns `list[PromptGroup]` with `GroupedItem` and `PromptGroup` as the D28 prompt's Build section says. contracts.md had written `list[list[...]]`; it is corrected in the same commit.
2. **Order.** Items are sorted by due instant (UTC), ties by name, then service id. Letters follow the name order of `letters_for`, which uses Python string order (code point, case-sensitive).
3. **Clock.** Due times are converted to UTC before they are compared or added to (lesson L52). A naive due time raises `ValidationFailed("due")`. Returned due times are UTC.
4. **Membership.** An item joins the current group only when it is less than `GROUP_WINDOW` after the group's first item. Groups are anchored on their first item, not chained, so 10:00, 10:05 and 10:12 give [10:00, 10:05] and [10:12] (the prompt's test 3).
5. **Lettering.** Only groups of two or more get letters. A group of one has `letter=None`. `letters_for` letters every name it is given, so one name gets `A`.
6. **Limits.** More than 26 items in one group raises `ValidationFailed("items")`. `letters_for` with more than 26 names raises `ValidationFailed("names")`. `MAX_LETTERED_ITEMS = 26`.
7. **Uniqueness, fail closed.** A repeated `service_id` in the input raises `ValidationFailed("service_id")`. Repeated names in one group, or in `letters_for`, raise `ValidationFailed("names")`: the letter map is keyed by name, so a repeat would give one name two letters.
8. **Phone load.** A negative count raises `ValidationFailed("count")`. A count above `MAX_SERVICES_PER_PHONE` (3) is overloaded, so 4 is flagged and 3 is not.
9. **Reply-by.** A group's reply-by is `schedule.reply_by(group due)`, due plus `REPLY_WINDOW` (30 minutes).

Owner-pending: the 10-minute `GROUP_WINDOW` is `[ASSUMED]` in domain-rules 2.4. The clinical safety officer should confirm it with the other `[ASSUMED]` values.

Tests: `backend/tests/unit/domain/rules/test_multi_service.py` (25 tests, including a Hypothesis partition property and a clock-change case). Partial replies (2.4, second bullet) belong to D11 and U04, not this module.

## DEC-049 FHIR-to-graph mapper choices the prompt leaves open, and where DEC-001 overrides R1 (G02)
Status: accepted · Affects: G02 (`adapters/outbound/graph_store/mapper.py`), G03, G04, G05 and every task that writes a resource.

Numbered DEC-049: DEC-048 is the highest number on any branch when this was written. Checked with `git show <branch>:docs/delivery/decisions.md` on every branch.

1. **No `json` property.** `fhir-data-model.md` R1 and the G02 prompt (test 6) keep a canonical `json` on each resource node. DEC-001 overrides that, so the mapper never writes `json`. The prompt's "json equals the canonical resource" test is replaced by two tests: reordered keys give an equal fragment, and a schema test refuses any map, list of maps or JSON-looking string in a node or relationship property (`test_no_node_or_relationship_carries_a_json_property`, `test_samples_hold_no_map_no_list_of_maps_and_no_json_string`). The round trip `from_graph(to_graph(r)) == r` replaces the canonical check.
2. **Primitives stay as written.** The mapper keeps FHIR primitive values as they came in, including dates and datetimes as ISO 8601 strings with their offset. DEC-001 says datetimes are stored as Neo4j `datetime` values. G05 converts at write. A Neo4j `datetime` holds an instant and does not keep the offset text, so G05 must keep the original text (or the offset) or the round trip will not return the same string. This is an open risk for G05, not settled here.
3. **Fail closed.** Any element the mapper does not represent raises `UnsupportedElement(path)`: CodeableConcept, Identifier, Extension, backbone elements, `meta` keys other than `versionId` and `lastUpdated`, empty lists, an empty `meta` object, lists that mix kinds, and `null`. A reference that is not a relative `Type/id` (absolute URL, history, bare type) raises `InvalidReference(path)`. Both subclass `DomainError`. A missing `resourceType` or `id` raises `ValidationFailed` with the field name only.
4. **Deterministic fragment.** Elements are read in sorted order, so two dicts that differ only in key order give equal `GraphFragment` values.
5. **Order.** A reference element given as a list always carries `order`, including a list of one. A single reference never does.
6. **Targets are not nodes.** A reference target keyed `Type/id` is a relationship end only. The mapper creates no placeholder node; G05 decides how a target that does not exist yet is stored.
7. **Lossless or refused (F1, verifier finding on 65f622d).** The round trip must give back exactly what went in, or the mapper must refuse. Three names are refused with `ValidationFailed(field)` at the top level because the node already stores them: `iri` (derived from type and id), `versionId` and `lastUpdated` (stored from `meta`, so a top-level copy would move into `meta`). An empty `meta` object is refused (`ValidationFailed("meta")`) rather than kept as an empty map, because an empty map is not a storable property (DEC-001) and omitting it would drop the element. Covered by fixed cases and a hypothesis property (`test_round_trip_is_exact_or_refused_for_any_generated_resource`, 400 examples; measured in the G02 run recorded in the evidence file: 843 of 2000 generated resources round-tripped (42%), 1157 refused (597 ValidationFailed, 560 UnsupportedElement)).
8. **Residual for G05, not fixed here.** The mapper does not check the time zone of a FHIR datetime (R2 says keep the zone). G05 must keep the original text or offset when it converts to Neo4j `datetime`, as item 2 says.
9. **Scope.** `meta` is limited to `versionId` and `lastUpdated` here. Other meta keys, extensions and the rest of the R-rules belong to G03 and G04.

Tests: `backend/tests/unit/adapters/outbound/graph_store/test_mapper.py` (40 tests, 100% line and branch on `mapper.py`).

## DEC-050 Owner decisions on the three open items (2026-10-25)
Status: accepted · Decided by the owner through the orchestrator. Each item supersedes the open question it answers.

1. **Grouping window, 10 minutes (DEC-048).** Accepted as the working value. It stays marked [ASSUMED] in the code and in contracts.md, because the rule book gives no figure. It is checked against real timings in the pilot before go-live. Changing it needs a new decision, not a silent edit.
2. **Printed need wording (DEC-047 item 9).** Accepted in principle, with a change to be made: the printed need in B1 is the plain-English category name, not the code. The wording of each category is drafted from the NeedCategory display names and goes to information governance for sign-off, so it stays IG-pending until IG approves it in writing. Until the change is built, B1 keeps printing the code and the decision does not claim otherwise. The change is a follow-up task on the D16 templates.
3. **DEC-044 item 1 (fifth-PIN outcome: locked).** Accepted. The fifth wrong PIN locks the account, as domain-rules section 7 requires; the fourth wrong attempt is still allowed.
4. **DEC-044 item 4 (fail-closed clock rules).** Accepted. Expiry and the 30-day re-verification are compared in UTC, and any check that cannot be evaluated denies access.

Follow-up: the B1 plain-English need change is not built. It must be built test-first on the D16 templates before any printed B1 message goes to users.

## DEC-051 Concept, identifier, period and quantity mapping choices the prompt leaves open (G03)
Status: accepted · Affects: G03 (`adapters/outbound/graph_store/mapper.py`), G04, G05, and every reader of a fragment. Extends DEC-049; supersedes DEC-049 item 3 for CodeableConcept, Identifier, Period, Quantity and Range.

Numbered DEC-051: DEC-050 is the highest number on `main` and on every `task/*` branch when this was written (checked with `git show <branch>:docs/delivery/decisions.md`).

1. **Concepts (R5).** A Coding becomes `(:Concept {system, code, display?, version?})` keyed `Concept|<system>|<code>`, with `(:Concept)-[:IN_SYSTEM]->(:CodeSystem {url})` keyed `CodeSystem|<url>`. The relationship from the resource is named after the element and carries `fhirPath`, `order` (the coding's index in its CodeableConcept, always present), `text` (if the CodeableConcept has one) and `userSelected` (if the Coding has one).
2. **Lists of concepts.** A CodeableConcept given as a list carries `conceptOrder` on every coding relationship, so a list of one is kept distinct from a single CodeableConcept. Without `conceptOrder` the element is single-valued.
3. **Refused, not guessed.** A Coding without a non-empty `system` and `code` is refused (`ValidationFailed` with the field name). A CodeableConcept without codings, with an unmapped key, or with non-text `text` raises `UnsupportedElement`. Any Coding key other than `system`, `code`, `display`, `version` and `userSelected` raises `UnsupportedElement`. A system, code or identifier value containing `|` is refused, because it would make two different keys collide. A reference target whose type contains `|` is an `InvalidReference`.
4. **Same key, different details.** Within one resource, the same concept with a different `display` or `version` is refused (`ValidationFailed("code")`). Across resources, G05 must not overwrite a concept's display or version by `MERGE ... SET` (see the lesson published with this task).
5. **Identifiers (R6).** An Identifier becomes `(:Identifier {system, value})` keyed `Identifier|<system>|<value>`, linked by `IDENTIFIED_BY` with `fhirPath`, `order` (for a list) and `use` (if given). **Deviation from the prompt's R6 text:** `use` is on the relationship only, not on the shared node. One identifier can be used with two different `use` values by two resources, and a `use` on the shared node would be overwritten. The element is recognised by its name, `identifier`. An identifier needs both `system` and `value`. Any other key (`type`, `period`, `assigner`, extensions) is refused.
6. **ODS (R6).** An identifier with system `ODS_ORG_SYSTEM` copies its value to `odsCode` on the resource node. Two different ODS organisation codes on one resource are refused. An `ODS_SITE_SYSTEM` identifier becomes an Identifier node and sets no property. Both URIs carry `# VERIFY against NHS England FHIR docs`. They appear in the mapper only as the two constants (checked by a test).
7. **Period, Quantity, Range (R7).** A Period `E` flattens to `EStart` and `EEnd` (so `period` gives `periodStart`, `periodEnd`). A Quantity `E` flattens to `E_value`, `E_unit`, `E_system`, `E_code`. A Range `E` flattens to `E_low_*` and `E_high_*`, each a Quantity. The kind is decided by the keys present: Period keys are `start` and `end`, Range keys are `low` and `high`, Quantity keys are `value`, `unit`, `system` and `code`. An empty object, a Quantity with `comparator`, or a non-text Period bound is refused. Quantity and Period flattening is exact for any dict with those keys, whatever the element means in FHIR, because the round trip is exact.
8. **Reserved names (so the reversal is unambiguous).** A top-level element may not contain `_`, may not end in `Start` or `End`, and may not be `odsCode` or `measureCode`. Each such name raises `ValidationFailed` with the name only. A stored property with `_` is always a flattened Quantity or Range, and a property ending in `Start` or `End` is always a Period bound.
9. **Filter codes (R11).** `FILTER_CODE_PROPERTIES` copies the `code` of the first coding of the first CodeableConcept to the property (`measureCode` for Observation.code). `odsCode` and `measureCode` are removed on rebuild, so they never reach the rebuilt resource. A `code` that is not a CodeableConcept gets no copy.
10. **Rebuild needs the shared nodes.** `from_graph` reads Concept and Identifier properties from `fragment.nodes`. A relationship to a missing Concept or Identifier node raises `NotFound`. A fragment whose element mixes kinds, a list with a single entry, or codings of one concept that disagree on `text` raises `ValidationFailed`. G05 must load those nodes into the fragment.
11. **G02 tests changed.** Two cases in `test_mapper.py` asserted the refusal of CodeableConcept and Identifier. They now test an unmapped element inside a CodeableConcept, and the identifier row is removed. The G02 behaviour for every other element is unchanged. `UnsupportedElement` and `NotFound` are still raised for those cases.
12. **Not in this task.** Backbone elements and extensions (G04). Persistence and the Neo4j datetime zone text (G05, DEC-049 item 2). `SUBSUMED_BY` (out of scope). Mutation testing of the mapper: not run (the mapper is not on the delivery standard's safety-critical list).

13. **Graph-safety check, corrected after verify-G03b FAIL on 5a0be59.** Every string value is refused if it parses as a JSON object or array (`json.loads`). That is the check the first green commit `0edfadc` used. Separately, a string that starts with `{` or `[` is refused, except a UCUM annotation in a property whose name ends in `_code`, and only if the whole value matches a strict pattern: a brace or bracket around a letter followed by letters, digits or underscores (for example `{referral}` or `[in_i]`). Nothing else is exempt, and the carve-out never reaches a value that parses as JSON, which the first check refuses. The round-2 wording called the original check a prefix test; that was wrong. The round-2 exemption accepted any `*_code` holding bracketed content, and it is removed. The IN_SYSTEM assertion in the capacity-report test compares all three concept relationships. `from_graph` returns codings, identifiers and concept lists in their original order whatever order the relationships arrive in. `test_rebuild_restores_the_original_order_whatever_order_the_relationships_arrive_in` is a regression pin, not a red test: it passes on the mapper it guards, and it is red against the sort-removed mutant.
Tests: `backend/tests/unit/adapters/outbound/graph_store/test_mapper_coded_values.py` (new), and the G02 `test_mapper.py` (two cases changed, see item 11). 100% line and branch on `mapper.py`.

## DEC-052 Backbone elements, extension registry and extension order (G04)
Status: accepted · Affects: G04 (`adapters/outbound/graph_store/mapper.py`, `extensions.py`), G05 (must write child nodes, `ext_` properties and `extensionOrder`, and load the child nodes into the fragment), every reader of a fragment. Extends DEC-049 and DEC-051.

Numbered DEC-052: DEC-051 is the highest number on `main` and on every `task/*` branch when this was written (checked with `git show <branch>:docs/delivery/decisions.md`, and no branch has DEC-052).

1. **Backbone table (R4).** Only the elements listed in `_BACKBONE` are mapped, keyed by the FHIR path of the owner and the element: `HealthcareService` availableTime, notAvailable, eligibility and telecom; `Location` address, hoursOfOperation and telecom; `Organization` address, contact and telecom; `Organization.contact` address and telecom. Any other object-valued element is refused with `UnsupportedElement`. Nothing is guessed.
2. **Child nodes.** A backbone entry becomes a node labelled as the table says (`HealthcareService_AvailableTime`, `HealthcareService_NotAvailable`, `HealthcareService_Eligibility`, `Location_HoursOfOperation`, `Organization_Contact`, `Address`, `ContactPoint`), keyed `<parentKey>#<element>[<index>]`. A child of a child extends the key, for example `Organization/x#contact[0]#telecom[0]`.
3. **Order.** A list entry, including a list of one, carries `order` on its relationship, and the index is its position. A single object has no `order` and its key index is `[0]`, so a list of one and a single object rebuild differently, as CodeableConcept lists do (DEC-051 item 2).
4. **Relationship names.** The catalogue names are used: `HAS_AVAILABLE_TIME`, `HAS_NOT_AVAILABLE`, `HAS_ELIGIBILITY`, `HAS_HOURS`, `HAS_CONTACT`, `HAS_ADDRESS`, `HAS_TELECOM`. Every entry in the table has one, so `HAS_ELEMENT` is not used. An element without a catalogue name must get a table entry with `HAS_ELEMENT` when it is needed.
5. **Refused, not guessed.** An empty object entry is refused with `ValidationFailed` (the same rule as an empty `meta`, DEC-049 item 7). An empty list is refused with `UnsupportedElement`. A child identifier is refused, because ODS codes are copied only from the resource itself.
6. **notAvailable.during (deviation).** FHIR `notAvailable.during` is a Period, so it flattens to `duringStart` and `duringEnd`. `fhir-data-model.md` lists `periodStart` and `periodEnd` for this node. The round trip is exact either way. The owner should reconcile the table; until then the FHIR name is used.
7. **Extension registry (R8).** `ExtensionDef(url, short_name, value_type)` validates itself: the short name is letters and digits, starting with a letter (no underscore, so `ext_<shortName>` splits unambiguously), and the URL must be `BASE_URL + "StructureDefinition/" + short_name`. `EXTENSIONS` is keyed by URL. Registering the same URL twice raises `ValueError`. The registry is global: the mapper does not check which resource type an extension belongs to, because profile validation is not part of the mapper.
8. **Registered value types (chosen here).** `smsShortName` string; `establishedCapacity` integer; `canExceedEstablished` boolean; `usualRangeMin` and `usualRangeMax` integer; `reportCadence` string (the `Cadence` values: every-2-hrs, twice-a-day, once-a-day); `limitedLevelPercent` integer (domain-rules 1.x, percentage 0 to 100); `geocodeSource` string; `geocodedAt` dateTime (text, zone kept, DEC-049 item 2); `uprn` string; `reportType` string; `referrerType` string.
9. **Extension entries.** Each entry must be exactly `url` plus the one value key of its registered type (`valueString`, `valueInteger`, `valueBoolean`, `valueDateTime` or `valueDecimal`). A value of the wrong type is refused with `ValidationFailed` (a boolean is not an integer). A complex value, an extra key, a repeated URL, a non-list `extension`, or an empty list is refused. An unregistered URL raises `UnknownExtension(url)`, a subclass of `UnsupportedElement`, so existing handlers still refuse it.
10. **Extension order.** A resource or child with more than one extension stores `extensionOrder`, a list of short names in the input order. A single extension has none. On rebuild, several extensions without an order, an order that does not name exactly the stored extensions, and an order with no extensions are each refused with `ValidationFailed`.
11. **Reserved names.** The top-level names `ext`, `extensionOrder`, `positionLatitude` and `positionLongitude` are refused, because a stored name must read back unambiguously. `ext` is refused because a quantity named `ext` would flatten to `ext_value`.
12. **Location.position.** Only `latitude` and `longitude` are accepted, as numbers that are not booleans, and they are stored as `positionLatitude` and `positionLongitude`. An `altitude` is refused. The Neo4j `position` point is set by G05.
13. **Reference targets containing `#` are refused** (`InvalidReference`). This narrows G02 acceptance, and it is needed because `#` separates child keys. Nothing that G02 or G03 tests accepted is refused now; the 21 fixtures in the existing mapper tests give fragments and rebuilt resources identical to `main`.
14. **Not built.** Complex extensions as child nodes (R8, second sentence), and extension values other than the registered type. Both are refused.
15. **Graph safety.** `test_mapper_backbone.py` holds a verbatim copy of main's graph-safety helper (the DEC-051 item 13 check in `test_mapper_coded_values.py`), including its UCUM carve-out for a `*_code` property. The helper is therefore identical to main's; the new fixtures hold no bracketed `*_code` value, so the carve-out does not apply to them. The DEC-049 property test was extended to cover backbone and extension input.
Tests: `backend/tests/unit/adapters/outbound/graph_store/test_mapper_backbone.py` and `test_extensions.py` (new). `mapper.py` and `extensions.py`: 100% line and branch.

## DEC-053 Graph writer and reader: layout, datetimes, versions and concurrency (G05)
Status: accepted · Affects: G05 (`adapters/outbound/graph_store/resource_store.py`), every repository that stores a resource (P01 onward), G13. Closes DEC-049 item 2 and the open risk in DEC-049 item 8. Corrects the zone wording of lesson L58.

Numbered DEC-053: DEC-052 is the highest number on `main` and on every `task/*` branch when this was written (checked with `git show <branch>:docs/delivery/decisions.md`).

1. **Layout.** Every node the store writes carries a `key` property: the mapper's NodeSpec key (`Type/id`, `<parent>#<element>[i]`, `Concept|...`, `Identifier|...`, `CodeSystem|...`). The names `key`, `placeholder`, `lockStamp` and `position` are the store's own, so an element with one of those names is refused (`ValidationFailed`). A version is a `ResourceVersion` node keyed `Type/id@<versionId>` (root label `ResourceVersion`, children `ResourceVersionPart`), linked from the resource by `HAS_VERSION {versionId}`. Copies carry their own labels so a query for a live type or child never returns history.
2. **Datetimes (closes DEC-049 item 2).** FHIR dateTime, date and time text is stored as the Neo4j `datetime`, `date` or `time` value. A probe on the harness Neo4j showed the fixed offset is kept: `+01:00` reads back as a `+01:00` offset. Lesson L58 said Neo4j does not keep the offset; that was true only for values converted to UTC first. A text is stored only if formatting the stored value gives the same text, else `ValidationFailed(field)`. So `+00:00` is refused (it reads back as `Z`), a fraction ending in zero is refused (`.000`), an invalid date is refused, and a partial date (`2026-10`) is refused because no Neo4j type keeps its precision. Up to nine fraction digits are kept.
3. **Versions (R10, DEC-001 overrides the json snapshot).** Each update copies the previous state (owned nodes and relationships, under the version key) into the graph. History is rebuilt with `from_graph`, never from a stored JSON. `Patient` and `ServiceRequest` keep no version (`NO_HISTORY_TYPES`), so a cleared value is gone from the graph. An existing `Observation` raises `NotAllowed` on any put.
4. **Concurrency (DEC-012).** A put begins with a write on the resource's root node. A second writer waits for the first to commit, then reads the committed version, so a stale expected version raises `Conflict` and exactly one of two racing writers wins (test `test_two_writers_racing_on_one_version_let_exactly_one_win`). A `ConstraintValidationFailed` from a racing create is mapped to `Conflict`. The store never retries; the caller's `execute_write` does.
5. **Shared nodes (L59).** `Concept`, `Identifier` and `CodeSystem` nodes are never deleted or moved. A `display` or `version` the node lacks is filled in. A different value already stored is refused with `ValidationFailed`, and the whole put is refused before the graph changes.
6. **Owned nodes.** On update the owned children (keys under `<key>#`) are deleted and recreated, and the root's outgoing relationships are deleted except HAS_VERSION. Incoming relationships and shared nodes are untouched. Everything that can be refused is checked before the first change (shared-node conflicts, reserved names, value conversions).
7. **Relationships are created, not merged.** Two relationships of one type between the same nodes are two facts (one concept listed twice in different positions). Owned relationships are cleared first, so there is nothing to duplicate on a clean write. A missing endpoint raises `NotFound`.
8. **Placeholders.** A reference target that is not yet written is a `Resource` node with `placeholder = true`, created `ON CREATE` only, so an existing node is never touched. The later write replaces all properties, which clears the flag.
9. **Named queries.** Templates are registered through `driver.run_query`. A query that needs a label or relationship type from data is registered on first use under its template id and that label or type (for example `Q-RES-UPSERT-NODE:Organization`). Every label and type name passes a regex before it reaches Cypher. The prompt's `Q-RES-SNAPSHOT` is not a separate query: the snapshot is written with `Q-RES-UPSERT-NODE` and `Q-RES-MERGE-RELS`. Extra queries (`Q-RES-GET` split, `Q-RES-CLEAR-ROOT-RELS`, `Q-RES-LOAD-NODES`, `Q-RES-LOAD-RELS`, `Q-RES-SHARED-*`, `Q-RES-SET-POSITION`, `Q-RES-HISTORY`) are needed for the layout above.
10. **`meta.lastUpdated` is written to whole seconds** (`2026-10-25T09:00:00Z`), because a `.000` fraction is refused by item 2. The sub-second part of the clock is not kept. `meta` in the input is refused (`ValidationFailed("meta")`), because the store sets it.
11. **Ids.** A FHIR id must match `[A-Za-z0-9.-]{1,64}`. `#`, `@`, `|` and `/` are refused, because they separate keys and labels.
12. **Position.** A Location's `position` is set as a Neo4j `point` from `positionLatitude` and `positionLongitude` on every put (`Q-RES-SET-POSITION`). The point is not returned by reads; the rebuild uses the two stored numbers.
13. **Patient.address is not mapped.** G04 maps only the backbone elements in `_BACKBONE`, so `Patient.address` raises `UnsupportedElement`. The privacy test (`test_clearing_a_patient_value_leaves_no_version_and_no_copy_of_it`) uses the `uprn` extension as the address-like value. The owner should decide whether Patient address is mapped in G04 or in a later task.
14. **Residuals, not fixed here.** (a) No index on `key`: each lookup scans the graph. Acceptable at pilot size; a label-scoped index or a migration is needed before scale. (b) A shared `Identifier` node written for a resource that is later cleared stays in the graph, because shared facts are not deleted (L59). The spec forbids NHS numbers as data, so nothing in this task stores one; a future identifier task must check this. (c) Only two writers are raced in tests.

15. **Idempotency key (added after verify-G05 FAIL, DEC-012).** `put` takes an optional `idempotency_key` (`[A-Za-z0-9._:-]{1,128}`). The store fingerprints the request (SHA-256 of the canonical JSON of the resource and the expected version) and writes `(:IdempotencyRecord {idemKey, fingerprint, versionId})` in the same transaction as the write. A replay with the same key and the same request returns the recorded version and writes nothing. The same key with a different request raises `Conflict`. Only the digest is stored, never the request. The P15 `IdempotencyStore` is not built, so this record stands in for it; when P15 lands, the record moves there.
16. **A refused write leaves nothing behind (added after verify-G05 FAIL).** Refusals on the input, on shared nodes and on the version run before the lock write, and the mapper fragment is converted before the lock too. A refused create therefore leaves no lock node, even if the caller catches the error and commits. Tests `test_a_refused_create_leaves_no_node_even_if_the_caller_commits` and `test_a_refused_datetime_leaves_no_node_even_if_the_caller_commits` assert zero `Resource` nodes after a swallowed error.
17. **Owner decisions, not settled here.** (a) `Patient.address` is not a mapped element (G04 `_BACKBONE`), so the postcode-clear path for a Patient is not proven. The privacy test uses the `uprn` extension instead. The owner decides whether Patient address is mapped, and how a cleared postcode is removed. (b) Organization and Location addresses keep their history: each `ResourceVersion` copy holds the old postcode, by design of R10. The owner decides whether a postcode can be removed from history. (c) Shared `Identifier` nodes persist after a clear (item 14b).
18. **Residual: `Resource.id` is unique across all resource types.** Migration `0001_resource_id` makes `Resource.id IS UNIQUE`, so `Organization/x` and `Location/x` with the same id collide, and the second write fails with a constraint error, mapped to `Conflict`. The spec line is `docs/spec/fhir-data-model.md`: "Resource ids | Random UUIDs. Never meaningful, never reused." The collision is not tested here. The owner or a later task decides whether the constraint becomes `(type, id)` or ids stay globally unique.

Tests: `backend/tests/integration/graph_store/test_resource_store.py` (27 integration tests against the harness Neo4j).

## DEC-054 Service and capacity repositories: stored names, mapping, versions and queries (P01)
Status: accepted · Affects: P01 (`application/ports/outbound/repositories.py`, `adapters/outbound/graph_store/service_repository.py`, `capacity_repository.py`), G04 (extension registry), every later repository that stores a FHIR resource (P02, P03, P13, P14).

Numbered DEC-054: DEC-053 is the highest number on `main` and on every `task/*` branch when this was written (checked with `git show <branch>:docs/delivery/decisions.md`).

1. **Stored names (DEC-052).** A registered extension is stored as `ext_<shortName>`. The prompt's test 3 asked for `establishedCapacity` as the property name; the stored name is `ext_establishedCapacity`, and the test asserts that name.
2. **No `json` (DEC-001).** The prompt's "json equals `profile_to_fhir(p)` apart from meta" check is replaced by a rebuild check: `ResourceStore.get` of the stored service equals `profile_to_fhir(p)` apart from `meta`.
3. **Extensions added.** `measure`, `unitLabel` and `channel` join the G04 registry (`extensions.py`). The G04 registry test pinned twelve names; it now pins fifteen. This edits a delivered task's test only to match the registry change.
4. **Test paths.** The prompt names `tests/unit/adapters/graph_store/` and `tests/integration/adapters/graph_store/`. The repo mirrors source paths (`adapters/outbound/graph_store/`) and G05 uses `tests/integration/graph_store/`, so the P01 tests live under those paths.
5. **Constructors.** `Neo4jServiceRepository(tx, store)` and `Neo4jCapacityRepository(tx, store)`, as the prompt says. `contracts.md` line 60 shows `(tx)`; the store is passed in so a repository never builds its own. The contract line is amended in this commit.
6. **`suspended`** is not stored (service flags hold it, P14). `save` ignores it, `get` returns `False`.
7. **`save` is insert or replace.** It reads the current version and writes with it. A change between that read and the write raises `Conflict` after the store's lock (DEC-053 item 4); nothing is silently overwritten.
8. **`add` checks before it writes.** An unknown service raises `NotFound` (the prompt is silent; a report must not create a placeholder service). An existing report id raises `Conflict`; the store would say `NotAllowed` for an existing Observation, so a race that reaches the store is mapped to `Conflict` as well. Reports are never updated or deleted.
9. **Latest.** Greatest `effectiveDateTime`. `CapacityReport` has no `issued` field, so the prompt's "later issued" tie-break uses the store's `meta.lastUpdated` (the write time, whole seconds). Two reports with the same effective time in the same second still tie and the order is undefined. Owner to decide whether D02's `CapacityReport` gets an `issued` field.
10. **`reports_since` is inclusive** (effective at or after `since`). The prompt says "since" only.
11. **`last_report_times`** is added to the port (the prompt lists it; `contracts.md` did not). It is named in `contracts.md` Additions in the same commit.
12. **Queries.** `Q-SVC-LIST-ACTIVE`, `Q-CAP-LATEST`, `Q-CAP-LATEST-FOR`, `Q-CAP-SINCE`, `Q-SVC-LAST-REPORT` are registered at import in the repository modules. The latest queries use the CALL-subquery shape of fhir-data-model query 1 and return observation ids; each observation is then loaded through the resource store. That is one load per report, acceptable at pilot size. The `effectiveDateTime` index in fhir-data-model is not created here (no migration in this task).
13. **Time text.** Effective times are written in UTC with a `Z`, fractions kept without trailing zeros, so the store accepts them and they read back identically (DEC-053 item 2).
14. **Shared helpers.** `codeable_to_fhir` and `codeable_from_fhir` live in `service_repository.py` and are used by `capacity_repository.py`. A code is read from its enum class's own code system (lesson L3); a coding from another system is refused.
15. **UCUM units** per measure as the prompt lists: `{referral}`, `{bed}`, `{slot}`, `{patient}`, `{package}`.

Residuals, not settled here: no `issued` on `CapacityReport` (item 9); no migration for the `effectiveDateTime` index (item 12); the mapping path where a racing add reaches the store is not exercised by a test.

## DEC-056 Communication records are Neo4j platform nodes written by named queries, and a reply must name a stored prompt (P07)
Status: accepted by the builder (build-P07); owner to confirm · Affects: P07 (`adapters/outbound/graph_store/communication_repository.py`, `application/ports/outbound/messaging.py`, `adapters/testing/recording_senders.py`), migrations 0014 and 0015, P08, P10 and every task that records or reads a message.

Numbered DEC-056. It was first written as DEC-054, which P01 took on main (07d3f82); DEC-055 is P05. DEC-053 was the highest number on any branch when this was first written. Checked with `git show <branch>:docs/delivery/decisions.md` on every branch.

The P07 prompt leaves these open or departs from DEC-001, and this decision settles them.

1. **Not saved through ResourceStore, and no `json`.** The prompt says the record is saved through the G05 `ResourceStore` and also keeps a `json` property. DEC-001 forbids `json`. The store's mapper refuses elements it does not map, and `payloadText`, `deliveryStatus` and `providerMessageId` are not FHIR Communication elements. A delivery update would also become a new version of the resource. The record is therefore a platform node written by named queries (the way outbox and scheduled-work nodes are written), with the prompt's property names. The constructor is `Neo4jCommunicationRepository(tx)`; the `store` argument is not taken.
2. **Labels.** `(:Resource:Communication)`, as the prompt says. The `Resource.id` constraint from `0001_resource_id` covers it. Migration `0014_communication_id` adds `Communication.id IS UNIQUE`, and `0015_communication_provider_id` indexes `providerMessageId`. They were appended to `migrations.py`, which is G01's file; no existing migration was changed. The ids are `0014` and `0015` because P05 uses `0009` to `0013` and P08 uses `0009_scheduled_work_id` on their branches. Migration ids must be unique across all tasks; whichever of P05, P07 and P08 merges second will conflict on the end of `MIGRATIONS` in `migrations.py`, and that conflict is resolved by keeping every entry, in order.
3. **Status.** `status` is the FHIR Communication status: queued gives in-progress, failed gives not-done, and sent, delivered and received give completed. `deliveryStatus` holds the delivery status, from `DELIVERY_STATUSES` in `messaging.py`.
4. **Inbound records.** A record with delivery status `received` stores its time in `received`, and `sent` is absent. The read path takes `sent_at` from whichever is present.
5. **Shared concepts.** `TOPIC` and `MEDIUM` point at Concept nodes with the G03 key `Concept|<system>|<code>`, merged on that key, so they are the same nodes ResourceStore writes. Systems: `https://diucs.example/CodeSystem/message-id` and `https://diucs.example/CodeSystem/channel`.
6. **Recipient and subject.** The recipient is a `PractitionerRole` placeholder (`Resource` with `placeholder=true`, key `PractitionerRole/<id>`), created only when it does not exist, as G05 does for references. `about_id` is taken as a `HealthcareService` in this task. A Task or Observation subject needs a later decision.
7. **Replies are checked before any write.** A reply whose prompt is not stored raises `NotFound` before the first node is written (DEC-053 item 16): a caller that catches the error and commits leaves nothing stored, not even a placeholder. Tests `test_a_refused_reply_that_is_swallowed_and_committed_leaves_no_node`.
8. **Latest prompt.** `latest_prompt_for_phone` counts outbound records only (any delivery status other than `received`), newest `sent` first, ties broken by id. A failed send still counts as a prompt that was attempted. Owner to confirm the failed case.
9. **Refusals.** An unknown delivery status and a naive `sent_at` raise `ValidationFailed` before any write.
10. **Recording senders.** Every attempt takes the next number (`sms-1`, `email-1`, `push-1`), so a refused attempt also has an id. Only accepted sends are kept in `sent`. `fail_next()` refuses the next attempt only.
11. **Replay (DEC-012).** A retried `add` of the same record is a no-op and returns without a second write. The same id with different content raises `Conflict` and leaves the stored record unchanged. A racing duplicate that reaches the unique constraint also maps to `Conflict`. Tests `test_a_retried_add_of_the_same_request_succeeds_without_a_second_write` and `test_a_second_add_with_the_same_id_and_different_content_is_refused`.

Tests: `backend/tests/unit/adapters/testing/test_recording_senders.py` and `backend/tests/integration/graph_store/test_communication_repository.py` (run against the harness Neo4j).

## DEC-055 Audit log and provenance on one hash chain (P05)
Status: accepted (builder decision, owner to reconcile) · Affects: P05 (`application/ports/outbound/audit.py`, `application/actor.py`, `adapters/outbound/audit_neo4j/audit_log.py`), the migrations in G01's `graph_store/migrations.py`, `.importlinter`, and every use case that appends (P06, U-series, U42).

Numbered DEC-055: DEC-053 is the highest number on `main` and on every `task/*` branch when this was written (checked with `git show <branch>:docs/delivery/decisions.md`).

1. **One chain.** An `AuditEvent` and a `Provenance` record are both `ChainLink` nodes with `seq`, `previousHash`, `chainHash` and `entryJson` (the canonical text that was hashed). Audit and provenance share one sequence, so `verify_chain` covers both.
2. **Hash input.** `chain_hash = sha256((previous_hash + canonical text).encode())`, as the prompt gives. The record id is not in the hashed text. It is kept unique by constraint instead. Residual: an edited `AuditEvent.id` is not detected by `verify_chain`.
3. **What the chain checks beyond the hash.** The hash covers `entryJson` only. `verify_chain` also checks each chain node against its hashed text:
   (a) **Properties.** The node's own property names must be within the allowed set, and these properties must equal their values in the text: for an AuditEvent, `action`, `useCase`, `outcome`; for a Provenance record, `id` and `activity` and each extra property. The `recorded` instant is checked for both kinds (`AuditEvent.recorded` = `entry.at`; `Provenance.recorded` = the payload's `recorded`). The AuditEvent `id` is allowed as a name but its value is not checked (see residuals).
   (b) **Edges.** The node's outgoing edges are compared as sorted lists of (type, properties, target), so a missing, extra, duplicated or changed edge fails. Targets: SNAPSHOT is the snapshot hash and JSON; ENTITY is the entity id, one edge per distinct id (MERGE stores one edge however often an id repeats); AGENT is the agent id, with its `role` and `requestor` (audit) or `type` and `role` (provenance); TARGET is the target id; ACTIVITY is the Concept's `system|code`; ENTITY with role `source` is the source communication id, when given.
   Tests: `test_an_edited_audit_event_recorded_time_is_detected`, `test_an_edited_provenance_recorded_time_is_detected`, `test_a_retargeted_provenance_target_is_detected`, `test_an_edited_audit_agent_edge_is_detected`, `test_a_retyped_activity_concept_system_is_detected`, `test_an_honest_append_with_a_repeated_entity_id_verifies`, and the untampered positive test `test_an_untampered_chain_with_snapshot_entities_and_provenance_verifies`.
   **Residuals, not checked:** the value of the AuditEvent `id` (not hashed by the spec formula, item 2); the `kind` property of `AuditRef` nodes; the node properties of `Concept` and `Snapshot` nodes beyond the edge targets above; and any node or edge added or removed by a writer that bypasses this adapter (the Enterprise write restriction, item 17, is the intended control).
18. **Provenance wiring: builder decision, for the owner to confirm.** The prompt's out-of-scope line names the unit of work (P06), audit replay (U42) and export. It does not mention provenance wiring. As builder I decided that wiring provenance into write paths is a use-case concern, because use cases own each write and the unit of work they commit through is P06. This task provides `append_provenance` and calls it from no write path. Each use-case task that writes data wires provenance and tests it. The owner has not confirmed this; if the owner wants provenance wired here, that is a new change to this task.
4. **Head and serialisation.** `AuditHead` holds `lastHash` and `lastSeq`. Every append writes the head first (`SET _lock`) and reads `lastHash` after it (lesson L63), so appends queue on the head. This is a write hot spot by design. It is not measured here.
5. **Head creation is an explicit startup step.** `ensure_audit_head(driver)` creates the head if it is missing. Append does not create it, because creating it inside two concurrent first appends would race on the unique constraint. An append without a head raises `AuditHeadMissing`. The composition root must call `ensure_audit_head` after `apply_migrations`. That wiring is not part of P05 and is not done here.
6. **Audit references are `AuditRef` nodes, not `Resource` nodes.** The prompt says to MERGE placeholders for AGENT, ENTITY and TARGET. They are `AuditRef {id, kind}` nodes with a unique id, not `Resource` nodes. Reason: G05 owns `Resource` and its `Resource.id` is unique across all types (DEC-053 item 18). An id-only placeholder there would collide with a later FHIR write. The source Communication is also an `AuditRef` (kind `Communication`) until P07 defines the node. The activity is a `Concept` with `key` `Concept|system|code`, as G03 defines.
7. **Roles on edges.** ENTITY carries `role: "subject"` for each touched id, because `AuditEntry` has no per-entity role. AGENT carries `requestor: true` on audit events. For provenance, AGENT carries `type` (default `Practitioner`) and `role`. `append_provenance` takes an optional keyword `agent_type` after the contract's parameters, so the contract signature still works.
8. **Provenance activities** are `create`, `confirm`, `approve` and `call-back`, the list in the prompt. Any other activity raises `ValidationFailed("activity")`.
9. **Provenance extra properties** must match `^[A-Za-z][A-Za-z0-9]{0,63}$`, must not reuse a name the store uses (`id`, `recorded`, `activity`, `chainHash`, `previousHash`, `seq`, `entryJson`, `key`, `placeholder`, `lockStamp`), and carry a string, integer or boolean.
10. **`outcome` is the constant `recorded`.** `AuditEntry` has no outcome field (contracts.md). A rolled-back append leaves no node, so every stored event is a committed one.
11. **Snapshots** are `(:Snapshot {hash, json})`. `json` is the canonical JSON of the snapshot, and `hash` is its SHA-256. DEC-001's rule against `json` is about resources, not audit snapshots. The snapshot holds ids, numbers and words; keeping patient values out is the caller's job.
12. **Clocks.** `Neo4jAuditLog(tx, ids=None, clock=None)`. Provenance `recorded` comes from `clock` (default UTC now). An audit event's `recorded` is `entry.at`. Naive datetimes are refused (`ValidationFailed("at")`).
13. **Async.** The transaction is async, so `append`, `records`, `verify_chain` and `append_provenance` are `async`. The contract's sync signatures are read as async.
14. **`records(since=id)`** returns the records after that record's id. An unknown id raises `ValidationFailed("since")`.
15. **Import contract.** The audit adapter uses the G01 driver (`run_query`) and query registry (`REGISTRY`), which the spec names. The "Adapters are independent" contract forbids that import, so `.importlinter` has two `ignore_imports` entries, one for each module, and nothing wider. The architecture probe (`tests/architecture/test_import_rules.py`) now contains those two modules, so the ignore has a target there.
16. **Migrations 0016 to 0020** add unique constraints on `AuditEvent.id` (0016), `AuditHead.id` (0017), `AuditRef.id` (0018), `Provenance.id` (0019) and `ChainLink.seq` (0020). They follow P07's 0014 and 0015 in list order. They were numbered 0009 to 0013 on the P05 branch and renumbered to 0016 to 0020 when P05 was rebased onto `main` after P07 (lesson L68). The 0009 to 0013 numbers collided with P08's `0009_scheduled_work_id`. Nothing of these five was applied on `main` before the renumber, so no applied id changed. The migration count in `test_driver.py` is 15: main's 10 (0001 to 0008, 0014, 0015) plus P05's five. P08's `0009_scheduled_work_id`, if it merges after this, must be renumbered by P08 to follow 0020 (L68).
17. **Open: Enterprise write restriction.** Community cannot deny `SET` or `DELETE` by role. The adapter carries a TODO for role-based write restrictions. The Enterprise edition is still open (architecture.md).

Residuals, not fixed here: the `AuditEvent.id` is not hashed (item 2) and is not checked in item 3; `AuditRef` placeholders are not joined to `Resource` nodes (item 6); the head-lock throughput is not measured (item 4); the composition root does not call `ensure_audit_head` yet (item 5); no write path records provenance yet (item 18).

Tests: `backend/tests/unit/application/ports/outbound/test_audit.py`, `backend/tests/unit/adapters/outbound/audit_neo4j/test_audit_log_queries.py`, `backend/tests/integration/audit_neo4j/test_audit_log.py` (17 integration tests against the harness Neo4j).

## DEC-059 Geography and terminology port choices the prompt leaves open (P11)
Status: accepted · Affects: P11 (`application/ports/outbound/geo.py`, `terminology.py`, `adapters/testing/fixed_geo.py`, `fixed_terminology.py`), I11, I12, I15, R14, U12, R16 and every use case that calls these ports.

Numbered DEC-059. It was first written as DEC-057, which task/P08-event-bus-work also claims (lesson L70), and DEC-058 is task/P09-cache-port's. DEC-059 is the next free number on `main` and on every `task/*` branch (checked with `git show <branch>:docs/delivery/decisions.md`, lesson L43).

1. **File list.** The prompt's "Files this task owns" names three files. Its build section also names `adapters/testing/fixed_terminology.py`, and contracts.md places `FixedTerminology`, `PassThroughValidator` and the validator fake there. All four files are built. The prompt's file list is treated as incomplete; the owner should correct it.
2. **Sync and async.** `Geocoder`, `TravelTime`, `Terminology` and `FhirValidator` are `async`, because each is a network call or a remote service in production, matching the existing outbound ports (`SmsSender`). `PostcodeLocator` is synchronous: the centroid file is read into memory at start-up, so each lookup is local. The fakes follow the same signatures.
3. **TravelRange.** Refuses `low_minutes < 0` and `low_minutes > high_minutes` with `ValidationFailed("minutes")`. Equal bounds and zero are valid. `source` is kept as given and not checked.
4. **ValidationIssue.severity** is one of the four FHIR issue severities (`fatal`, `error`, `warning`, `information`; the `Severity` type in terminology.py). Any other value raises `ValidationFailed("severity")`, so a severity cannot be invented when a FHIR OperationOutcome is mapped.
5. **Postcode and district keys.** The postcode fakes normalise every table key and every query with the D19 rules (DEC-019, DEC-028), so `dt48xx`, `DT48XX` and `DT4 8XX` name one postcode. A query that is not a postcode returns `None` (or `[]` for geocoding): an unknown answer, never a guess. A table key that is not a postcode or district raises `ValidationFailed` when the fake is built, and the message names the field only (DEC-047). The real adapters (I11, I12) must normalise the same way.
6. **The travel-time table is directional.** `(origin, destination)` and `(destination, origin)` are separate keys, because architecture F8 gives patient to site and site to patient as two numbers. The reverse pair uses the default unless it is in the table. The table is copied at construction.
7. **ODS lookups** ignore case and surrounding spaces in the code. A record is returned as stored, including an inactive one (`active=False`); the caller checks `active`, because the rule "exists and is active" needs both the lookup and that check. Display names are matched on the exact `(system, code)`, since FHIR codes are case-sensitive. A record stored under a key that differs from its own code raises `ValidationFailed("code")`.
8. **Validator fakes.** `PassThroughValidator` returns `[]` for any resource and profile. It is the stand-in named in architecture.md ("Pass-through") until R14, and it is not a validation. `RecordingValidator` returns a copy of its preset issues on every call, and keeps a shallow copy of each call's resource and profile in `calls`.
9. **Red-commit stubs (DEC-010).** The red commit `48d6979` holds the port modules (Protocols and dataclasses) and the four fake modules as stubs whose methods raise `NotImplementedError`, so the failures are on the stubs and on the assertions. The `TravelRange` and `ValidationIssue` refusal tests fail on "DID NOT RAISE" in that commit.

Tests: `backend/tests/unit/application/ports/outbound/test_geo.py`, `backend/tests/unit/application/ports/outbound/test_terminology.py`, `backend/tests/unit/adapters/testing/test_fixed_geo.py`, `backend/tests/unit/adapters/testing/test_fixed_terminology.py`.

## DEC-061 The spring gap in the London time test helper is derived from the zone, not hard-coded to 2026 (F06 correction)
1. **Cause.** `is_spring_gap(day, local)` in `backend/tests/unit/domain/rules/test_london_time.py` returned True only for the constant `SPRING_CHANGE` (2026-03-29). The Hypothesis property `test_conversion_is_monotonic_within_a_day_outside_the_gap` draws any day from 2020 to 2040, so it reached other spring change days. On 2030-03-31 (Hypothesis seed 3) local 01:00 and 02:00 both map to 01:00Z, so the strict `<` failed. The production code in `diucs/domain/rules/london_time.py` is correct and was not changed.
2. **Fix.** The helper now returns True only for local times 01:00 to 01:59 on a day where the UTC offset is GMT at 00:30 local and BST at 02:30 local. Autumn days are False. The 2026 constant is kept for the existing examples and boundary tests, which are unchanged.
3. **Scope.** This is a test-helper correction to F06 (`task/F06-clock-ids`, delivered). `london_time.py` is untouched, so the F06 behaviour and the schedule tasks that rely on `london_to_utc` (lesson L4) are unaffected. The property now runs over every year from 2020 to 2040.
4. **Tests.** `test_spring_gap_is_recognised_on_the_2020_change_day` and `test_spring_gap_is_derived_from_the_zone_for_every_year` were added. All existing assertions are kept.

## DEC-058 Cache port: when a subscription starts, fencing tokens, and expiry (P09)
Status: accepted · Affects: P12 and I01 (Redis adapter and its contract suite), I03 (outbox relay lock), I05, U08 and every live-update consumer of `board.updates`.

The prompt fixes the cache names but leaves these choices open. The owner decided them as follows.

1. **`subscribe` registers when it is called, not on the first read.** `Cache.subscribe(channel)` is a plain method that returns an `AsyncIterator[str]`. An `async def` generator would register only on the first `__anext__`, so a publish made between the call and the first read would be lost, which the prompt's "a subscriber receives only messages published after it subscribed" does not allow. The Redis adapter (I01) must have its SUBSCRIBE complete before `subscribe` returns, or buffer from the call. Both must pass the same contract test.
2. **Fencing tokens are a per-name counter that only goes up.** Each successful `acquire_lock` takes the next number for that name. Releasing does not lower it, and a lock for another name starts at 1 on its own counter. The Redis adapter must take tokens from an `INCR` on a key that never expires. A token taken from a key with a TTL, or from a per-process counter, could repeat after a restart and break the rule that a later token is always greater.
3. **Expiry is an instant comparison in UTC, inclusive at the end.** A value set with a TTL is missing at `set time + ttl` and after. A lock is held while `now < expires_at` and free from `expires_at` on. The fake converts every instant with `astimezone(UTC)` before comparing (lesson L52), and a test crosses the 2026-10-25 clock change.
4. **Releasing a lock that is not the current holder's does nothing.** It raises nothing, so a holder that lost its lock to expiry cannot release a newer holder's lock. The caller must still check its own token before writing (fencing), because an expired holder can keep running.

Limits: `InMemoryCache` never evicts expired keys except when they are read, so an unread expired key stays in memory. The fake is for tests only (architecture.md, Platform decisions), so the memory held by unread expired keys does not reach production.

## DEC-057 Scheduled-work records, the event bus fake and the scheduled-work subject (P08)
Status: accepted (builder decision, owner to reconcile) · Affects: P08, U03, I02, I03, I05, and every task that schedules or cancels work.
Numbered DEC-057: this was first written as DEC-054, which P01 took on main (07d3f82). DEC-055 is P05 and DEC-056 is P07. DEC-057 is the next free number on main and on every `task/*` branch (checked with `git show <branch>:docs/delivery/decisions.md`).

1. **Location.** `EventBus`, `BusMessage`, `QUEUES`, `TOPICS` and `ScheduledWorkRepository` are in `application/ports/outbound/event_bus.py`, as the P08 prompt and `contracts.md` say. `WorkKind`, `ScheduledWork` and its status values are in `application/work.py`.
2. **Records refuse bad input at construction.** `ScheduledWork.due_at` must be timezone-aware (a naive time raises `ValidationFailed`), and `status` must be `scheduled`, `done` or `cancelled`.
3. **Subject key.** `about_id` is the subject's resource key (`Type/id`, DEC-053), matched on `Resource.key`. The subject is a placeholder `Resource` (`placeholder = true`, key only, no `id`) when it is absent. It is not matched or created by `id`: `Resource.id` is unique across all resource types (DEC-053 item 18), so a placeholder with an id would block the resource writer on its first write. The P08 tests use opaque keys such as `booking-1`. Callers must pass the exact key the resource writer uses.
4. **Retry-safe add.** `add` on an id that is already stored with the same values changes nothing. With different values it raises `Conflict` and writes nothing. This keeps a driver retry of a committed write safe (DEC-012).
5. **Store parameter.** `Neo4jScheduledWorkRepository(tx, store)` takes the `QueryRegistry` that holds its named queries (default: the module registry). `run_query` gained an optional keyword `registry`. When it is not given, the module registry is looked up at call time, so the G01 test that replaces the module registry still works.
6. **Migration `0009_scheduled_work_id`** makes `ScheduledWork.id` unique (DEC-012: one record per id).
7. **Bus fake (`ManualEventBus`).** `publish` refuses a topic that is not in `TOPICS`. A `capacity.events` message without a `session_id` is refused, because the service id is the session id (architecture.md). `schedule` refuses a queue that is not in `QUEUES` and a naive enqueue time. `due(now)` compares UTC instants; with no `now` it reads the injected clock. Delivered and cancelled messages are removed. Sequence numbers start at 1 and are never reused. Cancelling an unknown or delivered number does nothing.
8. **Stored times.** Every `dueAt` is written in UTC. Read-back returns a UTC datetime (lessons L52, L61).
9. **Migration id and count.** `0009_scheduled_work_id` is unused on main and on every `task/*` branch (checked with `git show <branch>:backend/src/diucs/adapters/outbound/graph_store/migrations.py`). It sits between `0008` and `0014` in `MIGRATIONS`, so the list stays in ascending order (lesson L68). With P05 and P07 merged, `MIGRATIONS` has 16 entries, and `EXPECTED_MIGRATION_COUNT` is 16. The earlier pin of 9 was stale.
10. **Refusals leave zero nodes (DEC-053 item 16).** `add` checks for the id before its first write, so a conflicting add is refused with no node written, and `save` on an unknown id matches nothing and writes nothing. The tests refuse inside a unit of work, swallow the error, and commit, then count the nodes.
11. **Exact subject matching (verifier round 3).** `for_about` matches the subject key exactly. The test `test_work_is_found_only_for_its_exact_subject_key` stores `svc-1` and `svc-10` and checks that each query returns only its own record, and that a trailing space, a truncated key and a case variant return nothing. A prefix match on the key fails it.
12. **Residual: two nodes for one subject key (owner note, not resolved here).** P08's placeholder subject is a `Resource` with only the `Resource` label (DEC-053 item 18 keeps `id` off it). P07's `Q-COMM-LINK-ABOUT` MERGEs on `Resource:HealthcareService` and so creates a second node with the same key. The verifier's probe confirmed two nodes. `for_about` still returns the right records, so there is no cross-resource leak. The duplicate is a real residual: the typed MERGE in P07's communication repository must match on the key with the placeholder convention from G05 (`resource_store.py`), or the placeholder must be typed on first write. The task that must reconcile this is P07's communication repository (`Q-COMM-LINK-ABOUT`); it is delivered, so the fix needs a follow-up task that the owner names. Until then, no code path should rely on one node per key for a subject.

Tests: `backend/tests/unit/application/test_work.py`, `backend/tests/unit/adapters/testing/test_memory_event_bus.py`, `backend/tests/integration/graph_store/test_scheduled_work_repository.py`.

## DEC-062 Owner decisions closing the six open items (DEC-029, 035, 040, 047, 048, 055)
Status: accepted by the owner's delegation (orchestrator decides, sign-off at the end of the build) · Affects: D05, D17, D20, D28, U04, U12, G11, D08, P05, and every write task that appends audit or provenance.

The owner asked for these items to be decided and the open markers closed. Items 2 and 4 change code or text, and the follow-ups are listed. The clinical `[ASSUMED]` values and the printed wording still get a human sign-off at the end of the build, as the owner has said.

1. **DEC-048, grouping window.** `GROUP_WINDOW = 10 min` stays as it is, as a named `[ASSUMED]` constant in `domain/rules/multi_service.py`. Keep it as a single constant so a change is one edit. Clinical safety sign-off of the `[ASSUMED]` values is part of the end-of-build review.
2. **DEC-047 item 9, printed need wording.** Print a plain-English label for each `NeedCategory` code, from one table, and never the raw code. Labels: `fall-no-injury` → "fall, no injury"; `frailty` → "frailty"; `wound-care` → "wound care"; `iv-therapy` → "IV therapy"; `palliative` → "palliative care"; `dementia` → "dementia"; `suspected-fracture` → "suspected fracture"; `head-injury-anticoagulants` → "head injury on anticoagulants"; `infection-isolation` → "infection or isolation". A case with two needs joins the labels with ", " and "and" as the last join. Urgency and age band print as their existing values. Follow-up: B1 currently prints the code (`Age 80+, frailty, within 2 hrs`), and the sample in `docs/spec/ui-screens.md` line 1078 still reads "fall and frailty". The template change is a small follow-up to D17, not made in this decision. Information governance sign-off of the printed wording is at the end of the build.
3. **DEC-029, Monday-overdue reading.** Accepted as written in DEC-029: no report ever, and a Monday before the first due is overdue from Friday 19:00Z (`was_due` Friday, `age` None). This follows the rule book (domain-rules 1.5), and the fail-safe principle outweighs the prompt's expectation. The rule for a service's reporting start date waits for the registration date (D13 and the P tasks). Nothing in the profile holds it today, so it is not designed here.
4. **DEC-040, pressure type check.** Accepted as written. Only exact `Status` members are counted. Any other value, including a plain string with the same value, raises `TypeError`. This follows the refuse-rather-than-drop rule (DEC-049), so no caller can under-count pressure by passing the wrong type.
5. **DEC-035, active versus suspended split.** Accepted as written. G11 (`candidates`) excludes inactive and suspended services, U12 lists suspended services under "not suitable", and the criteria filter does not repeat the check. A suspended service is never offered to a call advisor. U12 must depend on G11, as DEC-035 item 6 says.
6. **DEC-055 item 18, P05 scope.** P05 covers the hash-chained audit log, the provenance record on the same chain, and `verify_chain`. It does not wire provenance into any write path. Each use-case task that writes data calls `append_provenance` and tests that it does. Retention and export are outside P05.

Follow-ups this decision creates (none block Stage 2): the B1 label table (item 2), the wording sample in `ui-screens.md` line 1078, and the provenance wiring tests on each write task (item 6).

## DEC-060 Link-token store, phone hashing and the single-use write (P10)
Status: accepted · Affects: P10 (`application/ports/outbound/tokens.py`, `application/ports/outbound/identity.py`, `adapters/outbound/graph_store/link_token_repository.py`, `adapters/testing/fixed_secrets.py`, migration 0021); L01, U25 onward (token use), P16 (contacts).

Numbered DEC-060: DEC-057 is claimed on task/P08-event-bus-work, DEC-058 and DEC-059 on task/P11-geo-terminology-ports (unmerged), so DEC-060 is the next free number above every branch (lesson L32). Checked with `git show <branch>:docs/delivery/decisions.md` on main and every task/* branch.

The P10 prompt and contracts.md leave these points open or need a decision:

1. **Migration 0021_link_token_hash.** A unique constraint on `(:LinkToken).tokenHash` is appended as migration 0021. 0021 is unused on main and every branch (L68). Two existing tests pinned the list shape and are updated in the same commit: `test_migration_ids.py` no longer requires the audit migrations to be the last five entries (it requires them to be contiguous and in order after 0015, and 0021 to follow them), and `test_driver.py` `EXPECTED_MIGRATION_COUNT` goes from 15 to 16. Nothing applied is edited.
2. **The node id is the token hash.** `LinkTokenRecord` has no id, and a second random id would need a generator in the port. The hash is not secret text (it is an HMAC of the token), so `id = tokenHash` adds no exposure.
3. **Neo4j stores no null property.** An unused link has no `usedAt` key; a link without a phone has no `phoneHash` key. Readers treat a missing key as null. Tests assert the documented property set minus the keys that are null.
4. **`mark_used` takes the lock first.** The prompt's query (`MATCH ... WHERE usedAt IS NULL SET usedAt`) is not atomic under concurrent callers. Measured on the harness Neo4j, the concurrency test returned True for 8 of 8 callers, then 16 of 16, because the WHERE reads before any write lock is held. A no-op `SET usedAt = usedAt` does not fix it either, since setting a missing property to null takes no lock. The stored query sets `tokenHash` to its own value first (a real write to a property that always exists), then reads `usedAt IS NULL` and sets it. The test (`test_concurrent_mark_used_lets_exactly_one_caller_win`, 5 rounds of 16 callers) passed on three repeated runs. The first two query versions failed that test; the failed versions are recorded here because the pattern applies to every single-use write (L63 family).
5. **Phone normalisation accepts UK mobiles only.** `normalise_uk_mobile` accepts the national form (`07700 900123`), `+44` (with or without `(0)`) and `0044`, removes spaces, hyphens, brackets and dots, and requires eleven digits starting `07`. Anything else, including a landline, is `ValidationFailed` on the field `phone`, with a fixed message that never echoes the number (H-09, DEC-047 privacy rules).
6. **Secret names are fixed:** `link-token` for the token HMAC and `phone-hash` for the phone HMAC (domain-rules 7 and the prompt). `FixedSecretStore.get` on an unknown name raises `NotFound`, naming the secret and never its value.
7. **`add` refuses a duplicate before the write.** A second add of the same hash is `Conflict`, decided by a read first, so a refused add leaves zero nodes (DEC-053 item 16). A constraint violation from a racing add is mapped to `Conflict` too.
8. **`resolve` treats malformed text as unknown.** A value that cannot be a token (not URL-safe, per D26 item 4) returns `None`, the same as an unknown token. Callers never get a validation error for text from a link.
9. **`burn` rules.** Unknown or malformed text is `NotFound`; a token already used is `Conflict` and changes nothing; a first burn sets `usedAt` to the clock's `now`. `burn` does not check expiry: the caller (L01, U25 onward) must run `check_link` first, as DEC-045 item 8 requires. This is a deliberate split, so the service stays one-purpose.
10. **Where the concrete classes live.** The prompt puts `LinkTokenService` and `HmacPhoneHasher` in `application/ports/outbound/`. They are kept there as the prompt says. They import only the standard library, `diucs.domain` and `diucs.application`, so the import rules (DEC-011) hold.
11. **The phone field holds only a hash (round 2, verifier finding).** `LinkTokenRecord` refuses any `phone_hash` that is not 64 lower-case hex characters (`check_phone_hash`, `domain/rules/tokens.py`), so a phone number, a name or a postcode cannot be stored through the record. The repository runs the same check before its first read or write, so a refused add leaves zero nodes (H-09, DEC-047). The D26 unit test sample `"sample-phone-hash"` becomes `"ab" * 32`.
12. **A retried burn is idempotent (round 2, DEC-012).** `burn(token, key)` takes a key that names one attempt (for example a request id). The first burn sets `usedAt` and `burnKey`. A replay with the same key on a used token returns the original result without a write. A different key on a used token is `Conflict`. Unknown or malformed text stays `NotFound`. Callers must reuse the key on retry. The `burnKey` property exists only after a burn.
13. **Query added:** `Q-LINK-BURN-KEY` (read) returns the burn key. `Q-LINK-MARK-USED` writes `burnKey` with `usedAt`, still lock-first.

## DEC-063 Booking Task mapping: derived properties, backbone restriction and output, and the racing add (P02)
Status: accepted (builder, for the owner to confirm) · Affects: P02 (`domain/model/booking.py`, `adapters/outbound/graph_store/booking_repository.py`, two entries in the mapper's backbone table); U17 to U22 (booking use cases); P13 (Task registration uses the same businessStatus shape); P21 (cases, which `focus` points at).

Numbered DEC-063: DEC-062 is the highest number on main and on every task/* branch, and no branch claims DEC-063 (checked with `git show` on each branch, lesson L43).

The P02 prompt and fhir-data-model.md "Booking" leave these points open or cannot be built as written on the existing mapper:

1. **businessStatus is a property, not a relationship.** FHIR `Task.businessStatus` is a CodeableConcept, which the mapper stores as a Concept relationship. The prompt's query (`Q-BOOK-PENDING`) matches a string property `businessStatus`. The repository writes the status code to that property after the store's put, in the same transaction, and does not send the concept to the mapper, so there is one copy. `read_task_fhir` turns the property back into the CodeableConcept. The mapper refuses a property with the same name as an element (`_check_element_name`), so the mapper is not changed for this.
2. **reference is a copy of the identifier value.** The spec asks for it, so the repository sets `Task.reference` after the put. The identifier stays the source; `read_task_fhir` drops the copy when it rebuilds the resource.
3. **restriction and output are backbone elements.** The mapper cannot store `restriction.period` (nested) or `output` (a list of mixed entries) without a backbone entry. Two entries were added to the backbone table: `("Task", "restriction")` as `Task_Restriction` with `HAS_RESTRICTION`, and `("Task", "output")` as `Task_Output` with `HAS_OUTPUT`. This is the G04 pattern. The reply-by time is therefore the child property `periodEnd`, not the Task property `restrictionPeriodEnd` that the spec table names.
4. **output entries.** `decision` (valueCodeableConcept = the booking status) is present for every booking that has moved. `reason` (valueString = the free-text reason) is present when a reason is set. The spec says "reason concept", but `Booking.reason` is free text, so no code system is applied. `confirmed-at` (valueDateTime) is present when confirmed_at is set. The output type codes use the system `CodeSystem/booking-output-type`, a local system that is not yet in contracts.md. Owner to add it to the code-system list or to supersede this item.
5. **confirmed_at has no property of its own.** It lives in the `confirmed-at` output entry. `confirmed_since` finds the confirmed Tasks of the service with `Q-BOOK-CONFIRMED-SINCE`, loads each one, and filters in Python. A Cypher filter would need a join through a child node. Revisit if the board needs it at scale.
6. **lastModified** is `responded_at`, or `requested_at` when nothing has responded. Booking has no field of its own for it.
7. **executionPeriod** runs from `requested_at` to `responded_at`. A confirmed booking ends at its confirmation, and a cancelled one ends at the cancellation. The end moves with every status change.
8. **statusReason** comes from D13 `to_fhir`, coded in the booking-business-status system (`expired` and `withdrawn` are BookingStatus codes).
9. **open_for_services** returns every requested service id as a key, with `[]` when it has no open booking, and orders by `authoredOn`.
10. **get_by_reference** returns the most recently requested booking with that reference (`authoredOn` descending, then id). Uniqueness of open references is enforced at request time by U17 (lesson L29), not by this repository.
11. **add of an existing id is Conflict, save of an unknown id is NotFound.** The store's own version check does both (expected version None for add; the stored version for save).
12. **A racing add of one booking id lets exactly one caller win.** Sixteen concurrent adds in the harness give one success and fifteen Conflicts. This test passed on its first run, so it was not seen to fail first. It is recorded as such in the evidence file.
13. **Booking datetimes must be timezone-aware.** A naive datetime is `ValidationFailed`. They are written as UTC with `Z` (lessons L52 and L56), and read back as UTC.

Not decided here, and still open: whether `Task.statusReason` should use a separate reason code system once the decline, withdraw and cancel reasons are stored (P02 keeps the status codes only); whether the output type needs a contracts.md entry (item 4).

## DEC-064 People on Neo4j: practitioners, posts, cover and the phone lookup (P03)
Status: accepted (builder, for the owner to confirm) · Affects: P03 (`domain/model/people.py`, `adapters/outbound/graph_store/person_repository.py`, `application/ports/outbound/repositories.py`), P13, P16, U16, U37, U38 and every inbound-text use case that resolves a phone; G04 (`mapper.py` backbone table, `extensions.py`); G05 (`resource_store.py` `_load`); F07 (`codes.py`, `tests/unit/domain/test_codes.py`).

Numbered DEC-064: DEC-063 is the highest number on main and on every task/* branch (checked with `git show <branch>:docs/delivery/decisions.md` for each branch, lesson L43), and no branch claims DEC-064.

The P03 prompt and the specs leave these points open, or cannot be built as written on the existing store and mapper:

1. **phoneHash and emailDomain are root node properties, not FHIR.** They are set by `Q-PERSON-SET-PROPS` after the store put, in the same transaction, and taken out of the rebuilt resource when read. The prompt's test `node_props("Practitioner", id="p1")["phoneHash"]` needs this exact name; an extension would be stored as `ext_phoneHash`. An absent hash is no property at all (lesson L74), so `SET p.phoneHash = null` removes it. The phone number is never passed to the repository.
2. **The Practitioner FHIR form has no telecom and no phone hash.** `practitioner_to_fhir` omits both. `practitioner_from_fhir(resource, phone_hash, email_domain)` takes the graph properties as arguments, so the pure round trip is exact. The same pattern is DEC-063 item 1 (businessStatus).
3. **Practitioner.name is one HumanName `text` entry**, mapped as a backbone child (`Practitioner_Name`, `HAS_NAME`). One mapper table entry was added. The mapper refuses a HumanName without it (G04 pattern, as DEC-063 item 3).
4. **The role code is an enum.** `PractitionerRoleCode` is a StrEnum in `domain/codes.py` with code system `practitioner-role`. The prompt says `code: str`. The field is typed as the enum, and `PractitionerRole.__post_init__` refuses a plain string or a member of another enum with the same value (lessons L3 and L38). `contracts.md` does not list this enum or its code system, and this task must not edit `docs/spec/`. Owner to add both to `contracts.md`. The expected values in `tests/unit/domain/test_codes.py` were added to the spec list in the same commit.
5. **Cover is stored twice, as the spec asks.** The extensions `coveredBy` (string) and `coveredUntil` (dateTime) are registered in the G04 registry, which goes from fifteen names to seventeen (lesson L66; `test_extensions.py` updated). `COVERED_BY {until}` is written after the put by `Q-ROLE-COVER`. The cover practitioner is checked before the write, and a missing one is `NotFound`.
6. **Channel is stored twice.** The extension `channel` (registered by P01) and `CHANNEL` to a Concept. The Concept is `Concept|<system>|<code>`, merged on system and code, with display set on create only, so a shared Concept is never overwritten (DEC-051 item 1 pattern). The mapper does not write CHANNEL, so the repository does.
7. **Local relationships are skipped on read (G05 change).** `ResourceStore._load` now skips a relationship with no `fhirPath`. Without this, `get` raised KeyError on CHANNEL and COVERED_BY, because `from_graph` groups relationships by `fhirPath`. Every put still clears the root's outgoing relationships (`Q-RES-CLEAR-ROOT-RELS`), so a save with no cover removes COVERED_BY (test `test_saving_a_role_without_its_cover_removes_the_covered_by_relationship`). The skip has no other effect: mapper-written relationships always carry `fhirPath`.
8. **Refusals come before the write.** `save_role` checks that the practitioner, the service and the cover practitioner exist (`NotFound`) before `store.put`, so no placeholder node is created (DEC-053 item 16, lesson L68). The tests catch the refusal and commit, so a write made before it would persist. Each check has a test that fails when the check is removed (see the mutation check in `docs/delivery/evidence/P03.md`).
9. **Phone lookup.** `services_for_phone_hash` is the union of `Q-PHONE-SERVICES-HELD` (query #3: active reporter roles the phone holds and that are not covered out of at `now`) and `Q-PHONE-SERVICES-AT` (the roles the phone covers until after `now`). Each role is loaded through the store and filtered in Python: active, reporter code (`REPORTER_ROLE_CODES`), and in effect (item 10). The phone's practitioner must be active. The returned `str` is the HealthcareService name, because query #3 returns the name. Results are sorted by service id, as the prompt's build text says. Query #3 itself says `ORDER BY s.name`, so the two differ, and the build text was followed. **Superseded by DEC-065 item 2:** results are now sorted by service name, then service id, then role id.
10. **Period.** The rule book is silent on periods. A role is in effect from `period_start` (inclusive) to `period_end` (exclusive) when it has one, and every reporter or service lookup applies this at `now`. A role not yet started or already ended gets no prompts. Owner to confirm.
11. **Ambiguous phone.** `find_by_phone_hash` returned the active practitioner with the lowest id when two shared a hash. **Superseded by DEC-065 item 1:** it now raises `Conflict` and returns nothing.
12. **reporter_roles_for_service** returns covered roles as stored. The caller resolves the holder with `role_holder(role, now)`, so the cover rule lives in one place.
13. **Racing saves.** Sixteen concurrent saves of one new practitioner give one save and fifteen `Conflict`. The store's lock and version check decide this (DEC-053 item 4). No application-level check is needed or added for `save_practitioner`, which is an upsert.
14. **No migration.** The `Practitioner.phoneHash` index is migration `0007_phone_hash` and already exists. `EXPECTED_MIGRATION_COUNT` is unchanged.
15. **Times.** Stored as UTC with `Z`, fraction digits without trailing zeros, which the store reads back identically (DEC-053 item 2). A naive datetime, or a FHIR datetime with no zone, is `ValidationFailed`.
16. **Port.** `PersonRepository` is added to `application/ports/outbound/repositories.py` with the seven methods the prompt lists. No other port in that file is changed.

Verified by: `tests/unit/domain/model/test_people.py`, `tests/unit/adapters/outbound/graph_store/test_person_mapping.py`, `tests/integration/graph_store/test_person_repository.py` (16 integration tests and 9 pure mapping tests), plus the people model tests (14) and the updated codes and extension tests. Not decided here: whether a role's period should ever gate prompts (item 10), and the entries `contracts.md` needs for `PractitionerRoleCode`, its code system and the two cover extensions (item 4 and item 5).

## DEC-065 Owner decisions and input checks on people (P03, round 2 after the verifier's FAIL)
Status: accepted (owner decisions in items 1 and 2; input checks in items 3 to 5 are the builder's, for the owner to confirm) · Affects: P03 (`domain/model/people.py`, `adapters/outbound/graph_store/person_repository.py`), G05 (`resource_store.py` `_load`), DEC-064 items 9 and 11 (superseded in part, see below); P13, P16, U16, U37, U38 and every inbound-text use case that resolves a phone.

Numbered DEC-065: DEC-064 is the highest on main and on every task/* branch, and no branch claims DEC-065 (checked with `git show` for each branch, lesson L43).

1. **Ambiguous phone is refused (owner decision).** `find_by_phone_hash` raises `Conflict` and returns nothing when two active practitioners share one phone hash. It no longer picks the lowest id. This supersedes DEC-064 item 11. The repository does not refuse the second save: a shared hash is a data fault that the lookup reports, and the owner decides how it is resolved.
2. **Services are ordered by name, then service id, then role id (owner decision).** `services_for_phone_hash` follows query #3's `ORDER BY s.name`, with service id and role id as tie-breaks. This supersedes DEC-064 item 9's sort. The returned name is the sort key.
3. **The phone hash must be 64 lowercase hex characters, or None (builder, verifier finding 1).** `check_phone_hash` runs in `Practitioner.__post_init__`, and again at both phone lookups (`find_by_phone_hash`, `services_for_phone_hash`), so a malformed value is refused before any query runs. A refusal is `ValidationFailed` naming the field `phone_hash` only. The value is never echoed, because a probe such as `07700900123` is a phone number. A refused write is refused in the Practitioner constructor, before the repository is called, so it leaves zero nodes (test `test_a_raw_phone_number_cannot_become_a_practitioner_and_writes_nothing`).
4. **The email domain must be a bare domain (builder, verifier finding 2).** `check_email_domain` runs in `Practitioner.__post_init__`. The domain is lowercase letters, digits and hyphens, with at least one dot. A value with `@`, a space, uppercase, no dot or a trailing dot is refused as `ValidationFailed` naming `email_domain` only, never echoed. The refused address `jane.doe@nhs.example` is one such test.
5. **The local-relationship skip is limited (builder, verifier finding 3).** `ResourceStore._load` skips a relationship with no `fhirPath` only when its type is in `LOCAL_RELATIONSHIP_TYPES`, which is `CHANNEL` and `COVERED_BY`. Any other relationship with no `fhirPath` is kept, so `from_graph` raises `KeyError`. Both halves are tested: `test_a_relationship_without_a_fhir_path_that_is_not_local_still_fails_the_read` (a `STRAY` relationship raises `KeyError`) and the existing cover and channel tests (the named types are skipped and the role still reads).

Tests: `tests/unit/domain/model/test_people_round2.py`, `tests/integration/graph_store/test_person_round2.py`. Existing person tests use valid 64-character hashes in place of the earlier placeholder strings.
