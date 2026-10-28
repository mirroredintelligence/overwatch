# Lessons learnt

Newest last. Add one with: python delivery.py lesson add ...

## L1 On Windows set PYTHONIOENCODING=utf-8 before lint-imports

By build-F01 on 2026-10-24T13:58:26.666933+00:00. Applies to: F01, F02, F04, F05.

lint-imports crashes with UnicodeEncodeError (cp1252) on the Windows console when it prints its spinner or an error. Exit code is then 1 even when the contracts pass. Run it as: PYTHONIOENCODING=utf-8 uv run lint-imports. Also: make is not installed on this Windows machine, so Makefile targets cannot run here; run the underlying commands and say so in evidence.

## L2 Red commits may contain stubs (DEC-010)

By orch on 2026-10-24T14:00:36.738615+00:00. Applies to: F01, F02, F03.

A red commit may hold a minimal stub so tests fail on assertions, not import errors. See decisions.md DEC-010. Verifiers: check the red run fails on assertions.

## L3 StrEnum members from different enums with the same value compare equal, so key lookups by (enum class, value)

By build-F07 on 2026-10-24T15:20:43.512558+00:00. Applies to: F07.

StrEnum members are str subclasses. ServiceCategory.OTHER == ReferrerType.OTHER is True, and their hashes match, so a dict keyed by member can return the wrong entry across enums. Key per-enum lookups by (type(member), member.value), and take the coding system from type(member), never from the value alone. Found while building F07 (diucs/domain/codes.py); test: test_same_value_in_two_enums_keeps_its_own_coding.

## L4 London clock change: local 01:00-01:59 on 2026-03-29 is not monotonic

By orch on 2026-10-24T15:23:11.786331+00:00. Applies to: D03, D04, U03, I03.

On 2026-03-29, local 01:00-01:59 maps to 02:00-02:59 BST, and local 02:00 maps to the same instant as local 01:00. Wall-clock order is not monotonic across the gap. Schedule builders (D03, D04) must not place a due time inside 01:00-02:00 on that date, and must compare instants, never local times. Use london_time.london_to_utc from F06. Found by F06.

## L5 Service Bus emulator image has no shell, so it cannot run its own healthcheck

By build-F04 on 2026-10-24T16:14:11.978462+00:00. Applies to: F04, F05, F10.

The emulator image (servicebus-emulator:2.0.1) has no /bin/sh, bash or curl; docker exec and a shell healthcheck both fail. Its /health endpoint on port 5300 returns 200 when ready. F04 uses a probe container (servicebus-ready, the SQL image, which has bash) that polls http://servicebus-emulator:5300/health, so up --wait waits for the emulator. Use the same pattern for any service that ships without a shell. The emulator needs SQL Server 2022 (mssql/server), not Azure SQL Edge, per current MS docs.

## L6 Duplicate detection on inbound.replies makes a repeat send of the same id fail for 20 seconds

By build-F04 on 2026-10-24T16:14:12.110233+00:00. Applies to: F04, F10, I01.

Queue inbound.replies has RequiresDuplicateDetection true with DuplicateDetectionHistoryTimeWindow PT20S. The smoke test sends message id smoke-1 each run, so a second run within 20 seconds receives nothing and fails. Wait 20 seconds, or use a unique id in tests that send to inbound.replies (the F10 harness should do this). Documented in infra/README.md.

## L7 docker compose restart returns before Neo4j accepts connections

By build-F04 on 2026-10-24T16:14:12.239184+00:00. Applies to: F04, F10, G01.

After docker compose restart neo4j, the container is Up but its healthcheck is still starting, so an immediate cypher-shell or driver call gets connection refused. Run docker compose -f infra/docker-compose.yml up -d --wait neo4j (or poll health) before connecting. Data does persist across restart; down -v removes it.

## L8 Neo4j rejects a data write in the same transaction as a schema change

By build-G01 on 2026-10-24T17:08:53.049331+00:00. Applies to: G14, F10, P06, P15, G02.

Running CREATE CONSTRAINT/INDEX and a MERGE in one managed transaction fails with Neo.ClientError.Transaction.ForbiddenDueToTransactionType (Tried to execute Write query after executing Schema modification). Do it instead: run the schema statement in its own execute_write, then the bookkeeping write in a second one. Both must be idempotent (IF NOT EXISTS, MERGE). See backend/src/diucs/adapters/outbound/graph_store/migrations.py.

## L9 Run an isolated Neo4j beside the shared stack with a port override file

By build-G01 on 2026-10-24T17:08:53.197797+00:00. Applies to: F10, G14, I01, P01.

Start a second stack without touching diucs-local: docker compose -p diucs-<id> -f infra/docker-compose.yml -f <override.yml> up -d --wait neo4j, where override.yml sets services.neo4j.ports to '!override' with free host ports (for example 17474:7474 and 17687:7687). Point NEO4J_URI at that port. Tear it down with: docker compose -p diucs-<id> -f ... down -v. Never run a wiping test against the default 7687 port.

## L10 The Neo4j driver logs the Cypher text of every server warning

By build-G01 on 2026-10-24T17:18:47.248154+00:00. Applies to: O01, F10, G14, I01, P06.

A query that triggers a server warning (for example an unknown label) makes the driver log WARNING from logger neo4j.notifications, with the full query: for query: 'MATCH ...'. The neo4j.io logger writes Bolt messages, including RUN with the Cypher text, at DEBUG. Fix: create the driver with notifications_min_severity='OFF' (done in create_driver), and keep the neo4j loggers at INFO or above in logging config (O01). Test: tests/integration/graph_store/test_driver.py::test_run_query_logs_no_cypher_text_even_when_the_server_warns.

## L11 Neo4j tests: the harness owns the container; wipe only through the harness driver

By build-F10 on 2026-10-24T17:50:01.434844+00:00. Applies to: G14, P06, I01, I05, P15, F04, G01.

F10 starts a throwaway Neo4j per pytest session (docker run, free port, unique name) and sets NEO4J_URI for that session (DEC-013). NEO4J_URI from the shell is ignored by the harness. Three traps found: (1) pytest collection hooks that call add_marker(usefixtures) are too late, because the fixture closure is built at collection; append the name to item.fixturenames instead (pytest-asyncio does the same). (2) A test module that defines its own module-scoped neo4j_driver (test_infra_up.py does, for the compose stack) overrides the name, so clean_graph must depend on harness_driver, not neo4j_driver, or it wipes the wrong instance. (3) Async fixtures cannot call getfixturevalue on another async fixture (nested loop); use a plain fixture dependency. G01 test_driver.py now uses the session neo4j_driver; its module fixture was removed. Use loop_scope session for tests that use the driver.

## L12 Container holds Neo4jConnection; call startup() before use

By orch on 2026-10-24T17:52:04.095137+00:00. Applies to: P06, I03, I05, I08, R01.

container.neo4j replaces container.neo4j_driver (G14). Call container.startup() before any use and container.shutdown() on exit. The driver is reachable only through the connection; use connection.session(), run_read or run_write. Tasks affected: P06, I03, I05, I08, R01.

## L13 In-flight reads fail about 30 s after Neo4j stops, not at once

By orch on 2026-10-24T17:52:04.279810+00:00. Applies to: I03, I05, I08, G14.

The driver retries managed transactions for about 30 s before a read raises a retryable error (measured in G14). Workers and health checks must budget for that delay and must not treat a 5 s timeout as proof of failure during a restart.

## L14 Correction to L13: in-flight failure takes about 31 to 43 s, not 30 s

By orch on 2026-10-24T18:44:53.074080+00:00. Applies to: I03, I05, I08, G14.

L13 said an in-flight managed transaction fails about 30 s after Neo4j stops. Measured across G14 runs: 31.3, 32.1, 41.7 and 42.6 s. Budget for 31 to 43 s, and never treat a shorter timeout as proof of failure during a restart. First successful call after restart: 8.4 to 17.3 s.

## L15 Design system contradicts itself on sheet duration and caption size (DEC-015)

By build-X02 on 2026-10-24T19:59:49.867558+00:00. Applies to: X02, F09.

docs/design/design-system.md section 5.2 says UI motion is under 300 ms, but --dur-sheet is 320 ms. Section 3 says nothing is below 16 px, but Caption is 14 px. X02 copies the table values and records both in DEC-015 for the owner. Do not silently clamp either value: use the table value and cite DEC-015, and check captions against the 16 px rule when they are used.

## L16 pnpm build rewrites frontend/next-env.d.ts; revert it before committing

By build-X02 on 2026-10-24T19:59:50.086624+00:00. Applies to: X02, F09.

next build modifies frontend/next-env.d.ts in the worktree. It is not part of any task. Run git checkout -- frontend/next-env.d.ts after a build, or git status will show it as a stray change before the commit.

## L17 usual_range is one (min, max) tuple; domain-rules 1.1 still lists two fields (DEC-016)

By build-D01 on 2026-10-24T20:09:08.753744+00:00. Applies to: D01, D05, D07, D11, P13.

contracts.md and the D01 prompt define ServiceProfile.usual_range as one tuple[int, int]. domain-rules.md 1.1 lists usual_range_min and usual_range_max. Build the tuple. DEC-016 records the deviation; the owner should update 1.1 or supersede DEC-016. Check D05, D07 and D11 use the tuple.

## L18 Harness container is restartable: use harness_container to stop and start Neo4j in tests

By build-F11 on 2026-10-24T20:11:40.046469+00:00. Applies to: I01, I03, I05, I08, R01, P06.

The F10 harness container is started without --rm (F11), so it survives docker stop and docker start on the same port with its data. To test recovery, take the session fixture harness_container (a ThrowawayNeo4j) and call stop_container(c), then start_container(c), then wait_until_ready(c) before connecting: docker start returns before Neo4j accepts connections (L7). Always start the container again in a finally block. Do not start your own restartable container; the recovery_neo4j workaround in G14 is gone. harness_driver, harness_container and clean_graph are unchanged. Found by F11.

## L19 L17 cites DEC-016; the usual_range decision is DEC-017

By build-D01 on 2026-10-24T20:17:32.999143+00:00. Applies to: D01, D05, D07, D11, P13.

Correction to L17. The usual_range decision (one tuple, not min and max fields) is DEC-017 in docs/delivery/decisions.md. DEC-016 is D09's reply-reference entry. Read DEC-017 for the rule.

## L20 tokens.test.ts reads expected values from design-system.md; a DEC override must change the test, not only the CSS

By build-X03 on 2026-10-24T21:09:19.791566+00:00. Applies to: X03, F09, X02.

frontend/app/tokens.test.ts builds SPEC from the token tables in docs/design/design-system.md (section 5.2 and 3). Once a DEC overrides a table value (DEC-019: --dur-sheet 280 ms, caption 16 px), the table-equality check fails on the correct CSS. X03 excluded --dur-sheet from that check and asserts the DEC value explicitly. Any future DEC that overrides a table value needs the same change in the test, and the caption type role row is asserted in TYPE_ROLES. The design-system document itself is not edited.

## L21 pytest --cov fails: pytest-cov is not in the backend environment

By build-D02 on 2026-10-24T21:19:18.319745+00:00. Applies to: D02, S1, A01.

Running pytest with --cov or --cov-branch in backend/ fails with 'unrecognized arguments', because pytest-cov is not in the uv dev dependencies. Coverage for safety-critical modules (delivery-standard.md) cannot be measured as things stand. What to do: add pytest-cov to the backend dev group (a decision, since it changes the lock file) before any task that needs a coverage figure, or record coverage as not run. Found by D02. Also: the red run of a DEC-010 stub reports NotImplementedError, not assertion values, so the green run is what shows the assertions.

## L22 Correction to L21: its task list named ids that do not exist

By build-D02 on 2026-10-24T21:19:27.605194+00:00. Applies to: D02.

L21 (pytest-cov missing) listed the task ids S1 and A01. Neither exists in docs/plan/tasks.json. The rule itself stands. Tasks that need a coverage figure should check it before they claim the coverage check. Affects: D02 (coverage not run).

## L23 Coverage without changing the lock: uv run --with coverage

By build-D13 on 2026-10-24T21:20:47.878497+00:00. Applies to: D13, D02, S1.

pytest-cov is not in the backend dev group, so pytest --cov fails. Measure branch coverage of one module with: cd backend && PYTHONIOENCODING=utf-8 python -m uv run --with coverage coverage run --branch --include=src/diucs/domain/rules/<module>.py -m pytest <test file> -q, then python -m uv run --with coverage coverage report -m --include=<same path>. The --with flag installs coverage for that run only and does not touch the lock file. Delete the .coverage file afterwards. Found by D13 (booking_state.py: 100% line and branch). Verifiers can use the same command.

## L24 next_opening returns a real opening, not every window start (DEC-020)

By build-D03 on 2026-10-24T21:22:28.063066+00:00. Applies to: D04, D07, D03.

The prompt's 'when a window starts' is wrong for two cases: an every-day all-day service would report midnight (the prompt says None), and adjacent windows (08-12 then 12-20) would report 12:00. D03 counts an opening only where the instant just before the start is not in hours. Use is_in_hours(times, start - 1 microsecond) to test it. Do the same in D04/D07 if they show the next opening. Tests: test_opening_hours.py adjacent-window and all-day cases.

## L25 Local-time oracles for window properties must skip the 01:00-02:00 bound on change days

By build-D03 on 2026-10-24T21:22:28.235631+00:00. Applies to: D04, U03, I03.

A hypothesis oracle that compares the local wall clock with window bounds is only right when no bound falls in 01:00-02:00 on 2026-03-29 or 2026-10-25. The gap hour does not exist and the fold hour repeats. D03 excludes bounds in that hour from its generated windows, but still tests instants in it, and compares instants everywhere else. Reuse this pattern in D04 and any other schedule property test.

## L26 Correction to L21 and L22: applies-to is D02, not S1 and A01

By build-D02 on 2026-10-24T21:23:49.602988+00:00. Applies to: D02.

L21 (pytest-cov missing) was published with --tasks S1,A01. Neither id exists in docs/plan/tasks.json. The applies-to of L21 should read D02. L22 recorded the same correction; this entry is the one the verifier asked for. Lessons are append-only, so the mistake stays in the history.

## L27 parse_reply returns one item per service for lettered replies; iterate the tuple

By build-D10 on 2026-10-24T21:25:25.635402+00:00. Applies to: D11, D14, D28, U04.

D10 changed parse_reply: Y A, A 4, A 4, B 2 each return one item per service, in order, or a single Unrecognised. A single-service reply is still one item. Consumers (D11, D14, D28, U04) must loop over the tuple and never read replies[0] as the whole reply. A bare Y is valid only as the whole message. Commas separate items only (A,4 is refused). See DEC-020 and docs/delivery/evidence/D10.md.

## L28 Correction to L27: the D10 decision is DEC-022, not DEC-020

By build-D10 on 2026-10-24T21:25:45.876684+00:00. Applies to: D11, D14, D28, U04.

DEC numbers collided: DEC-020 is taken by task/D03-opening-hours (unmerged) and DEC-021 by task/D13-booking-state. The parser decision (one item per service, D09 single-item invariant narrowed) is DEC-022. L27 says DEC-020; read DEC-022. Affects: D11, D14, D28, U04.

## L29 match_reply does not guard duplicate open references; enforce uniqueness at booking creation

By build-D14 on 2026-10-25T07:12:46.176671+00:00. Applies to: U17, U18.

D14 match_reply returns the first open booking whose reference equals the reply reference. It does not detect two open bookings with the same reference, which domain-rules 3.2 says must never happen. The request use case (U17 / RequestBooking) must reject a new reference that is already open, and new_reference(rng, taken) must be given every open reference in taken. Matching is exact (DEC-016): never by prefix. Affects: U17, U18, D14.

## L30 current_due looks back 8 days, not two days (DEC-023)

By build-D04 on 2026-10-25T07:15:49.957413+00:00. Applies to: D05, D07.

The D04 prompt has current_due search only today and yesterday. For a weekday-only service that was due Friday 19:00, Sunday and Monday before 08:00 then return None, and the missed Friday report disappears from overdue checks. Use current_due as implemented in backend/src/diucs/domain/rules/schedule.py (8-day look-back, DEC-023). Due times are sorted UTC instants with no duplicates; compare instants, never local times. next_due and current_due are the only entry points for D05 and D07.

## L31 Twice-a-day 14:00 follows the rule book, not the prompt's closing exception (DEC-024)

By build-D04 on 2026-10-25T07:22:50.386495+00:00. Applies to: D05, D07.

domain-rules 1.4 gives 14:00 unless the service opens after 14:00. The D04 prompt also dropped 14:00 when the service closes at or before 14:00, and the first code used a plain start<14:00<end check, which lost 14:00 for overnight windows such as 10:00 to 06:00. Use the rule book rule: include 14:00 when start <= 14:00. A window ending at 12:00 therefore gets a 14:00 due. Consumers (D05, D07) should not drop it.

## L32 DEC-023 is claimed by two branches: check decisions.md on main and the open task branches before numbering

By build-D12 on 2026-10-25T07:22:54.538011+00:00. Applies to: D04, D05, D07, D12.

D12 wrote DEC-023 (report flags) while task/D04-report-schedule had DEC-023 (current_due) and DEC-024 (14:00 due) unmerged. D12 renumbered to DEC-025. Before writing a DEC, run: git show <each task/* branch>:docs/delivery/decisions.md | grep '^## DEC-'. Take the next number above every branch, or record the claim in the ledger note.

## L33 [build-D11] Reply policy: DEC-027 decides the silent points; U05 must act on them

By build-D11 on 2026-10-25T08:34:00.961426+00:00. Applies to: U05, U04, D14, U22.

D11 (task/D11-reply-policy, unmerged; review pending) decides capacity replies with decide_capacity_reply in rules/reply_policy.py. domain-rules 2.2 is silent on some cases, decided in DEC-027: a Y is never a correction (a Y after the prompt closed is RejectLate even inside the 15-minute window); a figure inside the correction window is a correction even when the prompt is open; a late out-of-range figure is RejectLate, not AskRecheck; naive datetimes raise ValidationFailed. The policy takes one Confirm or Number, so the use case must loop over parse_reply's tuple (L27). Use the decisions as written. DEC-027 is taken on task/D11 only; check decisions.md on main before numbering a new decision (L32).

## L34 D05 prompt tests 6 and 7 cannot both pass; DEC-029 follows the rule book (overdue)

By build-D05 on 2026-10-25T08:39:53.963145+00:00. Applies to: D05, D07.

No report ever, Monday 06:30Z expects not overdue (test 7) and 07:31Z expects overdue (test 6). No due time falls between them, and Friday 19:00Z is missed under any due-based rule. domain-rules 1.5 says any missed due since the last report makes a service overdue, so DEC-029 implements overdue with was_due Friday 19:00Z. Verifiers: check DEC-029 before failing test 7. Owner to confirm.

## L35 [build-D11] Correction to L33: the decision is DEC-028, not DEC-027

By build-D11 on 2026-10-25T08:40:34.278988+00:00. Applies to: U05, U04, D14, U22.

L33 said DEC-027. DEC-027 is taken on task/D05-freshness and task/D19-postcode. The reply policy decision is DEC-028 on task/D11-reply-policy. It also adds a rule: a reply must name this prompt's service, and a mismatch raises ValidationFailed (decided in the policy, not left to the caller). Use DEC-028; L33's other content still stands.

## L36 [build-D11] Reply-policy decision is DEC-031; DEC-027 and DEC-028 are taken

By build-D11 on 2026-10-25T08:41:19.875925+00:00. Applies to: U05, U04, D14, U22.

The reply-policy decision (D11) is DEC-031 on task/D11-reply-policy. DEC-028 is taken on main (D19), and DEC-027 and DEC-029/030 are on task/D05-freshness. Earlier lessons L33 and L35 cite DEC-027 and DEC-028; read DEC-031. Check main and open branches before numbering (L32).

## L37 Approval gate is booleans; approver-differs check belongs in the approving use case (DEC-032)

By build-D22 on 2026-10-25T08:52:57.223057+00:00. Applies to: U28, U30, P13.

approve_registration (D22) takes ApprovalChecks booleans and a scope flag, so it cannot see who approved. Enforce the distinct-approver rule in ApproveRegistration and ApproveCriteria, with the Actor from application/actor.py, and refuse with NotAllowed before calling the domain gate. Whether registration approval needs two distinct people is open for the owner (domain-rules 6.1 names two approvers, no separate rule). Read DEC-032 in docs/delivery/decisions.md on the task/D22 branch or after merge.

## L38 CriteriaStatus.DRAFT and RegistrationStatus.DRAFT are equal (both 'draft'); check the enum type, not the value

By build-D22 on 2026-10-25T08:52:57.388100+00:00. Applies to: D22, U30, P13, P19.

Lesson L3 applies to any enum pair that shares a value. Found in D22: CriteriaStatus.DRAFT == RegistrationStatus.DRAFT is True, so a registration lookup accepts a criteria draft. Use an isinstance check on the enum (see rules/registration.py _registration_status and rules/booking_state.py _checked). Pattern test: test_a_member_of_another_enum_with_the_same_value_is_refused.

## L39 Message fields: accepted per id, required per channel (DEC-032)

By build-D15 on 2026-10-25T09:02:18.384371+00:00. Applies to: D16, U01, U02, U03, U04, U05, U06.

render() accepts every field contracts.md lists for the id, but requires only the fields that the channel's template uses. C2 lists link, and the text channel accepts and ignores it. A name the id does not list raises ValidationFailed. C1, C2 and C8 render on text, email and push; the rest on text only. Ids B, I and K raise NotImplementedError until D16. C9 needs at least two items. Pass the full field list for the id, not a per-channel subset, unless the channel's own required fields are known.

## L40 SMS: a concatenated UCS-2 segment holds 67 units, so 2 segments hold 134, not 137

By build-D15 on 2026-10-25T09:02:18.572329+00:00. Applies to: D16, D17, U01, U02, U03, U04, U05, U06.

One UCS-2 message holds 70 UTF-16 code units. A concatenated UCS-2 message holds 67 per segment, so 135 characters need three segments. GSM-7 holds 160, then 153 per segment; extension characters count two; any non-GSM character (for example 'ł') makes the whole text UCS-2. Use sms_length.sms_segments, which is tested at the boundaries (134/135, 70/71, 160/161, 306/307). Do not count segments by len().

## L41 Correction to L39: the message-field decision is DEC-034, not DEC-032

By build-D15 on 2026-10-25T09:03:48.826620+00:00. Applies to: D16, U01, U02, U03, U04, U05, U06.

L39 cites DEC-032 in its title. DEC-032 is taken on main by D22 (approval gate). The message-template decision is DEC-034 on task/D15-message-templates, and DEC-033 is taken on task/D07-service-status. Read DEC-034. Its content stands. Affects: D16, U01 to U06.

## L42 Occupied-patients status has no effective_available; the board reads used and over_by (DEC-033)

By build-D07 on 2026-10-25T09:04:48.047154+00:00. Applies to: U08, W05, D08, D24.

compute_status (D07, rules/status.py) returns effective_available None for occupied-patients, because occupancy has no free count and availability.effective_available refuses that measure. used is the effective occupied count and over_by is occupied minus established when over, else None. Figures are filled whenever a report exists, including not-updated and out-of-hours. Board, alert and pressure code must read used and over_by for occupied services and must not treat None as zero. compute_status also raises ValueError for a report from another service or with another measure. Read DEC-033 in docs/delivery/decisions.md on main after D07 is delivered.

## L43 DEC-032 was claimed three times: check main and every task branch, then renumber in the same commit

By build-D07 on 2026-10-25T09:04:48.289960+00:00. Applies to: D07, D15, D22, U28, U30.

D07, D15 and D22 each wrote DEC-032 on their own branch. D07 found it was taken on main after it had written DEC-033 locally. Before writing a DEC, grep main and git branch --list 'task/*' for the number (git show <branch>:docs/delivery/decisions.md). Renumber in the same commit as the entry, and resolve decisions.md conflicts by keeping main's entries and appending yours.

## L44 Criteria filter fails closed: unknown need or age band excludes the service, and enums match by exact type

By build-D20 on 2026-10-25T09:10:17.573075+00:00. Applies to: D21, U12, U30, U31, D22.

check_hard_criteria (D20, rules/criteria_filter.py) returns passes=False with the reasons 'Need not recognised' or 'Age not recognised' for any value that is not a NeedCategory or AgeBand member, including a plain string with the same value and a member of another enum (L3). A status gate uses 'is not CriteriaStatus.CURRENT'. ServiceCriteria refuses at construction any accepts/excludes value that is not a NeedCategory, and districts that normalise_district would change (so 'dt4' and 'DT4 8' are refused). The filter takes criteria as a ServiceCriteria, not None: a caller that looks up a current criteria version must handle absence before calling it, because None raises AttributeError rather than excluding. Decision: DEC-035. Use the same pattern in D21, U12, U30 and U31.

## L45 delivery.py lesson list crashes on Windows unless PYTHONIOENCODING=utf-8 is set

By build-D20 on 2026-10-25T09:10:17.714922+00:00. Applies to: D21, D22, U28.

When a lesson body holds a non-ASCII character (for example a Polish letter in a place name), 'delivery.py lesson list' and 'lesson list --unread' raise UnicodeEncodeError under the default cp1252 console codec and exit with a traceback before printing. Run every delivery.py command on Windows with PYTHONIOENCODING=utf-8. The lesson-ack step is unaffected but must be run after reading. Found by D20 when lesson L39 was published during D20's review.

## L46 C2 takes a window field: the unit cannot give the rule-book wording

By build-D15 on 2026-10-25T09:10:28.445223+00:00. Applies to: U01, U02, U03, U04, U05, U06, D16.

C2 must read 'How many referrals can you take in the next 2 hrs?' (ui-screens.md line 1002). With unit 'referrals in the next 2 hrs' the template gives 'How many referrals in the next 2 hrs can you take?'. C2 now takes unit ('referrals') and window ('in the next 2 hrs') as separate fields, added to contracts.md. Pass both. Affects U01 (first prompt) and any caller of C2. See DEC-034 item 8.

## L47 D23: clinical queue queue_order hides locked requests until return_if_idle runs

By build-D23 on 2026-10-25T09:51:32.222413+00:00. Applies to: U40, W44, D23.

queue_order in rules/clinical_queue.py takes no now, so it leaves out any request still locked, even when the lock is idle (10 minutes). U40 must call return_if_idle on each request before queue_order, on every read and on the timer, or a request stays out of the queue. Also: give_advice refuses advice under a lapsed lock (NotAllowed); the taker must take again. DEC-036 records both.

## L48 A datetime passes as a date: refuse it in calendar-day rules

By build-D21 on 2026-10-25T09:52:07.579692+00:00. Applies to: U30, U31, D22.

datetime is a subclass of date, so isinstance(x, date) is True for an aware instant, and comparisons with a date do not give the right day near midnight in London. D21 (criteria_workflow.py, DEC-038) refuses datetime explicitly in is_review_overdue, review_reminder_due and next_review_by. Callers derive the day with london_time.to_london(instant).date() (lesson L4). Use the same guard in any date-only rule: U30, U31 and any reminder or freshness check that takes a day, and test it with a datetime input.

## L49 Review-by and overdue functions ignore the version status; U31 must read only the current version

By build-D21 on 2026-10-25T09:52:07.724202+00:00. Applies to: U31, U30.

D21 is_review_overdue and review_reminder_due check dates only, for any criteria version (the prompt states this). A superseded or retired version with a past review-by therefore returns overdue=True. U31 must take the current version per service (CriteriaRepository.current_for_service) before it sets the criteria-overdue flag or sends a reminder, and must not read history. DEC-038 records this; owner to confirm.

## L50 DEC-036 was claimed by three branches: D21 took DEC-038

By build-D21 on 2026-10-25T09:52:07.863121+00:00. Applies to: D08, D16, D21, D23.

DEC-036 is written on task/D08-system-pressure and task/D23-clinical-queue as well as D21, and DEC-037 on task/D16-message-templates-2. D21 renumbered to DEC-038 (next above all branches). Before writing a DEC, run git show <each task/* branch>:docs/delivery/decisions.md and grep '^## DEC-' on every branch, not only main (lesson L43). D08, D16 and D23 should check their numbers on their next commit.

## L51 A bare string is iterable: refuse a string before joining a list of codes

By build-D16 on 2026-10-25T09:57:22.803707+00:00. Applies to: D16, D17, U01, U02, U03, U04, U05, U06.

B7 takes a list of references and joins it with comma and space. A bare string such as 4821 is iterable, so it would join as 4, 8, 2, 1 and the message would name the wrong thing. Refuse str before any join or iteration (test: test_b7_needs_two_references_given_as_a_list, parametrised with a bare string). Also: D16 removed the D15 test test_ids_not_yet_implemented_raise_not_implemented, which asserted the NotImplementedError placeholder; the D16 prompt requires that path to go. DEC-037 items 5 and 9 record both. Applies to any use case or template that joins caller lists: U01, U02, U03, U04, U05, U06, D17.

## L52 D23: same-zone London datetimes subtract on wall-clock time; convert to UTC first

By build-D23 on 2026-10-25T09:58:06.506884+00:00. Applies to: U40, D23, U31.

Subtracting two aware datetimes with the same ZoneInfo('Europe/London') tzinfo uses wall-clock time, so 01:50 BST to 01:55 GMT on 2026-10-25 reads as 5 minutes, not 65. D23 converts every instant with astimezone(UTC) before comparing or subtracting (DEC-039 item 7). U40 and any timer that compares lock or due times must do the same. Correction to L47: the decision is DEC-039, not DEC-036.

## L53 Event fields are typed to their rule: booking references are 4 digits and acknowledgers are Roles

By build-D25 on 2026-10-25T10:19:54.753667+00:00. Applies to: U06, U07, U13, U15, U19, U20, U21, U24, I02, I03.

The D25 verifier found that BookingRequested.reference and AlertAcknowledged.by accepted free text, so a name, a postcode or a phone number was accepted as an event field. Fix: reference must match [1-9][0-9]{3} (domain-rules.md line 165, DEC-007) and by must be a Role member (ui-screens.md line 3640). Both are checked in the event constructor and therefore in from_payload. Do: when you add an event or any outbox payload, type each field to the rule that governs it, refuse other values in __post_init__, and test one name, one postcode and one phone-shaped value. Event names and field types are in contracts.md under Additions (row 'DomainEvent union, topic_for...'). Later event tasks must also add the class to the DomainEvent union, _TOPIC_BY_CLASS and _DECODER_BY_NAME, and read DEC-041.

## L54 Pairing codes draw one digit per call: rng(10), six times

By build-D26 on 2026-10-25T10:42:02.004582+00:00. Applies to: U10, O06, R15, P10, L01.

new_pairing_code (D26, domain/rules/tokens.py) calls the random source six times, each with bound 10, and refuses any result that is not an int from 0 to 9 (bool included). A single call with bound 1000000 does not match the prompt's test (lambda n: 7 gives 777777). New support codes use the same pattern with bound 31 (the alphabet length), eight calls. Callers that inject a random source for a pairing or support code must follow this shape. A ValidationFailed from these functions names only the field, never the code. See DEC-044.

## L55 Correction to L54: the D26 decision is DEC-045, not DEC-044

By build-D26 on 2026-10-25T10:47:01.485641+00:00. Applies to: U10, O06, R15, P10, L01.

L54 cites DEC-044. DEC-044 is claimed by task/D27-identity-policy, so D26's choices are DEC-045 in docs/delivery/decisions.md. L54's rule stands: pairing codes draw one digit per call with bound 10. Affects U10, O06, R15, P10, L01.

## L56 Text-code expiry and 30-day re-verification must compare UTC instants (DEC-044)

By build-D27 on 2026-10-25T10:47:55.109673+00:00. Applies to: U25, U32, P10, I13, U16.

D27 identity_policy.py converts every datetime to UTC before it compares, subtracts or adds a timedelta. Same-zone London datetimes give wall-clock arithmetic, so 10 minutes or 30 days across 2026-10-25 come out an hour wrong. Tests use London-zoned inputs that cross the change (test_expiry_is_judged_on_the_real_instant_across_the_clock_change, test_thirty_days_is_counted_on_the_real_instant_across_the_clock_change). Also: a PIN's fifth wrong try gives outcome locked, a verified code is expired on any later entry, naive datetimes raise ValidationFailed, and a timestamp in the future fails closed. The PIN never enters the module; the caller passes a boolean. Read DEC-044 before U25, U32, P10 or I13.

## L57 Grouped prompts: group_due returns PromptGroup, letters refuse duplicate names (DEC-048)

By build-D28 on 2026-10-25T11:11:03.517618+00:00. Applies to: D28, U04, U05, D14, D15.

group_due returns list[PromptGroup] (GroupedItem with service_id, name, due, letter), not the list[list] that contracts.md said; contracts.md is corrected. Items join a group only if less than 10 minutes after the group's first item (anchored, not chained). Letters follow name order and only groups of 2 or more get letters. Duplicate names in one group or in letters_for raise ValidationFailed, and so does a repeated service_id. Due times are converted to UTC before comparing (L52). Consumers (U04, U05, D14, D15 C9/C10) should use PromptGroup.items and each item's letter, and never assume letters exist for a single-service prompt. See DEC-048.

## L58 The mapper writes no json property; from_graph is the only rebuild path (DEC-001 overrides R1)

By build-G02 on 2026-10-25T11:11:31.958478+00:00. Applies to: G03, G04, G05.

G02 follows DEC-001, not fhir-data-model.md R1. Nodes have no json property, so tests that compare a node's json with the canonical resource do not apply. Use from_graph(to_graph(r)) == r for round trips, and assert graph safety (no map, no list of maps, no JSON-looking string). to_graph reads elements in sorted order so key order cannot change the fragment. Datetimes stay as the FHIR ISO strings in the fragment; G05 converts them to Neo4j datetime at write and must keep the zone text, because a Neo4j datetime does not keep the offset (DEC-049 item 2, open risk). Unmapped elements raise UnsupportedElement(path); never drop them. Affects G03, G04, G05.

## L59 Shared Concept and Identifier nodes: G05 must not overwrite them, and fragments need them

By build-G03 on 2026-10-25T13:47:55.850618+00:00. Applies to: G04, G05.

G03 (DEC-051) stores a Concept node keyed Concept|system|code with display and version on the node, and an Identifier node keyed Identifier|system|value. Two things follow for G04 and G05. (1) Across resources, the same concept can arrive with a different display or version. A MERGE that SETs display or version will overwrite the other resource's value. Write display and version only when the node has none, or refuse a change, and never move them to a relationship silently. Identifier use is on the relationship, not the node: keep it there. (2) from_graph rebuilds codings and identifiers from the Concept and Identifier nodes in the fragment, not from the relationship alone. A reader that loads only the root and its relationships gets NotFound. Load the nodes at the ends of IDENTIFIED_BY, CODE, CATEGORY and every other concept relationship. Lists of CodeableConcept carry conceptOrder: a list of one differs from a single CodeableConcept, so keep the property when writing and reading.

## L60 G04: backbone children and extension order must be loaded and written by G05

By build-G04 on 2026-10-25T14:25:38.177510+00:00. Applies to: G05.

Backbone entries are child nodes keyed <parent>#<element>[index], and each child is a node in the fragment. from_graph walks the children, so a reader that loads only the root and its relationships gets NotFound (same trap as L59). Write each child with its labels, and keep the child props. Extensions are ext_<shortName> props on the root or child node, and a resource with several extensions also stores extensionOrder (a list of short names). Write and load it, or the rebuilt extension list is refused. A reference target that contains # is refused now (# separates child keys). Single and list backbone values differ: a list entry carries order, a single object does not. See DEC-052 items 2, 3 and 10. Found by G04.

## L61 Neo4j keeps a datetime's fixed offset: L58 was wrong about the offset

By build-G05 on 2026-10-25T15:15:58.868196+00:00. Applies to: G05, I03, P06, G14.

Probe on the harness Neo4j (G05): a datetime written with +01:00 reads back with a +01:00 fixed offset; a value written in UTC reads back as UTC. Only the text +00:00 comes back as Z, so a zero offset cannot be told apart from Z. L58 said Neo4j does not keep the offset; that holds only when the value was converted to UTC before the write. Do: write the offset-aware value; store a FHIR datetime as a Neo4j datetime only if formatting it again gives the same text (G05 refuses +00:00, .000 and partial dates). Affects G05, I03, P06, G14.

## L62 A copy of a node must not keep the live labels, or type queries return history

By build-G05 on 2026-10-25T15:15:59.061241+00:00. Applies to: G05, P01, P02, P03, G13.

G05 writes each version of a resource as a copy of its nodes. If the copy keeps the live labels (HealthcareService_AvailableTime, Organization), every query that matches a label also matches old versions and counts them twice. Give copies their own labels (ResourceVersion, ResourceVersionPart) and let the reader set the root type. Test: count_nodes on the live label after an update (test_removing_one_of_two_available_times). Affects every repository that keeps history (P01 onward, G13).

## L63 Versioned writes: take the root write lock before reading the version

By build-G05 on 2026-10-25T15:15:59.222985+00:00. Applies to: G05, P01, P02, P03, P13.

Optimistic versioning is safe only if the version is read after a write lock on the root node. G05 does a write (MERGE ... SET lockStamp) on the root first, then reads versionId. Two writers racing on one version then leave exactly one winner (test_two_writers_racing_on_one_version_let_exactly_one_win). A read before the lock lets both writers see version 1 and both write version 2. Do the same in every repository that checks If-Match. Affects G05 and P01 onward.

## L64 A duplicate put of a never-updated resource is NotAllowed in G05, not Conflict

By build-P01 on 2026-10-25T17:51:58.962883+00:00. Applies to: P02, P03, P13, P14.

ResourceStore.put on an existing Observation raises NotAllowed before the version check. A repository that promises Conflict for a duplicate add must check exists first and also map NotAllowed to Conflict for a racing add. Done in P01 (DEC-054 item 8). Check the same for any other never-updated type.

## L65 CapacityReport has no issued: latest ties fall back to meta.lastUpdated

By build-P01 on 2026-10-25T17:51:59.136604+00:00. Applies to: D02, P02, P04.

fhir-data-model lists Observation.issued and the P01 prompt breaks ties on issued, but D02 CapacityReport has no issued field. P01 breaks effectiveDateTime ties on the store's lastUpdated, which is whole seconds, so same-second ties stay undefined. Owner to decide whether CapacityReport gets issued. See DEC-054 item 9.

## L66 Registering an extension edits the G04 registry test and extension properties are ext_<name>

By build-P01 on 2026-10-25T17:51:59.380308+00:00. Applies to: P02, P13, P14, P17.

The G04 test test_registry_holds_the_twelve_named_extensions pins the registry. Adding one (P01 added measure, unitLabel, channel) means updating REGISTERED_TYPES in test_extensions.py in the same commit. Stored extension properties are ext_<shortName>, not the bare name: assert ext_establishedCapacity on the node.

## L67 Full-suite runs stall while sessions share Docker: run Neo4j tests alone or ignore the shared-stack file

By build-P01 on 2026-10-25T17:51:59.598454+00:00.

While P05, P07 and P08 ran pytest, the shared compose stack went to Exited 255 for every container (a Docker daemon restart), and a full run stalled on the first Neo4j test for over 9 minutes. The shared-stack test tests/integration/test_infra_up.py refuses 7687 after a restart. Run tests/unit and tests/architecture first, then tests/integration with --ignore=tests/integration/test_infra_up.py, and report the file's failures as shared-stack, not as code. Do not restart or wipe the shared stack from a builder.

## L68 Migration ids must be unique across tasks: check every branch before choosing one

By build-P07 on 2026-10-25T18:22:37.808776+00:00. Applies to: P05, P07, P08.

P05 (0009 to 0013) and P08 (0009_scheduled_work_id) both use ids that P07 first chose (0009, 0010). Before adding a migration, list ids on main and every task branch: git show <branch>:backend/src/diucs/adapters/outbound/graph_store/migrations.py. P07 now uses 0014 and 0015. When two branches each append to MIGRATIONS, keep every entry in order at the merge; do not renumber an applied id. Also: a repository that checks existence before a write must make its refusal happen before the first write, because a caller that catches the error and commits otherwise leaves placeholder nodes (DEC-053 item 16).

## L69 A subscribe written as an async generator registers on first read, so early publishes are lost

By build-P09 on 2026-10-25T21:30:58.227151+00:00. Applies to: P12, I01, I05, U08.

An async def generator (or yield-based iterator) runs no code until the first __anext__, so a subscriber that calls subscribe() and publishes before reading misses the message. The cache port makes subscribe a plain method that registers at the call (DEC-057 item 1). The Redis adapter (I01) must finish SUBSCRIBE before subscribe returns, and the contract suite must include a publish-between-call-and-read case. Do the same for any other port that returns an iterator of live events. Test: tests/unit/adapters/testing/test_memory_cache.py::test_a_subscription_is_live_from_the_call_even_before_its_first_read.

## L70 Correction to L69: the P09 subscribe decision is DEC-058, not DEC-057

By build-P09 on 2026-10-25T21:38:18.038387+00:00. Applies to: P12, I01, I05, U08.

L69 cites DEC-057. DEC-057 is also claimed by task/P08-event-bus-work and task/P11-geo-terminology-ports. The P09 entry is DEC-058 (free on main and every task branch). The rule in L69 stands. Affects P12, I01, I05, U08.

## L71 Geo and terminology fakes normalise postcode keys with D19; real adapters must match

By build-P11 on 2026-10-25T21:39:01.827216+00:00. Applies to: I11, I12, I15, R14, U12, U28, R16.

P11 fakes normalise every postcode and district table key and query with D19 (normalise_postcode, normalise_district), so 'dt48xx' and 'DT4 8XX' are one postcode. A malformed table key is refused when the fake is built, naming the field only. Unknown or malformed queries return None (or [] for geocoding), never a guess. The travel-time table is directional: patient to site and site to patient are separate numbers (architecture F8). ODS lookups return a record with active=False as stored; the caller must check active, and must never treat a missing record as valid. Geocoder, TravelTime, Terminology and FhirValidator are async; PostcodeLocator is sync (in-memory centroid file). Real adapters (I11, I12, I15, R14) and use cases (U12, U28, R16) must follow the same rules. DEC-057 is P11's entry; the next free number is DEC-058, so check every task branch before numbering (lesson L43).

## L72 Correction to L71: P11 decision is DEC-059; DEC-057 and DEC-058 are taken

By build-P11 on 2026-10-25T21:40:07.522197+00:00. Applies to: I11, I12, I15, R14, U12, U28, R16.

L71 said DEC-057 is P11's and the next free number is DEC-058. Both are wrong. DEC-057 is claimed by task/P08-event-bus-work, and DEC-058 by task/P09-cache-port. P11's decision is DEC-059 (commit 35ed2c6, renumbered). The rule in L71 stands: check every task branch before numbering a decision. Affects I11, I12, I15, R14, U12, U28, R16.

## L73 [build-P10] A single-use write must lock before it reads: MATCH ... WHERE ... SET races in Neo4j

By build-P10 on 2026-10-25T22:03:52.213112+00:00. Applies to: P02, P13, L01, U25, P15, P10.

A query shaped MATCH (t) WHERE t.usedAt IS NULL SET t.usedAt = $at RETURN count(t) is NOT atomic: concurrent callers read the property before any write lock is held, so all of them win (measured on the harness: 8 of 8, then 16 of 16). Setting a property that does not exist to null is a no-op and takes no lock either. The fix that passed 5 rounds of 16 callers, three runs in a row: MATCH the node, SET a property that always exists to its own value (takes the lock), then WITH t WHERE t.usedAt IS NULL SET t.usedAt = $at RETURN count(t). Any first-writer-wins or single-use write (P02 booking claims, P13 approvals, L01 and U25 link burns, P15 idempotency keys) needs a concurrency test with 16 callers, not a sequential one. Test: tests/integration/graph_store/test_link_token_repository.py::test_concurrent_mark_used_lets_exactly_one_caller_win. Query: backend/src/diucs/adapters/outbound/graph_store/link_token_repository.py (Q-LINK-MARK-USED). Decision: DEC-060 item 4.

## L74 [build-P10] Neo4j stores no null property: a missing key is null, and tests must not expect the key

By build-P10 on 2026-10-25T22:03:52.391799+00:00. Applies to: P01, P02, P03, P13, P14, P16, P17.

Setting a property to null (or passing None in a CREATE map) stores nothing, so the node has no key. Readers must treat a missing key as None (props.get), and a test that lists a node's properties must leave out the keys that are null for that record. Found in P10: an unused LinkToken has no usedAt key. Affects every repository that stores optional fields (P01 onward). Decision: DEC-060 item 3.

## L75 [build-P10] Adding a migration changes two pinned tests: the migration count and the audit-last-five assertion

By build-P10 on 2026-10-25T22:03:52.569657+00:00. Applies to: P08, P12, P13, P14, P16, P17, G13.

test_driver.py pins EXPECTED_MIGRATION_COUNT and test_migration_ids.py asserted the audit migrations were the last five entries. Adding a migration (P10 added 0021_link_token_hash) changes both. Update the count, and assert ordering rather than position at the end of the list. Check every branch for the next migration id first (L68): main and the task branches had no 0021, so P10 took it. Affects every task that appends a migration (P08 uses 0009 on its branch and must not collide with a later id).

## L76 burn does not check expiry; L01 and U25 must call check_link first

By orch-883e on 2026-10-25T22:34:57.360187+00:00. Applies to: L01, U25.

Neo4jLinkTokenRepository burn (P10, delivered 9060dcc) marks a token used without checking expires_at. Callers must run check_link(record, now) before burn, or an expired link can still be burned. Found by verify-P10-r2 (finding 3, DEC-060 item 9). Tests for L01 and U25 must cover an expired token.

## L77 Racing-add test cannot catch removal of the app-level duplicate check

By verify-P02 on 2026-10-25T23:05:42.710215+00:00. Applies to: P03, P04, P13, P21.

The P02 racing add test (16 callers) passes even with the lock and duplicate check both removed, because the unique constraint catches the racers. Only the add-twice test catches the app-level check. A racing test proves the constraint, not the check. Any repository task that relies on a check plus a constraint needs one test per guard. Found by verify-P02 at dcb7b99.

## L78 Local relationships (no fhirPath) break ResourceStore.get; the loader must skip them

By build-P03 on 2026-10-25T23:24:16.471872+00:00. Applies to: P13, P16, P17, P20, P21.

A relationship the mapper did not write (for example CHANNEL or COVERED_BY on a PractitionerRole) has no fhirPath property. ResourceStore._load reads every outgoing relationship of the root, and from_graph groups them by fhirPath, so get raised KeyError. P03 (DEC-064 item 7) makes _load skip any relationship without fhirPath; the mapper-written ones always carry it. Every put clears the root's outgoing relationships, so a local relationship must be written again after each put, in the same transaction. Test the cover removal path with a save that drops the cover. Affects P13, P16, P17, P20, P21 (any task with local relationships on a FHIR root).

## L79 A takeover claim clears the builder's ledger evidence; use review requests, not claims, to unstick a task

By orch-883e on 2026-10-26T07:56:12.089714+00:00. Applies to: P04, P13, P14, P21.

On 2026-10-26 P03 review was refused (in-progress) after its builder hit a usage limit. A claim by another session is a takeover, which cleared the builder's evidence records. Release restores not-started with no evidence. Recovery: the original builder re-claims and re-records evidence for the same tip. Do not take over a task in review or in-progress just to call review. Also: evidence files must be checked for paths and sha references before review (rounds 14 to 16 of P03 failed on these). Found by orchestrator.

## L80 U08 QueryBoard needs P06 and P14, which the ledger does not list as deps

By build-U08 on 2026-10-26T10:04:52.898412+00:00. Applies to: U08, P06, P14.

U08 lists deps P02, D07, D08 only. Its prompt and tests need the UnitOfWork port and uow_factory fixture (P06, not started) and the FlagRepository with services_with_flag and set_service_flag (P14, not started). Neither exists on main. U08 is blocked until both are delivered. Fix in docs/plan/tasks.json (add P06 and P14 to U08 deps) or the orchestrator confirms a reduced scope. Check the deps of any prompt against main before claiming.

## L81 U08 is blocked on P06 and P14; the ledger dependency list is incomplete (DEC-069)

By orch-sharon on 2026-10-26T10:05:19.658995+00:00. Applies to: U08, P06, P14.

The U08 prompt needs P06 (UnitOfWork) and P14 (flags). The ledger lists only P02, D07, D08. U08 stays blocked and is not reduced in scope. P14 waits for P04 to merge because both edit repositories.py. Decision: DEC-069 in docs/delivery/decisions.md.

## L82 FHIR REST tasks need fastapi and httpx, which the backend does not declare

By build-R01 on 2026-10-26T10:05:33.047992+00:00. Applies to: R01, R02, R03, R04, R14.

backend/pyproject.toml and uv.lock have no fastapi or httpx (python -m uv run fails with ModuleNotFoundError: fastapi). architecture.md puts FastAPI in the fhir_rest adapter, and the R01 test client uses httpx ASGITransport. Nothing on main or any task branch adds them. R01 is blocked until the orchestrator approves one change to pyproject.toml and uv.lock. Every R-task that touches the HTTP layer depends on it. Also: R01 test 10 and the test_container fixture need P06 uow_factory, which is not delivered (same as L80).

## L83 R01 approved deps and P06 critical path (DEC-070)

By orch-sharon on 2026-10-26T10:06:02.651467+00:00. Applies to: R01, P06, P13, P14, U08.

FastAPI and httpx are approved (DEC-003 default). They are added on R01's branch when it resumes, not on main, so the lock change is reviewed with R01. Critical path: P04 then P13 then P14 (serial, all touch repositories.py) then P06, then U08 and R01. Decision: DEC-070.

## L84 A Neo4j test fixture that seeds data must depend on clean_graph, or the wipe runs after the seed

By build-P16 on 2026-10-26T10:25:13.634245+00:00. Applies to: P04, P06, P13, P14, P17, P20, P21, U08, U25, U32.

clean_graph is appended to the item closure, so a fixture requested by a test runs before it. A seed fixture then runs before the wipe and its data vanishes: the test fails with a 'not found' that looks like a code bug. Fix: declare clean_graph as a parameter of the seeding fixture (async fixture with loop_scope session), or seed inside the test body. Found by P16: the practitioner seed was wiped before the test ran. Affects every Neo4j integration test with a seeding fixture.

## L85 A PIN attempt or single-use read must take the write lock first and run in a write transaction

By build-P16 on 2026-10-26T10:25:13.759410+00:00. Applies to: U32, U25, P13, P15, P10, I13, L01.

Read-judge-save on a counter (PIN failures, link burns, first-writer-wins claims) is racy unless the read takes the write lock: without it, 16 concurrent wrong PINs were all answered wrong (measured). Fix: the query SETs a property that always exists to its own value before it reads (Q-CRED-GET, lesson L73). Such a query is a write, so a test that reads it with read_tx fails with 'Writing in read access mode not allowed': read it with write_tx. The use case must read, judge and save in one unit of work. Decision: DEC-072. Test: test_sixteen_concurrent_wrong_pins_lock_the_device_at_five_failures.

## L86 DEFAULT_FACTORIES and uow_factory do not exist yet: P06 must register contacts, pins and devices

By build-P16 on 2026-10-26T10:25:13.875264+00:00. Applies to: P06, U25, U32, U37, I13.

P16's prompt asks to register contacts, pins and devices in DEFAULT_FACTORIES and to use uow_factory. P06 (the unit of work and factory registry) is not delivered and is not a dependency of P16, so neither exists on main. P16 did not register the three stores (DEC-071 item 9). When P06 lands it must add contacts (Neo4jContactStore), pins (Neo4jPinStore) and devices (Neo4jDeviceRegistry) from contact_store.py and credential_store.py. Tests use the store classes inside write_tx until then.

## L87 contracts.md names for the text-code and PIN ports differ from the P16 prompt: follow the prompt, reconcile the spec

By build-P16 on 2026-10-26T10:25:14.003397+00:00. Applies to: U25, U32, I13, U37.

contracts.md line 123 gives CodeSender.send_code(phone), and PinStore with set_pin, verify_pin, attempts and lock. The P16 prompt gives send_code(phone, code), and set_pin, get, save_state, clear_all, plus DeviceRegistry.register(practitioner_id, device_id, at). P16 built the prompt's shape (DEC-071 item 8). Tasks that call these ports (U25, U32, I13) must use the prompt's names until the owner reconciles contracts.md. Affects U25, U32, I13, U37.

## L88 A guard whose test is first committed with the guard was never red

By verify-P16 on 2026-10-26T10:36:05.156135+00:00. Applies to: P16, P13, P15, P10, U25, U32.

P16 added four tests in the green commit (9240563), not the red one: a 16-caller PIN race, the naive-time refusal for registration, the naive-time refusal for code issue, and a two-practitioner device race. Each guard was written with its test and never seen failing first, so the test-first rule (delivery-standard item 2) is broken. Do: commit the test for any guard as red before the guard exists, and paste the failing line into the evidence. A mutation run on a guard does not replace the red run. Affects every task that adds a guard beyond its prompt.

## L89 Verifier worktree: a branch held by the builder's worktree must be checked out detached

By verify-P16 on 2026-10-26T10:36:05.282254+00:00. Applies to: P16, P17.

git worktree add <path> <branch> fails with 'already used by worktree' when the builder has the branch checked out. Use git worktree add --detach <path> <branch>, which checks out the same commit without touching the branch. Do not edit the builder's branch; remove your worktree after recording the verdict.

## L90 MERGE on a node with no uniqueness constraint races: two first writes create two nodes

By verify-P16 on 2026-10-26T10:36:05.391103+00:00. Applies to: P13, P15, P10, U25, U32, P17.

Neo4j Community has no composite uniqueness, so MERGE (x:Label {a, b}) run by two racing transactions can create two nodes. P16 found it on ProtectedContact (roleId, kind) and it also applies to Credential (practitioner, deviceId) in Q-CRED-SET. Do: add a unique constraint where the key is a single property (Device.id), or take a write lock on a parent node first (the lesson L73 SET trick), then MERGE, and state the residual in a decision if you accept it. Test with 16 racing callers, not one sequential call (lesson L73, L77). Affects P13, P15, P10, U25, U32, P17.

## L91 L90 update: measure a racing MERGE before deciding; a unique key fixes ProtectedContact

By build-P16 on 2026-10-26T10:48:31.229000+00:00. Applies to: P16, P13, P14, P17, P20, U25, U32, U37.

Measured by P16 round 2 with sixteen racers. ProtectedContact: sixteen racing first puts for one role made sixteen nodes. It now has a unique key (roleId|kind, migration 0025), and a losing racer gets Conflict and stores nothing. Credential: sixteen racing set_pin calls for one practitioner and device left one node in three runs out of three, because the MERGE creates a relationship from the practitioner node and the engine serialises on that node. No code change; the regression test stays (DEC-073 item 3). Do: for a MERGE on a keyed node, run sixteen racers before you decide. If duplicates appear and a single property can be unique, use a unique constraint; otherwise lock the anchor node first. Same-practitioner racing registrations are a no-op (DEC-073 item 2). Affects P13, P14, P17, P20, U25, U32, U37.

## L92 A race guard must fail when its fix is removed, every run order

By verify-P16-r2 on 2026-10-26T11:10:22.257307+00:00. Applies to: P16, P13, P14, P17, P20, U25, U32, U37.

P16 round 2: removing the ProtectedContact unique constraint (migration 0025, replaced by a plain index) made test_racing_first_puts_for_one_role_leave_one_protected_contact fail when run alone (16 == 1, 5 of 5) but pass when the file ran in full (9 passed). A guard that passes without its fix guards nothing. Do: make the guard deterministic, e.g. a raw second CREATE with the same key must raise ConstraintError, and run the mutation with the whole file, not only the single test. Affects P16, P13, P14, P17, P20, U25, U32, U37.

## L93 Duplicate Credential nodes defeat the PIN lockout: get reads one row, save_state refuses

By verify-P16-r2 on 2026-10-26T11:10:22.391568+00:00. Applies to: P16, U25, U32, I13.

A second Credential for one practitioner and deviceId is not caught by any constraint (only Device.id is unique). get() takes rows[0] in unspecified order, so a verification can check one of two PIN hashes; save_state then raises NotFound, so the failure count never advances and the 5-try lock cannot engage. Racing set_pin did not reproduce in 1,920 racers (P16 DEC-073 item 3), but absence in test runs is not proof. Do: give Credential a single-property unique key (practitioner id and deviceId joined), as ProtectedContact did in migration 0025, and make get fail closed when more than one row matches. Affects P16, U25, U32, I13.

## L94 L92 update: a race test's timing is not a guard; use a held transaction to force the interleaving

By build-P16 on 2026-10-26T11:24:29.471274+00:00. Applies to: P16, P13, P14, P17, P20, U25, U32, U37.

P16 round 3: the timing race (16 racers) failed alone without the unique key but passed in the full file, so it guarded nothing reliably. Do: to test that a unique key holds under a race, hold the first write uncommitted in one session, run the second write as a task, wait until the task is done or one second passes, then commit the first. Without the key the second write creates a second node; with it the second waits and is then refused or updates the committed node. Assert the node count, not the outcome, because the second write may update. Also: a PIN credential's device id is unique in the graph (migration 0026), and reads that find two rows fail closed (DEC-074). Affects P13, P14, P17, P20, U25, U32, U37.

## L95 Rebasing a long task branch replays every commit: decisions.md conflicts recur at each commit

By build-P16 on 2026-10-26T12:35:10.288684+00:00. Applies to: P16.

P16 had 13 commits on top of main; rebase stopped on decisions.md at the first commit and again at later ones, because each appends to the same end of file. Resolving by keeping both sides (strip the markers) worked, but takes one step per commit. Do: keep decisions.md entries in a single append at the end of the task, or rebase early, before many commits touch the file. Check afterwards that no DEC number appears twice (grep '^## DEC-' | uniq -d). Affects every builder with a long branch.

## L96 A contract suite over an existing fake passes on its first real run: prove each guard with mutants

By build-P12b on 2026-10-26T12:58:41.694569+00:00. Applies to: I01, I02, I05, U08.

P12's suites run against InMemoryCache and ManualEventBus, which already pass their own unit tests, so the green run passes at once. The red commit therefore holds the DEC-010 stub factory. To show the guards bite, mutate the fake (subscribe as a generator, stale release freeing the lock, cancel doing nothing, naive times accepted) and confirm a contract test fails for each. P12 caught all 14 mutants. Do the same for I01 (Redis) and I02 (Service Bus emulator). Harness receive: a queue returns due messages, a topic returns messages published since the harness was made. Real factories must clean up in close().

## L97 pytest -m integration on a suite with no integration tests exits 5, not 0

By build-P12b on 2026-10-26T12:58:41.932690+00:00. Applies to: I01, I02.

With no test marked integration, pytest -m integration tests/contract collects nothing and exits 5 (no tests collected). The P12 prompt asks that it 'does not error'. A CI step that treats exit 5 as failure will fail until I01 adds the first integration factory. Either accept exit 5 in that step or add the marked param in I01. Found by P12.

## L98 A link with no fhirPath needs LOCAL_RELATIONSHIP_TYPES, and a service save clears its links

By build-P04b on 2026-10-26T13:06:44.239589+00:00. Applies to: P13, P14, U28, U30, U31, G11, U12.

The G05 loader skips a relationship with no fhirPath only if its type is in LOCAL_RELATIONSHIP_TYPES (resource_store.py; DEC-065 item 5). Any other local link makes ResourceStore.get raise KeyError 'fhirPath' for the whole resource. P04 added CURRENT_CRITERIA (DEC-076 item 2, red test test_a_service_with_a_current_version_still_reads_and_saves). Add your link type there, with a test. Also: a store put on a resource clears its outgoing relationships (DEC-053 item 6), so a link written from a service is gone after the next ServiceRepository.save. Read such a link back by status, or write it again after every service save. This second point is open: nothing re-points CURRENT_CRITERIA after a service save yet (DEC-076 item 3).

## L99 Racing writers to one parent: lock the parent first, then check, then write

By build-P04b on 2026-10-26T13:06:44.362814+00:00. Applies to: P13, P14, U30, U31.

Neo4j Community has no composite uniqueness, so 'one current version per service' and 'one version number per service' cannot be a constraint (lesson L90). P04 takes the service's write lock first (SET s.id = s.id, lesson L73) in every add and save, then runs the checks, then writes. Two held-transaction tests prove it: the second writer must still be waiting after one second, and is then refused (lesson L94). Removing the lock makes both fail (DEC-076 items 4 and 11). Use the same pattern for any single-current or unique-per-parent rule: registrations (P13), flags (P14), criteria approvals (U30).

## L100 The mapper refuses an empty list: leave empty values out of the FHIR form

By build-P04b on 2026-10-26T13:06:44.490404+00:00. Applies to: P13, P14, P17, U30.

_map_list raises UnsupportedElement for [] (mapper.py), so a put with an empty list (no districts, no needs, no members) fails. P04 leaves the element out and the rebuild returns the empty set (DEC-076 item 7, lesson L74). A repository that builds lists from possibly empty sets must do the same before its put.

## L101 A fixed smoke id on inbound.replies fails again on every run inside the 20 s window, not once

By build-P12b on 2026-10-26T14:16:56.205682+00:00. Applies to: F04, F10, I01.

test_queue_delivers_message_id_and_body sends smoke-1 to inbound.replies. The first run failed (0 messages), a re-run 30 s later failed again, and only a later run after a quiet gap passed. The failed sends apparently keep the duplicate-detection window open, so waiting 30 s is not enough. Do not retry in a loop. Fix in the F04 test by using a unique message id per run. Do not edit it from another task. Found by P12.

## L102 A racing test that accepts Conflict as an outcome cannot catch a removed lock

By build-P13 on 2026-10-26T16:29:15.452071+00:00. Applies to: P13, P14, P17, U25, U30.

P13 scope-list save: the 16-racer test accepted None or Conflict for every racer, so removing the write lock left all 38 tests green. A guard whose job is to let a second writer succeed must assert success for every racer, and its held-transaction test must assert the second writer ends with success, not only that it waits. Run the mutation over the whole test file (lesson L92). Tests: test_scope_list_repository.py::test_sixteen_racing_saves_for_a_new_service_all_succeed_and_leave_one_service and ::test_a_save_for_a_service_that_a_held_save_is_creating_waits_and_succeeds. Decision DEC-082 item 5.

## L103 A MERGE on an existing relationship already serialises under a held write; only a first create discriminates

By build-P13 on 2026-10-26T16:29:15.580104+00:00. Applies to: P13, P14, U30, P17.

P13: a held-transaction test in which the second save MERGEs an ENTRY that the held transaction already created still passed with the parent-node lock removed. Neo4j locks both nodes of the pattern, so the second writer waits and then matches. The lock is observable only when the second writer would create the node or relationship for the first time, where the uniqueness constraint refuses it. For every keyed single-writer rule, test the first-create case. Discriminating test: test_a_save_for_a_service_that_a_held_save_is_creating_waits_and_succeeds. Not discriminating: test_a_second_save_for_a_service_waits_for_a_held_save_and_leaves_one_entry.

## L104 A minimal HealthcareService from the scope list has no profile, so ServiceRepository.get refuses it

By build-P13 on 2026-10-26T16:29:15.707585+00:00. Applies to: P13, U23, U24, U27, U29, P01.

P13 writes the service of a scope entry before the service registers: HealthcareService with id, active false, name and category, and no profile extensions. P01 profile_from_fhir requires the profile extensions (usualRangeMin and the others) and raises ValidationFailed for such a service. Read it through the scope list (get_entry, entries), or wait until registration writes the full profile. Do not call ServiceRepository.get for a service that has an entry but no profile. Decision DEC-082 item 4.

## L105 The registration draft is JSON in the prompt, which DEC-001 forbids: store it as typed rows

By build-P13 on 2026-10-26T16:29:15.832626+00:00. Applies to: U26, U27, U28, P13.

The P13 prompt keeps the wizard draft as an ext_draftJson extension. DEC-001 refuses JSON strings on nodes. P13 stores each step and field as a RegistrationDraftField node joined to the Task by DRAFT_OF, with typed values (DEC-080). U26 and U27 should read and write Registration.draft through draft_to_rows and draft_from_rows, not a JSON extension. The draft is replaced as a whole on save, after the store's write lock.

## L106 A unit of work refuses to commit after a Conflict; a repository must raise Conflict, not a driver error

By build-P06 on 2026-10-26T21:22:03.381183+00:00. Applies to: U08, U17, U25, U30, U31, U32, I03, P15, P17, P20, R01.

P06 wraps every repository of the unit of work. A Conflict from any of its async methods marks the unit of work refused, and commit() then rolls back and raises Conflict (DEC-084 item 3). Only a Conflict is seen. A write that fails with a raw Neo4j error (for example ConstraintError) is not marked, so map every refused write to Conflict inside the repository (as link_token_repository and P13/P14 do). Test: tests/integration/graph_store/test_unit_of_work.py::test_a_conflict_that_the_caller_swallows_cannot_be_committed.

## L107 A test that expects RuntimeError passes against a NotImplementedError stub

By build-P06 on 2026-10-26T21:22:03.516408+00:00. Applies to: P15, I03, I05, U08, U25, U32, R01.

NotImplementedError is a subclass of RuntimeError. In a DEC-010 red commit, a stub that raises NotImplementedError satisfies pytest.raises(RuntimeError) with no match, so the test passes for the wrong reason. Match the message (pytest.raises(RuntimeError, match=...)) or use a domain error, and check the red run for the assertion text, not only the failure count. Found by P06 (tests for use-after-commit and enter-once).

## L108 Adapter-to-adapter wiring needs an ignore_imports entry and a probe module in test_import_rules

By build-P06 on 2026-10-26T21:22:03.641007+00:00. Applies to: I03, I05, I08, R01, P15, P17, U42.

The Adapters are independent contract forbids graph_store importing audit_neo4j, and audit_neo4j importing graph_store.driver or queries. P06 adds four named ignores in backend/.importlinter (DEC-084 item 8c), and the probe tree in tests/architecture/test_import_rules.py needs a module for each ignore target, or the architecture tests fail. Keep each ignore to one module pair. Run: PYTHONIOENCODING=utf-8 python -m uv run lint-imports.

## L109 QueryBoard reads confirmations per service: BookingRepository has no batch confirmed_since

By build-U08b on 2026-10-26T22:02:10.161641+00:00. Applies to: U09, R05, P02, W05.

BookingRepository.confirmed_since takes one service id, so the board calls it once for each service that has a latest report (U08, DEC-085 item 1). The rule 'one query per repository call across all services' cannot hold for confirmations without a new P02 port method. Do: if you need confirmations for many services, add a batch form in a P02 follow-up (for example confirmed_since_for_services returning dict[str, list[datetime]]) before you rely on the board at scale. Pending counts are already batched (open_for_services). Affects U09 (board cache), R05 ($board) and any caller that lists many services.

## L110 Board sample: a confirmation after the clock is not a fact; read the board later

By build-U08b on 2026-10-26T22:02:10.407236+00:00. Applies to: W05, U09, R05.

The U08 prompt reads the board at Friday 14:12 but adds a booking confirmed at 14:19. A confirmation after the clock cannot be stored as a past fact for that read. U08 tests it by reading the confirmed step at 14:25 (13:25 UTC) and asserting the result, not the time (DEC-085 item 3). Do the same in any test that mixes a clock with sample times from the artboards. The Main artboard samples (ui-screens.md) use times up to 16:00, so check each one against the clock before you write it as a fact. Note also: a sync test in a module with pytestmark asyncio emits a warning, so make it async.

## L111 Catch unhandled API errors in an outer middleware: Starlette's 500 handler lets the server log the message

By build-R01b on 2026-10-26T22:07:20.137225+00:00. Applies to: R02, R03, R04, R14, R15, R18, I03, I05, I08.

Starlette's exception handler for Exception responds with 500 and then re-raises, so uvicorn logs the message and the traceback. A FHIR error can carry a postcode, so the message leaks into the server log. R01 uses an outer ASGI middleware (UnhandledErrorMiddleware in adapters/inbound/fhir_rest/errors.py) that logs the exception class name only and sends the OperationOutcome itself. Do the same in any new inbound adapter. Decision: DEC-085 item 4. Test: tests/integration/adapters/inbound/fhir_rest/test_app.py::test_an_unexpected_error_is_logged_without_its_message_or_trace.

## L112 Error bodies use DEC-085's codes: 415 is not-supported, and framework 404 and 405 are OperationOutcome too

By build-R01b on 2026-10-26T22:07:20.369979+00:00. Applies to: R02, R03, R04, R14, R15, R18.

The prompt's error list does not name a 415, so the route tasks must not invent one. R01 uses not-supported for 415 and 405, not-found for an unknown path under /fhir, and invalid for other 4xx. Request validation errors are 400 invalid with expression set to the location, never the input value. Each shape is tested in test_app.py. Read DEC-085 before adding an error path.

## L113 Route tests build the container on a Neo4jConnection, not on neo4j_driver

By build-R01b on 2026-10-26T22:07:20.592600+00:00. Applies to: R02, R03, R04, R14, R15, R16, R17, R18, I03.

build_for_tests needs neo4j=<Neo4jConnection> (F08 signature). R01's test_container fixture (tests/support/api.py) opens one Neo4jConnection on harness_container (uri, user, password), passes it to build_for_tests with FixedClock(2026-10-23T13:12Z), and closes it per test. api_app is create_app(test_container) and api_client is httpx ASGITransport on it. Reuse the fixtures; add test-only routes to api_app. Decision: DEC-086 item 6.

## L114 A value from the injected clock needs a test that asserts its exact value

By build-R01b on 2026-10-26T22:07:20.816012+00:00. Applies to: R02, R03, R04, R14, U01, U08, U25, I03, I05.

R01's metadata date was read from the system clock and every test still passed: the removal mutant survived. Any field built from the container's clock (date, expiry, due time) needs a test that checks the exact value under the fixed test clock. A DEC-010 stub fixture also hides per-guard red: when every route test fails on the same stub fixture, the red run shows nothing per guard, so show each guard's red with a removal run (lesson L88). R01's red2 commit b7d86ed is the example.

## L115 R01 names are in DEC-086 item 8, not in contracts.md: the owner must add them to Additions

By build-R01b on 2026-10-26T22:07:21.048482+00:00. Applies to: R02, R03, R04, R14, U25, U32, U37.

The orchestrator's brief for R01 said not to edit docs/spec source files, so contracts.md is unchanged. The names this task introduces (ApiContainer, create_app, get_container, operation_outcome, FhirJSONResponse, register_resource, the metadata route, and the fixtures test_container, api_app, api_client) are listed in DEC-086 item 8. Use these names exactly; do not invent a second one. Dependency note: fastapi 0.162.0 and httpx 0.28.1 are on task/R01-fhir-rest-skeleton (commit dbbb935), so any route task rebases onto R01 before it adds a package to uv.lock.

## L116 Correction to L111-L115: R01's decisions are DEC-086 (errors) and DEC-087 (wiring); DEC-085 is U08's

By build-R01b on 2026-10-26T22:08:36.338078+00:00. Applies to: R02, R03, R04, R14, R15, R18, U08, I03, I05.

DEC-085 is taken by task/U08-query-board (QueryBoard, unmerged). R01 renumbered its entries to DEC-086 (error bodies, body types, unexpected errors) and DEC-087 (app wiring, metadata registry, API fixtures), in commit 366d929 on task/R01-fhir-rest-skeleton. Where L111, L112, L113 or L115 cite DEC-085 or DEC-086 for the wiring, read DEC-087. The rules in those lessons stand. Check every task branch for the next DEC number before writing one (L32, L43).

## L117 Redis SUBSCRIBE is live only when the server confirms it: publish waits for that confirmation

By build-I01 on 2026-10-27T08:24:43.953578+00:00. Applies to: I05, U08, R06, I03.

redis-py sends SUBSCRIBE and reads the server reply later, so a PUBLISH sent right after subscribe() can be lost. The I01 adapter starts SUBSCRIBE in a task, waits for the server subscribe reply, and RedisCache.publish waits for every subscription that cache made before it sends. This holds inside one process only. A publish from another process can still be missed in the round trip after subscribe(). Do: a live-update consumer must refetch its data on connect and after any reconnect, and must not assume a publish from another worker reaches it right after subscribe(). Tests: tests/contract/test_cache_contract.py (publish-between-subscribe-and-read case, redis id); mutant with the barrier removed fails 6 or 7 cases.

## L118 A Redis fencing counter is only as durable as its Redis: data loss restarts tokens at 1

By build-I01 on 2026-10-27T08:24:44.608006+00:00. Applies to: I03, I05, U08.

acquire_lock takes its token from INCR on diucs:fence:<name>, which never expires (DEC-058 item 2). The compose Redis has no volume, and a managed Redis can lose data or restart, after which the counter starts again and a new holder can receive a token an old holder already used. Redis alone cannot keep tokens increasing across that event. Do: a writer guarded by a fencing token must also compare the token with the highest token it has already committed in Neo4j, which is a fact of record, before it writes. The outbox relay lock (I03) must do this. Do not rely on Redis for this guarantee. Recorded in DEC-089 item 4.

## L119 A close test must wait until the reader is blocked, or it tests the closed path instead of the wake-up

By build-I01 on 2026-10-27T08:24:45.020946+00:00. Applies to: I05, R06, U08.

A reader started with ensure_future and then closed at once takes the closed-subscription branch before it waits on the queue, so a test named close wakes a waiting reader passes even with the wake-up removed (mutant survived in I01). Do: await the subscription opened task, start the reader, await asyncio.sleep(0) so it blocks on the empty queue, then close. Then confirm the test fails with the wake-up line removed. Test: tests/unit/adapters/outbound/cache_redis/test_redis_cache.py::test_a_closed_subscription_ends_a_reader_that_is_waiting.

## L120 redis-py pubsub: one reader per connection, and close by UNSUBSCRIBE plus its reply

By build-I01 on 2026-10-27T08:24:45.355946+00:00. Applies to: I05, R06.

get_message with timeout None blocks, and two tasks reading one PubSub take each other replies. The I01 adapter gives each subscription one reader task that ends on the unsubscribe reply, and closes the connection only after that reply, so PUBSUB NUMSUB is 0 when aclose returns. Closing the connection without UNSUBSCRIBE can leave NUMSUB at 1 for a moment, which is a race, not a pass. Test: tests/integration/adapters/outbound/cache_redis/test_redis_cache.py::test_closing_a_subscription_unsubscribes_it.

## L121 The Redis cache suite is the first integration factory: -m integration tests/contract now exits 0

By build-I01 on 2026-10-27T08:24:45.676106+00:00. Applies to: I02, I05.

With the redis factory marked integration, pytest -m integration tests/contract collects 23 cache cases and exits 0 (DEC-077 item 4). The Redis factories share the compose Redis and flush only diucs:* keys before and after each case, so they need no per-session container. Other sessions running the cache suite at the same time share the diucs: keyspace. Use the same factory shape for the Service Bus emulator (I02).

## L122 A racing MERGE on a unique key waits, then matches: it returns not-new, not Conflict

By build-P15 on 2026-10-27T08:40:24.451717+00:00. Applies to: P13, P14, P17, U25, U30, U32.

P15 measured two concurrent MERGE on a keyed node with a unique constraint. The second MERGE waits for the held first write; after the first commits it matches the committed node and returns not-new. It raises ConstraintError only when a CREATE meets the key. Expect a racing test to see False for the waiter, and write the expectation from the measured behaviour. A held-transaction test must assert the count of nodes, which is 1 with the constraint and 2 without it. Affects P13, P14, P17, U25, U30, U32.

## L123 Compare instants with astimezone(UTC) before asserting equality across zones

By build-P15 on 2026-10-27T08:40:24.607177+00:00. Applies to: U08, U25, U40, D23, I03.

Python compares two aware datetimes in different zones by instant only when neither is ambiguous. On 2026-10-25 a London 01:55 is ambiguous (PEP 495, fold 0 is BST): comparing it with a UTC value of the same instant can be False. In a test, convert the expected value with astimezone(UTC) first, then compare. Found in P15 (test_a_london_datetime_comes_back_as_the_same_instant_in_utc). Affects any test that round-trips a London time.

## L124 The Cache port subscribe is async now: await it, and it returns only once the server confirms

By build-I01 on 2026-10-27T08:53:01.467080+00:00. Applies to: I05, U08, R06, I03.

Changed by I01 (DEC-092). Callers must write subscription = await cache.subscribe(channel). subscribe returns only after the server has the subscription, so a publish sent right after it is delivered. The memory fake matches. Publish is no longer gated in-process. The owner must add this signature change to contracts.md Additions. Lesson L117 (subscribe confirmation) is superseded by this rule. Affects I05, U08, R06, I03.

## L125 A fencing token that must grow across a Redis loss cannot start at 1: the first token of a lock name is no longer 1

By build-I01 on 2026-10-27T08:53:01.755084+00:00. Applies to: I03, I05.

DEC-091 issues max(INCR, host clock in microseconds). A fresh counter and a lost counter look the same to Redis, so a lock name's first token is a large number, not 1. Two contract cases assert 1 and fail on the Redis adapter until the owner rules (DEC-091 item 4). Do not weaken those cases. Consumers must compare tokens only with the last token recorded in Neo4j, never assume the first token is 1. Affects I03, I05.

## L126 L90 correction: Community Neo4j does refuse a duplicate composite unique key

By sharon-orch on 2026-10-27T08:58:59.202403+00:00. Applies to: P15, P16, P13, P14, P04.

L90 said Neo4j Community lacks composite uniqueness. A verifier probe on Neo4j 5.26.32 Community (P15, round 1) found a composite unique constraint refuses a duplicate. L90's advice still holds (a single-property unique key is the safest, and a MERGE on a keyed node races without one), but the claim that composite keys are unavailable is wrong. Do not cite L90 for that. Affects P15 (DEC-090 items 5 and 10), and any earlier decision that repeats the claim: P16 DEC-071 item 1, DEC-073, DEC-074, P04, P13, P14.

## L127 Service Bus emulator: cancel of a non-pending number is an error; session receives need a longer open window

By build-I02 on 2026-10-27T14:23:59.068774+00:00. Applies to: I02, I03, I05.

Emulator 2.0.1 findings (I02). (1) cancel_scheduled_messages on a sequence number that is unknown, already delivered, or held by another queue raises ServiceBusError whose text is 'The scheduled message with SequenceNumber = N is already being cancelled'. Cancel of a pending message succeeds. The port says cancel of an unknown or delivered number does nothing, so the contract and the emulator disagree; do not weaken the case, record a DEC first. (2) Receiving from a session-enabled subscription with ServiceBusSessionFilter.NEXT_AVAILABLE and a short max_wait_time (0.3 s) raises OperationTimeoutError on opening the link when nothing is waiting; use a longer open window and treat that timeout as no message. (3) A contract run that drains and receives topic messages took over 280 s for 8 cases, so run the servicebus factory with a timeout and expect the topic cases to be slow. Affects I02, I03, I05.

## L128 A fake that fails at its first call hides the guard behind it

By build-U09 on 2026-10-27T14:25:10.669556+00:00. Applies to: U08, I04, I05, R06, I03.

U09: the publish-failure test used a cache whose set already failed, so publish was never reached and removing the publish guard left the test green (mutant survived). Make each failing fake fail at one call only: a cache that stores and fails only on publish, a cache that reads and fails only on set. Then run one removal mutant per guard, and check each mutant fails a test. Also: a guard that exists in two places (a TTL on two writes) needs a removal run on each write. Found by U09 removal runs (evidence U09.md, M3a and M4).

## L129 The board refresh events include PhoneTaskRaised before its event class exists (U06)

By build-U09 on 2026-10-27T14:25:10.923351+00:00. Applies to: U06, U09, I04.

U09's projector rebuilds the board on the name PhoneTaskRaised, which the events module does not define yet (contracts.md places it in capacity.events, U06). handle() takes an event name and payload, so it works now by name. When U06 adds the class, keep the name in REBUILD_EVENTS (board_projector.py) and add the class to the DomainEvent union, as lesson L53 says. Do not drop the name if U06 is late: a missing rebuild leaves the wall board stale up to 60 s (H-27).

## L130 One cached board serves every role: a role-specific filter needs its own cache key

By build-U09 on 2026-10-27T14:25:11.232393+00:00. Applies to: R05, U08, W05, R06.

board:v1 holds one board for all roles. QueryBoard refuses only the anonymous link, so the projector checks that role before it reads the cache (test_the_anonymous_link_is_refused_even_when_the_board_is_cached). If a later task filters the board by role, service or flag inside QueryBoard, a shared key would leak one role's view to another. Give that filtered view its own key, or do not cache it. Decision DEC-099 item 7.

## L131 FHIR routes: a 401 is login through errors.py, and the BFF secret comes from app.state.secrets

By build-R02 on 2026-10-27T14:25:14.693119+00:00. Applies to: R03, R04, R14, R15, R16, R17, R18, I13, W02, W09.

DEC-095: a missing, expired or badly signed bearer token is 401 with code login and WWW-Authenticate Bearer. R01's errors.py maps 401 to login only; other 4xx keep their DEC-086 codes. Route tests that need a token set api_app.state.secrets = FixedSecretStore({'bff-jwt': TEST_BFF_SECRET}) and mint tokens with issue_test_token (adapters/testing/tokens.py). A missing store or secret is a 500 (RuntimeError, class name logged), never a pass (DEC-096). Do: put current_actor, require_role and ensure_can_act_for in route signatures as Depends; never answer a missing token with NotAllowed. Decision: DEC-094 to DEC-096 (R02, branch task/R02-auth-roles).

## L132 A booking Task has no Task.code, so the reporter projection covers every Task (fail closed); fhir.resources 8.3 names

By build-R02 on 2026-10-27T14:25:14.945018+00:00. Applies to: R04, R05, R12, U17, U18, P02.

P02 (DEC-063) writes no Task.code, so a booking cannot be told apart by code. PROJECTIONS.register('Task', Role.REPORTER, fn) removes focus and for from every Task a reporter gets (DEC-098 item 2). A projection that changes a resource gets meta.security REDACTED; one that changes nothing gets no label. In fhir.resources 8.3 use resource.get_resource_type() (there is no resource_type attribute) and the 'for' element is the attribute for_fhir (alias 'for' in JSON). Model copies: model_copy(update=...) does not validate. Decision: DEC-098 (R02).

## L133 A test that writes audit entries must create the audit head after the wipe

By build-U01 on 2026-10-27T14:25:24.611482+00:00. Applies to: U02, U03, U04, U05, U06, U07, U08, U09.

clean_graph deletes the AuditHead node with everything else, and Neo4jAuditLog.append raises AuditHeadMissing without it. Call ensure_audit_head(driver) in the test body after the seed, or in a seed helper that depends on neo4j_driver (U01 does this in tests/integration/application/conftest.py seed_service). ensure_audit_head is idempotent. Applies to every use-case test that reaches uow.audit.append (U02 onward).

## L134 A fresh SequentialIds in a second use-case instance reuses report ids, which then conflict

By build-U01 on 2026-10-27T14:25:24.911116+00:00. Applies to: U02, U05, U07, U09.

SequentialIds starts counting at 1 for each instance. A test that builds a second use case for the same database gives it the same ids, so the second report id is the first one and the add raises Conflict. Share one IdGenerator across the calls of a test, and move the clock with FixedClock.set() between calls (U01 test helper _rig). Applies to every test that runs a command more than once.

## L135 A mutant that another check already refuses survives: give the guard a case only it refuses

By build-R02 on 2026-10-27T14:48:00.679866+00:00. Applies to: R03, R04, R14, R15, R16, R17, R18, I13, W02, W09.

R02 mutation runs: removing the header alg check or the size limit left every test green. The tests used inputs another check also refuses (a bad alg fails the signature; a token with no dots fails the part count). Fix: a correctly signed token whose only fault is the guarded property (a header naming HS512 over an HS256 signature; a long token with a valid signature). Also: a runner that edits a file must restore it byte for byte; check git status after. Decision: DEC-094 item 2 (R02, branch task/R02-auth-roles).

## L136 Design canvas moved to 1793087974-239d; UI tasks wait for snapshot refresh

By orch-sharon on 2026-10-27T17:18:22.908191+00:00. Applies to: UI tasks reproducing screen wording and states (W-series, F09-follow-ons, X-series UI).

The live design canvas (Artifact HFH2vRs95QbWbSFXbaLomk) is at version 1793087974-239d, not the snapshot 1792828565-7f44 in sources.json. Its project now holds about 70 dc.html screens, so wording in docs/spec/ui-screens.md may be stale. Do not claim or build any UI task (tasks that reproduce screen wording or states) until the orchestrator refreshes the canvas snapshot and publishes a follow-up lesson. Backend and domain tasks are unaffected. The sprint-plan artifact (J72UZiG9P5ka2PBoteQyYF) is not openable from the orchestrator's account, so tasks.json in the repo stays the working copy.

## L137 A prompt expectation that falls before the report producing it is unmeetable: check it against the clock first

By build-U01 on 2026-10-27T17:28:25.218494+00:00. Applies to: U02, U03, U04, U05.

U01 test 2 expected Next prompt 14:00 after a report at 13:12Z (14:12 BST). 14:00 BST is 13:00Z, before the report, so no correct echo can give it. DEC-101 records 16:00 and the prompt snapshot is not edited. What to do: for each expected due or next-prompt time in a prompt, check that it falls after the report and after the clock instant before you build to it, and record a decision if it does not. Affects the next-prompt and echo paths (U02, U03, U04, U05).

## L138 After-the-fact red: remove the guard, run the whole test file, and mutate a deterministic sort key, not a tie-break

By build-U01 on 2026-10-27T17:28:25.411156+00:00. Applies to: P13, P14, U08, U09, U25, U32, U37.

When a guard was committed with its test (no red commit for it), show it red by removing the guard in the current code, running the whole test file with -rf, and restoring the file from git (checking git status). Say in the evidence that it is after the fact, not the original red commit (L88). In U01 the repository latest query orders by effectiveDateTime DESC, lastUpdated DESC: mutating the effective key (DESC to ASC) fails the back-dated test deterministically. A lastUpdated-only mutant would depend on second-granularity ties (L65) and can pass by chance. Run each mutant with a script that asserts the old text occurs exactly once, so a silent non-application cannot pass as a red run.

## L139 A red stub must fail every test of its guard: a plausible stub value passes the refusal test

By build-I06 on 2026-10-27T17:38:30.723421+00:00. Applies to: I07, I10, I12.

I06 round 1: the stub send returned SendReceipt('', False), so the listed-refusal tests (accepted is False) passed at red, and a log test passed because nothing was logged. Fix: make the stub return the opposite value (accepted True) so each refusal test fails on its assertion, and assert on the logged id and code so the log test fails on the stub. Then run each guard's test at red and look at the failing list: a guard test that is green in the red run is not a red test. Also: a guard added after the green commit needs its own red commit (I06 did round 2, aad9c4f, before the guards). Tasks: I07, I10, I12.

## L140 The I06 prompt's Twilio-or-Notify open decision is closed: Twilio is fixed (DEC-002), I16 is cancelled

By build-I06 on 2026-10-27T17:38:31.151444+00:00. Applies to: I07, I10.

I06 prompt says 'Open decision: Twilio or GOV.UK Notify' and 'ask the product owner'. DEC-002 settles it: Twilio is fixed, I16 is removed. Build the Twilio adapter behind SmsSender and do not add a provider switch. The UK sender number, data region and sub-processors stay human-only. Tasks: I07, I10.

## L141 SmsSender consumers: a refused send has provider id '' and a retry after a timeout can send twice

By build-I06 on 2026-10-27T17:38:31.576915+00:00. Applies to: I10, I07.

DEC-101 (I06). (1) A Twilio refusal (21211, 21614, 21610) returns SendReceipt('', False): Twilio issues no sid, so the consumer must store no provider id (not the empty string) and must not look it up. (2) TransientSendError on a timeout does not prove the text was not sent. The consumer retries with the same message id, and a duplicate text is possible; there is no Twilio idempotency key on this path. (3) SendFailedError (any other answer) is not retried: record it as failed for staff, do not loop. Tasks: I10 (consumer of messages.outbound), I07 (status callback).

## L142 A self-SET of a changing property writes back a stale value: lock with a fresh stamp, then read

By build-R03 on 2026-10-27T17:54:51.578136+00:00. Applies to: R04, R14, R15, R16, R17, R18, U25, U30, U32.

Found by R03. SET t.versionId = t.versionId takes the write lock, but the value it writes is the one read before the lock was granted. A writer that held the node and committed version 4 was overwritten with 3 when the waiting statement ran: the PUT returned 200 instead of 412 on the harness Neo4j. Do: SET a separate lockStamp to a fresh value in one statement, then read the version in a second statement, as the G05 Q-RES-LOCK query does. The self-SET trick of lesson L73 is for properties that never change, such as an id. Test: backend/tests/integration/adapters/inbound/fhir_rest/test_concurrency.py::test_a_put_waits_for_a_held_write_then_sees_the_new_version_and_is_refused (a held uncommitted write; the request must wait, then see the committed version).

## L143 Coverage: the coverage script is blocked on this Windows machine; run it as python -m coverage

By build-R03 on 2026-10-27T17:54:51.971469+00:00. Applies to: F01, D02, D13, R04, U01.

On this machine the coverage executable is blocked by an Application Control policy (os error 4551), so uv run --with coverage coverage run fails and lesson L23 as written does not work. Run instead: python -m uv run --with coverage python -m coverage run --branch --include=<module path> -m pytest <test files>, then python -m uv run --with coverage python -m coverage report -m. Delete the .coverage file afterwards. Found by R03.

## L144 The scratchpad folder is shared between sessions: give scratch scripts a task name

By build-R03 on 2026-10-27T17:54:52.352056+00:00. Applies to: R04, U01, I03, U08.

During R03 a mutation script written to the shared scratchpad with a generic name was overwritten by another session, and the output mixed two tasks. Write scratch scripts with a task prefix (for example R03-mutate.py), and check that the file you run is the one you wrote. Run mutation runs from a copy of the test command, and restore the source files byte for byte afterwards.

## L145 Front-end worktrees need pnpm install; msw is pinned at 2.15.0 (DEC-109)

By build-W01 on 2026-10-27T22:16:04.841802+00:00. Applies to: W01, W02, W05, W09.

A new worktree has no frontend/node_modules, so run pnpm install --frozen-lockfile in frontend/ before pnpm test, lint or typecheck (about 20 s). W01 added msw as an exact devDependency at 2.15.0; do not move to msw 3.x without a decision, because its peer range does not match @vitest/mocker's msw ^2.4.9 (DEC-109 item 1). test/setup.ts now starts the MSW server with onUnhandledRequest error and resets to test/msw/handlers after each test. Add per-test mocks with server.use() in the test itself.

## L146 Email footer on D15 lacks the last screen sentence (DEC-110 item 7)

By build-I09 on 2026-10-27T22:22:30.657215+00:00. Applies to: D15, I09, I10.

D15's FOOTER in domain/messages/templates.py ends 'This email has no patient information.' ui-screens.md line 1046 adds 'Replies to this address are not read.' The email adapter (I09) adds no copy, so the missing sentence reaches every C1 and C2 email. D15 is delivered and was not edited. Email wording is IG-pending (DEC-042 item 3), so no real email goes out before the owner corrects the footer and IG approves it. Owner or a D15 follow-up task decides the fix.

## L147 An in-process SMTP server logs the body it receives: scope log-capture tests to the adapter

By build-I09 on 2026-10-27T22:22:30.942299+00:00. Applies to: I09, I10.

aiosmtpd, run in the test process, logs every line it receives under the logger mail.log at DEBUG, including the body and the RCPT address. A log-capture test that reads all of caplog fails on the stand-in server, not on the adapter. Filter caplog.records by logger name (exclude mail.log) and assert on the adapter's records. The adapter itself: aiosmtplib 5.1.3 logs nothing. Test: backend/tests/unit/adapters/outbound/email_smtp/test_smtp_email.py::test_logs_hold_neither_the_address_nor_the_body.

## L148 R06 delivered-at reference is wrong; the content is delivered at ab56d41

By orch-sharon-r6 on 2026-10-28T00:18:37.539185+00:00. Applies to: R06.

The ledger records R06 as delivered at b6e1283. That commit is not on main: the fast-forward failed because main had moved, and the delivery command ran after a failed merge in a pipeline that hid the failure. The R06 content is on main at ab56d41 (code f899f86, rebased onto main 16b31ab). verify-R06-r4 passed ab56d41; the earlier pass (verify-R06-r3) was at afa6a3e. Anyone building on R06 should use ab56d41 as the base. Lesson for everyone: never chain a fast-forward merge into a delivery with a pipe; check the merge exit code first.

## L149 Test harness containers must be removed with -v: docker rm -f alone leaks two anonymous volumes per run

By build-F10fix on 2026-10-28T10:00:29.476030+00:00. Applies to: F10, G14, I01, I05, P06, P15.

The neo4j image declares anonymous VOLUMEs for /data and /logs. docker rm -f <name> leaves them, and the harness did this until F10-fix (70 volumes, 18 GB in about an hour; the disk filled). Any container a test starts must be removed with docker rm -f -v (DEC-128), or given a named volume you remove yourself. Clean existing leaks with docker volume prune -f, which only removes volumes no container references. Check with: docker volume ls -qf dangling=true | wc -l before and after a run.

## L150 UI tasks proceed from the repo snapshot of the design canvas (DEC-129); record canvas differences for v1.1

By orchestrator on 2026-10-28T10:08:00.205644+00:00. Applies to: W04, W05, W06, W07, W08, W09.

The owner has ruled (DEC-129) that the repo docs/spec/ui-screens.md and docs/design/ are the specification for the build, so the hold in L136 no longer applies: claim UI tasks as normal. If you notice the live canvas differs from the snapshot, do not stop and do not fail a task for it. Add a Canvas differences note to the task evidence. All such notes go to a v1.1 pass after every task is delivered.

## L151 A context variable set by a sync yield fixture or an async fixture reaches async tests and their tasks; a sync web dependency or a thread cannot bind it for the request

By build-TEN-001 on 2026-10-28T13:55:14.092840+00:00. Applies to: TEN-002, TEN-003, TEN-018, TEN-019, TEN-020, TEN-025, TEN-035.

Observed in real tests (TEN-001, backend/tests/unit/application/test_tenancy.py, pytest-asyncio 1.4.0, anyio 4.15, Python 3.14, asyncio_default_test_loop_scope = session). (1) A ContextVar set by a synchronous yield fixture is visible in the async test body, in asyncio.create_task children, in asyncio.gather children and in TaskGroup tasks, and is unset at teardown. The same holds for an async fixture (pytest-asyncio copies the fixture's context changes into the test context and undoes them), and neither leaks into the next test. So TEN-003's bound-tenant fixtures can use the plain synchronous form: with bind_tenant(...): yield. (2) A value bound before create_task is visible in the task; a value bound inside a task is gone for the parent after it. (3) asyncio.to_thread and anyio.to_thread.run_sync run the function in a COPY of the caller's context: they see the caller's binding, and a binding entered inside the thread function does not outlive it. So a synchronous FastAPI dependency (run in a threadpool) cannot bind the tenant for the request: bind in an async dependency or in the handler body (TEN-018 proves the framework side). (4) Hypothesis works with async tests under pytest-asyncio (use suppress_health_check=[HealthCheck.function_scoped_fixture] when an autouse fixture exists). (5) The tenancy kernel lives in diucs.application.tenancy: ScopeId.tenant / ScopeId.network / ScopeId.parse, bind_scope / bind_tenant, current_scope / current_tenant, TenancyMode and use_tenancy_mode; names are listed in docs/spec/contracts.md and DEC-137 (on branch task/TEN-001-seam-warn until delivered).
