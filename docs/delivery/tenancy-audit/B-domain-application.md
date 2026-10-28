# Tenancy audit B: domain and application layers

Scope: `backend/src/diucs/domain/**` and `backend/src/diucs/application/**` on `main` (65c7da2, which is DEC-131 on top of the audited 1ac81b9), plus what the four unmerged task branches add under those paths. Read-only audit. Nothing was run. Decisions applied: DEC-130, DEC-131 (arrived while the audit was in progress, so sections 2, 3 and 5 reflect it), DEC-001, DEC-007, DEC-032, DEC-104, DEC-106, DEC-099, DEC-100.

Notes on sources:
- The unmerged branches exist locally as `task/U02-confirm-capacity`, `task/U03-send-prompts`, `task/I04-consumer-framework`, `task/W02-bff-session-csrf` (worktrees under `/home/user/overwatch-wt/`). There are no `origin/task/...` refs for these four, so the diffs below are `git diff main...task/<name>`.
- DEC-112 (U02) and DEC-115 (U03) exist only on those branches. DEC-112 and DEC-115 are not in `main`'s `decisions.md`.
- Delivered status is taken from `origin/ledger-refresh:docs/delivery/ledger.jsonl` (2377 events, 76 `deliver` events). The ledger on `main` is older (48 delivered). The live local ledger may be newer still.
- L130 and L126 are in `origin/ledger-refresh:docs/delivery/LESSONS.md`, not on `main`.

---

## 1. SUMMARY

### Counts (each verified by grep or a parse of the source)

| Thing | Count on main | Added by unmerged branches |
|---|---|---|
| Use-case classes with `execute` or `handle` | 3: `ReportCapacity` (`use_cases/report_capacity.py:260`), `QueryBoard` (`query_board.py:64`), `BoardProjector` (`board_projector.py:123`) | +2: `ConfirmCapacity` (U02, `confirm_capacity.py:80`), `SendPrompts` (U03, `send_prompts.py:150`) |
| Shared application functions that write like a use case | 1: `record_report` (`report_capacity.py:124`) | +2: `schedule_work`, `cancel_work` (U03, `scheduling.py:35`, `:74`) |
| Application services (not use cases) | 2: `LinkTokenService` (`ports/outbound/tokens.py:32`), `HmacPhoneHasher` (`ports/outbound/identity.py:28`) | 0 |
| Ports (Protocol classes) | 36 (35 in `ports/outbound/*.py`, 1 `IdempotencyStore` in `application/idempotency.py:36`), 112 methods | +2 methods on `CapacityRepository` (U02) |
| Inbound ports | 0 (`application/ports/inbound/` holds only `__init__.py`) | 0 |
| Domain rule modules (`domain/rules`) | 22 | 0 |
| Domain model modules (`domain/model`) | 9 | 0 |
| Code enums (`domain/codes.py`) | 26 | 0 |
| Domain event classes (`domain/events.py`) | 10 (lines 99, 131, 160, 191, 220, 246, 263, 289, 318, 347) | 0 |
| Message ids (`domain/messages/catalogue.py`) | 25 (C1-C11, B1-B7, I1-I3, K1-K4) | 0 |
| Templates (message id x channel) | 32 (`templates.py`) | 0 |
| Domain errors | 6 (`domain/errors.py`) | +2 (U02: `ConfirmLimitReached`, `NothingToConfirm`) |
| Identifier and reference generators | 6: `UuidGenerator` (`adapters/outbound/ids_uuid/uuid_ids.py`), `SequentialIds` (test fake, `adapters/testing/fixed_ids.py:4`), `new_reference` (`rules/booking_rules.py:56`), `new_link_token` (`rules/tokens.py:87`), `new_pairing_code` (`rules/tokens.py:111`), `new_support_code` (`rules/tokens.py:135`). Plus derived keys listed in section 5. | 0 |
| Time and threshold constants in domain | about 50 named constants (table in section 6) | 0 |
| `Actor(` construction sites | 4 in `src` (`board_projector.py:46`, `adapters/outbound/audit_neo4j/audit_log.py:238`, `adapters/inbound/fhir_rest/auth.py:40` and `:47`), 19 in `tests` across 10 files | W02 adds none (front end only) |
| Existing tests that touch this layer (rough) | 901 `def test_` in `tests/unit/domain`, 67 in `tests/integration/application` | U02 adds about 597 lines of tests, U03 about 757 |

### What the unmerged branches add under the audited paths

| Branch | Files under `domain/` and `application/` | Tenancy relevance |
|---|---|---|
| `task/U02-confirm-capacity` | new `application/use_cases/confirm_capacity.py`; edits `report_capacity.py` (`check_may_report` made public, `record_report` gains `use_case`, `audit_snapshot`); `ports/outbound/repositories.py` (+`lock_service`, +`trailing_confirmations` on `CapacityRepository`); `domain/errors.py` (+2 errors) | A lock query keyed by service key runs before the existence check. It must be tenant-bound or it becomes a cross-tenant timing channel (section 3). |
| `task/U03-send-prompts` | new `application/scheduling.py`, new `application/use_cases/send_prompts.py` | First writer of `ScheduledWork` and of link tokens. Carries a single `link_base_url`, a derived idempotency key, and an actor that is "recorded and not authorised". |
| `task/I04-consumer-framework` | nothing under `domain/` or `application/`. It adds `adapters/inbound/workers/consumer.py` and `servicebus_runner.py` | It is the worker entry point and has no tenant source. `to_bus_message` reads id, subject and payload only (`servicebus_runner.py`, `to_bus_message`), and `IdempotentConsumer.handle` opens the unit of work before anything is known about a tenant (`consumer.py`, `handle`). Listed here because it fixes the shape of `BusMessage` consumers. |
| `task/W02-bff-session-csrf` | nothing under `domain/` or `application/`. Front end only. | `Session` has no tenant (`frontend/lib/auth/session.ts`). Tenant must ride in the signed backend token that `bff_token.py` decodes (section 2). |

### Overall difficulty

Medium, and unusually well shaped for the retrofit, with five hot spots.

Why it is tractable: the domain is pure and takes `now`, so tenancy does not leak into rules. Every use case opens its own unit of work through a zero-argument `UnitOfWorkFactory`, so binding the tenant by context variable at `__aenter__` needs no use-case signature change. Ids come from `IdGenerator` (uuid4), so no id generator needs a tenant. Event payloads carry only ids, counts and codes.

Why it is not trivial:
1. Pure rule functions read module constants directly (`REPLY_WINDOW` is used in four modules). Per-tenant thresholds mean threading a policy value object through about 14 rule functions and their roughly 100 call sites in tests.
2. Several lookups and unique keys are global today and become existence oracles or cross-tenant joins (section 10, risks 2 and 3).
3. The board cache key, the pub/sub channel and the SSE relay are one global object (risk 1).
4. Worker and system actors have no tenant source (risk 4).
5. The collaboration model (grants plus projections, or a network above organisations) changes what `QueryBoard`, `BoardProjector`, booking and filtering mean. It should be chosen before those are reworked (section 3, collaboration column).

Estimated effort for this layer: about 80 hours across 16 tasks (section 11), plus amendments to about 45 planned task prompts, plus the collaboration seam which cannot be sized until the model is chosen.

---

## 2. THE ACTOR AND THE TENANT CONTEXT

### Today

`application/actor.py:7-14` is a frozen dataclass: `role`, `practitioner_id`, `device_id`, `channel`, `service_ids`. It has no tenant. It is built in four places:

| Site | What it does |
|---|---|
| `adapters/inbound/fhir_rest/auth.py:37-53` `actor_from_claims` | Two `Actor(...)` calls (`:40` wall device, `:47` everyone else) from `BffClaims`. This is the only request-side source of an actor. |
| `application/use_cases/board_projector.py:46` `WALL_ACTOR` | A module-level constant actor, `channel="system"`, used by `handle` (`:133`) to rebuild the board in a worker. |
| `adapters/outbound/audit_neo4j/audit_log.py:232-244` `_parse_entry` | Rebuilds an actor from stored canonical JSON. |
| U03 (branch) | `SendPromptCommand.actor` is "recorded and not authorised"; DEC-115 item 8 says the scheduled-work consumer (I05) passes a system actor. There is no system actor builder yet. |

`domain/rules/bff_token.py:32` `BffClaims` (`sub`, `role`, `services`, `expires_at`, `device`) is what a token decodes to (`decode_bff_token` `:63`, `_claims` `:128`). It has no tenant claim. `encode_bff_token` (`:48`) is the only writer of the claim set.

Where actors are checked:

| Check | Location | Meaning |
|---|---|---|
| May report for service | `report_capacity.py:80` `_check_may_report` (renamed public `check_may_report` by U02) | Reporter: own `service_ids`, any source except advisor-phoned. Advisor or lead: any service, only as advisor-phoned. Anything else: `NotAllowed`. |
| Anonymous link cannot read board | `query_board.py:70`, `board_projector.py:147` | Refuses `Role.ANONYMOUS_LINK`. |
| Service-wide roles | `auth.py:30` `_SERVICE_WIDE_ROLES` = lead, advisor, clinical, audit; `ensure_can_act_for` `:104` | HTTP layer. `NotAllowed` is answered as the same 404 as a missing record (DEC-086 item 5, per the module docstring). |
| Patient access | `auth.py:29` `PATIENT_ROLES`, `ensure_patient_access` `:109` | advisor, clinical. |
| Stream roles | `routes_events.py:36` | wall, advisor, clinical, lead, exec. |
| Approver differs (planned) | DEC-032: the use case, not `rules/registration.py`, refuses `NotAllowed` | Needs two distinct actors within one tenant. |
| Cover | `domain/model/people.py` `role_holder` (pure), `PersonRepository.services_for_phone_hash` and `reporter_roles_for_service` (`repositories.py:123`, `:132`); `save_role` refuses an unknown cover practitioner with `NotFound` | Cover is a practitioner-to-practitioner link. |
| Support | `Role.SUPPORT` exists (`codes.py`) but is in no role set. No use case or route grants it anything. DEC-130 item 8: no role holds cross-tenant access until decided. | |
| Advisor | `Role.ADVISOR` reports any service as advisor-phoned (DEC-100 item 3). | Under collaboration this may become a cross-organisation write (section 3). |

### Recommended design

**One context, one actor field, one assertion.**

1. New module `application/tenancy.py` (the seam for this layer, TEN-A01):
   - `TenantId`: validated string (lower-case letters, digits, hyphen, 3 to 40 characters, no colon or slash, so it is safe inside Redis keys, Service Bus session ids and `idem:<sub>:<key>` style keys).
   - A `ContextVar` holding the bound tenant, `bind_tenant(tenant_id)` (a context manager), `current_tenant()` (raises `TenantNotBound` with a fixed message, never a NotFound), and `unscoped(reason)` for the short allow-list of global operations (tenant directory lookups, token-hash resolution, outbox and scheduler iteration). `unscoped` must log the reason id and be import-restricted by an architecture test to named modules.
   - `domain` stays free of it. Only `application` and `adapters` import it. The adapters seam (`run_query`, DEC-130 item 2) reads the same variable. This audit does not design the adapter side.
2. `Actor` gains a required field `tenant_id: TenantId`. Required, no default: construction fails at the 4 `src` sites and 19 test sites on purpose, so nothing is built without one. `BffClaims` gains a required `tenant` claim. `encode_bff_token` writes it and `_claims` rejects a token without it as `TokenRejected` (fixed message). The BFF session (`frontend/lib/auth/session.ts` on the W02 branch) must carry the tenant inside the sealed backend token. The tenant is never a separate header or cookie the caller controls (DEC-130 item 6).
3. The tenant is bound **once, at the edge**: HTTP dependency `current_actor` (`auth.py:82`) after decoding the token; the worker entry (`IdempotentConsumer.handle`, I04) before `uow_factory()` is called; the inbound SMS route after resolving the tenant by `To` and `AccountSid` (DEC-131 item 2); the link route after resolving the token hash. `UnitOfWork.__aenter__` snapshots `current_tenant()` so a mid-flight rebind cannot change what a unit of work writes.
4. Every use case starts with `require_actor_in_bound_tenant(actor)`: if `actor.tenant_id != current_tenant()` raise `TenantMismatch` (fixed message, logged by id only, answered 500). This is defence in depth against a wiring bug. It is not an access check and must never be reachable by a caller-supplied value.
5. `BoardProjector.WALL_ACTOR` (`board_projector.py:46`) becomes `wall_actor(tenant_id)`; add `system_actor(tenant_id, channel)` for the scheduled-work consumer, the outbox relay and the sweeps. A worker actor carries the tenant of the message it is processing, not a platform-wide identity.
6. `AuditEntry` needs no new field (it holds the actor). `canonical_entry_json` (`ports/outbound/audit.py:71`) adds `"tenant_id"` inside the `actor` object for new entries. Legacy chain links keep the canonical text they were hashed from. Verification recomputes from the stored `entryJson`, so old and new links coexist. `_parse_entry` (`audit_log.py:232`) must read `actor.get("tenant_id")` and fall back to the legacy default tenant. See section 7 for the per-tenant chain.

### How permission checks become tenant-aware

The rule is an ordering invariant, not a parameter: **load by id through the tenant-bound repository first, then check the actor's permission on what was loaded.** The use cases already do this (`report_capacity.py:301` loads the service, `:304` checks permission; `confirm_capacity.py:108` then `:111`; DEC-100 item 3 says "the service is loaded first"). `_check_may_report` itself stays pure on `(actor, source, service_id)` and needs no tenant parameter, provided the repository returns `None` for another tenant's id. Record this as an invariant in the contract notes and test it for every use case (section 4).

**The exact rule for another tenant's service id:**

- A service id (or booking, case, report, role, criteria, registration, communication, practitioner, flag or work id) that exists only in another tenant must produce exactly what a nonexistent id produces. For `ReportCapacity` that is `NotFound("no active service with this id")`, raised before `_check_may_report` runs, never `NotAllowed`.
- It must be indistinguishable in four ways: same exception class, same message text, same number of queries executed, and no lock acquired. Lock matters because U02's `lock_service` runs before the existence check (`confirm_capacity.py:103`). If `Q-CAP-LOCK-SERVICE` matched by `key` alone, tenant A holding a lock would delay tenant B and reveal that the service exists. The lock statement must carry `tenantId: $tenant` like every other statement, and a held-lock timing test must prove it.
- `NotAllowed` is for "the object is in your tenant and you may not". It still reveals existence inside the tenant. That is accepted (the HTTP layer already maps it to the 404 body). It must never be returned across tenants.
- Do not echo the id in the message and do not branch on tenant in error text. `actor.service_ids` is a claim list of the actor's own tenant. A claim that names a service of another tenant yields `NotFound` for the same reason (the repository finds nothing), not `NotAllowed`.
- `performer_role_id` is accepted without validation at `report_capacity.py:314` and `:316` (and U02 `confirm_capacity.py:128`, `:131`). It becomes the echo recipient (`:179`, `:195`). Today any role id can be named. After tenancy the consumer resolves the role in the bound tenant and finds nothing for another tenant's role, but the use case should validate it (belongs to this tenant and to the actor) and fail with `NotFound`, so the error does not appear later in a worker.

**DEC-131 effect on actors.** Inbound SMS actors are built after the tenant is resolved from `To` and `AccountSid` in the tenant configuration. The sender number never chooses the tenant. The reporter is then found by phone hash inside that tenant. A person who is a reporter in two tenants is two `Practitioner` records, each with its own `service_ids`, `device_id` and PIN. There is no cross-tenant practitioner record, and cover (`covered_by_practitioner_id`) is always inside one tenant.

**Support and cross-tenant (DEC-130 item 8, still open).** A support actor must not be a normal `Actor` with a different tenant. Propose: `Actor.tenant_id` is the tenant being accessed, and an optional `grant` (grant id, home tenant of the engineer, expiry) is set only by an audited grant record. A token without a grant for a tenant cannot name that tenant. Each use under a grant appends an audit entry in the accessed tenant's chain and one in the home tenant's chain. Until the owner rules which roles may hold it, `Role.SUPPORT` stays in no role set and no grant exists.

**Collaboration (new).** Under either candidate model the `Actor` will need a way to name what else it may read. Design the seam so that `Actor.tenant_id` stays the single home tenant, and extra visibility comes only from a separate resolved object (`Visibility`: the home tenant plus a set of granted projections or a network scope) obtained from a `CollaborationGrants` port inside the unit of work, never from request input. That keeps TEN-A02 independent of the model.

---

## 3. EVERY USE CASE

Collaboration column: "reads other organisations?" asks whether the use case would ever need another organisation's data once organisations collaborate. R = reads, W = writes or sends to, N = never.

### 3.1 On main

| Use case | File:line | Ports and repositories used | Tenant scoping needed | Leak risk | Reads other orgs under collaboration? |
|---|---|---|---|---|---|
| **ReportCapacity** | `use_cases/report_capacity.py:260`, `execute` `:273` | `UnitOfWorkFactory`, `Clock`, `IdGenerator`, `IdempotencyStore` (early read outside the unit of work `:276`), then inside: `uow.idempotency` (`:297`), `uow.services.get` (`:301`), `uow.flags.service_flags` (`:142`), `uow.capacity.latest/add` (`:146`), `uow.bookings.confirmed_since` (`:148`), `uow.outbox.add` (`:166`, `:186`), `uow.communications.add` (`:185`), `uow.audit.append` (`:202`) | **Inputs by id:** `service_id` (must read as NotFound across tenants), `performer_role_id` (unvalidated today, `:314`), `idempotency_key` (global key space today, see section 5). **Outputs:** `ReportCapacityResult` (stored through the idempotency store, so the dataclass shape must not change incompatibly). **Events:** `CapacityReported`, `StatusChanged` on `capacity.events`, session id = service id (`events.py:419`); `SendMessage` on `messages.outbound` (`:186-199`). Each needs `tenant_id` on the outbox record and bus message, not in the payload. **Idempotency scope:** per tenant. The early read at `:276` goes through the tenant-bound store. The fingerprint (`:225`) should include the tenant as a belt-and-braces term. **Cache keys:** none written, but the event triggers a board rebuild for this tenant only. **Scheduled work:** none here (U03 schedules the next prompt). **Thresholds read:** `compute_status` (`:149-150`), `next_due` (`:168`): per-tenant policy. **Text:** `format_hhmm` London time in the echo. | **High** if the idempotency key or lookups are global, **Low** once tenant-bound. The Conflict on a reused key (`:254-257`) is an oracle if the key space is shared. | **W only** to its own tenant's service. An advisor-phoned report for another organisation's service (`check_may_report` `:88`) would be a cross-organisation write: decide under the model. Its `CapacityReported` event is the source of any outbound projection. |
| **QueryBoard** | `use_cases/query_board.py:64`, `execute` `:69` | `UnitOfWorkFactory`, `Clock`; `uow.services.list_active` (`:75`), `uow.flags.services_with_flag` (`:77`), `uow.capacity.latest_for_services` (`:78`), `uow.bookings.open_for_services` (`:79`), `uow.bookings.confirmed_since_for_services` (`:86`) | **Inputs:** only the actor (no ids). Everything is a list of the bound tenant's services; correctness depends on the repositories filtering, so `list_active` is the single point that sets the board's scope. **Output:** `Board` (entries named by service id and name, pressure). **Pressure thresholds** (`pressure.py:26-27`, 3 and 5) are absolute counts over the tenant's services: must become per-tenant. **Events:** none (read-only, no commit). **Cache:** the result is cached by BoardProjector. | **High** (largest data surface; the only thing between tenants is the repository filter). | **R: yes, the primary case.** An advisor's board across providers who are other organisations. Depends on the model: reads local read-only projections of provider capacity subject to a grant, or queries at network scope. The `Board` entries would then need an `organisation` attribute and "pressure" a defined scope (own services or everyone's). |
| **BoardProjector** (`handle`, `get_board`) | `use_cases/board_projector.py:123`, `handle` `:129`, `get_board` `:145` | `QueryBoard`, `Cache`, `Clock`. `handle` stores `BOARD_CACHE_KEY` (`:135`) and publishes `BOARD_UPDATES_CHANNEL` (`:142`); `get_board` reads (`:158`) and stores (`:169`) | **The most dangerous single module for leakage.** `BOARD_CACHE_KEY = "board:v1"` (`:31`) is a module constant; `board.updates` is a module constant (`cache.py:12`); `WALL_ACTOR` (`:46`) has no tenant. `handle(event_type, payload)` has no tenant argument, so the tenant must come from the message binding (I04). **Inputs:** `event_type`, `payload.service_id` (published in the message `:136-141`). **Output:** a board JSON and a "board-changed" message. **Keys and channel:** section 8. | **Critical** until the cache wrapper scopes key and channel by the bound tenant. | **R and fan-out.** Under grants, a capacity event in provider tenant P must trigger rebuilds for every tenant S whose board shows P. Today it rebuilds one global board. |

### 3.2 On unmerged branches

| Use case | File:line (branch) | Ports and repositories used | Tenant scoping needed | Leak risk | Reads other orgs? |
|---|---|---|---|---|---|
| **ConfirmCapacity** (U02) | `confirm_capacity.py:80`, `execute` `:93` | As ReportCapacity, plus `uow.capacity.lock_service` (`:103`) and `trailing_confirmations` (`:116`); reuses `check_may_report` and `record_report` | **Inputs:** `service_id`, `performer_role_id` (as above), `idempotency_key`. `Q-CAP-LOCK-SERVICE` and `Q-CAP-TRAILING-CONFIRMS` use `key=f"{_SERVICE}/{service_id}"` (capacity_repository diff): must add `tenantId: $tenant`. The lock runs **before** the replay and existence checks (`:103` then `:104`, `:108`), which is only safe if tenant-bound (see section 2). **Idempotency:** a key stored by `ReportCapacity` is a Conflict for a confirmation (`_replay`, DEC-112 item 6). Within one tenant that is fine. Across tenants it must not be reachable. **Events:** same as ReportCapacity. | **Medium-High** (lock channel plus the global key space). | **W only** to own tenant (same as ReportCapacity). |
| **SendPrompts** (U03) | `send_prompts.py:150`, `execute` `:167`, `_send` `:196` | `uow.idempotency` (`:176`), `uow.services.get` (`:180`), `uow.flags`, `uow.capacity.latest`, `uow.people.reporter_roles_for_service` (`:209`), `uow.people.get_practitioner` (`:281`), `uow.link_tokens` through `LinkTokenService` factory (`:215`), `uow.communications.add`, `uow.outbox.add`, `schedule_work` x4 (`:239-258`), `uow.audit.append` | **Inputs:** `service_id`, `due_at`, `idempotency_key` (derived `prompt:<service>:<due iso>`, DEC-115 item 6: deterministic, so two tenants with equal service ids would share a key; must be tenant-scoped). **Outputs:** `SendPromptResult` (communication ids). **Link:** `link_base_url` is one string for the process (`:158`, `:165`, `:216`). DEC-131 gives each tenant its own Twilio subaccount and number, so the link host becomes a per-tenant setting (open question: shared host with an opaque token versus per-tenant host). **Token:** purpose `capacity-reply`, `about_id` the communication id, `phone_hash`; the hash is looked up later with no tenant known, so the token record must carry `tenant_id` (DEC-131 item 5, section 5). **Ladder and thresholds:** `ladder_times` (`:239`), `reply_by` (`:204`, `:186`), `next_due` (`:251`): per-tenant policy. **Events:** `SendMessage` (messages.outbound), `ScheduleWork` x4 (scheduled.work). **Scheduled work:** `reminder`, `phone-task`, `escalate-to-lead` about the communication id, `prompt-due` about the service id. | **Medium** (everything is by id inside one tenant; the risks are the global key and link host). | **N.** |
| **schedule_work / cancel_work** (U03) | `scheduling.py:35`, `:74` | `uow.scheduled_work.add/get/save`, `uow.outbox.add` | `ScheduledWork` rows and `ScheduleWork`/`CancelWork` outbox messages carry the tenant. Payload (`:62-67`: `work_id`, `kind`, `about_id`, `enqueue_at`) stays tenant-free. The cancel id `cancel-<work id>` (`:86`) is unique only if work ids are; unique per tenant is enough under the composite constraint. `uow.scheduled_work.get(work.id)` returns another tenant's row only if unscoped, so `get` must fail closed (it returns `ScheduledWork`, not Optional, `event_bus.py:54`: a miss raises, which should read as NotFound). | Medium | N |

### 3.3 Application services and shared functions (not use cases but they hold tenant-sensitive logic)

| Item | File:line | Tenant issue |
|---|---|---|
| `record_report` | `report_capacity.py:124` | Writes to six repositories and the outbox. Reuse by U02 and later U05, U07, U13. Needs no tenant parameter, but its policy input (status, next due) must come from the tenant policy. |
| `LinkTokenService` | `ports/outbound/tokens.py:32`; `issue` `:38`, `resolve` `:55`, `burn` `:63` | `resolve` runs with no tenant bound on a public link. Needs the explicit unscoped hash lookup that returns the tenant, then bind, then `burn` inside the tenant. All failures (unknown, malformed, used, expired) must look identical to the caller. `issue` stamps the tenant from `current_tenant()`. |
| `HmacPhoneHasher` | `ports/outbound/identity.py:28` | One global secret `phone-hash` (`:18`), so the same phone hashes to the same value in every tenant. See section 4. |
| `IdempotencyStore` + `encode_result`/`decode_result` | `application/idempotency.py:36`, `:65`, `:74` | Result dataclasses are stored by `module:qualname` (`:21` allowed packages). Do not add fields to existing result dataclasses and do not rename `_StoredReport` and the like: stored records would stop decoding. Tenancy needs no field in results. |

### 3.4 Planned use cases (not delivered): collaboration reads, so the model can be chosen with these in view

Source: `docs/plan/tasks.json`, filtered to tasks that own files in `application/` or `domain/`, not in the 76 delivered. R = reads other organisations, W = writes or sends to another organisation, N = never.

| Task | Use case | Collaboration | Why |
|---|---|---|---|
| U04 | Grouped prompts | N | Own tenant's reporters. |
| U05, U22 | HandleInboundText (capacity, booking replies) | N | Reply arrives on the tenant's own number (DEC-131). A provider replying CONFIRMED to a booking raised by another organisation is a W into the requester's tenant under a cross-organisation model. |
| U06 | Missed-report ladder | N | Own tenant. |
| U07, U39 | Report flags, resolve flags | N | Own tenant. |
| L01 | Capacity link API | N | The token resolves one tenant. |
| U10 | PairWallScreen | N, but see section 5 | A wall screen shows its tenant's board. A screen showing collaborators' services is the board question. |
| U11, U13, U14 | OpenCase, advisor phoned, RecordOutcome | W in some models | Cases are the requesting organisation's. A case referred to another organisation's service creates a shared artefact. |
| U12 | FilterOptions with audit snapshot | **R** | Filters other organisations' criteria and capacity (uses `QueryBoard`, criteria of every candidate service). |
| U15, U16, U23-U26, U28-U31 | Service set-up, reporter numbers, scope list, invites, registration, criteria | N | Administration inside one tenant. Scope list entries "point at services which may not have registered yet" (`ScopeListRepository`): under a network above organisations this list may be shared. |
| U17-U21 | RequestBooking, RespondToBooking, Cancel, Withdraw, timers | **R and W** | An SPOA advisor requests a booking at a provider's service. The Task is owned by the provider's service, the requester is the advisor. This is the strongest cross-organisation write. Option 1 (grants plus projections) needs a message to the provider tenant or a booking object in both; option 2 (network) has one booking visible to two organisations. Booking reference "unique within a tenant" (DEC-131) is not enough if the reference is read out across organisations by phone. |
| U32, U37 | PIN, remove person | N | Own tenant. |
| U33, U34 | Alerts | R possibly | `system-pressure` and `service-closed` for a collaborator's services. |
| U35 | Week summary for COO and ICB | **R** | The ICB reads many organisations by design. |
| U36 | Suspend/resume service | N | Own tenant. A suspension affecting a collaborator's board is a projection effect. |
| U40 | Clinical advice requests | R possibly | A clinical advisor pool may serve several organisations. |
| U41, U42 | Safety concern, audit replay | N / R | Replay of "what the advisor saw" includes other organisations' data the advisor saw (U12): the snapshot must record which tenant each datum came from. |
| U43 | Planning analysis | **R** | Aggregates across organisations unless it is per tenant. |
| O06, R18 | Support codes and support access | Cross-tenant by design | DEC-130 item 8. |

---

## 4. PORTS

Principle: **every port that reads or writes tenant-owned data keeps its signature and gains tenant behaviour from the bound context.** DEC-130 item 2 says a caller cannot pass or override the tenant. A `tenant` parameter on a port is a parameter someone will fill wrongly. The exceptions are ports that operate across tenants on purpose; those are marked "explicit" and are on the allow-list.

### 4.1 Outbound ports (`application/ports/outbound`, plus `idempotency.py`)

| Port (file:line) | Tenant handling | Change needed | Contract-suite implication |
|---|---|---|---|
| `ServiceRepository` (`repositories.py:22`): get, list_active, save | Implicit | None to the signature. `get` returns `None` for another tenant's id (the NotFound rule). `list_active` is the board scope. | Two-tenant integration test: same ids in two tenants do not collide, `get` across tenants is `None`. |
| `CapacityRepository` (`:36`): add, latest, latest_for_services, reports_since, last_report_times (+ `lock_service`, `trailing_confirmations` on U02) | Implicit | Lock and trailing-confirmation statements tenant-bound. `last_report_times` returns "every active service": bound tenant only. | Held-lock test per tenant (A's held lock does not delay B). |
| `BookingRepository` (`:58`): 9 methods | Implicit | **Add `open_references() -> set[str]`** (tenant-bound) so `new_reference`'s `taken` set has a source (`booking_rules.py:56`; U17 does not say where `taken` comes from). `get_by_reference` (`:67`, docstring "most recently requested ... with this reference") must be tenant-bound and must not be used to match replies: `match_reply` takes an `open` list (`booking_rules.py:65`), so U22 must use `open_for_services(phone's services)`. | Test that reference 4821 in tenant A and tenant B resolve independently. |
| `PersonRepository` (`:100`): `find_by_phone_hash` (`:113`), `services_for_phone_hash` (`:123`), `reporter_roles_for_service` (`:132`), save_* | Implicit | The "two active practitioners on one hash raise Conflict" rule (`:113-118`) is per tenant. A phone in two tenants is two records and is never a Conflict. `save_role` refuses an unknown cover practitioner `NotFound`: a practitioner of another tenant is "unknown". | Test: same hash in two tenants, each lookup sees one practitioner, no Conflict. |
| `CaseRepository` (`:149`): `get_by_reference` (`:166`) | Implicit | Reference unique per tenant. See the reference-space problem in section 5. | |
| `CriteriaRepository` (`:177`), `RegistrationRepository` (`:214`), `FlagRepository` (`:268`) | Implicit | None to signatures. `FlagRepository.add_report_flag` "a report of another service raises ValidationFailed": a report of another tenant must read NotFound. | Generated two-tenant test (DEC-130 item 4). |
| `ScopeListRepository` (`:246`): `save_entry` (`:262`) | Implicit | `save_entry` creates "a minimal inactive HealthcareService" for an unknown service id: it creates it in the bound tenant only. Under a network model the scope list may be shared: decide with the collaboration model. | |
| `CommunicationRepository` (`messaging.py:82`): `by_provider_id` (`:87`), `set_delivery_status`, `latest_prompt_for_phone` | Implicit | DEC-131 item 2: delivery receipts are matched by `AccountSid` and message id, so receipts resolve the tenant first (tenant directory by `AccountSid`), then these methods run bound. Provider message ids are no longer a tenant oracle. | |
| `LinkTokenRepository` (`tokens.py:18`): `get_by_hash`, `mark_used`, `burn_key`, `add` | `add` implicit; **`get_by_hash` has an explicit unscoped variant** that returns the record with its `tenant_id` | `LinkTokenRecord` (`rules/tokens.py:52`) gains `tenant_id`. `mark_used` and `burn_key` run bound. Hash is globally unique (migration `0021_link_token_hash`), 128 bits. | Two-tenant test, plus "unknown, used, expired are indistinguishable". |
| `ScheduledWorkRepository` (`event_bus.py:51`) | Implicit | A consumer loads the row in the bound tenant. Missing row means done or foreign: ignore, log id only. | |
| `Outbox` (`outbox.py:58`): add, pending, mark_published, mark_failed | `add` implicit; **the relay needs a tenant iteration** | `OutboxMessage` (`:26`) gains required `tenant_id`; `outbox_message_for` (`:45`) takes it from `current_tenant()`. The relay (I03) iterates tenants and binds each, so one tenant's backlog and its failures cannot starve or break another's (`pending(limit)` is per tenant). | |
| `AuditLog` (`audit.py:101`): append, records, verify_chain | Implicit | One chain per tenant (DEC-130 item 7). `verify_chain()` verifies the bound tenant's chain. A platform-wide verify is an explicit loop over tenants. `GENESIS_HASH` (`:21`) becomes `genesis_hash_for(tenant)`, with the legacy tenant keeping `"0"*64`. | Per-tenant chain property tests; the existing P05 tests must run bound. |
| `UnitOfWork` (`unit_of_work.py`): 19 repositories and stores | Implicit | Captures the tenant at `__aenter__`. A `uow.tenant` read-only property aids tests and the guard. `UnitOfWorkFactory` stays zero-argument. | Unit of work refuses to enter with no tenant bound (fixed message). |
| `IdempotencyStore` (`idempotency.py:36`), `ProcessedMessages` (`ports/outbound/idempotency.py`) | Implicit | Composite uniqueness `(tenantId, key)`; `Processed` key likewise. The early read at `report_capacity.py:276` and `confirm_capacity.py:96` runs outside the unit of work: the store must itself read the binding. | |
| `Cache` (`cache.py:23`): get, set, delete, publish, subscribe, acquire_lock, release_lock | Implicit, done by a decorator | One `TenantScopedCache` wrapper in the composition root prefixes key, channel, lock name and fencing counter with `diucs:<tenant>:` (DEC-130 item 7) at call time. Callers keep logical names. Unbound call raises. A named `unscoped` caller (relay leader lock, pre-auth rate limits) uses the `_global` namespace. | Add two-tenant cases to `tests/contract/test_cache_contract.py` so both the real Redis adapter and `InMemoryCache` enforce the same isolation (the existing `factories.py` runs each test once per adapter). Include `subscribe`: a message published in A is never delivered to a subscriber bound to B. |
| `EventBus` (`event_bus.py:37`): publish, schedule, cancel | **Explicit**, through `BusMessage.tenant_id` (`:29`, add required) | `publish` and `schedule` write it as a Service Bus application property. Receive side (`to_bus_message`, I04) reads the property, never the payload, and dead-letters a message with a missing or unknown tenant as malformed. `session_id` becomes `<tenant>:<service id>` (`events.py:419`). `cancel(queue, sequence_number)` is unchanged. | Add tenant round-trip cases to `test_event_bus_contract.py` for `ManualEventBus` and the real bus. |
| `SmsSender`, `EmailSender`, `PushSender` (`messaging.py:51`, `:55`, `:59`) | Implicit sender selection | DEC-131: each tenant has its own Twilio subaccount and email identity. The adapter selects credentials from the bound tenant's configuration (secret reference id, DEC-131 item 4). `SmsSender.send(to, text, message_id)` stays. | Recording fakes keep a `tenant_id` per send so tests assert the right sender was used. |
| `ContactStore` (`identity.py:59`), `PinStore` (`:87`), `DeviceRegistry` (`:99`), `CodeStore` (`:77`) | Implicit | `CodeStore` is keyed by phone hash only (`:80-84`): key must include the tenant, since DEC-131 item 5 says verification codes are issued on the tenant's number. `DeviceRegistry`: migration `0023_device_id` makes device id unique across the graph and one device belongs to one practitioner (`credential_store.py`, "Device ids are unique in the graph"). If a device id is ever supplied by the client or reused across tenants, the owner lookup (`Q-` query returning `p.id AS owner`) is a cross-tenant identity oracle. Device ids must be server-issued and unique per tenant. | |
| `CodeSender` (`:71`) | Implicit | Sends from the tenant's number. | |
| `PhoneHasher` (`identity.py:24`) | Agnostic port, but see decision | Single global key today. With DEC-131 routing by number, a per-tenant derived key (key derivation from the master secret plus tenant) becomes possible and means the same phone hashes differently in each tenant, so a hash that leaks from one tenant is worthless in another. Cost: re-hash all stored hashes at migration, needing the numbers (`ContactStore` holds them). Recommendation: keep the global key in phase 1, record as owner question. | |
| `SecretStore` (`tokens.py:28`) | Agnostic | Per-tenant secrets are reached by secret reference id from the tenant record. `phone-hash`, `link-token`, `bff-jwt` stay platform secrets. | |
| `Clock` (`clock.py`), `IdGenerator` (`ids.py`) | **Agnostic** | None. `UuidGenerator` is uuid4: globally unique with no coordination. | |
| `Geocoder`, `PostcodeLocator`, `TravelTime` (`geo.py`), `Terminology` (ODS lookup, display), `FhirValidator` (`terminology.py`) | **Agnostic** (reference data, DEC-130 item 5) | None. They must stay free of tenant data: a postcode sent to a geocoder is already patient-adjacent (DEC-047). | Existing fixed-table fakes unchanged. |
| **New: `TenantDirectory`** | **Explicit, global, read-only** | `get(tenant_id)`, `by_inbound_number(account_sid, to_number)` (DEC-131 item 2), `by_account_sid(account_sid)` (receipts), `list_active()` (relay, scheduler, sweeps). Returns `Tenant` with `policy` (section 6), sender numbers, secret reference ids, time zone. Loaded through the explicit unscoped path. A short in-process cache is allowed (tenant configuration changes rarely) with invalidation on change. | Real Neo4j adapter. No fake. |
| **New: `CollaborationGrants`** (placeholder) | Explicit | Defined after the model is chosen. | |

### 4.2 Inbound ports

None exist (`application/ports/inbound/` is empty). Inbound adapters call use cases directly. Tenant binding at each inbound adapter is therefore part of the adapter audit. This layer provides `bind_tenant` and a `bind_from_claims(claims)` helper so the HTTP, worker and webhook adapters all bind the same way.

### 4.3 Contract suite implications

- `tests/contract/` has two suites today: `test_cache_contract.py` and `test_event_bus_contract.py`, run per adapter factory (`factories.py`). Neo4j-backed ports have no fakes (contracts.md, "Testing and persistence"), so their contract is the integration tests against the real adapters.
- Add a **generic two-tenant differential test** over every use case: seed tenant A and B, call each use case as a B actor with A's ids, and assert the result is identical (class, message, query count, no lock) to calling it with a random uuid, and that nothing in A changed. This is the executable form of the NotFound rule in section 2 and the use-case analogue of DEC-130 item 4's generated test over the query registry.
- Add architecture tests (`tests/architecture`): no module under `domain/` imports `application.tenancy`; `unscoped(...)` is imported only by an allow-listed set of modules; no `ContextVar.set` outside `tenancy.py`.
- `SequentialIds` (`fixed_ids.py:4`) produces `id-1, id-2...`. Parallel harness runs sharing one Neo4j (DEC-130 item 9) and lesson L134 (a second instance reuses ids) mean the harness must give each run's generator a tenant-derived prefix, as well as relying on the composite constraints.

---

## 5. IDENTIFIERS AND REFERENCES

### Uniqueness today and what each must become

| Identifier | Source | Uniqueness scope today | Required scope | Notes |
|---|---|---|---|---|
| Entity ids (service, report, booking, case, role, practitioner, communication, flag, work, criteria, registration) | `IdGenerator.new_id()` (`ids.py`), `UuidGenerator` = uuid4 (`ids_uuid/uuid_ids.py`) | Global. `Resource.id` unique (`migrations.py` `0001_resource_id`), others per label (`0009`, `0014`, `0016-0020`, `0027`, `0028`) | `(tenantId, id)` composite (DEC-130 item 7). No generator change. | uuid4 means two tenants cannot collide, so a client-chosen id is the only collision source. The FHIR layer must keep ids server-assigned or the composite constraint must be the arbiter (a collision then reads as Conflict only inside the tenant). |
| Booking reference | `new_reference(rng, taken)` `rules/booking_rules.py:56`: random 1000-9999 (`:22-23`), 50 attempts (`:20`), `Conflict` after (`:58-61`); format enforced in `events.py:40`, `templates.py` `REFERENCE_FORMAT`, `case_repository.py:69`. Stored as a Task identifier, system `BOOKING_REFERENCE_SYSTEM` (`booking_repository.py:31`) | Rule book 3.2: "unique among open bookings". The Task `reference` property has no constraint. But the mapper writes identifiers as **shared** `Identifier` nodes keyed by `(system, value)` (`mapper.py` `_flatten_identifier`, `mapping.share(...)`), unique by `0002_identifier_key`. Two bookings with the same reference therefore link to the same Identifier node. `Q-BOOK-BY-REF` (`booking_repository.py:78`) matches `Task {reference}` globally and returns the most recent. | Unique **among open bookings within a tenant** (DEC-131 item 3). The `Identifier` node becomes tenant-scoped (DEC-130 item 5) so tenant A's and tenant B's tasks never join one node. `taken` comes from `BookingRepository.open_references()` (new, bound). | Nine thousand values. At 50 attempts and a handful of open bookings per tenant collisions are negligible. Because it is no longer global, tenants no longer compete for the space. Replies match by exact reference among the phone's open bookings only (DEC-016). |
| Case reference | `new_reference` via `OpenCase` (U11 prompt line 54: "unique among open cases") | `ServiceRequest.reference` **unique forever** (`0022_case_reference_id`, `migrations.py:93`) and never cleared on close (P21: "Scores and the reference never change once recorded"). | `(tenantId, reference)`. **Pre-existing defect, independent of tenancy:** the constraint is lifetime-unique over a 9000-value space, while the rule book says "among open". After roughly 9000 cases `new_reference` would exhaust and raise `Conflict`. Per tenant the clock restarts, but a busy tenant still hits it. Owner decision needed (section 10). |
| Report id | `IdGenerator` | Global, uuid4 | Composite | Stored in `CapacityReported.report_id` (event payload) and in audit `entity_ids`. |
| Command key (`idempotency_key`) | Caller-supplied (`Idempotency-Key` header, R03 DEC-105 item 3, 1-200 visible ASCII) or derived (`prompt:<service>:<due iso>`, DEC-115 item 6) | **Global.** `IdempotencyRecord.key` unique (`0029_idempotency_key`). Durable store keyed by `scoped_key(sub, key)` (DEC-105 item 8); R03 cache `idem:<sub>:<key>`. | `(tenantId, key)`; cache `diucs:<tenant>:cache:idem:<sub>:<key>` | **Existence oracle today:** with a global key a tenant B caller who guesses a tenant A key gets `Conflict("this command key was used for a different report")` (`report_capacity.py:254-257`, decided before any permission or existence check per DEC-106). Composite scope removes it. Keep the fingerprint (DEC-104), add the tenant to it. |
| Consumer marker (`Processed`) | `f"{len(consumer)}:{consumer}:{message_id}"` (`idempotency_store.py`) | Global, `0030_processed_key` | `(tenantId, key)` | Message ids are uuid4 (outbox), so collisions are not expected. Composite for consistency. |
| `SequentialIds` | Test fake | per instance | per tenant prefix | L134. |
| Derived keys | `cancel-<work id>` (`scheduling.py:86` on U03); `recheck:{phone_hash}:{service_id}` (U05 prompt); `diucs:idem:sms:<MessageSid>` (I07 prompt); `idem:<sub>:<key>` (R03) | Global namespace in Redis (`diucs:` prefix only) | `diucs:<tenant>:...` through the cache wrapper | Pre-auth rate-limit counters (pairing, link attempts) live in a named `_global` namespace because the tenant is not known yet. |
| Link token | `new_link_token` `rules/tokens.py:87`: 128 bits, base64url, 22 characters; stored as HMAC-SHA256 hash, unique (`0021_link_token_hash`) | Global | Hash stays globally unique and is the **lookup key that yields the tenant** (DEC-131 item 5). `LinkTokenRecord.tenant_id` added. | Opaque: no tenant id or slug in the token text, so an SMS shows nothing tenant-specific. |
| Pairing code | `new_pairing_code` `rules/tokens.py:111`: six digits, valid 10 minutes (`:32`) | No storage yet (U10, R15 unbuilt) | Bound to the tenant at pairing (DEC-131 item 5). A wall screen is unauthenticated until paired, so the code itself must resolve the tenant: a lookup over **globally** active codes. | See ambiguity list below. |
| Support code | `new_support_code` `rules/tokens.py:135`: eight characters from a 31-character alphabet (about 8.5e11) | No storage yet (O06) | Globally unique among active codes; resolves tenant and the grant | Part of the cross-tenant privilege (DEC-130 item 8). |
| PIN | `identity_policy.py:27` `PIN_LENGTH` 6 digits, stored as keyed hash per `(practitioner_id, device_id)` (`PinStore`, `identity.py:87`) | Per practitioner and device. `Device.id` unique globally (`0023`), `Credential.deviceId` unique globally (`0026`) | Per tenant composite. PINs are never compared across practitioners, so no PIN collision exists. | The device id is the issue, see `DeviceRegistry` in section 4. |

### How a reply finds its tenant (DEC-131)

An inbound SMS carries `To` (our number), `AccountSid`, `From`, `Body`, `MessageSid`.

1. Look up `(AccountSid, To)` in the tenant directory (`TenantDirectory.by_inbound_number`). Never use `From`, the body or any header. No match: fixed empty answer, log the message id only, queue nothing.
2. Verify the webhook signature with **that tenant's** auth token (secret reference from the tenant record). A failure is a fixed-message 403.
3. Bind the tenant. Hash `From` with `PhoneHasher`, find the practitioner **inside the tenant** (`find_by_phone_hash`). Unknown: `dropped`, no write, no message (U05 outcome).
4. Parse and apply the reply policy (D09-D11). A booking reference such as `4821` is matched only among **open bookings for the services this phone holds in this tenant**. If the same four digits are open in another tenant, that is not visible and cannot be matched.

So `4821` from a phone does not need a global lookup. The number called decides the tenant, and the reference only has to be unique within it.

### Ambiguity cases, resolved

| Case | Today | Resolution |
|---|---|---|
| Phone registered to reporter roles in two tenants | `find_by_phone_hash` would raise `Conflict` on two active practitioners with one hash (`repositories.py:113-118`) | Two separate Person records, one per tenant (DEC-131 item 3). The lookup is bound, so no Conflict. A Conflict inside one tenant stays a Conflict. Registration must never report "this phone is already registered elsewhere" (existence oracle). |
| Shared Twilio sender | Single `twilio_from` setting (`bootstrap/settings.py:34`) | Removed by DEC-131: one subaccount and numbers per tenant. A number must be unique across tenants (unique constraint on the tenant record). A retired or ported number needs a "retired_at, still mapped for N days" entry so late replies do not fall into "unknown number". |
| A person replies on the wrong thread (two tenants, two sender numbers, both open prompts) | | The reply is interpreted by whichever tenant's number received it. If that tenant also has an open prompt for the person, a bare figure could be recorded for the wrong tenant's service. Residual, low-medium (clinical). Mitigations: the prompt names the service; U05's grouped-prompt letters; the echo (C3) names the service and value, so a wrong-thread figure is visible to the sender. Record in the hazard log (owner action). |
| A tenant with several numbers | | All map to one tenant. Reply routing is by `To`, so replies to an older number still work while mapped. |
| Link tokens | Hash unique globally | Global hash lookup returns `tenant_id`; bind; then act. Unknown, used and expired give the same page. |
| Pairing codes | Six digits, valid 10 minutes, no store yet | The screen is unauthenticated, so the tenant comes from the code. Rules: (1) a code is unique among all **globally** active codes: on issue, collision means silent regeneration. (2) Brute-force surface grows with the number of tenants with a live code at the same moment (K live codes give a guess K/1e6 chance), so a global attempt limiter and per-source lockout are mandatory, in the `_global` Redis namespace. (3) Spec fixes six digits (domain-rules 7); raising the entropy is an owner question. |
| PINs | Per practitioner and device | No cross-tenant ambiguity once devices are server-issued and tenant-scoped. After the text code is verified on the tenant's number, the practitioner and tenant are known. |
| Text verification codes | `CodeStore` keyed by phone hash | Issued on the tenant's number (DEC-131 item 5). Request needs a tenant hint (tenant-specific app entry); the hint only chooses the sending number. The bound tenant after verification is the tenant of the matched practitioner. The response to "unknown number" and "number known in a different tenant" must be identical. This is the one place a caller-influenced value picks a tenant; DEC-130 item 6 forbids using it as the bound tenant. Flagged for the owner. |
| Support codes | | Resolves tenant plus grant; only the support role may enter one; each use audited in both chains. |
| Delivery receipts | `by_provider_id` global | Resolve tenant by `AccountSid` first (DEC-131 item 2), then match the message id inside that tenant. |
| Same service id in two tenants | Possible only if ids are client-chosen | Composite constraints make it legal. Session ids and cache keys include the tenant. |

---

## 6. DOMAIN RULES AND THRESHOLDS

### Design

Introduce `domain/model/tenant_policy.py`: `TenantPolicy` is a frozen dataclass with one field per overridable value, each defaulting to today's constant, and validation ranges so a tenant cannot set an unsafe value (for example reply window 5 to 120 minutes, ladder steps strictly increasing and not less than the reply window, pressure `watch_from < high_from`). `DEFAULT_POLICY` is the current behaviour. Rule functions take an explicit `policy: TenantPolicy = DEFAULT_POLICY` argument. **Explicit parameters, not ambient lookups**: the domain stays pure and testable, and DEC-007's "named constants, a new decision to change one" survives because the global defaults stay the named constants. The use case loads the bound tenant's policy once per unit of work from the tenant directory.

Two behavioural notes for the owner:
- Rows already scheduled keep the times computed when they were scheduled (`ScheduledWork.due_at` is stored). A policy change affects new schedules and reads, not in-flight rows. A freshness read (`freshness.py:48` uses `REPLY_WINDOW`) will use the new window immediately. During a change the board and the ladder can disagree for up to one cycle. Record an effective-from time with each policy version.
- Many of these values are `[ASSUMED]` pending the clinical safety officer (`domain-rules.md` line 5, DEC-007). Per-tenant override means each tenant organisation is the owner of its own values. Whether a policy change is a change to that tenant's clinical safety case is for the owner and the clinical safety officer. Recommend policy changes are audited and need two people.

### Table

Recommendation key: **F** fixed global (platform or clinical definition, not tenant policy). **D+O** global default with per-tenant override. **S** already per service in the model, optionally a tenant default for new services.

| Constant | File:line | Today | Rec. | Reason |
|---|---|---|---|---|
| `REPLY_WINDOW` | `rules/schedule.py:21` | 30 min. Used by `reply_by`, freshness `_latest_missed_due` (`freshness.py:48`), `RejectLate` (`reply_policy.py`, imports it), grouped prompts (`multi_service.py`) | **D+O** | Reporters' response culture and the shift lead's staffing differ. It drives link expiry (U03 `reply` = link expiry, DEC-115 item 2) and the "By HH:MM" in SMS. |
| `REMINDER_AFTER`, `PHONE_TASK_AFTER`, `ESCALATE_AFTER` (the ladder +30, +60, +90) | `schedule.py:22-24`; `ladder_times` `:119-125` | 30, 60, 90 min | **D+O** | Depends on who covers the phone queue in each organisation. Validate strictly increasing and the first step not before the reply window ends. |
| `TWICE_A_DAY_SECOND` | `schedule.py:25` | 14:00 | **D+O** (low value) | Operational. Could instead be per service; per tenant is cheaper. |
| `EVERY_N_HOURS_STEP`, `SEARCH_DAYS` | `schedule.py:27`, `:31`; `opening_hours.py:21` | 2 h, 8 days | **F** | The step defines the cadence name `every-2-hrs` (`codes.py` `Cadence`). Search days is algorithmic. |
| `STALE_WARNING_AFTER` | `freshness.py:21` | 2 h | **D+O** | Display and safety judgement of "old data". |
| `LIMITED_LEVEL_PERCENT_DEFAULT` | `model/service.py:20` (field `limited_level_percent` `:108`) | 80 | **S**, plus a tenant default for new services | Already per service. |
| usual range | `ServiceProfile.usual_range` | per service | **S** | Already per service. |
| `WATCH_FROM`, `HIGH_FROM` | `rules/pressure.py:26-27` | 3, 5 limited-or-worse services | **D+O, firmly** | Absolute counts over the tenant's own services. A tenant with six services and one with sixty cannot share them. Consider offering a share-of-services form (owner). Also feeds the exec alert threshold (`alerts.py`). Under collaboration, the set the count runs over must be defined. |
| `CORRECTION_WINDOW` | `rules/reply_policy.py:25` | 15 min `[ASSUMED]` | **D+O** | Operational. |
| `MAX_CONSECUTIVE_CONFIRMS` | `reply_policy.py:26` | 2 | **D+O, bounded 1-3** | A safety control against stale confirms. Not lower than 1. Appears in C6 text ("Y was used twice already", `templates.py`): the wording must be parameterised or the value fixed. |
| `MANY_CHANGES_WINDOW`, `MANY_CHANGES_COUNT`, `PHONED_WINDOW` | `rules/report_flags.py:21-23` | 5 min, 3, 60 min `[ASSUMED]` | **D+O** | Tuning for how many false flags a lead tolerates. |
| `BOOKING_REPLY_WINDOW`, `PHONE_PROMPT_AFTER` | `rules/booking_rules.py:18-19` | 10 min, 5 min | **D+O** | Operational. The 10-minute withdrawal-to-lead rule (rule book 3.2) is not coded yet: put it in the policy when U21 lands. |
| booking and case reference digits | `booking_rules.py:22-23`, `events.py:40`, `templates.py` (`REFERENCE_FORMAT`), `case_repository.py:69`, parser `MIN/MAX_REFERENCE_DIGITS` (`reply_parser.py`) | four digits, no leading zero | **F** | Format is repeated in five places and messages assume it. A per-tenant digit count would touch all of them. Revisit globally if volume needs it (section 5). |
| `GROUP_WINDOW`, `MAX_SERVICES_PER_PHONE` | `rules/multi_service.py:19-20` | 10 min `[ASSUMED]`, 3 | **D+O** | Operational. `MAX_LETTERED_ITEMS` (26) and `SERVICE_LETTERS` (A to H, `reply_parser.py`) are **F**: wire format. |
| `REVIEW_REMINDER_BEFORE`, `REVIEW_PERIOD_MONTHS` | `rules/criteria_workflow.py:19`, `:21` | 14 days `[ASSUMED]`, {3, 6, 12} | **D+O** | Governance cycle of each organisation. The `review_by` date itself is data on each criteria version (`model/criteria.py`), set per service at approval: already per service. |
| `INVITATION_VALID_FOR` | `rules/registration.py:24` | 48 h | **F** | The SMS text says "Valid for 48 hrs" (`templates.py:279`, `:287`). Make it D+O only if the template takes the value as a field. |
| Re-verification of a service (`WorkKind.REVERIFY`, domain-rules line 241, "N to be set, default 180") | not coded | | **D+O** | Not built. Note the code's identity re-verification is a different value, 30 days (`identity_policy.py:26`, domain-rules line 249). Keep the two names distinct. |
| `CODE_VALID_FOR`, `CODE_MAX_TRIES`, `CODE_RESEND_AFTER`, `PIN_MAX_TRIES`, `PIN_LENGTH`, `REVERIFY_EVERY` | `rules/identity_policy.py:22-27` | 10 min, 5, 60 s, 5, 6, 30 days | **F** (a tenant may only tighten, later) | Security baseline. K1 text says "works for 10 minutes" (`templates.py:298`). |
| `PAIRING_CODE_VALID_FOR`, `LINK_TOKEN_BYTES`, `SUPPORT_CODE_*` | `rules/tokens.py:32`, `:38-41` | 10 min, 16 bytes, 8 chars | **F** | Security. |
| `NOT_UPDATED_HOURS`, `ACK_MINUTES`, `QUIET_START/END`, `CRITICAL_KINDS`, `ESCALATION_LADDER` | `rules/alerts.py:29-33` | {2, 4}, {10, 15, 30}, 22:00-06:00, {service-closed, system-pressure}, subscriber, deputy, shift-lead | allowed sets **F**; `CRITICAL_KINDS` **D+O**; new-user defaults (`default_preferences` `:77`) **D+O** | The allowed choice sets are the spec. Which kinds are critical is organisational. The escalation ladder stays inside one tenant. |
| `TAKE_TIMEOUT`, `NOTE_MAX` | `rules/clinical_queue.py:19`, `:20` | 10 min, 280 | `TAKE_TIMEOUT` **D+O**, `NOTE_MAX` **F** | Operational. The queue pool may span organisations under collaboration. |
| `AGE_BAND_BOUNDS`, `AGE_OVERLAP_WARNING` (hard criteria filter) | `rules/criteria_filter.py:13`, `:21` | band definitions | **F** | Clinical definition. A tenant's criteria data (age limits, districts, accepts and excludes) is per service already. |
| Category order for the board | `query_board.py` `_CATEGORY_ORDER` over `ServiceCategory` (`codes.py`) | enum order | **F** for now | Code systems are shared reference data (DEC-130 item 5). Tenant-specific categories are an owner question. |
| Time zone: `LONDON` | `rules/london_time.py:13`; used by `schedule.py`, `opening_hours.py`, `alerts.py` (quiet hours), `criteria_workflow.py` (review day derived by callers), `report_capacity.py` and `send_prompts.py` through `format_hhmm`; 84 test references | Europe/London everywhere; `AvailableTime` documents "London local" (`model/service.py` docstring) | **F** in phase 1 | See section 9. |
| Template wording | `templates.py:97-322` | "DIUCS:", "Dorset urgent care capacity" (`:286`), "SystmOne" (`:112`, `:119`, `:243`), "SPOA shift lead" (`:322`) | parameterise 3 items; leave the brand | See section 7. |

---

## 7. EVENTS AND MESSAGES

### Domain events (D25, `domain/events.py`)

The ten events carry ids, counts and codes only. **The tenant must not be added to the payload.** Reasons: `to_payload()` output is what `from_payload` rebuilds (`events.py:426`), consumers must take the tenant from the verified message property, and a tenant in the payload would be a second, forgeable source.

Where the tenant does appear:

| Place | Change |
|---|---|
| `OutboxMessage` (`outbox.py:26`) | Required `tenant_id`, set from `current_tenant()` in `outbox_message_for` (`:45`) and by `schedule_work`/`cancel_work` and the two inline `OutboxMessage(...)` constructions (`report_capacity.py:186`, `send_prompts.py` `_send`). The graph node carries `tenantId` (DEC-130 item 1). |
| `BusMessage` (`event_bus.py:29`) | Required `tenant_id`. The relay writes it as a Service Bus application property. |
| Session id (`events.py:419`) | `f"{tenant_id}:{service_id}"` on `capacity.events` so ordering is per tenant and service. |
| Scheduled messages | The `schedule` call carries the same property, so a message that fires later binds the same tenant. |
| Audit (`audit.py:71`) | `actor.tenant_id` inside the canonical entry; chain per tenant with genesis `genesis_hash_for(tenant)`. Legacy tenant keeps `"0"*64`. `ensure_audit_head` runs per tenant at onboarding, not once at startup. The head write lock (`audit_log.py` docstring, "write hot spot by design") is now per tenant, which also removes cross-tenant write contention. |

What must not carry tenant-identifying data:
- **SMS text and email (D15, D16):** no tenant id, slug, subaccount sid, number, or any other tenant's name or service. The recipient's own service name is allowed (`{service}` in C1 and others). The existing guard (`privacy_guard.py`) blocks patient-data shapes; add a second test that no rendered output contains a tenant id and that `render` has no field that accepts one.
- **Link text:** opaque token; the host is the tenant's configured link host (open question) but nothing tenant-specific is in the path.
- **Event payloads and SSE messages:** no tenant. The SSE message is `{"type", "service_id", "at"}` (`board_projector.py:136-141`) on a tenant-scoped channel.
- **Log lines and error text:** ids only, never a tenant name.
- **Wording that names a place or a system:** "Dorset" in I2 (`templates.py:286`), "SystmOne" in B1, B2 and the B2 email (`:112`, `:119`, `:243`), "SPOA" in K4 (`:322`) are tenant-specific facts hard-coded in templates. Replace with three tenant fields (`region_name`, `referral_system_name`, `coordination_team_name`) supplied by the caller from the tenant configuration, or reword neutrally. The brand prefix "DIUCS:" and the button colour (`BUTTON_STYLE` `:30`) can stay platform-wide unless the owner wants white-labelling. These templates are marked IG-pending (DEC-037), so changing wording needs IG approval anyway.
- **`SendMessage` outbox payload** contains `text` with the link token (needed to send); it never carries a phone number or hash (DEC-115 item 9). Unchanged. Tenant rides in the property.

How consumers rebuild tenant context from a message:
1. `to_bus_message` (I04 `servicebus_runner.py`) reads the `tenant_id` application property. Missing: `MalformedMessage` (dead-letter, fixed reason).
2. `IdempotentConsumer.handle` (I04 `consumer.py`) validates it against the tenant directory (cached), binds it, **then** calls `uow_factory()`. Unknown or inactive tenant: `PermanentError` with a fixed reason, never payload text.
3. `mark_if_new(message.id, consumer)` runs inside the bound unit of work (composite key).
4. The handler decodes the payload with `from_payload` and acts. The payload is never trusted for tenant.
5. The binding ends with the message (context manager). Tasks spawned inside inherit it, which is intended. Tasks created at start-up outside any binding are unbound and fail closed.

I04's current code has no tenant hook, so it is the first thing the sweep must change after the seam. It was built on the single-tenant model by decision (DEC-130 item 10).

---

## 8. CACHES AND PROJECTIONS

| Item | Today | After |
|---|---|---|
| Board cache key | `BOARD_CACHE_KEY = "board:v1"` (`board_projector.py:31`), TTL `BOARD_CACHE_TTL` 60 s (`:33`), used at `:135`, `:158`, `:169`; physically `diucs:cache:board:v1` (`redis_cache.py:20`, `_CACHE_KEY = "cache:{}"` `:22`) | `diucs:<tenant>:cache:board:v1`. Add the tenant by the cache wrapper (section 4), not by each caller. Keep the logical name `board:v1`; the physical key changes, so the old key simply expires. |
| Pub/sub channel | `BOARD_UPDATES_CHANNEL = "board.updates"` (`cache.py:12`); `GET /events` subscribes to it for every role (`routes_events.py:162`) and relays to all streams | `diucs:<tenant>:chan:board.updates`. The route subscribes with the actor's bound tenant. Today one stream shows every service change to every viewer: after tenancy a viewer would see other tenants' service ids and timing if this stayed global. |
| Role-specific filter (L130) | One key serves every role (DEC-099 item 7): only `ANONYMOUS_LINK` is refused (`query_board.py:70`, `board_projector.py:147`) | Define `board_cache_key(audience)` now: `board:v1:all` for the current board; any role, service or flag filter uses `board:v1:role:<role>` or `board:v1:svc:<hash of the allowed service ids>`, or is not cached. Because the wrapper already prefixes the tenant, the key never crosses tenants. Under grants, the board a viewer sees depends on the grants in force: add a `grants_rev` to the audience, and delete the key when a grant changes, otherwise a revoked collaborator's data stays visible for up to 60 s. |
| Rebuild trigger | `handle(event_type, payload)` is called by a consumer for 7 event names (`REBUILD_EVENTS`); rebuilds with `WALL_ACTOR` | The consumer binds the tenant from the message. `handle` builds `wall_actor(current_tenant())`. Under grants, one capacity event in tenant P triggers rebuilds for every tenant whose board includes P (fan-out list from `CollaborationGrants`). |
| `get_board(actor)` | Checks anonymous role, reads cache, falls back to QueryBoard | First `require_actor_in_bound_tenant(actor)`. |
| Other keys | `recheck:{phone_hash}:{service_id}` (U05), `diucs:idem:sms:<sid>` (I07), `idem:<sub>:<key>` (R03 DEC-105 item 4), sessions, attempt counters (I13), locks and fencing counters (`redis_cache.py` `_LOCK_KEY`, `_FENCE_KEY`) | All under `diucs:<tenant>:`. Platform-level keys (outbox relay leader lock, pre-auth limiters for link, pairing and sign-in) use `diucs:_global:` through the named unscoped path only. |
| Cache contract | `InMemoryCache` and `RedisCache` share `tests/contract/test_cache_contract.py` | Two-tenant cases for get/set/delete/publish/subscribe/locks/fence on both. An unbound call raises on both. |

The cache is not a store of record (DEC-001), so losing keys loses no fact. A leak through the cache is still a leak: the board JSON holds service names, status, figures and ids.

---

## 9. SCHEDULING AND TIME

### Carrying the tenant through scheduled work

1. `schedule_work` (U03 `scheduling.py:35`) runs in a bound unit of work: the `ScheduledWork` row and the `ScheduleWork` outbox message both get the tenant. `due_at` is stored UTC.
2. The relay (I03) iterates tenants from `TenantDirectory.list_active()`, binds each in turn, reads that tenant's `pending()` and publishes with the `tenant_id` property. One tenant's failures (a message at `MAX_ATTEMPTS` 10 goes dead, `outbox.py:18`) cannot block others. Fairness: cap messages per tenant per round.
3. When a scheduled message fires, the scheduled-work consumer (I05) reads `tenant_id` from the property, binds, loads the `ScheduledWork` by id inside the tenant (a miss is ignored: "handlers ignore work that is not scheduled", `scheduling.py` docstring), and dispatches by `WorkKind` (`work.py`).
4. The sequence number stored on the row (`ScheduledWork.sequence_number`, `work.py:39`) is only ever used from that row, so a cancel cannot cross tenants.
5. **System sweeps** (`NOT_UPDATED_CHECK`, `CRITERIA_REVIEW_REMINDER`, `REVERIFY`, `ALERT_ESCALATE`, `CLINICAL_RETURN`: all in `WorkKind`, `work.py:15-25`): written as per-tenant jobs scheduled by each tenant, or as one loop `for tenant in list_active(): with bind_tenant(tenant): ...` with a per-tenant try/except that logs the id only.
6. **No process-wide state that outlives a binding.** Today the use cases hold only ports and a `random.Random`. Keep it so: no module-level dict caches of tenant data, and the tenant directory cache is keyed by tenant and holds configuration only.
7. Context propagation pitfalls to test: `asyncio.create_task` and `gather` copy the context at creation (fine inside a binding); `asyncio.to_thread` copies; a raw `run_in_executor` does not. Receivers started before any binding (`ServiceBusRunner._loop`, I04) hold no tenant and must bind per message.
8. Noisy neighbour: shared queues (`QUEUES`, `TOPICS`, `event_bus.py:15-26`) mean one tenant's burst can delay another. Either use a session id per tenant on the work queues or cap concurrency per tenant. Raise with the infrastructure audit.

### Time zone and region

London is hard-coded, not per tenant:
- `LONDON = ZoneInfo("Europe/London")` (`london_time.py:13`); `AvailableTime` times are "London local" (service model docstring); opening hours, schedule, quiet hours and review days convert through it.
- The same zone shapes message text: `format_hhmm` renders London wall time into every SMS (`report_capacity.py` echo, `send_prompts.py:124-135`).
- DEC-131 makes each tenant a separate legal entity. The owner has described UK NHS organisations; the audit has no evidence of a non-UK tenant.

Recommendation: keep Europe/London fixed for phase 1, write it as an explicit platform assumption in the tenant record (`timezone: "Europe/London"`, read but not yet honoured), and do not thread it through the rules now. Threading a zone argument later touches the six modules above, about 60 call sites in `src`/tests directly, and the 84 test references to `LONDON`, roughly 12 to 16 hours (TEN-A04 would grow). If a non-UK tenant is on the roadmap, do it inside TEN-A04 instead. Owner question.

---

## 10. RISKS AND OPEN QUESTIONS (ranked)

### Risks

1. **Board cache, channel and stream are global (critical).** `board:v1` (`board_projector.py:31`), `board.updates` (`cache.py:12`) and the SSE relay (`routes_events.py:162`) are constants shared by every caller. Forgetting one of the three leaks a whole tenant's board to another. Fix at one point, the cache wrapper, with a two-tenant contract test. The projector's worker path also has no tenant source (`WALL_ACTOR`, `board_projector.py:46`).
2. **Global uniqueness and lookups are existence oracles or cross-tenant joins.** (a) `IdempotencyRecord.key` global: a guessed key returns `Conflict` across tenants (`report_capacity.py:254`). (b) `Device.id` global and an owner lookup returning the practitioner id (`credential_store.py`). (c) `Identifier (system, value)` is a shared node (`mapper.py` `mapping.share`), so a booking reference joins tasks of different tenants to one node, which DEC-130 item 1 forbids. (d) `Q-BOOK-BY-REF` and `Q-CASE-BY-REF` match references globally. (e) U02's `lock_service` before the existence check is a timing channel if not tenant-bound. All are closed by composite keys and tenant-bound statements, but the list shows where the generated query test and the differential use-case test earn their keep.
3. **Workers and system actors have no tenant source.** `BusMessage` has no tenant (`event_bus.py:29`); I04's runner and consumer build the unit of work before any tenant is known; I03 and I05 do not exist yet; U03 says the scheduled-work consumer "passes a system actor" with no tenant. Risk of an "unscoped system actor" workaround creeping in. Mitigation: required fields plus the import-restricted `unscoped`.
4. **The audit chain is one global chain** with one head and a global `seq` (`audit_log.py` docstring and `0020_chain_seq`, `0017_audit_head_id`). Per-tenant chains, per-tenant genesis, composite constraints and a legacy-tenant mapping must keep old links verifying. `_parse_entry` (`audit_log.py:232`) must tolerate entries with no tenant. Getting this wrong silently breaks `verify_chain`, which is a clinical-safety control.
5. **Collaboration model undecided.** It changes `Actor` (extra visibility), `QueryBoard` and `BoardProjector` (whose data, fan-out, cache keys), booking (cross-organisation writes), `FilterOptions`, alerts, week summary, clinical queue and audit replay (section 3.4). Reworking those before the model is chosen risks doing the board twice.
6. **Thresholds are module constants inside pure functions** (`REPLY_WINDOW` imported by four modules). Per-tenant policy touches about 14 rule functions and roughly 100 test call sites (`assess_freshness` 22, `is_in_hours` 25, `system_pressure` 16, `LONDON` 84 references). Behaviour during a policy change (in-flight rows keep old times) can make the board and ladder disagree for a cycle. Also a clinical-safety governance question, not only a coding one.
7. **Reference space and lifetime uniqueness.** The case reference is lifetime-unique over 9000 values today (`0022_case_reference_id`). It exhausts independent of tenancy. Booking references have no such constraint but share Identifier nodes (risk 2c).
8. **Unauthenticated tenant resolution paths**: link tokens (128 bit, low risk), pairing codes (six digits, brute-force surface grows with tenants), text verification code requests (tenant hint). Each needs rate limiting in a global namespace and identical responses.
9. **Test blast radius.** Required `Actor.tenant_id` breaks 19 test constructions in 10 files and the integration tests that assert on global counts (`count_nodes`), plus parallel runs sharing one Neo4j (DEC-130 item 9, `SequentialIds` collisions).
10. **Wrong-thread replies** (a person with two tenants and two numbers replies on the wrong thread): low probability, clinical effect if a figure is recorded for the wrong tenant's service.
11. **Idempotency decode compatibility.** Stored results decode by `module:qualname` and field names (`idempotency.py:74-`). Renaming a result class or adding a required field breaks replay of stored commands.

### Questions for the owner

1. Which collaboration model: grants plus read-only projections, or a network above organisations? Section 3.4 shows where it bites. Until chosen, no use case reads another tenant.
2. May any role hold cross-tenant access (DEC-130 item 8)? Proposed shape in section 2. Does it include a platform operator who is not part of any tenant?
3. Policy governance: who may change a tenant's thresholds, with two-person approval, and does each tenant's clinical safety officer own them? Which of the "D+O" values in section 6 do you want exposed at all in phase 1? A minimal first set could be reply window, ladder minutes and pressure thresholds.
4. Pressure thresholds: absolute counts per tenant, or a share of services? Over which set of services once organisations collaborate?
5. Case reference: keep lifetime uniqueness (and accept exhaustion), or unique among open cases only (which needs dropping the constraint and enforcing under a lock)? What is the expected case volume per tenant?
6. Is Europe/London fixed for every tenant, now and in the plan?
7. Reporter sign-in when a person works for two tenants: separate sessions per tenant with a tenant-specific entry point? (Staff map to exactly one tenant, DEC-130 item 6.)
8. Link host: one shared host with an opaque token, or a host per tenant?
9. Template wording: replace "Dorset", "SystmOne" and "SPOA" with tenant fields (needs IG approval since the templates are IG-pending), and do you want any per-tenant brand?
10. Phone-hash key: keep one platform key (simpler) or derive per tenant (isolation, but a re-hash migration)?
11. Pairing code entropy: keep six digits (spec) with strict global rate limiting?
12. Existing data: what is the legacy tenant's id and name, and does its audit chain keep its old genesis?
13. Tenant offboarding and erasure against an append-only audit chain.

---

## 11. PROPOSED TASK BREAKDOWN

Order is dependency order. The adapters seam (`run_query`, `NamedQuery` `$tenant` rule, harness) is owned by the other audits and DEC-130 item 10 puts it first. Task ids here are proposals.

| Id | Title | Files | Hours | Depends on |
|---|---|---|---|---|
| TEN-A01 | Tenancy kernel: `TenantId`, bind, `current_tenant`, `TenantNotBound`, import-restricted `unscoped`, architecture tests | `application/tenancy.py` (new), `tests/unit/application/test_tenancy.py`, `tests/architecture` | 4 | the adapters seam (shares the context variable) |
| TEN-A02 | Actor and token carry the tenant: required `Actor.tenant_id`, `BffClaims.tenant`, encode/decode, `actor_from_claims`, `wall_actor`, `system_actor`, `require_actor_in_bound_tenant`, fix 4 src and 19 test construction sites | `application/actor.py`, `domain/rules/bff_token.py`, `adapters/inbound/fhir_rest/auth.py`, `use_cases/board_projector.py`, `tests/**` | 5 | TEN-A01 |
| TEN-A03 | Tenant, policy and directory: `Tenant`, `TenantPolicy` with defaults equal to today's constants and bounds, `DEFAULT_TENANT_ID` for legacy data, `TenantDirectory` port (by id, by inbound number and AccountSid, list_active) | `domain/model/tenant.py`, `domain/model/tenant_policy.py`, `application/ports/outbound/tenant_directory.py` | 6 | TEN-A01 |
| TEN-A04a | Thread policy: schedule, freshness, status, pressure, reply policy (the ones the board and prompts use) | `domain/rules/schedule.py`, `freshness.py`, `status.py`, `pressure.py`, `reply_policy.py`, tests | 7 | TEN-A03 |
| TEN-A04b | Thread policy: booking rules, report flags, multi-service, criteria workflow, alerts, clinical queue | `domain/rules/booking_rules.py`, `report_flags.py`, `multi_service.py`, `criteria_workflow.py`, `alerts.py`, `clinical_queue.py`, tests | 8 | TEN-A03 |
| TEN-A05 | Port contracts: `OutboxMessage.tenant_id`, `BusMessage.tenant_id`, `outbox_message_for`, session id `<tenant>:<service>`, `LinkTokenRecord.tenant_id`, `BookingRepository.open_references`, docstrings stating implicit binding on every repository, `CodeStore` key note | `ports/outbound/outbox.py`, `event_bus.py`, `repositories.py`, `tokens.py`, `domain/events.py` (`session_id_for`), `domain/rules/tokens.py` | 6 | TEN-A01 |
| TEN-A06 | Audit entry and chain contract: `tenant_id` in canonical actor, `genesis_hash_for`, per-tenant `verify_chain` semantics, legacy compatibility, `_parse_entry` tolerance | `ports/outbound/audit.py`, `adapters/outbound/audit_neo4j/audit_log.py` (with the adapters audit), tests | 4 | TEN-A02, TEN-A05 |
| TEN-A07 | Idempotency and consumer markers: tenant in fingerprint, composite-key contract, decode-compatibility test, scoped early read | `use_cases/report_capacity.py` (`_fingerprint`), `application/idempotency.py`, tests | 3 | TEN-A02 |
| TEN-A08 | Rework U01 ReportCapacity: tenant guard, NotFound ordering invariant, validate `performer_role_id`, policy, two-tenant tests | `use_cases/report_capacity.py`, `tests/integration/application/test_report_capacity.py` | 5 | TEN-A02, TEN-A04a, TEN-A07 |
| TEN-A09 | Rework U08 and U09: board audience key function, `wall_actor(current_tenant())`, `get_board` guard, pressure from policy, cache wrapper tests | `use_cases/query_board.py`, `use_cases/board_projector.py`, tests | 6 | TEN-A02, TEN-A04a, the adapters cache wrapper |
| TEN-A10 | Templates: tenant fields for region, referral system, coordination team; no-tenant-data test for rendered output; D15, D16, D17 rework | `domain/messages/templates.py`, `privacy_guard.py`, tests | 5 | TEN-A03 |
| TEN-A11 | References and token resolution: tenant-bound reference generation, `open_references` use, link-token resolve then bind, pairing code global-active design, reference-space decision implemented | `domain/rules/booking_rules.py` (docs/tests), `ports/outbound/tokens.py`, pairing design note | 6 | TEN-A05, owner answer 5 |
| TEN-A12 | Two-tenant differential test over every use case (same result as a random id, no lock, no writes) and the held-lock timing test | `tests/integration/application/test_tenant_isolation.py` | 6 | TEN-A08, TEN-A09 |
| TEN-A13 | Rework U02 ConfirmCapacity after it merges: tenant-bound lock and trailing-count statements, replay across tenants, held-lock test | `use_cases/confirm_capacity.py`, `adapters/outbound/graph_store/capacity_repository.py` (with the adapters audit), tests | 3 | U02 merged, TEN-A08 |
| TEN-A14 | Rework U03 SendPrompts and scheduling after it merges: per-tenant `link_base_url`, derived key tenant-scoped, ladder and next prompt from policy, `schedule_work` tenant | `use_cases/send_prompts.py`, `application/scheduling.py`, tests | 4 | U03 merged, TEN-A04a, TEN-A05 |
| TEN-A15 | Legacy migration of the domain contract: default tenant id and name, legacy audit genesis, backfill rules | `domain/model/tenant.py`, migration note | 2 | TEN-A03, TEN-A06 |
| TEN-A16 | Collaboration seam (placeholder, **not sized**): `Visibility`, `CollaborationGrants`, board fan-out, booking across organisations | `application/**` | TBD | owner decision 1 |

Total sized: 80 hours (4+5+6+7+8+6+4+3+5+6+5+6+6+3+4+2).

### Delivered tasks that need rework

| Task | What changes |
|---|---|
| U01 | TEN-A08, TEN-A07 (and its fingerprint, `report_capacity.py:225`). |
| U08, U09 | TEN-A09. L130's "own key for a filtered view" becomes `board_cache_key(audience)`. |
| D04, D05, D07, D08, D11, D12, D14, D21, D23, D24, D28 | TEN-A04a and TEN-A04b: policy parameter (D07 only where it calls D05; D14's reference format stays fixed). |
| D15, D16, D17 | TEN-A10. |
| D25 | `session_id_for` (`events.py:419`), plus a test that no payload carries a tenant (TEN-A05). |
| D26 | `LinkTokenRecord.tenant_id` (TEN-A05, TEN-A11). |
| D01, D02, D03, D06, D09, D10, D13, D18, D19, D20, D22, D27 | No tenancy change. D03 and D27 only if the owner later wants a zone or tighter limits. |
| F06 (clock and ids) | None to ports. Harness id prefix per tenant (test support). |
| P01-P04, P13, P14, P21 (repository ports) | Docstring and `open_references` (TEN-A05); adapter work belongs to the other audits. |
| P05 (audit), P06 (outbox, unit of work), P08 (event bus, scheduled work), P09 (cache port), P10 (link tokens), P15 (idempotency), P16 (identity stores) | Contract changes in section 4; adapter changes in the other audits. |
| R02 | `BffClaims.tenant`, `actor_from_claims`, `current_actor` (TEN-A02); R03 (`idem:<sub>:<key>` and the durable key), R06 (channel per tenant) are adapter-side. |
| I01, I02, I06 | Adapter-side (cache wrapper, bus properties, per-tenant subaccount). Listed because their contracts are in section 4. |

### In-flight tasks (DEC-130 item 10: they finish on the current model and are migrated by the sweep)

U02 (TEN-A13), U03 (TEN-A14), I04 (adds `tenant_id` read in `to_bus_message` and bind before `uow_factory()`, adapters audit), W02 (tenant inside the sealed backend token; no `domain`/`application` change).

### Planned tasks whose prompts need amending (not delivered, touching these layers)

Add to every use-case prompt a common clause: the use case never accepts a tenant in its command; it starts with `require_actor_in_bound_tenant(actor)`; ids from other tenants read as NotFound (class, message, query count and no lock identical to a random id); it gets thresholds from the tenant policy; events and outbox records carry `tenant_id` as a property, not in the payload; a two-tenant test is part of "done". Then the specific amendments:

| Tasks | Amendment |
|---|---|
| U04, U06 | Ladder, group window and phone-load limit from `TenantPolicy`. |
| U05, U22 | The tenant is already bound by the inbound webhook from `To` and `AccountSid` (DEC-131 item 2); `from_phone_hash` is looked up in that tenant only; the `recheck:` cache key goes through the tenant cache; booking replies match among the phone's own open bookings only, never `get_by_reference`. Unknown phone in this tenant is `dropped`. |
| U07, U39 | Flags windows from policy. |
| L01, L02 | Resolve the token hash with the explicit unscoped lookup, bind the returned tenant, identical response for unknown, used and expired. |
| U10, R15 | Pairing code resolves the tenant through a global lookup of active codes, unique among active codes, global attempt limiter. |
| O01 | Add an opaque `tenant.id` span attribute; no tenant name; allow-list update. |
| U11, U13, U14 | Case reference unique within the tenant, per owner answer 5. Cases never cross tenants. |
| U12 | Mark clearly which organisation's criteria and capacity were read; collaboration model dependent (section 3.4). The audit snapshot must record the source tenant. |
| U15, U16, U23-U26, U28-U31 | Inside one tenant. U16: a phone held by another tenant is not a Conflict and is never mentioned. U24: invitation text from the tenant's number; wording fields per TEN-A10. U29: test prompt sent from the tenant's number. |
| U17-U21 | Reference from `open_references()` of the tenant. The cross-organisation booking question must be answered first (owner decision 1). U19 timers from policy. |
| U27 | The one-transaction registration write is tenant-bound; ODS lookups use shared `Terminology`. |
| U32, U37 | Server-issued, tenant-scoped device ids. PIN lock unaffected. |
| U33, U34 | Alert evaluation per tenant. `CRITICAL_KINDS` and defaults from policy. Escalation stays in the tenant. |
| U35, U43 | Collaboration-dependent. If they aggregate across tenants they need the cross-tenant privilege; otherwise per tenant only. |
| U40 | Clinical queue per tenant until the collaboration model says otherwise. |
| U42 | Audit replay per tenant chain; record the source tenant of each datum. |
| O06, R18 | Cross-tenant by design (DEC-130 item 8): grant record, two-chain audit, code globally unique among active codes. |
| O07, O08 | Aggregates per tenant, no cross-tenant join. |
| P17, P18, P19, P20 | New repositories written tenant-bound from the start (`$tenant` in every statement); `P19` push subscriptions are tenant-bound (DEC-131 item 5). |
| I03, I05, I10 (adapters, listed because they implement this layer's contracts) | I03 iterates tenants and writes the tenant property; I05 binds from the property; I10 resolves the sender from the bound tenant's configuration. |

---

## What could not be read or verified

- Live local ledger (the delivered set above is from `origin/ledger-refresh`, 76 tasks; `main`'s own ledger shows 48).
- `origin/task/U02-...`, `U03-...`, `I04-...`, `W02-...` do not exist as remote refs. Local `task/*` branches were used.
- Adapter internals (graph store statements, Redis, Service Bus, Twilio, FHIR routes) were read only where they define a contract the application layer depends on. They belong to the other audits. In particular the exact Cypher of `Q-CAP-LOCK-SERVICE`, the owner query in `credential_store.py`, and the shared `Identifier` node behaviour were read from source but not executed.
- Nothing was run (no tests, Docker, app). Test counts are `def test_` counts and so undercount parametrised cases.
- The prompts for tasks not listed in section 3.4 and section 11 were not read; only U05, U11, U17, I07, P12 were read in full or in part.
