# Tenancy audit F: tenant lifecycle, registration-to-data flow, users, roles, network and governance

Audit date 2026-10-28. Read-only audit of the specifications and the plan. Started at `main` 1ac81b9 (DEC-130). DEC-131 (65c7da2, per-tenant Twilio subaccount) and DEC-132 (2cf069e, tenant is the legal entity, Network with grants and read-only projections) landed while this audit was running. Sections 3 to 5 and 8 to 10 were rewritten against both. Where this file says "settled" it means an owner decision in `docs/delivery/decisions.md`. Everything else is a recommendation.

How to read the citations: `domain-rules.md:249` is a line in `docs/spec/`; `U28.md:54` is a line in `docs/plan/prompts/`; `migrations.py:20` is under `backend/src/diucs/adapters/outbound/graph_store/`; `DEC-nnn` is `docs/delivery/decisions.md`. DEC-125 is not on `main`. It exists only on branch `task/W02-bff-session-csrf` (line 1517 there), so anything built on it is unmerged.

Scope of reading. Read end to end: `docs/spec/domain-rules.md`, `contracts.md`, `architecture.md`, `fhir-data-model.md`, `observability.md`, `ui-screens.md` (all 4402 lines), `docs/delivery/hazard-log.md`, DEC-001, 032, 042, 050, 062, 064, 065, 071 to 074, 080, 082, 094 to 098, 104, 130, 131, 132. Prompt bodies (after the shared boilerplate) read in full: U03, U04, U05, U10, U15, U16, U23 to U35, U37, U38, U41, U43, P03, P05, P07, P08, P10, P13, P15, P16, L01, R02, R05, R06, R08, R10, R11, R15, R18, D27, I02 to I08, I10, I13, I14, O04, O06, O08, W08, W09, W23. Rules sections only: U36, U40, I12, O07. Every other prompt was searched by grep for the keys, hosts, wording and time-zone terms discussed below, not read in full. Not read: `LESSONS.md` beyond a grep, `evidence/*`, the live design canvas (DEC-129 says the repo snapshot is the spec), the Web-front-end prompts other than W08, W09 and W23, and the other audit files in this directory.

---

## 1. Summary and overall difficulty

The specifications never mention tenancy (a search for "tenan" in `docs/spec` finds only an unrelated word). DEC-130 settles the storage mechanics (a tenant id on every node, bound once at `run_query`, composite uniqueness, a generated two-tenant test). DEC-131 settles SMS and email (one Twilio subaccount per tenant, the number called identifies the tenant). DEC-132 settles the collaboration model (tenant = legal entity, a Network of tenants, sharing only by Grants and read-only projections, no query spans scopes). What none of them designs is the thing the owner asked for: the lifecycle "from registration through to the data and all users, flows, cyphers and UIs".

Overall difficulty: **high**. The storage seam is mechanical (78 named queries, one execution point). The hard parts are elsewhere:

1. **Every entry point that exists before a session has no tenant.** Link tokens, invitation links, pairing codes, wall device tokens, text codes and webhooks are resolved by a secret or a provider number, not by a signed session. DEC-130 item 6 covers only bearer tokens, sessions and worker messages. DEC-131 item 5 lists the rest as "still to bind". Section 3 designs each one.
2. **Roles are global today.** `lead`, `advisor` and `clinical` act on "all services" (`R02.md:62`). The `support` role is mapped from an Entra app role in the customer's own directory (`W09.md:48`), so a customer administrator could grant it to themselves. DEC-130 item 6 ("staff sign-in maps a user to exactly one tenant") is too strict for a clinician in two organisations.
3. **Shared state is keyed globally in at least 20 places** (section 3.3): `board:v1`, the `board.updates` channel, the `outbox-relay` lock, the single `AuditHead`, `IdempotencyRecord.key`, `ChainLink.seq`, `ServiceRequest.reference`, the fixed `scope-list` id, `Settings.area_districts`, `twilio_from`, one `bff-jwt` secret and one phone-hash secret, and others. The idempotency key one is a real data-leak path (an arbitrary client key returns another tenant's stored result).
4. **DEC-132 does not cover the booking flow, registration approval, criteria second approval, the chasing ladder, alerts or the week summary**, all of which cross legal entities today. Its three scopes are capacity, directory and criteria. Section 4.9 lists each gap with a proposed default. These are the largest unanswered design questions.
5. **Neo4j Community cannot enforce "every node has a tenant id"** (property existence constraints are Enterprise-only; `migrations.py:1-10`). A node missing its tenant id is invisible to every tenant-bound query. A service that vanishes from the board looks like "not listed", not "not updated". That needs a startup and daily invariant check, not only tests (section 2.6).
6. **Constants that are really tenant or network configuration**: London time zone in five modules, "Dorset" in five templates and screens, "SystmOne" in B1 wording, a Dorset-specific default for `area_districts`, the 14:00 second report, the 2-hour stale limit, pressure thresholds of 3 and 5 (section 6). Bank holidays are modelled nowhere (`D03.md:77` defers planned closures).

Difficulty by area (hours are my estimates for work beyond the DEC-130 seam tasks; the total is in section 10):

| Area | Difficulty | Why |
|---|---|---|
| Storage seam and constraints | Medium | Mechanical, but six of the 26 migrations change a constraint (expand and contract) (section 2.6) |
| Tenant lifecycle (create, activate, suspend, offboard) | High | Does not exist; offboarding touches Redis, Service Bus, Twilio, backups |
| Pre-session entry points | High | Six mechanisms, each needs a platform-scope resolver |
| Staff and operator identity | High | Multi-directory Entra, role source of trust, two audiences |
| Network, grants and projections | Very high | A new scope kind, a projector, staleness control, a read path for every advisor and board screen |
| Per-tenant configuration | Medium | About 45 settings; time zone threading touches five domain modules |
| Migration of existing data | Medium | Additive; pilot is not live, so likely only dev databases |
| UI | High | Operator console, tenant admin, network admin, chooser, plus a sweep of wording |

---

## 2. The tenant lifecycle that does not exist: design

### 2.1 Vocabulary (fixed by DEC-130, 131 and 132)

- **Platform**: the operator of the service. It is a scope (`platform`) that holds tenant records and nothing clinical. It is the data processor for tenants.
- **Tenant**: one legal entity (an NHS Trust, an ICB, a GP federation, a local authority team, a voluntary provider). It is the data controller for its own data. DEC-132 item 1.
- **Network**: a grouping of member tenants. Settled: one network today, owned by a lead hosting tenant (the network owner). DEC-132 items 2 and 5.
- **Scope**: the unit a unit of work binds to. Three kinds: `platform`, `tenant`, `network`. A network scope is treated like a tenant by DEC-130 (its own id; every node carries it in `tenantId`). I recommend a `scopeKind` recorded on the registry node and on each registered query (a tenant-scoped query refuses to run bound to a network scope and the reverse).

The property name stays `tenantId` (DEC-130 item 1). For nodes in the platform scope the value is the reserved string `platform`. For nodes in a network scope it is the network's scope id. Scope ids are random UUIDs, never reused.

### 2.2 Who does what in the lifecycle

| Actor | Where they sign in | What they may do | What they may never do |
|---|---|---|---|
| `platform-admin` (new role) | Operator's own Entra directory only (token `tid` equals the operator's tid), MFA, separate BFF audience `aud=ops` | Create, activate, suspend, resume, offboard tenants; create networks; record Twilio subaccount and number references; see tenant metadata | Read any tenant's business data; hold a tenant role |
| `platform-support` (the existing `support` role, renamed in meaning) | Operator directory only | Open a support access to one tenant (section 4.2.4) | Read the graph; approve their own access |
| `tenant-admin` (new role, tenant scoped) | Entra directory bound to that tenant | Tenant configuration versions, Entra group mapping, user administration, grants (as grantor admin), wall mode, retention view, the operator access log | Anything in another tenant or the network scope, except the grant and membership actions in section 4 |
| `network-admin` (new role, held in the owner tenant) | Owner tenant's directory | Network membership, agreement versions, grant approval as network owner, listing admission | Read a member's private data (DEC-132 item 2) |
| `lead` (existing) | Tenant's directory | Operational administration of the tenant's services, people, reporters, wall screens, suspend a service | Platform functions |

DEC-097 item 3 says the roles are "the ten members of `Role`, exactly". Adding `tenant-admin`, `network-admin` and `platform-admin` changes `contracts.md:79` and the W09 mapping; it needs recording as an amendment. The existing `support` role is kept but is platform support only.

### 2.3 The records (graph nodes, DEC-001: typed properties, no JSON, no map or list-of-maps)

All platform-scope nodes carry `tenantId = 'platform'`.

**`(:Tenant)`** (platform scope)

| Property | Type | Notes |
|---|---|---|
| `scopeId` | string (uuid) | Also copied to `tenantId` of every node the tenant owns |
| `slug` | string | Lower case, 3 to 40 characters, unique, never reused, used in URLs (`/t/<slug>`) |
| `displayName` | string | Shown in headers and messages, for example "Dorset HealthCare" |
| `legalName` | string | The legal entity |
| `odsCode` | string or absent | Organisation ODS code. Unique among active tenants |
| `organisationType` | code | NHS trust, ICB, GP practice, local authority, voluntary or independent, other (`ui-screens.md:2019-2023`) |
| `countryCode` | string | `GB` |
| `region` | code | Data region, for example `uk-south`. Fixed to the platform's UK region; recorded for the DPIA |
| `timeZone` | IANA string | Default `Europe/London`. Validated against an allow-list, initially only `Europe/London` (section 6) |
| `status` | code | `provisioning`, `active`, `suspended`, `offboarding`, `offboarded`, `purged` |
| `suspendMode` | code or absent | `read-only` or `blocked` |
| `suspendReason` | code or absent | Fixed list, no free text |
| `createdAt`, `activatedAt`, `suspendedAt`, `offboardingStartedAt`, `offboardedAt`, `purgedAt` | datetime | UTC |
| `retentionHoldUntil` | datetime or absent | Blocks deletion of audit and safety records |
| `currentConfigVersion` | integer | Points at the `TenantConfigVersion` in force |
| `epoch` | integer | Incremented on suspend, resume, role-mapping change. Sessions carry it and are refused when it is behind |
| `hashKeyVersion` | integer | `0` means the legacy global phone-hash and token keys (default tenant only); `1` means per-tenant derived keys |
| `dsaRef`, `dpiaRef`, `dcb0160Ref` | strings or absent | Reference ids only. The documents are never stored |

**`(:TenantContact)`** (child of Tenant, platform scope): `kind` (`spoa-phone`, `support-email`, `shift-lead-escalation`, `clinical-safety-officer`), `label`, `value`. These are organisational contacts, not personal. They feed the "[SPOA phone number]" placeholders (`ui-screens.md:1200`, `3261`, `3479`; `W36.md:51`) and the K3 safety-concern routing (`U41.md:55`). They must be role or switchboard numbers; the privacy guard (D17) runs on them.

**`(:TenantChannel)`** (child of Tenant): `kind` (`sms`, `email`), `provider` (`twilio`, `smtp`, ...), `accountSid` (an identifier, not a secret), `secretRef` (the id of the secret in the secret store, DEC-131 item 4), `status` (`active`, `retired`, `quarantined`), `senderLabel` (for example "DIUCS Dorset"), `fromAddress`, `fromDisplayName`. The auth token is never on a node.

**`(:TenantNumber)`** (platform scope): `e164`, `accountSid`, `tenantScopeId`, `status` (`active`, `retired`, `quarantined`), `quarantineUntil`. Unique on `e164` globally. This is the allowlisted lookup for inbound SMS (DEC-131 item 2). A retired number stays quarantined for 90 days [ASSUMED] before it can be given to any tenant, so replies from old contacts cannot land in a new tenant.

**`(:TenantEntraBinding)`** (platform scope): `entraTenantId` (the `tid` GUID), `status`, `verifiedAt`, `verifiedBy`. Created only by the operator after domain verification.

**`(:TenantRoleMapping)`** (platform scope): `entraTenantId`, `groupObjectId`, `role` (a tenant-scoped role), `status`. This replaces reading roles from the `roles` claim (`W09.md:48`). The BFF maps `(tid, group ids)` to roles only through rows that exist for a tenant bound to that `tid`.

**`(:TenantConfigVersion)`** (tenant scope): `version`, `status` (`draft`, `pending-approval`, `current`, `superseded`), `createdAt`, `createdByAccountRef`, `effectiveFrom`, `reasonCode`, `approvedAt`, `approvedByAccountRef`, `secondApprovedByAccountRef`. Linked `(:Tenant)-[:CURRENT_CONFIG]->` and `-[:SUPERSEDES]->` the previous version, the same pattern as criteria (`fhir-data-model.md:166-176`). A version is immutable once `current`.

**`(:TenantSetting)`** (child of a version, `HAS_SETTING`): `key`, and exactly one of `intValue`, `textValue`, `boolValue`, `timeValue` (a Neo4j `time`), plus `unit`. A code registry (`TENANT_SETTINGS`) defines for each key the type, default, bounds, and a safety class (`clinical` or `operational`). Settings in the `clinical` class need a second approver (a person other than the author; the same rule as DEC-032). Typed rows follow DEC-080's draft pattern; they avoid a migration for each new setting.

**`(:TenantRetention)`**: `dataClass` (`capacity-reports`, `bookings`, `case-audit`, `communications`, `telemetry-raw`, `telemetry-aggregates`, `audit-chain`, `safety-concerns`), `keepDays`, `action` (`delete`, `summarise`). Default: no row, and activation is blocked until IG has set the classes (`architecture.md:285`: "a retention schedule IG sets").

**`(:TenantInvitation)`** (tenant scope): `role`, `phoneHash` (tenant-keyed), `entraTenantId`, `expiresAt` (48 hours, `domain-rules.md:234`), `status`. A link token of purpose `tenant-admin-invite` resolves to the tenant (section 3).

**`(:TenantTombstone)`** (platform scope), written at purge: `scopeId`, `slug`, `purgedAt`, `exportManifestHash`, `finalAuditHash`, and one child row per label with `label` and `deletedCount`. It proves the audit chain existed without keeping it.

Network records are in section 4.

### 2.4 State machine (a pure domain rule, like D22)

```
provisioning -> active <-> suspended -> offboarding -> offboarded -> purged
                 ^______________________/ (reopen before purge)
```

| Transition | Who | Preconditions | Effects |
|---|---|---|---|
| Create | platform-admin | Unique slug; legal name; owner tenant of an existing network if it is a member | `Tenant` in `provisioning`; `TenantConfigVersion` 1 as `draft` from platform defaults; tenant audit chain created (genesis is `sha256("diucs-genesis:" + scopeId)`, section 2.6); secret references recorded |
| Activate | platform-admin plus a second operator | `activation_blockers(tenant)` is empty (below) | Config version 1 becomes `current`; `activatedAt`; first tenant admin invitation sent |
| Suspend | platform-admin (urgent: one person, reviewed by a second within 24 hours) | Reason code | `suspendMode` set; `epoch` incremented; relay and consumers skip the tenant; see below |
| Resume | platform-admin plus tenant-admin confirmation | Reason resolved | `epoch` incremented; per service the next `prompt-due` is rescheduled (the logic of `ResumeService`, `U36.md`); a `StatusChanged` is emitted per service so boards recompute |
| Start offboarding | tenant-admin request or platform-admin | Notice period 30 days [ASSUMED] | Read-only; prompts stop; network membership ended (section 4.5); export enabled |
| Export | platform-admin on tenant-admin request | Offboarding | Export package (below) |
| Offboard | platform-admin | Export delivered and acknowledged, or the tenant waives it in writing | `offboardedAt`; numbers retired and quarantined; Twilio subaccount closed (human) |
| Purge | two platform-admins | `retentionHoldUntil` passed; typed confirmation of the slug; dry-run counts reviewed | Per-label batched delete by `tenantId`; Redis keys under `diucs:<scopeId>:` deleted; tombstone written; backups expire by schedule (IG to accept) |

**Activation blockers** (a pure function that returns a list, like `missing_for_approval`, `domain-rules.md:236-240`): config version approved; time zone set; at least one `TenantNumber` active with a test text delivered; email sender verified if email is used; first tenant admin invited; Entra binding verified and at least one role mapping; support contacts set (`spoa-phone`, `clinical-safety-officer`); retention set for every data class; `dsaRef`, `dpiaRef`, `dcb0160Ref` recorded; area districts set if the tenant registers services (section 6); not a member of a network without an accepted agreement. Attestations that are human-only (IG, clinical safety) are recorded as Provenance by the operator and a second person; the system records that they were asserted, not that they are true.

**Suspend, safely.** A suspended tenant's board is a patient-safety event for any network that reads it. Effects: the tenant's own sessions, link tokens, device tokens and webhooks get fixed generic refusals; prompts stop and open booking requests are held; its network projections stop and the network view marks its services "Not updated, phone to confirm" through the staleness rule (section 4.7). Mode `read-only` lets the tenant admin export and read; mode `blocked` is for a security incident. The advisor and wall screens must show the "tool offline" state (`ui-screens.md:745-752`), never a blank board (hazard H-20).

**Export package** per data class, each with a manifest hash: directory and criteria history, capacity reports, registrations, communications metadata, audit chain with a verification manifest, safety concerns (text from the protected store only if the tenant asks). Protected contacts are included on request because the tenant is the controller of its staff's data. Cases are cleared at close (`domain-rules.md:174`), so only open or audited cases appear.

**Audit.** Two chains. The platform chain (`tenantId = 'platform'`) records every lifecycle action. The tenant's own chain records the same actions as events about the tenant, so the tenant sees what the operator did. Both use the P05 hash chain.

### 2.5 The first tenant admin: how created and how signed in

1. The operator creates the tenant and a `TenantInvitation` for role `tenant-admin` with the admin's mobile (hashed with the tenant's key) and the expected Entra directory.
2. A link token of purpose `tenant-admin-invite` is texted from the tenant's own number (DEC-131). The link `https://diucs.example/i/<token>` resolves the tenant from the token record (section 3.2).
3. The person verifies the mobile by text code (U25 flow, purpose `register`), then signs in with Microsoft Entra ID in the directory named by the binding. The BFF checks that the token's `tid` equals the bound `entraTenantId`.
4. The first sign-in consumes the invitation and creates a `Practitioner` and a `PractitionerRole` with code `tenant-admin` in that tenant. From then on the role comes from the group mapping the admin creates.
5. If either check fails, the invitation is not consumed and the refusal is the fixed message "Your account does not have access" (`W09.md:48`).

Entra detail. `W09.md:47` configures one directory (`ENTRA_TENANT_ID`). A second organisation's staff cannot sign in to that app registration. Use one multi-tenant app registration, with the issuer checked against the `TenantEntraBinding` allow-list, or one registration per tenant. I recommend the multi-tenant registration with the allow-list.

### 2.6 Migrating the existing single-tenant data: exact steps

State today: 78 of 215 tasks are recorded as delivered in `ledger.jsonl` (`STATUS.md` is stale and says 48), no go-live, so the data is development and pilot data. The steps below are still required because they are also the production schema change.

**Preconditions.** Stop the outbox relay, consumers and the scheduler; drain Service Bus to zero (messages without a tenant property must not exist when the cut-over finishes). Take a Neo4j backup and restore it to a scratch instance to prove it works. Record `MATCH (n) RETURN labels(n) AS l, count(*) AS c`.

**Step 1: create the platform and default tenant.** Write the platform scope registry. Write one `Tenant` with a random `scopeId` (not the literal word "default"), slug taken from the pilot's name, status `active`, `hashKeyVersion = 0`, `TenantConfigVersion` 1 holding the values that are the code constants today (so behaviour does not change). Write one `Network` with that tenant as owner only if the pilot has more than one organisation.

**Step 2: expand the schema** (new migrations 0031 onward; never edit an applied one, `migrations.py:5`). Add indexes on `tenantId` for every label that is queried by it. Add the composite constraints alongside the old ones (the table below). Property existence constraints cannot be added on Community.

**Step 3: backfill in batches.** For each label, in an order that is safe to restart:
`MATCH (n:<Label>) WHERE n.tenantId IS NULL CALL { WITH n SET n.tenantId = $t } IN TRANSACTIONS OF 10000 ROWS`.
Exclude shared reference data: `Concept`, `CodeSystem`, `Migration` (DEC-130 item 5). Do not change any `entryJson`, `chainHash` or `previousHash`, so the audit chain still verifies. Set `tenantId` on `AuditEvent`, `ChainLink`, `AuditHead`, `Snapshot`, `Provenance`, `AuditRef`. Rename the head to `{id: 'audit:<scopeId>'}` through a new node, not an edit, and keep the old one until verified. The default tenant keeps the all-zero genesis; new tenants use `sha256("diucs-genesis:" + scopeId)` so a chain cannot be spliced into another tenant.

**Step 4: key material.** The default tenant keeps the legacy global keys (`hashKeyVersion = 0`) so existing `phoneHash`, `tokenHash`, `pinHash` and code hashes stay valid. New tenants use keys derived per tenant (HKDF from the master secret and the scope id), so the same mobile number hashes differently in each tenant and a hash cannot be used to link people across tenants. Phone hashes could be recomputed from `ProtectedContact`, but link tokens expire anyway, so I do not recommend a rehash.

**Step 5: Redis, Service Bus, secrets, Twilio, Entra.** Flush Redis (cache and sessions only; everyone signs in again, `architecture.md:15`). New key prefix `diucs:<scopeId>:` for tenant data and `diucs:n:<networkScopeId>:` for network data. Add the tenant message property; after the drain, consumers dead-letter a message with no tenant as a permanent error. Record the existing `twilio_from` and account as the default tenant's `TenantNumber` and `TenantChannel`; move the number into a subaccount (human-only, DEC-131 item 1). Record the existing Entra directory as the default tenant's `TenantEntraBinding` and map its groups.

**Step 6: verify before lifting the freeze.** (a) `MATCH (n) WHERE n.tenantId IS NULL AND NOT n:Concept AND NOT n:CodeSystem AND NOT n:Migration RETURN labels(n), count(*)` returns nothing. (b) Per-label counts equal the pre-migration counts. (c) `verify_chain()` is true for the default tenant. (d) The generated two-tenant test (DEC-130 item 4) passes with the default tenant and a second synthetic tenant. (e) A board, a prompt and a reply run end to end.

**Step 7: contract the schema** after one clean release: drop the single-property constraints that the composite ones replace; remove the legacy default.

**Rollback.** The expand phase is additive. Until step 7, rolling the code back is safe. After step 7 the rollback is the restored backup.

**If no production data exists when the first tenant goes live**, skip steps 3 and 4 and create the tenant at first deploy. Keep the migration for development databases.

**Constraint and index conversion** (from `migrations.py:20-132`, 26 entries):

| Migration | Today | Action |
|---|---|---|
| 0001 `resource_id` | `Resource.id` unique | Keep. Ids are server-minted UUIDs. A reference to a foreign id must never create a placeholder (section 3.4) |
| 0002 `identifier_key` | `(system, value)` unique | Change to `(tenantId, system, value)`. Today one ODS Identifier node can be shared by two organisations; that is a cross-tenant path (`fhir-data-model.md:486`) |
| 0003 `concept_key` | `(system, code)` unique | Keep. Shared read-only reference data (DEC-130 item 5) |
| 0004 to 0008 | Indexes | Add `tenantId` to the leading position of the composite indexes where used |
| 0009 `scheduled_work_id`, 0014 `communication_id`, 0016 `audit_event_id`, 0018 `audit_ref_id`, 0019 `provenance_id`, 0023 `device_id`, 0027 `report_flag_id`, 0028 `outbox_message_id` | Random id unique | Keep (ids are UUIDs); add `tenantId` index |
| 0017 `audit_head_id` | `AuditHead.id` unique | Id becomes `audit:<scopeId>`; keep the constraint |
| 0020 `chain_seq` | `ChainLink.seq` unique | Change to `(tenantId, seq)` |
| 0021 `link_token_hash` | `tokenHash` unique | Keep global. The token is random and the hash lookup is how the tenant is found |
| 0022 `case_reference_id` | `ServiceRequest.reference` unique | Change to `(tenantId, reference)` |
| 0025 `protected_contact_key` | `roleId\|kind` | Change to `(tenantId, key)` |
| 0026 `credential_device_id` | `deviceId` unique | Keep global: device ids are random per enrolment (section 3.2) |
| 0029 `idempotency_record_key` | `key` unique | Change to `(tenantId, key)`. **Must change.** A client-chosen `Idempotency-Key` (`R03.md:56`) can otherwise return another tenant's stored result |
| 0030 `processed_key` | `key` unique | Change to `(tenantId, key)` |

### 2.7 New use cases, routes and screens

Use cases: `CreateTenant`, `RecordTenantChannel`, `ActivateTenant`, `InviteTenantAdmin`, `BindEntraDirectory`, `MapEntraGroup`, `DraftTenantConfig`, `ApproveTenantConfig`, `SuspendTenant`, `ResumeTenant`, `StartOffboarding`, `ExportTenant`, `PurgeTenant`, `ListTenants`, `GetTenantHealth`, `ListMyTenants` (for the chooser), `OpenSupportAccess` (extends O06), plus the network use cases in section 4.

Routes (not FHIR; separate auth audience, no `/fhir` prefix): `/platform/tenants` (list, create), `/platform/tenants/{id}` (read), `/platform/tenants/{id}/$activate`, `$suspend`, `$resume`, `$offboard`, `$export`, `$purge`; `/platform/tenants/{id}/channels`; `/platform/networks`; `/tenant/config` (versions), `/tenant/users`, `/tenant/entra`, `/tenant/operator-access-log`, `/tenant/networks`, `/tenant/grants`; `/me/tenants` (chooser).

Screens: operator console (tenants list, tenant detail, create wizard, activation checklist, suspend, offboard, export, purge dialogs, network list); tenant admin (configuration versions with a diff, channels read-only, Entra mapping, retention, operator access log, users and roles, grants, wall mode); tenant chooser at sign-in; a persistent tenant name in the header of every staff screen; wall board header taken from configuration (replaces the hard-coded "Dorset urgent care capacity", `ui-screens.md:657`, `W05.md:51`).

Task list in section 10.

---

## 3. The registration-to-data flow, step by step

### 3.1 Principle

A tenant is established at exactly one point in each flow, from a source the caller cannot choose, and bound once (DEC-130 items 2 and 6). Three kinds of source exist:

1. **A signed session** (staff and the reporter app): the tenant is a claim, and the API also checks it against a per-tenant `epoch` so a suspended tenant's tokens stop working (DEC-094 item 4 says a token is valid until `exp` with no revocation; that is not acceptable once tenants can be suspended).
2. **A server-held record found by a secret** (link tokens, invitation links, pairing codes, wall device tokens): the tenant is a property of that record.
3. **A provider fact** (inbound SMS): the number called and the Twilio `AccountSid` (DEC-131 item 2).

DEC-130 item 6 names only the first kind and worker messages. Kinds 2 and 3 need a short list of **platform-scope statements** on the allow-list of item 3 that return only a tenant id and a status. They never return business data.

### 3.2 Pre-session entry points (what DEC-131 item 5 left to bind)

| Entry point | Today | How the tenant is established | Notes and failure handling |
|---|---|---|---|
| Link token, capacity or booking (`GET/POST /links/{token}`, `contracts.md:139`; `L01.md`) | `Q-LINK-GET` by `tokenHash` (unique, migration 0021) | `Q-LINK-TENANT-BY-HASH` (platform scope) returns `tenantId` and `status`. The bound lookup then runs `Q-LINK-GET` inside the tenant. Unknown, expired, used or suspended all give the same 410 body (`L01.md:54`) | Keep `tokenHash` unique globally. The CSRF secret `link-csrf` (`L01.md:55`) is derived per tenant. The page header shows the tenant name and the service |
| Invitation link `/i/<token>` (`U24.md:58`) | Token purpose `invite` | Same resolver. `/register` takes `?invite=<token>` (`W23.md`) so the tenant is known before any phone is typed | A tenant-admin invitation uses purpose `tenant-admin-invite` |
| Text code request and verify (`U25`, `R11.md`) | `(phoneHash, purpose)`; request carries only a mobile | During registration the invitation token gives the tenant. For later sign-in (set-up, re-verify, PIN reset) the **installed app is per tenant** (`/t/<slug>/app`, manifest `start_url` and `scope` include the slug). The slug is a hint; the authority is a `Practitioner` found in that tenant by the tenant-keyed phone hash | Code key `diucs:<scopeId>:code:<hash>:<purpose>`; the code is texted from the tenant's number (DEC-131 item 5); unknown number gets the identical response, as `U25.md:56` requires |
| Inbound SMS (`I07`) | Allow-list by `phoneHash` only (`I07.md:55`); idempotency key `diucs:idem:sms:<MessageSid>` (`I07.md:56`) | `To` + `AccountSid` -> `TenantNumber` -> tenant (DEC-131 item 2). The signature is checked with that subaccount's token. Idempotency key `diucs:<scopeId>:idem:sms:<sid>`. The queued message carries the tenant property | Unknown number: fixed empty answer, log the id only. `U05` then runs bound to the tenant, so `find_by_phone_hash` and `latest_prompt_for_phone` (`U05.md:55`) can only see that tenant |
| Delivery receipt (`I08`) | `by_provider_id` | `AccountSid` -> tenant; `Communication` matched inside the tenant | |
| Wall pairing code (`U10`, `R15`) | Code hash looked up with no tenant; start is unauthenticated (`R15.md:59`) | Pairing records live in the platform scope (`WallPairing`: `codeHash`, `secretHash`, `expiresAt`, `status`). The code is unique among open pairings (regenerate on a clash). The lead of tenant T confirms it, which writes `tenantId = T` into the record. The claim then returns the device token | Rate-limit the unauthenticated start per address (none is specified). The lead's page says "Connect to <tenant name>" before the button. The paired screen shows the tenant name large for 10 seconds |
| Wall device token (`W08.md`) | Hash lookup, `sub` is the device id | The bearer is the opaque token. The backend resolves it each request (hash -> device -> tenant, status, `displayMode`; cached at most 60 seconds). No long-lived JWT with a tenant claim | Suspend and revoke take effect at the next request |
| Staff sign-in (`W09`) | One Entra directory; role from the `roles` claim; JWT `sub` is `oid` | `tid` + group ids -> `TenantRoleMapping` -> candidate tenants -> a `Practitioner` with that account reference in each. One tenant: sign in. More than one: chooser. The session holds exactly one tenant | `sub` must be `tid` + `oid`; an `oid` is unique only within one directory. Platform roles are ignored unless `tid` is the operator's |
| Operator sign-in | none | `aud=ops`, operator directory, separate route group and cookie | |
| Push subscription | one origin | Per tenant (section 5.5) | |
| Service Bus messages and `ScheduledWorkDue` | no tenant | A required `tenantId` application property. The handler binds it, loads the aggregate and checks the node's tenant equals it; a mismatch dead-letters (a permanent error) | Topic names stay global. Session id on `capacity.events` becomes `<scopeId>:<serviceId>` |
| Outbox relay (`I03.md:58`) | One global lock `outbox-relay` | The relay loops over active tenants, binds each in turn and drains up to a fair batch per tenant (one tenant's backlog must not starve the others) | Lock per tenant: `diucs:<scopeId>:lock:outbox-relay` |

### 3.3 Global keys and singletons that must become scoped

| # | Item | Where | Change |
|---|---|---|---|
| 1 | Board cache `board:v1` | `U09.md:52`; `contracts.md:261`; `board_projector.py:31` | `diucs:<scopeId>:board`, and `diucs:n:<networkScopeId>:board` for the network view |
| 2 | Live channel `board.updates` | `contracts.md:122`; `P09.md:52`; `cache.py:12` | One channel per scope; the stream subscribes only to the caller's scope |
| 3 | SSE `GET /events` | `R06.md:54` | Binds the caller's scope; a network channel is allowed only after a membership check |
| 4 | Outbox relay lock | `I03.md:58` | Per tenant |
| 5 | `AuditHead {id:'audit'}`, `ChainLink.seq` | `P05.md:57`; `audit_log.py:97`; migrations 0017, 0020 | One head per scope; `(tenantId, seq)`; per-tenant genesis (section 2.6). This also removes the single write hot spot P05 notes |
| 6 | `IdempotencyRecord.key`, `Processed.key` | migrations 0029, 0030 | `(tenantId, key)`; the actor also goes into the stored fingerprint (DEC-104 item 3 already does this per use case) |
| 7 | `ServiceRequest.reference`, booking references | migration 0022; DEC-041 item 6; DEC-131 item 3 | Unique per tenant |
| 8 | Fixed list id `scope-list` | `P13.md:54`; `DEC-082` item 1; `R10.md:53` | `Resource.id` stays globally unique, so the id becomes `scope-list-<scopeId>`; the API alias `scope-list` resolves in the caller's scope |
| 9 | Shared `Identifier` nodes, reused district `Location`s, "reuse an existing practitioner with that hash" | migration 0002; `U27.md:56` and test 2; `U15.md:55` | All per tenant. These three are explicit sharing instructions in prompts and must be rewritten |
| 10 | `Settings.area_districts` default DT1 to DT11, BH1 to BH31 | `U28.md:54` | Tenant setting with no default (section 6) |
| 11 | `twilio_from`, `base_url`, `email_from`, message-id domain | `settings.py:18,34,42`; `smtp_email.py:26` | Tenant channel rows. `base_url` stays one global host (short links) |
| 12 | Secrets `link-token`, `phone-hash`, `link-csrf`, `pin-hmac`, `code-hmac` | `P10.md:55`; `L01.md:55`; `U32.md:55`; `U25.md:55` | Derived per tenant; `bff-jwt` and `BACKEND_JWT_SECRET` stay platform keys, with a tenant claim and `epoch` |
| 13 | Redis `diucs:idem:sms:`, `diucs:sess:`, `diucs:sess-by-person:`, `diucs:code:`, `presence:clinical:<id>`, `recheck:{phone_hash}:{service_id}` | `I07.md:56`; `I13.md:55,57`; `U40.md`; `U05.md:56` | Prefix `diucs:<scopeId>:` |
| 14 | Safety concern counter `SC-nnnn` | `U41.md:54` | Counter node per tenant (the reference is shown in K3 text) |
| 15 | Daily criteria job singleton and "07:00 London" | `U31.md:54,59` | `ensure_daily_schedule()` per tenant; run time and zone from tenant settings |
| 16 | Phone-hash as a cross-tenant join key | `P10.md:55` | Per-tenant keys make hashes unlinkable between tenants |
| 17 | Telemetry attributes and daily aggregates have no tenant | `observability.md:24-34`; `fhir-data-model.md:303-307`; `O04.md` allow-list | Add an opaque `tenant.id` attribute and a `tenantId` on `FunnelDaily` and the others |
| 18 | `Settings.minutes_per_avoided_call` | `U35.md:59` | Tenant setting (the baseline is measured per organisation, `ui-screens.md:4399`) |
| 19 | Cookie `diucs_session`, `Path=/` | DEC-125 item 9 (branch only) | Cookie name includes the slug, path `/t/<slug>`, so two tenants in two tabs stay independent |
| 20 | Role from the Entra `roles` claim | `W09.md:48` | Group mapping per tenant (section 2.3) |

### 3.4 Cross-tenant reference checks

Rule (from DEC-130 item 1): a relationship is in the scope of the nodes it joins, and no query joins two scopes. The one allowed cross-scope target is shared reference data (`Concept`, `CodeSystem`, `IN_SYSTEM` and the concept-valued relationships, `fhir-data-model.md:317-319`).

1. **No placeholders.** The resource store creates a placeholder node for an unknown reference (DEC-053 item 8; P13 and P03 added explicit `NotFound` checks before the write, DEC-064 item 8). With tenant binding, a reference to an id that exists in another tenant would either create a placeholder in this tenant or collide with `Resource.id` and surface a `Conflict`, which tells the caller the id exists elsewhere. Recommend that in tenant mode the store refuses to create placeholders (`InvalidReference`), and every refusal for a foreign id returns the same body as a missing record.
2. **Audit placeholders.** `AuditRef` placeholders created by id (`P05.md:57`, `contracts.md:219`) are per scope.
3. **A generated matrix test.** For every relationship type in the catalogue (`fhir-data-model.md:314-365`) and every platform relationship (`FOR`, `ABOUT`, `FOR_PROMPT`, `HAS_CREDENTIAL`, `HAS_DEVICE`, `COVERED_BY`, `SHARED_VIA`, `SHARED_BY`, `OPENED_BY`, `OPENED`, `HAS_VERSION`), seed the source in tenant A and a target in tenant B and assert: refusal, the same body as a missing target, zero writes. The specific entry points to name in the test: a scope entry or registration pointing at another tenant's service (`R10.md:53`), a `PractitionerRole` for another tenant's service or practitioner (`P03.md`, DEC-064 item 8), a cover practitioner (DEC-064 item 5), a `CURRENT_CRITERIA` or `SUPERSEDES` pointing across, a booking `OWNER` or `FOCUS`, a `Communication` `RECIPIENT`, a Subscription `CONTACT`, a `ServiceMove`, a safety concern `FOCUS`.
4. **The network scope** holds copies, never references: every projected node has `sourceTenantId` and `sourceNodeId` as properties, not relationships.

### 3.5 The flow, step by step

Settled by DEC-132: each organisation registers and operates its own services inside its own tenant. The network owner does not write into a member's tenant. What the network sees is a projection (section 4). The steps below mark where the network scope is involved.

**Step 0. The tenant, the network and the grants exist.** Section 2 and section 4. Nothing below can start until the tenant is `active`, the tenant is an active member, and the grants for `capacity`, `directory` and `criteria` are active. A tenant that is not a member can still run its own board and prompts.

**Step 1. Staff accounts and the tenant's own reporters are invited.** Today the shift lead invites a person for an `in-pilot` scope entry (`U23`, `U24`). Under DEC-132 the invitation is written by the tenant's own `lead` in the tenant scope.
- Records: `Task invite-reporter` and a `Registration` in state `invited`; the reporter's mobile in `ProtectedContact`; `LinkToken` purpose `invite`; a `Communication` I1 (`U24.md:55-60`).
- Owner: the tenant. Keys: `LinkToken.tokenHash` global; everything else tenant scoped.
- Establishes the tenant: the lead's session. The recipient's tenant is established later from the token.
- Check: the mobile is hashed with the tenant's key, so the same number invited by another tenant is a separate person.
- The "in-pilot" gate (`domain-rules.md:234`) moves. It is no longer a tenant-side check (it would need a cross-scope read). It becomes the network owner's decision at step 9 (listing admission). The invitation still locks the service name, ODS code and mobile (`ui-screens.md:2897`).

**Step 2. The applicant opens the link and verifies the phone.** `/register?invite=<token>`, text code, session role `reporter` (`W23.md`).
- Records: the code hash in Redis; the session. A `text-code` audit entry (purpose and outcome only, `U25.md:58`).
- Tenant: from the invitation token (section 3.2). The code is sent from the tenant's number.
- Rate limits and code keys are per tenant and per tenant-keyed phone hash.

**Step 3. Draft.** `RegistrationDraftField` rows and the Task (DEC-080). Tenant owned. The ODS code and service name are locked from the invitation. The reporter's mobile or email goes only to `ProtectedContact` (`U26.md:57`). Uniqueness of the ODS code is per tenant (migration 0002 change).

**Step 4. Submit and persist as one FHIR transaction (`U27`).** Records: `Organization`, `Location`, `HealthcareService` (all inactive) and the first `ServiceCriteria` (`pending-approval`). Reused district `Location`s (`U27.md` test 2) become per tenant. The bundle writer resolves `urn:uuid:` references only inside the bundle, and refuses any other id that is not in the tenant (section 3.4). The OS Places call carries only a site postcode (`I12.md`); the key and the quota are platform level, so record usage per tenant.

**Step 5. Review (`U28`).** The tenant's `lead` runs the automatic checks, the call-back (to the register number, `U28.md:55`) and records Provenance.
- Configuration used: `areaDistrictPrefixes` and `acceptedOwnerEmailDomains` from the tenant's settings (section 6). The ODS lookup is shared read-only reference data.
- The "scope" check (`checkScope`, DEC-081 item 3) no longer comes from the same person. It is the network owner's listing decision (step 8), delivered back to the tenant as an event (`ListingDecided`) that a tenant-bound consumer records on the registration. If the tenant is not in a network, the tenant lead decides scope.

**Step 6. Criteria second approval (`U30`).** Within the tenant, the owner and a `clinical-lead` role in the same tenant (two distinct people, DEC-032; `U30.md`). A second tenant's clinical lead cannot approve it because they cannot see it. The network owner's clinical lead performs a separate **endorsement** of the projected version (section 4.9, gap G3).

**Step 7. Approve and test prompt (`U29`).** Needs two distinct people, the requester and the approver (DEC-032, `U29.md` "Added after D22"; the owner has not confirmed whether a registration needs two people, DEC-062 left it open; keep two as the default). The I3 test prompt is sent from the tenant's number to the registered phone. The answer arrives on that number and is matched to the registered phone hash inside the tenant (`U29.md:57`).

**Step 8. Listing admission (new, network scope).** After the tenant approves, the service appears as a `listing request` in the network scope (a projection of the directory scope). The network owner's `network-admin` or `lead` runs the network-side checks: call-back, scope decision (`in-pilot`, `later`, `out-of-scope`, with reason), criteria endorsement. The decision is a network-scope record `ListingDecision`. The tenant receives `ListingDecided`. Until a listing is approved the service is not shown on the network view (and a board that mixes unapproved services would repeat F26, "fake service").

**Step 9. Go live (`U29`).** The tenant's `lead` sets the service live (needs `approved`, a test answer and, if in a network, an approved listing). Effects in the tenant: `active=true`, new resource versions, first `prompt-due` `ScheduledWork` and its `ScheduleWork` outbox message, `RegistrationApproved`. Effects in the network: the projector starts the directory, criteria and capacity projections for this service.

**Step 10. Links between services, reporters, locations and districts.** `PractitionerRole` (`PRACTITIONER`, `HEALTHCARE_SERVICE`, `ORGANIZATION`), `HealthcareService` (`LOCATION`, `COVERAGE_AREA`, `CURRENT_CRITERIA`), `Location` districts. All within one tenant. Check: section 3.4.

**Step 11. Reporter set-up: channel, home screen, notifications, PIN, device (`W33`, `W34`, `U32`).**
- Records: `Credential` and `Device` (per practitioner and device), `PushSubscription`, a `Consent` or `Basic` (`I14.md:58`).
- Device ids are random and minted per tenant enrolment, so one physical phone running two tenants' apps has two device ids; `Device.id` and `Credential.deviceId` stay globally unique (DEC-071 item 4, DEC-074 item 2).
- The PIN is stored per tenant person and device with the tenant's `pin-hmac` key.

**Step 12. First prompt (`U03`, `U04`).** Records: `Communication` per reporter role, `LinkToken` purpose `capacity-prompt`, outbox `SendMessage` (tenant property), the ladder `ScheduledWork` rows, the next `prompt-due`. Sent from the tenant's number, with the tenant's `senderLabel`. Grouped prompts (`U04`) only group services within the tenant: `services_for_phone_hash` is tenant bound, so a phone that reports in two tenants gets two texts from two numbers, never one grouped text.

**Step 13. Reply by text (`I07`, `I08`, `U05`).** Section 3.2: tenant from `To` and `AccountSid`; the reply is applied only inside that tenant. Booking references are unique per tenant (DEC-131 item 3).

**Step 14. Reply by link (`L01`).** The token gives the tenant. `ReportCapacity` or `ConfirmCapacity` runs bound to it; the audit entry goes to the tenant's chain.

**Step 15. Reply by app (`R11`, `R04`).** The session's tenant claim; the `services` claim is validated inside the tenant (`R02.md:62`, with `lead` limited to its own tenant).

**Step 16. Status, projection and board.** The report creates the Observation and the `CapacityReported` event in the tenant. The tenant's own board recomputes (cache key per tenant). The projector writes the minimum capacity copy into the network scope and the network view refreshes (section 4.7). The status rules run with the tenant's configuration version; the audit entry records the version.

**Step 17. Missed reports.** `domain-rules.md:54-71`: reminder at +30, phone task at +60, escalate to the shift lead at +90. The reminder is the tenant's own. The phone task for advisors and the escalation to the SPOA shift lead are the network owner's staff, so they are driven by the projected overdue state in the network scope (gap G4).

**Step 18. Bookings.** Crosses legal entities and is not in DEC-132's scopes (gap G1).

**Step 19. Wall screen pairing (`U10`, `R15`, `W08`).** Section 3.2 and 4.7.

**Step 20. Suspend, resume, remove a person, lost phone (`U36`, `U37`).** In the tenant. The network owner cannot suspend a member's service in the member's tenant. It can suspend the listing in the network scope (gap G4).

---

## 4. Users, roles and the network (final design under DEC-132)

DEC-132 chose: tenant = legal entity; one Network owned by a lead tenant; sharing only by Grants and read-only projections into a network scope; no query spans scopes. This section is the design that follows from it. The four alternatives I analysed earlier (a network as the tenant, grants with projections, a hierarchy, a shared graph with per-field rules) are not repeated; the owner has chosen. Two consequences of the choice are worth stating because they drive the work: the number of tenants equals the number of organisations (so a Twilio subaccount and number per organisation, DEC-131), and every screen that shows more than one organisation's capacity becomes a read of the network scope (section 4.7).

### 4.1 Roles: how each is tied to a tenant

The ten members of `Role` are in `contracts.md:79` and `domain-rules.md:255`. A role always means "this role in this tenant" (or, where stated, in the network scope or the platform).

| Role | Identity source | Tied to | Notes under tenancy |
|---|---|---|---|
| `reporter` | Mobile, text code, PIN (`domain-rules.md:248-250`) | One tenant, through a `Practitioner` and one or more `PractitionerRole`s in it | The app is installed per tenant. `services` claim lists service ids in that tenant. Never sees the network view (DEC-132 item 5) |
| `advisor` | Entra (`domain-rules.md:247`) | One tenant (the network owner in practice, section 4.9 G6) | Cases and bookings live in that tenant. Reads the network view for options |
| `clinical` | Entra | One tenant | Presence and queue per tenant (`U40.md`) |
| `lead` | Entra | One tenant | Operational administration of that tenant only. `R02.md:62` ("a lead anywhere") becomes "anywhere in the bound tenant" |
| `owner` (criteria owner) | A `PractitionerRole criteria-owner` in the tenant (`P03.md`) | One tenant and one service | Entered by the provider; the person may be a reporter too |
| `exec` (COO or ICB) | Mobile, text code, PIN (`domain-rules.md:248`), invitation I2 | One tenant | Sees own tenant's board and the network view if the tenant is a member and the role may see the board. Alerts subscriptions are in the tenant (G5) |
| `wall` | Opaque device token after pairing | One tenant, set at pairing | Shows the tenant board or, if the tenant admin sets it, the network board (section 4.7) |
| `anonymous-link` | A link token | The token's tenant | No session; one action |
| `support` | Operator directory only | Platform, with a per-access tenant | Section 4.2 |
| `audit` | Entra | One tenant | Reads that tenant's audit. Network scope history is read by `audit` in the owner tenant for the network scope |
| `tenant-admin` (new) | Entra | One tenant | Section 2.2 |
| `network-admin` (new) | Entra | The owner tenant, with write rights limited to the network scope's membership, grant, agreement and listing records | Gains no read access to a member's private data (DEC-132 item 2) |
| `platform-admin` (new) | Operator directory | Platform | No tenant data |

### 4.2 Cross-tenant roles: the exact audited privilege model

DEC-130 item 8 and DEC-132 item 8: no role holds cross-tenant access yet. This is the model I propose for when it is needed. Every item is a separate explicit grant, never a default.

1. **Where the role comes from.** `platform-admin` and `platform-support` exist only in the operator's own Entra directory. The BFF refuses them unless `tid` equals the operator's tid, and mints a token with `aud=ops`. A customer directory cannot create them. This fixes `W09.md:48`, which maps `DIUCS.Support` from whatever directory signs in.
2. **No standing data access.** `platform-admin` manages tenant records. It cannot read capacity, people, communications or audit of any tenant. `platform-support` has no access until one is opened.
3. **A national or regional viewer is not a role.** DEC-132 gives a regional viewer nothing live. If one is wanted, it is a member of a network (or a future aggregate recipient, section 7), not a cross-tenant user.
4. **Support access** (extends O06, `O06.md:54`). A `SupportAccess` is created for exactly one tenant. It needs either a support code the person shared (the person is in that tenant) or a ticket **approved by that tenant's `lead`**, not by an operator `lead` (`O06.md:54` says "a lead's approval"; with tenants that must name whose lead). It lasts one hour [ASSUMED, `O06.md:55`]. It allows reading one session's timeline and traces (events carry element ids, outcomes and timings only, `R18.md:55`), not the graph. Every call made under it carries `accessId` and the tenant, and is written to the tenant's chain and the platform chain. The tenant admin's "operator access log" screen lists each open with the role, never a name (`observability.md:149`).
5. **Break-glass.** None in the application. Direct database access is the real super-privilege: Neo4j Community has one database and no role-based access (`migrations.py:6-10`, `contracts.md:45`), so anyone with database credentials can read every scope. That is a processor-level control (privileged access management, logging, named people) for IG to accept, and an argument for deciding early whether any tenant needs a dedicated instance (section 9, question O2).
6. **Token freshness.** Tokens carry the tenant and the tenant `epoch`; the API compares the epoch on each request (small cached read), so suspending a tenant or changing a role mapping takes effect within the cache time, not at `exp`.

### 4.3 A person who works for two tenants

**Data model: one `Practitioner` per tenant, never shared, never linked by an edge.** There is no cross-tenant relationship and no shared person node. What links the two records is only an opaque property the person's identity provides:

- Staff: `accountRef` on the `Practitioner` = HMAC over `tid` and `oid` with a platform key. "My tenants" is computed by taking the candidate tenants from `TenantRoleMapping` (platform scope) and, for each, running a tenant-bound lookup for that `accountRef`. That is a loop of single-scope queries, not a join.
- Reporters: nothing links them. The mobile hash is per tenant (`hashKeyVersion = 1`), so two hashes of one number are unlinkable by design.

| Case | What it means | Design |
|---|---|---|
| A clinician in two organisations | Two `Practitioner`s, two role sets | One session holds one tenant. Switching creates a second session; the old tenant's presence is set to away. Presence is per tenant (`U40.md`), so the clinician is not "available" in both by default. Taking a request in tenant A does not lock them in tenant B (no cross-scope state). Residual: double-booking by a clinician active in two tenants; recommend "go on duty for one tenant at a time" (hazard H-T28) |
| An advisor covering two SPAs | Same | Same. Two tabs are safe because the tenant is in the URL (`/t/<slug>/advisor`) and the cookie is per slug (section 3.3 item 19) |
| An exec user for two organisations | Same | Same; a deputy in the alert ladder is a person in the same tenant (`U33.md`: "another practitioner with role exec or lead") |
| A reporter on one phone for two tenants | Two `Practitioner`s, two apps, two numbers texting them | Section 5 |
| Cover across tenants | Not possible | `COVERED_BY` is within a tenant; a cover person who works in two tenants is two people |
| Lost phone | Handled per tenant | A lost phone must be reported in each tenant, because there is no cross-tenant join. Document it in the Help text and the tenant admin runbook (hazard H-T26) |

DEC-130 item 6 says "staff sign-in maps a user to exactly one tenant". I recommend amending it to: each session is bound to exactly one tenant; a user may hold one session per tenant.

### 4.4 The network: creation and the owner organisation

Records, in the **network scope** (`tenantId` = the network's scope id). A registry node `ScopeRegistry {scopeId, kind: 'network', ownerTenantId, status}` in the platform scope is how a scope id is resolved to a kind.

**`(:Network)`**: `scopeId`, `name`, `displayName`, `systemName` (the board title, today "Dorset urgent care capacity", `ui-screens.md:657`), `pathwayName` (today "Dorset", `ui-screens.md:2743`), `ownerTenantId`, `status` (`draft`, `active`, `suspended`, `closed`), `timeZone`, `currentAgreementVersion`, `projectionAllowlistVersion`, `currentConfigVersion`, `createdAt`, `closedAt`.

**`(:NetworkAgreement)`**: `reference` (an id in IG's document system; the content is never stored, DEC-132 item 2), `version`, `effectiveFrom`, `effectiveTo`, `status` (`draft`, `current`, `superseded`), `recordedByAccountRef`, `approvedAt`.

Creation, in order:
1. `platform-admin` creates the network node and its audit chain (genesis `sha256("diucs-genesis:" + scopeId)`) and names the owner tenant, which must be `active`.
2. The owner's `tenant-admin` accepts ownership. The agreement reference and version 1 are recorded by the owner's `network-admin`.
3. The network becomes `active`. The owner is the first `NetworkMembership` (`role = owner`, joined at creation, same agreement version).
4. Network configuration version 1 is approved by `network-admin` plus a second person (section 4.10).

The owner is a tenant like any other; being the owner adds administration rights over membership and the agreement, and nothing else. It cannot leave while it is the owner. Ownership transfer needs the old and new owner's admins, the operator, and an agreement version, and leaves the network scope's data in place.

### 4.5 Members: adding and removing

**`(:NetworkMembership)`**: `tenantScopeId`, `role` (`owner`, `member`), `status` (`invited`, `active`, `leaving`, `suspended`, `left`, `removed`), `invitedAt`, `joinedAt`, `leavingFrom`, `leftAt`, `leaveReason` (code), `acceptedAgreementVersion`, `acceptedByAccountRef`, `acceptedAt`. One active membership per tenant while the owner's answer "there is one network" holds (a unique constraint `(tenantId, tenantScopeId)` on active rows is application enforced).

**Adding a member**
1. The network owner's `network-admin` records an onboarding request (legal name, ODS code, work email). The operator creates the tenant (section 2.4) and invites its first admin.
2. The tenant must be `active`. The `network-admin` creates a membership in `invited`, naming the agreement version.
3. The member's `tenant-admin` accepts. The record stores the version, the account reference and the time. That is the system's evidence that the person asserted authority; whether they have authority is a human check (section 8).
4. The membership becomes `active`. Nothing is shared yet. Sharing starts only when grants are active (section 4.6). A member with no active grant is a member who sees the network view but contributes nothing.

**Leaving or being removed**
- Member leaves: the member's `tenant-admin` gives notice (default 30 days [ASSUMED], set by the agreement) or ends sharing at once for a security reason. Status `leaving`, then `left` at `leftAt`.
- Owner removes: `network-admin` records a reason code (breach of agreement, ceased service, other) and a second `network-admin` approves. Status `removed`.
- Automatic: tenant `suspended` makes the membership `suspended`; tenant `offboarding` ends it.
- Effects, all at the transition: every grant of that tenant becomes `lapsed`; the projector stops for it; its network records are marked `memberLeftAt` and `listingStatus = withdrawn`; the live view excludes it; wall screens set to the network view show their tenant board with a banner; the member's own data is untouched.
- **History stays** (DEC-132 items 6 and owner answer 4). Nothing in the network scope is deleted on leaving. The network's retention for these classes is a network setting set by IG. Projected records are organisational (service names, figures, contacts of a service). Because the directory carries a service-level contact, that contact must be a role or switchboard number, not a named person's mobile; the privacy guard enforces the shape, and the registration form says so.
- A tenant that rejoins gets a new membership row and new grants. A closed membership is never reopened.

### 4.6 Grants: creation and ending

**`(:Grant)`** in the network scope, one authoritative record: `id`, `version`, `grantorTenantId`, `scope` (`capacity`, `directory`, `criteria`), `purpose` (`network-capacity-view`), `agreementVersion`, `allowlistVersion`, `status` (`draft`, `pending`, `active`, `ended`, `superseded`, `lapsed`), `effectiveFrom`, `effectiveTo`, `approvedByGrantorAccountRef`, `approvedByGrantorAt`, `approvedByOwnerAccountRef`, `approvedByOwnerAt`, `endedByAccountRef`, `endedAt`, `endReason` (code), `supersedesId`. The grantor's tenant keeps an audit mirror (`GrantEvent`: `grantId`, `event`, `at`, `byRole`) written through the outbox, so the controller has its own record. The authoritative status is the network copy because the projection write has to check it in the same scope it writes to.

- **Create.** The grantor's `tenant-admin` drafts a grant for one scope and one purpose, naming the agreement version and the allowlist version. A grant cannot name a scope or purpose other than the three scopes and one purpose DEC-132 lists; adding one is a new decision (item 7).
- **Approve.** Two approvals are recorded: the grantor's administrator and the network owner's `network-admin` (DEC-132 item 3). They are different accounts in different organisations, so DEC-032's "approver differs from requester" holds by construction; where the drafter and the grantor-side approver are one person, that is allowed and the operator is notified.
- **Active** at `effectiveFrom`, when both approvals exist, the membership is `active` and the agreement version is the network's current one (or the member has accepted it).
- **Change.** Any change (scope, purpose, allowlist version, agreement version) is a new grant version that supersedes the old one at its `effectiveFrom`, without a gap or an overlap. Widening the allowlist needs the new version of the agreement.
- **End.** The grantor's `tenant-admin` alone can end a grant at any time, with a reason code. It takes effect at the commit. It stops future sharing only (DEC-132 item 3). The network owner cannot end a member's grant on its own; it can remove the member (section 4.5), which lapses the grants. A grant also ends at `effectiveTo`; the projection write checks `effectiveTo > now` itself and does not rely on a scheduled job.
- **A revoked grant must stop projecting.** The projection write statement matches an `active` grant in the same query and takes the grant's lock first (`SET g.id = g.id`, the lock-first rule of lesson L73 used in DEC-083 item 1), so an end and a projection write serialise and a projection after the end commits is a no-op. The grantor's end action writes the network copy directly (the use case binds the network scope; the permission check is `actor.tenant == grant.grantorTenantId`). Test: section 8, H-N05.

### 4.7 Projections and the read path

**The projector** is a worker. For each active grant it does two units of work in sequence and never one that spans both: (1) bound to the grantor's tenant, read the changed source data and build an allowlisted DTO; (2) bound to the network scope, upsert the copy through a named query that also matches the active grant. It is triggered by the tenant's outbox events (`CapacityReported`, `StatusChanged`, `ServiceActivated`, `CriteriaApproved`, a profile change), by time boundaries (below) and by a periodic heartbeat.

**What is copied, as typed nodes in the network scope** (properties and shapes only; everything not listed is not copied):

| Node | Properties | Notes |
|---|---|---|
| `NetworkService` | `id` (`ns:<sourceTenantId>:<sourceServiceId>`), `sourceTenantId`, `sourceServiceId`, `sourceVersion`, `name`, `category`, `active`, `locationName`, `latitude`, `longitude`, `coverageDistricts[]`, `referralMethods[]`, `serviceContactLabel`, `serviceContactPhone`, `source` (`manual`, later `dos`), `listingStatus`, `memberLeftAt`, `grantId`, `allowlistVersion`, `projectedAt` | Child `NetworkAvailableTime {days[], allDay, start, end}` nodes. The directory `source` property is DEC-132 item 7 |
| `NetworkCapacity` (append-only series, one node per report, plus a `CURRENT` pointer) | `sourceTenantId`, `sourceServiceId`, `sourceVersion`, `measure`, `unitLabel`, `established`, `canExceedEstablished`, `usualMin`, `usualMax`, `limitedLevelPercent`, `cadence`, `value`, `reportType`, `reportedAt`, `status`, `effectiveAvailable`, `used`, `overBy`, `overdue`, `wasDueAt`, `nextDueAt`, `validUntil`, `configVersion`, `projectedAt`, `heartbeatAt` | Source time is `reportedAt`. Data age is always computed from it, never from `projectedAt` |
| `NetworkCriteria` | `sourceTenantId`, `sourceServiceId`, `sourceVersion`, `version`, `status`, `ageMin`, `ageMax`, `districts[]`, `reviewBy`, `ownerRoleLabel`, `endorsement` (`none`, `endorsed`, `rejected`); `ACCEPTS_NEED` and `EXCLUDES_NEED` to shared `Concept`s | An advisor sees only an `endorsed` current version (G3) |
| `ProjectionHealth` | `sourceTenantId`, `lastProjectedAt`, `lastHeartbeatAt`, `lagSeconds`, `status` | Per member |

Never copied (DEC-132 item 4): reporters' names, phones, devices, PINs, link tokens, communications, bookings, cases, audit entries. Also never copied: free-text fields other than the service name, comment and contact label, and those pass the privacy guard (D17) and a length limit.

**How the allowlist is enforced** (DEC-132 item 7): projections are built from explicit typed DTOs, never by copying node properties. The allowlist is a versioned registry in code; each grant names its version. Tests: the set of property names on every network-scope label equals the allowlist exactly (a new property fails the build); the guard `find_patient_data` runs on every string; a scan of a seeded network scope finds no phone, postcode or name shape; no relationship leaves a network node into a tenant scope.

**Staleness (a stale projection must never read as live).**
- The tenant computes status with its own configuration and puts `validUntil` on each projection: the next instant at which the status could change (reply-by passing, opening, closing, an old-data limit). A tenant-side scheduled job emits a new projection at each boundary (the same `ScheduledWork` mechanism, `U03.md`).
- A heartbeat: every `heartbeatSeconds` [ASSUMED 30] the projector refreshes `heartbeatAt` per member, even with no change.
- The read use case degrades, in this order: `now > validUntil` and no newer projection means status `not-updated` (phone to confirm); `now - heartbeatAt > staleAfterSeconds` [ASSUMED 120] means "Last known" for that member's services; a projector-wide failure gives the board's existing "tool offline" state (`ui-screens.md:745`). Never the old figure as current (H-01, H-13, H-27 already say this for the single-tenant board).
- The board and options show `reportedAt`-based data age.

**The read path.** `QueryNetworkBoard` (and the network versions of the options and criteria reads, `U08`, `U12`, `G11`) is bound to the network scope and, in this order: the actor's session is active; the actor's tenant has an `active` membership in this network; the actor's role may see the board (`R05.md` role list); then it returns entries whose member has an active membership, an active grant for the scope, an approved listing, and a fresh projection. The same read serves the board, the advisor list and the exec home. Use cases that also write (open a case, snapshot what was shown) do the network read in one unit of work and the tenant write in another; the snapshot records the network service key, `sourceTenantId`, `reportedAt` and the criteria version shown, which keeps H-19 intact.

**Caches and streams.** Network board cache `diucs:n:<networkScopeId>:board`; network live channel `diucs:n:<networkScopeId>:chan:board.updates`. The stream subscribes to the network channel only after the membership check, and carries service keys and times only (`R06.md:54`).

**Wall screen.** A screen is paired to one tenant (section 3.2). The tenant's `tenant-admin` sets `displayMode` to `tenant` or `network` and, for `network`, `displayNetworkId` from networks the tenant is an active member of. On every request the backend resolves the device, then re-checks membership. The screen header always shows the network name and "Network view" when it is a network board, and the tenant name otherwise. If membership ends, the screen falls back to the tenant board with a banner "No longer showing <network>", not a blank or stale network board (H-N04).

### 4.8 The agreement reference, versions and roles in law

- A `NetworkAgreement` holds the reference and version only. Each membership records the version accepted; each grant records the version it was approved under.
- A new agreement version does not silently change what is shared. Grants stay as approved. The membership shows "agreement version N available" until the member's admin accepts it. Widening needs new grant versions.
- Proposed roles for IG and the data protection officers to decide (human-only, DEC-132 item 9; this is not legal advice): the platform operator is a processor for each tenant and for the network scope; each tenant is controller for its own scope; the network owner is controller, or the members and owner are joint controllers, for the network scope's contents. The agreement between tenants is the data sharing agreement. Controllers' withdrawal rights are met by ending a grant (stops sharing) and leaving (stops membership); erasure of already-projected organisational records is governed by the agreement's retention clause.

### 4.9 What crosses legal entities today, and what DEC-132 leaves open

| # | Data | Today crosses entities? | In DEC-132's scopes? | Patient-level? |
|---|---|---|---|---|
| 1 | Capacity reports and figures (`domain-rules.md:91-134`, `fhir-data-model.md:150-165`) | Yes, provider to everyone | Yes (`capacity`) | No |
| 2 | Derived status, pressure, due times, data age (`domain-rules.md:27-87`) | Yes, shown on every board | Yes (in `NetworkCapacity`) | No |
| 3 | Service directory: organisation, site, position, hours, coverage, referral method, service phone (`fhir-data-model.md:85-131`) | Yes | Yes (`directory`) | No (organisational) |
| 4 | Criteria, versions, owner role, review-by (`domain-rules.md:177-199`) | Yes | Yes (`criteria`) | No |
| 5 | Registration records, call-back, scope decision, approvals (`domain-rules.md:213-241`) | Yes today: the SPOA approves the provider | No (gap G2, G3) | No (staff and organisation data) |
| 6 | Booking requests and answers: reference, service, age band, need, urgency, reply-by, reasons (`domain-rules.md:138-165`; `fhir-data-model.md:229-240`) | Yes, SPOA to service | **No (gap G1)** | Indirect: age band, need, urgency and time. No name, NHS number or postcode (`domain-rules.md:277`) |
| 7 | Cases: stub, postcode until close, needs, scores, criteria seen, outcome, destination (`domain-rules.md:169-175`) | No: advisors and clinical staff only | Not shared | Yes, pseudonymous |
| 8 | Clinical advice requests and advice (`domain-rules.md:203-209`) | Within the SPOA; the clinical pool may be another organisation's staff (G6) | Not shared | Yes |
| 9 | Audit snapshots of what the advisor saw (`fhir-data-model.md:272-279`) | Owner tenant only | Not shared | Case-linked |
| 10 | Contacts: reporter phones and emails, role-holder names, owner emails, register numbers, cover numbers (`fhir-data-model.md:142-149`) | Yes today: the SPOA lead edits them (`U15`, `U16`, `U38`) | Not shared; only the service-level contact | Staff personal data, not patient |
| 11 | Suspension and service flags on a provider's service by the SPOA (`U36`) | Yes | No (G4) | No |
| 12 | Missed-report ladder: phone task, escalation to the SPOA lead (`domain-rules.md:54-65`) | Yes | No (G4) | No |
| 13 | Advisor-phoned positions (`domain-rules.md:117,126`; `U13`) | Yes, advisor writes a figure for a provider's service | No (G4b) | No |
| 14 | Alert subscriptions and escalation across organisations (`domain-rules.md:259-271`) | Yes | No (G5) | Staff only |
| 15 | Communication delivery records (`architecture.md:200`) | Yes, the lead reads them | Not shared | No |
| 16 | Week summary, planning (`U35`, `U43`; `ui-screens.md:3644-3659`, `3755-3850`) | Yes, aggregates across providers | No (G6) | Derived from case data, groups of fewer than 10 hidden (`domain-rules.md:329`) |
| 17 | Telemetry and support sessions (`observability.md`) | Staff of all organisations, processed by the operator | Not shared between tenants | Staff pseudonymous |
| 18 | Safety concerns (`U41`) | To a clinical safety officer | Not shared | Free text in the protected store |

Patient-level data in the platform today: rows 7, 8, 9, and, indirectly, 6 and 16. Under DEC-132, rows 7 to 9 never leave the owner tenant, so the only place patient-level data would cross entities is row 6.

**Gaps DEC-132 does not close.** Each is a design decision the owner should make before the tasks that touch it are built. My proposed default follows each.

- **G1. Bookings.** The advisor's request text, the reply by text or link and the pending count cross entities (`U17` to `U22`, `L02`, `W19` to `W22`, `W36`, `ui-screens.md:1069-1277`). They are not in the three scopes, and item 7 says patient-level coordination needs its own decision. *Default:* the owner tenant sends the request from its own number to a **booking contact** that the provider publishes in the directory as an organisational mobile; the reply arrives on the owner's number and is resolved in the owner tenant; the link page is served from the owner tenant's token. No data path between tenant scopes, no new grant scope. Cost: the provider's reporter app, email and push channels do not carry bookings; and the provider's staff receive a text about a patient need from a number that is not their usual tenant number (a shared-phone effect, section 5). This needs IG to confirm that disclosing age band, need and urgency to a published booking contact is covered by the agreement. Alternative: a new grant scope `booking` with its own purpose and IG and clinical sign-off. Alternative: drop B1 to B7 outside the owner tenant and use "I phoned" only.
- **G2. Registration, the scope list and invitations.** *Default:* section 3.5 steps 1 to 9. The provider registers in its own tenant; the network owner admits or declines the listing (a record in the network scope) and records the scope decision; the decision returns to the tenant as an event.
- **G3. Criteria second approval.** The rule book says a clinical lead is the second approver (`domain-rules.md:197`, `ui-screens.md:2782`). Only the provider's own people can see the draft. *Default:* the provider's `clinical-lead` is the second approver (DEC-032 unchanged); the network owner's clinical lead then **endorses** the projected version; advisors see only an endorsed `current` version, and the previous endorsed version stays until then. That keeps the two-approval safety control (H-07, H-08) and adds a network gate.
- **G4. Chasing, suspension, reporter numbers, advisor-phoned positions.** The SPOA lead cannot write into a member's tenant. *Default:* the provider's own lead changes the provider's reporter numbers and suspends its own service; the network owner can suspend the **listing** (the service then reads "Not updated, phone to confirm" and leaves the options). The missed-report ladder runs in the provider (reminder at +30); the phone task and the escalation to the SPOA lead come from the projected overdue state in the network scope. **G4b:** an advisor-phoned figure is written by the owner's staff into the network scope as a `PhonedPosition` (source `advisor-phoned`), and the network read takes the latest of the provider's projection and the phoned position. That is a record type DEC-132 does not list, so it needs the owner's confirmation.
- **G5. Alerts.** *Default:* the network scope emits status and pressure change events; each member tenant's evaluator consumes them bound to its own tenant, matches its own subscriptions and sends from its own number or push; escalation to the SPOA lead is an event the owner tenant's evaluator picks up. Subscriptions and staff data stay in the tenant.
- **G6. Week summary, planning and the clinical pool.** *Default:* the owner tenant's week summary uses its own cases and bookings; the capacity measures (on-time updates, status counts) are computed in the network scope from the append-only `NetworkCapacity` series; groups under 10 hidden. A per-member breakdown is not shown to other members unless the agreement says so. Clinical advisors and call handlers from other organisations are given accounts in the owner tenant (a person in two tenants, section 4.3).

### 4.10 Configuration fields: tenant and network

**Tenant fields** are in section 2.3 (record) and section 6 (settings, with the scope that owns each: `tenant`, `network`, or `platform`).

**Network record and settings** (versioned in the same way as tenant configuration; a `NetworkConfigVersion` and `NetworkSetting` rows; changes in the `clinical` class need a second approver):

| Field | Type | Default | Used by |
|---|---|---|---|
| `name`, `displayName` | text | none | Headers, messages from the network owner |
| `systemName` | text | none (replaces "Dorset urgent care capacity") | Wall header (`W05.md:51`), exec home (`W40.md:49`), I2 text (`D16.md:59`) |
| `pathwayName` | text | none (replaces "Dorset") | Scope questions (`U28.md:56`), "Address found, in <name>" (`ui-screens.md:2697`), "Outside <name>" (`ui-screens.md:3903`) |
| `timeZone` | IANA | `Europe/London` | Network board and summaries |
| `ownerTenantId` | scope id | required | Membership administration |
| `currentAgreementVersion`, `projectionAllowlistVersion` | integer | required | Grants |
| `pressureWatchFrom`, `pressureHighFrom` | integer | 3 and 5 [ASSUMED] (`domain-rules.md:83-85`) | System pressure across the network. Absolute counts only fit a network of about nine services; revisit when it grows |
| `heartbeatSeconds`, `staleAfterSeconds` | integer | 30 and 120 [ASSUMED] | Staleness (section 4.7) |
| `boardCacheSeconds` | integer | 60 [ASSUMED] (`U09.md:52`) | Network board cache |
| `defaultWallMode` | code | `tenant` | New screens |
| `areaDistrictPrefixes` | list of text | required, no default | Listing admission "address in area" |
| `pilotCategories` | list of codes | required | Listing admission scope question |
| `listingEndorsementRequired` | boolean | true | G3 |
| `retention.*` | days and action per class | unset; blocks activation | Network scope history |
| `minGroupSize` | integer | 10 (floor 10, `domain-rules.md:329`) | Summaries |

### 4.11 Network hazards (hazard-log rows are in section 8)

The five you named, each with its control, are H-N01 to H-N05. Others found while designing the read path: out-of-order projection overwrites a newer one (H-N06), a suspended or inactive service still shown as accepting (H-N07), a left member still visible live (H-N08), a member's agreement version out of date (H-N09), unendorsed criteria used by advisors (H-N10), the owner reading private data by being the owner (H-N11), two members listing one real service (H-N12), scope-kind confusion (H-N13), the projector bound to the wrong scope (H-N14), and a time zone or label shown wrongly on the network board (H-N15).

---

## 5. The shared phone problem (rewritten after DEC-131 and DEC-132)

A mobile number can belong to a reporter in two tenants. Settled: it is two separate `Practitioner` records, one per tenant, with different per-tenant phone hashes (DEC-131 item 3; section 4.3). Settled for SMS: the reply is resolved by the number it was sent to, so the shared phone is solved at the channel. What is left is everything that is not an inbound SMS.

### 5.1 Walk-through and resolution

| Mechanism | What can go wrong on a shared phone | Resolution | Failure mode that remains |
|---|---|---|---|
| **Inbound SMS reply** (`I07`, `U05`) | Settled. `To` + `AccountSid` give the tenant; the sender's hash is looked up only there; idempotency, queue message and `HandleInboundText` are bound to it | DEC-131 item 2 | The person replies on the wrong thread. Tenant A's prompt is answered "4" on tenant B's number; B may also have an open prompt for them, so "4" is applied to B's service. Controls: every text names the service and the tenant's `senderLabel` ("DIUCS Dorset: UCR West ..."); the echo names the service (`domain-rules.md:283`); a figure outside the usual range is asked again (`domain-rules.md:117`); lettered replies. Residual hazard H-T08 |
| **Number reuse and retirement** | A tenant's number is retired, then given to another tenant; old reporters' replies land in the new tenant | Retired numbers are quarantined 90 days [ASSUMED] (`TenantNumber.quarantineUntil`), never reassigned to another tenant inside it. Unknown number answers with the fixed empty reply | H-T13 |
| **Delivery receipt** (`I08`) | A receipt matched to the wrong message | Matched by `AccountSid` and provider message id inside the tenant | None expected |
| **Link opening** (`L01`) | Settled by the token: `tokenHash` is globally unique, the record gives the tenant. The link is tied to one prompt and one phone (`domain-rules.md:251`) | Section 3.2. The page header shows tenant name and service. Opening still changes nothing; a POST needs the per-tenant CSRF value (`L01.md:55`) | A forwarded link works for whoever holds it, exactly as in the single-tenant design |
| **Booking text** (G1 default) | The provider's contact gets a booking text from the owner tenant's number, a second sender they may not expect | The text says who is asking ("DIUCS REQUEST 4821: <service>") and the reply words are the same. The reply is resolved by the owner's number; the owner tenant matches the reference inside its own tenant | H-T08 for bookings: "CONFIRMED" sent to the capacity number instead of the booking number reaches the provider tenant, which has no open booking and answers "unrecognised" (C11), so the booking silently expires at 10 minutes (`domain-rules.md:159`) and the advisor is prompted to phone at 5. Safe by design ("silence is never acceptance"), but it costs a phone call |
| **Text code** (`U25`, `R11`) | A code request for a number registered in two tenants | The app is per tenant (`/t/<slug>/app`) and registration comes through an invitation token, so the tenant is known first. The code is hashed with the tenant's key, stored under the tenant's Redis prefix and texted from the tenant's number (DEC-131 item 5). Rate limits are per tenant and phone. An unknown number still gets the identical response | A person with a number in many tenants receives codes from several numbers. Fine. SMS pumping cost is limited by the subaccount spend caps |
| **PIN** (`U32`) | One PIN for two tenants | None shared. A `Credential` per tenant person and device (`pin-hmac` per tenant). A PIN set in A does not open B (`U32.md:55`) | Two PINs to remember. Accept, document in the set-up screen |
| **Device credentials** | One phone, two installs, one `Credential.deviceId` unique globally (DEC-074) | A device id is minted per tenant enrolment, so each install has its own id and credential | A person who signs out of everywhere in tenant A stays signed in to tenant B (H-T26) |
| **Push** (`I14`) | One browser subscription cannot serve two tenants' notices without the tenant being clear | One installed app per tenant: the manifest `id`, `start_url` and `scope` include `/t/<slug>/`, so the subscription belongs to one tenant. Per-tenant VAPID key pair (secret reference on the tenant) so the platform cannot send tenant B's notice through tenant A's subscription. The notification title carries the tenant's `senderLabel`; tapping opens that tenant's app. Per-tenant consent record | Needs checking on iOS: whether two installs of one origin with different `scope` and `id` are separate home-screen apps and keep separate subscriptions. Mark as a verification item for W32 |
| **Wall pairing code** (`U10`, `R15`) | Six digits, global lookup, unauthenticated start; two screens in two tenants can show the same code at once, or a lead types the code of a screen that is not theirs | Open codes are unique across the platform (regenerate on a clash); the confirming lead's tenant is written to the record; a rate limit on the start call; the confirmation page names the tenant it will connect to; the paired screen shows the tenant name large for 10 seconds; the pairing record expires in 10 minutes (`domain-rules.md:253`) | A lead who is shown a code by a stranger. Same as today. H-T16 |
| **Wall device token** | A token that is valid for a different tenant after a re-pair | The opaque token resolves to the device, its tenant and its display mode on every request; re-pair issues a new token and revokes the old | None expected |
| **Invitation** (`U24`) | A person invited by two organisations to the same number | Two invitations, two tokens, two tenants, two `Practitioner`s | None |
| **Link token for a person in two tenants** | A token minted in A used against B | Impossible: the record holds the tenant; B's use cases never see it | None |
| **Cover** (`U16`) | A cover number that belongs to a person who also reports for another tenant | `COVERED_BY` is within a tenant, so the cover is a person in the same tenant. The same mobile in the other tenant is a different person | The cover person gets texts from two numbers |
| **Grouped prompts** (`U04`) | Two tenants' services due together on one phone | Never grouped across tenants (`services_for_phone_hash` is tenant bound). Two texts from two numbers at 10:00 | Prompt volume (F12, reporter fatigue). Counting "more than 3 services" (`domain-rules.md:134`) is per tenant |

### 5.2 Patient-safety hazards specific to the shared phone

- Wrong figure to the wrong service by replying on the wrong thread (H-T08). Residual after controls: low, detectable by the echo.
- A recycled number receives another tenant's prompts (H-T13). Controlled by quarantine and the fixed unknown-sender answer.
- A lost or stolen phone must be removed in each tenant separately (H-T26). The Help text and the lead's runbook must say so, and the tenant admin screen "Remove a person" (`ui-screens.md:3547-3563`) must show "this person may also have access in other organisations; tell them to report it there" without naming any other tenant.
- Allow-list mismatch after changing hashing (H-T25): a reporter whose hash was computed under the wrong key is treated as unknown, and "Messages from a number not on the allow-list get no reply at all" (`domain-rules.md:109`), so a silent failure looks like a reporter who stopped replying. Control: per-tenant alert on the dropped-reply rate.

### 5.3 What does not change

The ambiguous-phone rule (DEC-065 item 1: refuse when two active practitioners share one hash) stays but only inside a tenant. Two active people with the same hash in one tenant is still a data fault. Across tenants it is expected and is not a fault, and with per-tenant keys it cannot even be detected.

---

## 6. Domain rules and configuration per tenant (and per network)

Rule for the table: a value is **global** if changing it would make the product mean something different to a person who works in two tenants, or if it is a security or privacy floor; it is **tenant configuration** if the organisation runs the service and the value was marked [ASSUMED] or varies by service organisation; it is **network configuration** if it describes the shared view; it is **per service** if it already is (the profile). Safety class `clinical` means a change needs a second approver and is stamped on decisions (the configuration version goes into audit snapshots and the status interpretation, so a later reader knows which rule produced a figure). Field names use lower camel case as in section 2.3. Defaults are today's values. Bounds are my proposals for clinical safety and IG to confirm.

### 6.1 Rules and constants

| Rule book section (and code) | Rule or constant today | Recommendation | Field or note | Owner scope, class |
|---|---|---|---|---|
| 1.1 (`domain-rules.md:13-25`) | Service profile fields (measure, unit label, established, can-exceed, usual range, cadence, limited percent, available time, channel) | Already per service | Registration sets them | per service |
| 1.1 `limited_level_percent` 80 [ASSUMED] (`:23`) | Default at registration (`U27.md:57` sets 80) | Tenant default for new services | `defaultLimitedLevelPercent`, 50 to 95 | tenant, clinical |
| 1.2 status words (`:29`) | Accepting; Limited: phone to confirm; Not accepting; Over capacity; Not updated: treat as unknown, phone; Out of hours | **Global.** Same meaning for a person in two tenants; wording is IG and clinical approved | none | global |
| 1.3 status rule order (`:33-39`) | First match wins | **Global**, code and tested | none | global |
| 1.4 report schedule (`:45-52`, `schedule.py`) | Every 2 hrs from opening on even hours; twice a day at opening and 14:00 [ASSUMED]; once a day at opening | Alignment global; the second time per tenant | `twiceADaySecondTime`, default 14:00 | tenant, clinical |
| 1.4 reply-by +30 (`REPLY_WINDOW`, `contracts.md:87`) | 30 minutes | Tenant | `replyWindowMinutes`, 15 to 60, default 30. It also sets the link expiry and the overdue point | tenant, clinical |
| 1.5 ladder (`REMINDER_AFTER`, `PHONE_TASK_AFTER`, `ESCALATE_AFTER`; `domain-rules.md:54-65`) | +30, +60, +90 | Tenant, kept in order and not before the reply window | `reminderAfterMinutes` (30), `phoneTaskAfterMinutes` (60), `escalateAfterMinutes` (90) | tenant, clinical |
| 1.5 stale warning (`STALE_WARNING_AFTER`, `:69`) | 2 hours | Tenant | `staleWarningHours`, 1 to 4, default 2 | tenant, clinical |
| 1.5 overdue definition, data-age wording (`:67-71`) | Fixed wording | Global | none | global |
| 1.6 effective available and pending (`:73-77`) | Formula | Global | none | global |
| 1.7 system pressure (`:79-87`, `pressure.py`: `WATCH_FROM` 3, `HIGH_FROM` 5 [ASSUMED]) | Counts of services limited or worse | **Network** for the network board, tenant for the tenant board. Absolute counts do not scale with the number of services | `pressureWatchFrom`, `pressureHighFrom` (an optional percentage form is a later decision). The alert text "5 or more" (`ui-screens.md:3710`) must read from this | network and tenant, clinical |
| 1.7 wall banner "System under pressure" when every in-hours service is limited or worse (`:87`) | Rule | Global | none | global |
| 2.1 reply grammar (`:93-109`) | Y, 0 to 999, A 4, Y A, CONFIRMED, DECLINE, 1 to 3 | Global. No STOP, START or HELP handling in the product (`:109`). Check each Twilio number type for carrier-level opt-out handling, which the product does not control | none | global |
| 2.2 correction window (`CORRECTION_WINDOW`, `:115`) | 15 minutes [ASSUMED] | Tenant | `correctionWindowMinutes`, 5 to 30 | tenant, clinical |
| 2.2 confirm limit (`MAX_CONSECUTIVE_CONFIRMS`, `:116`) | 2 | Tenant (anti-reflex control, H-15) | `maxConsecutiveConfirms`, 1 to 3 | tenant, clinical |
| 2.2 range check, out-of-range twice (`:117`) | Rule | Global | none | global |
| 2.3 flags (`MANY_CHANGES_WINDOW` 5 min, `MANY_CHANGES_COUNT` 3, `PHONED_WINDOW` 60; `:125-126`) | [ASSUMED] | Tenant, with defaults | `manyChangesWindowMinutes`, `manyChangesCount`, `phonedWindowMinutes`. `differs-from-phoned` compares across scopes (G4b), so it runs in the network scope | tenant (network for the phoned comparison), clinical |
| 2.4 grouping (`GROUP_WINDOW` 10 [ASSUMED], DEC-050 item 1, DEC-062 item 1: "changing it needs a new decision") | 10 minutes | Tenant, by the same decision route | `groupWindowMinutes`, 5 to 20. `MAX_SERVICES_PER_PHONE` 3 -> `maxServicesPerPhoneWarn`, 2 to 6 | tenant, clinical |
| 3.1 booking states (`:140-154`) | State machine | Global | none | global |
| 3.2 booking windows (`BOOKING_REPLY_WINDOW` 10, `PHONE_PROMPT_AFTER` 5; `:159`) | 10 and 5 minutes | Whoever runs the booking (owner tenant, G1) | `bookingReplyWindowMinutes`, `bookingPhonePromptMinutes` | tenant, clinical |
| 3.2 booking reference (`:165`, DEC-041 item 6) | 4 digits, unique among open bookings | Format global; uniqueness per tenant (DEC-131 item 3) | none | global (format) |
| 3.2 withdrawal escalation 10 minutes (`:164`) | Rule | Tenant | `withdrawalEscalateMinutes` | tenant, clinical |
| 3.2 reason lists (`:163`) | Fixed lists | Global shared code systems | none | global |
| 4 case fields, urgency map, score ranges (`:171-175`) | Rules | Global. Case data clears at close (`:174`) | none | global |
| 4 retention of case audit (`ui-screens.md:1583`) | "Retention periods are for IG to set" | Tenant | `retention.case-audit` | tenant |
| 4.1 hard filter, age bands, overlap warning (`:177-191`) | Rules and wording | Global | none | global |
| 4.2 criteria workflow (`:193-199`) | Draft, pending approval, current, superseded; two approvals; review choices 3, 6, 12 months | Global rule. Two distinct approvers is a floor, not a setting | none | global |
| 4.2 reminder before review-by (`REVIEW_REMINDER_BEFORE`, `:199`) | 14 days [ASSUMED] | Tenant | `criteriaReminderDays`, 7 to 30 | tenant, clinical |
| 4.2 daily criteria job at 07:00 London (`U31.md:54`) | [ASSUMED] | Tenant | `criteriaReviewRunTime`, time | tenant, operational |
| 4.2 network endorsement of a criteria version (G3) | New | Network | `listingEndorsementRequired` | network, clinical |
| 5 clinical take timeout (`TAKE_TIMEOUT`, `:208`) | 10 minutes | Tenant | `clinicalTakeTimeoutMinutes`, 5 to 20 | tenant, clinical |
| 5 note length 280, advice choices (`:208`) | Rules | Global | none | global |
| 6.1, 6.2 registration states and the four checks (`:213-240`) | State machine; approve needs four checks | Global | none | global |
| 6.2 invitation validity (`INVITATION_VALID_FOR`, `:234`) | 48 hours | Tenant, tighten only above 24 | `invitationHours`, 24 to 168 | tenant, operational |
| 6.2 re-verification N days (`:241`) | 180 [ASSUMED] | Tenant | `reverifyDays`, 30 to 365 | tenant, clinical |
| 6.2 registration approvals (DEC-032, DEC-062) | Two distinct people by default, owner has not confirmed | Global floor of two until the owner decides | none, not configurable | global |
| 6.2 area check, `Settings.area_districts` default DT1 to DT11, BH1 to BH31 (`U28.md:54`) | A Dorset default | **No default.** A new tenant that inherits it is wrong | `areaDistrictPrefixes` (list), required at activation, network version for admission | tenant and network, operational |
| 6.2 owner email domains (`U28.md:54`) | `nhs.net` or the organisation's domain; free-mail list fails | Global free-mail list; tenant additions | `acceptedOwnerEmailDomains` (list) | tenant, operational |
| 6.2 scope questions and pilot categories (`U28.md:56`) | "on the Dorset pathway", "category on the pilot list" | Network | `pathwayName`, `pilotCategories` | network, operational |
| 7 text code: 6 digits, 10 minutes, 5 tries, resend 60 s (`:249`) | Security rule | Global floor | none | global |
| 7 PIN: 6 digits, 5 tries (`:250`) | Security rule | Global floor | none | global |
| 7 re-verify every 30 days (`REVERIFY_EVERY`, `:250`) | 30 | Tenant may only shorten | `reverifyEveryDays`, 7 to 30 | tenant, clinical |
| 7 link token 128 bits, single use (`:251`) | Security rule | Global | none | global |
| 7 pairing code 6 digits, 10 minutes (`:253`) | Rule | Global (uniqueness platform wide, section 3.2) | none | global |
| 7 support code 4 hours, access 1 hour (`O06.md:54-55`) | [ASSUMED] | Tenant may only shorten | `supportCodeHours`, `supportAccessMinutes` | tenant, operational |
| 7 session lifetimes: reporters 12 hours [ASSUMED] (`I13.md:55`); staff JWT 8 hours (`W09.md:49`) | | Tenant may only shorten | `sessionHoursReporter`, `sessionHoursStaff` | tenant, operational |
| 8 alert kinds, thresholds 2 or 4 hours, quiet hours "none or 22:00 to 06:00", acknowledge 10, 15, 30 (`:259-271`; DEC-046 item 4) | Options | Option sets global; the zone is tenant | none | global |
| 8 critical kinds `service-closed`, `system-pressure` [ASSUMED] (`:268`) | | Tenant | `criticalAlertKinds` (list) | tenant, clinical |
| 8 new-user defaults (`:271`) | All on except weekly | Tenant | `alertDefaultKinds`, `alertDefaultNotUpdatedHours`, `dailySummaryTime` (07:30), `weeklySummaryDay` (Monday) | tenant, operational |
| 8 escalation ladder: deputy, then "the SPOA shift lead" (`:269`, `ui-screens.md:3752`) | A named role in the SPOA | Tenant contact (`shift-lead-escalation`) for the final tier, delivered by event (G5) | `TenantContact` | tenant, operational |
| 9 message wording (`:279-321`) | Templates with "DIUCS:" prefix, "SystmOne", "[SPOA phone number]" | Wording global and IG approved; only whitelisted fields are tenant values | `senderLabel` (at most 12 characters, one SMS segment), `systemName`, `spoaPhone`, `referralSystemName` (default "SystmOne"; `domain-rules.md:288`, `ui-screens.md:1078,2091`), `fromDisplayName`. Every substituted field passes `find_patient_data` and a character allow-list, and the privacy guard runs after substitution | tenant and network, operational |
| 9 message catalogue ids C1 to K4 (`:293-321`) | | Global | none | global |
| 10 groups under 10 hidden (`:329`) | Floor | Global floor; scope may raise it | `minGroupSize` ≥ 10 | network and tenant |
| 10 telemetry retention raw 30 to 90 days, aggregates [period] (`observability.md:152`) | Set with IG | Tenant within a platform maximum | `retention.telemetry-raw`, `retention.telemetry-aggregates` | tenant |
| Link host `Settings.base_url` (`settings.py:18`) | One host `diucs.example` | Global (short links); per-tenant vanity host is a later option | none | platform |
| `Settings.minutes_per_avoided_call` (`U35.md:59`) | Unset shows "[x]" | Tenant (baseline is per organisation, `ui-screens.md:4399`) | `minutesPerAvoidedCall` | tenant |
| Board cache 60 s, wall poll 1 minute (`U09.md:52`, `architecture.md:175`) | [ASSUMED] | Global | none | global |
| Opening-hours semantics (`D03.md`): start inclusive, end exclusive, overnight windows, all day | Rules | Global | none | global |
| Planned closures (`notAvailable`, `D03.md:77`) | Not built | Per service | See 6.3 | per service |

### 6.2 Time zone

`LONDON = ZoneInfo("Europe/London")` is used by `london_time.py` (`contracts.md:85`) and imported by `schedule.py:19`, `opening_hours.py:19`, `alerts.py:25`, `criteria_workflow.py` (DEC-038) and the message formatter `format_hhmm`. All four UK nations observe Europe/London, so no UK tenant needs another zone. Recommendation: store `timeZone` on the tenant and the network now, validate it against an allow-list that today holds only `Europe/London`, and pass the zone explicitly into those five modules (a short, mechanical signature change, task TEN-K03). If the owner prefers to defer, keep the constant but record the decision so the constant does not spread into the roughly 137 undelivered tasks (the ledger shows 78 of 215 delivered). The domain rule "all domain times are UTC, everything a person sees is local" (`domain-rules.md:7`) is unchanged. Quiet hours (`22:00 to 06:00`) and the 07:00 criteria job use the tenant's zone.

### 6.3 Bank holidays and closures

The specifications do not model bank holidays anywhere (no mention in `docs/spec` or the prompts; `D03.md:77` puts planned closures out of scope, "later"). A service open Monday to Friday is prompted, shown "Not updated" and escalated on a bank holiday. That is the safe direction for the board, but it is reporter fatigue (F12) and a false chase for the shift lead. It is not new with tenancy, but tenancy adds a second variable: bank holidays differ between England and Wales, Scotland and Northern Ireland, so a tenant needs a holiday region. Recommendation: a shared read-only reference list of bank holidays per nation (platform reference data, like `Concept`), a tenant setting `holidayRegion` (`england-and-wales`, `scotland`, `northern-ireland`), and per-service closure windows (`notAvailable`, `fhir-data-model.md:125`) honoured by D03, D04 and the ladder. Build before any tenant outside England and Wales, and preferably before the pilot because the first Christmas will expose it. Task TEN-K05.

### 6.4 "Dorset" and other place-specific text

Found in: `templates.py:286` (I2), `D16.md:59`, `W05.md:51` and `ui-screens.md:657` (wall header), `W40.md:49` and `ui-screens.md:3608` ("Dorset system"), `U28.md:56` and `ui-screens.md:2743` ("Dorset urgent care pathway"), `ui-screens.md:2697`, `2835` ("Address found, in Dorset"), `ui-screens.md:3903` ("Outside Dorset"), `U28.md:54` (the area default), `ui-screens.md:2671` ("Not on the Dorset pathway"), `ui-screens.md:3685` (invitation sample). All come from `systemName` and `pathwayName` (network settings) or `displayName` (tenant). The registration form lists the referral method "SystmOne" (`ui-screens.md:2091`); other organisations use other systems, so the list of referral methods needs `referralSystemName` or a fuller list per tenant (the FHIR `referralMethod` is already a coded list).

---

## 7. Reporting and analytics across tenants

### 7.1 What is per tenant

Each tenant's own use cases, bound to its scope: its week summary (`U35`: referrals, best fit unavailable, time to a confirmed booking, updates by channel, `ui-screens.md:3644-3659`) from its own cases, bookings, communications and reports; its planning analysis (`U43`) from its own audit snapshots and outcomes; its telemetry aggregates (`O08`); its own board. These need no new governance beyond the existing "groups under 10 hidden" rule (`domain-rules.md:329`). A small tenant (six advisors) will see most telemetry groups suppressed. That is a property of the rule, and tenants should be told.

### 7.2 What the network can compute

The network scope holds an append-only `NetworkCapacity` series (section 4.7) with `reportedAt`, `nextDueAt`, `wasDueAt` and `status` for every member service under an active grant. From that, and only that, the network scope can compute: counts by status, system pressure over time, on-time update rate, time since last report, channel mix if `reportType` and source are in the allowlist, and capacity trends by category and catchment. Referrals, outcomes and best-fit analysis need cases and snapshots, which are in the owner tenant and never leave it, so those stay in the owner tenant's week summary and planning view (`U35.md:55-59`, `U43.md:55`). A per-member breakdown of on-time rate is capacity data but is reputationally sensitive; default is that members see only their own, and the owner sees the breakdown only if the agreement says so (the spec already says "not a league table", `ui-screens.md:1793`, `3847`).

### 7.3 Cross-network aggregates (regional or national)

Out of scope for v1 and not a role. If it is wanted later it needs a new grant scope `aggregate` with its own purpose, an agreement version, and IG sign-off (the same rule as DEC-132 item 7). Governance I would require:

- Aggregates are produced inside each tenant (or the network) on a schedule and published, as rows, into a separate analytics scope that no tenant can read.
- Only metrics classed non-personal are published without suppression (counts of services, statuses, capacity). Anything derived from cases is suppressed below 10 at source, and a second pass applies complementary suppression so a total minus the visible cells does not reveal a small cell.
- No live query crosses scopes. The publication is a message, not a join.
- The recipient is named in the grant; the analytics scope is read-only and has no row-level identity (services are pseudonymised per export with a salt).
- Withdrawal: ending the grant stops further publication; already-published rows follow the agreement's retention clause.

### 7.4 Telemetry

Telemetry attributes (`observability.md:24-34`) and the daily aggregate nodes (`fhir-data-model.md:303-307`) carry no tenant today. Add an opaque `tenant.id` span and event attribute (a hashed scope id, not the slug) and a `tenantId` on `FunnelDaily`, `FrictionDaily`, `ElementUsageDaily`, `RouteDaily` and `QueryStatDaily`; update the collector allow-list (`O04.md`). Query statistics by named query (`QueryStatDaily`) are platform operational data and need no tenant. IG flag: using tenants' staff session data across tenants for the operator's own product improvement is processing for the operator's own purpose, which can make the operator a controller for that processing. Default: telemetry is read per tenant; cross-tenant product analytics is allowed only on anonymised aggregates meeting the group size across at least three tenants, and only if the agreement says so. The rule that no per-person speed, error or ranking view exists (`observability.md:13-16,151`) applies in every scope.

### 7.5 Keeping later graph data science possible (DEC-001's reason for graph storage)

- Keep `tenantId` on every node so a tenant subgraph can be projected with a node filter. Network analytics project the network scope. Never project across scopes; cross-scope research uses an exported, pseudonymised graph in a separate analytics scope.
- Keep time series append-only (`Observation` and `NetworkCapacity`), with `effectiveDateTime` and `reportedAt` as typed datetimes (DEC-001), and never delete detail without writing the summary first (retention action `summarise`).
- Stamp every decision with the configuration version in force (`configVersion` on the status interpretation and on audit snapshots), so a status or a due time can be re-derived under the rule that applied.
- Keep service ids stable across versions and keep `sourceVersion` on projections, so a service's history is one chain.
- Keep relationships typed with one direction and one meaning (DEC-001) so the Concept walk "services that accept falls" (`fhir-data-model.md:6,554`) works per scope. The shared `Concept` and `CodeSystem` nodes are the only cross-scope nodes; projected criteria link to them, and a projection over a tenant must not traverse out through a shared `Concept` into another tenant's nodes (the filter on `tenantId` applies to every node on the path).
- Snapshot nodes are one node per service shown (`fhir-data-model.md:279`), not a JSON blob, so planning analysis stays a graph query.
- Run analysis on a read replica or separate database (`fhir-data-model.md:540`). On Community there is one database, so an export is the practical route. Verify the current licensing limits of the data science library before planning on its Community edition.

---

## 8. Hazards and information governance

Existing hazards are H-01 to H-28 (`hazard-log.md`). New rows use `H-T` (tenancy and lifecycle) and `H-N` (network). Severity and likelihood are the clinical safety officer's (`hazard-log.md:8`), so they are left `TBD`. "Verified by" names the test I propose; none exists yet.

### 8.1 Tenancy and lifecycle

| Id | Hazard | Cause | Control | Verification test (proposed) |
|---|---|---|---|---|
| H-T01 | One tenant sees or changes another's data | A query without the tenant predicate; a repository bug | `NamedQuery` registration refuses a statement without `$tenant` unless allow-listed (DEC-130 item 3); the binding refuses to run with none (item 2) | `tests/integration/graph_store/test_tenant_isolation.py::test_every_registered_query_returns_nothing_of_tenant_b_to_tenant_a`, `::test_every_write_leaves_tenant_b_unchanged` (generated from the registry, DEC-130 item 4) |
| H-T02 | A shared node joins two tenants | Shared `Identifier`, reused district `Location`, "reuse an existing practitioner" (`U15.md:55`, `U27.md:56`), placeholder nodes | All such nodes per tenant; no placeholders in tenant mode (section 3.4) | `::test_two_tenants_with_the_same_ods_code_and_district_share_no_node`, the relationship matrix test (`TEN-T02`) |
| H-T03 | A text goes from the wrong tenant's number, or to the wrong tenant's person | Sender resolved globally; recipient looked up globally | The outbox message carries the tenant; the sender is resolved from that tenant's channel; a missing channel fails closed with no send | `::test_a_message_for_tenant_a_is_sent_through_a_subaccount_a_and_never_b`, `::test_a_missing_channel_sends_nothing` |
| H-T04 | An inbound reply is applied in the wrong tenant | Lookup by sender only | `To` + `AccountSid` resolve the tenant (DEC-131 item 2); unknown number gets the fixed answer | `::test_a_reply_from_a_phone_in_both_tenants_is_applied_only_in_the_tenant_whose_number_it_was_sent_to` |
| H-T05 | A wall screen shows the wrong tenant's board | Shared cache key `board:v1` and channel; pairing to the wrong tenant | Per-scope keys and channels; the device is bound at pairing; the header names the tenant; the screen resolves its tenant every request | `::test_a_report_for_tenant_a_never_reaches_tenant_b_stream`, `::test_the_cached_board_of_a_is_never_served_to_b` |
| H-T06 | Support access is abused | The `support` role comes from a customer directory; standing access | Platform roles only from the operator directory; per-tenant access with a code or the tenant lead's approval; one hour; logged to both chains; shown to the tenant | `::test_a_customer_directory_cannot_grant_a_platform_role`, `::test_support_access_expires_and_is_logged_in_both_chains` |
| H-T07 | Staff act in the wrong tenant | One cookie for two tabs; no tenant name on screen | Tenant in the URL; cookie per slug; header and banner; irreversible actions name the tenant; a session for A with a B URL is refused | `frontend/e2e/tenant-tabs.spec.ts`, `::test_a_session_for_a_with_a_b_path_is_refused` |
| H-T08 | A reply on a shared phone goes to the wrong service | Two threads, both "DIUCS" | Per-tenant sender label; service name in every text and echo; range check | `::test_every_prompt_and_echo_names_the_service_and_the_sender_label` |
| H-T09 | A caller reaches another tenant's record by guessing an id in a path, query or body | Client-supplied ids in routes and in references | Every read and write is tenant bound, so a foreign id is "not found", with the same body and timing class as a missing record (`R02.md:55`, DEC-098 item 3); no existence oracle through constraint errors (section 3.4) | `::test_a_foreign_id_in_every_route_gives_the_same_response_as_a_missing_one` (`TEN-T04`) |
| H-T10 | A client idempotency key returns another tenant's stored result | `IdempotencyRecord.key` unique globally (migration 0029; `R03.md:56`) | `(tenantId, key)` and the actor in the fingerprint | `::test_the_same_key_in_two_tenants_runs_both_and_replays_neither` |
| H-T11 | An audit chain is spliced or contends | One global head and sequence (`P05.md:57`) | One chain per scope with its own genesis; verification per scope | `::test_a_chain_copied_into_another_tenant_fails_verification` |
| H-T12 | Suspending a tenant blinds advisors mid-call | Board disappears | Suspend modes; the network view degrades to "Not updated" and the tool-offline state; notify and a runbook; the manual process (`architecture.md:292`) | `::test_a_suspended_tenants_services_read_not_updated_on_the_network_board` |
| H-T13 | A retired number is reissued and replies land in a new tenant | Number reuse | 90-day quarantine; the unknown-number fixed answer | `::test_a_quarantined_number_cannot_be_assigned` |
| H-T14 | A configuration change silently alters a safety threshold | Direct edit of a constant or setting | Versioned immutable configuration; second approver for `clinical` settings; effective-from; the version stamped on decisions | `::test_a_clinical_setting_needs_two_approvers`, `::test_the_status_interpretation_records_the_config_version` |
| H-T15 | A new tenant runs with another place's defaults | "Dorset" districts and wording as defaults | No default for `areaDistrictPrefixes`; `systemName` and `pathwayName` required; activation blocked | `::test_activation_is_blocked_until_required_settings_exist` |
| H-T16 | A wall pairing code collides or is squatted | Six digits, unauthenticated start, global lookup | Unique open codes; rate limit; "Connect to <tenant>" confirmation | `::test_two_open_pairings_never_share_a_code`, `::test_the_pairing_start_is_rate_limited` |
| H-T17 | Anyone with database credentials reads every tenant | One Community database, no role-based access | Application enforcement only; privileged access controls; option of a dedicated instance per tenant (driver chosen at the binding point) | IG acceptance; `::test_the_binding_point_can_select_a_driver_per_tenant` |
| H-T18 | A purge deletes the wrong tenant's data | Operator error | Two operators, typed slug, dry-run counts, the `tenantId` filter only | `::test_purging_tenant_a_leaves_tenant_b_unchanged` |
| H-T19 | Nodes without a tenant id are invisible, and a service vanishes from the board | Backfill gap; Community cannot enforce existence (`migrations.py:6-10`) | Invariant query at start and daily; alert and degrade on any hit; a services-count reconciliation per tenant on the board | `::test_a_node_with_no_tenant_id_is_reported_by_the_invariant_check` |
| H-T20 | A worker binds the wrong tenant | The message property disagrees with the node | The handler loads the node and compares tenants; a mismatch dead-letters | `::test_a_message_whose_tenant_differs_from_its_node_is_dead_lettered` |
| H-T21 | Due times are wrong for a tenant | Time zone or bank holiday handling | Zone validated; tests per zone across clock changes; holiday calendar (TEN-K05) | `test_schedule.py` parametrised by zone; `::test_a_bank_holiday_closure_suppresses_prompts` |
| H-T22 | A directory mapping grants a role in the wrong tenant | A group mapped in the wrong tenant; a reused `tid` | Operator verifies the binding; the first-admin ceremony; mappings only for bound `tid`s | `::test_a_directory_not_bound_to_a_tenant_gets_no_role_in_it` |
| H-T23 | A token stays valid after suspension or role change | HS256 token valid until `exp`, no revocation (DEC-094 item 4) | Tenant `epoch` in the token, compared per request | `::test_a_token_issued_before_a_suspend_is_refused_after_it` |
| H-T24 | Entry points that precede a session resolve the wrong tenant | Link, pairing, device lookups without a tenant | Platform-scope resolvers return only tenant id and status; same refusal for unknown, expired, used | `::test_link_pairing_and_device_lookups_leak_no_tenant_information` |
| H-T25 | Reporters are treated as unknown after a key change | Per-tenant hash keys; legacy key for the default tenant | `hashKeyVersion` on the tenant; per-tenant dropped-reply alert | `::test_a_reporter_hashed_under_the_tenant_key_is_found` |
| H-T26 | A lost phone stays signed in in another tenant | No cross-tenant join | Runbook and Help text; remove-person screen shows the notice | `::test_sign_out_everywhere_affects_only_the_bound_tenant` (documents the limit) |
| H-T27 | Telemetry re-identifies a small tenant or leaks tenant identity | Tenant attribute; small groups | Opaque `tenant.id`; per-tenant reads; group floor; agreement for cross-tenant analytics | collector allow-list test (O04) extended |
| H-T28 | A clinician available in two tenants is double booked | Presence per tenant, no cross-scope lock | One duty tenant at a time; switching sets presence away in the old tenant | `::test_switching_tenant_sets_presence_away_in_the_previous_tenant` |
| H-T29 | A purged tenant's backups still hold its data | Backup retention | Backup expiry documented and accepted by IG; no restore of a purged tenant without the operator pair | IG item |

### 8.2 Network

| Id | Hazard | Cause | Control | Verification test (proposed) |
|---|---|---|---|---|
| H-N01 | A projection carries something it should not | A source property copied generically; a free-text field; a new field added later | DTO-based projection, versioned allowlist, grants name the allowlist version, the privacy guard on every string, a schema test on every network label | `tests/unit/application/test_projection_allowlist.py::test_network_scope_properties_equal_the_allowlist_exactly`, `::test_a_patient_shaped_value_in_any_text_field_is_refused`, `tests/integration/test_network_scope_scan.py::test_a_seeded_network_scope_holds_no_phone_postcode_or_name_shape`, `::test_no_relationship_leaves_a_network_node_into_a_tenant_scope` |
| H-N02 | A member sees another member's private data | Network read widened; a tenant query run under the network binding; a role that should not read | The network scope contains only the allowlist; the read is read-only and checks membership, grant and role; reporters excluded; scope-kind check on every registered query | `::test_member_a_reading_the_network_gets_no_field_outside_the_allowlist_for_b`, `::test_a_tenant_scoped_query_refuses_to_run_in_a_network_scope` |
| H-N03 | A stale projection is read as live | Projector stopped; lag; age computed from `projectedAt` | `validUntil`, heartbeat, "Last known" and "Not updated" degrade, age from `reportedAt`, per-member lag alert | `::test_a_paused_projector_makes_the_board_read_not_updated_after_valid_until`, `::test_data_age_is_computed_from_the_source_report_time` |
| H-N04 | A wall screen shows the wrong network's board | Screen's network set wrongly; membership ended; shared cache | Device bound to one tenant; `displayNetworkId` validated against active membership on every request; network name on the header; cache and channel per network; fallback with banner | `::test_a_screen_set_to_a_network_the_tenant_left_shows_the_tenant_board_with_a_banner`, `::test_a_screen_cannot_be_set_to_a_network_the_tenant_is_not_in` |
| H-N05 | A revoked grant still projects | A queued event processed after the end; a cached grant; a race | The projection write matches an active grant and takes its lock first; `effectiveTo` checked in the statement; the live view filters on the grant; a reconciliation job | `::test_no_projection_node_is_written_after_the_grant_end_commits`, `::test_a_racing_end_and_projection_serialise`, `::test_the_live_view_excludes_a_member_whose_grant_ended` |
| H-N06 | An older projection overwrites a newer one | Out-of-order delivery | `sourceVersion` monotonic; the upsert only moves forward | `::test_an_older_source_version_does_not_replace_a_newer_one` |
| H-N07 | A suspended or inactive service stays "Accepting" | Projection of status only | `active` and suspension are projected; the tenant's suspension stops the heartbeat | `::test_a_suspended_service_reads_not_updated_on_the_network_board` |
| H-N08 | A left member still shows live | Live view not filtered by membership | Membership and grant filters; history view separate | `::test_a_left_member_is_absent_from_the_live_view_and_present_in_history` |
| H-N09 | A member runs on an old agreement version unnoticed | Version drift | Membership shows the accepted version; admin notification; grants keep their approved version | `::test_a_member_behind_the_current_agreement_version_is_flagged` |
| H-N10 | Advisors use criteria nobody at the network endorsed | Criteria projected on approval alone | `endorsement` gate; the previous endorsed version stays | `::test_an_unendorsed_current_version_is_not_offered_to_advisors` |
| H-N11 | The owner reads private data by being the owner | A broad role | No role grants it (DEC-132 item 2); the owner's sessions bind its own tenant or the network scope only | `::test_a_network_admin_session_cannot_read_a_members_tenant_resources` |
| H-N12 | Two members list one real service | Duplicate admission | Key is (source tenant, source service); admission checks ODS code and name; the board shows the member name | `::test_a_listing_with_a_duplicate_ods_code_is_flagged` |
| H-N13 | A tenant id and a network id are confused | One property name for both | `ScopeRegistry.kind`; each registered query declares its scope kind | `::test_every_registered_query_declares_a_scope_kind` |
| H-N14 | The projector writes into the wrong scope | A bug in the two-unit-of-work sequence | Explicit scope on each unit; written nodes' `tenantId` equals the network scope and `sourceTenantId` equals the grantor; the DTO carries no scope field | `::test_projected_nodes_carry_the_network_scope_and_the_grantor_as_source` |
| H-N15 | The network board shows the wrong time zone or label | Hard-coded London or Dorset | Network `timeZone` and `systemName` | `::test_the_board_header_comes_from_network_settings` |

### 8.3 Human-only items (information governance and clinical safety)

These stay human, as the owner has ruled for sign-off (DEC-042 item 3, DEC-062, DEC-132 item 9). This build can record references and attestations; it cannot grant approval.

1. The data sharing agreement between tenants, its versions, and the controller and processor roles (platform operator, each tenant, the network owner), and the Article 28 contract between each tenant and the operator.
2. A data protection impact assessment for the platform and for the network scope, including the projection allowlist and each grant scope and purpose; the operator's registration with the information regulator.
3. IG approval of the projection allowlist, of each grant, of any new scope or purpose, and of the message wording with tenant fields (the substituted fields, not only the templates).
4. Retention periods for every class in section 2.3, for the network scope, and for backups after a purge; the offboarding policy and the 30-day and 90-day periods.
5. Clinical safety: DCB0129 is the manufacturer's (the platform operator's) hazard log and covers the tenancy and network hazards above; DCB0160 is each deploying organisation's. Each tenant needs a named clinical safety officer (`TenantContact`) who receives safety concerns (`U41.md:55`), with a copy to the manufacturer's officer. The [ASSUMED] clinical values per tenant (section 6, class `clinical`) need clinical safety sign-off, and a change needs it again.
6. The Data Security and Protection Toolkit and the digital technology assessment for the operator and, where required, for each tenant; a penetration test whose scope includes cross-tenant and cross-network access (insecure direct object reference tests, token and epoch tests, pairing and link resolvers, the projector).
7. Twilio subaccounts, sender registration, numbers and spend caps (DEC-131 item 1); the email sender identities; the OS Places licence for NHS use (`I12.md`); the push sender and VAPID key custody.
8. The Entra multi-tenant application registration, admin consent per customer directory, and the domain verification behind each `TenantEntraBinding`.
9. Whether and how the operator may use staff telemetry across tenants (section 7.4).
10. The decision on isolation strength (shared database versus dedicated instance for any tenant) and the privileged-access controls on the database.
11. A named authority at each tenant to sign the agreement and approve grants: the system can only record that an account asserted it.

---

## 9. Risks and open questions

### 9.1 Settled (owner decisions; no longer questions)

| Question I had raised | Settled by | Answer |
|---|---|---|
| What is a tenant? Network, organisation, or each legal entity? | DEC-132 item 1 | Each legal entity is one tenant and the controller of its own data |
| How do organisations collaborate? | DEC-132 items 2 to 4 | One Network owned by a lead hosting tenant; sharing only by Grants and read-only projections; no query spans scopes |
| Who is in the network, how many networks? | DEC-132 owner answers 3 and 5 | One network; the lead hosting organisation is the network owner |
| What is shared? | DEC-132 owner answer 2, item 4 | Capacity, the service directory (manual now, Directory of Services later) and criteria. Never reporters' personal data, bookings, cases, audit |
| Who sees the network view? | DEC-132 item 5 | Staff of member tenants whose role may see the board; reporters see their own tenant only; a wall screen is paired to one tenant and set by its administrator to show the tenant or network board |
| What happens to history when a member leaves? | DEC-132 item 6 | It stays, marked with the leave date; nothing new is projected |
| Patient-level coordination in the network? | DEC-132 item 7 | Out of scope; needs a new scope, purpose, agreement, IG and clinical sign-off |
| Who approves a grant? | DEC-132 item 3 | The grantor's administrator and the network owner |
| One Twilio account or one per tenant; how does an inbound reply find its tenant? | DEC-131 | One subaccount and number per tenant; the number called and the `AccountSid` |
| Shared mobile across tenants | DEC-131 item 3, DEC-132 | Two `Practitioner`s, one per tenant |
| Where is the tenant bound? | DEC-130 item 2 | At `run_query`, once per unit of work, one scope per unit |
| Do any cross-tenant roles exist? | DEC-130 item 8, DEC-132 item 8 | None yet (the model in section 4.2 is a proposal, see O5) |

### 9.2 Top risks, ranked

1. **DEC-132 leaves the cross-entity workflows open (section 4.9, G1 to G6).** Bookings, registration approval, criteria second approval, the chasing ladder, alerts and the week summary all cross legal entities today. About 30 undelivered tasks (`U17` to `U22`, `U28`, `U29`, `U33` to `U36`, `U13`, `U35`, `L02`, `W17` to `W22`, `W28` to `W31`, `W36`, `W39` to `W43`) assume one organisation. The booking path alone is a patient-safety flow. A wrong default here costs more than anything else in this file.
2. **A new safety-critical component: the projector and the network read path.** The board, the options list and the wall screen all become reads of copies. Staleness, ordering, a revoked grant still projecting and an allowlist leak are new ways to show a confident wrong figure or to expose data. Controls in sections 4.6 and 4.7 are designed but unproven; this component needs the mutation and race testing the delivery standard already applies to the repositories.
3. **Isolation is enforced by application code in one shared Neo4j Community database** (`contracts.md:45`, `migrations.py:6-10`). A missed predicate, a missing tenant id (not enforceable by constraint on Community), or database credentials expose every tenant. DEC-130's generated test is the right control; the invariant monitor (H-T19) and the access test harness (`TEN-T04`) close the rest. The residual belongs to IG.
4. **Global state and pre-session entry points** (section 3.2 and 3.3, 20 items). The `IdempotencyRecord.key` collision and the shared board cache key are leaks today. Link tokens, pairing codes, device tokens and the invitation link need platform-scope resolvers that are not yet in DEC-130's allow-list design.
5. **Identity.** One Entra app registration for one directory (`W09.md:47`); a `support` role that a customer directory can mint (`W09.md:48`); staff who work for two tenants (DEC-130 item 6); token revocation (DEC-094 item 4). Each can turn a tenant boundary into a role claim that a customer can forge.
6. **Backfill and constraints.** Six of the 26 migrations change a constraint; Community cannot require `tenantId`. The migration is additive and low risk, and it is only exercised by development data today, but the null-tenant failure is silent.
7. **Configuration and hard-coded place and time.** London time in five modules, "Dorset" in ten places, a Dorset district default, no bank holidays. All are cheap now and expensive after 137 more tasks are built on them.
8. **Tenant count.** Tenant = organisation means a Twilio subaccount, number, sender registration and an Entra binding per organisation. If the network has 20 or more members, onboarding is an operator workload, not a form. The cost of numbers and sender registration, and the time to obtain them, is on the critical path (`architecture.md:311`).
9. **Plan effort.** New work is about 271 hours in 71 tasks (section 10), excluding the DEC-130 seam, the in-flight task sweep and the rework of about 30 undelivered tasks under risk 1.

### 9.3 Genuinely open questions, ranked, each with a recommended default

Answer yes or no to each. Nothing below is decided by DEC-130, 131 or 132.

| # | Question | Recommended default |
|---|---|---|
| O1 | **Bookings (G1).** How does a booking request reach a provider and its answer return, given bookings are not shared? | Yes: the owner tenant texts a **booking contact** that the provider publishes in the directory (an organisational mobile), the reply returns on the owner's number, no tenant-to-tenant path. IG to confirm the disclosure of age band, need and urgency is covered. Bookings by app, push and email are not offered outside the owner tenant |
| O2 | Accept application-level isolation in one shared Neo4j database for the pilot, with the driver choice kept open at the binding point for any tenant that needs a dedicated instance? | Yes, and record the residual for IG |
| O3 | **Registration and the scope list (G2).** The provider registers in its own tenant; the network owner admits or declines the *listing* (call-back, scope decision), and the invitation is by the provider's own lead? | Yes |
| O4 | **Criteria (G3).** Two approvals inside the provider (owner plus its clinical lead), then the network's clinical lead **endorses** before advisors see the version? | Yes, endorsement required |
| O5 | **Chasing and control (G4, G4b).** The network owner can suspend a *listing*, advisor-phoned positions are written into the network scope, the provider's own lead changes its reporter numbers; the ladder is split between provider and network? | Yes |
| O6 | **Cross-tenant roles (DEC-130 item 8).** Platform roles only from the operator directory; support access to one tenant at a time, one hour, by a code or the tenant lead's approval, never reading the graph; no break-glass in the application? | Yes |
| O7 | Amend DEC-130 item 6: a session is bound to one tenant, but one person may hold a session in each tenant they work for? | Yes |
| O8 | **Registration approvals (DEC-032, DEC-062).** Two distinct people for a registration, not configurable? | Yes, two |
| O9 | **Alerts, summaries and the clinical pool (G5, G6).** Alerts by network events consumed per tenant; the owner tenant's week summary plus network capacity measures; clinical advisors from other organisations hold accounts in the owner tenant? | Yes |
| O10 | The owner tenant (the lead hosting organisation) hosts the SPOA's advisors, clinical advisors, shift leads and the case and booking data? | Yes |
| O11 | Lifecycle parameters: tenant creation by the operator only; 30-day offboarding notice; 90-day number quarantine; purge by two operators; activation blocked until retention is set by IG? | Yes |
| O12 | One link host `diucs.example` with the tenant resolved from the token, and an installed app per tenant at `/t/<slug>`? | Yes |
| O13 | Per-tenant derived phone-hash and token keys, with the legacy global key kept for the default tenant only? | Yes |
| O14 | Time: store `timeZone` per tenant and network, restrict to `Europe/London`, pass it explicitly; and build bank holidays before the pilot? | Yes to both |
| O15 | Telemetry: per tenant by default; cross-tenant product analytics only on anonymised aggregates meeting the group floor across at least three tenants and only under the agreement? | Yes |
| O16 | How many organisations will be in the network in the first year, and who pays for each number and sender registration? | I assumed 10 to 30. Please confirm; above 30 I would add self-service tenant creation with operator approval |
| O17 | Per-member breakdown of on-time rate visible to the network owner? | No unless the agreement says so |

---

## 10. Proposed task breakdown

Ids use the prefix `TEN-` and a group letter: F foundations, M migration, L lifecycle, A access, C channels, K configuration, N network, R reporting, T tests, W screens, H documentation. `SEAM` means the DEC-130 item 10 seam tasks (the binding in `run_query`, the registry rule and the two-tenant harness), which I assume exist elsewhere and are not counted here. Hours are the plan's units (3 to 4 hours per task, `tasks.json`). Each task follows the plan's test-first rules. The booking task `TEN-N16` is a placeholder for the answer to O1; it replaces rework of `U17` to `U22`, `L02` and `W19` to `W22` and `W36`, and its hours are a guess until the booking design is settled.

| Id | Title | Files | Hours | Depends on |
|---|---|---|---|---|
| | **Foundations** | | | |
| TEN-F01 | Tenant and scope domain model, lifecycle state machine, activation blockers (pure) | domain/model/tenant.py, domain/rules/tenant_lifecycle.py, tests/unit | 4 | F07, D22 |
| TEN-F02 | Scope registry, scope kinds, platform-scope resolvers (link, device, number, pairing) on the allow-list | adapters/outbound/graph_store/scope_registry.py, queries.py | 4 | SEAM, G01 |
| TEN-F03 | Tenant records and repositories (Tenant, config versions, settings, channels, numbers, contacts, Entra bindings, retention) and migrations | graph_store/tenant_repository.py, migrations.py | 4 | TEN-F01, TEN-F02 |
| TEN-F04 | Tenant settings registry (typed keys, bounds, safety class) and configuration versioning rules | domain/rules/tenant_settings.py, domain/model/tenant_config.py | 4 | TEN-F01 |
| TEN-F05 | Per-tenant key derivation, secret references, hashKeyVersion and the legacy key | application/ports/outbound/identity.py, adapters/outbound/secrets/ | 3 | P10, TEN-F03 |
| TEN-F06 | Per-scope audit chain: genesis, head per scope, verification per scope | audit_neo4j/audit_log.py, migrations.py | 4 | P05, SEAM |
| TEN-F07 | Composite constraints, expand and contract (table in section 2.6) | graph_store/migrations.py, test_migration_ids.py | 4 | SEAM |
| TEN-F08 | Session and token claims: scope, tenant epoch, per-request epoch check (amends R02, W02, W09) | domain/rules/bff_token.py, fhir_rest/auth.py, frontend/lib/auth/session.ts | 4 | R02, TEN-F03 |
| | **Migration and backfill** | | | |
| TEN-M01 | Default-tenant backfill job, label by label, restartable, idempotent | scripts/backfill_default_tenant.py, graph_store/backfill.py | 4 | TEN-F03, TEN-F07 |
| TEN-M02 | Invariant monitor: null tenant id check at start and daily, services reconciliation per tenant | graph_store/invariants.py, health.py | 3 | TEN-M01 |
| TEN-M03 | Cut-over runbook and scripts: drain, Redis, Service Bus, secrets, Twilio, Entra, rollback | docs/runbooks/tenancy-cutover.md, scripts/ | 3 | TEN-M01, TEN-F05 |
| TEN-M04 | Contract step: drop superseded constraints | graph_store/migrations.py | 2 | TEN-M02 |
| | **Tenant lifecycle use cases** | | | |
| TEN-L01 | CreateTenant, RecordTenantChannel, ActivateTenant | application/use_cases/tenant_admin.py | 4 | TEN-F03, TEN-F04, TEN-F06 |
| TEN-L02 | InviteTenantAdmin and first sign-in, BindEntraDirectory, MapEntraGroup | application/use_cases/tenant_access.py | 4 | TEN-L01, U25 |
| TEN-L03 | DraftTenantConfig, ApproveTenantConfig, configuration diff | application/use_cases/tenant_config.py | 4 | TEN-F04 |
| TEN-L04 | SuspendTenant and ResumeTenant: modes, epoch, relay gate, board degrade, rescheduling | application/use_cases/tenant_suspend.py | 4 | TEN-L01, TEN-F08, U36 |
| TEN-L05 | StartOffboarding and ExportTenant | application/use_cases/tenant_offboard.py | 4 | TEN-L04 |
| TEN-L06 | PurgeTenant, tombstone, number quarantine | application/use_cases/tenant_purge.py | 4 | TEN-L05 |
| TEN-L07 | Operator and tenant-admin API routes (/platform, /tenant, /me/tenants) | adapters/inbound/fhir_rest/routes_platform.py, routes_tenant.py | 4 | TEN-L01, TEN-A02 |
| | **Identity and access** | | | |
| TEN-A01 | Staff sign-in: multi-directory Entra, tid allow-list, group mapping, tenant chooser backend (amends W09) | frontend/lib/auth/staff.ts, application/use_cases/list_my_tenants.py | 4 | W09, TEN-L02 |
| TEN-A02 | Operator sign-in and roles: operator directory only, audience, separate route group and cookie | frontend/app/(operator)/, lib/auth/operator.ts | 4 | TEN-A01 |
| TEN-A03 | Support access scoped to one tenant, approved by the tenant lead (amends O06, R18) | application/use_cases/support_access.py, routes_support.py | 3 | O06, TEN-F08 |
| TEN-A04 | Wire pre-session resolvers: link token, invitation, device token, pairing with unique open codes and rate limit (amends L01, U10, R15, U24) | application/use_cases/pair_wall_screen.py, link_access.py | 4 | TEN-F02, L01, U10 |
| TEN-A05 | Tenant-keyed identity stores: Redis keys, code store, sessions, rate limits, devices (amends I13, U25, U32, I01) | adapters/outbound/cache_redis/, application/use_cases/text_code.py | 4 | I13, TEN-F05 |
| | **Channels and messaging** | | | |
| TEN-C01 | Per-tenant Twilio resolver, inbound webhook by To and AccountSid, receipts (amends I06, I07, I08) | sms_twilio/, sms_webhook/routes.py, workers/ | 4 | I07, TEN-F02 |
| TEN-C02 | Per-tenant email sender (amends I09, I10) | email_smtp/smtp_email.py, workers/message_senders.py | 3 | I09, TEN-F03 |
| TEN-C03 | Service Bus tenant property, per-tenant relay loop and lock, consumer binding check (amends I02, I03, I04, I05) | bus_servicebus/, workers/outbox_relay.py, consumer.py | 4 | I03, I04, SEAM |
| TEN-C04 | Push per tenant: VAPID per tenant, manifest per tenant (amends I14, W32) | push_webpush/, frontend/public/ | 3 | I14 |
| | **Per-tenant configuration** | | | |
| TEN-K01 | Thread tenant settings through the pure rules (reply window, ladder, stale limit, pressure, flags, group window, booking windows) | domain/rules/schedule.py, freshness.py, pressure.py, reply_policy.py, report_flags.py, multi_service.py, booking_rules.py, clinical_queue.py | 4 | TEN-F04, D04, D05, D08 |
| TEN-K02 | Load settings in use cases and keep the version on decisions (audit snapshot and status interpretation) | application/use_cases/*, audit snapshots | 4 | TEN-K01 |
| TEN-K03 | Time zone threading into the five modules (amends F06, D03, D04, D21, D24) | domain/rules/london_time.py, opening_hours.py, schedule.py, alerts.py, criteria_workflow.py | 4 | TEN-F04 |
| TEN-K04 | Template tenant fields and guard: sender label, system name, SPOA phone, referral system (amends D15, D16, D17) | domain/messages/templates.py, privacy_guard.py | 3 | D17, TEN-F04 |
| TEN-K05 | Bank holiday calendar and service closures | domain/rules/holidays.py, opening_hours.py, reference data | 4 | D03, TEN-K03 |
| | **Network, grants and projections** | | | |
| TEN-N01 | Network, membership, agreement and grant domain rules and state machines | domain/model/network.py, domain/rules/grants.py | 4 | TEN-F01 |
| TEN-N02 | Network scope repositories and migrations (Network, agreement, membership, grant, listing decision, projection health) | graph_store/network_repository.py, migrations.py | 4 | TEN-N01, TEN-F02 |
| TEN-N03 | Create network, add and remove members, leave notice | application/use_cases/network_admin.py | 4 | TEN-N02, TEN-L01 |
| TEN-N04 | Grant create, approve, change, end: two approvals, lock-first end | application/use_cases/grants.py | 4 | TEN-N03 |
| TEN-N05 | Projection allowlist registry, DTOs, privacy guard and schema tests | application/projection/allowlist.py, tests/unit | 4 | D17, TEN-N01 |
| TEN-N06 | Projector: directory and criteria | adapters/inbound/workers/projector.py | 4 | TEN-N05, TEN-N04, I04 |
| TEN-N07 | Projector: capacity and status with validUntil, heartbeat and ordering | adapters/inbound/workers/projector.py | 4 | TEN-N06, U09 |
| TEN-N08 | Provider-side boundary scheduler: overdue, open, close emit a projection | application/use_cases/projection_boundaries.py | 3 | TEN-N07, U03 |
| TEN-N09 | QueryNetworkBoard and the network versions of the options and criteria reads (amends U08, U12, G11) | application/use_cases/query_network_board.py | 4 | TEN-N07, U08 |
| TEN-N10 | Network cache and live stream; staleness degrade (amends U09, R06) | board_projector.py, routes_events.py | 3 | TEN-N09 |
| TEN-N11 | Wall screen display mode, tenant or network, with fallback (amends U10, W08) | pair_wall_screen.py, routes_screens.py | 3 | TEN-N10, TEN-A04 |
| TEN-N12 | Member leave handling: lapse grants, mark records, history view | application/use_cases/network_leave.py | 3 | TEN-N04 |
| TEN-N13 | Listing admission and criteria endorsement (G2, G3) | application/use_cases/listing_admission.py | 4 | TEN-N09, U28 |
| TEN-N14 | Network events to member alert evaluators (G5) (amends U33, U34) | application/use_cases/alerts.py | 4 | U34, TEN-N10 |
| TEN-N15 | Projection reconciliation and revoked-grant leak check job | application/use_cases/projection_reconcile.py | 3 | TEN-N07 |
| TEN-N16 | Booking path under the G1 default: booking contact in the directory, send from the owner tenant (contingent on owner decision O1; replaces rework of U17 to U22, L02) | application/use_cases/request_booking.py, link_access.py | 12 | TEN-N09, U17 |
| TEN-N17 | Advisor-phoned positions and listing suspension in the network scope (G4, G4b) (amends U13, U36) | application/use_cases/network_positions.py | 4 | TEN-N09, U13 |
| | **Reporting** | | | |
| TEN-R01 | Tenant and network dimension on telemetry and aggregates (amends O04, O08) | infra/otel-allowlist.txt, aggregate_repository.py | 3 | O04, O08 |
| TEN-R02 | Network-scope week summary measures (G6) (amends U35) | application/use_cases/week_summary.py | 4 | TEN-N07, U35 |
| | **Tests** | | | |
| TEN-T01 | Two-tenant and network test harness: seed two tenants and a network, generated network-scope checks | backend/tests/support/tenancy.py | 4 | SEAM, TEN-N02 |
| TEN-T02 | Relationship matrix test: cross-tenant references refused with the same body as missing | backend/tests/integration/test_cross_tenant_references.py | 4 | SEAM |
| TEN-T03 | Pre-session entry points and idempotency cross-tenant tests | backend/tests/integration/test_pre_session.py | 4 | TEN-A04, TEN-C01 |
| TEN-T04 | Access test harness: per-route cross-tenant and cross-network object reference attempts | backend/tests/integration/test_access_matrix.py | 4 | R02, TEN-T01 |
| | **Screens** | | | |
| TEN-W01 | Operator console shell, tenants list and detail | frontend/app/(operator)/ | 4 | TEN-A02, TEN-L07 |
| TEN-W02 | Create tenant wizard and activation checklist | frontend/app/(operator)/tenants/new | 4 | TEN-W01 |
| TEN-W03 | Suspend, offboard, export and purge dialogs | frontend/app/(operator)/tenants/[id] | 4 | TEN-W01, TEN-L06 |
| TEN-W04 | Tenant settings: configuration versions, diff, approvals | frontend/app/(tenant)/settings | 4 | TEN-L03 |
| TEN-W05 | Channels (read-only), Entra mapping, retention and operator access log pages | frontend/app/(tenant)/ | 4 | TEN-W04 |
| TEN-W06 | Tenant users and roles page | frontend/app/(tenant)/users | 3 | TEN-W04, TEN-L02 |
| TEN-W07 | Tenant chooser, header banner, URL scoping, per-slug cookies (amends W02, W09, every route group) | frontend/app/, lib/auth/, middleware.ts | 4 | TEN-A01 |
| TEN-W08 | Wall header, exec home and wording from settings (sweep of W05, W36, W40, W46, D16 texts) | frontend/components/board/, exec/ | 3 | TEN-K04 |
| TEN-W09 | Network admin: members, invite, remove, leave notice | frontend/app/(network)/members | 4 | TEN-N03 |
| TEN-W10 | Network admin: grants (create, approve, end) and agreement versions | frontend/app/(network)/grants | 4 | TEN-N04 |
| TEN-W11 | Network view on board and options, projection health and stale states | frontend/components/board/, advisor/ | 4 | TEN-N09, TEN-N10 |
| TEN-W12 | Wall screen mode control for the tenant admin | frontend/app/(tenant)/screens | 2 | TEN-N11 |
| TEN-W13 | PWA per tenant: manifest, scope, set-up flow changes (amends W32 to W35) | frontend/public/, app/(reporter)/ | 3 | TEN-C04, W34 |
| TEN-W14 | Listing admission and criteria endorsement screens | frontend/app/(network)/listings | 4 | TEN-N13 |
| | **Documentation** | | | |
| TEN-H01 | Hazard log rows, DCB0129 note and runbooks (suspend, offboard, lost phone, number quarantine) | docs/delivery/hazard-log.md, docs/runbooks/ | 3 | - |

| Group | Tasks | Hours |
|---|---|---|
| Foundations | 8 | 31 |
| Migration and backfill | 4 | 12 |
| Tenant lifecycle use cases | 7 | 28 |
| Identity and access | 5 | 19 |
| Channels and messaging | 4 | 14 |
| Per-tenant configuration | 5 | 19 |
| Network, grants and projections | 17 | 71 |
| Reporting | 2 | 7 |
| Tests | 4 | 16 |
| Screens | 14 | 51 |
| Documentation | 1 | 3 |
| **Total** | 71 | **271** |

### 10.1 What the total does not include

- The DEC-130 seam and the sweep of the existing 78 queries and delivered repositories.
- The amendment of about 30 undelivered prompts that assume one organisation (risk 1 in section 9.2); each needs a tenancy paragraph in its prompt, and the booking, registration, criteria, alert and week-summary ones need redesign under O1 to O9.
- Human-only work: agreements, DPIA, sign-offs, Twilio and Entra set-up (section 8.3).

### 10.2 Existing tasks that need a tenancy amendment (the change in one line)

| Task | Change |
|---|---|
| P05 | Per-scope chain, genesis and head (`TEN-F06`) |
| P06, P15 | Bind the scope in the unit of work; `(tenantId, key)` idempotency and processed markers |
| P10 | Per-tenant keys; platform-scope token resolver |
| P13 | List id per tenant; scope list becomes the network owner's listing candidates |
| P16 | Device ids per tenant enrolment; tenant-keyed contacts |
| P03 | Phone lookup per tenant; no sharing of practitioners (`U15.md:55`) |
| P07, P08 | Tenant on `Communication` and `ScheduledWork`; tenant message property |
| I01, I13 | Key prefixes per scope; sessions, codes, rate limits per tenant |
| I02, I03, I04, I05 | Tenant property; relay per tenant; consumer binding check |
| I06, I07, I08, I09, I10 | Per-tenant channel; inbound by `To` and `AccountSid`; per-tenant idempotency key |
| I12 | Per-tenant usage metering of OS Places |
| I14, W32 to W35 | Push, manifest and install per tenant |
| L01, L02 | Per-tenant CSRF secret; token resolver; booking per G1 |
| U03, U04 | Tenant sender label; grouping only within a tenant; time zone |
| U05 | Tenant bound lookups only |
| U09, R06 | Per-scope cache and stream; network board |
| U10, R15, W08 | Unique open pairing codes; tenant at confirm; display mode |
| U15, U16, U38 | Tenant only; no practitioner sharing; the provider's own lead |
| U17 to U22, W19 to W22, W36 | Booking path per O1 |
| U23, U24, U26 to U29, R10, W23 to W29 | Registration in the provider's tenant; listing admission in the network scope (O3) |
| U30, U31, W30, W31 | Criteria approvals in the tenant; endorsement in the network scope (O4); per-tenant job |
| U33, U34, W39, W40 | Subscriptions in the tenant; network events (O9) |
| U35, W41, U43, W51 | Per-tenant and network measures (section 7) |
| U36, U37, W42 | Tenant scope only; listing suspension (O5) |
| U40, U41, W44, W46 | Presence per tenant; safety officer from `TenantContact`; counter per tenant |
| O04, O06, O08, R18, W48 | `tenant.id`; support access per tenant (O6) |
| R02, W02, W09 | Tenant and epoch claims; Entra multi-directory; operator audience |
| D15, D16, D17 | Tenant fields in wording and the guard after substitution |
| D03, D04, D21, D24, F06 | Time zone parameter |
| W05, W36, W40, W46 | Header and wording from settings |
| F04, F10 | Harness: unique tenant per run, tenant-only cleanup (DEC-130 item 9); a second tenant and a network fixture |
