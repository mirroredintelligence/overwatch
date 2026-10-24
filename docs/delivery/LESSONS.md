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
