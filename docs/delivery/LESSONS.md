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
