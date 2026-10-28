# Tenancy audit E: tests and test harness

Audit of `main` at 1ac81b9 (read-only); section 11 added after DEC-132 (main at 780bb3e). Scope: `backend/tests/**`, every conftest, `frontend/test/**`, frontend unit and e2e tests, `.github/workflows/ci.yml`, `backend/Makefile`, the scripts under `.claude/skills/diucs-delivery/scripts`, and the tests on the four unmerged branches (I04, U02, U03, W02, read from their worktrees under `/home/user/overwatch-wt/`). Nothing was run: no pytest, Docker, app or tenancy code. Counts come from `grep -c` and file listings.

Method note on counts: "tests" below means `def test_` / `it(` / `test(` definitions. Parametrised and Hypothesis tests collect into more items than this (backend: 266 `parametrize` and 72 `@given` lines in unit, 20 `parametrize` in integration, 3 in architecture, 1 in contract). Pytest was not run, so collected-item totals are not stated.

---

## 1. SUMMARY

### 1.1 Counts (verified)

Backend, `backend/tests`:

| Area | Test files | Test functions | Notes |
|---|---|---|---|
| unit | 107 | 1450 | unit/domain 49 files, 901 tests; unit/adapters 41, 453; unit/application 9, 51; unit/bootstrap 2, 18; unit/support 4, 10; `unit/test_ci_workflow.py` 13; `unit/test_smoke.py` 4 |
| architecture | 1 | 13 | `architecture/test_import_rules.py` |
| integration | 38 | 491 | graph_store 21 files, 297 tests; application 4, 67; adapters 8, 74; audit_neo4j 2, 32; support 2, 14; `test_infra_up.py` 1, 7 |
| contract | 8 | 48 | cache 24, event bus 11, characterisation 2, factory drain 2, redis isolation 2, redis ttl 1, session window 5, markers 1 |
| support modules | 0 | 0 | 8 helper modules in `tests/support` (`api.py` has a fixture named `test_container`, which a naive grep counts as a test) |
| **backend total** | **154** | **2002** | plus 6 conftest/helper modules outside `support` (see 1.2) |

Frontend (`frontend/`): 19 vitest files with 114 tests (`app/tokens.test.ts` 17, `components/ui/*.test.tsx` 47 in 8 files, `lib/**` 38 in 8 files, `app/layout` and wall page 4, `test/msw/server.test.ts` 2), plus 1 Playwright file `e2e/smoke.spec.ts` with 2 tests. Support: `test/setup.ts`, `test/a11y.ts`, `test/msw/{server.ts,handlers/index.ts}` (empty handler list). Total frontend: 20 files, 116 tests.

Delivery scripts: `.claude/skills/diucs-delivery/scripts/test_delivery.py` (38 tests) and `test_converters.py` (4). No tenancy impact.

Unmerged branches (tests only, versus their merge base with main):

| Branch | Test files | Tests |
|---|---|---|
| task/I04-consumer-framework | `integration/adapters/inbound/workers/test_consumer.py` (7), `.../test_servicebus_runner.py` (1), `unit/adapters/inbound/workers/test_servicebus_runner.py` (11) | 19 |
| task/U02-confirm-capacity | `integration/application/test_confirm_capacity.py` (21), 3 added to `integration/graph_store/test_capacity_repository.py` | 24 |
| task/U03-send-prompts | `integration/application/test_send_prompts.py` (27) | 27 |
| task/W02-bff-session-csrf | `frontend/app/api/bff/session/route.test.ts` (11), `lib/auth/csrf.test.ts` (18), `lib/auth/session.test.ts` (28), `lib/bff/handler.test.ts` (15), helper `test/cookies.ts` | 72 |
| F01, F03, F10-fix, W03, claude/optimistic-albattani | no test difference from main | 0 |

### 1.2 Fixtures and helpers

Fixtures defined outside unit: 23. Unit: 10 (7 files, none touch a database).
- Session scope (`tests/conftest.py`): `harness_neo4j` (:52), `harness_driver` (:72), `harness_container` (:79), `neo4j_driver` (:86).
- Function scope: `clean_graph` (:93, added by hook to every integration item), `uow_clock` (:102), `uow_factory` (:108), `test_container` / `api_app` / `api_client` (`support/api.py:26,43,48`), `seed_service` (`integration/application/conftest.py:21`), `cache_harness` / `bus_harness` (`contract/conftest.py:14,23`), per-file: `audit_head` (`test_audit_log.py:62`, `test_unit_of_work.py:37`), `practitioners` (`test_credential_store.py:89`), `conn` (`test_connection_recovery.py:82`), `auth_app`, `things_app`, `stream_app`, `stream_cache`, `empty_registry`, and a module-scoped `neo4j_driver` override in `test_infra_up.py:56` for the compose stack.
- Reference counts: `neo4j_driver` 1359 references in 31 files; `uow_factory` 266 in 10 files; `api_client` 116 in 6 files; `seed_service` 51 in 2; `clean_graph` 15 in 7; `harness_container` 12 in 4.
- Helper modules: `support/neo4j.py` (336 lines), `api.py`, `redis.py`, `round_trip.py`, `servicebus.py`, `things.py`, `uow.py`; `contract/{factories,harness,conftest}.py`.

### 1.3 Touch points

- Neo4j: 35 files import `tests.support.neo4j` (4 of them in `unit/support`, which never reach Docker). 34 of the 38 integration files use the session container's data. The other 4: `test_infra_up.py` (compose stack on 7687), `test_harness_restart.py` (own container per test), `cache_redis/test_redis_cache.py` and `bus_servicebus/test_service_bus.py` (no Neo4j). `clean_graph` loops over `_active` only (`conftest.py:97`), so a Redis or Service Bus test does not itself start a container.
- Raw Cypher string literals in `integration/` and `support/`: 115 (`grep` for statements starting MATCH, CREATE, MERGE, UNWIND, SHOW, DROP, RETURN). 22 are CREATE or MERGE that bypass `run_query` and so will not carry a tenant. About 90 are reads that match by label with no tenant predicate.
- `count_nodes` call sites: 184 across 24 integration files plus harness tests (largest: `test_report_capacity.py` 26, `test_case_repository.py` 18, `test_flag_repository.py` 16, `test_resource_store.py` 13, `test_criteria_repository.py` 12).
- Redis (live, shared `localhost:6379`): `contract/factories.py:92`, `contract/test_redis_isolation.py`, `contract/test_redis_ttl.py`, `integration/adapters/outbound/cache_redis/test_redis_cache.py`, `integration/test_infra_up.py:97`. Contract cache cases: 24 tests, each also run against Redis (24 live cases).
- Service Bus (live emulator on `localhost:5672`): `contract/factories.py:216`, `support/servicebus.py`, `integration/adapters/outbound/bus_servicebus/test_service_bus.py` (7), `integration/test_infra_up.py:159,171`, plus the contract event bus cases (11, each also run against the emulator).

### 1.4 Difficulty assessment

Overall: **medium-high, about 365 hours (range 260 to 470) across 38 tasks**: about 297 hours for tenant isolation (31 tasks, sections 1 to 10) and about 68 hours for the network layer of DEC-132 (7 tasks, section 11). About 28 hours of the total are interim protection that does not depend on tenancy.

Why it is not worse: the tests already use one chokepoint for data (`neo4j_driver` + `uow_factory` + helpers in `support/neo4j.py`), the Redis contract factory already uses a unique key prefix per run, and the pure domain layer (49 unit files, 901 tests) is untouched. Firm edits are 48 of 154 backend test files (31%); a further 18 are conditional on design choices in section 3.

Why it is not easy:
1. Every test writes its data with fixed ids (`svc-ucr-west` 72 uses in 17 files, `svc-1` 36, `dev-1` 44, `prac-1` 26, `case-1`, `bk-4821`, reference `4821`). They only pass today because one container belongs to one run. They stay valid under tenancy only after the unique constraints become composite (DEC-130 item 7). Until that migration lands, sharing a Neo4j between runs breaks them.
2. 115 hand-written Cypher literals in tests cannot be rewritten automatically (DEC-130 item 3 says so for production code; the same holds for test code).
3. The generated two-tenant test (DEC-130 item 4) needs a per-query probe table. About 123 queries are registered, not 78 (section 3.5).
4. Service Bus tests cannot be made parallel-safe by tenancy at all: the emulator has fixed queues and receivers consume other runs' messages (section 4.7).
5. The harness reaper, readiness probe and memory behaviour are the actual cause of the stalls the team sees today, and tenancy does not fix them (section 2.4). They need work whether or not tenancy happens.

---

## 2. THE HARNESS TODAY

### 2.1 How one Neo4j per session starts and stops

`tests/conftest.py`:
- `pytest_sessionstart` (:35) calls `reap_stale_test_containers()` (DEC-108). This runs for unit-only runs too, and again in every nested pytest session that `test_smoke.py` starts through `pytester` (it copies this conftest, `unit/test_smoke.py:34-60`).
- `pytest_collection_modifyitems` (:40-49) adds the `integration` marker to every item under `tests/integration/` and appends `clean_graph` to `item.fixturenames` (lesson L11 trap 1).
- `harness_neo4j` (:52-68), session scope, `loop_scope="session"`: `async with throwaway_driver()` starts a container, connects, then `apply_session_env(container)`, `await apply_migrations(driver)`, appends the driver to module-level `_active`, yields, and clears `_active` on exit. The container is created lazily: only when a test first requests `neo4j_driver`, `harness_driver` or `harness_container`.
- `harness_driver`, `harness_container`, `neo4j_driver` (:72-90) are thin views of that tuple. `neo4j_driver` can be overridden by a module (`test_infra_up.py:56` does); `clean_graph` deliberately does not use that name (L11 trap 2).
- `clean_graph` (:93-98): for each driver in `_active`, `wipe(driver)`.

`tests/support/neo4j.py`:
- `start_throwaway_neo4j` (:79-132): name `diucs-test-neo4j-<12 hex>`, label `diucs-test=true`, a free port picked by binding port 0 on 127.0.0.1 (`_free_port`, :46; there is a gap between closing the probe socket and `docker run` binding it, so two sessions can pick the same port), published as `127.0.0.1:<port>:7687`, password from `secrets.token_hex(16)`, image `neo4j:5.26.32-community` (:35). No `--memory`, no `NEO4J_server_memory_*`, no healthcheck, no volume flags (the image's anonymous volumes are removed by `rm -v`, DEC-128).
- `wait_until_ready` (:135-146): polls `docker exec <name> cypher-shell ... "RETURN 1"` (`_ready`, :66-72, 20 s subprocess timeout) every 1 s until `CONTAINER_READY_TIMEOUT_S = 120.0` (:37).
- `connect_or_fail` (:177-186): driver `verify_connectivity`, 5 s timeout, raises `Neo4jNotRunning`.
- `stop_throwaway_neo4j` (:148): `docker rm -f -v <name>`; raises `RuntimeError` if that fails.
- `throwaway_driver` (:155-166): start, connect, yield, close driver, remove container (also when connecting fails).
- `stop_container` / `start_container` (:111-132): `docker stop` / `docker start`; the caller must `wait_until_ready` (L7).

### 2.2 wipe, migrations, ports, environment

- `wipe` (:238-253): `MATCH (n) WHERE NOT n:Migration WITH n LIMIT 10000 DETACH DELETE n`, looped in batches until 0. Global: it deletes every node of every tenant. Constraints, indexes and `:Migration` nodes survive.
- `apply_migrations` (`src/diucs/adapters/outbound/graph_store/migrations.py`): 26 migrations (0001 to 0009, 0014 to 0030). Each is two write transactions (statement, then `MERGE (m:Migration {id})`) because Neo4j refuses schema and data writes together (L8). Run once per session in `harness_neo4j`. 19 `CREATE CONSTRAINT` statements, all single-property or `(system, value)` / `(system, code)` unique: `resource_id`, `identifier_key`, `concept_key`, `scheduled_work_id`, `communication_id`, `audit_event_id`, `audit_head_id`, `audit_ref_id`, `provenance_id`, `chain_seq`, `link_token_hash`, `case_reference_id`, `device_id`, `protected_contact_key`, `credential_device_id`, `report_flag_id`, `outbox_message_id`, `idempotency_record_key`, `processed_key`.
- Ports: each session gets a random loopback port. The compose stack keeps 7687, 7474, 6379, 5672, 5300.
- `NEO4J_URI` override (DEC-013, `apply_session_env`, :169-174): the harness sets `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` in `os.environ` for the process and ignores any value from the shell. `test_connection_recovery.py:_harness_settings()` (:48-54) and `test_infra_up.py:23-25` (module-level `os.environ.get("NEO4J_URI", "bolt://localhost:7687")` evaluated at import, before any fixture runs) read these. `integration/support/test_neo4j_harness.py:175` proves the shell value is overwritten.
- Reaper (DEC-108, :256-336): lists `diucs-test=true` containers, keeps only names starting `diucs-test-neo4j-`, inspects `Created`, removes (`rm -f -v`) any older than `REAPER_MAX_AGE = 90 min` (:256). Age is the only criterion: a container of a dead run younger than 90 minutes stays, and a live run longer than 90 minutes is removed under it. DEC-108 itself lists both limits. It is also confused by restarted containers.
- No `pytest-timeout`, no `pytest-xdist` in `pyproject.toml` dev group or `uv.lock`. A hung session never ends on its own.

### 2.3 Why runs time out under load (from the code)

1. The readiness probe is a JVM. `cypher-shell` runs inside the container as a Java process per probe. Each probe costs seconds of CPU on an idle 4-core machine (this host: 4 CPUs, 16 GB) and much more when several Neo4j JVMs are starting. The probe loop runs every second and competes with the very JVM it is waiting for. A probe that exceeds its 20 s subprocess limit counts as "not ready". The overall deadline is a fixed 120 s (`:37`).
2. No memory limits. Neo4j 5 sizes heap and page cache from the host's memory when the container has no limit, so N parallel containers each reserve a large share of 16 GB. DEC-108 records "dozens of these exhausted Docker memory and stopped the Service Bus emulator", and DEC-128 records 70 leaked volumes (18 GB) in one hour with four builders.
3. `_docker` has a 60 s default timeout (`:60`), including for `docker run`. If the image is absent, `docker run -d` pulls it inside that timeout; `TimeoutExpired` is then reported as "Docker is not available" (`:100-103`), which is misleading.
4. The harness itself starts extra containers: `test_neo4j_harness.py:144,152,175` (3 tests) and `test_harness_restart.py:35,66` (2 tests) each call `throwaway_driver()`, so one full run starts 6 containers in sequence, not 1.
5. Lesson L67 (origin/ledger-refresh): a Docker daemon restart left a full run stalled on the first Neo4j test for over 9 minutes. There is no timeout around the first test's fixture other than the 120 s probe deadline, so this stall was in `connect_or_fail` or inside a test with no timeout.
6. The Service Bus contract cases are slow by design: 33 s waits (`test_service_bus.py:70`), 30 s cancel delay (`test_event_bus_contract.py:19`), and 280+ s for 8 topic cases (L127). A wall-clock timeout in the caller applies to these as much as to Neo4j.
7. A free port is probed then released (`:46-50`), so concurrent sessions can collide on the port, and `docker run` then fails with a bind error that is reported as "could not start".

### 2.4 What each part becomes under tenancy

| Part | Today | Under tenancy |
|---|---|---|
| Container start (`start_throwaway_neo4j`) | One per session, owned | Two modes: owned (as today; mandatory for schema and lifecycle tests) and attached to a shared instance. Add an `owned` flag to `ThrowawayNeo4j`. |
| `harness_neo4j` | start, migrate, `_active` | owned mode unchanged. attached mode: take a cross-process lock, apply migrations once (idempotent but not safe under concurrent DDL), do not wipe schema. |
| `NEO4J_URI` rule (DEC-013 item 3) | Shell value ignored | Needs an owner ruling. Replace with an explicit opt-in `DIUCS_TEST_NEO4J_URI` for attach mode. Keep ignoring `NEO4J_URI`. |
| `wipe` | Global delete | Two functions: `wipe_tenant(driver, tenant)` (the default for `clean_graph`) and `wipe_all(driver)` (owned mode only, refuse otherwise). |
| `clean_graph` | Wipes `_active` drivers | Wipes only the run tenant's nodes, then re-provisions the tenant's prerequisites (audit head). |
| `count_nodes`, `node_props` | Global by label | Tenant-scoped by default from the bound tenant, explicit override, and a separate `count_nodes_all` for tests that really mean global (only `Migration`). |
| Reaper | Age 90 min | Owner-based (section 8), plus an orphan-tenant sweeper for attached mode. |
| Readiness probe | `docker exec cypher-shell` | Bolt handshake with backoff (cheap), or `docker inspect` health plus `verify_connectivity`. |
| Migration runner | Once per session | Needs a cross-process lock in attached mode. Migrations become table of composite constraints (src change, outside this audit); the tests of them stay in owned mode. |
| `apply_session_env` | Sets env | Same, plus `DIUCS_TEST_TENANT`. |
| `uow_factory`, `neo4j_driver` | Unchanged signature | Unchanged. Tenant arrives through the context variable (DEC-130 item 2). |

---

## 3. THE TENANT-PER-RUN DESIGN

### 3.1 Inconsistencies in DEC-130 that change test design (need an owner or design ruling)

1. Item 1 says every node carries `tenantId`. Item 5 says Concept nodes are shared and read-only. Existing code merges Concepts from tenant requests: `Q-PROV-LINK` (`audit_log.py`, `MERGE (c:Concept ...) ON CREATE SET c.key`), the mapper's `_coding_rel` / `_concept_rels` (`mapper.py:425-480`), and the communication repository (`test_communication_repository.py:125-130` asserts Concept counts). If Concepts stay shared, tenant-scoped wipe leaves them behind (so four `count_nodes(..., "Concept")` assertions change meaning), and concurrent runs MERGE the same `(system, code)` nodes, which creates lock contention and possible deadlocks (Neo4j returns a transient error; managed transactions retry, raw `session.run` does not). My recommendation: first cut, make Concepts tenant-scoped like everything else (simplest to test and isolate), and move shared reference data into a later optimisation.
2. Item 3's allowlist of tenant-free statements must also cover the pre-tenant lookups that cannot know the tenant yet: link-token resolution by hash (the user holds only the token, `Q-LINK-GET` in `link_token_repository.py`), SMS inbound by phone and number, pairing codes, BFF login, and the Service Bus consumer's first step. Each such lookup returns a tenant id; tests for them are listed in 6.2.

### 3.2 Choosing and binding the tenant

- Tenant id format: `t-test-<ownerpid>-<epoch>-<8 hex>` (no `:` because `scoped_key` refuses it, `concurrency.py:105-110`, and Redis key segments use `:`). Embedding owner pid and start time lets a sweeper in attached mode delete tenants of dead runs.
- Without xdist: one tenant per pytest session, generated in `pytest_configure`. With xdist: the controller makes a run id in `pytest_configure_node` and passes it in `node.workerinput`; each worker's tenant is `<runid>-<PYTEST_XDIST_WORKER>` (for example `gw0`). Never derive a tenant from the test name or the worker index alone (collides across runs).
- A second tenant for cross-tenant tests: `other_tenant_id` fixture, derived as `<run tenant>-b`. Torn down by the same sweeper.
- Binding: a new `tests/support/tenancy.py` exports `current_test_tenant()`, `bind_tenant(tenant)` (context manager over the production context variable, DEC-130 item 2) and fixtures. Add a plain synchronous autouse fixture `bound_tenant` for every item under `tests/integration/` (append it in the same hook that appends `clean_graph`, `conftest.py:40-49`, or put it in a new `tests/integration/conftest.py`). A synchronous fixture sets the variable in the main thread's context; the session event loop creates each test's task by copying the current context, so the test and the tasks it creates (`asyncio.gather` in racing tests; `create_task` in `redis_cache.py`) see it. `pytest-asyncio` 1.4.0 also copies context-variable changes made by async fixtures back to the test (`pytest_asyncio/plugin.py:406-424,454-467`), so async seed fixtures can bind too. Spike task TEN-E06 should still prove this on this stack, because it is the single assumption the whole design rests on.
- Reset trap: any request handler or consumer that sets the tenant inside a test's task (for example the FastAPI middleware that reads the bearer token, through `ASGITransport`, which awaits the app in the caller's task) must reset it in `finally`. If it does not, the test's own tenant is silently replaced by the last request's tenant. Add an autouse guard that asserts `current_tenant()` equals the test's tenant at teardown, and a test that sends a request with tenant B's token and then checks the test is still bound to A.
- No-tenant failure: `run_query` must refuse with its fixed-message error when no tenant is bound (DEC-130 item 2). Unit tests in `unit/adapters/outbound/graph_store/test_driver.py` call `run_query` against a stub transaction with no tenant (9 tests); they bind a tenant through a `@pytest.fixture(autouse=True)` in that file, and one new test proves the refusal.

### 3.3 Scoping clean_graph and the helpers

- `wipe_tenant(driver, tenant)`: `MATCH (n {tenantId: $tenant}) WITH n LIMIT 10000 DETACH DELETE n RETURN count(*)`, batched as today. `DETACH` removes relationships to shared Concepts but leaves the Concept nodes. Without a label the planner uses an all-nodes scan, so the cost grows with all tenants' data on a shared instance. A test data set is small (hundreds of nodes per test), but TEN-E06 should measure it; the fallback is a per-label delete over the known label list, which can use the composite `(tenantId, id)` index.
- After the delete, re-provision: `ensure_audit_head` for the tenant (the audit head is a per-tenant node once DEC-130 item 7 lands). Today it is created by three separate fixtures (`integration/application/conftest.py:29`, `test_unit_of_work.py:39`, `test_audit_log.py:64`). Move it into `clean_graph` so a test cannot forget it, and delete the three copies. The test that proves "appending without a head is refused" (`test_audit_log.py:303`) then needs a fixture that removes the head explicitly.
- `count_nodes(driver, label)` (`support/neo4j.py:208`): add `{tenantId: $tenant}` from the bound tenant. All 184 call sites keep their signature, so call sites need no edit; the helper edit covers them. `node_props` (:219) the same. Add `count_nodes_all` and use it only for `Migration` (2 call sites: `test_neo4j_harness.py:134-140`).
- `read_tx` / `write_tx`: unchanged. Add `tx_run(tx, cypher, **params)` that adds `tenant=<bound tenant>` to the parameters, so test Cypher can say `{tenantId: $tenant}` without every call site passing it.
- `uow_factory_on`, `build_for_tests`: no signature change; tenant is ambient.
- Test Cypher lint: an AST test over `tests/integration/**` that fails on any string constant starting with MATCH, CREATE, MERGE or UNWIND and containing no `$tenant`, unless the line carries `# tenant-free: <reason>`. This keeps the 115 existing literals, and every future one, honest.

### 3.4 Assertions that count or read globally (all of them)

`count_nodes(driver, label)`: 184 call sites. By file: `integration/application/test_report_capacity.py` 26, `graph_store/test_case_repository.py` 18, `test_flag_repository.py` 16, `test_resource_store.py` 13, `test_criteria_repository.py` 12, `test_credential_store.py` 11, `test_unit_of_work.py` 10, `test_communication_repository.py` 10, `support/test_neo4j_harness.py` 9, `test_scope_list_repository.py` 7, `test_person_repository.py` 7, `test_contact_store.py` 7, `test_link_token_repository.py` 6, `test_scheduled_work_repository.py` 5, `test_registration_repository.py` 4, `test_idempotency_store.py` 4, `application/test_link_token_service.py` 4, `test_service_repository.py` 3, `audit_neo4j/test_outbox.py` 3, `test_person_round2.py` 2, `test_capacity_repository.py` 2, `test_booking_repository.py` 2, `audit_neo4j/test_audit_log.py` 2, `support/test_harness_restart.py` 1. Labels counted: Observation 22, HealthcareService 15, AuditEvent 11, OutboxMessage 10, LinkToken 10, ServiceCriteria 8, ResourceVersion 8, Resource 8, ReportFlag 7, Patient 7, Communication 7, ServiceRequest 6, ServiceFlag 6, ProtectedContact 6, Device 6, ScheduledWork 5, Credential 5, Task 4, Probe 4 (+3), PractitionerRole 4, Practitioner 4, Concept 4, IdempotencyRecord 3, RegistrationDraftField 2, Migration 2, HealthcareService_AvailableTime 2, Basic 2, Processed 1, List 1. Fixed by the helper change, with these two exceptions: `Migration` (global by nature) and `Concept` (depends on 3.1 item 1).

Raw global Cypher that no helper change fixes (must be edited):

| File:line | Statement | Why it breaks on a shared instance |
|---|---|---|
| `integration/application/test_query_board.py:179-184,409-415` | `MATCH (n) RETURN count(n)` before and after a read-only use case | Another run's writes change the count between the two reads. Must be scoped to the tenant. |
| `integration/graph_store/test_credential_store.py:73` | `MATCH (n) RETURN properties(n)`; `_nodes_holding(text)` (:71) searches every property for a raw PIN | Scans other tenants; a false positive if another run stored the same sample text, and slow. |
| `integration/graph_store/test_contact_store.py:47` | `MATCH (n) RETURN labels(n), properties(n)` | same (no plaintext phone in any node) |
| `integration/graph_store/test_resource_store.py:72-73` | `MATCH (n) RETURN properties(n)` and `MATCH ()-[r]->() RETURN properties(r)` | same, plus relationships |
| `integration/application/test_link_token_service.py:72` | `MATCH (n) RETURN properties(n)` | same (no raw token stored) |
| `integration/graph_store/test_idempotency_store.py:186` | `MATCH (n) WHERE n:IdempotencyRecord OR n:IdempotencyValue OR n:Processed` | same |
| `integration/graph_store/test_registration_repository.py:204` | `MATCH (n) WHERE n:Task OR n:RegistrationDraftField` | same |
| `integration/graph_store/test_case_repository.py:132-136,160,253` | `MATCH (n) WHERE n.postalCode IS NOT NULL OR n.json CONTAINS 'DT4'`; global `count(r)` on `REASON_CODE`; `ServiceRequest {reference: '9999'}` | same; the reference lookups also depend on composite uniqueness |
| `integration/audit_neo4j/test_audit_log.py:127,218-264` | `MATCH (:AuditEvent)-[r:SNAPSHOT]->(:Snapshot) RETURN count(r)`, and five `scalar(...)` counts over `Provenance`, `AuditRef`, `Concept` | global relationship counts across tenants |
| `integration/graph_store/test_communication_repository.py:123-136,242-245` | `_count(...)` over Concept and relationships | Concept question (3.1) plus global edge counts |
| `integration/graph_store/test_scope_list_repository.py:234,313` | `(:List)-[e:ENTRY]->(:HealthcareService {id: $id}) count(e)` | no tenant on the match |
| `integration/graph_store/test_person_repository.py:95` | `MATCH ()-[r:\`...\`]->() RETURN count(r)` | global edge count |
| `integration/graph_store/test_scheduled_work_repository.py:178` | `MATCH (s:Resource {key: $key}) RETURN count(s)` | no tenant |
| `integration/graph_store/test_connection_recovery.py:65-77` | `MATCH (n:G14Probe)` count and `DETACH DELETE` | run in the "alone" group (section 5), but the probe label must still not leak |
| `integration/test_infra_up.py:77-90` | `InfraProbe {id: 'p1'}` on the compose stack | compose stack, not the harness; fixed id collides between runs on 7687 |
| `support/things.py:29,48` | `MATCH (t:TestThing) RETURN count(t)`, `CREATE (:TestThing {id, versionId})` | `count()` is a global count used by `test_concurrency.py:150`; `CREATE` writes no tenant |
| `integration/adapters/inbound/fhir_rest/test_api_support.py:15` | `MATCH (m:OutboxMessage) RETURN m.id ORDER BY id` | returns other tenants' outbox ids |
| `integration/application/test_report_capacity.py:~110` (`_communications`) | `MATCH (c:Communication) OPTIONAL MATCH (c)-[:TOPIC]->(t:Concept)` | global |
| Unmerged: `U03 test_send_prompts.py:92,207,212` | `ALL_COUNTED_LABELS` snapshot of every label, and `MATCH (n) RETURN properties(n)` | global |
| Unmerged: `U02 test_confirm_capacity.py:279-289,536-541` | `count_nodes` before/after deltas | fixed by the helper change |
| Unmerged: `I04 test_servicebus_runner.py:68` | `count_nodes(.., "Processed") == len(set(calls))` | `Processed` counted globally while the runner drains a shared queue |

`RETURN count(` in racing-outcome code (`outcomes.count("stored")` in `test_flag_repository.py:345`, `test_person_repository.py:313`, `test_case_repository.py:199`, `test_credential_store.py:310`, `test_idempotency_store.py:163,246`) is a Python list count, not a database count; no change.

### 3.5 The registry is bigger than 78

DEC-130 says 78 statements. A `grep -c "NamedQuery("` over `src` gives 78 constructor sites, but many queries are registered through dictionaries and loops: `idempotency_store.py:41-89` (6), `link_token_repository.py:48`, `contact_store.py:38`, `credential_store.py:98` (10), `communication_repository.py:109` (9), `resource_store.py:579-580` (17, built from a template with `{insert}`), `health.py:14` (ping). A count of query-id definitions gives about 123. The true registry size must be read at runtime (I did not import the modules). The generated isolation test must cover all of them, so size it for 120 to 130, not 78.

Test code also pollutes the registry. `integration/graph_store/test_driver.py:32-39` registers `Q-TEST-ECHO` and `Q-TEST-WARN` into the production `REGISTRY` at import, which means at collection, so in a full run they sit in `REGISTRY` while the generated two-tenant test and the `$tenant` mention test iterate it. Neither mentions `$tenant`. Fix: register them in a private `QueryRegistry` and pass `registry=` to `run_query` (the parameter already exists), or add them to the explicit allowlist from a test-support module. `unit/.../test_queries.py` registers `RETURN 1` queries into private registries; those need a `tenant_free` flag or a registry constructed with `enforce_tenant=False`.

---

## 4. TESTS THAT ASSUME ONE TENANT OR GLOBAL STATE

For each: what it assumes (file:line) and what changes.

### 4.1 Audit chain head, ChainLink sequence, hash chain

- `integration/audit_neo4j/test_audit_log.py` (19 tests). Assumes one head `id='audit'`: `node_props(neo4j_driver, "AuditHead", id="audit")` (:112); one global `seq` series: `MATCH (e:AuditEvent {seq: 2})` (:91) and `{seq: 1}` (:387); `Neo4jAuditLog(tx).records()` returns every event; `verify_chain()` walks the whole graph; first record's `previous_hash == GENESIS_HASH` (:77). The `Q-AUDIT-*` queries (`audit_log.py`) all use `AuditHead {id: 'audit'}`. Under tenancy: one head and one `seq` series per tenant, so these tests run unchanged in spirit but each match gets `tenantId: $tenant` and the head lookup uses the tenant's head. New decisions needed: is genesis per tenant (a constant `GENESIS_HASH` makes two empty chains identical) and does the hash input include the tenant? Tests in 6.3 assert whichever is chosen.
- `chain_seq` constraint (`migrations.py`, `0020_chain_seq`, `ChainLink.seq IS UNIQUE`) is global: with two tenants each starting at seq 1, the second tenant's first append fails. The composite migration `(tenantId, seq)` must land before any shared instance. `test_audit_log.py:132` (two concurrent appends) and `test_unit_of_work.py` rely on the head write lock serialising appends (lesson L63); with per-tenant heads, appends of different tenants no longer serialise on one node, which is the point, and needs a test (6.3).
- `ensure_audit_head` fixtures: `integration/application/conftest.py:29`, `test_unit_of_work.py:39`, `test_audit_log.py:64`. Change: one place, inside `clean_graph` (3.3).
- `unit/application/ports/outbound/test_audit.py` (7 tests): `GENESIS_HASH`, `chain_hash_over`; edit only if genesis or hash input becomes tenant-aware.
- `integration/graph_store/test_unit_of_work.py` (11 tests, 4 use `audit_head`): the commit-together tests keep working with the shared fixture.
- Test for tamper detection edits the chain with raw Cypher (`test_audit_log.py:91,189,387,410,434,459`): add `tenantId: $tenant`, and add a test that tampering in tenant A leaves tenant B's `verify_chain()` true.

### 4.2 :Migration nodes, constraints, indexes

- `integration/graph_store/test_driver.py`: `_reset_bookkeeping` deletes every `:Migration` node (:43-45, used at :52 and :110); `EXPECTED_MIGRATION_COUNT = 26` (:22); `EXPECTED_CONSTRAINTS` and `EXPECTED_INDEXES` (:23-29); `DROP INDEX obs_by_service` (:109); every migration statement runs twice (:78-88). All destructive to the schema of the instance. Under tenancy: stay in owned mode (section 5); update the expected count and constraint names for the composite migrations; `test_migration_ids_are_unique_and_run_in_ascending_order` (:166) is pure and can move to unit.
- `integration/support/test_neo4j_harness.py:110-141` (`constraint_from_migrations_survives_wipe`, `migration_nodes_survive_clean_graph`): `Migration` count equals `len(MIGRATIONS)`, `wipe` leaves it. Under tenancy `wipe_all` is owned-mode only and these keep their meaning; `count_nodes_all` is needed.
- `unit/adapters/outbound/graph_store/test_migration_ids.py` (11 tests): pins migration ids by name (outbox, idempotency, link token). New migrations change the expected lists.
- Concurrent DDL: `apply_migrations` running in two sessions at once against one instance races on `CREATE CONSTRAINT ... IF NOT EXISTS` (Neo4j can throw an equivalent-schema-rule error) and on the `MERGE (m:Migration)` bookkeeping. In attached mode, apply under a cross-process lock; assert it in a test with two simultaneous sessions.

### 4.3 Fixed ids that collide across runs

Collisions matter because the current constraints are global: `resource_id`, `scheduled_work_id`, `communication_id`, `audit_event_id`, `audit_ref_id`, `provenance_id`, `device_id`, `report_flag_id`, `outbox_message_id`, `credential_device_id`, `case_reference_id`, `link_token_hash`, `idempotency_record_key`, `processed_key`, `protected_contact_key`. Two runs on one instance writing `svc-ucr-west` fail at once. Under per-tenant composite constraints they are valid. The fixed values, by use count in `integration/`, `support/` and `contract/`:

| Id | Uses | Files |
|---|---|---|
| `svc-ucr-west` | 72 (+1 single-quoted) | 17 files: audit_log 37 literal ids in total, booking, capacity, case, communication, credential, query_board, board_projector, routes_events, auth, report_capacity (as `ucr-west`, 12 uses in 2 files) and others |
| `dev-1` | 44 (+2) | credential, auth, report_capacity, communication |
| `svc-1` | 36 | routes_events, `contract/test_cache_contract.py`, infra smoke (`test_infra_up.py:173-180`) |
| `prac-1` | 26 (+4) | audit_log, credential, person, auth |
| `svc-ucr-east` | 20 | query_board, board_projector, registration |
| `case-1` | 15 | case |
| `comm-1` | 14 (+2) | communication, audit_log |
| `obs-west-1403` | 13 | query_board, board_projector |
| `bk-4821` / `bk-1` / `bk-4822` / `bk-4823` | 8 / 9 / 2 / 2 | booking, query_board, audit_log |
| `reg-ucr-east-1..6`, `-old`, `-new` | 8 + 3 + 3 + 2 + 2 + 2 | registration |
| case reference `4821`, `4822`, `4823`, `9999`, `9434765919` | | `test_case_repository.py:35,47,111,246,299,333`, `test_booking_repository.py:36,46,156,216`, `test_query_board.py:241,441,450` (constraint `case_reference_id`) |
| phone `07700900123` | 3 | `test_person_round2.py:68,86,90` (`phoneHash` lookup) |
| `p1`, `prac-advisor-1`, `prac-lead-1`, `dev-sms-1`, `dev-same`, `out-1..`, `out-api-1`, `rep-api-1`, `req-1`, `pat-1`, `smoke-1` | | outbox, api_support (:21-28), auth, infra |
| Mapper sample ids | | `ORG_ID`, `LOC_ID`, `SVC_ID` UUID literals in `unit/.../test_mapper.py:31-33` (pure; no collision risk) |

Totals: 166 `svc-*` literals in 26 files; 43 `prac-*` in 7; 62 `dev-*`/`device-*` in 6; 24 `bk-*` in 3; 17 `comm-*` in 2. All are valid after composite constraints land. Edit needed per fixed id: none, if the tenant is ambient; a test that asserts the same id in two tenants is the whole point of 6.2.

Factories and fixtures with fixed content: `tests/integration/application/test_report_capacity.py:59-90` (`REPORTER`, `ADVISOR`, `LEAD`, `UCR_WEST`), `test_credential_store.py:39-50` (`_seed_practitioners`), `test_booking_repository.py:30-50` (`BOOKING_4821`), `test_case_repository.py:28-50` (`OPEN_CASE`), `test_query_board.py` (`WEST`, `EAST`), `test_auth.py` (`req-1`, `pat-1`), and the `seed_service` fixture. There is no shared factory module today: each file defines its own sample graph. TEN-E13 should create one tenant-aware `seed_world(tenant)` for the isolation test and leave per-file samples alone.

### 4.4 SequentialIds

`SequentialIds` (`src/diucs/adapters/testing/fixed_ids.py`) yields `id-1`, `id-2`, ... and restarts from 1 for every instance. It is the default of `build_for_tests` (`container.py:91`) and is used directly at `test_report_capacity.py:93,561`, `unit/bootstrap/test_container.py:45`, and `unit/adapters/testing/test_fixed_ids.py` (5 tests). The ids it makes become node ids (report ids, outbox ids, audit ids), so two tenants, two tests, or two runs all create `id-1`. Within one tenant the per-test wipe prevents collisions; across tenants it needs composite constraints. Change: none to the class; add the cross-tenant test; the U02 note "one generator for the whole test: report ids never collide (L134)" (`test_confirm_capacity.py:551`) stays true.

### 4.5 FixedClock and fixed instants

`FixedClock` is a pure object per test and carries no tenant, so it is safe to share. The constants it is built from are shared by every tenant: `TEST_NOW` 2026-10-23 13:00Z (`container.py:18`), `R01_TEST_NOW` 13:12Z (`support/api.py:24`), `NOW` in `test_report_capacity.py:55` and `test_audit_log.py:35`, `START` in `contract/factories.py:44`, `TEST_TOKEN_EXPIRES_AT` 2026-10-24 (`adapters/testing/tokens.py`). Consequences: (1) two tenants write the same `recorded` timestamp, so ordering and latest-report tie-breaks are identical across tenants, which is good for isolation tests; (2) audit entries that are identical in content and time hash to identical values in two tenants unless the tenant is part of the hash input (see 4.1); (3) `TEST_BFF_SECRET` is one secret for every test token, so the token signature does not distinguish tenants, only the claim does. Edit: none, but add the identical-input test in 6.3.

### 4.6 Redis

Current state differs from the brief: no test flushes `diucs:*`. The contract factory uses `diucs-contract-<uuid>:` (`contract/factories.py:97`), the TTL test `diucs-ttl-check-<uuid>:` (`test_redis_ttl.py:26`), the integration tests `diucs-integration-<uuid>:` (`test_redis_cache.py:30`), and `flush_prefix` (`support/redis.py:6`) deletes only that prefix. Fixed key names: `test_redis_isolation.py:17` writes `diucs:cache:isolation-check:status` under the default prefix with a raw client, to prove a new harness does not delete another run's keys; `unit/.../test_redis_cache.py:94` asserts every key name starts with `diucs:`. Under tenancy (`diucs:<tenant>:`): `DEFAULT_KEY_PREFIX` and the key shape change (`redis_cache.py:16-22`); `test_redis_ttl.py:31` reads the physical key `f"{prefix}cache:svc-1:status"` and `test_redis_cache.py:34` builds `f"{prefix}chan:{BOARD_UPDATES_CHANNEL}"`, so both need the tenant segment; `test_redis_isolation.py` must be rewritten around tenants (a flush of tenant A's keys leaves tenant B's, in addition to the per-run prefix). The per-run prefix design already gives parallel safety, and stays.

Other Redis points: the live Redis is the compose one on 6379 (running here as a container with `docker-proxy`); the unit test `test_compose_redis_persistence.py` (2 tests) checks compose settings only. The fakes `InMemoryCache` and `ManualEventBus` are per-instance, so already tenant-safe; their unit tests (`test_memory_cache.py` 19, `test_memory_event_bus.py` 10) change only if the port methods gain a tenant.

### 4.7 Service Bus shared queues and fixed message ids (lessons L6, L101)

Emulator config is static (`infra/servicebus-config.json`): queues `inbound.replies` (duplicate detection, window `PT20S`), `inbound.receipts`, `scheduled.work`; topics `capacity.events`, `booking.events`, `registration.events`, `criteria.events`, `alerts.events`, `messages.outbound`; session subscriptions such as `capacity.events/board-projector`. One emulator, one set of queues, for every session on the machine. Tenancy cannot give each run its own queue.

- `contract/factories.py:187-193,228,240` `_drain` receives and completes every message in `scheduled.work`, `inbound.receipts` and the `capacity.events` session subscription at harness start and close, including other runs' messages. It is the single clearest parallel hazard in the suite. `test_factory_drain.py` (2 tests) pins this behaviour.
- `contract/test_event_bus_contract.py:24-35`: fixed ids `w-1`, `w-2`, `x-1`, session id `svc-1` on `capacity.events`; `QUEUE = "scheduled.work"`. No duplicate detection on that queue, so no id collision, but the received message can be another run's.
- `integration/adapters/outbound/bus_servicebus/test_service_bus.py`: unique ids per message (`_unique_id`, :19-20, lessons L6 and L101), and a fixed queue read that can pick up another run's message (`_receive_one`, :23-31; the asserts check ids so the test would wait or fail, not mis-pass). 7 tests, including a 33 s wait (:70).
- `integration/test_infra_up.py:161,165`: `message_id="smoke-1"` on `inbound.replies`. L101 says this was to be fixed with a unique id; it is not fixed on `main`. A second run within the 20 s window fails; two parallel runs fail each other. `test_infra_up.py:173-180` also reads session `svc-1` of `capacity.events`.
- Unmerged `I04 test_servicebus_runner.py`: the runner consumes `inbound.receipts` and hands every message it receives to this run's consumer (`:68`); the test comment says the queue can hold an older run's message. Under tenancy the consumer binds the tenant from the message's properties, so a message from run B read by run A's runner would be processed in B's tenant by A's process. Abandoning a foreign message to give it back raises its delivery count, and `MaxDeliveryCount` is 10 in the config, so a few cross-reads dead-letter another run's message.
- Under tenancy: add the tenant as a validated message property. The Service Bus message id used for duplicate detection on `inbound.replies` should include the tenant (`<tenant>:<id>`); otherwise the same provider message id for two tenants within 20 s drops the second. That is a design question for the Service Bus audit, flagged in section 9.
- Isolation these tests need: one Service Bus session at a time, machine-wide (lock), tagged `servicebus`; no parallel run can be made safe by tenancy alone. A second option is one emulator instance per run (SQL Server plus the emulator, several GB each), which is not worth it.

### 4.8 Other global or shared state

- REST tests: `support/api.py:26-40` builds one `Neo4jConnection` per test on the harness container; `api_app.state.secrets`, `state.cache` are set per test (`test_auth.py:42`, `test_concurrency.py:47`). `test_routes_events.py` (11 tests) and `routes_events.py` subscribe to the single channel `BOARD_UPDATES_CHANNEL`; under tenancy the channel is per tenant and the SSE route must subscribe to the caller's; tests assert it.
- `issue_test_token(role, services, sub, ...)` (`adapters/testing/tokens.py`) has no tenant. 24 call sites: `test_auth.py` 19, `test_routes_events.py` 3, `test_concurrency.py` 2 (plus `unit/domain/rules/test_bff_token.py` 14 and `unit/adapters/inbound/fhir_rest/test_auth.py` 3 with `BffClaims`). Add a `tenant` claim defaulting to the run tenant, so existing calls need no edit.
- `scoped_key(sub, key)` (`concurrency.py:105`) names idempotency replay keys `idem:<sub>:<key>`; with tenancy it needs the tenant (DEC-130 item 7). `integration/.../test_concurrency.py:98,102` and `unit/.../test_concurrency.py:121` (`test_the_scoped_key_follows_the_cache_name_rule`) change.
- `support/things.py`: `TestThing` writes via raw `tx.run` inside the unit of work, with no tenant; 4 statements (:19,:29,:38,:48,:52) need the tenant or a tenant-stamping helper.
- Module-level registries and observers: `driver._observer` (`set_query_observer`, `unit/.../test_driver.py:47-50`, reset around each test), `REGISTRY` (3.5), `os.environ` writes (`apply_session_env`, `monkeypatch.setenv` in `test_connection_recovery.py:343-381`, `unit/bootstrap/test_settings.py`). Per process, so safe under xdist workers; unsafe only if tests are ever run on threads in one process.
- `test_smoke.py:34-60` copies `tests/conftest.py` text into a `pytester` project. Any new import in the conftest must resolve inside that sandbox, or the two integration-hook tests there fail.
- `test_ci_workflow.py` (13 tests) parses `ci.yml`. Any CI change (a service, `-n`, a lock step) must update it; `test_backend_job_does_not_use_compose_for_tests` forbids `docker compose` in the backend job.

---

## 5. TESTS THAT MUST STILL RUN ALONE

Isolation levels used below: **own container** (a container no other session shares), **serial** (never concurrent with any other session on the machine, enforced by the lock), **exclusive phase** (runs in a second pytest invocation after the parallel phase), **marker** (selected by pytest marker).

| File | Tests | Why | Isolation |
|---|---|---|---|
| `integration/graph_store/test_driver.py` | 8 (tests 1 to 5 schema: migrations, bookkeeping delete, drop index, run twice; 6 to 8 are `run_query` checks) | Deletes `:Migration` nodes (:43-45), drops an index (:109), asserts the exact constraint and index set and migration count (:22-29). A shared instance would lose its schema bookkeeping mid-run for every other session. | Tests 1 to 5: own container + marker `schema`. Tests 6 to 8: parallel-safe once the private registry is used (3.5). Split the file. |
| `integration/support/test_neo4j_harness.py` | 12 | Tests at :144, :152, :175 start their own containers (lifecycle, removal on error, `NEO4J_URI` override); :134 asserts the `Migration` count after `wipe`. | Lifecycle tests: marker `lifecycle`, exclusive phase (they launch containers, which is heavy). `Migration` and `wipe_all` tests: owned mode only. The `write_tx`, `count_nodes`, `node_props`, round-trip tests become parallel-safe and must be rewritten around tenant scoping. |
| `integration/support/test_harness_restart.py` | 2 | `docker stop` / `docker start` and container id checks on a private container. | Own container (already). Marker `lifecycle`, exclusive phase. |
| `integration/graph_store/test_connection_recovery.py` | 12 | `test_in_flight_write_fails_retryably_and_the_service_recovers` (:191) and `test_health_reports_degraded_within_the_timeout_while_stopped_and_never_raises` (:246) stop the session container (`stop_container(harness_container)`, :207, :250). On a shared instance that kills every other run. The other 10 tests only use probes and monkeypatched env. | The 2 stop tests need an own container (new fixture `own_neo4j`, because the F11 assumption "no test needs a container of its own" no longer holds, `test_connection_recovery.py:5-6`). Marker `lifecycle`, exclusive phase. Split the file: lifecycle module (parallel-safe, 10 tests) and recovery module (2). |
| `integration/test_infra_up.py` | 7 | Targets the compose stack on 7687, 6379, 5672. `test_every_compose_service_reports_healthy` asserts the whole stack. Fixed `InfraProbe`, `smoke-1`, session `svc-1`. | Serial, marker `infra`. Not harness-based; keep out of tenancy. Fix the L101 id. |
| `integration/adapters/outbound/bus_servicebus/test_service_bus.py` | 7 | Shared emulator, fixed queues, 20 s duplicate window. | Serial, marker `servicebus`. |
| `contract/test_event_bus_contract.py` (servicebus param) | 11 cases | Drain removes other runs' messages (`factories.py:187-193`). | Serial, marker `servicebus`; the memory param stays in the parallel phase (parametrised, so select by `-k servicebus` or add the marker on the param, as `integration` is today, `factories.py:261`). |
| `contract/test_session_window.py`, `test_characterisation.py`, `test_factory_drain.py` | 5 + 2 + 2 | Pure, with fakes. | Parallel-safe. |
| `contract/test_redis_isolation.py`, `test_redis_ttl.py`, `integration/.../test_redis_cache.py`, contract cache (redis param, 24 cases) | 2 + 1 + 6 + 24 | Shared Redis, per-run prefixes. Timing tests (TTL, sleeps) are sensitive to load. | Parallel-safe by prefix. Marker `redis` so CI without Redis can deselect. |
| `integration/graph_store/test_idempotency_store.py`, `test_flag_repository.py`, `test_person_repository.py`, `test_case_repository.py`, `test_credential_store.py`, `test_scope_list_repository.py`, `test_criteria_repository.py` (racing tests, 16 tasks on one key, `asyncio.gather`) | about 12 tests | CPU-timing sensitive; they assert exactly one winner, which is a property of the lock, not of the machine. | Parallel-safe under tenancy; each racing test needs its own tenant-scoped keys only. Watch for a transient deadlock error once Concepts are shared. |
| `unit/test_smoke.py` | 4 | Nested pytest sessions through `pytester`, copies the conftest, one test sets `DOCKER_HOST` to a dead port. | Parallel-safe; runs the reaper in each nested session, so the reaper must stay a no-op without Docker. |
| `architecture/test_import_rules.py` | 13 | Runs import-linter over the tree, CPU-heavy. | Parallel-safe. |

Count of tests that stay alone: about 38 (schema 5, harness lifecycle 5, restart 2, recovery 2, infra 7, Service Bus 7 + 11 = 18 in the serial group), out of 491 integration + 48 contract.

---

## 6. THE NEW TESTS TENANCY NEEDS

### 6.1 (a) Generated two-tenant isolation test over the registry

Design (`tests/integration/test_tenant_isolation_generated.py`, `tests/support/query_probes.py`):
1. Seed tenants A and B with the same full sample graph (`seed_world`, one function; the same ids in both, with a distinguishing marker value per tenant such as `name`). Identical ids are the strength of the test: a query that forgets `tenantId: $tenant` matches B's node by id.
2. For each `query_id` in `REGISTRY.ids()`, look up its entry in a probe table: `params(world) -> dict`, mode, expected-effect class (`read-own`, `write-own`, `ensure`). The table has one entry per query (about 123). A **completeness test** fails when a registered id has neither a probe nor an exemption with a reason, so a new query cannot be added silently (this is what makes the test "generated").
3. Open a transaction as tenant A, run the query through `run_query` (which injects `tenant=A`), and inspect: for reads, every returned row, flattened, contains no B marker; for writes, within the same transaction, re-read B's whole subgraph (`MATCH (n {tenantId:$b}) RETURN labels, properties` plus relationships) and compare to the snapshot taken before; then roll the transaction back, so no cleanup is needed and the 123 cases are cheap.
4. Global invariant after the sweep: no relationship joins nodes with two different non-null `tenantId`s (allow edges to shared Concept nodes if 3.1 keeps them).
5. A second parametrisation runs each write query with B's ids only, as tenant A (the "foreign id" case): the write must report not-found or no-op and create nothing in A that references B.
6. Honest limit: the registry yields ids and the `$param` names (parse `\$[a-zA-Z_]+` from the Cypher). It cannot yield valid values, so the probe table is hand-written; this is about 1 hour per 5 queries. Auto-generation of probes is not realistic for queries such as the 17 template-built `resource_store` statements and the audit chain queries that depend on head state.
7. Mode: parallel-safe (owned or attached), because all work is inside rolled-back transactions on tenants A and B of this run.

Size: about 123 parametrised cases for reads and writes (call it 250 collected items with the foreign-id variant), plus 4 supporting tests (completeness, invariant, exemption list is minimal, probe table has no unknown id).

### 6.2 (b) Every registered query mentions `$tenant`, with allowlist

`tests/unit/adapters/outbound/graph_store/test_tenant_predicate.py` (no database):
- every id in `REGISTRY` mentions `$tenant`, except an explicit `TENANT_FREE` set;
- `TENANT_FREE` entries are individually justified in the test, each still registered (no stale allowlist entries), and the set is exactly: migrations (not in the registry), `PING_QUERY_ID` (`health.py:14`), and the pre-tenant lookups from 3.1 item 2 (link token by hash, phone and number resolution, pairing code, BFF session) once they exist;
- lint: every node pattern with a label in every statement carries `tenantId: $tenant` (regex over `(var:Label {` ... `})` and `MERGE`/`CREATE`/`MATCH` patterns), apart from shared-label exceptions (`Concept`, if shared);
- no statement text contains an f-string splice of caller data (the two f-string sites, `scheduled_work_repository.py:30` and `capacity_repository.py:58`, splice constants only; the test asserts the registered text has no `{`, `}` left over);
- no query accepts a `tenant` argument from callers: `run_query(tx, id, tenant="x")` raises (DEC-130 item 2);
- register a query without `$tenant` and not on the allowlist: `NamedQuery` registration is rejected (item 3);
- architecture test: `tx.run(` / `session.run(` appear only in `driver.py`, `migrations.py` and `health.py` under `src/diucs` (today only `driver.py` and `migrations.py` contain `tx.run`; checked by grep). Add to `architecture/test_import_rules.py`.
Estimate: 8 to 10 tests.

### 6.3 (c) Per-layer cross-tenant tests

Each is "same ids in A and B, act as A, B is untouched and A sees only A".

| Layer | Tests | Count |
|---|---|---|
| Repositories and stores (21 classes: services, capacity, bookings, cases, people, criteria, registrations, scope lists, flags, communications, link tokens, scheduled work, contacts, credentials/pins/devices, idempotency, processed, resource store, audit, outbox, ...) | per class: read-own-only, write-leaves-other-unchanged, same key in both tenants coexist | 21 x 3 = 63 |
| Use cases (ReportCapacity, QueryBoard, BoardProjector; ConfirmCapacity and SendPrompts on unmerged branches) | a service id of tenant B read as tenant A raises `NotFound` (not `NotAllowed`, which would reveal existence, DEC-086 item 5); a report in A does not change B's board; outbox and audit entries land in A's chain | 5 x 4 = 20 |
| REST routes (`/fhir/*`, SSE, capability) | bearer token for A cannot read B's id (404 body byte-identical to a missing record, as `test_auth.py:200` already requires for roles); token with no tenant claim is a 401 login error; a `tenant` in the body, query string or header is ignored; two clients with two tokens run the same request and get different data; SSE of A does not receive B's board events; `ETag` and `If-Match` versions are per tenant | 12 |
| SMS inbound resolution (I06 and later) | the same reference `4821` in two tenants resolves by the sender's tenant; an unknown sender resolves to no tenant and is dropped without a write; the same phone in two tenants (open question, section 9) | 6 |
| Service Bus consumer (I04) | tenant property required, missing means permanent error and dead-letter; consumer binds the tenant from the property and resets it; `Processed` marker for the same message id in two tenants does not collide; a message for another tenant is not processed by this run | 8 |
| Redis keys | key contains tenant segment; fence counter and lock per tenant; pub/sub channel per tenant; a tenant-wide flush leaves the other; TTL unaffected | 6 |
| Audit chain per tenant | independent heads and `seq` from 1 in both; identical entries produce identical or different hashes as decided; tamper in A leaves B's `verify_chain()` true; concurrent appends in A and B both succeed and neither waits on the other's head | 8 |
| Outbox | `pending()` returns only A's; marking B's id as A is `NotFound`; same message id in two tenants coexists; a failure count for A does not change B | 5 |
| Idempotency | same key in two tenants does not collide (`IdempotencyRecord` and `Processed`, plus the REST `Idempotency-Key` replay via `scoped_key`) | 6 |
| Link tokens | a token hash from A is not resolved as B; the pre-tenant lookup returns the issuing tenant only; used and burn keys per tenant; no raw token in any node of either tenant | 5 |
| Pairing codes | the same six digits in two tenants pair the right device (built with U10 and R15) | 5 |
| BFF session (frontend, W02) | session carries the tenant from the verified sign-in, not a cookie the caller sets; two sessions get two tokens; CSRF per session | 6 |
| Harness itself | `wipe_tenant` leaves the other tenant; `run_query` with no bound tenant is refused; the bound tenant survives a request; two sessions in one run get different tenants; xdist workers get different tenants; the attached-mode refusal for schema tests | about 12 |

### 6.4 (d) Fixtures for two tenants

- `tenant_id` (session), `other_tenant_id` (session), autouse `bound_tenant` (function, binds `tenant_id`), `as_tenant(tenant)` context manager for use inside a test, `in_tenant` decorator for helper functions.
- `seed_world(tenant)` (3.1 of section 6.1) and `seed_service_for(tenant, ...)`; the existing `seed_service` (`integration/application/conftest.py:21`) becomes a wrapper for the current tenant.
- `tenant_clients`: two `AsyncClient`s on one `api_app` with two tokens, and `token_for(tenant, role, services, sub)`.
- `two_tenant_world`: both tenants seeded, with a teardown that removes both (`other_tenant_id` is not covered by `clean_graph`).
- `own_neo4j` (function or module scope): a private container for lifecycle and recovery tests.

### 6.5 Estimate of new tests

| Group | Test functions | Collected cases |
|---|---|---|
| Generated isolation test (a) | 6 | about 250 |
| Registry and architecture tests (b) | 10 | 10 |
| Per-layer (c) as tabulated, excluding harness | 63 + 20 + 12 + 6 + 8 + 6 + 8 + 5 + 6 + 5 + 5 + 6 = 150 | 150 |
| Harness and fixtures | 12 harness + 8 reaper/lock/modes (rewrite of 5 existing) | about 20 |
| **Total** | **about 190** | **about 430** |

Of these, about 35 depend on tasks not yet built (SMS inbound, pairing, Service Bus consumer, BFF session); those are written with their tasks, and this audit only counts them.

---

## 7. PARALLEL EXECUTION

### 7.1 Contention points on one shared Neo4j

1. Schema: `apply_migrations` is not safe to run concurrently (DDL races, `:Migration` MERGE), and a destructive schema test (section 5) breaks every other session. Fix: a cross-process migration lock, and run schema tests in owned mode only.
2. Global constraints: until the composite migration lands, every fixed id collides across runs (4.3). This is a hard precondition, not an optimisation.
3. Concept nodes: shared MERGE targets cause lock waits and possible deadlocks between runs (3.1 item 1).
4. Heavy scans: tenant-scoped wipe and `MATCH (n {tenantId: $t})` do an all-nodes scan unless an index applies, so cost grows with total data on the instance (TEN-E06 measures this).
5. Memory and page cache: one JVM now serves all runs; without `NEO4J_server_memory_*` limits it can still grow to the host.
6. Redis: already safe per prefix. Remaining risk is timing tests under load.
7. Service Bus: shared queues, drain, 20 s duplicate window, session `svc-1`: cannot be made parallel (4.7). Serial lock.
8. The compose stack: `test_infra_up.py` and any `diucs-local` use. Serial.
9. A dead run leaves tenants behind on a shared instance. Needs the orphan-tenant sweeper (TEN-E11).
10. Frontend e2e: `playwright.config.ts` fixes port 3000 with `reuseExistingServer: !process.env.CI`, so two e2e sessions on one machine race for the port and the second one reuses the first's dev server. Not a tenancy matter, but it blocks running two full suites at once. Use a per-run port.

### 7.2 Is pytest-xdist viable

Yes, with conditions. Not installed today (`pyproject.toml` dev group and `uv.lock` have no `xdist`; one `uv add --dev pytest-xdist` and a lock update). Facts that make it workable:
- pytest-asyncio 1.4.0 with `asyncio_default_fixture_loop_scope = session` and `asyncio_default_test_loop_scope = session` (`pyproject.toml`): each xdist worker is a separate process with its own session loop and its own session fixtures, so each worker gets its own driver and (owned mode) its own container, or (attached mode) its own tenant on the shared instance. No loop sharing across workers.
- Module-level state (`_active`, `os.environ`, `REGISTRY`, `_observer`) is per process.
- Constraints: `pytest_sessionstart` and the reaper run in the controller and every worker (harmless). `--dist loadfile` keeps a file's tests on one worker (several files assume order within a file, such as the Probe-gone test at `test_neo4j_harness.py:49-56`; that pair is order-dependent today, so it needs `loadfile` or a rewrite). The `exclusive`/`lifecycle`/`schema`/`servicebus`/`infra` groups run in a second invocation, not under `-n` (or with `xdist_group` and `--dist loadgroup` as a fallback; the second invocation is simpler and safer).
- Without Neo4j sharing, xdist alone gives N containers on one machine, which is the situation that exhausted Docker memory before. So xdist is only worthwhile with the shared instance plus memory limits.
- Within one worker, tests still run serially and share that worker's tenant; per-test isolation is still `clean_graph`.

### 7.3 Order in which isolation can be introduced

1. Interim protection now (section 8): lock, limits, owner reaper. No dependency on tenancy.
2. Tenancy seam (src): context variable, `run_query` binding, `$tenant` registration rule (DEC-130 item 10, step 1). Test side: `tenancy.py`, bound-tenant fixture, scoped `clean_graph`, contextual helpers (TEN-E06 to TEN-E08), run in owned mode. This is already useful: it catches missing predicates with one container per run.
3. Composite constraints migration (src). Test side: TEN-E10, and the fixed-id tests run unchanged.
4. Existing tests edited (TEN-E14, E15), isolation test and per-layer tests (E19 to E27).
5. Attached mode and the shared instance (TEN-E09, E11), with lifecycle and schema tests moved to owned containers.
6. xdist (TEN-E28), then CI (E29).
Redis and Service Bus (E16, E17) follow their src tasks. Do not run two sessions against one Neo4j before step 3.

---

## 8. THE INTERIM PLAN WHILE TENANCY IS BUILT

Goal: stop the stalls and leaks with the fewest changes, all in the harness, none depending on tenancy.

Recommended sequence (cheapest first):

1. **One-at-a-time rule, enforced, machine-wide (about 4 h, TEN-E01).** All worktrees (`/home/user/overwatch-wt/I04`, `U02`, `U03`, `W02`, and `main`) share one Docker daemon, so a lock is only effective if it is machine-wide. `flock` on a file in `/tmp` held for the whole integration pytest session: a `make test-integration` target in `backend/Makefile` doing `flock -w 3600 /tmp/diucs-test.lock uv run pytest ...`, plus a conftest `pytest_sessionstart` that takes the same lock (Python `fcntl.flock`) when the session will start Docker, so a bare `uv run pytest` is also covered. Unit-only runs do not lock (they never reach Docker, and the reaper is a no-op). Today's rule is only prose (DEC-008 and DEC-130 item 9: "agents run Neo4j tests one at a time") and the builder brief claims "parallel sessions do not collide" (`assets/builder-brief.md:18`, `assets/verifier-brief.md:13`, `references/collective.md:62`); those three lines need correcting in TEN-E31. The queue wait is the price: with 4 builders it means serial integration runs, which is what actually happens now.
2. **Memory limits (about 3 h, TEN-E02).** Add to the `docker run` in `start_throwaway_neo4j` (`neo4j.py:84-98`): `--memory 1g`, and environment `NEO4J_server_memory_heap_initial__size=256m`, `NEO4J_server_memory_heap_max__size=512m`, `NEO4J_server_memory_pagecache_size=256m` (Neo4j 5 setting names with a double underscore for an underscore in the setting name). Values are `[ASSUMED]`: the test graph is a few thousand nodes. The first run should print `docker stats` to confirm. Make them overridable by environment variables for a heavier test. Add a unit test on the argument list (the runner is already injectable in the reaper tests).
3. **Owner-based cleanup instead of age (about 8 h, TEN-E03).** Label each container with `diucs-test-owner=<pid>`, `diucs-test-owner-start=<process start time from /proc/<pid>/stat>`, and `diucs-test-host`. The reaper removes a container whose owner process is dead (pid absent or start time differs) at any age, never removes one whose owner is alive, and keeps an age cutoff only as a fallback for unlabelled legacy containers (raise it to 6 hours, DEC-108's 90 minutes goes wrong for long runs and for restarted containers). Also register `atexit` and SIGTERM handlers in the conftest so a plain kill removes its own container. SIGKILL remains covered by the next session's reaper. This replaces `REAPER_MAX_AGE`; it amends DEC-108, so it needs a new DEC. The five tests in `unit/support/test_reaper.py` and the three in `test_container_removal.py` are rewritten (inject a fake `pid_alive`).
4. **Cheaper readiness probe and honest timeouts (about 5 h, TEN-E04).** Replace `docker exec cypher-shell` with a Bolt connect retry loop using the driver (`verify_connectivity` with backoff) or a TCP probe on the published port followed by one `RETURN 1`. Keep the 120 s deadline but make it an environment-tunable value, report "image not present, pulling" separately from "Docker unavailable" (run `docker image inspect` first and pull with a long timeout), pick the port with `docker run -p 127.0.0.1::7687` and read it back (`docker port`) to remove the port race. Add `pytest-timeout` (or a session watchdog) so a stall fails in minutes, not 9 (L67).
5. **Container reuse (about 8 h, TEN-E05, optional).** Because the lock makes sessions serial, one long-lived container `diucs-test-neo4j-shared` (label `diucs-test=true`, owner field set to the lock holder) can serve them in turn: the session under the lock reuses it or creates it, resets it fully (`wipe_all`, drop all constraints and indexes, delete `:Migration`) and runs migrations. This removes 30 to 120 s of start-up per session. Cautions: (a) the 5 container-lifecycle tests still need their own containers; (b) `docker stop`/`start` tests (`test_connection_recovery.py:207,250`) must restore the container in `finally` (they do); (c) do not use `--tmpfs /data` to avoid the volume leak, because `docker stop` then `docker start` empties a tmpfs and `test_harness_restart.py:35-60` asserts data survives a restart; (d) a stale shared container must be recreated when the image tag changes. This step is the natural base for the later attached mode.

Not recommended now: running more containers in parallel, raising the 90-minute age, or relying on `docker volume prune` (it is safe, DEC-128, but only treats the symptom).

Total interim effort: 20 h without reuse, 28 h with it.

---

## 9. RISKS AND OPEN QUESTIONS (ranked)

1. **Shared instance before composite constraints (blocking).** If the harness is switched to attach mode before the composite-constraint migration lands, every test with a fixed id fails across runs (`svc-ucr-west` 72 uses, `dev-1` 44, case references). Ruling needed: composite migration is a hard prerequisite for any shared instance (section 7.3).
2. **Service Bus cannot be isolated by tenancy.** Fixed queues, a drain that removes other runs' messages, the 20 s duplicate window, and consumers that bind the tenant from the message. Owner decision: serial lock only (cheap) or a second emulator per run (expensive). Also: should the duplicate-detection message id be tenant-qualified?
3. **Concepts: shared or per tenant (DEC-130 items 1 and 5 disagree).** Drives wipe semantics, four Concept-count assertions, lock contention between runs, and the isolation test's invariant. Recommendation: per tenant first.
4. **The single assumption behind the design: ambient tenant through a context variable.** Verified from source (pytest-asyncio 1.4.0 copies context from fixtures and tests copy from the loop), but not run. Failure modes: a request handler that does not reset the variable, tasks created before binding, background tasks that outlive the test. Spike TEN-E06 before anything else.
5. **The isolation test is only as strong as its probe table.** About 123 queries, not 78, and values cannot be generated. A missing or weak probe is a silent hole. Mitigation: the completeness test, identical ids in both tenants, snapshot comparison of B, and a mutation check (remove `$tenant` from one query in a scratch branch and confirm the test fails).
6. **Pre-tenant lookups.** Link token by hash, SMS inbound by phone or number, pairing code, BFF login: none can bind a tenant first. They are the allowlist, and they are the highest-risk queries. Open question: can the same phone number belong to a person in two tenants? Test data uses one phone throughout (`07700900123`).
7. **Interim stalls continue regardless of tenancy.** Probe cost, no memory limits, a 60 s `docker run` timeout that includes image pull, an age-only reaper, no test timeout (section 2.3). Steps 1 to 4 of section 8 should not wait for tenancy.
8. **CI cannot run the infrastructure tests today.** `ci.yml` job `backend` runs plain `uv run pytest` with no Redis, no Service Bus emulator and no compose (and `test_ci_workflow.py:test_backend_job_does_not_use_compose_for_tests` forbids it), but the suite includes `test_infra_up.py` (7), the Redis tests (33 cases) and the emulator tests (18). I did not see CI results and cannot confirm its state; by static reading the backend job must fail on those or has been red. Decision needed: add services to the job, or add `redis`, `servicebus`, `infra` markers and deselect on CI (the test `test_backend_job_runs_full_suite_without_deselecting_integration` forbids `-m`, `--deselect` and `--ignore` too, so that test changes with the decision).
9. **Scoped wipe cost on a shared instance** (all-nodes scan per test). Measure first; fallback is per-label deletion on a composite index.
10. **Test-only code in production registries** (`test_driver.py:32-39`, `things.py`) will trip the new registration rule and the generated test. Fix with a private registry (section 3.5).
11. **Orphan tenants** of killed runs accumulate on a shared instance. Needs the sweeper (owner pid in the tenant id).
12. **DEC-013 item 3 and DEC-108 are owner-confirmed rules that the plan changes.** Attach mode (a new opt-in variable) and owner-based reaping each need a new DEC; the harness today refuses a shell `NEO4J_URI` by design.
13. **xdist ordering assumptions.** At least one pair is order-dependent today (`test_neo4j_harness.py:49-56`, the "previous test's probe is gone" test). Use `--dist loadfile` and fix the pair.
14. **Unmerged branches.** I04, U02, U03, W02 (11 test files, 163 tests) were written on the single-tenant model and are migrated by the sweep (DEC-130 item 10). Merging them first adds about 12 hours of edits to this plan; merging them after adds the same edits at merge time.
15. **Lesson numbers.** Lessons L67, L84, L101, L126, L127 live on `origin/ledger-refresh`; `main`'s `LESSONS.md` stops at L63. The tasks below cite them from that branch.

Could not read or verify: GitHub Actions run history (no access), the live `REGISTRY` size (modules not imported by design), collected-item counts (pytest not run), actual container start and probe timings (Docker not used), current Neo4j memory behaviour (no `docker stats`), and the web canvas. The four unmerged branches were read from their worktrees, not built.

---

## 10. PROPOSED TASK BREAKDOWN

Hours are builder hours including the red/green commit pair and evidence; verification is extra. "Seam" = the production tenant seam (context variable, `run_query` binding, `$tenant` registration rule); "Comp" = the composite-constraint migration; both are outside this audit.

| ID | Title | Files | Hours | Depends on |
|---|---|---|---|---|
| TEN-E01 | Machine-wide test lock and `make test-integration` | `tests/support/lock.py` (new), `tests/conftest.py`, `backend/Makefile`, `unit/support/test_lock.py` (new) | 4 | none |
| TEN-E02 | Neo4j memory and CPU limits on the harness container | `tests/support/neo4j.py:84-98`, `unit/support/test_container_args.py` (new) | 3 | none |
| TEN-E03 | Owner-labelled containers, owner-liveness reaper, atexit and SIGTERM cleanup (amends DEC-108) | `tests/support/neo4j.py:256-336`, `tests/conftest.py:35`, `unit/support/test_reaper.py`, `test_container_removal.py` | 8 | none |
| TEN-E04 | Cheaper readiness probe, image-pull-aware start, port race, pytest-timeout | `tests/support/neo4j.py:46-146`, `pyproject.toml`, `uv.lock`, `unit/support/test_connect_or_fail.py` | 5 | none |
| TEN-E05 | Reuse one container across serial sessions under the lock (optional) | `tests/support/neo4j.py`, `tests/conftest.py` | 8 | E01, E03 |
| TEN-E06 | Spike: context propagation, scoped-delete cost, xdist plus session loop | scratch only; note in `docs/delivery/` | 4 | none |
| TEN-E07 | `tests/support/tenancy.py`: run tenant id, `bind_tenant`, bound-tenant fixture and guard | `tests/support/tenancy.py` (new), `tests/conftest.py:40-49` | 6 | Seam, E06 |
| TEN-E08 | Scoped `wipe_tenant`, `wipe_all`, `clean_graph`, contextual `count_nodes`, `node_props`, `tx_run`, tenant re-provision | `tests/support/neo4j.py:208-253`, `tests/conftest.py:93-98`, `integration/support/test_neo4j_harness.py` | 10 | E07 |
| TEN-E09 | Owned versus attached mode, `DIUCS_TEST_NEO4J_URI`, markers `schema`/`lifecycle`/`exclusive`, `own_neo4j` fixture, split `test_connection_recovery.py` (new DEC superseding DEC-013 item 3) | `tests/support/neo4j.py`, `tests/conftest.py`, `pyproject.toml` markers, `integration/graph_store/test_connection_recovery.py`, `integration/support/test_harness_restart.py` | 10 | E08 |
| TEN-E10 | Migrations in attached mode: cross-process lock; rewrite schema tests for composite constraints | `tests/conftest.py:52-68`, `integration/graph_store/test_driver.py`, `unit/.../test_migration_ids.py` | 8 | Comp, E09 |
| TEN-E11 | Orphan-tenant sweeper (dead-owner tenants) | `tests/support/tenancy.py`, `tests/conftest.py` | 5 | E07, E09 |
| TEN-E12 | Token and API fixtures: tenant claim in `issue_test_token`, bound `test_container` and `api_client`, `tenant_clients` | `src/.../adapters/testing/tokens.py` (src), `tests/support/api.py`, `integration/adapters/inbound/fhir_rest/{test_auth,test_routes_events,test_concurrency}.py`, `tests/support/things.py` | 7 | Seam, token claim (src) |
| TEN-E13 | Seed layer: tenant-aware `seed_service`, `seed_world(tenant)`, one `audit_head` in `clean_graph`, remove three duplicates | `integration/application/conftest.py`, `test_audit_log.py:62`, `test_unit_of_work.py:37`, `tests/support/seed.py` (new) | 10 | E08 |
| TEN-E14 | Edit graph_store integration tests: scoped raw Cypher, global dumps, tenant on raw CREATE (17 files) | `integration/graph_store/test_{booking,case,communication,contact_store,credential_store,criteria,flag,idempotency_store,link_token,person,person_round2,registration,resource_store,scheduled_work,scope_list}_repository.py` (names as in the tree) | 24 | E08, Comp |
| TEN-E15 | Edit application, audit and outbox integration tests (global counts, per-tenant chain) | `integration/application/test_{report_capacity,query_board,link_token_service}.py`, `integration/audit_neo4j/test_audit_log.py`, `integration/adapters/inbound/fhir_rest/test_api_support.py` | 14 | E08, E13 |
| TEN-E16 | Redis: tenant segment in keys, contract factory and tests | `contract/factories.py:92-117`, `contract/test_redis_isolation.py`, `contract/test_redis_ttl.py`, `integration/adapters/outbound/cache_redis/test_redis_cache.py`, `unit/.../cache_redis/test_redis_cache.py` | 8 | Redis tenant keys (src) |
| TEN-E17 | Service Bus: serial marker, tenant property, tenant-qualified ids, fix `smoke-1` (L101), drain scope | `tests/support/servicebus.py`, `contract/factories.py:187-246`, `contract/test_event_bus_contract.py`, `integration/.../bus_servicebus/test_service_bus.py`, `integration/test_infra_up.py:161,165` | 10 | Service Bus tenant property (src) |
| TEN-E18 | Unit-test edits, firm list (17 files) | `unit/adapters/outbound/graph_store/{test_driver,test_queries,test_migration_ids}.py`, `unit/domain/rules/test_bff_token.py`, `unit/adapters/inbound/fhir_rest/{test_auth,test_concurrency}.py`, `unit/adapters/outbound/{cache_redis/test_redis_cache,bus_servicebus/test_service_bus}.py`, `unit/bootstrap/test_container.py`, `unit/application/ports/outbound/test_audit.py`, `unit/application/test_idempotency.py`, `unit/adapters/testing/{test_memory_cache,test_memory_event_bus}.py`, `unit/support/{test_reaper,test_container_removal}.py`, `unit/test_ci_workflow.py`, `unit/test_smoke.py` | 14 | Seam |
| TEN-E19 | Registry rule tests, tenant-predicate lint, architecture rule on `tx.run`, test-source Cypher lint | `unit/adapters/outbound/graph_store/test_tenant_predicate.py` (new), `architecture/test_import_rules.py`, `tests/architecture/test_test_cypher.py` (new) | 10 | Seam |
| TEN-E20 | Generated two-tenant isolation test: probe table for about 123 queries, rollback runner, snapshot, invariant, completeness | `tests/support/query_probes.py` (new), `integration/test_tenant_isolation_generated.py` (new) | 28 | E13, Seam, Comp |
| TEN-E21 | Repository cross-tenant tests (21 classes, 3 each) | `integration/graph_store/test_tenancy_repositories.py` (new, or per class) | 20 | E13, Comp |
| TEN-E22 | Use-case cross-tenant tests | `integration/application/test_tenancy_use_cases.py` (new) | 8 | E13 |
| TEN-E23 | Audit chain, outbox, idempotency cross-tenant tests | `integration/audit_neo4j/test_tenancy_audit.py` (new), `test_tenancy_outbox.py`, `integration/graph_store/test_tenancy_idempotency.py` | 10 | E13, Comp |
| TEN-E24 | Link token, pairing code, SMS inbound resolution tests (with U10, R15, I06) | `integration/application/test_tenancy_link_tokens.py` (new), later tasks' files | 10 | E13, those tasks |
| TEN-E25 | REST and SSE cross-tenant tests | `integration/adapters/inbound/fhir_rest/test_tenancy_routes.py` (new) | 8 | E12 |
| TEN-E26 | Service Bus consumer and Redis cross-tenant tests | `integration/adapters/inbound/workers/` (I04), `integration/adapters/outbound/cache_redis/test_tenancy_keys.py` (new) | 8 | E16, E17, I04 |
| TEN-E27 | Frontend: tenant in BFF session tests, e2e port per run | `frontend/lib/auth/session.test.ts` (W02), `frontend/test/cookies.ts`, `frontend/playwright.config.ts` | 6 | W02 merged |
| TEN-E28 | xdist: dependency, worker tenants through `workerinput`, two-phase `make test-parallel`, `--dist loadfile`, fix order-dependent pair | `pyproject.toml`, `uv.lock`, `tests/conftest.py`, `tests/support/tenancy.py`, `backend/Makefile`, `integration/support/test_neo4j_harness.py:49-56` | 10 | E07 to E11 |
| TEN-E29 | CI: Redis and Service Bus services or marker split, shared Neo4j service, update `test_ci_workflow.py` | `.github/workflows/ci.yml`, `unit/test_ci_workflow.py`, `pyproject.toml` | 6 | E09, E28 |
| TEN-E30 | Migrate unmerged branch tests to tenancy (I04 3 files, U02 2, U03 1, W02 4 plus helper) | the branch files listed in 1.1 | 12 | merges |
| TEN-E31 | Lessons, DECs, correct the builder, verifier and collective briefs | `docs/delivery/decisions.md`, `LESSONS.md`, `.claude/skills/diucs-delivery/assets/{builder,verifier}-brief.md`, `references/collective.md:62` | 3 | E01 to E04 |

Subtotals: interim (E01 to E04) 20 h, with E05 28 h; harness (E06 to E11) 43 h; fixtures and edits (E12 to E18) 87 h; new tests (E19 to E27) 108 h; infrastructure (E28 to E31) 31 h. **Total about 297 hours** (31 tasks) for tenant isolation, plus verification. Section 11 adds TEN-E32 to TEN-E38 (68 hours), giving about 365 hours for 38 tasks.

### 10.1 Existing test files that will need edits

Firm (cannot be avoided by helper changes alone), with the ambient-tenant design of 3.2 and contextual helpers of 3.3:

- Backend integration: 28 of 38 files: graph_store 17 (booking, case, communication, connection_recovery, contact_store, credential_store, criteria, driver, flag, idempotency_store, link_token_repository, person_repository, person_round2, registration, resource_store, scheduled_work, scope_list), application 3 (report_capacity, query_board, link_token_service), audit_neo4j 1 (audit_log), fhir_rest 2 (api_support, concurrency), cache_redis 1, bus_servicebus 1, support 2 (test_neo4j_harness, test_harness_restart), infra 1.
- Helper-only (no file edit, the helper change covers them): 10: test_capacity_repository, test_person_round8, test_service_repository, test_unit_of_work, test_board_projector, test_outbox, test_auth, test_routes_events, test_app, test_capability.
- Contract: 2 firm (`test_redis_isolation.py`, `test_redis_ttl.py`), 5 conditional (`test_cache_contract.py`, `test_event_bus_contract.py`, `test_factory_drain.py`, `test_session_window.py`, `test_characterisation.py`).
- Unit: 17 firm (listed under TEN-E18); about 13 conditional on design: the nine mapper-family files if the mapper, not the store, stamps `tenantId` (`test_mapper.py`, `test_mapper_backbone.py`, `test_mapper_coded_values.py`, `test_extensions.py`, `test_case_mapping.py`, `test_criteria_mapping.py`, `test_flag_mapping.py`, `test_person_mapping.py`, `test_registration_mapping.py`; recommendation: stamp in `resource_store.py` at write time so the pure mapper tests stay untouched), plus `test_settings.py`, `unit/application/ports/outbound/{test_outbox,test_cache}.py`, `unit/adapters/inbound/fhir_rest/test_routes_events.py`.
- Architecture: 1.
- Support and conftest modules edited: `tests/conftest.py`, `support/{neo4j,api,things,servicebus,redis}.py`, `integration/application/conftest.py`, `contract/{factories,conftest}.py`, `integration/adapters/inbound/fhir_rest/conftest.py` (re-export list).

Totals: **48 firm backend test files (of 154), up to 66 with the conditional ones**; 0 firm frontend test files on `main` (W02's 4 files and `test/cookies.ts` on the branch); 11 branch test files at merge time; 9 support modules.

---

## 11. NETWORK LAYER (DEC-132): FIXTURES, TESTS, TASKS

Source: DEC-132 on main (780bb3e). Tenant is the legal entity; one `Network` groups member tenants; sharing happens only through `Grant`s (scopes `capacity`, `directory`, `criteria`; purpose "network capacity view") and read-only projections written into a network scope with its own id, each copied node carrying `sourceTenantId`. A unit of work binds exactly one scope. The projector reads in a member's scope and writes in the network scope, in two units of work. Nothing in this section changes sections 1 to 10; it extends them.

### 11.1 Effects on the harness design

- A second scope kind. The ambient context variable (3.2) must carry one scope, either a tenant or a network. `bind_tenant` becomes `bind_scope`; the guard that checks the bound scope at teardown stays. A unit of work that tries to bind a second scope must fail (tested in 11.3).
- Scope ids per run: networks get `n-test-<ownerpid>-<epoch>-<8 hex>`, same format and sweeper rules as tenants (3.2). `wipe_tenant` becomes `wipe_scope(driver, scope)`; a run's wipe covers its tenants and its network. The orphan sweeper (TEN-E11) must sweep network scopes and `Network`, `NetworkMembership` and `Grant` nodes too.
- Production has one network (DEC-132 item 5). Tests must not share it across runs, so the model must allow many `Network` nodes, with each run creating its own. Flag for the design audit: any code that assumes a single network breaks parallel runs.
- Redis keys and SSE channels, Service Bus message properties and the projector consumer need a scope id as well as a tenant id; the Redis prefix `diucs:<scope>:` carries either (4.6, 4.7).
- Composite constraints (DEC-130 item 7) apply to the network scope: `(scopeId, id)` on projected nodes, plus `(tenantId or scopeId, sourceTenantId, sourceId)` so a projection is idempotent per source node. The schema tests (5) stay in owned mode.

### 11.2 Fixtures for a network with three member tenants and an owner

Added to the 6.4 fixtures (`tests/support/tenancy.py`, `tests/support/seed.py`):
- `owner_tenant`: the lead hosting organisation. It is itself a tenant and also holds the network, so the world has four tenants in total: the owner plus members `member_a`, `member_b`, `member_c`. Whether the owner is also a member that projects capacity is a design point; the fixture makes it a parameter (`owner_is_member=True`) so both are tested.
- `outsider_tenant`: a fifth tenant that is not in the network, to prove non-members read nothing.
- `network_id`: the run's network scope id (11.1).
- `network_world` (function scope, torn down by `wipe_scope` for all five tenants and the network): creates the network, the memberships, and one service with a capacity report in each member. Every member gets identical service ids with a per-tenant marker (as in 6.1), and sentinel values in every private field the allowlist forbids (reporter name, phone, device, PIN, link token, communication, booking, case, audit entry), so the allowlist test (11.4) can scan for them.
- `grants_for(member, scopes, approved_by_grantor=True, approved_by_owner=True, effective_from, effective_to)` builder with a `FixedClock`, producing grants in each lifecycle state (pending, approved by one side, active, expired, ended by grantor, lapsed by leaving).
- `run_projector(member)`: runs the projector as two units of work (read in the member scope, write in the network scope), returning what it wrote; `as_member(tenant)` and `as_network()` context managers for binding.
- `member_clients`: bearer tokens for staff of each member (a role that may see the board) and for a reporter, plus a wall-screen device token paired to one tenant, for 11.3.
- Fixed `FixedClock` instants are shared by all scopes, as in 4.5; the lifecycle tests move one clock to cross `effective_from`, `effective_to` and the leave date.

### 11.3 Generated isolation test extended to network scope

Extension of 6.1 (`test_tenant_isolation_generated.py`, `query_probes.py`):
1. A scope dimension: each probe declares which scope kind the query belongs to (`tenant` or `network`). The registry will gain network queries (network read, membership, grant, projection write); expect 15 to 25 new ids on top of the about 123 (the probe table and the completeness test cover them).
2. Seed the network scope with copies of the same ids used in the member tenants, each carrying `sourceTenantId`. Run every tenant-scope query bound to tenant A: it returns nothing from the network scope or from B. Run every network-scope query bound to the network scope: it returns nothing that carries a tenant's private properties and touches no tenant-scope node. Rolled-back transactions, as before.
3. Invariant, widened: no relationship joins nodes of two different scopes (tenant to tenant, tenant to network, network to network of another network). The only allowed link from a projected node to its source is the `sourceTenantId` property, not an edge; this is tested.
4. Single-scope unit of work: a unit of work bound to tenant A that calls a network-scope repository, or binds the network scope, raises a fixed-message error and writes nothing. A projector test proves the two-unit-of-work shape: the read in scope A commits or is read-only, the write happens in a second unit of work in the network scope, and a failure between them leaves no partial projection (the second unit is idempotent by source key, so a retry converges).
5. No query text mixes `$tenant` and `$network` (or whichever parameter names the seam uses) in one statement; a static lint in the test of 6.2 (`test_tenant_predicate.py`).
6. Read use case: a member's staff reads the network view only after the membership and grant checks. A non-member and a member whose grant ended get `NotFound` (same body as a missing record, DEC-086 item 5), not `NotAllowed`. The network owner has no read access to a member's private data by being owner: the owner, bound to its own tenant, reading `member_a`'s service id gets `NotFound`, and a query bound to the network scope cannot reach `member_a`'s scope.
7. Roles: staff of a member see the network view and their own tenant's; a reporter on phone or link sees the own tenant only; a wall screen paired to one tenant shows that tenant's board or the network board per its administrator's setting, and cannot be switched by a request parameter.

### 11.4 Projection allowlist test

`tests/unit/.../test_projection_allowlist.py` and `tests/integration/.../test_projection_privacy.py`, tied to the privacy guard (D17, `domain/messages/privacy_guard.py` already has `test_no_patient_data_in_templates.py`, 32 tests, as the pattern):
- An explicit allowlist table: node labels and properties that may enter the network scope. Capacity status and figures, as-of time, not-updated flag; service name, category, location, district coverage, opening hours, service-level contact; current criteria version; the directory `source` property (manual today, Directory of Services later); `sourceTenantId`; the leave date mark. A test fails if a projector statement writes any property not in the table (parse the `SET`, `CREATE` and `MERGE` property maps of the registered projection statements, and any `SET n += $map` is refused because it hides fields).
- Sentinel scan: seed a tenant with a unique sentinel in every forbidden field and run the projector for that tenant; then read every node and relationship in the network scope, all labels, all properties, flattened, and assert no sentinel appears. One parametrised case per forbidden category: reporter name, reporter phone (raw and hash), device id, PIN (raw and hash), link token (raw and hash), communication text, booking, case, audit entry, plus patient identifiers (NHS number, postcode, date of birth) and free text.
- Property-based test (Hypothesis, already a dev dependency): random strings written to forbidden fields never reach the network scope.
- Label allowlist: only the projection labels exist in the network scope; a tenant label (`Practitioner`, `Communication`, `ServiceRequest`, `Task`, `AuditEvent`, `LinkToken`, `Credential`, `ProtectedContact`, `OutboxMessage`) in the network scope fails the test.
- Contact fields: service-level contact is allowed, a practitioner's personal contact is not; the test checks that a service contact stored as a practitioner phone is not projected.
- The allowlist is data the owner and information governance approve (DEC-132 item 9), so the test pins it with a version string; changing the table forces a test edit and a decision.

### 11.5 Grant lifecycle tests

`tests/integration/.../test_grant_lifecycle.py` (clock-driven):
- Approval by both sides: a grant is `pending` until approved by the grantor's administrator and by the network owner; either approval alone shares nothing (the projector writes nothing); approval by a non-administrator is refused; the same person cannot be both approvals if the design says so (open question, section 11.7); the version increases on each change; the stored agreement reference and version are present and the agreement content is never stored.
- Effective window: before `effective_from` nothing projects; between, it does; at and after `effective_to` it stops (boundary at the instant, `FixedClock.set`).
- Ended by the grantor: allowed at any time; stops future sharing only (existing projections stay, no new data projects, the read use case reflects the end date); the network owner cannot end or alter another tenant's grant on its own; ending is audited in the grantor's own audit chain, not the owner's.
- Scope separation: a grant for `capacity` does not share `directory` or `criteria`; each scope is tested as an independent grant.
- A member leaves: membership ends with a leave date, its grants lapse, projections already written stay in the network scope marked with the leave date, no new data is projected, and history remains readable for audit by the path the design allows; the leaving tenant's own data is untouched and follows its own retention. The audit chain of the tenant and of the network each verify after the leave.
- Re-joining creates new membership and grant versions; history from before the leave is not rewritten.
- Concurrency: two administrators approve at the same time, or the grantor ends while the projector runs: a projection written after the end instant must not exist (the projector re-checks the grant in the write unit of work; test with a held transaction as in the racing tests of 5).
- Network-wide: a grant exists per member; one member's grant ending does not change another member's projections.

### 11.6 Number of new tests (network layer)

| Group | Test functions | Collected cases |
|---|---|---|
| Fixtures and harness (scope ids, `wipe_scope`, sweeper, per-run networks) | 5 | 5 |
| Generated isolation extended to network scope (11.3 items 1 to 4) | 8 | about 123 extra parametrised cases (one more scope run per registered query) plus about 20 for the new network queries |
| Network read use case, roles, wall screen, REST (11.3 items 5 to 7) | 14 | 14 |
| Projection allowlist (11.4) | 12 | about 26 (parametrised categories and labels) |
| Grant lifecycle (11.5) | 22 | 22 |
| Network realtime (network SSE channel, Redis keys, projector consumer idempotency per source key) | 7 | 7 |
| **Network total** | **68** | **about 215** |

Combined with 6.5: about **258 new test functions and about 645 collected cases** across tenant isolation and the network. About 55 of the network tests depend on code not yet built (membership, grant, projector, network read use case, wall-screen setting) and are written with those tasks; this audit only counts them.

### 11.7 Open questions and risks added by DEC-132

1. Single network in production, many in tests: the model must not assume one network (11.1), or parallel runs share and corrupt it.
2. Can one person approve both sides of a grant (administrator of the grantor who is also in the owner)? Needed to write the approval tests.
3. Are projections of a member that left readable by the other members, or only by the owner for audit? DEC-132 item 6 says they stay "for audit and history"; the read tests need the visibility rule.
4. The projection allowlist is the highest-value test in this audit: a wrong allowlist exposes patient-adjacent data to other organisations. A mutation check (add a forbidden property to one projector statement on a scratch branch and confirm the tests fail) belongs in the evidence.
5. The network owner is a tenant. The tests must prove that being owner gives no read to members' private data, and that owner-administration actions (membership) are audited in the owner's chain.
6. Two-unit-of-work projection is not atomic: a crash between read and write must converge on retry. Idempotency by source key is a precondition and is tested in 11.3 item 4.
7. Wall-screen board choice (tenant board or network board) is a UI decision still open (DEC-132 item 5); its tests wait for that decision.
8. Human-only gates (DEC-132 item 9) cannot be tested away: the allowlist, the grants and the agreement need information-governance approval before the projector is enabled in any real environment.

### 11.8 Added tasks

| ID | Title | Files | Hours | Depends on |
|---|---|---|---|---|
| TEN-E32 | Network fixtures and harness: `bind_scope`, run network id, `network_world` (owner, three members, outsider), `grants_for`, `run_projector`, `wipe_scope`, sweeper for network scopes | `tests/support/tenancy.py`, `tests/support/seed.py`, `tests/support/neo4j.py`, `tests/conftest.py` | 10 | E07, E08, E11, network model (src) |
| TEN-E33 | Generated isolation test extended to network scope: scope dimension, probes for the new network queries, widened invariant | `tests/support/query_probes.py`, `integration/test_tenant_isolation_generated.py` | 14 | E20, E32 |
| TEN-E34 | Single-scope unit of work and two-unit-of-work projection tests, including retry convergence | `integration/test_network_scope_binding.py` (new) | 6 | E32, projector (src) |
| TEN-E35 | Projection allowlist tests: allowlist table, statement parse, sentinel scan, Hypothesis, label allowlist, mutation evidence | `unit/.../test_projection_allowlist.py` (new), `integration/.../test_projection_privacy.py` (new) | 10 | E32, D17, projector (src) |
| TEN-E36 | Grant lifecycle tests: dual approval, window, end by grantor, leave and history, re-join, concurrency | `integration/.../test_grant_lifecycle.py` (new) | 12 | E32, grant model (src) |
| TEN-E37 | Network read use case, role matrix and wall-screen setting tests (REST) | `integration/adapters/inbound/fhir_rest/test_network_view.py` (new) | 10 | E12, E32, network read (src) |
| TEN-E38 | Network realtime tests: network SSE channel, Redis keys, projector consumer idempotency | `integration/adapters/inbound/fhir_rest/test_network_stream.py`, `integration/adapters/outbound/cache_redis/test_network_keys.py` (new) | 6 | E16, E32 |

Network subtotal 68 hours. Existing test files that gain edits because of DEC-132: none beyond section 10.1 (the network tests are new files); `tests/support/tenancy.py`, `seed.py` and `conftest.py` grow, and the lint tests of 6.2 gain the network-scope rule.
