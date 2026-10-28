# Tenancy audit G: task-by-task sweep of all 215 tasks

Repository `/home/user/overwatch`, `main` at 2cf069e (DEC-130, DEC-131 and DEC-132 read). Statuses come from `delivery.py show <ID>` run on 2026-10-28 (the live ledger lives in the git common directory; `docs/delivery/STATUS.md` and `docs/delivery/ledger.jsonl` are older backups and disagree with it). Read-only audit: no code, test or ledger was changed.

## How to read the table

- **Impact**: NONE (no change), LOW (one or two statements, a config value or a test), MEDIUM (a repository, key scheme or use case changes), HIGH (the seam itself, an audit/outbox/session key scheme, or an unauthenticated entry point).
- **Action**: REWORK-DELIVERED (code already delivered must change), AMEND-PROMPT (the task is not delivered, so its prompt gets the amendment paragraphs in section 2 plus the task-specific change shown), NO-CHANGE.
- **Depends on**: SEAM (tenant binding, run_query injection, registration check, two-tenant test, harness), SCHEMA (composite constraints, backfill), AUTH (token, session and link-record claims), CONFIG (per-tenant configuration and secret references, DEC-131), LIFECYCLE (tenant creation and admin), NETWORK (DEC-132 network scope, grants, projections).
- **Extra hours**: for REWORK-DELIVERED, hours to change the delivered code and its tests once the seam exists. For AMEND-PROMPT, hours added to the task's original estimate. These are my estimates (about 0.25 h per statement plus fixture and test work), not measurements. The seam, schema, config, lifecycle and network work that is not one of the 215 tasks is listed in the New rows section below and counted separately.
- A status of `stale` means the claim lapsed (I04 and I09 are stale with review requested and no verification recorded).

## S0 Foundations

| ID | Stage | Title | Status | Impact | What changes | Action | Depends on | Extra h |
|---|---|---|---|---|---|---|---|---|
| F01 | S0 | Backend project scaffold | delivered | NONE | Scaffold and error classes only. | NO-CHANGE | - | 0 |
| F02 | S0 | Architecture import rules enforced by tests | delivered | LOW | Add an architecture test that only driver.py, migrations.py and health.py execute Cypher, so the run_query tenant injection (DEC-130 item 2) cannot be bypassed by a new `tx.run` call. | REWORK-DELIVERED | SEAM | 1 |
| F03 | S0 | Front-end project scaffold | delivered | NONE | Front-end scaffold; no tenant data. | NO-CHANGE | - | 0 |
| F04 | S0 | Local infrastructure with Docker Compose | delivered | LOW | Topology is unchanged (the tenant rides in a message property, not in entity names), but servicebus-config.json needs a `network-projector` subscription on capacity.events (sessions), criteria.events and registration.events (DEC-132 item 4). | REWORK-DELIVERED | NETWORK | 0.5 |
| F05 | S0 | CI pipeline | delivered | NONE | CI already runs the whole suite, so the generated two-tenant test runs in the `backend` job unchanged. | NO-CHANGE | - | 0 |
| F06 | S0 | Clock and id ports, London time helpers | delivered | NONE | Clock, ids and London time; tenant-neutral. | NO-CHANGE | - | 0 |
| X01 | S0 | Fix London wall-clock property test on other UK change days | delivered | NONE | Test-only fix to a pure rule. | NO-CHANGE | - | 0 |
| F07 | S0 | Local code systems and Coding value object | delivered | NONE | Code systems are shared read-only reference data (DEC-130 item 5). | NO-CHANGE | - | 0 |
| F08 | S0 | Settings and composition root skeleton | delivered | LOW | Container gains the tenant-context accessor and a TenantConfig/secret-reference port (DEC-131 item 4); Settings must hold no default tenant, and the single `sms_provider`/`base_url` settings stop being the per-tenant source. | REWORK-DELIVERED | SEAM+CONFIG | 1 |
| G01 | S0 | Neo4j adapter base: driver, named queries, migrations | delivered | HIGH | THE SEAM. run_query adds `tenant=<bound>` from a ContextVar and raises a fixed-message error when none is bound; NamedQuery registration rejects text lacking `$tenant` unless allowlisted (migrations, health ping, tenant lifecycle, Network statements); the scope binding must accept a tenant or a network scope but exactly one per unit of work (DEC-132 item 4); the dynamic Q-RES-*:<label> registrations in resource_store must pass the same check. | REWORK-DELIVERED | SEAM | 9 |
| G14 | S0 | Neo4j connection lifecycle, health and recovery | delivered | LOW | Neo4jConnection.session/run_read/run_write become the only tenant-free paths (health, migrations); add a test that they refuse application queries with no tenant bound. | REWORK-DELIVERED | SEAM | 1 |
| F09 | S0 | Design tokens, font and StatusBadge | delivered | NONE | Design tokens and StatusBadge. | NO-CHANGE | - | 0 |
| X02 | S0 | Add motion, spacing and type tokens from the design system | delivered | NONE | Design tokens. | NO-CHANGE | - | 0 |
| X03 | S0 | Apply DEC-019 design-system values (sheet 280 ms, caption 16 px, reduced-motion opacity) | delivered | NONE | Design tokens. | NO-CHANGE | - | 0 |
| F10 | S0 | Neo4j test harness | delivered | HIGH | Harness creates a unique tenant per test run and binds it; `clean_graph` deletes only `{tenantId: $t}` nodes and keeps :Migration; `write_tx`, `read_tx`, `count_nodes`, `node_props` and tests/support/things.py stamp or take the tenant; provide a two-tenant fixture and a network-scope fixture; keep one container per session until delivered. | REWORK-DELIVERED | SEAM | 6 |
| F11 | S0 | Restartable Neo4j mode in the test harness | delivered | LOW | Restart and container-lifecycle tests destroy the shared Neo4j, so mark them exclusive (run alone) once runs share one database. | REWORK-DELIVERED | SEAM | 1 |

Stage S0: 16 tasks, 19.5 extra hours.

## S1 Domain rules

| ID | Stage | Title | Status | Impact | What changes | Action | Depends on | Extra h |
|---|---|---|---|---|---|---|---|---|
| D01 | S1 | Service profile value objects | delivered | NONE | Pure value objects; tenant is not a domain field (it is bound in context). | NO-CHANGE | - | 0 |
| D02 | S1 | Capacity report value object and latest report | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D03 | S1 | Opening hours rule | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D04 | S1 | Report schedule and missed-report ladder times | delivered | NONE | Pure; London time only. | NO-CHANGE | - | 0 |
| D05 | S1 | Freshness and data-age text | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D06 | S1 | Effective available and pending count | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D07 | S1 | Service status rule | delivered | NONE | Pure status rule; the network view reuses it on projected data without change. | NO-CHANGE | - | 0 |
| D08 | S1 | System pressure rule | delivered | NONE | Pure over any list of statuses, so tenant and network pressure both reuse it. | NO-CHANGE | - | 0 |
| D09 | S1 | Reply parser: capacity and booking words | delivered | NONE | Parser; a 4-digit booking reference in a reply is only meaningful inside the tenant its number resolves to (DEC-131 item 3), which is the use case's job. | NO-CHANGE | - | 0 |
| D10 | S1 | Reply parser: multi-service lettered replies | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D11 | S1 | Capacity reply policy | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D12 | S1 | Report flag rules | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D13 | S1 | Booking state machine and FHIR status mapping | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D14 | S1 | Booking rules: timers, one open request, references | delivered | NONE | `new_reference(rng, taken)` is pure; callers (U11, U17) must pass a tenant-scoped `taken` set (references are unique per tenant only). | NO-CHANGE | - | 0 |
| D15 | S1 | Message templates: capacity (C1 to C11) | delivered | NONE | Capacity templates; the `DIUCS:` prefix is the product name. | NO-CHANGE | - | 0 |
| D16 | S1 | Message templates: booking, invitations, codes, alerts | delivered | LOW | Template I2 hard-codes 'Dorset urgent care capacity': make the region name a template field from tenant config and update D17's SAMPLE_FIELDS. | REWORK-DELIVERED | CONFIG | 1 |
| D17 | S1 | No-patient-data guard for every template | delivered | LOW | Add the network projection allowlist guard and test: no field outside the DEC-132 item 4 list (patient-level, names, phones, devices, tokens, communications, bookings, cases, audit) can enter a projection. | REWORK-DELIVERED | NETWORK | 1.5 |
| D18 | S1 | Case model, referrer scores and outcomes | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D19 | S1 | Postcode normalisation and district | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D20 | S1 | Criteria model and hard filter | delivered | NONE | Pure hard filter; also usable on projected criteria. | NO-CHANGE | - | 0 |
| D21 | S1 | Criteria workflow and review-overdue rule | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D22 | S1 | Registration state machine and approval gate | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D23 | S1 | Clinical advice queue and presence rules | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D24 | S1 | Alert rules: triggers, subscriptions, quiet hours, escalation | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D25 | S1 | Domain events | delivered | NONE | The tenant rides on the bus message envelope (P08/I02), not in the event payload; session ids are server UUIDs, so `session_id_for` stays the service id. | NO-CHANGE | - | 0 |
| D26 | S1 | Link tokens, pairing codes and support codes | delivered | MEDIUM | LinkTokenRecord gains `tenant_id` so the unauthenticated link edge binds the tenant from the stored record (DEC-131 item 5); pairing codes unique per tenant, support codes stay global because the console resolves the tenant from the code. | REWORK-DELIVERED | AUTH | 1.5 |
| D27 | S1 | Identity policy: text codes, PINs, re-verification | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| D28 | S1 | Multi-service rules: grouped prompts and phone load | delivered | NONE | Pure. | NO-CHANGE | - | 0 |
| G02 | S1 | FHIR-to-graph mapper: resources, primitives, references | delivered | LOW | Reserve `tenantId` as a mapper-owned property name and keep from_graph ignoring it; the mapper stays pure and the writer stamps the tenant. | REWORK-DELIVERED | SCHEMA | 1 |
| G03 | S1 | Mapper: concepts, identifiers, periods and quantities | delivered | MEDIUM | Identifier nodes (`Identifier/system/value`) become tenant-scoped so two tenants' ODS identifiers never merge; Concept and CodeSystem stay shared. NodeSpec needs a shared-versus-tenant flag for the writer. | REWORK-DELIVERED | SCHEMA | 2.5 |
| G04 | S1 | Mapper: backbone elements and extension registry | delivered | LOW | Backbone child nodes and ext_ properties inherit the owner's tenant; prefix ownership (`<parentKey>#...`) must be combined with tenantId in G05 queries. | REWORK-DELIVERED | SCHEMA | 1 |
| G05 | S1 | Graph writer and reader with versions | delivered | HIGH | All 17 Q-RES templates add `tenantId: $tenant` (MERGE on {tenantId,key}); label-less shared reads and the Q-RES-CLEAR-OWNED / LOAD-NODES prefix scans are tenant-scoped; Q-RES-SHARED-FILL lets a tenant write display/version onto a shared Concept (cross-tenant write), so freeze Concepts to seeded reference data; Q-RES-IDEM-* and the `resource_id` constraint go composite; placeholders and ResourceVersion nodes carry tenantId. | REWORK-DELIVERED | SCHEMA+SEAM | 10 |

Stage S1: 32 tasks, 18.5 extra hours.

## S2 Capacity loop: core and storage

| ID | Stage | Title | Status | Impact | What changes | Action | Depends on | Extra h |
|---|---|---|---|---|---|---|---|---|
| P01 | S2 | Service and capacity ports with Neo4j repositories | delivered | MEDIUM | Q-CAP-LATEST, -LATEST-FOR, -SINCE, Q-SVC-LAST-REPORT and Q-SVC-LIST-ACTIVE match HealthcareService by `{key}` or `{active}` with no tenant: add `tenantId: $tenant` on service and observation; re-seed fixtures per tenant. | REWORK-DELIVERED | SEAM+SCHEMA | 3 |
| P02 | S2 | Booking port with Neo4j repository | delivered | MEDIUM | Q-BOOK-PENDING/-OPEN-FOR/-CONFIRMED-SINCE/-BY-REF match Task and HealthcareService by id: add tenant on both nodes. `get_by_reference` returns the latest booking for a 4-digit reference, now unique per tenant only, so it must never run unbound. | REWORK-DELIVERED | SEAM+SCHEMA | 3 |
| P21 | S2 | Case port with Neo4j repository | delivered | MEDIUM | Constraint `case_reference_id` on ServiceRequest.reference becomes (tenantId, reference); Q-CASE-BY-REF and Patient/ServiceRequest/score nodes carry tenant; closing a case clears the postcode within the tenant only. | REWORK-DELIVERED | SEAM+SCHEMA | 2.5 |
| P03 | S2 | Person, role and practitioner ports with Neo4j repository | delivered | HIGH | Index `phone_hash` becomes (tenantId, phoneHash); Q-PHONE-SERVICES(-AT) and find_by_phone_hash run inside one tenant, so one mobile in two tenants is two Practitioners (DEC-131 item 3). 8 statements and cover relationships to re-test. | REWORK-DELIVERED | SEAM+SCHEMA | 4 |
| P04 | S2 | Criteria port with Neo4j repository | delivered | MEDIUM | Q-CRIT-CURRENT/-FOR/-VERSIONS/-SET-CURRENT: tenant on ServiceCriteria, HealthcareService and author role; Concept stays global; one-current-per-service is checked per tenant. | REWORK-DELIVERED | SEAM+SCHEMA | 3 |
| P13 | S2 | Registration and scope list ports with Neo4j repositories | delivered | HIGH | Scope list uses fixed List id `scope-list`, which collides with the global resource_id constraint for a second tenant: needs (tenantId,id) and one list per tenant; Q-REG-*/Q-SCOPE-* add tenant; the placeholder HealthcareService made by save_entry lands in the caller's tenant only. | REWORK-DELIVERED | SCHEMA+SEAM | 4 |
| P14 | S2 | Report and service flag ports with Neo4j repository | delivered | MEDIUM | 13 Q-FLAG-* statements: ReportFlag gets tenantId and `report_flag_id` goes composite; open_report_flags(None) lists only the bound tenant; ServiceFlag Basic nodes follow G05. | REWORK-DELIVERED | SEAM+SCHEMA | 3.5 |
| P05 | S2 | Audit log port with Neo4j hash chain and provenance | delivered | HIGH | One chain per tenant: AuditHead `{id:'audit'}` and `chain_seq` (unique on seq) become (tenantId,id) and (tenantId,seq); ensure_audit_head runs per tenant at creation; AuditRef placeholders MERGE by (tenantId,id); records() and verify_chain read one tenant; recommend tenantId inside the hashed entryJson (no production data to migrate). | REWORK-DELIVERED | SCHEMA+SEAM | 8 |
| P06 | S2 | Outbox and unit of work on Neo4j | delivered | HIGH | UnitOfWork.__aenter__ captures the bound scope and refuses to open without one (exactly one scope, DEC-132 item 4); Neo4jOutbox stamps tenantId and `outbox_message_id` goes composite; `Outbox.pending` is read across tenants by the relay (I03) so it needs an allowlisted statement or a per-tenant loop; `uow_factory` fixture binds a test tenant. | REWORK-DELIVERED | SEAM+SCHEMA | 6.5 |
| P15 | S2 | Idempotency store and processed-message markers on Neo4j | delivered | MEDIUM | IdempotencyRecord.key and Processed(messageId, consumer) uniqueness become (tenantId,key) and (tenantId,messageId,consumer); DriverIdempotencyStore opens its own transactions so it reads the bound tenant too. | REWORK-DELIVERED | SEAM+SCHEMA | 3 |
| P07 | S2 | Messaging ports, recording senders and Neo4j communication records | delivered | MEDIUM | Q-COMM-* add tenant; `by_provider_id` (Twilio SID) is called from the receipts consumer, so the tenant comes from the resolved subaccount/message property (DEC-131 item 2), and the providerMessageId index becomes (tenantId, providerMessageId). | REWORK-DELIVERED | SEAM+CONFIG | 3 |
| P08 | S2 | Event bus port, manual-clock fake and Neo4j scheduled-work records | delivered | MEDIUM | ScheduledWork id constraint composite and Q-WORK-* tenant; BusMessage and ManualEventBus carry `tenant_id` so tests can see cross-tenant delivery. | REWORK-DELIVERED | SEAM+SCHEMA | 2.5 |
| P09 | S2 | Cache port with in-memory fake | delivered | MEDIUM | Cache keys, channels and lock names are tenant-prefixed `diucs:<tenant>:`; InMemoryCache must prefix with the bound tenant so use-case tests catch leaks; `board.updates` becomes per tenant (and per network); the outbox-relay lock is an explicit global. | REWORK-DELIVERED | SEAM | 2 |
| P10 | S2 | Link token, secret and phone-hash ports with Neo4j token store | delivered | HIGH | `link_token_hash` stays globally unique but Q-LINK-GET by hash is a tenantless allowlisted read returning tenantId (DEC-131 item 5); SecretStore.get takes tenant context. Per-tenant phone-hash secret is now optional hardening since the number channel resolves the tenant (DEC-131 item 3). | REWORK-DELIVERED | SEAM+AUTH | 3.5 |
| P16 | S2 | Contact store and PIN credentials on Neo4j, text-code store port | delivered | HIGH | ProtectedContact `key`, Credential `deviceId` and Device `id` uniqueness go composite; Q-DEVICE-OWNER/-KNOWN look up inside the tenant (device bound to the tenant at pairing); InMemoryCodeStore keys on phone_hash are tenant-prefixed; 12 statements. | REWORK-DELIVERED | SEAM+SCHEMA | 4 |
| P11 | S2 | Geocoder, travel-time, terminology and validator ports with fakes | delivered | NONE | Ports and fakes for external providers; ODS and display lookups are shared reference data. | NO-CHANGE | - | 0 |
| P12 | S2 | Contract tests for the cache and event bus fakes | delivered | LOW | Add two-tenant cases to the cache and bus contract suites (same key or channel in two tenants stays isolated; the tenant property round-trips). | REWORK-DELIVERED | SEAM | 1 |
| U01 | S2 | ReportCapacity use case | delivered | LOW | No Cypher of its own: add the two-tenant use-case test (a reporter of tenant A reporting on tenant B's service id gets the non-revealing NotFound) and move the 617-line integration fixtures to the tenant harness. | REWORK-DELIVERED | SEAM | 1.5 |
| U02 | S2 | ConfirmCapacity use case | in-progress | LOW | In progress: finish on the current model. Q-CAP-TRAILING-CONFIRMS and the per-service write lock then use `tenantId: $tenant` and get a two-tenant race test after the seam. | AMEND-PROMPT | SEAM | 0.5 |
| U03 | S2 | SendPrompts use case (one service) | in-progress | MEDIUM | In progress: finish on the current model. `link_base_url` becomes per-tenant config; link token records carry tenant; the prompt idempotency key and schedule_work messages are tenant-stamped by P15/P06. Independent of the plain-text-token failure. | AMEND-PROMPT | SEAM+CONFIG | 1.5 |
| U04 | S2 | Grouped prompts for multi-service phones | not-started | LOW | 'Other services on the phone' is looked up within the tenant only; two-tenant test. | AMEND-PROMPT | SEAM | 0.5 |
| U05 | S2 | HandleInboundText use case: capacity replies | not-started | MEDIUM | Cache key `recheck:{phone_hash}:{service_id}` is tenant-prefixed by the cache; the command has no tenant, so the inbound consumer binds the tenant resolved from the called number (DEC-131 item 2); 'unknown phone' means unknown within that tenant. | AMEND-PROMPT | SEAM+CONFIG | 1.5 |
| U06 | S2 | Missed-report ladder handlers | not-started | LOW | Ladder handlers load work and communications under the tenant bound by the scheduler consumer. | AMEND-PROMPT | SEAM | 0.5 |
| U07 | S2 | Raise report flags when reports break rules | not-started | LOW | New statements use `$tenant`; open-flag-per-reason check is per tenant. | AMEND-PROMPT | SEAM | 0.5 |
| U08 | S2 | QueryBoard read model | delivered | LOW | Tenant board needs no code change; add the two-tenant test (A's board excludes B's services, pressure computed within A). Network view is a separate read use case (TEN-N05), not a flag on this one. | REWORK-DELIVERED | SEAM+NETWORK | 1.5 |
| U09 | S2 | Board projector: cache and live updates | delivered | MEDIUM | `board:v1` and the `board.updates` channel become per tenant via the cache adapter; handle() runs under the tenant bound from the message; test that tenant A events never rebuild or publish for B. The network board gets its own projector key and channel (TEN-N07). | REWORK-DELIVERED | SEAM+NETWORK | 3 |
| I01 | S2 | Redis cache adapter | delivered | MEDIUM | Key builder reads the bound scope (`diucs:<tenant>:cache/lock/fence/chan`) and refuses without one; keep the test key_prefix as an outer prefix; add two-tenant Redis contract cases. | REWORK-DELIVERED | SEAM | 3 |
| I02 | S2 | Service Bus event bus adapter | delivered | MEDIUM | `to_service_bus_message` sets `application_properties['tenantId']` (or network scope id) and the consumer side validates it; session id stays the service UUID; emulator contract test for the property. | REWORK-DELIVERED | SEAM | 3 |
| I03 | S2 | Outbox relay worker | not-started | HIGH | Relay reads pending outbox rows across tenants: use an allowlisted cross-tenant read of ids only or loop the active tenants (TEN-G04 list), then publish each message with its tenant property in that tenant's unit of work; the `outbox-relay` lock is global; sequence numbers are saved under the row's tenant. | AMEND-PROMPT | SEAM+LIFECYCLE | 2.5 |
| I04 | S2 | Idempotent message consumer framework | stale | HIGH | Stale, review requested, no verification recorded. IdempotentConsumer binds the tenant from the message property (missing or unknown tenant is PermanentError and dead-letter) before opening the unit of work; `mark_if_new` is composite; runner reads the property. | AMEND-PROMPT | SEAM | 2.5 |
| I05 | S2 | Scheduled work consumer | not-started | MEDIUM | Dispatcher loads ScheduledWork under the bound tenant; scheduled messages carry the tenant property set by the relay. | AMEND-PROMPT | SEAM | 1 |

Stage S2: 31 tasks, 79.5 extra hours.

## S3 Capacity loop: channels, API and wall board

| ID | Stage | Title | Status | Impact | What changes | Action | Depends on | Extra h |
|---|---|---|---|---|---|---|---|---|
| R01 | S3 | FHIR REST app skeleton | delivered | LOW | Per-request tenant binding is installed by the auth dependency; `/health` and `/fhir/metadata` become explicit tenant-free routes; tests/support/api.py gets a two-tenant client. | REWORK-DELIVERED | SEAM | 1 |
| R02 | S3 | Authentication, roles and service scope | delivered | HIGH | BffClaims and the HS256 token gain a `tid` claim (reject tokens without it); Actor gains tenant_id; current_actor binds the tenant context for the request; issue_test_token takes a tenant; test that a tenant-A token reads nothing of B (404). | REWORK-DELIVERED | AUTH+SEAM | 4 |
| R03 | S3 | ETag, If-Match and Idempotency-Key handling | delivered | LOW | Replay cache key `idem:<sub>:<key>` is tenant-prefixed through the cache adapter; ETag logic unchanged; two-tenant replay test. | REWORK-DELIVERED | SEAM | 1.5 |
| R04 | S3 | HealthcareService and capacity Observation endpoints | not-started | LOW | Ids and the `organization`/`focus` search parameters resolve inside the bound tenant; a cross-tenant id returns the same 404 body; two-tenant route test. | AMEND-PROMPT | SEAM | 1 |
| R05 | S3 | $board and $confirm-capacity operations | not-started | MEDIUM | `$board` returns the tenant display name and gains `scope=network` (membership and grant checked, entries carry the owning organisation); the tenant board stays the default. | AMEND-PROMPT | SEAM+NETWORK+CONFIG | 2.5 |
| R06 | S3 | Server-sent events stream | delivered | HIGH | `GET /events` subscribes to the global `board.updates` channel, so any signed-in role would stream every tenant's service ids: subscribe to the caller's tenant channel (and the network channel only on request, DEC-132) and add a two-tenant stream test. | REWORK-DELIVERED | SEAM | 3 |
| L01 | S3 | Capacity link API | not-started | HIGH | Unauthenticated `/links/{token}`: resolve the token hash with the allowlisted global read, bind the tenant from the record, then run everything in that tenant; unknown token keeps the same 410 body; no tenant in URL, body or header. | AMEND-PROMPT | AUTH+SEAM | 2.5 |
| I06 | S3 | Twilio SMS adapter | delivered | MEDIUM | TwilioSms takes one account at construction: per DEC-131 resolve the tenant's subaccount SID, sender number and secret reference at send time (secret store, never a graph node); status callback URL identifies the subaccount. | REWORK-DELIVERED | CONFIG | 3 |
| I07 | S3 | SMS inbound webhook | not-started | HIGH | Resolve the tenant from `To` plus `AccountSid` in tenant config, then verify the signature with that subaccount's token; unknown number gets a fixed empty answer and an id-only log; replay key tenant-prefixed; queue message carries the tenant property; receipts matched by AccountSid and message id. | AMEND-PROMPT | CONFIG+SEAM | 3 |
| I08 | S3 | Reply processor and delivery receipt consumers | not-started | MEDIUM | Processors bind the tenant from the message property before building the command; receipts update the Communication inside that tenant. | AMEND-PROMPT | SEAM | 1.5 |
| I09 | S3 | Email adapter (SMTP) with HTML and text bodies | stale | LOW | Stale (review requested). Sender identity and credentials per tenant (DEC-131 item 1, product under DEC-003); `email_from` and the Message-ID domain come from tenant config. | AMEND-PROMPT | CONFIG | 1 |
| I10 | S3 | Outbound message senders (messages.outbound consumers) | not-started | MEDIUM | Consumers bind the tenant from the message property, read contacts inside it and send with that tenant's subaccount/sender via the resolver. | AMEND-PROMPT | SEAM+CONFIG | 1.5 |
| U10 | S3 | PairWallScreen use case | not-started | HIGH | StartPairing is unauthenticated so the pairing record is created unassigned (allowlisted tenantless statements); ConfirmPairing by a lead assigns the lead's tenant; the device token hash resolves to the tenant claim (DEC-131 item 5). NETWORK: the device also stores a board scope (tenant or network). | AMEND-PROMPT | AUTH+SEAM | 3 |
| R15 | S3 | Wall screen pairing endpoints | not-started | MEDIUM | Unauthenticated start/claim routes use the unassigned pairing store; `POST /screens` binds the lead's tenant and accepts the board-scope setting. | AMEND-PROMPT | AUTH | 1.5 |
| W01 | S3 | BFF foundations: typed FHIR client and MSW test setup | delivered | NONE | Typed client; the tenant travels only inside the bearer token. | NO-CHANGE | - | 0 |
| W02 | S3 | BFF session cookie and CSRF | in-review | LOW | In review: finish on the current model. Afterwards add `tenantId` to Session, and make withBff refuse any `tenant`/`tenantId` query or body key (central guard so route tasks need no repeat). | AMEND-PROMPT | AUTH | 1 |
| W03 | S3 | Base UI components | delivered | NONE | Base components. | NO-CHANGE | - | 0 |
| W04 | S3 | Capacity link pages | not-started | NONE | Public link pages: the tenant is derived by the back end from the token; nothing to add. | NO-CHANGE | - | 0 |
| W05 | S3 | Wall board page | not-started | LOW | Header 'Dorset urgent care capacity' comes from the tenant display name in `$board`; add the network variant (tiles labelled with the owning organisation, scope toggle or setting). | AMEND-PROMPT | NETWORK+CONFIG | 1.5 |
| W06 | S3 | Wall board live updates and Last known | not-started | LOW | The BFF relay must open the network stream when the board is in network scope. | AMEND-PROMPT | NETWORK | 0.5 |
| W07 | S3 | Wall board variants: pressure, out of hours, pending | not-started | LOW | Pressure banner and out-of-hours states also render for the network board (pressure computed over projected services). | AMEND-PROMPT | NETWORK | 0.5 |
| W08 | S3 | Wall screen pairing pages | not-started | LOW | Start pairing is tenantless; the lead's admin form gains the tenant-or-network board setting. | AMEND-PROMPT | AUTH+NETWORK | 1 |
| O01 | S3 | Backend OpenTelemetry baseline | not-started | LOW | Add `tenant.id` as an allow-listed span attribute (never a metric label). | AMEND-PROMPT | SEAM | 1 |

Stage S3: 23 tasks, 35.5 extra hours.

## S4 Advisor call

| ID | Stage | Title | Status | Impact | What changes | Action | Depends on | Extra h |
|---|---|---|---|---|---|---|---|---|
| U11 | S4 | OpenCase use case | not-started | LOW | Case reference uniqueness retries through the tenant-scoped repository. | AMEND-PROMPT | SEAM | 0.5 |
| U12 | S4 | FilterOptions use case with audit snapshot | not-started | MEDIUM | New Q-SVC-POSITIONS carries `$tenant`. NETWORK: options may include network services read from the projection; they are view-only (booking, 'I phoned' and declines cannot cross tenants) and audit snapshots record the source tenant. | AMEND-PROMPT | SEAM+NETWORK | 2.5 |
| U13 | S4 | Advisor phoned and declined-despite-capacity | not-started | LOW | Refuse 'I phoned' and decline for a service outside the caller's tenant (a cross-tenant write). | AMEND-PROMPT | NETWORK | 0.5 |
| U14 | S4 | RecordOutcome and close case | not-started | LOW | Close clears postcode and needs inside the tenant; two-tenant test. | AMEND-PROMPT | SEAM | 0.5 |
| U15 | S4 | Lead-assisted service set-up (pilot) | not-started | MEDIUM | Practitioner reuse by phone hash is within the tenant; first prompt-due and criteria v1 in the tenant; area districts from tenant config. | AMEND-PROMPT | SEAM+CONFIG | 1.5 |
| U16 | S4 | Change reporter number and cover | not-started | MEDIUM | Cover and 'until changed' roles are created in the tenant even when the same mobile exists in another tenant. | AMEND-PROMPT | SEAM | 1 |
| G11 | S4 | Criteria hard-filter and history queries | not-started | MEDIUM | The literal Q-CRIT-FILTER Cypher in the prompt needs `tenantId: $tenant` on service and criteria (Concept stays global) and a two-tenant agreement test; add a network variant reading projected criteria. | AMEND-PROMPT | SEAM+NETWORK | 2.5 |
| I11 | S4 | Local postcode centroids and interim travel-time adapter | not-started | NONE | Local postcode centroid file and straight-line travel; no tenant data. | NO-CHANGE | - | 0 |
| R07 | S4 | Case endpoints and $filter-options | not-started | LOW | Case and service ids resolve inside the tenant; `$filter-options` marks network options as view-only. | AMEND-PROMPT | SEAM+NETWORK | 1.5 |
| R08 | S4 | Lead endpoints: service set-up and reporter numbers | not-started | LOW | Setup and change-number routes bind the lead's tenant; two-tenant route test. | AMEND-PROMPT | SEAM | 1 |
| R16 | S4 | Pathways Dx code lookup endpoint | not-started | NONE | Pathways Dx codes are shared reference data. | NO-CHANGE | - | 0 |
| W09 | S4 | Staff sign-in with Entra ID and role guard | not-started | HIGH | Entra sign-in must map the user to exactly one DIUCS tenant (tenant record maps Entra directory/app config to tenantId; unmapped users get /forbidden) and mint the `tid` claim. `ENTRA_TENANT_ID` is the Entra directory, a different thing from a DIUCS tenant: rename in the prompt. | AMEND-PROMPT | AUTH+CONFIG | 4 |
| W10 | S4 | Advisor home and call step header | not-started | LOW | Board counts gain a network count variant. | AMEND-PROMPT | NETWORK | 0.5 |
| W11 | S4 | Patient needs form | not-started | NONE | Case form; data arrives through the session's tenant. | NO-CHANGE | - | 0 |
| W12 | S4 | Referrer score pickers | not-started | NONE | Pathways picker; shared reference data. | NO-CHANGE | - | 0 |
| W13 | S4 | Options list | not-started | MEDIUM | Option cards for network services show the owning organisation and a source label, and have no 'Request booking', 'I phoned' or 'They declined' buttons (booking is not shared); phone-to-confirm wording applies. | AMEND-PROMPT | NETWORK | 2 |
| W14 | S4 | Criteria, I phoned and They declined dialogs | not-started | LOW | Criteria dialog works for projected criteria; phoned/declined dialogs are not offered for network services. | AMEND-PROMPT | NETWORK | 0.5 |
| W15 | S4 | Record outcome, SystmOne summary and call closed | not-started | NONE | Outcome and summary; tenant-only data. | NO-CHANGE | - | 0 |
| W16 | S4 | No service fits state | not-started | NONE | Empty state. | NO-CHANGE | - | 0 |
| W17 | S4 | Shift lead page: chasing, system now, covering | not-started | LOW | 'System now' counts gain the network variant; chasing and covering stay tenant-only. | AMEND-PROMPT | NETWORK | 0.5 |
| W18 | S4 | Shift lead: add service and change number forms (pilot) | not-started | NONE | Lead forms; tenant from the session. | NO-CHANGE | - | 0 |
| S01 | S4 | Browser security headers and CSP | not-started | NONE | Headers and CSP; if tenants get host-based URLs later add the wildcard origin. | NO-CHANGE | - | 0 |

Stage S4: 22 tasks, 19 extra hours.

## S5 Booking by text and link

| ID | Stage | Title | Status | Impact | What changes | Action | Depends on | Extra h |
|---|---|---|---|---|---|---|---|---|
| U17 | S5 | RequestBooking use case | not-started | MEDIUM | Booking reference is unique among open bookings of the tenant; link host from tenant config; refuse a service that is not in the caller's tenant (network services cannot be booked). | AMEND-PROMPT | SEAM+CONFIG | 1.5 |
| U18 | S5 | RespondToBooking use case | not-started | LOW | Respond inside the tenant bound by the link record, consumer or session. | AMEND-PROMPT | SEAM | 0.5 |
| U19 | S5 | Booking timers: phone prompt and expiry | not-started | LOW | Timer handlers run under the tenant on the scheduled message. | AMEND-PROMPT | SEAM | 0.5 |
| U20 | S5 | CancelBooking use case | not-started | LOW | Tenant-scoped booking lookup; two-tenant test. | AMEND-PROMPT | SEAM | 0.5 |
| U21 | S5 | WithdrawBooking and NotReached use cases | not-started | LOW | Withdrawal escalation work carries the tenant. | AMEND-PROMPT | SEAM | 0.5 |
| U22 | S5 | Booking replies by text | not-started | MEDIUM | A reply matches open bookings only inside the tenant its number resolves to (DEC-131 item 3); the new 'declined without reason by this phone' query carries `$tenant`. | AMEND-PROMPT | SEAM+CONFIG | 1.5 |
| R09 | S5 | Booking Task endpoints, $respond and service projection | not-started | LOW | Task ids and `owner`/`focus` references resolve inside the tenant; two-tenant route test. | AMEND-PROMPT | SEAM | 1 |
| R17 | S5 | Advisor acknowledgement of a withdrawn booking | not-started | LOW | Acknowledge looks the booking up within the tenant. | AMEND-PROMPT | SEAM | 0.5 |
| L02 | S5 | Booking link API | not-started | MEDIUM | booking-request and booking-change tokens bind the tenant from the stored record; the 24-hour change token inherits it. | AMEND-PROMPT | AUTH+SEAM | 1.5 |
| W19 | S5 | Booking link page for services | not-started | LOW | `SPOA_PHONE_DISPLAY` is one global env var: the SPOA phone comes from the link GET response (tenant config). | AMEND-PROMPT | CONFIG | 0.5 |
| W20 | S5 | Advisor booking card states, live | not-started | NONE | Booking card; same-tenant bookings only. | NO-CHANGE | - | 0 |
| W21 | S5 | Advisor cancel booking and withdrawal alert | not-started | NONE | Cancel and alerts; same tenant. | NO-CHANGE | - | 0 |
| W22 | S5 | Service booking exceptions: withdraw, not reached, cancelled | not-started | LOW | Same global `SPOA_PHONE_DISPLAY` issue as W19. | AMEND-PROMPT | CONFIG | 0.5 |

Stage S5: 13 tasks, 9 extra hours.

## S6 Registration and approval

| ID | Stage | Title | Status | Impact | What changes | Action | Depends on | Extra h |
|---|---|---|---|---|---|---|---|---|
| U23 | S6 | Scope list management | not-started | MEDIUM | One scope list per tenant (fixed id `scope-list` made composite in P13); entries and placeholder services created in the caller's tenant. | AMEND-PROMPT | SEAM+SCHEMA | 1.5 |
| U24 | S6 | Invite a service reporter | not-started | MEDIUM | Invitation token record carries the tenant (the link `/i/<token>` is the verified source); the invite text is sent on the tenant's number (DEC-131); link host from tenant config; the same mobile may be invited by two tenants. | AMEND-PROMPT | AUTH+CONFIG | 2 |
| U25 | S6 | Text code request and verification | not-started | HIGH | Code request and verify are unauthenticated: tenant comes from the invitation token, device or session, never a phone alone; codes are sent from the tenant's number (DEC-131 item 5) and keyed `code:<phone_hash>:<purpose>` under the tenant prefix; unknown-number responses must not reveal which tenants know the number. | AMEND-PROMPT | AUTH+CONFIG | 3 |
| U26 | S6 | Registration draft and submit | not-started | LOW | Draft stored in the tenant; same ODS code allowed in two tenants. | AMEND-PROMPT | SEAM | 0.5 |
| I12 | S6 | OS Places geocoder and ODS terminology check adapters | not-started | NONE | OS Places and ODS file are platform-wide reference services; the API key is not tenant data. | NO-CHANGE | - | 0 |
| U27 | S6 | Registration persistence as one FHIR transaction | not-started | MEDIUM | Organization, Location, HealthcareService and Basic written in the tenant; ODS Identifier nodes tenant-scoped; coverage-area Locations are reused only within the tenant. | AMEND-PROMPT | SEAM+SCHEMA | 1.5 |
| U28 | S6 | Review registration: automatic checks, call-back, scope | not-started | MEDIUM | `Settings.area_districts` (DT1-DT11, BH1-BH31) becomes per-tenant configuration; reviewer checks run in the tenant. | AMEND-PROMPT | CONFIG+SEAM | 2 |
| U29 | S6 | Approve, send back, test prompt and go live | not-started | LOW | First prompt-due scheduled with the tenant; test message is sent from the tenant's number. | AMEND-PROMPT | SEAM | 0.5 |
| U30 | S6 | ChangeCriteria, ApproveCriteria and ConfirmCriteria | not-started | LOW | Versions, approval Task and current pointer in the tenant. NETWORK: a criteria change re-triggers the directory/criteria projection. | AMEND-PROMPT | SEAM | 0.5 |
| U31 | S6 | Criteria review reminders and overdue flag | not-started | MEDIUM | The daily 07:00 job schedules its own next run, so it must be seeded per tenant at tenant creation (TEN-G04) and run under that tenant; processed markers are composite. | AMEND-PROMPT | LIFECYCLE+SEAM | 2 |
| R10 | S6 | Registration, scope and criteria endpoints | not-started | LOW | Registration, scope and criteria routes bind the session tenant; two-tenant route test. | AMEND-PROMPT | SEAM | 1 |
| W23 | S6 | Registration: sign in and start | not-started | MEDIUM | Tenant comes only from the invitation token validated by the back end; BFF code endpoints never accept a tenant; the new session carries the tenant. | AMEND-PROMPT | AUTH | 1.5 |
| W54 | S6 | Registration: organisation step and error summary | not-started | NONE | Form step. | NO-CHANGE | - | 0 |
| W24 | S6 | Registration: location step with address lookup | not-started | NONE | Form step. | NO-CHANGE | - | 0 |
| W25 | S6 | Registration: service and criteria step | not-started | NONE | Form step. | NO-CHANGE | - | 0 |
| W26 | S6 | Registration: capacity reporting, review, submitted, my services | not-started | NONE | Form step. | NO-CHANGE | - | 0 |
| W27 | S6 | Applicant status pages | not-started | NONE | Status page; SPOA phone already arrives from the API. | NO-CHANGE | - | 0 |
| W28 | S6 | Reviewer: scope list, queue and overview | not-started | NONE | Scope list and queue for the lead's tenant. | NO-CHANGE | - | 0 |
| W29 | S6 | Reviewer: call-back, scope, decide and go live | not-started | LOW | 'Dorset directory' wording in the call-back script comes from tenant config. | AMEND-PROMPT | CONFIG | 0.5 |
| W30 | S6 | Criteria owner: review, confirm, change, preview, send | not-started | NONE | Criteria owner flow. | NO-CHANGE | - | 0 |
| W31 | S6 | Criteria second approval, history and overdue | not-started | NONE | Approval and history. | NO-CHANGE | - | 0 |

Stage S6: 21 tasks, 16.5 extra hours.

## S7 Reporter app, PIN, push and alerts

| ID | Stage | Title | Status | Impact | What changes | Action | Depends on | Extra h |
|---|---|---|---|---|---|---|---|---|
| P17 | S7 | Alert subscription and alert repositories on Neo4j | not-started | MEDIUM | Q-ALERT-SUB-* and Q-ALERT-*: `subscribers_for_kind` returns only the bound tenant's subscribers; tenantId on AlertSubscription and alert Tasks. | AMEND-PROMPT | SEAM+SCHEMA | 1.5 |
| P19 | S7 | Push subscription repository on Neo4j | not-started | LOW | Q-PUSH-*: tenantId on Device; device id uniqueness composite. | AMEND-PROMPT | SEAM+SCHEMA | 1 |
| U32 | S7 | PIN set, sign-in, lock, reset and 30-day check | not-started | MEDIUM | PIN credentials per device inside the tenant; sign-in returns the tenant for the session claims. | AMEND-PROMPT | AUTH+SEAM | 1.5 |
| I13 | S7 | Redis sessions, attempt counters and rate limits | not-started | HIGH | All key families (`sess`, `sess-by-person`, `code`, rate limits) take the tenant prefix; the session id lookup needs the tenant from the sealed BFF cookie; 'sign out everywhere' is per tenant. | AMEND-PROMPT | SEAM+AUTH | 3 |
| I14 | S7 | Web Push adapter and notification consent | not-started | LOW | Decide VAPID keys are platform-wide (changing them forces re-subscription); consent resource written in the tenant. | AMEND-PROMPT | CONFIG | 1 |
| R11 | S7 | Reporter identity and push endpoints | not-started | HIGH | Unauthenticated `/identity/*` routes cannot take the tenant from a phone alone: use the invitation, device cookie or session, and sign code messages from the tenant's number; responses must not reveal which tenants know a number. | AMEND-PROMPT | AUTH+CONFIG | 2.5 |
| W32 | S7 | PWA manifest, service worker and offline shell | not-started | NONE | PWA shell; caches no data. | NO-CHANGE | - | 0 |
| W33 | S7 | Reporter set-up: welcome, number check, channel | not-started | MEDIUM | The invitation lookup returns the tenant name and the session cookie carries the tenant; the BFF never takes a tenant from the client. | AMEND-PROMPT | AUTH | 1 |
| W34 | S7 | Reporter set-up: home screen, notifications, PIN | not-started | NONE | Set-up screens. | NO-CHANGE | - | 0 |
| W35 | S7 | Reporter app: PIN entry, respond, confirmation | not-started | NONE | Reporter app. | NO-CHANGE | - | 0 |
| W36 | S7 | Reporter app: booking decision | not-started | LOW | SPOA phone number comes from tenant config via the API, not an env var. | AMEND-PROMPT | CONFIG | 0.5 |
| W37 | S7 | Reporter app: recovery and settings | not-started | NONE | Recovery screens with a session. | NO-CHANGE | - | 0 |
| W38 | S7 | Reporter app: several services on one phone | not-started | NONE | Multi-service screens. | NO-CHANGE | - | 0 |
| U33 | S7 | SubscribeAlert use case | not-started | LOW | Deputy and subscriber lookups within the tenant. | AMEND-PROMPT | SEAM | 0.5 |
| U34 | S7 | Alert evaluator, acknowledge, snooze and escalation | not-started | MEDIUM | Consumes StatusChanged under the bound tenant; system-pressure alert computed within the tenant; NETWORK: a network-pressure alert for members is an owner decision, not built by default. | AMEND-PROMPT | SEAM+NETWORK | 2 |
| U35 | S7 | Week summary for COO and ICB | not-started | MEDIUM | Week-summary Cypher carries `$tenant`; small-group suppression applies per tenant; `minutes_per_avoided_call` per tenant; network summary can only cover capacity-derived figures (bookings and cases are not shared): owner decision. | AMEND-PROMPT | SEAM+CONFIG+NETWORK | 2 |
| R12 | S7 | Subscription and alert endpoints | not-started | LOW | Own-subscription and week-summary routes bind the tenant; `$week-summary` scope parameter reserved for the network variant. | AMEND-PROMPT | SEAM+NETWORK | 1 |
| W39 | S7 | Exec set-up: alerts, quiet hours, escalation | not-started | NONE | Alert set-up. | NO-CHANGE | - | 0 |
| W40 | S7 | Exec home, service detail and alerts | not-started | MEDIUM | Heading 'Dorset system' becomes the tenant or network name; exec home gains network pressure and counts. | AMEND-PROMPT | NETWORK+CONFIG | 1.5 |
| W41 | S7 | Exec week summary | not-started | LOW | Week summary shows a network variant only if TEN-N13 is built. | AMEND-PROMPT | NETWORK | 0.5 |

Stage S7: 20 tasks, 19.5 extra hours.

## S8 Shift lead tools, clinical advice and safety

| ID | Stage | Title | Status | Impact | What changes | Action | Depends on | Extra h |
|---|---|---|---|---|---|---|---|---|
| P18 | S8 | Clinical request repository on Neo4j | not-started | LOW | Task via the resource store inherits tenant; presence heartbeat keys tenant-prefixed. | AMEND-PROMPT | SEAM | 1 |
| P20 | S8 | Service move and protected text stores on Neo4j | not-started | MEDIUM | Q-PROT-* statements and ServiceMove carry tenantId; protected-text handles resolve inside the tenant. | AMEND-PROMPT | SEAM+SCHEMA | 1.5 |
| U36 | S8 | SuspendService and ResumeService | not-started | LOW | Suspension flag in the tenant. NETWORK: a suspended service stops being projected. | AMEND-PROMPT | SEAM | 0.5 |
| U37 | S8 | RemovePerson, sign out everywhere and lost phone | not-started | LOW | Revoke devices, credentials, push subscriptions and Redis sessions within the tenant. | AMEND-PROMPT | SEAM | 1 |
| U38 | S8 | Move a service between phones | not-started | LOW | Moves and cover inside the tenant; codes sent from the tenant's number. | AMEND-PROMPT | SEAM+CONFIG | 1 |
| U39 | S8 | Resolve report flags | not-started | LOW | Tenant-scoped flag resolution. | AMEND-PROMPT | SEAM | 0.5 |
| U40 | S8 | Clinical advice requests | not-started | MEDIUM | Clinical queue is per tenant; a shared clinical pool across tenants would be cross-tenant access (DEC-130 item 8), so state it as out of scope; presence cache keys tenant-prefixed. | AMEND-PROMPT | SEAM+CONFIG | 2 |
| U41 | S8 | Safety concern and problem report | not-started | MEDIUM | `SC-` counter node and safety-officer role are per tenant. | AMEND-PROMPT | SEAM+CONFIG | 1 |
| U42 | S8 | Audit replay of what the advisor saw | not-started | MEDIUM | `records_for(entity_id)` and verify_chain read one tenant's chain; audit role is tenant-bound. | AMEND-PROMPT | SEAM | 1.5 |
| R13 | S8 | Lead, clinical and safety endpoints | not-started | LOW | Lead, clinical and audit routes bind the tenant; `/identity/new-phone` follows the R11 unauthenticated rule. | AMEND-PROMPT | SEAM+AUTH | 1 |
| R14 | S8 | Profiles, $validate and the validator adapter | not-started | NONE | Profiles and validator are platform-wide and pure; route tests only. | NO-CHANGE | - | 0 |
| W42 | S8 | Lead: suspend, resume, remove, reports to check | not-started | NONE | Lead screens. | NO-CHANGE | - | 0 |
| W43 | S8 | Lead: phones and services, invite and track set-up | not-started | NONE | Lead screens. | NO-CHANGE | - | 0 |
| W44 | S8 | Clinical advisor screens | not-started | NONE | Clinical screens. | NO-CHANGE | - | 0 |
| W45 | S8 | Advisor: ask a clinical advisor, wired | not-started | NONE | Dialog. | NO-CHANGE | - | 0 |
| W46 | S8 | Help: safety concern, problem report, share session | not-started | NONE | Help. | NO-CHANGE | - | 0 |
| W47 | S8 | Lead: audit replay screen | not-started | NONE | Audit replay. | NO-CHANGE | - | 0 |
| W55 | S8 | Reporter: lost phone and sign out everywhere | not-started | MEDIUM | 'No session needed' lost-phone flow cannot resolve a tenant from a phone alone: it needs the tenant hint rule (see design gaps) and must send the code from that tenant's number. | AMEND-PROMPT | AUTH | 1.5 |

Stage S8: 18 tasks, 12.5 extra hours.

## S9 Observability and support console

| ID | Stage | Title | Status | Impact | What changes | Action | Depends on | Extra h |
|---|---|---|---|---|---|---|---|---|
| O02 | S9 | Browser telemetry module and element ids | not-started | LOW | The BFF telemetry endpoint adds `tenant.id` from the session; the browser never sets it. | AMEND-PROMPT | SEAM | 0.5 |
| O03 | S9 | Friction rules engine | not-started | NONE | Pure friction rules. | NO-CHANGE | - | 0 |
| O04 | S9 | OpenTelemetry Collector with attribute allow-list | not-started | LOW | Add `tenant.id` to the collector allow-list. | AMEND-PROMPT | SEAM | 1 |
| O05 | S9 | Telemetry schema scan for free text | not-started | NONE | Schema scan; `tenant.id` fits the id pattern rule. | NO-CHANGE | - | 0 |
| O06 | S9 | Support codes and support access audit | not-started | HIGH | Support codes resolve a tenant; the `support` role is cross-tenant, which DEC-130 item 8 and DEC-132 item 8 say no role holds yet: build only the audited guard and open the session in the code's tenant. | AMEND-PROMPT | AUTH+LIFECYCLE | 3 |
| O07 | S9 | TelemetryQuery port and Azure Monitor adapter | not-started | MEDIUM | Telemetry queries filter by `tenant.id` (KQL parameter). | AMEND-PROMPT | SEAM | 1.5 |
| O08 | S9 | Daily telemetry aggregates job | not-started | MEDIUM | Aggregate nodes (FunnelDaily etc.) carry tenantId in their MERGE keys; the under-10 suppression is evaluated per tenant. | AMEND-PROMPT | SEAM | 2.5 |
| R18 | S9 | Support code and console endpoints | not-started | MEDIUM | Support routes open the shared session in the code's tenant; the person sees and stops only their own code. | AMEND-PROMPT | AUTH+SEAM | 1.5 |
| W48 | S9 | Console: find session, timeline and trace | not-started | HIGH | The console is the cross-tenant surface: no tenant picker until DEC-130 item 8 is decided; session open resolves the tenant from the support code. | AMEND-PROMPT | AUTH | 2 |
| W49 | S9 | Console: funnels, paths, friction, performance, releases | not-started | MEDIUM | Insight aggregates are per tenant; a cross-tenant product view needs the same privilege decision. | AMEND-PROMPT | SEAM+AUTH | 1.5 |
| W56 | S9 | Help: share my session (support code) | not-started | NONE | Person-side support code screen. | NO-CHANGE | - | 0 |
| O09 | S9 | Synthetic journey checks | not-started | MEDIUM | `POST /test/synthetic/prompt` needs a dedicated synthetic tenant or one synthetic service per tenant, with a token for it (TEN-G04). | AMEND-PROMPT | LIFECYCLE+SEAM | 1.5 |

Stage S9: 12 tasks, 15 extra hours.

## S10 Later

| ID | Stage | Title | Status | Impact | What changes | Action | Depends on | Extra h |
|---|---|---|---|---|---|---|---|---|
| I15 | S10 | Routing travel-time adapter (once the engine is chosen) | not-started | LOW | Travel cache key `diucs:cache:travel:<site>:<district>` is tenant-prefixed by the cache adapter. | AMEND-PROMPT | SEAM | 0.5 |
| W50 | S10 | Map view and travel details | not-started | LOW | Map includes network services as view-only pins with the owning organisation. | AMEND-PROMPT | NETWORK | 1 |
| U43 | S10 | Planning analysis from decision snapshots | not-started | MEDIUM | Q-PLAN-* carry `$tenant`; planning stays tenant-only (decision snapshots are not shared). | AMEND-PROMPT | SEAM | 1.5 |
| W51 | S10 | Planning view | not-started | NONE | Planning view; the API suppresses small groups. | NO-CHANGE | - | 0 |
| W52 | S10 | Product tour by role | not-started | NONE | Static tour. | NO-CHANGE | - | 0 |
| W53 | S10 | Training lessons and practice mode | not-started | LOW | Champion name and SPOA shift-lead phone come from tenant config. | AMEND-PROMPT | CONFIG | 0.5 |
| G13 | S10 | RDF (Turtle) export from the mapper | not-started | LOW | Exported IRIs `res:Type/id` collide across tenants: namespace per tenant and include tenantId. | AMEND-PROMPT | SCHEMA | 1 |

Stage S10: 7 tasks, 4.5 extra hours.

## New rows: tenancy and network work that is not one of the 215 tasks

No `TEN-` ids exist in the repository yet, so these ids are provisional (prefix `TEN-G` for general tenancy, `TEN-N` for the DEC-132 network). Rename them if another auditor has already issued ids. Stage is where I would place them in the plan.

| ID | Stage | Title | Impact | What it is | Depends on (piece) | Depends on (tasks) | Est. h |
|---|---|---|---|---|---|---|---|
| TEN-G01 | S2 | Two-tenant test generated from the query registry | HIGH | Seed tenants A and B (and a network scope), run every registered statement as A, assert no B node is returned and every write leaves B unchanged; a new statement is covered automatically. | SEAM | G01, F10 | 6 |
| TEN-G02 | S2 | Composite constraints, index swap and tenantId backfill | HIGH | New migrations drop and recreate 17 uniqueness constraints as (tenantId, key) and 7 indexes with tenantId; backfill existing dev data into one default tenant; Concept, CodeSystem and link_token_hash stay global. Runs alone. | SCHEMA | G01, TEN-G01 | 6 |
| TEN-G03 | S2 | Tenant record, TenantConfig port and secret references | HIGH | `Tenant` node (id, legal name, display name, status), per-tenant config (SPOA phone, area districts, link host, region wording, Twilio subaccount SID, sender numbers, email identity, secret reference ids per DEC-131 item 4), a fake secret store for tests, allowlisted tenant-resolution statements (by To+AccountSid, by slug). | CONFIG | G01, TEN-G02 | 8 |
| TEN-G04 | S2 | Tenant lifecycle: create, suspend, offboard | HIGH | Create a tenant (record, AuditHead, scope list, seeded daily jobs such as U31, first administrator, secrets), list active tenants for workers, suspend, offboard with its own retention; history of a leaving member stays (DEC-132 item 6). | LIFECYCLE | TEN-G03, P05, P13 | 10 |
| TEN-G05 | S3 | Unauthenticated-edge tenant resolution | HIGH | One resolver for link-token hash, pairing codes and device tokens, invitation tokens, text-code and lost-phone flows, inbound SMS (DEC-131) and a tenant hint (host or path slug) that only selects the lookup scope and is overridden by any token. | AUTH | TEN-G03, P10, D26 | 6 |
| TEN-G06 | S9 | Cross-tenant privilege guard (support and operator) | MEDIUM | A deny-by-default guard and audit entry for any cross-tenant read; no role holds it until the owner decides (DEC-130 item 8, DEC-132 item 8). | AUTH | R02, O06 | 3 |
| TEN-N01 | S2 | Network scope model and repositories | HIGH | `Network`, `NetworkMembership`, `Grant` nodes (agreement reference and version only), a bindable network scope id treated like a tenant by the seam, composite constraints, NetworkRepository port and Neo4j adapter. | NETWORK+SCHEMA | G01, TEN-G02 | 8 |
| TEN-N02 | S6 | Network administration use cases | HIGH | Create network, add or end membership, record agreement reference and version, create or end a Grant (scopes capacity, directory, criteria) with approval by the grantor's administrator and the network owner, versioning; a leaving tenant's grants lapse and projections are marked with the leave date. | NETWORK | TEN-N01, TEN-G04 | 10 |
| TEN-N03 | S3 | Projection allowlist and privacy guard | MEDIUM | Single allowlist module for the DEC-132 item 4 fields, `source` property on directory data (manual today), a test that no patient-level field can enter a projection (extends D17). | NETWORK | D17, TEN-N01 | 4 |
| TEN-N04 | S3 | Network projector worker | HIGH | Consumers on capacity, criteria and registration events read in the member's scope and write allowlisted copies into the network scope with sourceTenantId; honours grant dates; stops on grant end or leave; rebuild-from-source job; idempotent. | NETWORK+SEAM | TEN-N01, TEN-N03, I04, I05, U09 | 12 |
| TEN-N05 | S3 | Network read use cases | HIGH | QueryNetworkBoard, network pressure, network directory and criteria reads, bound to the network scope after a membership and grant check; the application layer merges own-tenant and network views (never one query across two scopes). | NETWORK | TEN-N04, U08 | 8 |
| TEN-N06 | S3 | Network API | MEDIUM | `$board?scope=network`, network SSE stream, directory and criteria read routes with owning-organisation fields; 404 for non-members. | NETWORK | TEN-N05, R05, R06 | 5 |
| TEN-N07 | S3 | Network cache key and live updates | MEDIUM | Per-network board key and channel written by the projector. | NETWORK+SEAM | TEN-N04, P09, U09 | 3 |
| TEN-N08 | S6 | Network administration API | MEDIUM | Routes over TEN-N02 for the network owner and tenant administrators. | NETWORK | TEN-N02, R02 | 4 |
| TEN-N09 | S6 | Network administration screens | MEDIUM | Member list, grants with approvals, agreement reference and version, leave history. | NETWORK | TEN-N08, W09 | 8 |
| TEN-N10 | S4 | Wall screen board-scope setting | LOW | Administrator chooses tenant board or network board for a paired screen (DEC-132 item 5); the device token carries the scope. | NETWORK | TEN-N06, U10, R15 | 3 |
| TEN-N11 | S4 | Network board UI variant | MEDIUM | Organisation label on tiles, tenant/network toggle on advisor and exec boards, view-only service cards from other members. | NETWORK | TEN-N06, W05, W13 | 6 |
| TEN-N12 | S4 | Network directory and criteria view | MEDIUM | Read-only service directory and current criteria of member organisations. | NETWORK | TEN-N06, W14 | 5 |
| TEN-N13 | S7 | Network week summary and pressure | MEDIUM | Capacity-derived figures only (bookings, cases and outcomes are not shared); owner decision on content. | NETWORK | TEN-N05, U35 | 4 |
| TEN-N14 | S3 | Two-member network tests | HIGH | Grant on and off, leave, history stays, no cross-scope join; extend the generated two-tenant test to the network scope. | NETWORK+SEAM | TEN-N04, TEN-G01 | 5 |

New rows: 20 rows, 124 hours (general tenancy 39 h, network 85 h).

## 1. Totals

Impact counts across the 215 tasks: NONE 75, LOW 65, MEDIUM 53, HIGH 22 (sum 215).

Action counts: REWORK-DELIVERED 40, AMEND-PROMPT 100, NO-CHANGE 75 (sum 215).

Where the REWORK-DELIVERED tasks sit by ledger status: all 40 are `delivered`. In-flight tasks (U02, U03, W02, I04, I09) are AMEND-PROMPT, not rework.

Extra hours by stage (the 215 tasks only):

| Stage | Extra h (rework + amendments) | Of which rework of delivered | Of which prompt amendments | New rows (below) |
|---|---|---|---|---|
| S0 Foundations | 19.5 | 19.5 | 0 | 0 |
| S1 Domain rules | 18.5 | 18.5 | 0 | 0 |
| S2 Capacity loop: core and storage | 79.5 | 68.5 | 11 | 38 |
| S3 Capacity loop: channels, API and wall board | 35.5 | 12.5 | 23 | 43 |
| S4 Advisor call | 19 | 0 | 19 | 14 |
| S5 Booking by text and link | 9 | 0 | 9 | 0 |
| S6 Registration and approval | 16.5 | 0 | 16.5 | 22 |
| S7 Reporter app, PIN, push and alerts | 19.5 | 0 | 19.5 | 4 |
| S8 Shift lead tools, clinical advice and safety | 12.5 | 0 | 12.5 | 0 |
| S9 Observability and support console | 15 | 0 | 15 | 3 |
| S10 Later | 4.5 | 0 | 4.5 | 0 |
| **Total** | **249** | **119** | **130** | **124** |

Overall: 249 h across the 215 tasks plus 124 h of new rows = **373 h** of extra work, against a plan of 720 h (247 h delivered). The largest items are G05 (10), G01 (9), P05 (8), P06 (6.5), F10 (6) and the new TEN-G04 (10), TEN-N02 (10) and TEN-N04 (12).

**Delivered tasks needing rework, sorted by risk (HIGH first, then by hours):**

| Rank | ID | Title | Impact | Extra h | Why it is risky |
|---|---|---|---|---|---|
| 1 | G05 | Graph writer and reader with versions | HIGH | 10 | All 17 Q-RES templates add `tenantId: $tenant` (MERGE on {tenantId,key}); label-less shared reads and the Q-RES-CLEAR-OWNED / LOAD-NODES prefix scans are tenant-scoped; Q... |
| 2 | G01 | Neo4j adapter base: driver, named queries, migrations | HIGH | 9 | THE SEAM. run_query adds `tenant=<bound>` from a ContextVar and raises a fixed-message error when none is bound; NamedQuery registration rejects text lacking `$tenant` un... |
| 3 | P05 | Audit log port with Neo4j hash chain and provenance | HIGH | 8 | One chain per tenant: AuditHead `{id:'audit'}` and `chain_seq` (unique on seq) become (tenantId,id) and (tenantId,seq); ensure_audit_head runs per tenant at creation; Aud... |
| 4 | P06 | Outbox and unit of work on Neo4j | HIGH | 6.5 | UnitOfWork.__aenter__ captures the bound scope and refuses to open without one (exactly one scope, DEC-132 item 4); Neo4jOutbox stamps tenantId and `outbox_message_id` go... |
| 5 | F10 | Neo4j test harness | HIGH | 6 | Harness creates a unique tenant per test run and binds it; `clean_graph` deletes only `{tenantId: $t}` nodes and keeps :Migration; `write_tx`, `read_tx`, `count_nodes`, `... |
| 6 | P03 | Person, role and practitioner ports with Neo4j repository | HIGH | 4 | Index `phone_hash` becomes (tenantId, phoneHash); Q-PHONE-SERVICES(-AT) and find_by_phone_hash run inside one tenant, so one mobile in two tenants is two Practitioners (D... |
| 7 | P13 | Registration and scope list ports with Neo4j repositories | HIGH | 4 | Scope list uses fixed List id `scope-list`, which collides with the global resource_id constraint for a second tenant: needs (tenantId,id) and one list per tenant; Q-REG-... |
| 8 | P16 | Contact store and PIN credentials on Neo4j, text-code store port | HIGH | 4 | ProtectedContact `key`, Credential `deviceId` and Device `id` uniqueness go composite; Q-DEVICE-OWNER/-KNOWN look up inside the tenant (device bound to the tenant at pair... |
| 9 | R02 | Authentication, roles and service scope | HIGH | 4 | BffClaims and the HS256 token gain a `tid` claim (reject tokens without it); Actor gains tenant_id; current_actor binds the tenant context for the request; issue_test_tok... |
| 10 | P10 | Link token, secret and phone-hash ports with Neo4j token store | HIGH | 3.5 | `link_token_hash` stays globally unique but Q-LINK-GET by hash is a tenantless allowlisted read returning tenantId (DEC-131 item 5); SecretStore.get takes tenant context.... |
| 11 | R06 | Server-sent events stream | HIGH | 3 | `GET /events` subscribes to the global `board.updates` channel, so any signed-in role would stream every tenant's service ids: subscribe to the caller's tenant channel (a... |
| 12 | P14 | Report and service flag ports with Neo4j repository | MEDIUM | 3.5 | 13 Q-FLAG-* statements: ReportFlag gets tenantId and `report_flag_id` goes composite; open_report_flags(None) lists only the bound tenant; ServiceFlag Basic nodes follow ... |
| 13 | I01 | Redis cache adapter | MEDIUM | 3 | Key builder reads the bound scope (`diucs:<tenant>:cache/lock/fence/chan`) and refuses without one; keep the test key_prefix as an outer prefix; add two-tenant Redis cont... |
| 14 | I02 | Service Bus event bus adapter | MEDIUM | 3 | `to_service_bus_message` sets `application_properties['tenantId']` (or network scope id) and the consumer side validates it; session id stays the service UUID; emulator c... |
| 15 | I06 | Twilio SMS adapter | MEDIUM | 3 | TwilioSms takes one account at construction: per DEC-131 resolve the tenant's subaccount SID, sender number and secret reference at send time (secret store, never a graph... |
| 16 | P01 | Service and capacity ports with Neo4j repositories | MEDIUM | 3 | Q-CAP-LATEST, -LATEST-FOR, -SINCE, Q-SVC-LAST-REPORT and Q-SVC-LIST-ACTIVE match HealthcareService by `{key}` or `{active}` with no tenant: add `tenantId: $tenant` on ser... |
| 17 | P02 | Booking port with Neo4j repository | MEDIUM | 3 | Q-BOOK-PENDING/-OPEN-FOR/-CONFIRMED-SINCE/-BY-REF match Task and HealthcareService by id: add tenant on both nodes. `get_by_reference` returns the latest booking for a 4-... |
| 18 | P04 | Criteria port with Neo4j repository | MEDIUM | 3 | Q-CRIT-CURRENT/-FOR/-VERSIONS/-SET-CURRENT: tenant on ServiceCriteria, HealthcareService and author role; Concept stays global; one-current-per-service is checked per ten... |
| 19 | P07 | Messaging ports, recording senders and Neo4j communication records | MEDIUM | 3 | Q-COMM-* add tenant; `by_provider_id` (Twilio SID) is called from the receipts consumer, so the tenant comes from the resolved subaccount/message property (DEC-131 item 2... |
| 20 | P15 | Idempotency store and processed-message markers on Neo4j | MEDIUM | 3 | IdempotencyRecord.key and Processed(messageId, consumer) uniqueness become (tenantId,key) and (tenantId,messageId,consumer); DriverIdempotencyStore opens its own transact... |
| 21 | U09 | Board projector: cache and live updates | MEDIUM | 3 | `board:v1` and the `board.updates` channel become per tenant via the cache adapter; handle() runs under the tenant bound from the message; test that tenant A events never... |
| 22 | G03 | Mapper: concepts, identifiers, periods and quantities | MEDIUM | 2.5 | Identifier nodes (`Identifier/system/value`) become tenant-scoped so two tenants' ODS identifiers never merge; Concept and CodeSystem stay shared. NodeSpec needs a shared... |
| 23 | P08 | Event bus port, manual-clock fake and Neo4j scheduled-work records | MEDIUM | 2.5 | ScheduledWork id constraint composite and Q-WORK-* tenant; BusMessage and ManualEventBus carry `tenant_id` so tests can see cross-tenant delivery. |
| 24 | P21 | Case port with Neo4j repository | MEDIUM | 2.5 | Constraint `case_reference_id` on ServiceRequest.reference becomes (tenantId, reference); Q-CASE-BY-REF and Patient/ServiceRequest/score nodes carry tenant; closing a cas... |
| 25 | P09 | Cache port with in-memory fake | MEDIUM | 2 | Cache keys, channels and lock names are tenant-prefixed `diucs:<tenant>:`; InMemoryCache must prefix with the bound tenant so use-case tests catch leaks; `board.updates` ... |
| 26 | D26 | Link tokens, pairing codes and support codes | MEDIUM | 1.5 | LinkTokenRecord gains `tenant_id` so the unauthenticated link edge binds the tenant from the stored record (DEC-131 item 5); pairing codes unique per tenant, support code... |
| 27 | D17 | No-patient-data guard for every template | LOW | 1.5 | Add the network projection allowlist guard and test: no field outside the DEC-132 item 4 list (patient-level, names, phones, devices, tokens, communications, bookings, ca... |
| 28 | R03 | ETag, If-Match and Idempotency-Key handling | LOW | 1.5 | Replay cache key `idem:<sub>:<key>` is tenant-prefixed through the cache adapter; ETag logic unchanged; two-tenant replay test. |
| 29 | U01 | ReportCapacity use case | LOW | 1.5 | No Cypher of its own: add the two-tenant use-case test (a reporter of tenant A reporting on tenant B's service id gets the non-revealing NotFound) and move the 617-line i... |
| 30 | U08 | QueryBoard read model | LOW | 1.5 | Tenant board needs no code change; add the two-tenant test (A's board excludes B's services, pressure computed within A). Network view is a separate read use case (TEN-N0... |
| 31 | D16 | Message templates: booking, invitations, codes, alerts | LOW | 1 | Template I2 hard-codes 'Dorset urgent care capacity': make the region name a template field from tenant config and update D17's SAMPLE_FIELDS. |
| 32 | F02 | Architecture import rules enforced by tests | LOW | 1 | Add an architecture test that only driver.py, migrations.py and health.py execute Cypher, so the run_query tenant injection (DEC-130 item 2) cannot be bypassed by a new `... |
| 33 | F08 | Settings and composition root skeleton | LOW | 1 | Container gains the tenant-context accessor and a TenantConfig/secret-reference port (DEC-131 item 4); Settings must hold no default tenant, and the single `sms_provider`... |
| 34 | F11 | Restartable Neo4j mode in the test harness | LOW | 1 | Restart and container-lifecycle tests destroy the shared Neo4j, so mark them exclusive (run alone) once runs share one database. |
| 35 | G02 | FHIR-to-graph mapper: resources, primitives, references | LOW | 1 | Reserve `tenantId` as a mapper-owned property name and keep from_graph ignoring it; the mapper stays pure and the writer stamps the tenant. |
| 36 | G04 | Mapper: backbone elements and extension registry | LOW | 1 | Backbone child nodes and ext_ properties inherit the owner's tenant; prefix ownership (`<parentKey>#...`) must be combined with tenantId in G05 queries. |
| 37 | G14 | Neo4j connection lifecycle, health and recovery | LOW | 1 | Neo4jConnection.session/run_read/run_write become the only tenant-free paths (health, migrations); add a test that they refuse application queries with no tenant bound. |
| 38 | P12 | Contract tests for the cache and event bus fakes | LOW | 1 | Add two-tenant cases to the cache and bus contract suites (same key or channel in two tenants stays isolated; the tenant property round-trips). |
| 39 | R01 | FHIR REST app skeleton | LOW | 1 | Per-request tenant binding is installed by the auth dependency; `/health` and `/fhir/metadata` become explicit tenant-free routes; tests/support/api.py gets a two-tenant ... |
| 40 | F04 | Local infrastructure with Docker Compose | LOW | 0.5 | Topology is unchanged (the tenant rides in a message property, not in entity names), but servicebus-config.json needs a `network-projector` subscription on capacity.event... |

The count of 78 statements in DEC-130 looks low: counting `id="Q-..."` and template keys in `backend/src` I get about 123 distinct statement ids (resource_store 17, flag_repository 13, audit_log 11, credential_store 10, communication 9, person 8, criteria 8, and so on). I could not confirm by importing the registry (running code was out of scope), so treat my hour figures for the P-series as sized for roughly 120 statements.

## 2. The prompt amendment text

Append the matching paragraph to the prompt of every task whose action is AMEND-PROMPT. Tasks marked NO-CHANGE need nothing (the paragraphs are harmless on them but add noise). Each paragraph is under 200 words and consistent with DEC-130, DEC-131 and DEC-132.

### 2a. Backend tasks (use cases, repositories, routes, workers)

**Tenancy (DEC-130, DEC-131, DEC-132).** This platform is multi-tenant: a tenant is one legal entity and every node carries `tenantId`. Never accept, pass or read a tenant in your code. It is bound once at the edge from the signed token or BFF session, the link-token record, the called number, or the validated message property, and `run_query` adds `tenant`. Every statement you register must write `tenantId: $tenant` on each node it matches, merges or creates; only shared Concept and CodeSystem reference nodes and allowlisted global statements are exempt, and registration fails otherwise. Never take a tenant from a request body, query string or caller-controlled header. Uniqueness is composite (`tenantId` plus the key), including references, idempotency keys and message ids. A unit of work binds exactly one scope. Another organisation's data is reached only through a network projection, never a join. Write a two-tenant test: seed tenants A and B, run your use case or query as A, and assert nothing of B is returned or changed, including a B id given as input (answer as not found). Keep tenant data and secrets out of logs.

(0 words)

### 2b. Frontend tasks

**Tenancy (DEC-130, DEC-132).** The browser never sends, chooses or reads a tenant identifier as input: no tenant field, query string, header or route segment is accepted by any BFF route. The tenant exists only in the sealed session and the back-end token. Show organisation-specific names, phone numbers and wording (display name, SPOA phone, region) from the API response, never from constants or environment variables. Where a screen shows capacity, directory or criteria for more than one organisation, build the network variant: label each item with its owning organisation, make other organisations' services view-only (no Request booking, I phoned or They declined), and keep the own-organisation view as the default. Test fixtures include two organisations, and a test proves data for another organisation is never rendered. Never put organisation data in telemetry attributes, URLs or localStorage.

(0 words)

### 2c. Tasks that touch Redis, Service Bus or SMS

**Tenancy for Redis, Service Bus and SMS (DEC-130, DEC-131).** Redis keys, lock names and pub/sub channels get the prefix `diucs:<tenant>:` from the adapter, using the bound tenant; a missing tenant is an error, never a default, and the network board uses its network scope id as the prefix. Every Service Bus message sets `application_properties['tenantId']`; a consumer binds it before opening a unit of work and dead-letters a missing or unknown tenant as PermanentError. Message ids and idempotency markers are unique per tenant. Text and email use the tenant's own Twilio subaccount and sender identity, resolved from tenant config at send time; credentials are secret-store references, never graph properties or log text. Inbound SMS resolves the tenant from `To` plus `AccountSid` before verifying the signature with that subaccount's token; an unknown number gets the fixed empty answer and an id-only log. Tests use a fake secret store and prove a tenant-A message never reaches tenant B's channel, queue handler or number.

(0 words)

Apply 2c in addition to 2a on these AMEND-PROMPT tasks: I03, I04, I05, I07, I08, I09, I10, I13, I14, I15, U03, U05, U22, U25, U34, U40, R11, plus the new rows TEN-N04 and TEN-N07. (I01, I02, I06, R03, R06, U09, P08, P09 and P12 are already delivered, so they are rework rows, not prompt amendments.) Apply 2b to these AMEND-PROMPT frontend tasks: W02, W05, W06, W07, W08, W09, W10, W13, W14, W17, W19, W22, W23, W29, W33, W36, W40, W41, W55, O02, W48, W49, W50, W53.

## 3. The critical path and wave plan

### 3.1 Principles

1. **The seam goes first and lands in two steps.** Step one is the tenant context, `run_query` injection and the registration check in *warn* mode, together with the F10 harness that binds a test tenant, so the roughly 123 existing statements keep working. Step two flips the check to *enforce* once G05 and the P-series are migrated. Turning enforcement on first would fail every unmigrated repository and every in-flight branch at once.
2. **Order of the tenancy chain** (each step needs the one before): G01 seam, F10 harness, TEN-G01 two-tenant test, TEN-G02 composite constraints (runs alone), G02/G03/G04 mapper, G05 store, then the P-series repositories in parallel, P06 unit of work, P15 idempotency, then adapters (I01, I02), AUTH (R02, R06, R01, R03), CONFIG (TEN-G03, I06) and LIFECYCLE (TEN-G04). TEN-N01 (network scope model) can start as soon as TEN-G02 is in, in parallel with the mapper and repositories. The network projector TEN-N04 needs the consumer framework (I04, I05), the outbox relay (I03) and U09, so the network chain finishes later than the tenant chain: TEN-N01, TEN-N03, TEN-N04, TEN-N05, TEN-N06, then the UI (TEN-N10 to TEN-N12).
3. **Longest sequential chain** (my estimate): G01 9 + F10 6 + TEN-G01 6 + TEN-G02 6 + mapper 4.5 + G05 10 + critical P-series repository about 9.5 + P15 3 + consumers I04, I05, I03 about 10 + TEN-N04 12 + TEN-N05 8 + TEN-N06 5 + TEN-N11 6, about **95 hours** if nothing waits. The network work adds roughly 40 hours at the end of the chain; it does not delay the tenant seam.
4. **New feature work after the seam is written tenant-aware** (its prompt is amended), so it creates no rework. Feature work that is unaffected can use the free slots now.
5. **One Neo4j test run at a time** until the tenant-per-run harness is delivered (DEC-130 item 9). After that, runs share one Neo4j and may run in parallel, except TEN-G02 and container-lifecycle tests (F11, G14 recovery), which run alone. `[N]` below means the wave may run Neo4j tests, `[P]` means no Neo4j is needed.

### 3.2 What can proceed now without waiting for the seam

Ready by dependency today and NONE impact (prompt unchanged): **I11** [P], **I12** [P], **S01** [P], **W32** [P], **W52** [P], **R16** [P], **R14** [N, route tests only]. Ready with only a one-line amendment and no Neo4j: **O02** [P], **W53** [P]. All pure domain rules are already delivered. I15 and G13 (S10) are ready but low priority and wait for the seam (cache keys and IRIs).

Ready by dependency but better started only once the seam exists, with the amended prompt: U07, R04, I07, U10, O01, U11, U16, G11, U23, U25, U26, U30, P17, P19, I13, U35, P18, P20, O06, O07. Each registers new Cypher, and the amendment requires `tenantId: $tenant` and a two-tenant test, which is only provable once the harness exists.

Must wait for the seam: every repository, the unit of work, adapters I01 and I02, and every use case after U08.

### 3.3 Wave plan (waves of up to four concurrent tasks)

| Wave | Tasks | Neo4j | Notes |
|---|---|---|---|
| 1 (now) | U02 (finish, current model), W02 (finish, current model), G01 seam step one (unit-level work first), I11 | [N]: U02 first, G01 integration run after it | In-flight tasks finish on the current model (DEC-130 item 10). G01 starts with pure unit work (context variable, injection, check in warn mode) so it needs Neo4j only after U02 has delivered. I11 is free work. |
| 2 | U03 (finish), F10 tenant-per-run harness, I12, S01 | [N]: U03 then F10 | F10 and G01 merge to main together so a default test tenant is bound everywhere. The U03 and I04 branches rebase onto it. Last wave that needs strictly serial Neo4j. |
| 3 | TEN-G01 two-tenant test, I04 (verify and deliver on current model), W32, R16 | [N]: TEN-G01 then I04 (emulator) | After this wave every run has its own tenant, so Neo4j runs can be parallel. |
| 4 | TEN-G02 composite constraints and backfill, O02, W52, D16 | [N] TEN-G02 runs alone; the others [P] | Schema-changing, so exclusive. D16 is a unit-level template change. |
| 5 | G02+G03+G04 (one lane, mapper), TEN-G03 tenant record and config, TEN-N01 network scope model, P05 audit chain | [N] parallel allowed | P05 only needs the seam, so it runs beside the mapper. TEN-N01 starts the network model early. |
| 6 | G05 resource store, R02 token and session claims, cache lane (I01, P09, P12), TEN-N03 allowlist guard with D17 rework | [N] G05, R02 | G05 is the biggest single rework; nothing that stores FHIR resources can be verified until it lands. |
| 7 | P01, P02, P21, P03 | [N] parallel | Separate files. P03 is HIGH (phone index). |
| 8 | P04, P13, P14, P16 | [N] parallel | P13 carries the fixed `scope-list` id collision. |
| 9 | P06 unit of work and outbox, P15 idempotency, P07 communication, P08 scheduled work | [N] parallel | P06 follows the repositories it wires. Seam step two (enforce the registration check) is switched on at the end of this wave. |
| 10 | I02 Service Bus tenant property, P10 link tokens, I06 per-tenant Twilio (DEC-131), TEN-G04 lifecycle | [N]; the I02 emulator run is serial | TEN-G04 needs P05 and P13. |
| 11 | U01, U08, U09, API lane (R01, R03, R06) | [N] | Delivered use-case and API reworks. R06 closes the cross-tenant SSE leak: move it forward if any shared environment is reachable by more than one tenant. |
| 12 | I03 relay, I05 scheduler consumer, I07 inbound SMS, TEN-G05 unauthenticated-edge resolver | [N] | First feature tasks written tenant-aware. I03 and I05 are on the network critical path. |
| 13 | TEN-N04 network projector, TEN-N14 two-member tests, L01 link API, U10 pairing | [N] | The projector needs I04, I05, U09, TEN-N01 and TEN-N03. |
| 14 | TEN-N05 network read use cases, TEN-N07 network cache and channel, R05 `$board` with network scope, R04 | [N] | |
| 15 | TEN-N06 network API, W05 wall board with network variant, W06, W09 staff sign-in | [N] API; W05, W06, W09 [P] | W09 needs the tenant record (TEN-G03). |
| 16 | TEN-N10 wall screen scope setting, TEN-N11 network board UI, TEN-N12 directory and criteria view, W07 | [P] | Frontend wave. |
| 17 onward | Remaining feature work in stage order (S4 advisor, S5 booking, S6 registration, S7 reporter app, S8, S9), with TEN-N02, TEN-N08, TEN-N09 (network administration) in the S6 slot, TEN-N13 in S7 and TEN-G06 in S9 | [N] parallel | Do not start S6 registration before TEN-G05 and W09 exist. |

**First three waves:** wave 1 is U02, W02, G01 seam and I11; wave 2 is U03, F10 harness, I12 and S01; wave 3 is TEN-G01, I04, W32 and R16.

Why the network chain cannot start earlier: grants and projections need working consumers (I03 to I05), the per-tenant board projector (U09) and the composite schema. Only the model (TEN-N01, wave 5) and the allowlist guard (TEN-N03, wave 6) can start early, and both are cheap and let information governance start reviewing (DEC-132 item 9 is human-only).

### 3.4 Network variants of existing tasks (DEC-132)

| Existing task | Variant | Covered by |
|---|---|---|
| U08 QueryBoard, D08 pressure | Network board and network pressure as a separate read use case bound to the network scope; own-tenant and network views merged in the application layer | TEN-N05 (U08 itself only needs the two-tenant test) |
| U09 board projector | Per-network cache key and channel written by the projector | TEN-N07 |
| R05 `$board`, R06 events | `scope=network` parameter; network stream for members only | R05 amendment, TEN-N06 |
| U10, R15, W08 wall screen | Device is paired to one tenant; the administrator sets tenant or network board | TEN-N10 plus amendments |
| W05, W06, W07 wall board | Organisation label on tiles, network pressure, stream scope | amendments, TEN-N11 |
| U12, G11, W13, W14, W50 advisor options, criteria, map | Network services shown view-only from projected data; booking, 'I phoned' and declines refused (a cross-tenant write, and bookings are not shared) | amendments, TEN-N12 |
| W10, W17, W40 home counts and 'system now' | Network counts and pressure; heading is the tenant or network name | amendments, TEN-N11 |
| U34, U35, R12, W41 alerts and week summary | Network pressure alert and network summary are owner decisions; only capacity-derived figures could be shown | amendments, TEN-N13 |
| D17 privacy guard | Projection allowlist and test | TEN-N03 |
| F04 infra | `network-projector` subscriptions | F04 rework |
| U27, U29, U30, U36 go live, criteria change, suspend | Start or stop projecting a service | amendments |
| U43, W51 planning | Stay tenant-only (decision snapshots are not shared) | no variant |

## 4. Conflicts with in-flight work

Live ledger state on 2026-10-28: U02 and U03 are `in-progress` after failed verification; W02 is `in-review` after failed verification r3 (a fourth verifier session, `verify-W02-r4`, was last seen at 11:30); I04 is `stale` with review requested, green evidence at fa0d5b3 and no verification recorded; I09 (not in your list) is also `stale`.

| Task | Do now (current model) | After the seam |
|---|---|---|
| U02 | Fix the seven verification findings and deliver: per-service write lock (set the HealthcareService id first, then read, then write) with the held-first-write and 16-caller race test, pin the stub message, rebase onto main, rerun the harness self-tests on a quiet machine, test the suspended case and the reverse key direction, make the U01 helper public. Add no tenant code. Keep the new `Q-CAP-TRAILING-CONFIRMS` statement small and parameterised so the sweep is a one-line change. | Add `tenantId: $tenant` to that statement and to the lock statement, and a two-tenant race test (+0.5 h). The lock pattern is what the seam relies on: a write lock on a tenant-qualified node. |
| U03 | Fix findings A to I now. A (the link token stored in plain text in `Communication.payloadText` and the outbox payload) is a security defect independent of tenancy and must not wait. Keep `link_base_url` a constructor argument, as it is, so config can later supply it per tenant. | Link token record carries the tenant; link host from tenant config; the idempotency key `prompt:{service_id}:{due_at}` is made tenant-safe by P15; messages are stamped by P06 (+1.5 h). Expect a merge with F10: rebase in wave 2. |
| I04 | Verify and deliver as built. It is the shared consumer framework, so later rework lands in one function (`IdempotentConsumer.handle`) and the runner conversion. Do not add a half-finished tenant hook. | Bind the tenant from the message property before opening the unit of work, dead-letter a missing or unknown tenant as PermanentError, make `mark_if_new` composite, add the property to the runner conversion (+2.5 h). TEN-N04 depends on this. |
| W02 | Finish the three verify-r3 findings (the expired-`exp` test that kills the jose survivor, the DEC-010 stub-file list in the evidence, the jose 6.1.0 age check) and deliver. No tenant code. | Add `tenantId` to Session, and make `withBff` refuse any `tenant` or `tenantId` query or body key (+1 h). This changes the sealed-cookie format, which is harmless before the pilot. |
| I09 (not asked) | Deliver as built, then rework for per-tenant sender identity (DEC-131 item 1, product under DEC-003). | +1 h. |

Merge risk: F10 changes the harness for everyone. Tell the owners of U02, U03 and I04 that the wave-2 rebase binds a default test tenant, so tests that seed raw nodes with `CREATE (...)` must add `tenantId` (the criteria, credential, flag, scope-list and registration integration tests do this most: 31, 31, 28, 21 and 20 matching lines).

## 5. Design gaps the owner or coordinator should settle (not decided by DEC-130 to DEC-132)

1. **Unauthenticated phone-only flows.** DEC-131 resolves inbound SMS by the number called, but a request that carries only a phone number (lost phone W55 and R13 `/identity/new-phone`, PIN reset, first text-code request R11 and U25) has no tenant. Proposed rule: a tenant hint (host or path slug) selects the lookup scope only, is resolved by one allowlisted statement, is overridden by any token, and every later check happens inside that tenant. DEC-130 item 6 currently forbids caller-controlled sources outright.
2. **The global-statement allowlist.** Link-token hash lookup (L01, L02, U24), pairing start and claim (U10, R15), device-token resolution, tenant-by-number lookup (I07) and the outbox relay's pending read (I03) are tenantless by nature. List them explicitly in G01's allowlist and record the exception to DEC-130 item 3.
3. **Shared Concepts can be written by a tenant.** `Q-RES-SHARED-FILL` in the delivered resource store merges `display` and `version` onto shared Concept nodes from any tenant request. DEC-130 item 5 says tenants never write reference data; G05's rework must seed code systems and make that statement read-only.
4. **Audit hash.** Decide whether `tenantId` goes inside the hashed `entryJson` (my recommendation; there is no production data to migrate).
5. **Advisor view across the network.** DEC-132 item 5 lets advisors see the network capacity view. Bookings, cases, 'I phoned' and declines are tenant-private, so a network option can only be a phone-to-confirm card. Confirm that is the intended workflow; otherwise a cross-tenant booking grant scope is needed (DEC-132 item 7 defers that).
6. **Network week summary.** Referrals, bookings and outcomes are not shared, so a network summary could show only capacity-derived figures. Owner to confirm (TEN-N13).
7. **Projector and the one-scope rule.** The projector reads in the member's scope and writes in the network scope as two units of work with an in-memory hand-off. State that this satisfies 'a unit of work binds exactly one scope'.
8. **Clinical advice pool.** A clinical queue shared by several tenants would be cross-tenant access; U40 is written as per-tenant.
9. **Name clash.** W09 uses `ENTRA_TENANT_ID` for the Microsoft directory. Keep 'tenant' for the DIUCS organisation in every prompt and call the Entra directory `entraDirectoryId`.
10. **DEC-130 statement count** (78) versus about 123 found by grep, noted in section 1.

## 6. What I could not read or verify

- Everything in the repository was readable. I read every task's prompt from the Goal through Rules and Build (lines trimmed to 260 to 420 characters in my working extracts) rather than every line of every prompt, and I did not read the 81 evidence files in full: delivered tasks were classified from the prompt, the live ledger record and the delivered source (graph_store, audit, outbox, cache, bus, auth, events, harness). If an evidence file records behaviour that differs from its prompt, my row for that task could be off.
- I did not run the registry, tests, Docker or the app, so the statement count and all hours are estimates.
- No `TEN-` ids from other auditors exist in the repository, so my new rows use provisional ids.
