# W9C routes: the operator, support and tenant administrator API (for the screens that follow)

Back end only; nothing here is built in the front end. Source of truth: `routes_platform.py`, `routes_tenant.py`, `auth.py`, `app.py`. The mount is the app ROOT, not `/fhir` (a BFF route uses `root: true`). All answers are JSON with `Cache-Control: no-store`; every error is a FHIR `OperationOutcome` (`{"resourceType":"OperationOutcome","issue":[{"severity":"error","code","diagnostics"}]}`) with fixed words.

## The two doors

| door | token | made by | roles | binds |
|---|---|---|---|---|
| operator, `/platform/**` | audience `diucs-ops`, claims `sub` (the opaque account reference), `role`, `exp` only | `POST /auth/operator-token` `{idToken}` -> `{token, expiresAt, role}` (one hour) | `platform-operator`, `support` | no tenant of its own; an operator-only route binds the tenant of its PATH |
| tenant, `/tenant/**` | audience `diucs-api`, claims incl. `tenant` and `epoch` | `POST /auth/token` | `tenant-admin` only | the signed `tenant` claim and nothing else |

`Authorization: Bearer <token>`. A tenant token on `/platform/**`, an operator token on `/tenant/**` or any tenant route, a missing, expired, mis-signed or wrongly-claimed token: the one 401 (`code: "login"`, `WWW-Authenticate: Bearer`). A valid token of a role the route is not for: the 404 `not-found` of a route that is not there (never a 403). A path that is not a tenant id: 404.

Writes (POST, PUT, DELETE) need `Idempotency-Key: <1-200 printable ASCII>` (400 `required` without) and, for POST and PUT, `Content-Type: application/json` even with no body (send `{}`; otherwise 415). A repeat with the same key and body returns the first answer with `Idempotent-Replay: true`; the same key with another body is 422. EXCEPTIONS: a support person's writes and a tenant ticket approval are not replayed (the approval's answer holds the code). Every body is strict: an unknown field (including any `tenant`, `tenantId`) is a 400.

Common statuses: 400 invalid body or parameter (`expression` names the field), 404 not found or not for you, 409 conflict or the move is not allowed in the state (`code: "conflict"` or `"business-rule"`), 422 key reused, 500 service not configured, 503 transient.

## Operator door: `/platform`

Times are UTC `YYYY-MM-DDTHH:MM:SSZ`.

### Session and list
- `GET /platform/session` (operator, support) -> `{role, accountRef, expiresAt, permissions[]}`. Permissions: operator `tenants:list, tenants:read, tenants:provision, tenants:lifecycle, audit:read`; support `tenants:list, support:request`. The token is the session: sign out = drop it; renew = exchange again.
- `GET /platform/tenants` (operator, support) -> `{tenants:[...]}`. Operator row: `{id, displayName, status, organisationType, host|null, activatedAt|null}`. Support row: `{id, displayName, status}`. Status: `provisioning|active|suspended|offboarding|offboarded|purged`.

### Operator: provisioning (all operator only; `{id}` is a tenant id)
- `PUT /platform/tenants/{id}` `{displayName, legalName, organisationType, countryCode="GB", timeZone="Europe/London", odsCode?}` -> 201 `{tenantId, created:true, recorded}` (new) or 200 `{..., created:false, recorded}` (a creation that stopped is finished). `organisationType`: `nhs-trust|icb|gp-practice|local-authority|voluntary-independent|other`.
- `GET /platform/tenants/{id}` -> `{tenant:{id, displayName, legalName, organisationType, countryCode, timeZone, odsCode, status, epoch, createdAt, activatedAt, suspendedAt, suspendMode, suspendReason, offboardingStartedAt, offboardedAt, purgedAt, references:{dsa, dpia, dcb0160}}, host, directoryId, numbers:[{e164, accountSid, status, testedAt, quarantineUntil, hasSecret}], activation: null | {ready, blockers:[string]}}`. `activation` is set only while `provisioning`; blockers are fixed words (`Host set`, ...). No secret reference is ever shown.
- `PUT /platform/tenants/{id}/host` `{host}` -> 200 `{recorded}`; a host another tenant holds: 409.
- `POST /platform/tenants/{id}/numbers` `{e164, accountSid, senderLabel}` -> 201 `{channelId, recorded}`; a number another tenant holds: 409.
- `POST /platform/tenants/{id}/numbers/tested` `{e164}` -> 200 `{recorded}`.
- `PUT /platform/tenants/{id}/references` `{dsaRef?, dpiaRef?, dcb0160Ref?}` (at least one) -> 200 `{references:[names recorded by this call: "dsa_ref"|"dpia_ref"|"dcb0160_ref"], recorded}`.
- `POST /platform/tenants/{id}/directory/verification` `{directoryId}` -> 200 `{recorded}` (only a directory the tenant's administrator bound and that is `pending`; else 404).
- `POST /platform/tenants/{id}/admin-invitation` `{mobile}` -> 201 `{expiresAt, recorded}`. The mobile is never echoed. One open invitation at a time (409).
- `POST /platform/tenants/{id}/activation` (no body) -> 200 `{tenantId, epoch, seeded:[bool,bool], recorded}`; not ready: 409 with `diagnostics: "Activation is unavailable until: <blockers joined by '; '>"`.

### Operator: lifecycle
- `POST /platform/tenants/{id}/suspension` `{mode: "read-only"|"blocked", reason: "security-incident"|"information-governance"|"clinical-safety"|"contract"|"operator-request"}` -> 200 `{tenantId, epoch, mode, recorded}`; not active: 409.
- `DELETE /platform/tenants/{id}/suspension` -> 200 `{tenantId, epoch, servicesPrompted, servicesAnnounced, resumedAgain, recorded}`; not suspended: 409.
- `POST /platform/tenants/{id}/offboarding` `{confirmTenantId}` (the tenant's own id, typed) -> 200 `{tenantId, startedAt, noticeEndsAt, recorded}`; a wrong confirmation 400; a tenant that is not active or suspended 409. The tenant is closed at the edge from now (known issue W9C-K2): the console must say so in the dialog.
- `recorded: false` on any of these means the step was DONE and the platform chain could not record it; the console says so and does not retry the step.

### Operator: the platform chain
- `GET /platform/audit?afterSeq=0&limit=50` (limit 1-200) -> `{entries:[{seq, action, principalRef, tenantId|null, accessId|null, snapshot|null, at}], next: seq|null}` oldest first; `next` is the `afterSeq` of the next page, null at the end. Actions: `tenant-created`, `tenant-host-set`, `tenant-number-recorded`, `tenant-number-tested`, `tenant-references-recorded`, `tenant-directory-verified`, `tenant-admin-invited`, `tenant-activated`, `tenant-suspended`, `tenant-resumed`, `tenant-offboarding-started`, `operator-signed-in`, `support-ticket-requested|cancelled|approved|refused|revoked|opened|ended`, `support-access-opened|used|ended|revoked|refused|aborted`.
- `GET /platform/audit/verification` -> `{intact: bool}` (walks the whole chain).

### Support: the ticket (support role only)
- `POST /platform/tenants/{id}/support-tickets` `{reasonCode: "security-incident"|"clinical-safety"|"service-fault"|"configuration"|"user-request"|"other", reason (10-200 chars of letters, digits and . , ' & ( ) + -, at most 6 digits, no postcode, NHS number or titled name), reference? (help-desk number: letters, digits, hyphens, 32)}` -> 201 ticket. The tenant must be active (else 404); a second live ticket for the same tenant is 409.
- `GET /platform/support-tickets` -> `{tickets:[ticket]}` (the caller's own, newest first, 50). `GET /platform/support-tickets/{ticket}` -> ticket.
- `POST /platform/support-tickets/{ticket}/cancellation` -> 200 ticket (only while `pending`).
- `POST /platform/support-tickets/{ticket}/access` `{code}` (the code the tenant's administrator gave, `XXXX-XXXX`) -> 200 `{ticket, access:{accessId, tenantId, expiresAt}}`. Every refusal (not your ticket, not approved, a wrong, used or lapsed code) is the one 404. The code opens once, one tenant, one hour.
- `DELETE /platform/support-tickets/{ticket}/access` -> 200 ticket (the access ends at once).
- Support ticket shape: `{id, tenantId, state, reasonCode, reason, reference|null, requestedAt, validUntil, decidedAt|null, openedAt|null, endedAt|null, endedBy: "support"|"tenant-admin"|null, accessId|null}`. `state` is the EFFECTIVE state: `pending|approved|refused|cancelled|opened|ended|revoked|expired` (a live ticket whose `validUntil` has passed reads `expired`). The deciding administrator is not named and no hash is shown.

## Tenant door: `/tenant` (role `tenant-admin`)

A tenant suspended `read-only` lets the administrator read (GET) and refuses every write at the edge (401).

### Reads
- `GET /tenant/overview` -> `{tenant:{id, displayName, legalName, organisationType, countryCode, timeZone, odsCode, status, host|null}, config: null | {version, status, values:{key: value}, createdAt, createdByRef, effectiveFrom, approvedByRefs[], reasonCode}, contacts:[{kind, label, value}], channels:[{id, kind: "sms"|"email", provider, status, senderLabel, accountSid|null, fromAddress|null, fromDisplayName|null, hasSecret}], retention:[{dataClass, keepDays|null, action}], bindings:[{directoryId, status: "pending"|"verified"|"revoked", verifiedAt|null}], mappings:[{groupObjectId, role, status: "active"|"retired"}]}`. `config.values` holds only the overrides (a key absent has its default); a time is `HH:MM`, a set of codes a sorted list.
- `GET /tenant/settings` -> `{settings:[{key, kind: "int"|"text"|"bool"|"time"|"codes", unit, default, minimum, maximum, choices|null, allowed|null, safetyClass: "clinical"|"operational", scope: "tenant"|"network"|"both", requiredForActivation}]}` (the registry the draft form is built from; clinical keys need two approvers).
- `GET /tenant/config/versions` -> `{versions:[version]}` newest first; `GET /tenant/config/versions/{n}` -> version. Version = the config shape above plus `changedKeys[]`, `clinicalKeys[]`, `approvalsRequired`, `replaces: n|null` (the diff against the version in force below it). `status`: `draft|pending-approval|current|superseded`.
- `GET /tenant/access-log?days=90` (1-400) -> `{entries:[{at, useCase, action, role: "platform-operator"|"support", actorRef, entityIds[], snapshot|null}]}` newest first, 200 at most: what the platform's own people did in this tenant.

### Configuration changes
- `POST /tenant/config/drafts` `{basedOn (the version in force you read, 0 if none), changes:{key: value}, removals:[key], reasonCode?}` -> 201 `{version, changedKeys, clinicalKeys, approvalsRequired}`. A stale `basedOn`: 409; an unknown key, a value outside its bounds, a draft that changes nothing: 400.
- `POST /tenant/config/versions/{n}/approval` -> 200 `{version, status, approvals, approvalsRequired}`; the author of a clinical change, a repeat approver, an older version: refused (404 or 409). The approval that completes it makes it current.
- `PUT /tenant/contacts` `{kind: "coordination-phone"|..., label, value}` -> 204 (one contact per kind).
- `POST /tenant/channels` / `PUT /tenant/channels/{id}` `{kind: "email", senderLabel, fromAddress, fromDisplayName?, secretRef? (this tenant's own), status?}` -> 201 / 200 `{id}`. `kind: "sms"` is a 400 ("set by the platform operator").
- `PUT /tenant/retention` `{useDefaults: true}` or `{rules:[{dataClass, keepDays|null, action: "delete"|"summarise"|"keep"}]}` -> 200 `{stored}`.
- `PUT /tenant/directory` `{directoryId}` -> 204 (binds as `pending`; the operator verifies).
- `PUT /tenant/role-mappings` `{groupObjectId, role (advisor|clinical|lead|owner|exec|audit), status? "active"|"retired"}` -> 204.

### Support tickets, the administrator's side
- `GET /tenant/support-tickets` -> `{tickets:[ticket]}`; `GET /tenant/support-tickets/{id}` -> ticket. Ticket = `{id, state, requestedByRef, reasonCode, reason, reference|null, requestedAt, validUntil, decidedByRef|null, decidedAt|null, openedAt|null, endedAt|null, endedBy|null, accessId|null}` (`state` effective, as above).
- `POST /tenant/support-tickets/{id}/approval` -> 200 `{ticket, code, codeExpiresAt}`. The `code` is shown ONCE (the screen says "give this to the support person; it is not shown again; valid for four hours; opens one access for an hour") and is never cached or stored: if the answer is lost, revoke and ask again. A ticket not pending: 409.
- `POST /tenant/support-tickets/{id}/refusal` -> 200 ticket. `DELETE /tenant/support-tickets/{id}/access` -> 200 ticket (`revoked`): takes back an approved code or ends an open access at once.
- Another tenant's ticket is a 404 on every one of these.

## What a BFF needs to hold

- The operator console signs in through `/auth/operator-token` and keeps the token in a sealed cookie like the tenant session; the console is a separate origin from every tenant host. Use `root: true` for these routes. The `/platform/session` read is how the page learns the role and permissions after a reload.
- The tenant administration pages use the ordinary tenant-bound session with role `tenant-admin` (`/auth/token` maps the directory group; the first administrator comes from the invitation).
- Test support for the front end: the shapes above are what the route modules write (`tenant_to_dict`, `detail_to_dict`, `support_ticket_to_dict`, `overview_to_dict`, `version_to_dict`, `ticket_to_dict`, `log_entry_to_dict`, `audit_record_to_dict`); generate fixtures from them as `backend-shapes.gen.py` does for the other routes.
