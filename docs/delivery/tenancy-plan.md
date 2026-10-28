# Tenancy master plan: one canonical task list for the multi-tenancy retrofit

Basis: DEC-130 to DEC-134 and DEC-136, the seven audits in `docs/delivery/tenancy-audit/` (A graph store, B domain and application, C adapters and infrastructure, D front end, E tests and harness, F lifecycle and flows, G task sweep), `docs/plan/tasks.json`, and the live ledger read while this plan was written (78 of 215 tasks delivered; U02, U03, I04 and I09 are stale or in progress, W02 was delivered while this plan was being written). The task list is `docs/plan/tenancy-tasks.json` (ids `TEN-001` to `TEN-086`, epic `T`). Hours are builder hours in the units of `tasks.json`, estimates within plus or minus 30 percent. Nothing here reopens DEC-130 to DEC-134 or DEC-136; where an audit proposal contradicts one of them it is dropped and the reason is shown in section 1.

## 1. Summary, total hours and reconciliation of the audits

### 1.1 Result

- **86 tasks, 540 hours** of tenancy work, each 2 to 8 hours, in build order (an earlier id never depends on a later id), no cycles, no two tasks that share a file without a dependency path between them.

| Stage | Tasks | Hours |
|---|---|---|
| S2 | 38 | 235 |
| S3 | 25 | 160 |
| S4 | 9 | 49 |
| S6 | 9 | 66 |
| S7 | 1 | 6 |
| S9 | 4 | 24 |
| **Total** | **86** | **540** |

- Not counted above, and not planned as tasks: the amendments of 95 undelivered prompts, which the orchestrator has already appended (marker `<!-- tenancy-amendment`). The sweep sizes them at 123.5 extra hours spread over those tasks; they are added to the duration of the feature tasks in the wave plan.
- The whole remaining product, tenancy included: remaining plan hours 470 (all not-yet-delivered tasks, including the four in flight) plus 123.5 hours of amendments plus 540 hours of tenancy tasks, about **1133.5 hours**, in 56 waves of up to four tasks (section 3).
- The interim harness work (machine-wide lock, Neo4j memory limits, owner-based reaper, Bolt readiness probe) is audit E tasks E01 to E04 and is **not planned again**: it belongs to the F10b task now being built. E05 (container reuse) is dropped as superseded, E06 (the context-propagation spike) is folded into TEN-001. TEN-003 (harness step one) must start after F10b has merged, because both edit `backend/tests/conftest.py`; F10b is not a ledger id so that dependency cannot be written in `deps` and is enforced by the orchestrator.

### 1.2 Why the audits add up to far more than this plan

The seven audits propose 239 task rows and about 1364 hours (A 137, B 153, C 137, D 177 (including an optional 8 h), E 365, F 271, G 124 for new rows; G also counts 249 hours of rework and amendments of the 215 existing tasks, which are not task rows). They are not additive. The reasons, with the hours they remove:

1. **The same work was proposed up to five times.** The seam (context variable, `run_query` binding, registration check) is A:G01, B:A01, C:C01, C:C26 and part of G:TEN-G01; the actor and token claim are B:A02, C:C02, C:C03, E:E12 and F:TEN-F08; the tenant record is A:G10, C:C04, F:TEN-F02, F:TEN-F03, G:TEN-G03 and B:A03; the projector is A:G20, B:A24, G:TEN-N04, F:TEN-N06 and N07, with C:C30 for its transport; the network read side is B:A25, G:TEN-N05, F:TEN-N09. Each is one TEN task here.
2. **Test edits were counted twice**: A (inside each repository task), E (E14 24 h, E15 14 h, E21 20 h, E22 to E26 44 h) and F (TEN-T01 to T04) all price the same two-tenant tests. Here each area task carries its own tests and probes, and only the shared machinery (generated test, harness steps, network test suite, cross-tenant reference matrix) is a separate task.
3. **Prompt amendments are not tasks.** C, D, B and F priced the amendment of undelivered prompts as tasks (about 67 hours: C09, C10, C12, C16, C19, C31, D18, D21 to D24, F:A05, F:C04, F:R01, F:W13 and parts of others). The orchestrator has already appended them.
4. **Decisions made after the audits remove work.** DEC-136 drops cross-organisation booking (F:TEN-N16, 12 h), alert fan-out from network events (F:TEN-N14), per-version criteria endorsement and written advisor-phoned positions (parts of F:TEN-N13 and N17), and the tenant chooser (F:TEN-W07: one sub-domain and one session per tenant). DEC-134 settles Concept, CodeSystem and Identifier as tenant-scoped (A:G14 and the 8 h "if shared" alternative disappear), the back end issuing the token, and the seam in two steps.
5. **Sizing differed**: for the same work A, C and G price lower than E and F (the generated test is 6 h in G, 14 h in A and 28 h in E). This plan sizes it at 8 h for the skeleton plus the probes carried by the repository tasks that own the statements, which is the ratchet design A proposed.

Hours by disposition (proposed hours of the rows, by audit; "absorbed" means the row is merged into, or split across, a TEN task):

| Audit | Rows | Proposed h | Merged into one TEN task | Dropped as duplicate of another row | Split across several TEN tasks | Covered by F10b | Prompt amendment, not a task | Dropped by decision |
|---|---|---|---|---|---|---|---|---|
| A | 23 | 137 | 13 / 72 h | 0 / 0 h | 10 / 65 h | 0 / 0 h | 0 / 0 h | 0 / 0 h |
| B | 28 | 153 | 16 / 86 h | 6 / 36 h | 5 / 31 h | 0 / 0 h | 0 / 0 h | 1 / 0 h |
| C | 32 | 137 | 15 / 64 h | 6 / 24 h | 5 / 26 h | 0 / 0 h | 6 / 23 h | 0 / 0 h |
| D | 27 | 177 | 19 / 121 h | 0 / 0 h | 2 / 22 h | 0 / 0 h | 5 / 31 h | 1 / 3 h |
| E | 38 | 365 | 16 / 138 h | 3 / 45 h | 14 / 154 h | 4 / 20 h | 0 / 0 h | 1 / 8 h |
| F | 71 | 271 | 23 / 86 h | 28 / 102 h | 13 / 50 h | 0 / 0 h | 4 / 13 h | 3 / 20 h |
| G | 20 | 124 | 3 / 12 h | 12 / 78 h | 5 / 34 h | 0 / 0 h | 0 / 0 h | 0 / 0 h |

G rows are the 20 new tenancy and network rows of the sweep (TEN-G01 to G06 and TEN-N01 to N14), where G:TEN-G and A:G are different ranges; the 40 delivered tasks the sweep marks for rework are mapped in 1.4. Ids below are written `audit:id`.

### 1.3 Every audit task id and where it went

**Audit A graph store (ids as `A:Gnn`, the audit calls them TEN-G01 to TEN-G23)**

| Id | Proposed title (shortened) | h | Disposition |
|---|---|---|---|
| A:G01 | The seam: `ScopeId`, `bound_scope`, `NamedQuery.scope`/`scopes`/`pr... | 7 | merged into TEN-001 |
| A:G02 | Unit of work, connection, bootstrap and health on the scoped transa... | 6 | merged into TEN-002 |
| A:G03 | Migration runner for parametrised and looped steps; migrations 0031... | 6 | merged into TEN-005; part in TEN-032 |
| A:G04 | ResourceStore and mapper: stamp the six write templates and the rea... | 9 | split across TEN-008, TEN-009 |
| A:G05 | Service, capacity, booking and case repositories (15 statements) | 5 | merged into TEN-010 |
| A:G06 | Person, criteria, flag, registration and scope-list repositories (4... | 8 | split across TEN-011, TEN-012 |
| A:G07 | Link tokens (with global resolver), contacts, credentials and devic... | 7 | split across TEN-013, TEN-014, TEN-015 |
| A:G08 | Scheduled work, idempotency store, processed markers, outbox (17 st... | 5 | split across TEN-015, TEN-016 |
| A:G09 | Audit chain per scope: head provisioning, genesis, `Q-AUDIT-*`, `Q-... | 6 | merged into TEN-017 |
| A:G10 | Tenant registry: `Tenant`, `TenantNumber`, global resolvers (`Q-TEN... | 5 | split across TEN-007, TEN-026, TEN-028 |
| A:G11 | Test harness: per-test tenant fixture, tenant-prefixed `SequentialI... | 8 | part of TEN-003 (the rest of the task is covered by the shared work there) |
| A:G12 | Generated isolation test: probe table, mirror seed, digest and inva... | 14 | split across TEN-004, TEN-030 |
| A:G13 | Indexes and a measurement: `Resource (tenantId, key)` use, typed pa... | 4 | split across TEN-005, TEN-009 |
| A:G14 | Concept recommendation implemented (folded into G04) | 0 | part of TEN-009 (the rest of the task is covered by the shared work there) |
| A:G15 | Operational invariant check: the section 3.3 queries as a health ch... | 2 | merged into TEN-031 |
| A:G16 | Scope kinds: `ScopeId` kinds, `NamedQuery.scopes`, label partition... | 5 | merged into TEN-037; part in TEN-001 |
| A:G17 | Registry: `Network`, `NetworkMembership`, `Grant` nodes and constra... | 6 | merged into TEN-051 |
| A:G18 | Network-scope projection repository: `Projected*`, `ProjectionSourc... | 8 | merged into TEN-053 |
| A:G19 | Projection value objects and allowlist, `to_props()`, D17 guard ext... | 5 | merged into TEN-052 |
| A:G20 | Projector: two units of work, grant check, ordering and replay rule... | 7 | merged into TEN-054 |
| A:G21 | Network scope provisioning and audit: head and genesis, `provision_... | 5 | split across TEN-077, TEN-078 |
| A:G22 | Leave and grant-end semantics: end statements, source marker, live... | 4 | merged into TEN-056 |
| A:G23 | Three-scope generated test: extend TEN-G12 with a network scope, pe... | 5 | merged into TEN-060 (shares the task with E:E32) |

**Audit B domain and application (`B:Ann`, the audit calls them TEN-A01 to A27)**

| Id | Proposed title (shortened) | h | Disposition |
|---|---|---|---|
| B:A01 | Tenancy kernel: `TenantId`, bind, `current_tenant`, `TenantNotBound... | 4 | dropped as duplicate of A:G01, merged into TEN-001 |
| B:A02 | Actor and token carry the tenant: required `Actor.tenant_id`, `BffC... | 5 | merged into TEN-018 |
| B:A03 | Tenant, policy and directory: `Tenant`, `TenantPolicy` with default... | 6 | dropped as duplicate of A:G10, whose task absorbs it (TEN-006, TEN-007) |
| B:A04a | Thread policy: schedule, freshness, status, pressure, reply policy... | 7 | merged into TEN-021 |
| B:A04b | Thread policy: booking rules, report flags, multi-service, criteria... | 8 | merged into TEN-064 |
| B:A05 | Port contracts: `OutboxMessage.tenant_id`, `BusMessage.tenant_id`,... | 6 | split across TEN-010, TEN-013, TEN-020 |
| B:A06 | Audit entry and chain contract: `tenant_id` in canonical actor, `ge... | 4 | dropped as duplicate of A:G09, merged into TEN-017 |
| B:A07 | Idempotency and consumer markers: tenant in fingerprint, composite-... | 3 | merged into TEN-024; part in TEN-016 |
| B:A08 | Rework U01 ReportCapacity: tenant guard, NotFound ordering invarian... | 5 | merged into TEN-024 (shares the task with B:A07) |
| B:A09 | Rework U08 and U09: board audience key function, `wall_actor(curren... | 6 | merged into TEN-039 |
| B:A10 | Templates: tenant fields for region, referral system, coordination... | 5 | merged into TEN-022 |
| B:A11 | References and token resolution: tenant-bound reference generation,... | 6 | split across TEN-010, TEN-013 |
| B:A12 | Two-tenant differential test over every use case (same result as a... | 6 | merged into TEN-027 |
| B:A13 | Rework U02 ConfirmCapacity after it merges: tenant-bound lock and t... | 3 | merged into TEN-027 (shares the task with B:A12) |
| B:A14 | Rework U03 SendPrompts and scheduling after it merges: per-tenant `... | 4 | merged into TEN-027 (shares the task with B:A12) |
| B:A15 | Legacy migration of the domain contract: default tenant id and name... | 2 | merged into TEN-028 (shares the task with F:L01); part in TEN-005 |
| B:A16 | (Placeholder replaced by TEN-A17 to TEN-A27 below, DEC-132.) | 0 | dropped: placeholder row (0 h) replaced by B:A17 to A27 |
| B:A17 | Scope kinds in the kernel: `ScopeId` (reserved `net-` prefix), `bin... | 4 | dropped as duplicate of A:G16, whose task absorbs it (TEN-001, TEN-037) |
| B:A18 | Network domain model and grant rules: `Network`, `Membership`, `Gra... | 7 | merged into TEN-036 |
| B:A19 | Projection domain: allowlists, `CapacityProjection`, `DirectoryProj... | 8 | dropped as duplicate of A:G19, merged into TEN-052 |
| B:A20 | Network ports: `NetworkRepository`, `MembershipRepository`, `GrantR... | 5 | part of TEN-051 (the rest of the task is covered by the shared work there) |
| B:A21 | Actor and access: `Actor.network_ids`, `NetworkAccess`, `require_me... | 5 | merged into TEN-059 (shares the task with G:N06) |
| B:A22 | Membership use cases: CreateNetwork (provisioning), AddNetworkMembe... | 8 | merged into TEN-077 |
| B:A23 | Grant use cases and saga: ProposeGrant, ApproveGrant, ActivateGrant... | 8 | merged into TEN-078 |
| B:A24 | Projection producers and consumer: ProjectCapacity, ProjectDirector... | 10 | dropped as duplicate of A:G20, merged into TEN-054; part in TEN-056 |
| B:A25 | Network read side: QueryNetworkBoard, QueryNetworkDirectory, QueryN... | 8 | split across TEN-057, TEN-058 |
| B:A26 | Events: add the eleven event classes and `network.events` topic, `S... | 4 | merged into TEN-038 |
| B:A27 | Network isolation tests: generated allowlist test over every projec... | 6 | split across TEN-061, TEN-062 |

**Audit C adapters and infrastructure (`C:Cnn`)**

| Id | Proposed title (shortened) | h | Disposition |
|---|---|---|---|
| C:C01 | Tenant id type, context variable, binder and fail-closed errors (pure) | 3 | dropped as duplicate of A:G01, merged into TEN-001; part in TEN-042 |
| C:C02 | `tenant` claim in the BFF token, `Actor.tenant_id`, test token help... | 4 | dropped as duplicate of B:A02, merged into TEN-018 |
| C:C03 | API edge binding: async dependency or middleware, directory check,... | 5 | dropped as duplicate of B:A02, merged into TEN-018 |
| C:C04 | `TenantDirectory` port and Neo4j adapter: Tenant and TenantChannel... | 6 | dropped as duplicate of A:G10, merged into TEN-007 |
| C:C05 | Tenant-scoped cache: `TenantScopedCache` over `RedisCache` and `InM... | 6 | split across TEN-019, TEN-039 |
| C:C06 | Per-tenant lock and fencing: lock names, per-tenant Neo4j high-wate... | 2 | merged into TEN-019 |
| C:C07 | Service Bus message tenant: `BusMessage.tenant_id`, property write,... | 5 | merged into TEN-020 |
| C:C08 | Consumer framework binds tenant from the property, dead-letters on... | 4 | merged into TEN-025 |
| C:C09 | Outbox relay: tenant round robin, per-tenant lock, backoff and batc... | 5 | not a task: I03 relay per tenant: prompt amendment already appended; the relay is feature work |
| C:C10 | Scheduled-work consumer and dispatch table use the bound tenant. **... | 1 | not a task: I05 uses the bound tenant: prompt amendment |
| C:C11 | Per-tenant Twilio: `TwilioSmsRouter`, secret references, `AccountSi... | 5 | merged into TEN-042 |
| C:C12 | SMS inbound and receipt webhooks with lookup-verify-bind flow (2A),... | 6 | not a task: I07 lookup-verify-bind flow: prompt amendment (resolvers are in the edge tasks) |
| C:C13 | Per-tenant email identity and credentials. **Reworks I09 (not deliv... | 4 | merged into TEN-042 (shares the task with C:C11) |
| C:C14 | Link token resolution: global allowlisted statement returning the t... | 5 | merged into TEN-041 |
| C:C15 | Wall-screen pairing: tenant-less pending pairing in `diucs:_:pair:`... | 4 | merged into TEN-041 (shares the task with C:C14) |
| C:C16 | Text codes, sessions, rate limits per tenant; pre-authentication te... | 4 | not a task: text codes, sessions, rate limits per tenant: amendments to I13, U25, R11 (the tenant hint is the host, settled by DEC-134 item 3) |
| C:C17 | Per-tenant phone hash, `code-hmac` and `link-csrf` derivation. **Re... | 2 | merged into TEN-023 |
| C:C18 | BFF session and minting carry the tenant; Entra `tid` to tenant map... | 5 | split across TEN-043, TEN-044 |
| C:C19 | Telemetry: `tenant.id` on spans and logs via the binder, allow-list... | 5 | not a task: telemetry tenant.id: amendments to O01, O04, O07, O08 |
| C:C20 | Composition root: new fields (`tenants`, `secrets`, `cache`, `bus`,... | 5 | part of TEN-007 (the rest of the task is covered by the shared work there) |
| C:C21 | Infra: servicebus subscription names and filters, tenant property d... | 4 | split across TEN-035, TEN-086 |
| C:C22 | Test harness for edges: two-tenant fixtures for API, Redis and Serv... | 6 | part of TEN-035 (the rest of the task is covered by the shared work there) |
| C:C23 | Cross-tenant privilege for support: platform principal, support-cod... | 5 | merged into TEN-084 (shares the task with G:G06) |
| C:C24 | Template branding and tenant-specific wording (DIUCS, Dorset, Systm... | 3 | dropped as duplicate of B:A10, merged into TEN-022 |
| C:C25 | Per-tenant SMS cap and API rate limits; platform source-address lim... | 3 | merged into TEN-040 |
| C:C26 | Scope type: widen the bound context from tenant to scope (`tenant`... | 3 | dropped as duplicate of A:G16, merged into TEN-001 |
| C:C27 | Network access check and claims: `networks` claim (hint), `Actor.ne... | 4 | merged into TEN-059 (shares the task with G:N06) |
| C:C28 | Network read routes and SSE: `$network-board`, `/network/{id}/servi... | 6 | merged into TEN-059 (shares the task with G:N06) |
| C:C29 | Network and grant administration routes (section 13.1): members, gr... | 6 | merged into TEN-079 (shares the task with G:N08) |
| C:C30 | Projection transport: queue `projection.work`, subscriptions `netwo... | 6 | merged into TEN-055 |
| C:C31 | Network telemetry: `network.id`, `scope.kind`, `projection.*` attri... | 2 | not a task: network telemetry attributes: amendments to O01, O04 |
| C:C32 | Wall-screen board scope setting at the edge: device `boardScope`, `... | 3 | merged into TEN-067 |

**Audit D front end (`D:Dnn`)**

| Id | Proposed title (shortened) | h | Disposition |
|---|---|---|---|
| D:D01 | UI tenancy decision record and v1.1 change list (answers to Q1 to Q... | 3 | dropped: the UI answers are recorded in DEC-134 and DEC-136 |
| D:D02 | W02 rework before merge: `tenantId` in Session, fail-closed unseal,... | 5 | merged into TEN-044 |
| D:D03 | Tenant-bound CSRF and a separate link CSRF (`diucs_link_csrf`, or t... | 3 | merged into TEN-046 |
| D:D04 | BFF handler hardening: `Cache-Control: private, no-store` and `Vary... | 5 | merged into TEN-044 (shares the task with D:D02) |
| D:D05 | W01 rework: `fhirFetch` `cache: 'no-store'`, token required except... | 2 | merged into TEN-045 |
| D:D06 | Tenant profile and policy layer: server-only profile fetch cached p... | 7 | merged into TEN-049; part in TEN-040 |
| D:D07 | F03 rework: product-name constant, title template with area name, r... | 2 | merged into TEN-045 (shares the task with D:D05) |
| D:D08 | Test harness: `test/tenants.ts` (A, B, C, network, overlapping ids)... | 8 | merged into TEN-047 |
| D:D09 | Guard rails: lint rules and repo-scan tests (no `use cache`, `unsta... | 4 | merged into TEN-048 |
| D:D10 | Client storage and sign-out wipe: `tenantStore`, `signOutLocal()` (... | 5 | merged into TEN-050 |
| D:D11 | Scope and row-attribution components (tokens only, no new colours):... | 4 | merged into TEN-069 |
| D:D12 | Network scope in the BFF: `/api/bff/network/*` route family and `/n... | 6 | merged into TEN-068 |
| D:D13 | Network capacity view: board grid and list (W05 to W07 components g... | 14 | merged into TEN-070; part in TEN-082 |
| D:D14 | Wall screens: list, which-board control, unpair, re-pair, pairing c... | 9 | merged into TEN-072 |
| D:D15 | Network administration screens (N1): members, add and end membershi... | 10 | merged into TEN-080 |
| D:D16 | Grant approval and sharing transparency (N2): pending grants with t... | 8 | merged into TEN-081 |
| D:D17 | Network unavailable states (N5) and scope-keyed offline: no network... | 5 | merged into TEN-070 (shares the task with D:D13) |
| D:D18 | Telemetry tenancy: server-stamped `tenant.id`, signed context for l... | 6 | not a task: telemetry tenancy: amendments to O02 and O05 |
| D:D19 | Support console cross-tenant mode (E1 to E9): elevation start, pers... | 16 | part of TEN-084 (the rest of the task is covered by the shared work there) |
| D:D20 | Staff sign-in tenant mapping and failure screens (N6), `proxy.ts` i... | 6 | part of TEN-043 (the rest of the task is covered by the shared work there) |
| D:D21 | Reporter and exec device sessions: tenant from the invitation in co... | 10 | not a task: reporter and exec device sessions: amendments to W23, W33 to W38, W55 |
| D:D22 | PWA and offline: tenant-neutral `/offline`, `isCacheable` tests for... | 3 | not a task: PWA and offline: amendment to W32 |
| D:D23 | Config-driven copy sweep: area name, SPOA and staff account names,... | 6 | not a task: configuration-driven copy sweep: amendments to the W prompts |
| D:D24 | Prompt amendments: tenancy-neutral preamble and a tenancy ground-ru... | 6 | not a task: prompt amendments: done by the orchestrator (95 prompts) |
| D:D25 | Two-tenant and network end-to-end suite | 10 | merged into TEN-085 |
| D:D26 | Network scope spec for the UI: wireframes, wording, empty and error... | 6 | merged into TEN-063 |
| D:D27 | Optional: tenant lifecycle UI (N9) | 8 | merged into TEN-083 (shares the task with F:W01); part in TEN-076 |

**Audit E tests and harness (`E:Enn`)**

| Id | Proposed title (shortened) | h | Disposition |
|---|---|---|---|
| E:E01 | Machine-wide test lock and `make test-integration` | 4 | covered by the F10b task: machine-wide test lock: part of the F10b task now being built |
| E:E02 | Neo4j memory and CPU limits on the harness container | 3 | covered by the F10b task: Neo4j memory limits: F10b |
| E:E03 | Owner-labelled containers, owner-liveness reaper, atexit and SIGTER... | 8 | covered by the F10b task: owner-based reaper: F10b |
| E:E04 | Cheaper readiness probe, image-pull-aware start, port race, pytest-... | 5 | covered by the F10b task: Bolt readiness probe: F10b |
| E:E05 | Reuse one container across serial sessions under the lock (optional) | 8 | dropped: container reuse is superseded by the shared Neo4j mode (TEN harness step two); not needed once runs share one instance |
| E:E06 | Spike: context propagation, scoped-delete cost, xdist plus session... | 4 | part of TEN-001 (the rest of the task is covered by the shared work there) |
| E:E07 | `tests/support/tenancy.py`: run tenant id, `bind_tenant`, bound-ten... | 6 | merged into TEN-003 |
| E:E08 | Scoped `wipe_tenant`, `wipe_all`, `clean_graph`, contextual `count_... | 10 | merged into TEN-033 |
| E:E09 | Owned versus attached mode, `DIUCS_TEST_NEO4J_URI`, markers `schema... | 10 | merged into TEN-034 |
| E:E10 | Migrations in attached mode: cross-process lock; rewrite schema tes... | 8 | split across TEN-005, TEN-034 |
| E:E11 | Orphan-tenant sweeper (dead-owner tenants) | 5 | merged into TEN-033 (shares the task with E:E08) |
| E:E12 | Token and API fixtures: tenant claim in `issue_test_token`, bound `... | 7 | dropped as duplicate of B:A02, merged into TEN-018 |
| E:E13 | Seed layer: tenant-aware `seed_service`, `seed_world(tenant)`, one... | 10 | merged into TEN-033 (shares the task with E:E08) |
| E:E14 | Edit graph_store integration tests: scoped raw Cypher, global dumps... | 24 | split across TEN-010, TEN-011, TEN-012, TEN-013, TEN-014, TEN-015 |
| E:E15 | Edit application, audit and outbox integration tests (global counts... | 14 | part of TEN-024 (the rest of the task is covered by the shared work there) |
| E:E16 | Redis: tenant segment in keys, contract factory and tests | 8 | merged into TEN-019 (shares the task with C:C06) |
| E:E17 | Service Bus: serial marker, tenant property, tenant-qualified ids,... | 10 | part of TEN-020 (the rest of the task is covered by the shared work there) |
| E:E18 | Unit-test edits, firm list (17 files) | 14 | split across TEN-001, TEN-002, TEN-018, TEN-019, TEN-020 |
| E:E19 | Registry rule tests, tenant-predicate lint, architecture rule on `t... | 10 | merged into TEN-004 |
| E:E20 | Generated two-tenant isolation test: probe table for about 123 quer... | 28 | dropped as duplicate of A:G12, merged into TEN-004 |
| E:E21 | Repository cross-tenant tests (21 classes, 3 each) | 20 | split across TEN-010, TEN-011, TEN-012, TEN-013, TEN-014, TEN-015 |
| E:E22 | Use-case cross-tenant tests | 8 | merged into TEN-027 (shares the task with B:A12) |
| E:E23 | Audit chain, outbox, idempotency cross-tenant tests | 10 | split across TEN-016, TEN-017 |
| E:E24 | Link token, pairing code, SMS inbound resolution tests (with U10, R... | 10 | dropped as duplicate of C:C14, merged into TEN-041 |
| E:E25 | REST and SSE cross-tenant tests | 8 | part of TEN-018 (the rest of the task is covered by the shared work there) |
| E:E26 | Service Bus consumer and Redis cross-tenant tests | 8 | part of TEN-025 (the rest of the task is covered by the shared work there) |
| E:E27 | Frontend: tenant in BFF session tests, e2e port per run | 6 | split across TEN-035, TEN-044 |
| E:E28 | xdist: dependency, worker tenants through `workerinput`, two-phase... | 10 | merged into TEN-035 |
| E:E29 | CI: Redis and Service Bus services or marker split, shared Neo4j se... | 6 | merged into TEN-035 (shares the task with E:E28) |
| E:E30 | Migrate unmerged branch tests to tenancy (I04 3 files, U02 2, U03 1... | 12 | split across TEN-025, TEN-027, TEN-044 |
| E:E31 | Lessons, DECs, correct the builder, verifier and collective briefs | 3 | merged into TEN-035 (shares the task with E:E28) |
| E:E32 | Network fixtures and harness: `bind_scope`, run network id, `networ... | 10 | merged into TEN-060 |
| E:E33 | Generated isolation test extended to network scope: scope dimension... | 14 | merged into TEN-060 (shares the task with E:E32) |
| E:E34 | Single-scope unit of work and two-unit-of-work projection tests, in... | 6 | merged into TEN-062 |
| E:E35 | Projection allowlist tests: allowlist table, statement parse, senti... | 10 | merged into TEN-062 (shares the task with E:E34) |
| E:E36 | Grant lifecycle tests: dual approval, window, end by grantor, leave... | 12 | merged into TEN-061 |
| E:E37 | Network read use case, role matrix and wall-screen setting tests (R... | 10 | split across TEN-059, TEN-062 |
| E:E38 | Network realtime tests: network SSE channel, Redis keys, projector... | 6 | split across TEN-059, TEN-062 |

**Audit F lifecycle and flows (`F:` plus the audit letter and number, for example `F:A01` is F's TEN-A01, not B's)**

| Id | Proposed title (shortened) | h | Disposition |
|---|---|---|---|
| F:A01 | Staff sign-in: multi-directory Entra, tid allow-list, group mapping... | 4 | merged into TEN-043 |
| F:A02 | Operator sign-in and roles: operator directory only, audience, sepa... | 4 | split across TEN-043, TEN-083 |
| F:A03 | Support access scoped to one tenant, approved by the tenant lead (a... | 3 | dropped as duplicate of C:C23, merged into TEN-084 |
| F:A04 | Wire pre-session resolvers: link token, invitation, device token, p... | 4 | dropped as duplicate of C:C14, merged into TEN-041; part in TEN-040 |
| F:A05 | Tenant-keyed identity stores: Redis keys, code store, sessions, rat... | 4 | not a task: tenant-keyed identity stores: amendments to I13, U25, U32, I01 is delivered and covered by the cache task |
| F:C01 | Per-tenant Twilio resolver, inbound webhook by To and AccountSid, r... | 4 | part of TEN-042 (the rest of the task is covered by the shared work there) |
| F:C02 | Per-tenant email sender (amends I09, I10) | 3 | merged into TEN-042 (shares the task with C:C11) |
| F:C03 | Service Bus tenant property, per-tenant relay loop and lock, consum... | 4 | part of TEN-020 (the rest of the task is covered by the shared work there) |
| F:C04 | Push per tenant: VAPID per tenant, manifest per tenant (amends I14,... | 3 | not a task: push per tenant: amendment to I14 and W32 to W35 |
| F:F01 | Tenant and scope domain model, lifecycle state machine, activation... | 4 | merged into TEN-006 |
| F:F02 | Scope registry, scope kinds, platform-scope resolvers (link, device... | 4 | dropped as duplicate of A:G10, merged into TEN-007 |
| F:F03 | Tenant records and repositories (Tenant, config versions, settings,... | 4 | split across TEN-007, TEN-026 |
| F:F04 | Tenant settings registry (typed keys, bounds, safety class) and con... | 4 | merged into TEN-006 (shares the task with F:F01) |
| F:F05 | Per-tenant key derivation, secret references, hashKeyVersion and th... | 3 | dropped as duplicate of C:C17, whose task absorbs it (TEN-023) |
| F:F06 | Per-scope audit chain: genesis, head per scope, verification per scope | 4 | dropped as duplicate of A:G09, merged into TEN-017 |
| F:F07 | Composite constraints, expand and contract (table in section 2.6) | 4 | dropped as duplicate of A:G03, merged into TEN-005 |
| F:F08 | Session and token claims: scope, tenant epoch, per-request epoch ch... | 4 | dropped as duplicate of B:A02, merged into TEN-018 |
| F:H01 | Hazard log rows, DCB0129 note and runbooks (suspend, offboard, lost... | 3 | merged into TEN-086 |
| F:K01 | Thread tenant settings through the pure rules (reply window, ladder... | 4 | split across TEN-021, TEN-064 |
| F:K02 | Load settings in use cases and keep the version on decisions (audit... | 4 | part of TEN-024 (the rest of the task is covered by the shared work there) |
| F:K03 | Time zone threading into the five modules (amends F06, D03, D04, D2... | 4 | merged into TEN-065 |
| F:K04 | Template tenant fields and guard: sender label, system name, SPOA p... | 3 | dropped as duplicate of B:A10, merged into TEN-022 |
| F:K05 | Bank holiday calendar and service closures | 4 | merged into TEN-066 |
| F:L01 | CreateTenant, RecordTenantChannel, ActivateTenant | 4 | merged into TEN-028 |
| F:L02 | InviteTenantAdmin and first sign-in, BindEntraDirectory, MapEntraGroup | 4 | merged into TEN-028 (shares the task with F:L01) |
| F:L03 | DraftTenantConfig, ApproveTenantConfig, configuration diff | 4 | merged into TEN-026 |
| F:L04 | SuspendTenant and ResumeTenant: modes, epoch, relay gate, board deg... | 4 | merged into TEN-073 |
| F:L05 | StartOffboarding and ExportTenant | 4 | merged into TEN-074 |
| F:L06 | PurgeTenant, tombstone, number quarantine | 4 | merged into TEN-074 (shares the task with F:L05) |
| F:L07 | Operator and tenant-admin API routes (/platform, /tenant, /me/tenants) | 4 | merged into TEN-075 |
| F:M01 | Default-tenant backfill job, label by label, restartable, idempotent | 4 | dropped as duplicate of A:G03, merged into TEN-005 |
| F:M02 | Invariant monitor: null tenant id check at start and daily, service... | 3 | dropped as duplicate of A:G15, merged into TEN-031 |
| F:M03 | Cut-over runbook and scripts: drain, Redis, Service Bus, secrets, T... | 3 | split across TEN-028, TEN-086 |
| F:M04 | Contract step: drop superseded constraints | 2 | merged into TEN-032 |
| F:N01 | Network, membership, agreement and grant domain rules and state mac... | 4 | dropped as duplicate of B:A18, merged into TEN-036 |
| F:N02 | Network scope repositories and migrations (Network, agreement, memb... | 4 | split across TEN-051, TEN-053 |
| F:N03 | Create network, add and remove members, leave notice | 4 | dropped as duplicate of B:A22, merged into TEN-077 |
| F:N04 | Grant create, approve, change, end: two approvals, lock-first end | 4 | dropped as duplicate of B:A23, merged into TEN-078 |
| F:N05 | Projection allowlist registry, DTOs, privacy guard and schema tests | 4 | dropped as duplicate of A:G19, merged into TEN-052 |
| F:N06 | Projector: directory and criteria | 4 | dropped as duplicate of A:G20, merged into TEN-054 |
| F:N07 | Projector: capacity and status with validUntil, heartbeat and ordering | 4 | dropped as duplicate of A:G20, merged into TEN-054 |
| F:N08 | Provider-side boundary scheduler: overdue, open, close emit a proje... | 3 | merged into TEN-056 (shares the task with A:G22) |
| F:N09 | QueryNetworkBoard and the network versions of the options and crite... | 4 | dropped as duplicate of B:A25, merged into TEN-057 |
| F:N10 | Network cache and live stream; staleness degrade (amends U09, R06) | 3 | dropped as duplicate of G:N07, merged into TEN-058 |
| F:N11 | Wall screen display mode, tenant or network, with fallback (amends... | 3 | dropped as duplicate of C:C32, merged into TEN-067 |
| F:N12 | Member leave handling: lapse grants, mark records, history view | 3 | dropped as duplicate of A:G22, merged into TEN-056 |
| F:N13 | Listing admission and criteria endorsement (G2, G3) | 4 | part of TEN-077 (the rest of the task is covered by the shared work there) |
| F:N14 | Network events to member alert evaluators (G5) (amends U33, U34) | 4 | dropped: DEC-136 item 9: alerts stay tenant-only |
| F:N15 | Projection reconciliation and revoked-grant leak check job | 3 | dropped as duplicate of A:G22, merged into TEN-056 |
| F:N16 | Booking path under the G1 default: booking contact in the directory... | 12 | dropped: DEC-136 item 1: no cross-organisation booking |
| F:N17 | Advisor-phoned positions and listing suspension in the network scop... | 4 | part of TEN-077 (the rest of the task is covered by the shared work there) |
| F:R01 | Tenant and network dimension on telemetry and aggregates (amends O0... | 3 | not a task: telemetry dimension: amendments to O04 and O08 |
| F:R02 | Network-scope week summary measures (G6) (amends U35) | 4 | dropped as duplicate of G:N13, merged into TEN-082 |
| F:T01 | Two-tenant and network test harness: seed two tenants and a network... | 4 | split across TEN-004, TEN-060 |
| F:T02 | Relationship matrix test: cross-tenant references refused with the... | 4 | merged into TEN-029 |
| F:T03 | Pre-session entry points and idempotency cross-tenant tests | 4 | dropped as duplicate of C:C14, merged into TEN-041 |
| F:T04 | Access test harness: per-route cross-tenant and cross-network objec... | 4 | dropped as duplicate of E:E25, merged into TEN-018 |
| F:W01 | Operator console shell, tenants list and detail | 4 | merged into TEN-083 |
| F:W02 | Create tenant wizard and activation checklist | 4 | merged into TEN-083 (shares the task with F:W01) |
| F:W03 | Suspend, offboard, export and purge dialogs | 4 | merged into TEN-083 (shares the task with F:W01) |
| F:W04 | Tenant settings: configuration versions, diff, approvals | 4 | merged into TEN-076 |
| F:W05 | Channels (read-only), Entra mapping, retention and operator access... | 4 | merged into TEN-076 (shares the task with F:W04) |
| F:W06 | Tenant users and roles page | 3 | merged into TEN-076 (shares the task with F:W04) |
| F:W07 | Tenant chooser, header banner, URL scoping, per-slug cookies (amend... | 4 | dropped: DEC-136 items 7 and 11: one session per tenant on its own host, so no chooser |
| F:W08 | Wall header, exec home and wording from settings (sweep of W05, W36... | 3 | part of TEN-049 (the rest of the task is covered by the shared work there) |
| F:W09 | Network admin: members, invite, remove, leave notice | 4 | dropped as duplicate of D:D15, merged into TEN-080 |
| F:W10 | Network admin: grants (create, approve, end) and agreement versions | 4 | split across TEN-080, TEN-081 |
| F:W11 | Network view on board and options, projection health and stale states | 4 | dropped as duplicate of D:D13, merged into TEN-070 |
| F:W12 | Wall screen mode control for the tenant admin | 2 | dropped as duplicate of D:D14, merged into TEN-072 |
| F:W13 | PWA per tenant: manifest, scope, set-up flow changes (amends W32 to... | 3 | not a task: PWA per tenant: amendments to W32 to W35 |
| F:W14 | Listing admission and criteria endorsement screens | 4 | dropped as duplicate of D:D15, merged into TEN-080 |

**Audit G sweep new rows (`G:G01` to `G:G06` are TEN-G01 to G06, `G:N01` to `G:N14` are TEN-N01 to N14)**

| Id | Proposed title (shortened) | h | Disposition |
|---|---|---|---|
| G:G01 | Two-tenant test generated from the query registry | 6 | dropped as duplicate of A:G12, merged into TEN-004; part in TEN-030 |
| G:G02 | Composite constraints, index swap and tenantId backfill | 6 | dropped as duplicate of A:G03, merged into TEN-005 |
| G:G03 | Tenant record, TenantConfig port and secret references | 8 | dropped as duplicate of A:G10, whose task absorbs it (TEN-007, TEN-026) |
| G:G04 | Tenant lifecycle: create, suspend, offboard | 10 | split across TEN-028, TEN-073, TEN-074 |
| G:G05 | Unauthenticated-edge tenant resolution | 6 | split across TEN-040, TEN-041 |
| G:G06 | Cross-tenant privilege guard (support and operator) | 3 | dropped as duplicate of C:C23, merged into TEN-084 |
| G:N01 | Network scope model and repositories | 8 | dropped as duplicate of A:G17, merged into TEN-051 |
| G:N02 | Network administration use cases | 10 | split across TEN-077, TEN-078 |
| G:N03 | Projection allowlist and privacy guard | 4 | dropped as duplicate of A:G19, merged into TEN-052 |
| G:N04 | Network projector worker | 12 | dropped as duplicate of A:G20, merged into TEN-054 |
| G:N05 | Network read use cases | 8 | dropped as duplicate of B:A25, merged into TEN-057 |
| G:N06 | Network API | 5 | dropped as duplicate of C:C28, merged into TEN-059 |
| G:N07 | Network cache key and live updates | 3 | merged into TEN-058 |
| G:N08 | Network administration API | 4 | dropped as duplicate of C:C29, merged into TEN-079 |
| G:N09 | Network administration screens | 8 | dropped as duplicate of D:D15, merged into TEN-080 |
| G:N10 | Wall screen board-scope setting | 3 | split across TEN-067, TEN-072 |
| G:N11 | Network board UI variant | 6 | dropped as duplicate of D:D13, merged into TEN-070 |
| G:N12 | Network directory and criteria view | 5 | merged into TEN-071 |
| G:N13 | Network week summary and pressure | 4 | merged into TEN-082 |
| G:N14 | Two-member network tests | 5 | split across TEN-060, TEN-061, TEN-062 |

### 1.4 The 40 delivered tasks the sweep marks REWORK-DELIVERED, and the rework task that carries each

| Delivered task | Reworked by |
|---|---|
| D16 Message templates: booking, invitations, codes, alerts | TEN-022 |
| D17 No-patient-data guard for every template | TEN-022, TEN-052 |
| D26 Link tokens, pairing codes and support codes | TEN-013 |
| F02 Architecture import rules enforced by tests | TEN-001 |
| F04 Local infrastructure with Docker Compose | TEN-055 |
| F08 Settings and composition root skeleton | TEN-001, TEN-007, TEN-026 |
| F10 Neo4j test harness | TEN-003, TEN-033, TEN-034 |
| F11 Restartable Neo4j mode in the test harness | TEN-003, TEN-034 |
| G01 Neo4j adapter base: driver, named queries, migrations | TEN-001, TEN-002, TEN-005, TEN-030 |
| G02 FHIR-to-graph mapper: resources, primitives, references | TEN-008 |
| G03 Mapper: concepts, identifiers, periods and quantities | TEN-008 |
| G04 Mapper: backbone elements and extension registry | TEN-008 |
| G05 Graph writer and reader with versions | TEN-009 |
| G14 Neo4j connection lifecycle, health and recovery | TEN-002 |
| I01 Redis cache adapter | TEN-019 |
| I02 Service Bus event bus adapter | TEN-020 |
| I06 Twilio SMS adapter | TEN-042 |
| P01 Service and capacity ports with Neo4j repositories | TEN-010 |
| P02 Booking port with Neo4j repository | TEN-010 |
| P03 Person, role and practitioner ports with Neo4j repository | TEN-011 |
| P04 Criteria port with Neo4j repository | TEN-012 |
| P05 Audit log port with Neo4j hash chain and provenance | TEN-017 |
| P06 Outbox and unit of work on Neo4j | TEN-002, TEN-016 |
| P07 Messaging ports, recording senders and Neo4j communication records | TEN-015 |
| P08 Event bus port, manual-clock fake and Neo4j scheduled-work records | TEN-015, TEN-020 |
| P09 Cache port with in-memory fake | TEN-019 |
| P10 Link token, secret and phone-hash ports with Neo4j token store | TEN-013, TEN-023 |
| P12 Contract tests for the cache and event bus fakes | TEN-019, TEN-020 |
| P13 Registration and scope list ports with Neo4j repositories | TEN-011 |
| P14 Report and service flag ports with Neo4j repository | TEN-012 |
| P15 Idempotency store and processed-message markers on Neo4j | TEN-016 |
| P16 Contact store and PIN credentials on Neo4j, text-code store port | TEN-014 |
| P21 Case port with Neo4j repository | TEN-010 |
| R01 FHIR REST app skeleton | TEN-018 |
| R02 Authentication, roles and service scope | TEN-018, TEN-043 |
| R03 ETag, If-Match and Idempotency-Key handling | TEN-018 |
| R06 Server-sent events stream | TEN-039 |
| U01 ReportCapacity use case | TEN-024 |
| U08 QueryBoard read model | TEN-039 |
| U09 Board projector: cache and live updates | TEN-039 |

Also reworked, beyond the sweep list: D03, D04, D05, D07, D08, D11, D12, D14, D15, D21, D23, D24, D25, D27, D28, F03, F05, F06, W01, W02. The sweep marked the pure rules D04, D05, D07, D08, D11, D12, D14, D21, D23, D24, D27, D28 and the time rules F06, D03 as unchanged; audits B and F show that DEC-134 item 14 (threshold overrides) and DEC-136 item 13 (time zone and bank holidays) need them to take a policy or zone argument, so TEN-021, TEN-064 and TEN-065 add it with a default equal to today's constant, which leaves every delivered caller unchanged. W01, F03 and W02 are reworked by the front-end tasks (audit D); the sweep rated W01 and F03 as no change.

### 1.5 Conflicts between the audits, and what this plan took

| Question | Audits | Taken | Why |
|---|---|---|---|
| Do tenancy-bound tests run in parallel on one Neo4j as soon as the harness binds a tenant? | G wave 3 says yes; E says only after composite constraints and an attached mode | Not until harness step two (TEN-033 to TEN-035), after enforce and the contract migration | Until every statement stamps `tenantId` a tenant-scoped wipe leaves unstamped nodes behind, and fixed ids collide across runs while the single-property constraints exist. Waves before that are marked serial. |
| Seam in one task or two | A: one task; G, DEC-134 item 12: two steps | Two: TEN-001 (warn) and TEN-030 (enforce) | DEC-134 item 12 |
| Where does the tenant record live and how are secrets named | A: registry nodes; C: Tenant plus TenantChannel; F: Tenant plus many child records | TEN-007 (Tenant, TenantNumber, directory, secret references), TEN-026 (config versions, channels, contacts, bindings, retention) | Split so the early seam work needs only the small part |
| Hashed audit text includes tenantId | B and G: add it; A and DEC-134 item 10: unchanged | Unchanged, genesis per new scope | DEC-134 item 10 |
| Service Bus session id | C and B: `<tenant>:<service>`; G: stays the service UUID | Stays the service UUID; the tenant is a message property | Server UUIDs cannot collide; tests use the tenant filter |
| Network scope id prefix | B: `net-`; C: `_net-` | `net-` and tenant ids may not start with it (decided in TEN-001) | One reserved prefix, checked at construction |
| Push keys | C and G: one platform key; F: per tenant | Per tenant, with a secret reference (the I14 amendment text says platform-wide and is listed in section 5 for re-reading) | DEC-136 item 11 gives each tenant its own origin |
| Concept, CodeSystem | DEC-130: shared; A, E: per tenant | Per tenant (DEC-134 item 1) | Decided |
| Booking across organisations | F: owner tenant texts a booking contact (12 h); C, B: not possible | Not built | DEC-136 item 1 |
| Tenant chooser at sign-in | F: yes; D: URL per tenant | No chooser: one host and one session per tenant | DEC-134 item 3, DEC-136 items 7 and 11 |
| Token epoch (suspend takes effect within a cache interval) | F: epoch claim; C: directory status check | Both, in TEN-018 (status and epoch from the directory, cached for at most 60 seconds) | H-T23 needs suspend to bite before `exp` |
| Who issues the token | DEC-134 item 2 | Back end (TEN-043); the BFF holds no signing secret | Decided |
| Operator console | F: three UI tasks plus operator sign-in; D: optional 8 h | One last, droppable task (TEN-083); a `provision_tenant` script comes with TEN-028 | A pilot with a handful of tenants does not need a console to start |

## 2. The TEN tasks

Impact is the sweep scale (NONE, LOW, MEDIUM, HIGH). N means the task runs Neo4j tests (one run at a time until harness step two), P means none. Stage is the sweep stage where the work belongs; a task never depends on a later-stage TEN task. Descriptions of what each task does are in the second table.

| Id | Stage | Title | Hours | Depends on | Reworks delivered | Impact | Neo4j |
|---|---|---|---|---|---|---|---|
| TEN-001 | S2 | Tenancy seam step one: tenant context, run_query binding and registration check in warn mode | 8 | G01, G14, F02, F08 | G01, F02, F08 | HIGH | P |
| TEN-002 | S2 | Unit of work, connection and health on the scoped transaction (reworks P06, G14) | 6 | TEN-001, P06 | P06, G14, G01 | HIGH | N |
| TEN-003 | S2 | Test harness step one: tenant per run, bound-tenant fixtures, tenant-prefixed ids (reworks F10, F11) | 6 | F10, F11, TEN-001, TEN-002 | F10, F11 | HIGH | N |
| TEN-004 | S2 | Generated two-tenant isolation test over the query registry, with the unconverted-ids ratchet | 8 | TEN-001, TEN-002, TEN-003 | - | HIGH | N |
| TEN-005 | S2 | Composite constraints, index swap and default-tenant backfill (runs alone) | 8 | G01, TEN-004 | G01 | HIGH | N |
| TEN-006 | S2 | Tenant domain model, configuration bounds, policy defaults and lifecycle state machine (pure) | 7 | D22, F06 | - | MEDIUM | P |
| TEN-007 | S2 | Tenant record, TenantDirectory, global statement allowlist, secret references and fake secret store | 8 | TEN-005, TEN-006, TEN-002 | F08 | HIGH | N |
| TEN-008 | S2 | Mapper reserves tenantId; Concept, CodeSystem and Identifier tenant-scoped (reworks G02 to G04) | 3 | TEN-005, TEN-004 | G02, G03, G04 | MEDIUM | P |
| TEN-009 | S2 | Resource store statements stamped and anchored (reworks G05) | 8 | TEN-008, TEN-005, TEN-004, TEN-002 | G05 | HIGH | N |
| TEN-010 | S2 | Service, capacity, booking and case repositories tenant-scoped (reworks P01, P02, P21) | 7 | TEN-009, TEN-005, U02 | P01, P02, P21 | MEDIUM | N |
| TEN-011 | S2 | Person, registration and scope-list repositories tenant-scoped (reworks P03, P13) | 8 | TEN-009, TEN-005 | P03, P13 | HIGH | N |
| TEN-012 | S2 | Criteria and flag repositories tenant-scoped (reworks P04, P14) | 7 | TEN-009, TEN-005 | P04, P14 | MEDIUM | N |
| TEN-013 | S2 | Link token record and store carry the tenant (reworks D26, P10) | 5 | TEN-002, TEN-005, TEN-007 | D26, P10 | HIGH | N |
| TEN-014 | S2 | Contact, credential and device stores tenant-scoped (reworks P16) | 5 | TEN-002, TEN-005 | P16 | HIGH | N |
| TEN-015 | S2 | Communication and scheduled-work repositories tenant-scoped (reworks P07, P08) | 5 | TEN-009, TEN-005 | P07, P08 | MEDIUM | N |
| TEN-016 | S2 | Outbox, idempotency and processed markers tenant-scoped (reworks P06, P15) | 6 | TEN-002, TEN-005 | P06, P15 | HIGH | N |
| TEN-017 | S2 | Audit chain per scope with per-scope genesis (reworks P05) | 8 | TEN-002, TEN-005 | P05 | HIGH | N |
| TEN-018 | S2 | REST edge: tenant claim, Actor.tenant_id, roles, scope binding dependency (reworks R01, R02, R03) | 8 | TEN-007, TEN-002, TEN-003, TEN-017, TEN-016 | R01, R02, R03 | HIGH | N |
| TEN-019 | S2 | Tenant-scoped cache keys, locks and channels in the adapter and the fake (reworks P09, I01, P12) | 6 | TEN-001 | P09, I01, P12 | MEDIUM | P |
| TEN-020 | S2 | Service Bus tenant property and in-memory bus parity (reworks I02, P08, P12) | 6 | TEN-019, TEN-001 | I02, P08, P12 | MEDIUM | P |
| TEN-021 | S2 | Tenant policy threaded through board and prompt rules (reworks D04, D05, D07, D08, D11) | 7 | TEN-006 | D04, D05, D07, D08, D11 | MEDIUM | P |
| TEN-022 | S2 | Message templates take tenant fields; no place names (reworks D15, D16, D17) | 4 | TEN-006 | D15, D16, D17 | LOW | P |
| TEN-023 | S2 | Per-tenant derived hash and token keys | 3 | TEN-007, TEN-013 | P10 | MEDIUM | P |
| TEN-024 | S2 | ReportCapacity rework: tenant guard, performer validation, fingerprint (reworks U01) | 6 | TEN-018, TEN-010, TEN-016, TEN-017 | U01 | MEDIUM | N |
| TEN-025 | S2 | Consumer framework binds and verifies the tenant (I04 after delivery) | 4 | I04, TEN-020, TEN-007, TEN-016 | - | HIGH | N |
| TEN-026 | S2 | Tenant configuration versions, channels, contacts, directory binding and retention | 8 | TEN-007, TEN-021, TEN-017 | F08 | MEDIUM | N |
| TEN-027 | S2 | Migrate U02 and U03 after delivery; use-case differential and held-lock test | 6 | TEN-024, U02, U03, TEN-015, TEN-016, TEN-026 | - | MEDIUM | N |
| TEN-028 | S2 | Tenant provisioning: create, activate, provision scope, first administrator | 8 | TEN-006, TEN-007, TEN-026, TEN-017, TEN-011, TEN-023 | - | HIGH | N |
| TEN-029 | S2 | Cross-tenant reference matrix test and placeholder refusal | 5 | TEN-010, TEN-011, TEN-012, TEN-015 | - | HIGH | N |
| TEN-030 | S2 | Tenancy seam step two: enforce mode, ratchet empty, mutant evidence | 6 | TEN-004, TEN-009, TEN-010, TEN-011, TEN-012, TEN-013, TEN-014, TEN-015, TEN-016, TEN-017, TEN-018, TEN-025, TEN-029, TEN-024 | G01 | HIGH | N |
| TEN-031 | S2 | Start-up and daily invariant check for nodes without a tenantId | 3 | TEN-030 | - | HIGH | N |
| TEN-032 | S2 | Contract migration: drop superseded single-property constraints (runs alone) | 3 | TEN-030, TEN-031 | - | MEDIUM | N |
| TEN-033 | S2 | Test harness step two (a): tenant-scoped wipe, helpers, sweeper, seed layer | 8 | TEN-030, TEN-032 | F10 | HIGH | N |
| TEN-034 | S2 | Test harness step two (b): shared Neo4j attached mode, markers, exclusive runs, migration lock | 8 | TEN-033 | F10, F11 | HIGH | N |
| TEN-035 | S2 | Test harness step two (c): parallel runs, CI, serial markers, briefs corrected | 8 | TEN-034 | F05 | MEDIUM | N |
| TEN-036 | S2 | Network domain model and grant rules (pure) | 6 | TEN-006, D25 | - | MEDIUM | P |
| TEN-037 | S2 | Seam: network scope kind, label partition lint, read-only and nested-unit rules | 5 | TEN-030, TEN-036 | - | HIGH | N |
| TEN-038 | S2 | Network domain events and topic | 4 | TEN-036, TEN-020 | D25 | LOW | P |
| TEN-039 | S3 | Board projector, query board and SSE stream per tenant (reworks U08, U09, R06) | 7 | TEN-018, TEN-019, TEN-020, TEN-021 | U08, U09, R06 | HIGH | N |
| TEN-040 | S3 | Unauthenticated edge: host-based tenant resolution, public profile, rate limiter | 6 | TEN-018, TEN-007, TEN-019 | - | HIGH | N |
| TEN-041 | S3 | Unauthenticated edge: link, invitation, device, pairing and inbound-number resolvers | 5 | TEN-040, TEN-013, TEN-014 | - | HIGH | N |
| TEN-042 | S3 | Per-tenant Twilio and email senders (reworks I06; I09 after delivery) | 7 | TEN-026, TEN-015, I06, I09 | I06 | MEDIUM | P |
| TEN-043 | S3 | Back-end token exchange: the back end issues the tenant-bound token | 7 | TEN-018, TEN-026, TEN-040 | R02 | HIGH | N |
| TEN-044 | S3 | BFF session and handler rework: tenant in session, no-store, input guard (reworks W02) | 8 | W02, TEN-043 | W02, W01 | HIGH | P |
| TEN-045 | S3 | Front-end foundation guards (reworks W01, F03) | 4 | W01, F03, TEN-044 | W01, F03 | LOW | P |
| TEN-046 | S3 | Tenant-bound CSRF and separate link CSRF cookie | 3 | TEN-044 | W02 | MEDIUM | P |
| TEN-047 | S3 | Front-end tenancy test harness and leak canary | 8 | TEN-044, TEN-045 | W01 | MEDIUM | P |
| TEN-048 | S3 | Front-end guard rails: lint and repository scans | 4 | TEN-045 | - | LOW | P |
| TEN-049 | S3 | Tenant profile and copy layer; remove global SPOA phone variable | 7 | TEN-044, TEN-040 | - | MEDIUM | P |
| TEN-050 | S3 | Browser state wipe on sign-out and unpair | 5 | TEN-044 | - | MEDIUM | P |
| TEN-051 | S3 | Network registry: Network, membership, grant and listing nodes, repositories, ports | 8 | TEN-037, TEN-036, TEN-007 | - | HIGH | N |
| TEN-052 | S3 | Projection allowlist, DTOs and privacy guard (reworks D17) | 8 | TEN-036, TEN-022, TEN-021 | D17 | MEDIUM | P |
| TEN-053 | S3 | Network-scope projection repository and constraints | 8 | TEN-051, TEN-052 | - | HIGH | N |
| TEN-054 | S3 | Network projector core: producers and apply step in two units of work | 8 | TEN-053, TEN-025, I05, TEN-039, TEN-012, TEN-010, TEN-038 | - | HIGH | N |
| TEN-055 | S3 | Projection transport: queue, subscriptions, two-scope runner (reworks F04) | 5 | TEN-054, TEN-020 | F04 | MEDIUM | N |
| TEN-056 | S3 | Leave and grant-end semantics, boundary projection, reconciliation | 6 | TEN-054, TEN-027 | - | HIGH | N |
| TEN-057 | S3 | Network read use cases with staleness degrade | 8 | TEN-054, TEN-018, TEN-026 | - | HIGH | N |
| TEN-058 | S3 | Network board projector, cache keys and channel | 4 | TEN-057, TEN-019, TEN-039 | - | MEDIUM | N |
| TEN-059 | S3 | Network API: board, directory, criteria, stream, membership claims | 6 | TEN-058, R05 | - | MEDIUM | N |
| TEN-060 | S3 | Network test fixtures and generated test extended to three scopes | 8 | TEN-053, TEN-051, TEN-004, TEN-003 | - | HIGH | N |
| TEN-061 | S3 | Two-member network tests: grant lifecycle, leave, history, concurrency | 8 | TEN-056, TEN-060 | - | HIGH | N |
| TEN-062 | S3 | Two-member network tests: privacy scan, scope binding, roles, isolation of keys and streams | 8 | TEN-059, TEN-060 | - | HIGH | N |
| TEN-063 | S3 | Network screens specification for the UI | 4 | - | - | LOW | P |
| TEN-064 | S4 | Tenant policy threaded through booking, flag, grouping, criteria, alert and clinical rules | 8 | TEN-021 | D12, D14, D21, D23, D24, D28, D27 | MEDIUM | P |
| TEN-065 | S4 | Time zone per tenant and network passed explicitly into the time rules | 4 | TEN-064 | F06, D03, D04, D21, D24 | LOW | P |
| TEN-066 | S4 | Bank holiday calendar and service closures | 5 | TEN-065 | D03, D04 | LOW | P |
| TEN-067 | S4 | Wall screen board scope setting (backend) | 3 | TEN-059, U10, R15 | - | MEDIUM | N |
| TEN-068 | S4 | BFF network scope: routes, availability check, stream relay | 6 | TEN-044, TEN-047, TEN-059, TEN-063 | - | MEDIUM | P |
| TEN-069 | S4 | Scope header and organisation label components | 4 | TEN-049, TEN-063 | - | LOW | P |
| TEN-070 | S4 | Network board UI and unavailable states | 8 | TEN-068, TEN-069 | - | MEDIUM | P |
| TEN-071 | S4 | Network directory and criteria views | 5 | TEN-068, TEN-069 | - | MEDIUM | P |
| TEN-072 | S4 | Wall screen administration and last-known by scope | 6 | TEN-067, TEN-068, TEN-050 | - | MEDIUM | P |
| TEN-073 | S6 | Tenant suspend and resume | 6 | TEN-028, TEN-018, TEN-020, TEN-027 | - | HIGH | N |
| TEN-074 | S6 | Tenant offboarding, export and purge | 8 | TEN-073, TEN-056 | - | HIGH | N |
| TEN-075 | S6 | Operator and tenant-administrator API routes | 6 | TEN-028, TEN-073, TEN-043 | - | MEDIUM | N |
| TEN-076 | S6 | Tenant administration screens | 8 | TEN-075, TEN-049, TEN-047 | - | MEDIUM | P |
| TEN-077 | S6 | Network administration use cases: network, members, agreement, listings | 8 | TEN-051, TEN-028, TEN-056, TEN-038, TEN-017 | - | HIGH | N |
| TEN-078 | S6 | Network administration use cases: grants and the cross-scope saga | 8 | TEN-077 | - | HIGH | N |
| TEN-079 | S6 | Network and grant administration API | 6 | TEN-078, TEN-043 | - | MEDIUM | N |
| TEN-080 | S6 | Network administration screens | 8 | TEN-079, TEN-068, TEN-069 | - | MEDIUM | P |
| TEN-081 | S6 | Grant approval and sharing transparency screens | 8 | TEN-080 | - | MEDIUM | P |
| TEN-082 | S7 | Network week summary and pressure (capacity-derived only) | 6 | TEN-057, TEN-059, U35, W41 | - | MEDIUM | N |
| TEN-083 | S9 | Operator console screens (last, droppable) | 8 | TEN-075, TEN-047 | - | LOW | P |
| TEN-084 | S9 | Cross-tenant support guard | 4 | TEN-018, TEN-017, TEN-043 | - | MEDIUM | N |
| TEN-085 | S9 | Two-tenant and network end-to-end suite | 8 | TEN-070, TEN-072, TEN-080, TEN-035 | - | MEDIUM | P |
| TEN-086 | S9 | Hazard log rows and tenancy runbooks | 4 | TEN-028, TEN-074, TEN-078 | - | LOW | P |

Scope of each task:

- **TEN-001**: Seam step one: tenancy kernel (scope id with tenant or network kind, bind and current accessors, fixed-message errors), run_query tenant injection and the registration-time $tenant check in warn mode (log and count, do not refuse), global-statement runner and pinned allowlist, single-execution-point architecture test, TENANCY_MODE setting.
- **TEN-002**: Unit of work, connection and health on the scoped transaction: scope captured once at open, one open unit per context, ScopedTx and the Tx alias, DriverIdempotencyStore and ensure_audit_head scoped, ping and migrations on the global path, container wiring.
- **TEN-003**: Test harness step one: a unique tenant per test run, bound-tenant fixtures and teardown guard, tenant-prefixed SequentialIds, two-tenant fixtures, uow_factory and container binding; whole-database wipe and one container per run are unchanged.
- **TEN-004**: Generated two-tenant test over the query registry: probe protocol and completeness test, mirror seed with identical ids in both tenants, digest and invariant checks, fail-closed cases, leaky-query proof, UNCONVERTED ratchet so repository tasks convert ids in parallel.
- **TEN-005**: Composite constraints, index swap and default-tenant backfill (expand step, runs alone): migration runner for parametrised and looped steps, composite constraints and indexes created before the old ones go, Resource (tenantId, key), case reference unique per open case only, backfill in batches, invariant query, migration registry assembled from per-area modules so later tasks never edit the core list, migration-count test derived from the registry.
- **TEN-006**: Tenant domain model (pure): Tenant, TenantConfig with bounds and defaults, TenantContact, TenantSetting registry (typed keys, bounds, safety class), TenantPolicy defaults equal to today constants, lifecycle state machine and activation blockers.
- **TEN-007**: Tenant record: Tenant and TenantNumber registry nodes, TenantDirectory port and Neo4j adapter with the allowlisted global statements (by called number and AccountSid, by host, by Entra directory, list active), secret references and a fake secret store, tenants and secrets on the container, apply_migrations and audit head at start-up.
- **TEN-008**: Mapper: reserve tenantId and sourceTenantId as mapper-owned property names (refused in resources, stripped on read), Identifier, Concept and CodeSystem all tenant-scoped (no shared-node flag).
- **TEN-009**: Resource store: tenantId on all 17 Q-RES statements and the run-time label variants, label-less matches typed and anchored, Q-RES-SHARED-FILL no longer writes shared nodes, dead idempotency pair removed, duplicate IN_SYSTEM edges fixed, version nodes stamped.
- **TEN-010**: Repositories for services, capacity, bookings and cases (P01, P02, P21): stamp the 15 statements, the U02 lock and trailing-confirms statements, per-tenant open references, case reference per open case, probes and two-tenant tests.
- **TEN-011**: Repositories for people, registrations and the scope list (P03, P13): phone lookup inside one tenant, accountRef lookup, one scope list per tenant, role channel statement no longer creates a Concept before the role exists, probes and two-tenant tests.
- **TEN-012**: Repositories for criteria and report and service flags (P04, P14): stamp 21 statements, one current criteria per service per tenant, open flags listed for the bound tenant only, probes and two-tenant tests.
- **TEN-013**: Link token record and store (D26, P10): LinkTokenRecord carries the tenant, global tokenHash lookup returns the tenant only, tenant-stamped reads and writes, pairing codes per tenant.
- **TEN-014**: Contact, credential and device stores (P16): composite keys, device owner lookup inside the tenant, 12 statements stamped, probes and two-tenant tests.
- **TEN-015**: Communication and scheduled-work repositories (P07, P08): stamp 15 statements, provider-id lookup inside the tenant, composite ids, probes and two-tenant tests.
- **TEN-016**: Outbox, idempotency store and processed markers (P06, P15): outbox rows stamped, pending read per tenant, composite idempotency and processed keys, tenant in the fingerprint, probes and two-tenant tests.
- **TEN-017**: Audit chain per scope (P05): AuditHead and sequence per tenant, genesis per new scope with the existing chain kept as the default tenant, hashed text unchanged, AuditRef per tenant, verify_chain per scope, Actor parsing tolerant of entries with no tenant.
- **TEN-018**: REST edge: required Actor.tenant_id and the tenant claim in the back-end token, roles tenant-admin, network-admin and platform-operator, async dependency that binds the scope (threadpool proof), directory status and epoch check, health and metadata as explicit tenant-free routes, route-registry test that every route binds or is allowlisted, replay key per tenant, two-tenant test client.
- **TEN-019**: Tenant-scoped cache (P09, I01, P12): the adapter and the in-memory fake prefix every key, lock, fence and channel with the bound scope and refuse without one, two-tenant contract cases on both.
- **TEN-020**: Event bus tenant property (I02, P08 fake, P12): BusMessage and OutboxMessage carry the tenant, Service Bus application property written and read, in-memory bus parity, two-tenant contract cases, serial marker for emulator tests.
- **TEN-021**: Tenant policy threaded through the board and prompt rules (reply window, ladder, stale limit, pressure, reply policy, correction window, confirm limit), default argument equals today constant so delivered callers are unchanged.
- **TEN-022**: Message templates take tenant fields (sender label, system name, SPOA phone, referral system name); no place names in templates; privacy guard runs after substitution.
- **TEN-023**: Per-tenant derived hash keys for phone hashes, link tokens, code and PIN HMACs (HKDF from the platform secret and the tenant id), hashKeyVersion on the tenant, legacy key for the default tenant only.
- **TEN-024**: ReportCapacity rework (U01): tenant guard, foreign ids answer as not found with no lock taken, performer_role_id validated, tenant in the idempotency fingerprint, configVersion in the audit snapshot, two-tenant use-case tests.
- **TEN-025**: Consumer framework binds the tenant (I04 after delivery): tenant read from the validated message property before the unit of work opens, missing or unknown tenant is a permanent error and dead-letters, tenant of the loaded node compared, runner conversion.
- **TEN-026**: Tenant configuration in the graph: versioned immutable TenantConfigVersion and typed TenantSetting rows, channels, contacts, Entra directory binding and role mapping, retention, draft and approve use cases with a second approver for clinical settings, configuration read port used by use cases and templates.
- **TEN-027**: Migrate the in-flight use cases after delivery (U02, U03): per-tenant link host from configuration, link token record with the tenant, tenant-bound lock and trailing-count statements, derived keys tenant-safe, use-case differential test over every delivered use case with a held-lock timing test.
- **TEN-028**: Tenant provisioning: CreateTenant and ActivateTenant, provision_scope (audit head and genesis, scope list, seeded recurring jobs registry), activation blockers, first administrator invitation and the provision_tenant script, active-tenant list for workers.
- **TEN-029**: Cross-tenant reference matrix: every relationship type with its source in tenant A and target in tenant B is refused with the same body as a missing target and writes nothing; tenant-mode placeholders refused where no explicit existence check exists.
- **TEN-030**: Seam step two: flip TENANCY_MODE to enforce (unbound execution and unstamped statements refused), UNCONVERTED set asserted empty, reviewed mutant per repository, decision recorded; from then the full tenancy rules apply to every task.
- **TEN-031**: Start-up and daily invariant check: counts nodes with no tenantId (outside registry labels) and relationships joining two scopes, fails loudly and degrades the board, per-tenant service-count reconciliation, CI gate.
- **TEN-032**: Contract step (runs alone): drop the superseded single-property constraints and indexes after one clean run; link_token_hash stays global.
- **TEN-033**: Test harness step two (a): tenant-scoped wipe, count_nodes, node_props and write helpers, run tenant and network scope created per run, orphan-tenant sweeper, tenant-aware seed layer, scoped round-trip helpers.
- **TEN-034**: Test harness step two (b): attached mode on one shared Neo4j, schema and lifecycle markers, own-container fixture, connection-recovery and restart tests moved to exclusive runs, cross-process migration lock.
- **TEN-035**: Test harness step two (c): parallel test runs (xdist, worker tenants, two-phase make target), Redis and Service Bus serial markers, CI services or marker split, front-end e2e port per run, builder and verifier briefs corrected (parallel runs now allowed).
- **TEN-036**: Network domain model and grant rules (pure): Network, membership, grant, agreement reference and version, listing status including suspended, transition tables, effective window, two approvals, version bump, fail closed; network enums.
- **TEN-037**: Scope kinds in the seam: network statements declare scopes, label partition lint (a tenant statement cannot name a network label and the reverse), kind check in run_query, read-only unit of work, nested-unit refusal.
- **TEN-038**: Network domain events and topic: network, membership, agreement, grant and projection events, ServiceDirectoryChanged with source, network.events topic, documented payload exception for the projection message.
- **TEN-039**: Board read and live path (U08, U09, R06): wall_actor and system_actor per tenant, board cache key by audience, projector binds the tenant from the message, SSE subscribes to the caller scope channel only, cross-tenant stream test.
- **TEN-040**: Unauthenticated-edge tenant resolution, part one: one sub-domain per tenant resolved from the host by the directory, public tenant profile route, host-bound binder for every unauthenticated route, fixed refusals, platform-namespace rate limiter for unauthenticated paths.
- **TEN-041**: Unauthenticated-edge tenant resolution, part two: link token, invitation token, device token, pairing code and inbound number with AccountSid resolve to a tenant through allowlisted statements, host and token disagreement is a 404, uniform refusals for unknown, expired, used and suspended, inbound number lookup quarantine.
- **TEN-042**: Per-tenant senders: Twilio router resolves subaccount, sender number and secret reference at send time (I06), receipt parser carries AccountSid, email sender identity per tenant (I09), global twilio and smtp settings removed, recording senders record the tenant.
- **TEN-043**: Token exchange: the back end verifies the Entra sign-in itself and issues the tenant-bound token (the BFF holds no signing secret), host-resolved tenant must be bound to the sign-in directory, roles from the tenant role mapping, operator roles only from the operator directory with a separate audience, first administrator consumes the invitation, Practitioner accountRef.
- **TEN-044**: BFF session and handler rework (W02 after delivery): tenantId in Session with fail-closed unseal, session response with display fields only, withBff rejects tenant, scope and network inputs, private no-store and Vary on every response, cross-tenant answers shown as not found, host-only cookies per tenant host, cookie fake with get.
- **TEN-045**: Front-end foundation guards (W01, F03): fhirFetch no-store and token required except link calls, no tenant header or query ever sent, product-name constant and neutral title and description, root page and wall placeholder without place names.
- **TEN-046**: Tenant-bound CSRF token and a separate link CSRF cookie so opening a link never rotates a staff token (settles the W04 and L01 disagreement).
- **TEN-047**: Front-end test harness: tenants fixture with A, B, a non-member C and a network with overlapping ids, tenant-aware MSW factories, bearer-claim leak canary, generated test that every BFF route answers 404 across tenants, Playwright projects per tenant host.
- **TEN-048**: Front-end guard rails: lint and repository-scan tests (no use cache, unstable_cache, revalidate or force-static under app, no NEXT_PUBLIC tenant configuration, no direct localStorage, no place names or SPOA phone literals, no back-end fetch outside lib/fhir).
- **TEN-049**: Tenant profile and copy layer: server-only profile fetch per host with a short TTL, copy parameters from tenant fields, TenantHeader, SPOA phone and support sharing flag read from the profile (environment variables removed).
- **TEN-050**: Browser state wipe: tenant-keyed local storage helper, sign-out and unpair wipe (caches, push subscription, Clear-Site-Data, hard navigation), back-forward cache guard.
- **TEN-051**: Network registry: Network, NetworkMembership, Grant and listing nodes and constraints, global statements pinned on the allowlist, repositories and ports, network settings (system name, pathway name, time zone), a network scope id that can never equal a tenant id.
- **TEN-052**: Projection allowlist and privacy guard: frozen DTOs with exactly the allowed fields, pure builders (profile subset, latest report, confirmed count, reply window), compute_status inputs helper, allowlist version, directory source property, guard on every string, property-level tests.
- **TEN-053**: Network-scope projection repository: Projected service, opening hour, location, capacity, criteria, source and cursor nodes with composite constraints, upserts that match an active grant and take its lock first, end and mark-left statements, one probe each.
- **TEN-054**: Network projector core: producers read in the member scope and build the DTO, apply step writes in the network scope as a second unit of work, grant and membership gate, ordering by source version, idempotent, backfill on activation.
- **TEN-055**: Projection transport: projection.work queue, network-projector subscriptions on capacity, criteria and registration events, runner two-scope handler, in-memory bus parity, contract cases.
- **TEN-056**: Leave and grant-end semantics: end statements, source markers, live and history reads, boundary and heartbeat projection with validUntil, periodic reprojection, revoked-grant leak check job, race test (late projection after the end writes nothing).
- **TEN-057**: Network read use cases: QueryNetworkBoard, network pressure, directory and criteria reads bound to the network scope after the membership, role and grant check, staleness degrade (validUntil, heartbeat, age from the source time), non-member answers as not found, live and history views.
- **TEN-058**: Network board projector and cache: per-network key and channel written by the projector, event-driven invalidation on grant and membership change, per-network audience key.
- **TEN-059**: Network API: networks claim as a hint, membership re-check, network directory and criteria routes, network stream with periodic membership re-check and scope-ended message, wall device checks, 404 for non-members.
- **TEN-060**: Network test fixtures and the generated test extended to three scopes: owner, three members and an outsider, grants builder, run_projector, scope dimension on probes, widened invariants, tenant-delete-leaves-network test.
- **TEN-061**: Two-member network tests, part one: grant lifecycle (dual approval, window, end by grantor, scope separation), leave and history, re-join, concurrency between end and projection, stale projection reads Not updated.
- **TEN-062**: Two-member network tests, part two: projection privacy sentinel scan of every property, label and relationship allowlist, single-scope unit of work, role matrix and wall device checks, owner has no read of members, stream and key isolation.
- **TEN-063**: Network screens specification for the UI (no snapshot edit): wireframes and wording for the network board, administration, grant approval, wall control and unavailable states, scope header and organisation label.
- **TEN-064**: Tenant policy threaded through the remaining rules (booking windows, report flags, multi-service grouping, criteria reminders, alerts defaults, clinical take timeout, re-verify days), bounds enforced, defaults equal today constants.
- **TEN-065**: Time zone stored per tenant and network (allow-list Europe/London) and passed explicitly into the five modules that read the London constant; re-verify day count reads 30 or fewer.
- **TEN-066**: Bank holiday calendar per nation as shared reference data, tenant holidayRegion, per-service closure windows honoured by opening hours, the schedule and the missed-report ladder (new defect fix, before the pilot).
- **TEN-067**: Wall screen board scope setting (backend): device boardScope and network id, PUT board-scope by the tenant administrator with If-Match, scope decided on the server for the board and the stream, membership re-check, fall back to the tenant board with a banner flag.
- **TEN-068**: BFF network scope: /api/bff/network route family and network pages skeleton, availability check per call, network stream relay, non-member and ended-grant tests.
- **TEN-069**: Scope and attribution components using existing tokens: ScopeHeader, ScopeSwitch (two routes), OrgLabel, own-organisation marker, read-only note, scope banner tone.
- **TEN-070**: Network board UI: network board page, organisation filter, unavailable states (not a member, grant ended, member left), scope-keyed last known, and the network variants of the wall board, advisor home, options rows, shift-lead counts, exec home and map that their own tasks did not deliver.
- **TEN-071**: Network directory and criteria views: read-only list and detail of member services and their current criteria, organisation labels, phone-to-confirm wording.
- **TEN-072**: Wall screen administration: screen list, which-board control, unpair and re-pair, claim confirmation naming the tenant, 401 clears the board and returns to pairing, last known keyed by scope with no silent fallback.
- **TEN-073**: Tenant suspend and resume: suspend modes, epoch increment so tokens stop within the cache time, relay and consumers skip a suspended tenant, board and network degrade to Not updated, resume reschedules the next prompt per service and emits StatusChanged.
- **TEN-074**: Tenant offboarding and purge: 30-day offboarding with read-only mode, export package with manifest hashes, network membership ended, number quarantine of 90 days, purge by two operators with typed slug and dry-run counts, batched delete by tenantId, Redis prefix delete, tombstone, retention set before activation.
- **TEN-075**: Operator and tenant-administrator API: platform tenant routes (create, activate, suspend, resume, offboard, export, purge), tenant configuration versions, users and roles, operator access log, tenant networks.
- **TEN-076**: Tenant administration screens: configuration versions with diff and approval, channels read-only, Entra mapping, retention, users and roles, operator access log, wall screen mode list.
- **TEN-077**: Network administration use cases, part one: create network (scope, audit head, genesis), add member, accept agreement version, leave and remove, record agreement reference and version, listing admission and suspension by the network owner, both audit trails.
- **TEN-078**: Network administration use cases, part two: propose, approve (grantor administrator and network owner), change by new version, end by the grantor, lapse on leave, saga across the two scopes with the registry write last and idempotent retries.
- **TEN-079**: Network and grant administration API: members, agreement, grants (request, approve, end), listings, projection status, two-person rule, grants authoritative in the grantor scope.
- **TEN-080**: Network administration screens: members, add and end membership, agreement reference and version, grants overview with owner approval, listing admission and suspension, projection health, history.
- **TEN-081**: Grant approval and sharing transparency for a member administrator: pending grants with the exact list of fields rendered from the allowlist, approve, decline, end, what stays after ending, who data is shared with.
- **TEN-082**: Network week summary and pressure: capacity-derived measures only (status counts, on-time updates, pressure over time), small groups suppressed, per-member breakdown hidden, route and exec variant.
- **TEN-083**: Operator console, last and droppable: sign-in from the operator directory only, tenant list and detail, create wizard with activation checklist, suspend, offboard, export and purge dialogs.
- **TEN-084**: Cross-tenant support guard: deny by default, one tenant and one hour per access opened by a code issued by that tenant administrator, platform roles only from the operator directory, audit entries in the tenant chain and the platform chain, no standing role.
- **TEN-085**: Two-tenant and network end-to-end suite: staff isolation, link opened in another tenant host, wall pairing and board change, grant ended while the network board shows, sign-out wipe, network read-only, synthetic checks in a dedicated tenant outside every network.
- **TEN-086**: Hazard log rows for the tenancy and network hazards (each with its control and verifying test), tenant onboarding, suspension, offboarding, number quarantine and lost-phone runbooks.

## 3. Wave plan, interleaved with the remaining feature work

### 3.1 Rules used to build the waves

- A wave is up to four tasks started together. A task starts in the wave after the last wave that holds one of its dependencies. The plan covers all 223 undelivered tasks: 137 feature tasks (the not-started ones plus those in flight) and the 86 TEN tasks.
- Feature tasks also wait for the tenancy tasks their amended prompt needs (the sweep column "Depends on"): `SEAM` means the generated two-tenant test and harness step one (TEN-004); `SCHEMA` TEN-005; `AUTH` the REST edge TEN-018, and for the unauthenticated entries (L01, L02, U10, R15, U24, U25, R11, U32, W08, W23, W33, W55, R13) the token resolvers TEN-041; `CONFIG` the tenant configuration TEN-026 (front end: the profile layer TEN-049); `LIFECYCLE` provisioning TEN-028. Feature routes (epic R) also wait for the edge. These extra dependencies are listed per task in 3.4 and are not written into `tasks.json`.
- **[N]** marks a wave with at least one task that runs Neo4j tests, **[P]** a wave with none. Until harness step two has landed (TEN-034, in wave 16) every [N] run queues behind the machine-wide lock, so a wave holds at most three [N] tasks and the fourth slot is pure work; from wave 17 runs may overlap on the shared instance, each in its own tenant.
- **Schema-changing tasks run alone**: TEN-005 (composite constraints and backfill) and TEN-032 (contract migration) share their wave only with [P] tasks that never touch the database.
- The seam lands in two steps: TEN-001 (warn mode: log and count unscoped statements, nothing refused) in wave 1, and TEN-030 (enforce) in wave 11, after every repository, the audit chain, the outbox, the REST edge and the consumer binding are migrated. Flipping to enforce is recorded as its own decision, from which the skill's full rules apply (DEC-134 item 12).
- In flight, kept on the current model: U02, U03 and I04 finish first (wave 1), then I09; W02 has been delivered since the sweep, so its tenant rework is TEN-044. They are migrated afterwards by TEN-027 (U02, U03), TEN-025 (I04) and TEN-042 (I09 email sender).
- A deviation from the sweep: G's wave 3 says that once the harness binds a test tenant "every run has its own tenant so Neo4j runs can be parallel". That is not true while repositories still write unstamped nodes and the old single-property constraints exist. Parallel runs on one Neo4j start in the wave after TEN-034.
- Pure work ([P]: domain rules, templates, cache and bus fakes, front end) fills the fourth slot while the Neo4j queue is serial. The network UI variants are built by the amended W-prompts when their dependencies allow and otherwise absorbed by TEN-070, so a slow network chain never stalls Milestone A or B.

### 3.2 The waves

| Wave | Needs | Tasks |
|---|---|---|
| 1 | [N] serial, seam step one | TEN-001 Tenancy seam step one: tenant context, run_query binding and registration c... (8h)<br>U02 ConfirmCapacity use case (3h) (in flight, current model)<br>I04 Idempotent message consumer framework (4h) (in flight, current model)<br>U03 SendPrompts use case (one service) (4h) (in flight, current model) |
| 2 | [N] serial | I09 Email adapter (SMTP) with HTML and text bodies (3h) (in flight, current model)<br>TEN-002 Unit of work, connection and health on the scoped transaction (reworks P06,... (6h)<br>TEN-006 Tenant domain model, configuration bounds, policy defaults and lifecycle st... (7h)<br>TEN-019 Tenant-scoped cache keys, locks and channels in the adapter and the fake (r... (6h) |
| 3 | [N] serial | TEN-003 Test harness step one: tenant per run, bound-tenant fixtures, tenant-prefix... (6h)<br>TEN-020 Service Bus tenant property and in-memory bus parity (reworks I02, P08, P12) (6h)<br>TEN-036 Network domain model and grant rules (pure) (6h)<br>TEN-021 Tenant policy threaded through board and prompt rules (reworks D04, D05, D0... (7h) |
| 4 | [N] serial | TEN-004 Generated two-tenant isolation test over the query registry, with the uncon... (8h)<br>TEN-022 Message templates take tenant fields; no place names (reworks D15, D16, D17) (4h)<br>TEN-038 Network domain events and topic (4h)<br>TEN-063 Network screens specification for the UI (4h) |
| 5 | [N] serial, schema alone | TEN-005 Composite constraints, index swap and default-tenant backfill (runs alone) (8h)<br>TEN-052 Projection allowlist, DTOs and privacy guard (reworks D17) (8h)<br>O01 Backend OpenTelemetry baseline (4h)<br>TEN-064 Tenant policy threaded through booking, flag, grouping, criteria, alert and... (8h) |
| 6 | [N] serial | TEN-008 Mapper reserves tenantId; Concept, CodeSystem and Identifier tenant-scoped... (3h)<br>TEN-007 Tenant record, TenantDirectory, global statement allowlist, secret referenc... (8h)<br>TEN-017 Audit chain per scope with per-scope genesis (reworks P05) (8h)<br>TEN-016 Outbox, idempotency and processed markers tenant-scoped (reworks P06, P15) (6h) |
| 7 | [N] serial | TEN-009 Resource store statements stamped and anchored (reworks G05) (8h)<br>TEN-018 REST edge: tenant claim, Actor.tenant_id, roles, scope binding dependency (... (8h)<br>TEN-013 Link token record and store carry the tenant (reworks D26, P10) (5h)<br>TEN-065 Time zone per tenant and network passed explicitly into the time rules (4h) |
| 8 | [N] serial | TEN-010 Service, capacity, booking and case repositories tenant-scoped (reworks P01... (7h)<br>TEN-011 Person, registration and scope-list repositories tenant-scoped (reworks P03... (8h)<br>TEN-012 Criteria and flag repositories tenant-scoped (reworks P04, P14) (7h)<br>TEN-023 Per-tenant derived hash and token keys (3h) |
| 9 | [N] serial | TEN-015 Communication and scheduled-work repositories tenant-scoped (reworks P07, P08) (5h)<br>TEN-024 ReportCapacity rework: tenant guard, performer validation, fingerprint (rew... (6h)<br>TEN-014 Contact, credential and device stores tenant-scoped (reworks P16) (5h)<br>R16 Pathways Dx code lookup endpoint (2h) |
| 10 | [N] serial | TEN-029 Cross-tenant reference matrix test and placeholder refusal (5h)<br>TEN-025 Consumer framework binds and verifies the tenant (I04 after delivery) (4h)<br>TEN-026 Tenant configuration versions, channels, contacts, directory binding and re... (8h)<br>TEN-066 Bank holiday calendar and service closures (5h) |
| 11 | [N] serial, seam step two | TEN-030 Tenancy seam step two: enforce mode, ratchet empty, mutant evidence (6h)<br>U06 Missed-report ladder handlers (4.5h)<br>TEN-027 Migrate U02 and U03 after delivery; use-case differential and held-lock test (6h)<br>TEN-042 Per-tenant Twilio and email senders (reworks I06; I09 after delivery) (7h) |
| 12 | [N] serial | TEN-037 Seam: network scope kind, label partition lint, read-only and nested-unit r... (5h)<br>I05 Scheduled work consumer (4h)<br>TEN-028 Tenant provisioning: create, activate, provision scope, first administrator (8h)<br>I11 Local postcode centroids and interim travel-time adapter (3h) |
| 13 | [N] serial | TEN-031 Start-up and daily invariant check for nodes without a tenantId (3h)<br>TEN-051 Network registry: Network, membership, grant and listing nodes, repositorie... (8h)<br>TEN-040 Unauthenticated edge: host-based tenant resolution, public profile, rate li... (6h)<br>S01 Browser security headers and CSP (2h) |
| 14 | [N] serial, schema alone | TEN-032 Contract migration: drop superseded single-property constraints (runs alone) (3h)<br>I12 OS Places geocoder and ODS terminology check adapters (3h)<br>W32 PWA manifest, service worker and offline shell (4h)<br>I13 Redis sessions, attempt counters and rate limits (6h) |
| 15 | [N] serial | TEN-033 Test harness step two (a): tenant-scoped wipe, helpers, sweeper, seed layer (8h)<br>TEN-053 Network-scope projection repository and constraints (8h)<br>TEN-039 Board projector, query board and SSE stream per tenant (reworks U08, U09, R06) (7h)<br>O07 TelemetryQuery port and Azure Monitor adapter (5.5h) |
| 16 | [N] serial | TEN-034 Test harness step two (b): shared Neo4j attached mode, markers, exclusive r... (8h)<br>TEN-043 Back-end token exchange: the back end issues the tenant-bound token (7h)<br>U07 Raise report flags when reports break rules (3.5h)<br>O04 OpenTelemetry Collector with attribute allow-list (4h) |
| 17 | [N] shared | TEN-035 Test harness step two (c): parallel runs, CI, serial markers, briefs corrected (8h)<br>TEN-054 Network projector core: producers and apply step in two units of work (8h)<br>I03 Outbox relay worker (5.5h)<br>TEN-044 BFF session and handler rework: tenant in session, no-store, input guard (r... (8h) |
| 18 | [N] shared | U05 HandleInboundText use case: capacity replies (5.5h)<br>U04 Grouped prompts for multi-service phones (3.5h)<br>TEN-041 Unauthenticated edge: link, invitation, device, pairing and inbound-number... (5h)<br>TEN-056 Leave and grant-end semantics, boundary projection, reconciliation (6h) |
| 19 | [N] shared | TEN-045 Front-end foundation guards (reworks W01, F03) (4h)<br>TEN-057 Network read use cases with staleness degrade (8h)<br>TEN-049 Tenant profile and copy layer; remove global SPOA phone variable (7h)<br>U10 PairWallScreen use case (6h) |
| 20 | [N] shared | TEN-047 Front-end tenancy test harness and leak canary (8h)<br>R05 $board and $confirm-capacity operations (5.5h)<br>TEN-058 Network board projector, cache keys and channel (4h)<br>R15 Wall screen pairing endpoints (3.5h) |
| 21 | [N] shared | TEN-059 Network API: board, directory, criteria, stream, membership claims (6h)<br>L01 Capacity link API (6.5h)<br>TEN-050 Browser state wipe on sign-out and unpair (5h)<br>W05 Wall board page (5.5h) |
| 22 | [N] shared | TEN-060 Network test fixtures and generated test extended to three scopes (8h)<br>W04 Capacity link pages (4h)<br>W06 Wall board live updates and Last known (4.5h)<br>I07 SMS inbound webhook (7h) |
| 23 | [N] shared | TEN-061 Two-member network tests: grant lifecycle, leave, history, concurrency (8h)<br>TEN-062 Two-member network tests: privacy scan, scope binding, roles, isolation of... (8h)<br>R04 HealthcareService and capacity Observation endpoints (5h)<br>TEN-055 Projection transport: queue, subscriptions, two-scope runner (reworks F04) (5h) |
| 24 | [N] shared | I08 Reply processor and delivery receipt consumers (4.5h)<br>I10 Outbound message senders (messages.outbound consumers) (4.5h)<br>TEN-048 Front-end guard rails: lint and repository scans (4h)<br>W08 Wall screen pairing pages (4h) |
| 25 | [N] shared | W07 Wall board variants: pressure, out of hours, pending (3.5h)<br>TEN-046 Tenant-bound CSRF and separate link CSRF cookie (3h)<br>U11 OpenCase use case (3.5h)<br>W09 Staff sign-in with Entra ID and role guard (8h) |
| 26 | [N] shared | U12 FilterOptions use case with audit snapshot (6.5h)<br>U13 Advisor phoned and declined-despite-capacity (3.5h)<br>U14 RecordOutcome and close case (3.5h)<br>TEN-068 BFF network scope: routes, availability check, stream relay (6h) |
| 27 | [N] shared | R07 Case endpoints and $filter-options (5.5h)<br>W10 Advisor home and call step header (3.5h)<br>TEN-069 Scope header and organisation label components (4h)<br>U16 Change reporter number and cover (4h) |
| 28 | [N] shared | W11 Patient needs form (4h)<br>U15 Lead-assisted service set-up (pilot) (5.5h)<br>TEN-067 Wall screen board scope setting (backend) (3h)<br>TEN-070 Network board UI and unavailable states (8h) |
| 29 | [N] shared | W13 Options list (6h)<br>TEN-072 Wall screen administration and last-known by scope (6h)<br>R08 Lead endpoints: service set-up and reporter numbers (4h)<br>G11 Criteria hard-filter and history queries (6.5h) |
| 30 | [P] | W15 Record outcome, SystmOne summary and call closed (4h)<br>W17 Shift lead page: chasing, system now, covering (4.5h)<br>TEN-071 Network directory and criteria views (5h)<br>W14 Criteria, I phoned and They declined dialogs (4.5h) |
| 31 | [N] shared | W16 No service fits state (2h)<br>W12 Referrer score pickers (3h)<br>W18 Shift lead: add service and change number forms (pilot) (3h)<br>U17 RequestBooking use case (5.5h) |
| 32 | [N] shared | U18 RespondToBooking use case (4.5h)<br>U20 CancelBooking use case (2.5h)<br>U19 Booking timers: phone prompt and expiry (3.5h)<br>U25 Text code request and verification (7h) |
| 33 | [N] shared | U21 WithdrawBooking and NotReached use cases (4.5h)<br>U22 Booking replies by text (4.5h)<br>U26 Registration draft and submit (4.5h)<br>TEN-077 Network administration use cases: network, members, agreement, listings (8h) |
| 34 | [N] shared | L02 Booking link API (4.5h)<br>R09 Booking Task endpoints, $respond and service projection (5h)<br>U28 Review registration: automatic checks, call-back, scope (6h)<br>U23 Scope list management (4.5h) |
| 35 | [N] shared | W19 Booking link page for services (3.5h)<br>W20 Advisor booking card states, live (4h)<br>R17 Advisor acknowledgement of a withdrawn booking (2.5h)<br>U30 ChangeCriteria, ApproveCriteria and ConfirmCriteria (4.5h) |
| 36 | [N] shared | W22 Service booking exceptions: withdraw, not reached, cancelled (4.5h)<br>W21 Advisor cancel booking and withdrawal alert (3h)<br>TEN-078 Network administration use cases: grants and the cross-scope saga (8h)<br>U24 Invite a service reporter (5h) |
| 37 | [N] shared | U29 Approve, send back, test prompt and go live (4.5h)<br>TEN-079 Network and grant administration API (6h)<br>TEN-073 Tenant suspend and resume (6h)<br>U27 Registration persistence as one FHIR transaction (5.5h) |
| 38 | [N] shared | R10 Registration, scope and criteria endpoints (5h)<br>TEN-080 Network administration screens (8h)<br>TEN-075 Operator and tenant-administrator API routes (6h)<br>TEN-074 Tenant offboarding, export and purge (8h) |
| 39 | [P] | W23 Registration: sign in and start (5.5h)<br>W28 Reviewer: scope list, queue and overview (4h)<br>TEN-076 Tenant administration screens (8h)<br>TEN-081 Grant approval and sharing transparency screens (8h) |
| 40 | [N] shared | W54 Registration: organisation step and error summary (3h)<br>W30 Criteria owner: review, confirm, change, preview, send (4h)<br>U31 Criteria review reminders and overdue flag (5h)<br>W29 Reviewer: call-back, scope, decide and go live (4.5h) |
| 41 | [N] shared | W25 Registration: service and criteria step (4h)<br>W24 Registration: location step with address lookup (3h)<br>W31 Criteria second approval, history and overdue (3h)<br>P19 Push subscription repository on Neo4j (3h) |
| 42 | [N] shared | W26 Registration: capacity reporting, review, submitted, my services (4h)<br>P17 Alert subscription and alert repositories on Neo4j (4.5h)<br>U32 PIN set, sign-in, lock, reset and 30-day check (5.5h)<br>I14 Web Push adapter and notification consent (5h) |
| 43 | [N] shared | W27 Applicant status pages (3h)<br>U33 SubscribeAlert use case (3.5h)<br>R11 Reporter identity and push endpoints (5.5h)<br>U35 Week summary for COO and ICB (5h) |
| 44 | [N] shared | U34 Alert evaluator, acknowledge, snooze and escalation (6h)<br>W33 Reporter set-up: welcome, number check, channel (5h)<br>P18 Clinical request repository on Neo4j (4h)<br>U37 RemovePerson, sign out everywhere and lost phone (5h) |
| 45 | [N] shared | R12 Subscription and alert endpoints (4h)<br>W34 Reporter set-up: home screen, notifications, PIN (4h)<br>P20 Service move and protected text stores on Neo4j (4.5h)<br>U40 Clinical advice requests (6h) |
| 46 | [N] shared | W39 Exec set-up: alerts, quiet hours, escalation (4h)<br>W35 Reporter app: PIN entry, respond, confirmation (4h)<br>U42 Audit replay of what the advisor saw (4.5h)<br>U38 Move a service between phones (4h) |
| 47 | [P] | W40 Exec home, service detail and alerts (5.5h)<br>W37 Reporter app: recovery and settings (4h)<br>W38 Reporter app: several services on one phone (4h)<br>W36 Reporter app: booking decision (3.5h) |
| 48 | [N] shared | W41 Exec week summary (3.5h)<br>U41 Safety concern and problem report (4h)<br>U36 SuspendService and ResumeService (3.5h)<br>U39 Resolve report flags (2.5h) |
| 49 | [N] shared | TEN-082 Network week summary and pressure (capacity-derived only) (6h)<br>R13 Lead, clinical and safety endpoints (5h)<br>R14 Profiles, $validate and the validator adapter (4h)<br>TEN-084 Cross-tenant support guard (4h) |
| 50 | [P] | W44 Clinical advisor screens (4h)<br>W46 Help: safety concern, problem report, share session (3h)<br>W55 Reporter: lost phone and sign out everywhere (4.5h)<br>W42 Lead: suspend, resume, remove, reports to check (4h) |
| 51 | [N] shared | W43 Lead: phones and services, invite and track set-up (4h)<br>W45 Advisor: ask a clinical advisor, wired (2h)<br>W47 Lead: audit replay screen (2h)<br>O06 Support codes and support access audit (7h) |
| 52 | [N] shared | R18 Support code and console endpoints (5.5h)<br>O08 Daily telemetry aggregates job (6.5h)<br>O02 Browser telemetry module and element ids (4.5h)<br>TEN-083 Operator console screens (last, droppable) (8h) |
| 53 | [N] shared | W48 Console: find session, timeline and trace (6h)<br>TEN-085 Two-tenant and network end-to-end suite (8h)<br>O09 Synthetic journey checks (4.5h)<br>O03 Friction rules engine (4h) |
| 54 | [P] | W49 Console: funnels, paths, friction, performance, releases (5.5h)<br>TEN-086 Hazard log rows and tenancy runbooks (4h)<br>W56 Help: share my session (support code) (3h)<br>O05 Telemetry schema scan for free text (2h) |
| 55 | [N] shared | I15 Routing travel-time adapter (once the engine is chosen) (4.5h)<br>U43 Planning analysis from decision snapshots (5.5h)<br>G13 RDF (Turtle) export from the mapper (5h)<br>W53 Training lessons and practice mode (3.5h) |
| 56 | [P] | W50 Map view and travel details (5h)<br>W51 Planning view (4h)<br>W52 Product tour by role (3h) |

First four waves in short: wave 1 is TEN-001 SEAM1, U02, I04, U03; wave 2 is I09, TEN-002 UOW, TEN-006 TENDOM, TEN-019 CACHE; wave 3 is TEN-003 HARN1, TEN-020 EVENTBUS, TEN-036 NETDOM, TEN-021 POLICYA; wave 4 is TEN-004 GEN, TEN-022 TEMPLATES, TEN-038 NETEVENTS, TEN-063 NETSPEC.

### 3.3 Milestones in the wave plan

| Point | Wave |
|---|---|
| Seam step one (warn) | 1 |
| Composite constraints and backfill (alone) | 5 |
| Every repository, audit chain and outbox migrated | 9 |
| Seam step two (enforce) | 11 |
| Contract migration (alone) | 14 |
| Shared Neo4j and parallel test runs (harness step two b) | 16 |
| Unauthenticated-edge resolvers | 18 |
| Outbox relay I03 | 17 |
| Wall board W05 (Milestone A area) | 21 |
| Network projector | 17 |
| Network API | 21 |
| Advisor call complete (U14, W16) | 31 |
| Booking inside one tenant complete (U22, W22) | 36 |
| Registration complete (U29, W31) | 41 |
| Network administration screens | 38 |
| Last wave | 56 |

### 3.4 Extra dependencies given to feature tasks (from the sweep, or because the task edits a file a TEN task edits; not written into tasks.json)

| Feature task | Also waits for |
|---|---|
| G11 | TEN-004 GEN, TEN-057 NETREAD |
| G13 | TEN-004 GEN, TEN-005 SCHEMA |
| I03 | TEN-004 GEN, TEN-016 REPO_OUTBOX, TEN-020 EVENTBUS, TEN-028 PROVISION |
| I05 | TEN-004 GEN, TEN-025 CONSUMER |
| I07 | TEN-004 GEN, TEN-026 TENCFG, TEN-041 EDGE_TOKENS, TEN-042 SENDERS |
| I08 | TEN-004 GEN, TEN-025 CONSUMER, TEN-042 SENDERS |
| I10 | TEN-004 GEN, TEN-025 CONSUMER, TEN-026 TENCFG, TEN-042 SENDERS |
| I13 | TEN-004 GEN, TEN-018 EDGE, TEN-019 CACHE |
| I14 | TEN-026 TENCFG |
| I15 | TEN-004 GEN |
| L01 | TEN-004 GEN, TEN-018 EDGE, TEN-041 EDGE_TOKENS |
| L02 | TEN-004 GEN, TEN-018 EDGE, TEN-041 EDGE_TOKENS |
| O01 | TEN-004 GEN |
| O02 | TEN-004 GEN, TEN-047 FEHARN |
| O04 | TEN-004 GEN |
| O06 | TEN-004 GEN, TEN-018 EDGE, TEN-028 PROVISION, TEN-084 SUPPORTGUARD |
| O07 | TEN-004 GEN |
| O08 | TEN-004 GEN |
| O09 | TEN-004 GEN, TEN-028 PROVISION |
| P17 | TEN-004 GEN, TEN-005 SCHEMA |
| P18 | TEN-004 GEN |
| P19 | TEN-004 GEN, TEN-005 SCHEMA, TEN-042 SENDERS |
| P20 | TEN-004 GEN, TEN-005 SCHEMA |
| R04 | TEN-004 GEN, TEN-018 EDGE |
| R05 | TEN-004 GEN, TEN-018 EDGE, TEN-026 TENCFG, TEN-057 NETREAD |
| R07 | TEN-004 GEN, TEN-018 EDGE, TEN-057 NETREAD |
| R08 | TEN-004 GEN, TEN-018 EDGE |
| R09 | TEN-004 GEN, TEN-018 EDGE |
| R10 | TEN-004 GEN, TEN-018 EDGE, TEN-041 EDGE_TOKENS, TEN-043 EXCHANGE |
| R11 | TEN-004 GEN, TEN-018 EDGE, TEN-026 TENCFG, TEN-041 EDGE_TOKENS |
| R12 | TEN-004 GEN, TEN-018 EDGE |
| R13 | TEN-004 GEN, TEN-018 EDGE, TEN-041 EDGE_TOKENS |
| R14 | TEN-004 GEN, TEN-018 EDGE |
| R15 | TEN-004 GEN, TEN-018 EDGE, TEN-041 EDGE_TOKENS |
| R16 | TEN-004 GEN, TEN-018 EDGE |
| R17 | TEN-004 GEN, TEN-018 EDGE |
| R18 | TEN-004 GEN, TEN-018 EDGE, TEN-084 SUPPORTGUARD |
| U04 | TEN-004 GEN, TEN-027 INFLIGHT |
| U05 | TEN-004 GEN, TEN-026 TENCFG |
| U06 | TEN-004 GEN |
| U07 | TEN-004 GEN, TEN-024 U01REWORK |
| U10 | TEN-004 GEN, TEN-018 EDGE, TEN-041 EDGE_TOKENS |
| U11 | TEN-004 GEN |
| U12 | TEN-004 GEN, TEN-057 NETREAD |
| U13 | TEN-004 GEN |
| U14 | TEN-004 GEN |
| U15 | TEN-004 GEN, TEN-026 TENCFG, TEN-038 NETEVENTS |
| U16 | TEN-004 GEN |
| U17 | TEN-004 GEN, TEN-026 TENCFG |
| U18 | TEN-004 GEN |
| U19 | TEN-004 GEN |
| U20 | TEN-004 GEN |
| U21 | TEN-004 GEN |
| U22 | TEN-004 GEN, TEN-026 TENCFG |
| U23 | TEN-004 GEN, TEN-005 SCHEMA, TEN-041 EDGE_TOKENS, TEN-043 EXCHANGE |
| U24 | TEN-004 GEN, TEN-018 EDGE, TEN-026 TENCFG, TEN-041 EDGE_TOKENS |
| U25 | TEN-004 GEN, TEN-018 EDGE, TEN-026 TENCFG, TEN-041 EDGE_TOKENS |
| U26 | TEN-004 GEN, TEN-038 NETEVENTS |
| U27 | TEN-004 GEN, TEN-005 SCHEMA, TEN-011 REPO_PEOPLE, TEN-038 NETEVENTS |
| U28 | TEN-004 GEN, TEN-026 TENCFG |
| U29 | TEN-004 GEN |
| U30 | TEN-004 GEN |
| U31 | TEN-004 GEN, TEN-028 PROVISION |
| U32 | TEN-004 GEN, TEN-018 EDGE, TEN-041 EDGE_TOKENS |
| U33 | TEN-004 GEN |
| U34 | TEN-004 GEN |
| U35 | TEN-004 GEN, TEN-026 TENCFG |
| U36 | TEN-004 GEN |
| U37 | TEN-004 GEN |
| U38 | TEN-004 GEN, TEN-026 TENCFG |
| U39 | TEN-004 GEN |
| U40 | TEN-004 GEN, TEN-026 TENCFG |
| U41 | TEN-004 GEN, TEN-026 TENCFG |
| U42 | TEN-004 GEN |
| U43 | TEN-004 GEN |
| W05 | TEN-044 FE1, TEN-047 FEHARN, TEN-049 FEPROFILE |
| W06 | TEN-044 FE1, TEN-047 FEHARN |
| W07 | TEN-044 FE1, TEN-047 FEHARN |
| W08 | TEN-018 EDGE, TEN-041 EDGE_TOKENS, TEN-044 FE1, TEN-047 FEHARN |
| W09 | TEN-018 EDGE, TEN-043 EXCHANGE, TEN-044 FE1, TEN-047 FEHARN, TEN-049 FEPROFILE |
| W10 | TEN-044 FE1, TEN-047 FEHARN |
| W13 | TEN-044 FE1, TEN-047 FEHARN |
| W14 | TEN-044 FE1, TEN-047 FEHARN |
| W17 | TEN-044 FE1, TEN-047 FEHARN |
| W19 | TEN-044 FE1, TEN-047 FEHARN, TEN-049 FEPROFILE |
| W22 | TEN-044 FE1, TEN-047 FEHARN, TEN-049 FEPROFILE |
| W23 | TEN-018 EDGE, TEN-041 EDGE_TOKENS, TEN-043 EXCHANGE, TEN-044 FE1, TEN-047 FEHARN |
| W29 | TEN-044 FE1, TEN-047 FEHARN, TEN-049 FEPROFILE |
| W33 | TEN-018 EDGE, TEN-041 EDGE_TOKENS, TEN-044 FE1, TEN-047 FEHARN |
| W36 | TEN-044 FE1, TEN-047 FEHARN, TEN-049 FEPROFILE |
| W40 | TEN-044 FE1, TEN-047 FEHARN, TEN-049 FEPROFILE |
| W41 | TEN-044 FE1, TEN-047 FEHARN |
| W48 | TEN-018 EDGE, TEN-044 FE1, TEN-047 FEHARN, TEN-084 SUPPORTGUARD |
| W49 | TEN-004 GEN, TEN-018 EDGE, TEN-044 FE1, TEN-047 FEHARN, TEN-084 SUPPORTGUARD |
| W50 | TEN-044 FE1, TEN-047 FEHARN |
| W53 | TEN-044 FE1, TEN-047 FEHARN, TEN-049 FEPROFILE |
| W55 | TEN-018 EDGE, TEN-041 EDGE_TOKENS, TEN-044 FE1, TEN-047 FEHARN |
| W56 | TEN-084 SUPPORTGUARD |

## 4. Critical path and main risks

### 4.1 Critical path

Longest chain by hours, counting each task's hours plus its amendment hours (139 h): TEN-001 (SEAM1) -> TEN-002 (UOW) -> TEN-003 (HARN1) -> TEN-004 (GEN) -> TEN-005 (SCHEMA) -> TEN-008 (MAPPER) -> TEN-009 (RESSTORE) -> TEN-011 (REPO_PEOPLE) -> TEN-029 (REFMATRIX) -> TEN-030 (ENFORCE) -> TEN-037 (NETSCOPE) -> TEN-051 (NETREG) -> TEN-053 (NETPROJREPO) -> TEN-054 (NETPROJECTOR) -> TEN-056 (NETLEAVE) -> TEN-077 (NETADMIN1) -> TEN-078 (NETADMIN2) -> TEN-079 (NETADMINAPI) -> TEN-080 (FENETADMIN) -> TEN-081 (FESHARING).

- To the end of repository migration and seam step two (66 h): SEAM1 -> UOW -> HARN1 -> GEN -> SCHEMA -> MAPPER -> RESSTORE -> REPO_PEOPLE -> REFMATRIX -> ENFORCE.
- To parallel test runs and CI (96 h): SEAM1 -> UOW -> HARN1 -> GEN -> SCHEMA -> MAPPER -> RESSTORE -> REPO_PEOPLE -> REFMATRIX -> ENFORCE -> INVARIANT -> CONTRACT -> HARN2A -> HARN2B -> HARN2C.
- To the network API (114.5 h): SEAM1 -> UOW -> HARN1 -> GEN -> SCHEMA -> MAPPER -> RESSTORE -> REPO_PEOPLE -> REFMATRIX -> ENFORCE -> NETSCOPE -> NETREG -> NETPROJREPO -> NETPROJECTOR -> NETREAD -> R05 -> NETAPI.
- To network administration (123 h): SEAM1 -> UOW -> HARN1 -> GEN -> SCHEMA -> MAPPER -> RESSTORE -> REPO_PEOPLE -> REFMATRIX -> ENFORCE -> NETSCOPE -> NETREG -> NETPROJREPO -> NETPROJECTOR -> NETLEAVE -> NETADMIN1 -> NETADMIN2 -> NETADMINAPI.

Reading it: the tenant chain up to enforce is about 66 hours and is strictly sequential through the seam, the generated test, the schema step and the resource store; the six repository tasks and the audit chain run side by side but queue on one Neo4j. Everything on the network side (registry, projection repository, projector, leave handling, administration, screens) hangs off enforce and adds roughly 73 hours after it, so network administration is the last tenancy capability to finish. Tenant lifecycle and the front end are off the critical path.

### 4.2 Main risks and mitigations

| Risk | Why | Mitigation |
|---|---|---|
| One statement without `tenantId` leaks silently | Neo4j Community cannot require the property; one of about 124 statements, 13 of them built from Python strings, is enough. | Registration check (warn, then enforce), the generated test with identical ids in both tenants, the unconverted-ids ratchet, one reviewed mutant per repository, the invariant check at start-up and daily (TEN-031), and the cross-tenant reference matrix (TEN-029). |
| The serial Neo4j queue stretches the first waves | Until harness step two every integration run queues; the sweep assumed parallel runs from wave 3. | Keep the first waves to pure work beside a single N task, put the harness steps directly after enforce and the contract migration, and keep unit-level work first in every Neo4j task. |
| Collision with the in-flight branches and F10b | U02, U03 and I04 were written on the single-tenant model and the harness change rebinds every test; F10b edits the same harness files. | U02, U03 and I04 deliver first on the current model; harness step one waits for F10b; tests that seed raw nodes with `CREATE` gain `tenantId` in their repository task; migrations are split per area so later tasks never edit the core list. |
| Cross-cutting edits make merges collide | `Actor.tenant_id` is required, which touches many files; `migrations.py`, `settings.py` and `container.py` are edited by several tasks. | The actor change is one task (TEN-018) that owns every construction site; per-area migration modules; dependency order on shared files is checked mechanically (no two tasks in a wave share a file). |
| Unauthenticated entries (link, invitation, pairing, device, inbound number, text code) can become tenant oracles | They run before any binding and could answer differently for unknown, expired and wrong-tenant. | Host-first resolution (TEN-040), allowlisted statements that return only a tenant id and status (TEN-041), one uniform refusal, a 404 when host and token disagree, a platform-namespace rate limiter, tests per entry. |
| The network projector is new safety-critical code | An over-wide allowlist, a revoked grant that still projects, or a stored status that goes stale shows a confident wrong figure or exposes data. | DTO-only projection with a versioned allowlist, status computed at read time from projected inputs (DEC-134 item 6), `validUntil` and heartbeat degrade, the active-grant match and lock inside the write statement, sentinel and race tests (TEN-060 to TEN-062), and the human-only sign-off of DEC-132 item 9 recorded as references, never as approvals. |
| Network UI prompts depend on a long backend chain | W05, W06, W07, W10, W13, W14, W17, W40 and W50 were amended to build network variants. | They do not wait for the network chain; when it is late they deliver the tenant view and TEN-070 absorbs the variants. |
| Identity cannot be tested against real directories | Entra, Twilio subaccounts and vaults are human-only (DEC-133 item 3). | Fakes for the identity verifier and secret store; each real credential is listed as "needs a real credential at deploy". |
| Estimates | The audits differ by a factor of two (generated test 6 h, 14 h and 28 h). | This plan sizes each task at 2 to 8 hours with tests included; re-estimate after the first four repository tasks. |
| Throughput | 223 undelivered tasks in waves of four give 56 waves whatever the order; the order only decides which capability finishes first. | The order puts the seam, the repositories and the edge first, then Milestone A and B work beside the network chain. |
| Context propagation under the web framework | A synchronous dependency runs in a threadpool, so a context variable set there is lost (audit C). | Proof test in TEN-001 and an async binding dependency with a route-registry test in TEN-018. |

## 5. Which undelivered prompts carry which amendment

Taken from the sweep (section 2 of audit G) and checked against the 95 prompts that now carry the marker `<!-- tenancy-amendment`. The paragraph texts are in the sweep and in those prompts; this plan does not repeat them.

| Amendment | Applies to | Count |
|---|---|---|
| Backend (2a) | G11, G13, L01, L02, O01, O04, O06, O07, O08, O09, P17, P18, P19, P20, R04, R05, R07, R08, R09, R10, R12, R13, R15, R17, R18, U04, U06, U07, U10, U11, U12, U13, U14, U15, U16, U17, U18, U19, U20, U21, U23, U24, U26, U27, U28, U29, U30, U31, U32, U33, U35, U36, U37, U38, U39, U41, U42, U43 | 58 |
| Backend plus Redis, Service Bus and SMS (2a and 2c) | I03, I05, I07, I08, I10, I13, I14, I15, R11, U05, U22, U25, U34, U40 | 14 |
| Front end (2b) | O02, W05, W06, W07, W08, W09, W10, W13, W14, W17, W19, W22, W23, W29, W33, W36, W40, W41, W48, W49, W50, W53, W55 | 23 |

U02, U03, I04 and I09 are not amended (in flight): their migration is TEN-027, TEN-025 and TEN-042. The sweep's 100 AMEND-PROMPT rows are the 95 above plus these four and W02, which has since been delivered.

Follow-up amendments the orchestrator should check, because DEC-134 and DEC-136 postdate the sweep text (listed, not planned as tasks):

| Decision | Prompts to re-read |
|---|---|
| DEC-136 items 1 and 5: no cross-organisation booking, no cross-tenant write; the advisor records the call in their own case as typed snapshot properties | U12, U13, U17 to U22, L02, W13, W14, W19 to W22 |
| DEC-136 item 3: network owner admits the listing and may suspend it; a service is visible only with a grant and an admitted listing | U27, U29, U36, W28, W29, W42 |
| DEC-136 item 4: two approvals inside the provider, no network endorsement | U30, U31, W30, W31 |
| DEC-136 item 8: registration needs two distinct approvers | U28, U29, W29 |
| DEC-136 item 9: alerts and clinical work stay tenant-only; clinical advisers from another organisation hold accounts in the owner tenant | U33, U34, U40, W39, W40, W44 |
| DEC-136 items 6 and 7: operator directory only for platform roles, one session per tenant, accountRef, support code issued by the tenant administrator | W09, O06, R18, W48, W49, W56, U32, I13, R11 |
| DEC-134 item 3 and DEC-136 item 11: one sub-domain per tenant for every web entry, pairing codes unique within a tenant and entered on its host, a link whose host and token disagree is a 404 | L01, L02, U10, R15, W04, W08, W19, W22, W23, W32 to W35, I14 |
| DEC-136 items 12 and 13: per-tenant derived keys, time zone per tenant, bank holidays | U04, U19, U31, U32, W39 |
| DEC-136 item 14: telemetry per tenant, anonymised cross-tenant aggregates only across three or more tenants | O02, O04, O07, O08, W49 |
| DEC-134 item 14: `ENTRA_TENANT_ID` renamed `ENTRA_DIRECTORY_ID`, "Dorset" removed | W09, W05, W29, W40, U28 |

## 6. Defects the audits found that stand regardless of tenancy

| Defect | Source | Recommended home |
|---|---|---|
| Case reference is lifetime-unique over 9,000 values (migration 0022) although the rule is "unique among open cases"; a busy organisation exhausts it | A, B, DEC-134 item 13 | TEN-005: constraint on an open-only property; the case repository sets it at open and clears it at close in TEN-010 |
| `performer_role_id` is accepted without validation in ReportCapacity and ConfirmCapacity and becomes the echo recipient | B | TEN-024 (ReportCapacity); TEN-027 covers ConfirmCapacity once U02 is delivered |
| The network view would show a stored status that goes stale after a service stops reporting (the tenant board recomputes status from time on every read) | B, C, DEC-134 item 6 | TEN-052 (inputs are projected, status computed at read time) and TEN-057 (validUntil and heartbeat degrade) |
| "Dorset" and single-organisation wording in templates, prompts, W05, W40, U28 and the Dorset district default | B, D, F | Templates TEN-022; front end TEN-049; prompts amended by the orchestrator; the district default is removed in the U28 prompt and tenant configuration TEN-026 |
| Element ids that embed dynamic service ids break the telemetry schema scan and cardinality (W38 line 55, W50 line 56) | D | Fix the two prompts now (stable ids, the service id as an attribute); verified by O05 |
| W04 (double-submit cookie) and L01 (token-bound csrfToken) specify two CSRF mechanisms for one page, and the link page overwrites the staff CSRF cookie | D | L01 wins; TEN-046 separates the cookies; amend W04 |
| Artboards `AdvisorDialogsPhone` and `AdvisorFinishPhone` named in W14, W15, W16 and W45 do not exist in the snapshot | D | Record under "Canvas differences" in those tasks (DEC-129); include in the v1.1 canvas refresh |
| `frontend/middleware.ts` (W09, S01) is the deprecated name in Next 16; a check there is only optimistic | D | W09 and S01 use `proxy.ts` and every route handler re-checks |
| U03 stores the one-time link token in plain text in `Communication.payloadText` and the outbox payload (and dead letters keep it) | U03 verification, C | U03 itself, now; not part of the retrofit |
| Every put re-creates `IN_SYSTEM` edges (`CREATE`, not `MERGE`), so reference data accumulates edges | A | TEN-009 |
| `CodeSystem` and `Migration.id` have no unique constraint | A | TEN-005 |
| `Q-ROLE-CHANNEL` creates a Concept before checking the role exists | A | TEN-011 |
| `apply_migrations` and `ensure_audit_head` are not called by the composition root, and there is no process entry point | A, C | TEN-007 (start-up wiring) and TEN-028 (audit head) |
| Bank holidays are modelled nowhere; a service closed on a holiday is prompted and chased | F | TEN-066, before the pilot (S4) |
| Re-verification is 30 days in code (`REVERIFY_EVERY`) and 180 in the rule book | C, F | TEN-064 makes it a bounded setting; the U32 builder settles the default against the rule book |
| `to_e164_uk` and `normalise_uk_mobile` refuse non-UK numbers, which would turn an unknown sender into a 500 in the SMS webhook | C | I07 (amended prompt): an unknown sender gets the fixed empty reply |
| The webhook replay key `diucs:idem:sms:<sid>` sits outside the four key families and is shaped like R03's `idem:<sub>:<key>` | C | I07 (amended prompt): use the cache adapter prefix |
| Successful responses carry no `Cache-Control: no-store`; Next or a CDN could cache across users | D | TEN-044 |
| CI cannot run the Redis, emulator and compose tests (`test_backend_job_runs_full_suite` forbids deselection) | E | TEN-035 (services or marker split) |
| Playwright fixes port 3000 and reuses an existing server, so two e2e sessions race | E | TEN-035 |
| `observability.md` lists 8 roles; the code has 10 and DEC-134 adds 3 | D | Spec reconciliation by the lead developer in the same change (DEC-133 item 4) |
| The decision records say 78 statements and two f-strings; the code has about 124 statements and 13 string-built ones | A | Recorded in DEC-134 item 15; the generated test covers the real registry |

## 7. Still open, with the default this plan assumes

DEC-134 and DEC-136 settle most questions. What remains is small and each has a default so no task waits (DEC-133 item 1).

| Open point | Default |
|---|---|
| Which threshold overrides a tenant may set | The clinical settings of audit F section 6.1 with its bounds (reply window 15 to 60, ladder, stale limit 1 to 4 hours, correction window, confirm limit, flag windows, group window, pressure thresholds), a second approver for a clinical setting, and the configuration version stamped on the ReportCapacity audit snapshot (TEN-021, TEN-064, TEN-026); later use cases stamp it when their prompt says so |
| Retention defaults (activation is blocked until set, DEC-136 item 10) | The builder of TEN-026 records defaults in a decision: audit chain and safety concerns kept until purge, cases cleared at close as the rule book says, communications metadata 2 years, raw telemetry 90 days and aggregates 2 years, all marked assumed |
| Tenant id and network scope id format | Tenant ids `[a-z0-9][a-z0-9-]{1,30}`, immutable; network scope ids start `net-`, which a tenant id may not; both usable in Redis keys and message properties (TEN-001) |
| Entra registration shape | One multi-tenant app registration; the back end checks the sign-in directory against the tenant's bound directory (TEN-043); the operator records the binding |
| How long a suspend takes to bite | At most 60 seconds (directory status and epoch cached that long); staff tokens 8 hours; wall devices use an opaque token resolved per request |
| Is the network owner also a projecting member | Yes, parameterised in the test fixtures; the model does not assume one network (tests create many) |
| Number of organisations and who pays | 10 to 30 in year one (DEC-136 item 15); outside the build |
| Operator console or script | Script first (TEN-028); the console (TEN-083) is last and may be dropped |
| Per-member on-time breakdown for the owner | Not shown unless the agreement says so (DEC-136 item 14) |
| Bank holiday data source | A checked-in reference list per nation generated from the government data set; no runtime fetch (TEN-066) |
| When a member leaves while a wall shows the network board | Falls back to the tenant board with a visible banner (TEN-067, TEN-072) |
| Neo4j edition | Community; the invariant check (TEN-031) is the compensating control; the driver stays selectable per tenant at the binding point |
| Hazard rows | H-T and H-N rows are added to the hazard log as the tasks land, and consolidated by TEN-086 |
| Human-only items (agreement, DPIA, allowlist and grant approval, Twilio, Entra, vault) | Recorded as references and "prepared, not externally certified" (DEC-133 item 2); never block a task |

