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
| Link token, capacity or booking (`GET/POST /links/{token}`, `contracts.md:139`; `L01.md`) | `Q-LINK-GET` by `tokenHash` (unique, migration 0021) | `Q-LINK-TENANT-BY-HASH` (platform scope) returns `tenantId` and `status`. The bound lookup then runs `Q-LINK-GET` inside the tenant. Unknown, expired, used or suspended all give the same 410 body (`L01.md:53`) | Keep `tokenHash` unique globally. The CSRF secret `link-csrf` (`L01.md:55`) is derived per tenant. The page header shows the tenant name and the service |
| Invitation link `/i/<token>` (`U24.md:58`) | Token purpose `invite` | Same resolver. `/register` takes `?invite=<token>` (`W23.md`) so the tenant is known before any phone is typed | A tenant-admin invitation uses purpose `tenant-admin-invite` |
| Text code request and verify (`U25`, `R11.md`) | `(phoneHash, purpose)`; request carries only a mobile | During registration the invitation token gives the tenant. For later sign-in (set-up, re-verify, PIN reset) the **installed app is per tenant** (`/t/<slug>/app`, manifest `start_url` and `scope` include the slug). The slug is a hint; the authority is a `Practitioner` found in that tenant by the tenant-keyed phone hash | Code key `diucs:<scopeId>:code:<hash>:<purpose>`; the code is texted from the tenant's number (DEC-131 item 5); unknown number gets the identical response, as `U25.md:56` requires |
| Inbound SMS (`I07`) | Allow-list by `phoneHash` only (`I07.md:55`); idempotency key `diucs:idem:sms:<MessageSid>` (`I07.md:56`) | `To` + `AccountSid` -> `TenantNumber` -> tenant (DEC-131 item 2). The signature is checked with that subaccount's token. Idempotency key `diucs:<scopeId>:idem:sms:<sid>`. The queued message carries the tenant property | Unknown number: fixed empty answer, log the id only. `U05` then runs bound to the tenant, so `find_by_phone_hash` and `latest_prompt_for_phone` (`U05.md:55`) can only see that tenant |
| Delivery receipt (`I08`) | `by_provider_id` | `AccountSid` -> tenant; `Communication` matched inside the tenant | |
| Wall pairing code (`U10`, `R15`) | Code hash looked up with no tenant; start is unauthenticated (`R15.md:55`) | Pairing records live in the platform scope (`WallPairing`: `codeHash`, `secretHash`, `expiresAt`, `status`). The code is unique among open pairings (regenerate on a clash). The lead of tenant T confirms it, which writes `tenantId = T` into the record. The claim then returns the device token | Rate-limit the unauthenticated start per address (none is specified). The lead's page says "Connect to <tenant name>" before the button. The paired screen shows the tenant name large for 10 seconds |
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
- The "in-pilot" gate (`domain-rules.md:234`) moves. It is no longer a tenant-side check (it would need a cross-scope read). It becomes the network owner's decision at step 9 (listing admission). The invitation still locks the service name, ODS code and mobile (`ui-screens.md:2896`).

**Step 2. The applicant opens the link and verifies the phone.** `/register?invite=<token>`, text code, session role `reporter` (`W23.md`).
- Records: the code hash in Redis; the session. A `text-code` audit entry (purpose and outcome only, `U25.md:58`).
- Tenant: from the invitation token (section 3.2). The code is sent from the tenant's number.
- Rate limits and code keys are per tenant and per tenant-keyed phone hash.

**Step 3. Draft.** `RegistrationDraftField` rows and the Task (DEC-080). Tenant owned. The ODS code and service name are locked from the invitation. The reporter's mobile or email goes only to `ProtectedContact` (`U26.md:55`). Uniqueness of the ODS code is per tenant (migration 0002 change).

**Step 4. Submit and persist as one FHIR transaction (`U27`).** Records: `Organization`, `Location`, `HealthcareService` (all inactive) and the first `ServiceCriteria` (`pending-approval`). Reused district `Location`s (`U27.md` test 2) become per tenant. The bundle writer resolves `urn:uuid:` references only inside the bundle, and refuses any other id that is not in the tenant (section 3.4). The OS Places call carries only a site postcode (`I12.md`); the key and the quota are platform level, so record usage per tenant.

**Step 5. Review (`U28`).** The tenant's `lead` runs the automatic checks, the call-back (to the register number, `U28.md:55`) and records Provenance.
- Configuration used: `areaDistrictPrefixes` and `acceptedOwnerEmailDomains` from the tenant's settings (section 6). The ODS lookup is shared read-only reference data.
- The "scope" check (`checkScope`, DEC-081 item 3) no longer comes from the same person. It is the network owner's listing decision (step 8), delivered back to the tenant as an event (`ListingDecided`) that a tenant-bound consumer records on the registration. If the tenant is not in a network, the tenant lead decides scope.

**Step 6. Criteria second approval (`U30`).** Within the tenant, the owner and a `clinical-lead` role in the same tenant (two distinct people, DEC-032; `U30.md`). A second tenant's clinical lead cannot approve it because they cannot see it. The network owner's clinical lead performs a separate **endorsement** of the projected version (section 4.9, gap G3).

**Step 7. Approve and test prompt (`U29`).** Needs two distinct people, the requester and the approver (DEC-032, `U29.md` "Added after D22"; the owner has not confirmed whether a registration needs two people, DEC-062 left it open; keep two as the default). The I3 test prompt is sent from the tenant's number to the registered phone. The answer arrives on that number and is matched to the registered phone hash inside the tenant (`U29.md:54`).

**Step 8. Listing admission (new, network scope).** After the tenant approves, the service appears as a `listing request` in the network scope (a projection of the directory scope). The network owner's `network-admin` or `lead` runs the network-side checks: call-back, scope decision (`in-pilot`, `later`, `out-of-scope`, with reason), criteria endorsement. The decision is a network-scope record `ListingDecision`. The tenant receives `ListingDecided`. Until a listing is approved the service is not shown on the network view (and a board that mixes unapproved services would repeat F26, "fake service").

**Step 9. Go live (`U29`).** The tenant's `lead` sets the service live (needs `approved`, a test answer and, if in a network, an approved listing). Effects in the tenant: `active=true`, new resource versions, first `prompt-due` `ScheduledWork` and its `ScheduleWork` outbox message, `RegistrationApproved`. Effects in the network: the projector starts the directory, criteria and capacity projections for this service.

**Step 10. Links between services, reporters, locations and districts.** `PractitionerRole` (`PRACTITIONER`, `HEALTHCARE_SERVICE`, `ORGANIZATION`), `HealthcareService` (`LOCATION`, `COVERAGE_AREA`, `CURRENT_CRITERIA`), `Location` districts. All within one tenant. Check: section 3.4.

**Step 11. Reporter set-up: channel, home screen, notifications, PIN, device (`W33`, `W34`, `U32`).**
- Records: `Credential` and `Device` (per practitioner and device), `PushSubscription`, a `Consent` or `Basic` (`I14.md:55`).
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
