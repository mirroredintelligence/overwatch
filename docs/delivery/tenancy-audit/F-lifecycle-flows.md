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
3. **Shared state is keyed globally in at least 19 places** (section 3.3): `board:v1`, the `board.updates` channel, the `outbox-relay` lock, the single `AuditHead`, `IdempotencyRecord.key`, `ChainLink.seq`, `ServiceRequest.reference`, the fixed `scope-list` id, `Settings.area_districts`, `twilio_from`, one `bff-jwt` secret and one phone-hash secret, and others. The idempotency key one is a real data-leak path (an arbitrary client key returns another tenant's stored result).
4. **DEC-132 does not cover the booking flow, registration approval, criteria second approval, the chasing ladder, alerts or the week summary**, all of which cross legal entities today. Its three scopes are capacity, directory and criteria. Section 4.9 lists each gap with a proposed default. These are the largest unanswered design questions.
5. **Neo4j Community cannot enforce "every node has a tenant id"** (property existence constraints are Enterprise-only; `migrations.py:1-10`). A node missing its tenant id is invisible to every tenant-bound query. A service that vanishes from the board looks like "not listed", not "not updated". That needs a startup and daily invariant check, not only tests (section 2.6).
6. **Constants that are really tenant or network configuration**: London time zone in five modules, "Dorset" in five templates and screens, "SystmOne" in B1 wording, a Dorset-specific default for `area_districts`, the 14:00 second report, the 2-hour stale limit, pressure thresholds of 3 and 5 (section 6). Bank holidays are modelled nowhere (`D03.md:77` defers planned closures).

Difficulty by area (hours are my estimates for work beyond the DEC-130 seam tasks; the total is in section 10):

| Area | Difficulty | Why |
|---|---|---|
| Storage seam and constraints | Medium | Mechanical, but 9 of the 28 migrations need an expand-and-contract change (section 2.6) |
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
| Create | platform-admin | Unique slug; legal name; owner tenant of an existing network if it is a member | `Tenant` in `provisioning`; `TenantConfigVersion` 1 as `draft` from platform defaults; tenant audit chain created (genesis is `sha256("diucs-genesis:" + scopeId)`, section 2.6); secret references recorded; tenant-scope tombstone-free |
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

State today: 48 of 215 tasks are delivered (`STATUS.md`, generated 2026-10-25, stale), no go-live, so the data is development and pilot data. The steps below are still required because they are also the production schema change.

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

**Constraint and index conversion** (from `migrations.py:20-132`):

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
