# Tenancy audit C: adapters (except graph_store and audit_neo4j), bootstrap and infra

Audited at `main` 2cf069e (DEC-130 at 1ac81b9, DEC-131 at 65c7da2, DEC-132 on top; section 13 covers DEC-132). Read-only audit; this is the only file written.
Basis: DEC-130 (tenant on every node, bound once per unit of work from a verified source), DEC-132 (tenant is the legal entity; a Network shares capacity, directory and criteria through grants and read-only projections), DEC-131 (one Twilio subaccount per tenant, tenant resolved from `To` plus `AccountSid`), and DEC-002, 003, 012, 077, 089 to 096, 098, 101.

Conventions: paths are under `backend/src/diucs/` unless they start with `backend/tests`, `infra/`, `docs/` or `frontend/`. "Branch" paths are read with `git show task/<name>:<path>` (see section 12 on why local `task/*` refs). "Delivered" means delivered in the ledger refreshed on `origin/ledger-refresh` (76 of 215 tasks; the `docs/delivery/STATUS.md` on main is stale at 48).

---

## 1. SUMMARY

### Counts (all verified by grep or a script on main unless marked)

| Item | Count | Detail |
|---|---|---|
| HTTP routes served today | 3 | `GET /health` (`adapters/inbound/fhir_rest/app.py:47`), `GET /fhir/metadata` (`capability.py:456`), `GET /events` (`routes_events.py:160`). R03's `concurrency.py` has helpers only, no PUT or `_history` route exists. |
| HTTP routes named in `docs/spec/contracts.md` (planned) | 45 | 27 on lines 134 to 139, plus 18 in the "HTTP (back end)" additions table (R15 3, R16 1, R17 1, R13 3, R18 10). R04 to R12 resource routes are not enumerated, so the real number is higher. |
| Unmerged branch routes | 2 | `GET` and `DELETE /api/bff/session` (W02, Next.js, `frontend/app/api/bff/session/route.ts:30-31`). |
| Inbound adapter packages | 1 delivered (`fhir_rest`, 6 modules, 910 lines incl. `__init__`) | Planned and absent: `sms_webhook` (I07), `link_pages` (L01), `workers` (I03 relay, I04 consumer and runner, I08, I10, I05 under `scheduler`). |
| Outbound adapter packages in scope | 6 real | `bus_servicebus`, `cache_redis`, `clock_system`, `email_smtp`, `ids_uuid`, `sms_twilio`. Excluded: `graph_store`, `audit_neo4j` (auditor A). |
| Test fake modules (`adapters/testing`) | 10 | `fixed_clock`, `fixed_geo`, `fixed_ids`, `fixed_secrets`, `fixed_terminology`, `memory_cache`, `memory_code_store`, `memory_event_bus`, `recording_senders`, `tokens`. |
| Planned adapters not built | 7 | geo and terminology real adapters (I11, I12, only `Fixed*` fakes exist), telemetry (O01, O07), Redis sessions and code store (I13), Web Push (I14), outbox relay (I03), SMS webhook (I07). |
| Bootstrap modules | 2 | `bootstrap/container.py` (94 lines, 4 fields: `clock`, `ids`, `neo4j`, `uow_factory`), `bootstrap/settings.py` (42 lines). |
| Service Bus queues | 3 | `inbound.replies`, `inbound.receipts`, `scheduled.work` (`infra/servicebus-config.json:8,22,36`). |
| Service Bus topics | 6 | `capacity.events`, `booking.events`, `registration.events`, `criteria.events`, `alerts.events`, `messages.outbound` (lines 52, 98, 156, 202, 236, 282). |
| Service Bus subscriptions | 18 | 3 + 4 + 3 + 2 + 3 + 3. No filter rules anywhere (`Rules` does not occur in the file). 3 are session-enabled (`capacity.events`). |
| Redis key or channel patterns on main | 3 concrete, in 4 families | `cache:board:v1`, `cache:idem:<sub>:<key>`, `chan:board.updates`; families `lock:` and `fence:` exist in the adapter (`redis_cache.py:22-24`) but nothing on main calls `acquire_lock`. |
| Redis patterns planned | 8 | `sess:<id>`, `sess-by-person:<id>`, `code:<phone_hash>:<purpose>`, `idem:sms:<MessageSid>`, `cache:travel:<site>:<district>`, rate-limit counters (I13, names unspecified), presence heartbeats (U40, P18), link-token lookup cache (architecture.md:14, no prompt), reference-data cache (architecture.md:17, no prompt). Lock `outbox-relay` (I03). |
| Env vars | 21 `DIUCS_*` settings fields, plus 6 outside Settings | Settings: `bootstrap/settings.py:17-42` (21 fields, verified by script). Outside Settings: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `REDIS_URL`, `SERVICEBUS_CONNECTION` (tests only, `backend/tests/integration/test_infra_up.py:24-28`), `MSSQL_SA_PASSWORD` (`infra/docker-compose.yml:44,62`, `infra/.env.example`). Frontend: `DIUCS_FHIR_BASE_URL` (`frontend/lib/fhir/client.ts:36`), `SESSION_SECRET` (W02 branch, `session.ts:35`). Planned: `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, `BACKEND_JWT_SECRET` (W09), `APPLICATIONINSIGHTS_CONNECTION_STRING` (O04), `otlp_endpoint` (O01). |
| Secret store names | 3 in code, 4 planned | In code: `bff-jwt` (`auth.py:28`), `link-token` (`application/ports/outbound/tokens.py:15`), `phone-hash` (`application/ports/outbound/identity.py:18`). Planned: `link-csrf` (L01), `code-hmac` (U25), VAPID private key (I14), per-tenant Twilio token refs (DEC-131). |
| Infra files | 4 | `docker-compose.yml` (5 services: neo4j, redis, servicebus-sql, servicebus-emulator, servicebus-ready), `servicebus-config.json`, `README.md`, `.env.example`. No Dockerfile, no deployment manifest, no collector config exists in the repo. |

### Overall difficulty

**Moderate, and cheaper now than it will ever be.** The delivered edge code is thin: 3 routes, one token verifier, one Redis adapter with a working prefix seam (`redis_cache.py:109-119`), a Service Bus adapter that sets two application properties, a container with four fields and no wiring of Redis, Service Bus, secrets or senders at all (nothing sets `app.state.secrets` or `app.state.cache`; grep finds no process entry point). Most of the tenancy work is in code that is **not built yet** (I03, I04, I05, I07, I08, I10, I13, L01, U10, R15, O01), where a tenant-aware prompt costs almost nothing, against retrofitting after delivery.

Hard parts, in order:
1. The unauthenticated entries that arrive with no tenant: link tokens, pairing codes, text-code requests, push (section 10).
2. Every cache and channel name in delivered code is global today, and two of them are active leaks: the board cache key `board:v1` (`application/use_cases/board_projector.py:31`) and the `board.updates` channel (`application/ports/outbound/cache.py:12`) would show one tenant's board and live events to another.
3. Workers must iterate tenants (outbox relay, scheduler) or bind per message (consumers). The consumer framework on the I04 branch has no tenant concept.
4. Observability policy (metric labels, small-group suppression) was written for one tenant.

Estimated total in section 11: 137 hours over 32 tasks (107 over TEN-C01 to C25, 30 added for the network scope of DEC-132), about 55 of them on edges that are not yet built.

---

## 2. HOW THE TENANT ENTERS EACH EDGE

Legend: V = verified source. "Fail" = what happens when no tenant can be established. Every failure must be fixed-message, fail closed and leak no existence.

| # | Entry point | Verified source of the tenant | Fail closed behaviour required | What must change (file:line today) |
|---|---|---|---|---|
| 1 | FHIR REST routes (`/fhir/*`, `/events`) | New `tenant` claim in the signed bearer token. The token is HS256 and checked in `domain/rules/bff_token.py:63-79`; the claims are read at `:128-160` (`sub`, `role`, `services`, `device`, `exp`). No tenant today. | Missing or malformed `tenant` claim, or a tenant that is unknown or suspended in the directory: `TokenRejected` then the existing 401 `login` body (`errors.py:106-108`, fixed text `LOGIN_TEXT`). Never a 404 that distinguishes "wrong tenant" from "bad token". | Add `tenant: str` to `BffClaims` (`bff_token.py:32`), encode (`:48`) and decode; add `tenant_id` to `Actor` (`application/actor.py:9`); `actor_from_claims` (`auth.py:37`); bind in an **async** dependency (note: `current_actor` is a sync `def`, `auth.py:82`, so FastAPI runs it in a threadpool and a `ContextVar.set` inside it is lost; binding must happen in an async dependency or ASGI middleware, and must be proven to reach the endpoint and any threadpool code). |
| 2 | `GET /health`, `GET /fhir/metadata` | None. Both are unauthenticated and tenant-free by design (`app.py:47`, `capability.py:456`). | Must stay tenant-free: no query, no bound tenant. Add them to the explicit global allowlist so the "every route binds a tenant" test knows they are exempt. | Add an allowlist. `/fhir/metadata` advertises resource types; per-tenant capability (profiles, enabled resources) would be a later change and is not needed now. |
| 3 | `GET /events` (SSE) | Same bearer claim. Roles `wall, advisor, clinical, lead, exec` (`routes_events.py:36`). | Same as row 1. | **Leak today:** the handler subscribes to the single global channel `board.updates` (`routes_events.py:162`). The message carries `service_id` and `at` only (`board_projector.py:142`), so tenant B's open pages would receive tenant A's board events (service ids and times). Channel must be `diucs:<tenant>:chan:board.updates`. Compute the channel eagerly in the handler: `StreamingResponse` iterates in a later task, after request-scoped context may have been reset. |
| 4 | Bearer token for a wall screen | Claim `tenant` stamped by the BFF from the device record at pairing (see row 12). `sub` is the device id (`auth.py:38-45`). | A device token whose device record is not in the claimed tenant fails the same way as an unknown device. | BFF mint (W09 prompt) and R02 tests; `issue_test_token` (`adapters/testing/tokens.py:18`) gains `tenant`. |
| 5 | BFF session cookie (W02 branch) | The cookie is a sealed JWE (`dir`, `A256GCM`) holding `{role, services, sub, device, backendToken, expiresAt}` (`session.ts:23-31,69-76`). Tenant must be added to `Session` and sealed, and the `backendToken` it carries has the tenant claim. The BFF never trusts a tenant from a header, query or body. | `unsealSession` already returns null for any malformed payload (`session.ts:94-118`); a session with no `tenant` must return null (re-login). | `Session.tenant` (`session.ts:23`), `sealSession` (`:69`), `unsealSession` (`:103-114`), `GET /api/bff/session` response (`route.ts:14-17`, should return the tenant slug for display only), `docs/spec/contracts.md:146` Session type. W02 is in flight (DEC-130 item 10 lets it finish; the sweep migrates it). |
| 6 | Inbound SMS webhook `POST /webhooks/sms/twilio` (I07, planned) | DEC-131 item 2: `To` plus `AccountSid` looked up in tenant config, then the signature is verified with that tenant's subaccount auth token, then the tenant is bound. Full flow in 2A below. | Unknown number, `AccountSid` mismatch, tenant suspended: fixed 200 empty TwiML, log the MessageSid only. Signature failure: 403 fixed message, nothing queued. Secret missing: 500, alert, nothing queued. | I07 prompt (`docs/plan/prompts/I07.md`) is written for one tenant: global `PhoneHasher`, global `diucs:idem:sms:<MessageSid>`, one `auth_token`, queue message without tenant. Amend per 2A. |
| 7 | SMS delivery receipt `POST /webhooks/sms/twilio/status` (I07) | `AccountSid` looked up in tenant config, signature verified with that subaccount's token, tenant bound, then `MessageSid` matched inside the tenant (DEC-131 item 2). | Unknown `AccountSid`: 200 empty (nothing to retry); bad signature: 403. | `parse_status_callback` (`sms_twilio/twilio_sms.py:69-78`) returns `DeliveryUpdate(sid, status, error_code)` with no account; add `AccountSid` to the result or parse it in the route. Queue message id `MessageSid:MessageStatus`, tenant property. |
| 8 | Inbound email | None exists. Email is outbound only (`email_smtp/smtp_email.py`, role inboxes, `Auto-Submitted` header at `:65`). There is no inbound mail path, no reply handling and no bounce parser in code or prompts. | n/a | Note for the owner: DEC-131 item 1 gives each tenant its own sender identity; replies and bounces to that identity go nowhere. If a bounce webhook is ever added, it needs the same lookup-verify-bind flow as SMS. |
| 9 | Service Bus consumers (I04 runner, I08, I10, I05, U09, others) | The application property `tenant` on the message, validated against the tenant directory before the unit of work opens. Today the runner reads only `event_type` and `session_id` (I04 branch `servicebus_runner.py:63-83`) and `BusMessage` has no tenant field (`application/ports/outbound/event_bus.py:29-34`). | Missing, malformed or unknown tenant property: dead-letter with the fixed reason `tenant missing or unknown`, no payload text, no processing. A suspended tenant: abandon is wrong (it loops); dead-letter with a fixed reason, or complete and drop, an owner choice (section 10). | `BusMessage.tenant_id`; `to_service_bus_message` (`service_bus.py:25-37`) writes `tenant`; `to_bus_message` reads it; `IdempotentConsumer.handle` (I04 branch `consumer.py:51-65`) binds before `uow_factory()` and the Processed marker (`:54`) is then tenant-scoped. Trust note: application properties are not signed. The trust boundary is Service Bus send permission. See 5.4 for an optional signed tenant property. |
| 10 | Scheduled-work worker (I05, planned) | The `tenant` property of the `ScheduledWorkDue` message (the relay copies it from the tenant's outbox row). | `ScheduledWork` not found in the bound tenant: `PermanentError` (I05 prompt rule), which for a wrong tenant property is the correct fail-closed outcome. | I05 prompt: the dispatch table is built once in the container, with no tenant in the signature `(message, uow)`. The handler context must read the bound tenant, never `message.payload`. |
| 11 | Outbox relay (I03, planned) | The relay is not a request and has no token. Its tenant list comes from the tenant directory (Neo4j `Tenant` nodes, a global allowlisted statement). It binds each tenant in turn and relays that tenant's rows. | A tenant whose bind or lock fails is skipped this round with a per-tenant backoff; other tenants continue. | I03 prompt: lock `outbox-relay` becomes `diucs:<tenant>:lock:outbox-relay`; fencing high-water mark is per tenant (L118, L125). `OutboxRelay(uow_factory, bus, cache, clock)` needs a `TenantDirectory`. See 5.5. |
| 12 | Wall-screen pairing (R15, U10, planned) | Split. `POST /screens/pairing` is unauthenticated (R15 prompt): the screen has no tenant. The tenant is bound at `POST /screens` from the lead's token (role `lead`, tenant claim). The device token returned by the claim call carries the tenant because the device record was created in the lead's tenant. | A wrong code and an expired code keep the same 404 (R15 prompt). A code that exists but belongs to a pairing already confirmed in another tenant also gets that 404. | U10 stores two link-token records at `StartPairing` before any tenant exists (U10 prompt). Needs a decision: store the unclaimed pairing in Redis under a reserved platform namespace (`diucs:_:pair:<code_hash>`, TTL 10 minutes, losable by design) and write the Neo4j Device only at confirm, in the lead's tenant. See 10, risk 6. |
| 13 | Wall-screen device credential (planned) | Device token hash lookup, global allowlisted statement `find_by_token_hash` (U10 prompt) returns `{deviceId, tenantId}`; the BFF mints the bearer from it. | Unknown or revoked: 401 `login`. | U10 `DeviceRegistry.find_by_token_hash(hash)` is tenant-less; mark it a global statement (DEC-130 item 3 allowlist) and have it return the tenant. |
| 14 | Link token pages (L01, L02, planned): `GET/POST /links/{token}`, `/renew` | The token itself. Token hash is `HMAC-SHA256(link-token secret, token)` (`domain/rules/tokens.py:94-99`), looked up by `LinkTokenService.resolve` (`application/ports/outbound/tokens.py:55-61`), which has no tenant. A global allowlisted statement `Q-LINK-GET-GLOBAL(tokenHash)` returns the record **with its tenantId**, then the tenant is bound and every further read is tenant-scoped. | Unknown, malformed, used, expired: the existing uniform 410 `{state}` (L01 prompt). A token whose tenant is suspended: the same 410. | See 3.5 and 10. The SMS link is `<link_base_url>/<token>` (U03 branch `send_prompts.py:216`), 22 characters of token. Recommended: do **not** put a tenant slug in the link (SMS length, `sms_segments` in `domain/messages/sms_length.py`); resolve by hash. |
| 15 | Reporter app text code request `POST /identity/code` (R11, U25, planned) | **Unresolved.** The caller is unauthenticated and sends only a mobile number. A number can now be a reporter in two tenants (DEC-131 item 3), so the number alone does not name a tenant. | Always 202, same body, whether or not the number is known (R11 prompt). Must stay true when the tenant hint is missing or wrong. | Needs an owner ruling on a pre-authentication tenant hint (host name or path). See 10, risk 3. |
| 16 | Reporter PIN and sessions (I13, planned) | After code verify, the BFF seals a session whose backend token carries the tenant. Redis session ids are 256 bits (I13 prompt). | Session id unknown under the token's tenant: 401. | `diucs:<tenant>:sess:<id>`; the tenant for the lookup comes from the token, never from the cookie id. |
| 17 | Push subscription and notification click (I14, R11, planned) | Subscription is stored by an authenticated route (tenant claim). The click opens the PWA, which must route to a tenant. | n/a | VAPID keys are bound to a subscription (browser rule, not verified here): one origin cannot hold two subscriptions with different keys. Use one platform VAPID key pair and tenant-tagged notification URLs. See 10, risk 7. |
| 18 | Support console (R18, O06, O07, planned) | Support staff are platform principals. They redeem a **support code**; the code's hash resolves (global allowlisted statement) to `{tenantId, sessionId}`, and access is bound to that tenant for the access window only. A ticket path is approved by a `lead` of the person's tenant. | Wrong, expired or revoked code: the single 403 "That code is not valid or has expired." (R18 prompt). | DEC-130 item 8: no role holds cross-tenant access yet. This design makes the privilege "redeem a code across tenants", each redemption audited in the tenant's chain. See 3.6. |
| 19 | Telemetry ingest (O04 collector) | OTLP from the BFF and back end. `tenant.id` is a span, log and metric attribute stamped by our code after binding, never read from browser-supplied attributes. | A browser span claiming a `tenant.id` is overwritten by the BFF (it knows the session's tenant) or dropped. | O04 allow-list file `infra/otel-allowlist.txt` (not yet created). See 7. |

### 2A. Inbound SMS webhook: exact flow (DEC-131)

Twilio posts form fields including `To`, `From`, `Body`, `MessageSid`, `AccountSid`. (Twilio's field list and `AccountSid` being the owning subaccount are taken from the I07 prompt and DEC-131, not verified against Twilio's documentation here; confirm before building.)

1. **Parse.** Read the form with a body size cap. Not a form, or no `To`, `MessageSid` or `AccountSid`: respond as an unknown number (step 4). No tenant is bound; no query runs yet except the directory lookup.
2. **Normalise `To`.** Use a plain E.164 normaliser. Do **not** use `to_e164_uk` (`twilio_sms.py:53-66`): it rejects anything that is not a UK mobile, and a tenant's Twilio number may be another type. Likewise `normalise_uk_mobile` (`application/ports/outbound/identity.py:38-56`) on `From` refuses non-UK senders with `ValidationFailed`; that must become "unknown sender, 200 empty", not a 500.
3. **Look up (global, allowlisted, read-only).** `TenantDirectory.by_inbound_number(to_e164)` returns the tenant channel config, and the route requires `config.subaccount_sid == AccountSid`. The directory is the only code that runs before a tenant is bound and it returns config only (no person data). It must not use `run_query` with an unbound tenant except through the allowlisted statement.
4. **Unknown number, `AccountSid` mismatch, tenant suspended, number released:** HTTP 200, `Content-Type: text/xml`, body `<?xml version="1.0" encoding="UTF-8"?><Response/>` (byte-identical to the success body), log `MessageSid` only (the number is never logged, matching `twilio_sms.py:5-6`). Nothing queued.
5. **Verify.** `secrets.get(config.secret_ref)` returns that subaccount's auth token. Compute `base64(HMAC-SHA1(token, public_url + sorted params))` where `public_url` comes from settings, not from the proxy-visible URL (I07 prompt rule), compare in constant time. Failure: 403 with a fixed body, nothing queued. A `NotFound` for the secret: 500 (configuration fault), alert, nothing queued. The auth token is never put on a node, in a log or in an error (DEC-131 item 4).
6. **Bind.** `bind_tenant(config.tenant_id)` for the rest of the request.
7. **Replay.** `SET diucs:<tenant>:cache:webhook:sms:<MessageSid> 1 NX EX 86400` (prompt says `diucs:idem:sms:<sid>`, which sits outside the four key families of DEC-089 item 7 and collides in shape with R03's `idem:<sub>:<key>` when `sub` is `sms`; rename).
8. **Allow-list.** Hash `From` with the **tenant-derived** phone hasher (3.7), look it up with `find_by_phone_hash`, which today raises `Conflict` for two active people on one phone (`graph_store/person_repository.py:341-344`, DEC-065). In the webhook a `Conflict` must become "unknown, 200 empty", not a 500.
9. **Queue.** `BusMessage(id=MessageSid, topic="inbound.replies", event_type="SmsReceived", tenant_id=<bound>, payload=...)`. The Service Bus `message_id` is `MessageSid` (globally unique, so `inbound.replies` duplicate detection, `servicebus-config.json:17`, cannot drop another tenant's message).
10. **Respond** 200 TwiML immediately.

### 2B. Tenant channel config the webhook (and senders) need

Stored on a `Tenant` node (or a `TenantChannel` node joined to it), **not** in env or Settings. Secrets are references only.

| Field | Purpose | Notes |
|---|---|---|
| `tenantId` | key | validated `[a-z0-9][a-z0-9-]{1,30}`; no `:`, `*`, `?`, `[`, `]`, `\`, whitespace; reserved prefix `_` for platform |
| `status` | `active`, `suspended`, `offboarding` | suspended: webhooks answer as unknown, workers skip, token verify fails |
| `twilioSubaccountSid` | `AccountSid` match, outbound basic-auth user | unique across tenants (unique constraint on this global label) |
| `twilioSecretRef` | secret-store name of the subaccount auth token | never the token; `FixedSecretStore` in tests |
| `numbers[]` | E.164 numbers owned by the subaccount: `{e164, role: sender or inbound, activeFrom, releasedAt}` | `e164` unique across all tenants; history kept (number reassignment, below) |
| `primarySenderE164` | `From` for outbound | one number per tenant at first |
| `statusCallbackUrl` | optional override; default is `base_url` plus `/webhooks/sms/twilio/status` | |
| `emailFromAddress`, `emailFromName`, `emailSecretRef`, `emailProvider` | per-tenant sender identity (DEC-131 item 1) | provider decided under DEC-003 when I09 is revisited |
| `displayName` | brand in SMS and email text | see 6.3 |
| `entraTenantId` | maps staff sign-in to this tenant | unique across tenants; see 3.3 |
| `smsDailyCap` | spend guard [ASSUMED] | see 9 |

### 2C. Failure modes the owner named

| Mode | Behaviour | Test that proves it |
|---|---|---|
| Unknown number | 200 empty TwiML, log MessageSid, no queue, no Neo4j read of person data | two-tenant fixture, post to an unregistered `To` |
| `AccountSid` does not match the number's subaccount | treated as unknown number (not 403), so a probe learns nothing extra | post a registered `To` with another tenant's `AccountSid` |
| Signature failure | 403 fixed body; checked against the **resolved** tenant's token, so tenant A's valid signature on a message addressed to tenant B's number fails | sign with A's token, address B's number |
| Number reassigned | see below | |
| Suspended tenant | as unknown | |
| Secret missing | 500, alert | |

**Number reassigned.** If number N moves from tenant A to tenant B (or Twilio recycles a released number), a late reply to a prompt A sent from N now resolves to B. At best the sender is unknown to B and is dropped silently; at worst the sender is also a B reporter and a B prompt is open, and the reply is applied to B's service. Controls: (a) `numbers[].e164` unique across all tenants, enforced by a constraint on the global directory; (b) a quarantine on release: no number is reassigned or released at Twilio for [ASSUMED] 7 days, longer than any reply window (prompt window 30 minutes, booking window 10 minutes, link validity to reply-by); (c) number history kept with `releasedAt`, so a reply `received_at` before a reassignment can be traced; (d) the human-only runbook for moving a number states these steps.

One observation on DEC-131 item 2 as written: an unknown number returns 200 and a known number with a bad signature returns 403, so an unauthenticated caller can learn which `To` numbers are registered. Numbers are not secret (every reporter sees one), so I rate this low and recommend accepting it. The alternative is to return 403 for both, at the cost of Twilio logging errors for genuinely unknown numbers.

---

## 3. TOKENS AND AUTH

### 3.1 Claims and signing today (R02, DEC-094 to DEC-098)

- HS256 JWT, stdlib codec in `domain/rules/bff_token.py`. Claims: `sub`, `role` (one of the ten `Role` values), `services` (list of service ids), optional `device`, `exp` (int). Parsed at `:128-160`. Max length 8192 (`:24`); secret at least 32 bytes (`:23`, `:86-88`); algorithm pinned (`:73`); signature compared before the payload is parsed (`:75-79`).
- No `iss`, `aud`, `kid`, `nbf`, revocation (DEC-094 item 4).
- The secret is read from `request.app.state.secrets` under `bff-jwt` (`auth.py:71-78`, DEC-096). Nothing on main sets it.
- "Scope list": R02 has no scope list claim. `services` is the only scope. Service-wide roles (`lead, advisor, clinical, audit`) ignore it (`auth.py:30,104-108`); `owner` and `exec` act only for listed services (DEC-098 item 4). `PATIENT_ROLES` (`:29`) and the `PROJECTIONS` registry (`:121`, reporter Task projection) are per role and tenant-independent.
- Both `refuse` paths are uniform: wrong role, wrong service and a missing record all return the same 404 body (`errors.py:135`, DEC-086 item 5). That property must hold across tenants: a record that exists in tenant B and is requested by tenant A is "not found", indistinguishable from absent.

### 3.2 Where `tenant` goes

- New claim `tenant` (string, required). Validated by the tenant-id regex in 2B, inside `_claims` (`bff_token.py:128`), before the `BffClaims` is built; absence or a bad shape is `TokenRejected` (the 401 `login` body). Add it to `encode_bff_token` (`:48-60`).
- `Actor.tenant_id` (`application/actor.py:9`) set by `actor_from_claims` (`auth.py:37-53`).
- After the signature check, an async dependency (a) looks the tenant up in the directory (status `active`), (b) binds the context variable, (c) asserts `actor.tenant_id` equals the bound tenant on every unit of work (defence in depth against a code path that builds an `Actor` by hand, such as `WALL_ACTOR` at `board_projector.py:46-48`, which is a constant with no tenant and must become per-tenant).
- `sub` becomes tenant-local. `scoped_key` rejects a colon in `sub` (`concurrency.py:105-110`); with a tenant prefix on the key that stays safe. Entra object ids are GUIDs with no colon.
- Cut-over: the token lifetime is 8 hours (W09 prompt), so a deploy that starts requiring `tenant` forces every session to re-sign-in once. Acceptable before pilot.
- Not recommended: per-tenant HMAC secrets. The BFF holds every secret anyway, so a BFF compromise is every tenant either way. A better blast-radius reduction (asymmetric signing, BFF signs and API verifies) is independent of tenancy and is not proposed here.

### 3.3 Staff sign-in (W09) and exactly one tenant

W09 prompt (`docs/plan/prompts/W09.md`): Auth.js with `MicrosoftEntraID`, env `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, role from the Entra `roles` claim, `sub` = Entra `oid`, token HS256 with `BACKEND_JWT_SECRET`, 8 hours.

Problems and answers:
- **Name clash.** `ENTRA_TENANT_ID` is a Microsoft directory id, not a DIUCS tenant. Use `ENTRA_DIRECTORY_ID` in code and docs, or the word "tenant" will be wrong in half the reviews.
- **One Entra app for many directories.** Single-tenant app registrations cannot sign in users from another directory. Each DIUCS tenant (an ICB or SPA operator) will have its own Trust directory. Either register one multi-tenant Entra app (the `organizations` endpoint) or one app per directory with a provider per tenant. Mapping rule either way: the **verified ID token's `tid` claim** looks up the DIUCS tenant (`Tenant.entraTenantId`, unique across tenants); no match: no session, the existing "Your account does not have access" page. The user never chooses a tenant.
- **Exactly one tenant per sign-in.** A person in two directories signs in twice and gets two sessions. There is no in-session tenant switch (a switch is a re-authentication). Staff `oid` values are per directory, so `sub` is already unique per tenant.
- **Multi-tenant users.** In today's code and prompts nobody belongs to two tenants: `Role` values are global, the practitioner id is a FHIR id, and DEC-130 item 6 maps a staff user to exactly one tenant. The only realistic overlap is a reporter's mobile in two tenants (DEC-131 item 3), handled as two Person records. Contractors and clinical advisors who work for two ICBs are the likely real case; they need two accounts or guest accounts, one per directory. This is an owner confirmation, not a build question.
- **Role mapping is per directory.** App roles are assigned in each directory's enterprise application; `DIUCS.Support` (W09) must not be honoured from a customer directory (3.6).
- Secret naming: `BACKEND_JWT_SECRET` (frontend) must equal the secret stored as `bff-jwt` (backend). Two names for one value is a rotation hazard. Pick one name.

### 3.4 BFF session (W02)

Sealed JWE cookie, `SESSION_SECRET` base64 of 32 bytes (`session.ts:35-48`), no server-side revocation (DEC-125 item 10). With multiple tenants: one cookie, one tenant, `SameSite=Strict`, no `Domain` attribute (DEC-125 item 9), so a per-tenant subdomain would get its own cookie jar. That is good isolation if tenants get subdomains and is neutral otherwise. The `diucs_csrf` cookie is not tenant-bound and does not need to be.

### 3.5 Link tokens, pairing codes, support codes (issuance)

- **Link token** (`rules/tokens.py:87-99`): 128 bits, HMAC-SHA256 with the global `link-token` secret. Issued in the tenant's unit of work (U03 branch factory pattern, DEC-115 item 1) so the record carries `tenantId`. Resolution is the only place a lookup runs before a tenant is bound; see row 14. Keep the global secret (a per-tenant secret would force the tenant into the URL).
- **Pairing code** (`rules/tokens.py:111-118`): 6 digits, 10 minutes (`:32`, `:36`). 10^6 values for **all** tenants at once; `StartPairing` must retry on collision against the global pending set. Confirm is rate limited per lead (brute force across 10^6 values by a signed-in lead of any tenant binds a stranger's screen to their tenant; impact is a mislabelled screen, not data exposure, because the screen reads only that tenant's board).
- **Support code** (`:135-143`, 8 characters from a 31-letter alphabet): redeemed across tenants as in 3.6.
- Text codes (`CODE_VALID_FOR` 10 min, `CODE_MAX_TRIES` 5, resend 60 s, `identity_policy.py:22-24`): key by tenant plus phone hash; the tenant for the key is the open question in 10 (risk 3).

### 3.6 Support and cross-tenant privilege

DEC-130 item 8: no role holds it. Proposal consistent with that and with O06/R18:
- The `support` role exists only on **platform** principals (Microsoft directory of the operator, never a customer directory) and is rejected on any token whose `tenant` is a customer tenant. Platform staff have `tenant = "_platform"` and can call nothing tenant-scoped.
- The one cross-tenant action is "redeem a support code". The code hash resolves, through a global allowlisted statement, to `{tenantId, uiSessionId}`. Redemption creates a `SupportAccess` node and an audit entry **in that tenant's chain**, and returns a short-lived token with `tenant = <target>`, role `support`, `exp` at most the 1 hour access window (O06 prompt). The person sees the open in their own tenant ("14:02 by [Support role]").
- Engineering trace access (R18 `GET /support/traces/{traceId}`) reads Azure Monitor, not Neo4j, so it needs its own guard: the KQL always filters `tenant.id` to the access's tenant (7.4).
- A platform-wide aggregate view for engineering (error rates by tenant) is a different privilege and should be named separately (`platform-ops`), read-only, over metrics only.

### 3.7 Phone hash

`HmacPhoneHasher` (`application/ports/outbound/identity.py:28-35`) uses one global key (`phone-hash`) over the national number. The same phone is therefore the same hash in every tenant, which links two Person records across tenants in any database dump. Derive the key per tenant (`HMAC(master, "phone-hash:" + tenant)` or HKDF) and have `hash()` read the bound tenant. Cost: the hasher stays a one-argument port; tests must bind a tenant. There is no production data yet, so no migration. Same for `code-hmac` and `link-csrf`.

---

## 4. REDIS

### 4.1 Today (verified)

The adapter prefixes everything with `diucs:` (`cache_redis/redis_cache.py:20`) and has a constructor `key_prefix` (`:109`, `from_url :115`), used by every test to isolate runs (`backend/tests/contract/factories.py:97`, `backend/tests/integration/adapters/outbound/cache_redis/test_redis_cache.py:27-33`). Families: `cache:{}`, `lock:{}`, `fence:{}`, `chan:{}` (`:21-24`).

| Key or channel | Written by | TTL | Tenant today |
|---|---|---|---|
| `diucs:cache:board:v1` | `BoardProjector` (`board_projector.py:31,135,158,168`) | 60 s (`:33`, [ASSUMED]) | **none: one board for everyone. Active leak the moment two tenants exist.** |
| `diucs:chan:board.updates` | `BoardProjector.publish` (`:142`), `GET /events` subscribe (`routes_events.py:162`) | none (pub/sub) | **none** |
| `diucs:cache:idem:<sub>:<key>` | `ReplayCache` (`concurrency.py:105-110,127,154`) | 24 h (`:33`) | `sub` only. Two tenants can share a `sub` string (a practitioner id is a tenant-local FHIR id), and then a replay in tenant A could answer tenant B's create with A's stored response body. |
| `diucs:lock:<name>`, `diucs:fence:<name>` | `acquire_lock` (`redis_cache.py:146-158`); no caller on main | lock: caller TTL (relay: 30 s); fence: never expires | none |

Planned (prompts): `diucs:sess:<id>` (12 h sliding), `diucs:sess-by-person:<practitioner_id>`, `diucs:code:<phone_hash>:<purpose>` (10 min), `diucs:idem:sms:<MessageSid>` (86400 s, I07), `diucs:cache:travel:<site>:<district>` (24 h, I15), rate-limit counters (I13 `allow(key, limit, window)` via `INCR`+`EXPIRE NX`), presence heartbeat keys (U40/P18), link-token lookup cache (architecture.md:14), reference-data cache (architecture.md:17), lock `outbox-relay` 30 s (I03).

### 4.2 New shapes

Every tenant key is `diucs:<tenant>:<family>:<name>`, where `<tenant>` matches the tenant-id regex in 2B (no `:` and no glob characters, so `diucs:a:` can never be a prefix of `diucs:ab:` and `SCAN MATCH` cannot be injected).

| Old | New |
|---|---|
| `diucs:cache:board:v1` | `diucs:<t>:cache:board:v1` |
| `diucs:chan:board.updates` | `diucs:<t>:chan:board.updates` |
| `diucs:cache:idem:<sub>:<key>` | `diucs:<t>:cache:idem:<sub>:<key>` |
| `diucs:lock:outbox-relay` / `diucs:fence:outbox-relay` | `diucs:<t>:lock:outbox-relay` / `diucs:<t>:fence:outbox-relay` |
| `diucs:sess:<id>` | `diucs:<t>:sess:<id>` |
| `diucs:sess-by-person:<practitioner>` | `diucs:<t>:sess-by-person:<practitioner>` |
| `diucs:code:<phone_hash>:<purpose>` | `diucs:<t>:code:<phone_hash>:<purpose>` (the hash is itself per tenant, 3.7) |
| `diucs:idem:sms:<sid>` | `diucs:<t>:cache:webhook:sms:<sid>` |
| `diucs:cache:travel:<site>:<district>` | `diucs:<t>:cache:travel:<site>:<district>` |
| rate limits | `diucs:<t>:rl:<name>` |
| presence | `diucs:<t>:presence:<practitioner>` |
| unclaimed wall pairing (tenant-less) | `diucs:_:pair:<code_hash>` (reserved platform segment `_`, TTL 10 min) |
| unauthenticated source-IP limiter | `diucs:_:rl:ip:<hash>` |

Where the prefix is built: the cleanest seam is a tenant-aware cache, not a change to every caller. Two options:
- (a) `TenantScopedCache` wrapper in the adapter layer: implements `Cache`, reads the bound tenant on each call, delegates to `RedisCache` with `key_prefix` computed per call. Callers (`BoardProjector`, `ReplayCache`, relay) do not change; the Redis adapter's `_key` (`redis_cache.py:118-119`) takes a prefix argument per call instead of a constructor value. **Recommended**: it makes a missing tenant a hard error in one place (same fail-closed rule as `run_query`), and it fixes the leaks without editing the callers.
- (b) Pass `tenant` through the port. Rejected: every caller and both fakes change and a caller can forget it.

Subscriptions need care: `subscribe` computes its channel when called (`redis_cache.py:136-144`), so the SSE handler must call it inside the bound context (row 3).

### 4.3 TTLs, fencing, rate limits

- TTLs stay as listed in 4.1; none depends on the tenant.
- **Fencing (DEC-091, L118, L125).** Token = `max(INCR, host clock µs)` (`redis_cache.py:28-32,146-158`). Per tenant counter `diucs:<t>:fence:<name>`. The rule "a writer must refuse a token lower than the highest it committed, held in Neo4j" must be per tenant: the high-water mark lives on the tenant's outbox head node, not in a global. Offboarding a tenant and deleting its `fence:` keys must not reset the Neo4j mark. `InMemoryCache` still issues 1, 2, 3 per lock name (`adapters/testing/memory_cache.py:104-112`); the wrapper must key `_last_token` and `_holders` by tenant too, or two tenants share a fake lock in tests.
- **Rate limits and attempt counters (I13).** The fast throttle is per tenant (`diucs:<t>:rl:code:<phone_hash>`). Durable PIN lock stays on the Neo4j credential (I13 prompt), which is tenant-scoped by DEC-130. Pre-tenant endpoints (pairing start, code request without a hint, webhooks before lookup, link GET) need a platform limiter keyed by source address under `diucs:_:rl:`.
- **Sessions (I13).** `sess-by-person` "sign out of every phone" deletes within one tenant only.
- **Reference-data cache** (code systems are shared and read-only, DEC-130 item 5): may live under `diucs:_:cache:refdata:<name>` (shared). Service profiles (architecture.md:17 lists them as reference data) are **tenant data**, so they go under the tenant prefix.

### 4.4 Flush-by-prefix in tests

`tests/support/redis.py:6-10` `flush_prefix(client, prefix)` does `SCAN MATCH <prefix>*` then `DEL`. Today each run builds `diucs-contract-<uuid>:` or `diucs-integration-<uuid>:` (outside `diucs:`, so `test_redis_cache.py:94` still passes because that test uses a recording stub). With tenancy, a run creates a unique tenant id (DEC-130 item 9) and the prefix becomes `diucs:<tenant>:`; `flush_prefix(client, f"diucs:{tenant}:")` is exact because of the trailing colon. Note `DEL` does not remove pub/sub channels; those go with their subscriptions (the existing subscriber-count assertions already cover this). New contract cases needed: two tenants on one `RedisCache` and one `InMemoryCache`: same key, different value; publish in A not seen by B; lock held in A is free in B; fence counters independent; a call with no bound tenant raises.

`backend/tests/contract/test_redis_isolation.py:15` uses the literal key `diucs:cache:isolation-check:status` and must be rewritten to a tenant key.

Open sub-question: Azure's managed Redis offerings (architecture and observability name both, undecided) may run clustered. If so, multi-key operations need hash tags (`diucs:{<tenant>}:...`). Current Lua scripts are single key (`redis_cache.py:28-40`), so nothing breaks today. The braces change every key shape, so decide before the first key is written in production. I have not verified the clustering behaviour of either product.

---

## 5. SERVICE BUS

### 5.1 Current configuration (all in `infra/servicebus-config.json`, one namespace `sbemulatorns`, line 4)

| Entity | Kind | Line | Duplicate detection | Session | Other |
|---|---|---|---|---|---|
| `inbound.replies` | queue | 8 | **required**, window PT20S (17, 12) | no | TTL PT1H, lock PT1M, max delivery 10, dead-letter on expiry |
| `inbound.receipts` | queue | 22 | not required (31; PT20S set) | no | same |
| `scheduled.work` | queue | 36 | not required (45) | no | same |
| `capacity.events` | topic | 52 | not required (56) | subs: `board-projector`, `alert-evaluator`, `analytics-aggregator` all **require sessions** (69, 81, 93) | session id = service id (architecture.md:31) |
| `booking.events` | topic | 98 | not required (102) | no | subs `notifier`, `board-projector`, `advisor-stream`, `analytics` |
| `registration.events` | topic | 156 | no | no | subs `notifier`, `lead-queue-projector`, `analytics` |
| `criteria.events` | topic | 202 | no | no | subs `notifier`, `flag-maintainer` |
| `alerts.events` | topic | 236 | no | no | subs `notifier`, `escalation-timer`, `analytics` |
| `messages.outbound` | topic | 282 | no | no | subs `text-sender`, `email-sender`, `push-sender` (290, 302, 314) |

No subscription has a filter rule. The architecture text says "filter on event type" (booking) and "subscriptions filter on the channel" (messages.outbound, architecture.md:32,36) and the I10 prompt names subscriptions `sms`, `email`, `push` with SQL filters on `channel`; the config names them `text-sender`, `email-sender`, `push-sender` and filters nothing, so today every sender subscription would receive every message. Pre-existing gap, independent of tenancy, but it must be fixed in the same change that adds the tenant property.

Properties the adapter sets today (`service_bus.py:25-37`): `message_id`, `session_id`, `subject` = event type, `application_properties` = `event_type` and, when the payload has `channel`, `channel`.

### 5.2 Shared entities with a tenant property, or entities per tenant?

**Recommendation: one shared set of entities; `tenant` is a required application property on every message; session ids and message ids that are tenant-local are prefixed with the tenant.**

| Criterion | Shared + property | Per tenant |
|---|---|---|
| Entity count | 3 queues, 6 topics, 18 subscriptions, constant | 9 entities and 18 subscriptions **per tenant** (27 + 54 at 3 tenants) |
| Emulator | works as is; config is static JSON loaded at start (`infra/README.md` line "Queues, topics and subscriptions are recreated from servicebus-config.json on every start") | the config must be regenerated per test run and per tenant; the emulator's entity limits are not something I have verified, and 27 queues/topics and 54 subscriptions at 3 tenants may exceed them. Check the emulator's documented limits before ruling this out for sure. |
| Cloud provisioning | none per tenant | an infrastructure step per tenant; a failed provisioning leaves a tenant half-created |
| Consumers | one runner per subscription | one runner per subscription per tenant; a worker fleet that grows with tenants |
| Isolation | by convention and by the consumer's tenant check; message properties are not signed (5.4) | stronger: a consumer can only ever read its tenant's entity, and access can be granted per entity with RBAC (only if the platform uses entity-level roles; not verified) |
| Noisy neighbour | head-of-line effects on a shared queue; one tenant's burst delays another | isolated |
| DLQ privacy | one shared DLQ per entity mixes tenants | one DLQ per tenant |
| Ordering | `capacity.events` sessions keyed `<tenant>:<service>` keep per-service order | same |
| Cost | namespace-level | more entities, more idle receivers |

Why shared wins at this scale: the product is an NHS SPA tool with a small number of tenants and low volume (a few hundred prompts a day per tenant, not verified); the operating cost of per-tenant provisioning and the static emulator config outweigh the isolation gain. The isolation weakness is covered by (a) binding the tenant from the property before any work, (b) per-tenant unit of work scoping in Neo4j which makes a wrong tenant property unable to read another tenant's data, (c) per-tenant fairness in the relay (5.5). Revisit per-tenant **subscriptions** (not whole entities), with a correlation filter on `tenant`, only if one tenant's volume starts to starve others.

Mitigations for the shared design that must be built:
- **Fairness at the producer.** The relay round-robins tenants and caps each tenant's batch (5.5). Receivers use `max_concurrency` (default 4, I04 runner); a single tenant could occupy all slots. A per-tenant concurrency cap in the runner is optional.
- **Session id.** `session_id = "<tenant>:<service_id>"` for `capacity.events` (`ManualEventBus` demands a session id on that topic, `adapters/testing/memory_event_bus.py:15,49`). Ids are composite-unique per tenant under DEC-130 item 7, so service ids can repeat across tenants.
- **Message ids.** `MessageSid` (SMS) and UUID outbox ids are globally unique. `SequentialIds` (tests) and `cancel-<work id>` (`scheduling.py:86` on the U03 branch) are tenant-local. Send them as `<tenant>:<id>` so duplicate detection on `inbound.replies` can never drop another tenant's message, and so the I04 Processed marker is unambiguous in logs.
- **Cancel by sequence number.** `cancel(queue, sequence_number)` (`service_bus.py:81`) has no ownership check. Sequence numbers are per entity and global; the relay must read the number from the bound tenant's `ScheduledWork` node only (tenant-scoped read), so a bug cannot cancel another tenant's work.
- **TTL.** All entities have TTL PT1H with dead-letter on expiry. An outage over an hour dead-letters every tenant's backlog at once. Pre-existing; the DLQ rules below make it a cross-tenant event, so size the alert accordingly.

### 5.3 What a consumer needs to rebuild tenant context

1. The `tenant` application property (string, regex of 2B) and `event_type`.
2. A `TenantDirectory` lookup (cached) confirming `active`.
3. Bind the tenant context, then `uow_factory()`, then `processed.mark_if_new(message.id, consumer)` (tenant-scoped under DEC-130 item 7), then the handler.
4. The handler never reads the tenant from the body. The body may still include `tenant` for humans reading a dead letter; if so, the runner asserts body equals property or dead-letters (`tenant mismatch`).
5. The tracing hook already planned in I08 ("leave a hook for trace context from application properties", I08 prompt) takes `traceparent` from the same properties.

Runner changes (I04 branch `servicebus_runner.py`): `to_bus_message` (`:63-83`) reads the property; `_outcome` (`:119-124`) dead-letters on a missing or invalid tenant with `Outcome("dead-letter", "tenant missing or unknown")`; the `IdempotentConsumer` gets a `TenantBinder` constructor argument. Sessions: `NEXT_AVAILABLE_SESSION` receivers (`:142-153`) deliver one session at a time, and every message in a session shares the tenant by construction (the session id carries it); the runner still binds per message.

### 5.4 Optional: sign the tenant property

Anyone with send rights on the namespace can set any `tenant`. Defence: a `tenant_sig` property, `HMAC(master, tenant|message_id|event_type)`, checked by the runner. Cost: a secret in every publisher (relay, webhook) and every consumer. Not recommended for the pilot; revisit if send rights are ever granted outside our own processes.

### 5.5 Outbox relay, scheduled work

- Relay loop: for each active tenant from the directory, bind, take `diucs:<t>:lock:outbox-relay` (30 s), read at most `batch_size` pending rows, publish with the tenant on the message, mark published in the same tenant. Per-tenant backoff (I03 prompt: 1 s doubling to 60 s) so one tenant's failing publishes never slow the others. Tenants with nothing pending cost one cheap read each; with more than about 50 tenants consider a pending-tenants set.
- The fencing mark per tenant (4.3).
- Dead rows are logged by id and topic (I03 prompt); add `tenant.id`.
- `ScheduleWork`/`CancelWork` payloads (U03 branch `scheduling.py:57-70,84-91`) carry no tenant in the body, correctly; the relay adds the property.

### 5.6 Dead letters and the privacy rule

- Existing rule (I04 branch `consumer.py:12-14`): dead-letter reasons never contain payload text; a retry reason is the exception class name.
- **Message bodies are not clean.** The `SendMessage` outbox payload holds the rendered SMS or email text, including the live single-use link token (U03 branch `send_prompts.py:290-304`, DEC-115 item 9 says so). A dead-lettered `messages.outbound` message therefore holds a usable token until its reply-by time. In a shared DLQ, anyone who can browse it sees every tenant's tokens. Rules: (1) DLQ read access is restricted to named operators and never exported to tickets, chat or logs; (2) the re-drive tool takes the tenant from the property and refuses a message without one; (3) DLQ alert text carries `tenant.id`, entity and count only; (4) when a tenant is offboarded, its DLQ messages are purged by property; (5) consider rendering the link at send time in the sender (I10) instead of in the outbox body, so no token is ever in the bus. Option (5) is a design change for U03 and I10 and belongs to the owner.
- Dead letters are also a data-incident signal per tenant (each tenant is a separate controller for IG purposes, which I have not verified; check with the clinical safety and IG leads).

---

## 6. SMS, EMAIL AND TEXT CONTENT

### 6.1 Sender numbers and credentials (DEC-131)

- `TwilioSms` takes `account_sid, auth_token, from_number, status_callback_url` in the constructor (`sms_twilio/twilio_sms.py:94-106`) and posts with basic auth `(account_sid, auth_token)` (`:121-122`). It is already shaped for one subaccount. Build a `TwilioSmsRouter` implementing `SmsSender` that reads the bound tenant, gets the channel config (2B), fetches the token from the secret store by `twilioSecretRef`, and delegates to a cached `TwilioSms` for that tenant (one shared `httpx.AsyncClient`). The `SmsSender.send(to, text, message_id)` signature (`application/ports/outbound/messaging.py:52`) does not change.
- `RecordingSmsSender` (`adapters/testing/recording_senders.py:55`) records no tenant; add `tenant_id` to `RecordedSms` so tests can assert that tenant A's message left from A's number.
- A sender refusing a tenant with no configured number or no secret: `SendFailedError` (permanent, not retried), alert. It must not fall back to another tenant's number or a global default; remove `twilio_account_sid`, `twilio_auth_token`, `twilio_from` from `Settings` (`bootstrap/settings.py:32-34`) in production profile, keeping them only as test fixtures.
- The `_log` lines (`twilio_sms.py:124,130,133,137,139`) log `message_id` and `sid`; add the bound `tenant.id` via a logging filter, not at each call.
- `for _name in ("httpx","httpcore")` sets process-wide log levels (`:28-29`); unchanged.

### 6.2 Email

`SmtpEmail(settings)` has one host, user, password, one `email_from` (`email_smtp/smtp_email.py:115-121`), a fixed Message-ID domain `diucs.example` (`:26,126`). DEC-131 says per-tenant sender identity and credentials, product to be chosen under DEC-003. Needed now, before that choice: `EmailSender` is `send(to, subject, text, html)` (`messaging.py:55-56`); the adapter reads the bound tenant, loads `emailFromAddress`, `emailFromName`, `emailSecretRef` and sends with them. DKIM/SPF/DMARC and the Message-ID domain must follow the sending domain per tenant (not verified for any provider). `SmtpSettings` Protocol (`:77-83`) becomes per-tenant config. Recording sender: record the `from` used.

### 6.3 Templates and branding

- Templates hard-code the product name `DIUCS` in every SMS (`domain/messages/templates.py:97-105,111,219,229,278,286,293,298,321`), and the exec invitation says "Dorset urgent care capacity" (`:286`). Another tenant's reporter would be told they are looking at Dorset capacity. These are in `domain/messages` (not my scope) but the I09 and I10 outputs inherit them. Fix: a `brand` field (from `Tenant.displayName`) passed to `render`, keeping `DIUCS` as the platform prefix if the owner wants it. `catalogue.py` ids and field sets do not change.
- Booking template references SystmOne ("Referral details follow in SystmOne", `templates.py:112`). That is a Dorset assumption that may be false for another ICB; owner decision.
- `domain/privacy_guard.py` scans templates for patient data; extend the scan to fail on any literal place or organisation name in a template.
- Link host: `Settings.base_url = "https://diucs.example/"` is global (`settings.py:18`) and is passed to `SendPrompts` as `link_base_url` (U03 branch `send_prompts.py:158,216`). One host for all tenants is fine and keeps the SMS short. Per-tenant hosts would need the host in tenant config and the link resolver to accept it.
- Booking references: four digits, "unique among open bookings" (`domain-rules.md:165`); under DEC-131 item 3 unique per tenant. The 4-digit space (10,000) per tenant is not a new problem, but `new_reference(rng, taken)` must be given the tenant's open set only.

### 6.4 Delivery receipts to a tenant

DEC-131: `AccountSid` plus message id. `parse_status_callback` (`twilio_sms.py:69-78`) must also return `AccountSid`. The lookup is `TenantDirectory.by_subaccount(AccountSid)`; verify with that subaccount's token; bind; `CommunicationRepository.set_delivery_status(provider_message_id, status)` (`messaging.py:89`) then runs inside the tenant, so a receipt can only touch that tenant's Communications even if a sid were guessed. Twilio `MessageSid` values are unique across Twilio, so a tenant-scoped match on sid alone is safe once the tenant is bound.

### 6.5 Reply matching and a phone in two tenants

Solved by the channel for SMS (DEC-131 item 3): the reply arrives on tenant A's number and is matched only in A (allow-list by tenant-derived phone hash, open prompt by `latest_prompt_for_phone` in A, booking reference unique within A). What remains: (a) the two Person records for one human are unlinked by design (3.7), which is wanted; (b) the human sees two sender numbers and must reply to the right thread, which is a content question: every prompt names the service (`DIUCS: UCR West.`) and booking requests carry the reference; (c) a reply sent to the **wrong** number (to B's number about A's prompt) is processed in B, finds no open prompt and gets B's "unrecognised" help or nothing (D11 reply policy). That is correct and safe.

### 6.6 Remaining ambiguities (DEC-131 item 5)

See risk list in 10: link tokens, pairing codes, text codes, push, plus device credentials.

---

## 7. TELEMETRY AND LOGGING

Nothing is built yet (O01, O04, O07, O08 not started, no `adapters/outbound/telemetry/`, no `infra/otel-collector.yaml`). Spec: `docs/spec/observability.md`; prompts O01, O04, O07, O08.

### 7.1 Where `tenant.id` goes

- **Spans and span events:** yes, on every span, set by the same hook that binds the tenant (so a use case span, a `neo4j.query` span, a `redis.*` span, a `servicebus.*` span all carry it). The O01 allow-list rule "domain ids ending `.id`" (O01 prompt) already admits `tenant.id`; add it explicitly so a rename cannot drop it.
- **Resource attributes:** no. One process serves many tenants, so the tenant is per span, not per service instance.
- **Logs:** a logging filter adds `tenant.id` and `trace_id` from the bound context. Never log the Cypher text, parameters, numbers, message bodies, tokens or `AccountSid`/auth tokens. Unauthenticated paths (webhook before lookup) log `MessageSid` and no tenant.
- **Metrics:** observability.md says "Metrics are labelled by route template, role and outcome only. Ids go on spans" (line 68), and O01 repeats it. A per-tenant SLO and noisy-neighbour detection need a tenant dimension. Recommend amending the rule: `tenant.id` is permitted as a metric dimension while the tenant count is at most about 50 (I have not verified Azure Monitor's custom-metric dimension limits; check before enabling). Never `service.id`, `user.id` or `session.id` on a metric.
- **Servicebus spans:** add `messaging.destination.name` and keep the bound `tenant.id`. The span name `servicebus.process {topic}/{subscription}` is unchanged.
- **Redis spans:** `redis.{operation}` carries "key family (never the key)" (observability.md:61); with tenant-prefixed keys this rule becomes more important: the key now contains the tenant, and a session id or phone hash may follow. Keep family only.

### 7.2 What must never be logged or traced

Auth tokens, subaccount SIDs plus tokens, `SESSION_SECRET`, BFF tokens, link tokens (also those inside `SendMessage` bodies), phone numbers and phone hashes, pairing and support and text codes, session ids, postcodes, case references, free text, anything from the request body. Tenant **names** (as opposed to ids) are not patient data, but keep them out of metrics.

### 7.3 Collector and allow-list

`infra/otel-allowlist.txt` (O04, single list both configs are checked against) must contain `tenant.id`. The browser telemetry module (O02) must not set `tenant.id`; the BFF stamps it from the session so a user cannot label spans as another tenant. Sampling: tail sampling "always keep errors" is global; consider a per-tenant floor so a quiet tenant is never entirely unsampled.

### 7.4 Support-console reads (O07) and aggregates (O08)

- `TelemetryQuery` methods (`session_timeline`, `trace`, `search_sessions`, O07 prompt) must take the tenant from the bound context and add `tenant.id == <tenant>` to every KQL query, passed as a parameter. A cross-tenant search is a separate, audited privilege (3.6).
- Aggregate nodes (`FunnelDaily`, `FrictionDaily`, and so on, O08 prompt) carry `tenantId`. **The "groups under 10 sessions are hidden" rule (observability.md:150) applied per tenant will suppress almost everything for a small tenant** (the pilot is "a few services"). Owner decision: suppress per tenant (safer for staff privacy, but small tenants see nothing) or suppress on the platform total and show tenants their own numbers only above a lower floor. I recommend keeping the floor and telling tenants it applies to them.
- The platform-level view across tenants (engineering) exposes counts only.

### 7.5 Spec implications

`docs/spec/observability.md` is a source artifact and is not edited (DEC-130); the owner reconciles it in v1.1. Lines affected: 24-34 (add `tenant.id` to "attributes on every event and span"), 68 (metrics rule), 150 (aggregates floor), 171-175 (support access: per tenant and cross-tenant rules), 185-191 (collector allow-list).

---

## 8. COMPOSITION ROOT AND CONFIG

### 8.1 What exists

`bootstrap/container.py` `Container` has `clock`, `ids`, `neo4j`, `uow_factory` (`:32-39`); `build(settings)` (`:63-74`) and `build_for_tests(clock, ids, *, neo4j)` (`:77-94`). The comment at `:39` ("Each later task adds one field here") means Redis, bus, secrets, senders, geo and terminology are not wired yet. The API container Protocol is `ApiContainer` with `clock` and `uow_factory` only (`fhir_rest/app.py:22-30`); `secrets` and `cache` hang off `app.state` set by "the process that serves the app", and no such process exists on main. `tests/support/api.py:27-39` builds one container per test with `FixedClock(R01_TEST_NOW)` (`:23`).

### 8.2 What changes

1. **One process-wide container, per-unit tenant binding.** The container remains a process singleton (DEC-012: one driver per process). The tenant is not a container field. `uow_factory` stays `Callable[[], UnitOfWork]` (`application/ports/outbound/unit_of_work.py`), reads the bound tenant when the unit of work opens, and refuses with the fixed-message error if none (the same rule as `run_query` in DEC-130 item 2). Per-request wiring: the API dependency binds; the consumer runner binds; the relay and scheduler bind per tenant loop; tests bind via a fixture.
2. **New container fields:** `tenants: TenantDirectory` (Neo4j-backed, global allowlisted statements), `secrets: SecretStore`, `cache: Cache` (the `TenantScopedCache` of 4.2), `bus: EventBus`, `sms: SmsSender` (router), `email: EmailSender` (router), `tenant_binder`. `ApiContainer` gains `tenants`, `secrets`, `cache`; remove the `app.state.secrets`/`app.state.cache` convention (DEC-096) once the container carries them, so there is one wiring place.
3. **`build_for_tests`** gains a required or defaulted `tenant_id`, creates the tenant's directory row, and returns a container whose helper `bound(tenant)` is a context manager. It builds a **second** tenant on request for two-tenant tests (`build_for_tests(..., tenants=("t-a","t-b"))`). The R01 `test_container` fixture (`tests/support/api.py:27-39`) must yield both, and `api_client` must be able to send a token for either (`issue_test_token(..., tenant=...)`, `adapters/testing/tokens.py:18`).
4. **Settings.** Remove from production use: `twilio_*`, `smtp_*`, `email_from` (`settings.py:32-42`), because they become per-tenant secret references. Keep `base_url`, `redis_url`, `servicebus_connection`, `neo4j_*`. Add: `secret_backend` (vault vs env for dev), `tenant_directory_cache_ttl_s`. The `sms_provider: Literal["twilio","govuk-notify","none"]` (`:29`) is per-tenant now (a tenant could in principle use a different provider; DEC-131 fixes Twilio, so drop `govuk-notify`, which DEC-002 already cancelled).
5. **Secrets.** `SecretStore.get(name) -> bytes` is synchronous and tenant-blind (`application/ports/outbound/tokens.py:28-29`). Per-tenant secrets are looked up by reference name from the tenant record (`twilio/<tenantId>/auth-token` is a convention, not a node property). The port is enough; `FixedSecretStore` (`adapters/testing/fixed_secrets.py:9`) serves tests. A real vault adapter does not exist (human-only, DEC-096 item 3). Cache secrets in memory for a short TTL; never write them to a log or cause them to appear in `repr` (Settings uses `SecretStr`).
6. **Where per-tenant configuration lives.** A `Tenant` node (plus `TenantChannel` for numbers), in Neo4j, because DEC-001 makes Neo4j the system of record and config is a fact that must survive Redis loss. Not env (needs a restart and a deploy per tenant), not a separate config table (no second database, DEC-003 keeps Neo4j the only one). Fields: 2B, plus `timeZone` (default `Europe/London`) and `thresholds` (below). The tenant directory is the first global-allowlisted statement set (`Q-TENANT-GET`, `Q-TENANT-LIST`, `Q-TENANT-BY-NUMBER`, `Q-TENANT-BY-SUBACCOUNT`, `Q-TENANT-BY-ENTRA`) and belongs with auditor A's registry work.
7. **Time zone.** `domain/rules/london_time.py` hard-codes `Europe/London` and phone normalisation hard-codes UK mobiles (`identity.py:21,38-56`; `twilio_sms.py:35-39`). Every tenant is a UK NHS organisation and the UK has one time zone, so I recommend **not** making time zone configurable now. Keep the field in config, default `Europe/London`, unused. Making it live touches `schedule.py`, `opening_hours.py`, `alerts.py`, `criteria_workflow.py`, the reply parser's windows and `format_hhmm`, a domain-wide change with no current benefit.
8. **Thresholds.** The rule book has `[ASSUMED]` numbers (`GROUP_WINDOW`, `CORRECTION_WINDOW`, limited percentage per service, `MANY_CHANGES`, `REVERIFY_EVERY` 30 days at `identity_policy.py:26` against 180 in `domain-rules.md:241`). Only service-level values are stored per service today (`ServiceProfile.limited_level_percent`). Do not make platform constants tenant-configurable until a tenant asks; record the list in the open questions.
9. **Entry points.** There are none: no `__main__`, no `[project.scripts]`, no ASGI factory (`pyproject.toml` has no scripts; grep for `uvicorn` finds nothing in src). The first process entry (API, relay, consumers, scheduler) should be written tenant-aware, and each worker `python -m` entry from I03, I05, I08 and I10 builds its ports from the container.

### 8.3 Import rules

`.importlinter` forbids `adapters.*` importing each other and `application` importing adapters (`backend/.importlinter`). The tenant context type and binder live in `application/tenant.py` (pure, `contextvars` is stdlib); `graph_store.driver`, `cache_redis` wrapper and the API dependency import it from there. The Redis `TenantScopedCache` is an adapter and must not import `graph_store`; it gets its tenant from the application module only.

---

## 9. INFRA

| Area | Today | Assumes one tenant? | Change |
|---|---|---|---|
| `infra/docker-compose.yml` | Neo4j 5.26.32 Community (Community has one database, line 11), Redis 7.4.11 with append-only (`:26-33`), SQL Server and the Service Bus emulator 2.0.1 (`:40-69`), probe container (`:75-89`). Credentials local-only. No app containers. | Not in its content, but the **single Neo4j and single Redis** are the production shape too (DEC-130 puts tenants in one database). | Nothing structural. Document that tenant isolation is logical. The Redis `--appendonly yes` (DEC-091) is fine. Add nothing per tenant. |
| `infra/servicebus-config.json` | 3 queues, 6 topics, 18 subscriptions, one namespace, no filters | Entities are global, which is the recommended shape | (a) Fix subscription names and add filters per the I10 prompt (5.1); (b) keep PT1H TTL but flag the outage case; (c) no tenant entities. If the owner picks per-tenant entities, this file must be generated. |
| Env vars | 21 settings, 6 test/compose | `twilio_*`, `smtp_*`, `email_from` are single-tenant (`settings.py:32-42`) | Replace with secret references per tenant. Name the future env `DIUCS_SECRET_BACKEND`. Frontend: `ENTRA_TENANT_ID` renamed (3.3); `BACKEND_JWT_SECRET` equals `bff-jwt`. |
| Secrets | `FixedSecretStore` only; no vault adapter | n/a | A vault adapter is human-only. Needs naming: `bff-jwt`, `link-token`, `phone-hash`, `link-csrf`, `code-hmac`, VAPID key, `twilio/<tenant>/...`, `email/<tenant>/...`, `SESSION_SECRET`. Rotation story for `bff-jwt` and `phone-hash` (rotating `phone-hash` rehashes every phone: re-hash migration needed; `link-token` rotation invalidates live links, acceptable). |
| CI `.github/workflows/ci.yml` | Backend static job, full-suite job (`uv run pytest`, throwaway Neo4j per session, DEC-008), frontend, e2e | The full-suite job runs on one Neo4j and serially (`contracts.md:45`, "tests run serially"). DEC-130 item 9 allows parallel runs after the tenancy harness lands. | Add the two-tenant generated test to the full-suite job. Do not enable `pytest-xdist` until `clean_graph` is tenant-scoped (auditor A/D). The Redis and Service Bus suites share the compose Redis and emulator (`DEC-089 item 8`); tenant-prefixed keys make Redis safe to share, and a tenant property filter makes Service Bus tests safe to share, see below. |
| Service Bus contract tests | `backend/tests/contract/factories.py:124,216-240` drain shared queues; two sessions on one emulator can see each other's messages (lesson L127: topic cases take about 280 s) | yes | Tag every test message with the run's tenant and receive only that tenant's messages; unknown-tenant messages are left for their owner. |
| Smoke test | `backend/tests/integration/test_infra_up.py:160-165` sends `message_id="smoke-1"` and notes the 20 s duplicate window (`infra/README.md`) | n/a | The message needs a `tenant` property once the runner enforces one, or the smoke test uses the raw SDK and keeps its current shape. |
| Telemetry | no collector, no allow-list file | n/a | `infra/otel-collector.yaml` and `infra/otel-allowlist.txt` (O04) get `tenant.id`. |
| Deployment | **no Dockerfile, no manifests, no entry point.** | n/a | Out of repository scope today; each worker process (API, relay, consumers, scheduler) will need a tenant-aware start-up check (directory reachable, at least one active tenant or an explicit empty state). |
| Per-tenant resources | none exist | | Human-only per tenant (DEC-131 item 1): Twilio subaccount, numbers and sender registration, email identity, Entra directory mapping, a row in the directory. A tenant onboarding runbook and a `provision_tenant` script that creates only the Neo4j side (Tenant node, first lead invitation) is the first automation. |
| Backup and offboarding | not described | | One Neo4j holds every tenant. Per-tenant export, restore and **delete** need a design (a tenant's nodes, audit chain, outbox, Redis keys under `diucs:<t>:`, DLQ messages by property, telemetry by `tenant.id`). Note that a per-tenant restore from a whole-database backup is not straightforward on Community; flag for the owner. |

---

## 10. RISKS AND OPEN QUESTIONS FOR THE OWNER (ranked)

1. **Cross-tenant leaks already present in delivered code (certain, high).** The board cache key (`board_projector.py:31`), the live-update channel (`cache.py:12`, `routes_events.py:162`) and the replay-cache key (`concurrency.py:110`) are global. Any second tenant shows them immediately. They are small changes behind one wrapper (4.2) but they are the first thing a reviewer will test. Recommendation: land the `TenantScopedCache` before anything else on the edge.

2. **The unauthenticated entries that carry no tenant (high).** DEC-131 item 5 lists them; the audit adds detail.
   - **Link tokens** (`/links/{token}`, L01/L02, email links). Resolution by token hash through a global allowlisted statement. Risk: an enumeration oracle if the unknown, used and expired answers differ in time or body (they must not; L01 prompt already makes unknown look like expired). The token is 128 bits, so guessing is not the concern; **the DLQ and outbox bodies containing live tokens are** (5.6). Option: render the link at send time.
   - **Pairing codes.** A tenant-less pending record (row 12) and a 10^6 shared space. Recommend Redis `diucs:_:pair:` with TTL, device row written at confirm. Decision needed: is a Redis-only pending pairing acceptable (it loses a pairing on a Redis restart, and the screen shows a new code; DEC-001 allows it)?
   - **Device credentials.** Token hash lookup returns the tenant; same global-statement treatment.
3. **Text codes and reporter sign-in pre-authentication (high, needs a ruling).** `POST /identity/code` receives only a mobile number (R11 prompt). With one person's mobile in two tenants, the server cannot know which tenant's number to send the code from, or whose Person to verify. DEC-130 item 6 forbids taking the tenant from a request body, query or caller-controlled header. A pre-authentication hint is unavoidable: a tenant-specific host (`<tenant>.diucs...`), a path (`/t/<slug>/...`), or the tenant embedded in the invitation link and remembered by the PWA. Safe only because the credential check (code sent to the number registered **in that tenant**) runs entirely inside the hinted tenant and fails the same way when the hint is wrong. Ruling needed: "a pre-auth tenant hint from the host or path is allowed where the credential itself is verified inside that tenant." The invitation path (I1, 48 hours) can carry the tenant through the invitation token hash and avoids the problem for first sign-in; re-verification every 30 days and a new device are the cases that need the hint.
4. **Inbound SMS (resolved by DEC-131; residual risks, medium).** (a) Number reassignment and quarantine (2C). (b) The unknown-number versus bad-signature response difference reveals registered numbers (2C, low). (c) Everything before signature verification is attacker-controlled input: only the directory lookup may run, it must be a cache hit or one indexed read, and the unauthenticated path needs a platform rate limit by source address (a flood of random `To` values must not hammer Neo4j). (d) Twilio recycles numbers and the sender-ID regulatory side takes time (architecture.md:310): lead time per tenant. (e) Subaccount auth-token rotation: the secret reference needs a version so a rotation does not leave a window of 403s. (f) Spend: a runaway tenant (bug or abuse) can exhaust shared budget unless per-subaccount spend limits and `smsDailyCap` exist; subaccounts make this practical.
5. **Support and operator access (medium to high).** DEC-130 item 8 leaves it open. Unless decided, the support console (O06, R18, O07) cannot be built, and platform engineers have no sanctioned path to a tenant's data. Proposal in 3.6; needs the owner to confirm who holds `support` and that it is platform-only.
6. **Push (medium).** One installed web app, one origin, one subscription per origin and (browser rule, not verified) per VAPID key: a user in two tenants cannot hold per-tenant keys on one origin. Use one platform key pair; the notification click URL carries the tenant (path hint, as risk 3); a notification that arrives for a tenant the session is not signed in to must open a sign-in for that tenant, not another tenant's page. Needs the owner's view on single origin versus tenant subdomains (subdomains give separate service workers and cookie jars but need wildcard TLS and cookie handling).
7. **Shared infrastructure noisy neighbour (medium).** One Neo4j, one Redis, one Service Bus namespace. A tenant with a pathological import or alert storm slows all. Controls proposed: per-tenant fairness in the relay, per-tenant SMS cap, per-tenant rate limits at the API, per-tenant metrics (7.1). Not proposed: separate infrastructure per tenant, because Neo4j Community has one database and the owner has ruled one platform.
8. **Metrics cardinality and the small-group floor (medium).** 7.1 and 7.4.
9. **Message properties are unsigned (low to medium).** 5.4.
10. **Spec drift (low).** `architecture.md`, `contracts.md` and `observability.md` still describe one tenant and the I10 subscription names; the owner reconciles in v1.1 (DEC-130).
11. **Entra mapping assumptions (medium, needs confirmation).** One directory per tenant, `tid` maps to a tenant (3.3). If two tenants share a directory (for example an ICB and its provider collaborative on one Microsoft tenant), `tid` alone is ambiguous and a group or role claim has to pick the tenant. Ask which organisations are likely tenants and whether any share a directory.
12. **Backups and offboarding (medium).** Section 9, last row.
13. **Redis clustering and hash tags (low).** 4.4.

Questions to put to the owner in one list: (1) pre-auth tenant hint ruling (risk 3); (2) number quarantine period; (3) unknown-number versus signature response (2C); (4) support principal model; (5) single origin or tenant subdomains for the app; (6) whether to render links at send time instead of in outbox bodies; (7) per-tenant small-group floor; (8) per-tenant time zone and thresholds not needed now; (9) whether any person is staff in two tenants; (10) tenants sharing an Entra directory; (11) brand: replace "DIUCS" and "Dorset" and "SystmOne" in templates by a tenant brand.

---

## 11. PROPOSED TASK BREAKDOWN

IDs are TEN-C01 to TEN-C32 (C26 to C32 come from DEC-132, section 13). Dependencies on the seam (DEC-130 items 2 to 4, the `bind_tenant` context and `run_query` guard, owned by the graph auditor's tasks) are written as "SEAM". Hours are builder hours including tests and are estimates; the task-prompt convention applies (red tests first, real Neo4j, no fakes for Neo4j-backed ports).

| ID | Title | Files | Hours | Depends on |
|---|---|---|---|---|
| TEN-C01 | Tenant id type, context variable, binder and fail-closed errors (pure) | `application/tenant.py` (new), `tests/unit/application/test_tenant.py`; tenant-id regex; reserved `_` namespace | 3 | SEAM |
| TEN-C02 | `tenant` claim in the BFF token, `Actor.tenant_id`, test token helper. **Reworks delivered R02** | `domain/rules/bff_token.py:32,48,128`, `fhir_rest/auth.py:37`, `application/actor.py:9`, `adapters/testing/tokens.py:18`, R02 tests | 4 | C01 |
| TEN-C03 | API edge binding: async dependency or middleware, directory check, route-binding test with an allowlist (`/health`, `/fhir/metadata`), threadpool and SSE context proof. **Reworks delivered R01, R02, R06** | `fhir_rest/app.py`, `auth.py`, `routes_events.py`, `tests/support/api.py` | 5 | C02, C04 |
| TEN-C04 | `TenantDirectory` port and Neo4j adapter: Tenant and TenantChannel nodes, `by_inbound_number`, `by_subaccount`, `by_entra_directory`, `list_active`, number uniqueness constraint and quarantine, global-statement allowlist entries (coordinate with the graph auditor's registry task) | `application/ports/outbound/tenants.py` (new), `graph_store/tenant_directory.py` (new), migration | 6 | SEAM |
| TEN-C05 | Tenant-scoped cache: `TenantScopedCache` over `RedisCache` and `InMemoryCache`, per-call prefix, board key and channel, replay key, SSE channel; two-tenant contract cases. **Reworks delivered I01, P09, P12 fakes, U09, R03, R06** | `cache_redis/redis_cache.py:109-144`, `adapters/testing/memory_cache.py`, `board_projector.py:31,135,142,158`, `concurrency.py:110`, `routes_events.py:162`, `tests/contract/*`, `tests/support/redis.py` | 6 | C01 |
| TEN-C06 | Per-tenant lock and fencing: lock names, per-tenant Neo4j high-water mark (with graph auditor), in-memory fake parity | `cache_redis/redis_cache.py:146`, `memory_cache.py:104-117`; I03 | 2 | C05 |
| TEN-C07 | Service Bus message tenant: `BusMessage.tenant_id`, property write, composite session id and message ids, `ManualEventBus` parity, contract cases. **Reworks delivered I02, P08 fake** | `application/ports/outbound/event_bus.py:29`, `bus_servicebus/service_bus.py:25-37`, `adapters/testing/memory_event_bus.py`, contract suite | 5 | C01 |
| TEN-C08 | Consumer framework binds tenant from the property, dead-letters on missing or unknown, per-tenant Processed marker. **Amend I04 (in flight on `task/I04-consumer-framework`)** | `workers/consumer.py`, `workers/servicebus_runner.py` | 4 | C07, C04 |
| TEN-C09 | Outbox relay: tenant round robin, per-tenant lock, backoff and batch, tenant on published and scheduled messages. **Amend I03 prompt** | `workers/outbox_relay.py` (to build) | 5 | C05, C06, C07, C04 |
| TEN-C10 | Scheduled-work consumer and dispatch table use the bound tenant. **Amend I05 prompt** | `scheduler/scheduled_work_consumer.py` (to build) | 1 | C08 |
| TEN-C11 | Per-tenant Twilio: `TwilioSmsRouter`, secret references, `AccountSid` in the status parser, recorded `tenant_id`, remove global `twilio_*`. **Reworks delivered I06** | `sms_twilio/twilio_sms.py`, `adapters/testing/recording_senders.py`, `bootstrap/settings.py:32-34` | 5 | C04, C20 |
| TEN-C12 | SMS inbound and receipt webhooks with lookup-verify-bind flow (2A), unknown-number, signature, suspended and secret-missing cases. **Amend I07 prompt** | `sms_webhook/routes.py` (to build) | 6 | C03, C04, C05, C07, C11 |
| TEN-C13 | Per-tenant email identity and credentials. **Reworks I09 (not delivered, partial)** | `email_smtp/smtp_email.py:26,115-126`, `settings.py:37-42` | 4 | C04, C20 |
| TEN-C14 | Link token resolution: global allowlisted statement returning the tenant, uniform 410, tenant in `LinkTokenService.resolve`; token issued inside the tenant unit of work. **Amend L01, L02; adjust U03 branch** | `application/ports/outbound/tokens.py:55-61`, `link_pages/*` (to build), U03 `send_prompts.py` | 5 | C04, SEAM |
| TEN-C15 | Wall-screen pairing: tenant-less pending pairing in `diucs:_:pair:`, device row at confirm, device-token hash lookup returning the tenant, pairing brute-force limit. **Amend U10, R15** | `use_cases/pair_wall_screen.py`, `fhir_rest/routes_screens.py` (to build) | 4 | C05, C04 |
| TEN-C16 | Text codes, sessions, rate limits per tenant; pre-authentication tenant hint (after the owner ruling). **Amend I13, U25, R11** | `cache_redis/sessions.py`, `cache_redis/code_store.py`, `routes_identity.py` (to build) | 4 | C05, owner ruling |
| TEN-C17 | Per-tenant phone hash, `code-hmac` and `link-csrf` derivation. **Reworks delivered P10** | `application/ports/outbound/identity.py:28-35`, P10 tests | 2 | C01 |
| TEN-C18 | BFF session and minting carry the tenant; Entra `tid` to tenant mapping; rename `ENTRA_TENANT_ID`; one secret name for `bff-jwt`. **Amend W02 (in flight), W09** | `frontend/lib/auth/session.ts:23-31,69-76,103-114`, `frontend/app/api/bff/session/route.ts:14`, W09 files | 5 | C02, C04 |
| TEN-C19 | Telemetry: `tenant.id` on spans and logs via the binder, allow-list entry, metric dimension decision, KQL tenant guard, aggregate `tenantId`, small-group floor. **Amend O01, O04, O07, O08** | `telemetry/otel.py` (to build), `infra/otel-allowlist.txt` (to build), `telemetry_query.py` (to build) | 5 | C01 |
| TEN-C20 | Composition root: new fields (`tenants`, `secrets`, `cache`, `bus`, senders), `build` and `build_for_tests` with two tenants, `ApiContainer`, drop `app.state` wiring, startup check. **Reworks delivered F08 and G14 lifecycle (startup/shutdown order)** | `bootstrap/container.py:32-94`, `bootstrap/settings.py`, `fhir_rest/app.py:22-41` | 5 | C01, C04 |
| TEN-C21 | Infra: servicebus subscription names and filters, tenant property docs, otel allow-list, compose README, CI two-tenant job, tenant onboarding and offboarding runbook, number quarantine procedure | `infra/servicebus-config.json:290-314`, `infra/README.md`, `.github/workflows/ci.yml`, `docs/delivery/` runbook | 4 | C07, C12 |
| TEN-C22 | Test harness for edges: two-tenant fixtures for API, Redis and Service Bus (tenant property filtering on shared emulator queues), route-registry generated test that every route is tenant-bound or allowlisted. **Reworks delivered F10 support use and `tests/support/api.py`, `redis.py`, `servicebus.py`** | `backend/tests/support/*`, `backend/tests/contract/factories.py` | 6 | C03, C05, C07 |
| TEN-C23 | Cross-tenant privilege for support: platform principal, support-code redemption statement and audit in the target chain, KQL guard. **Amend O06, R18, O07** | `use_cases/support_access.py`, `routes_support.py` (to build) | 5 | owner ruling, C04, C19 |
| TEN-C24 | Template branding and tenant-specific wording (DIUCS, Dorset, SystmOne), privacy guard extension. **Reworks delivered D15, D16, D17** | `domain/messages/templates.py:97-321`, `privacy_guard.py` | 3 | owner decision |
| TEN-C25 | Per-tenant SMS cap and API rate limits; platform source-address limiter for unauthenticated paths | `application/ports/outbound/*` (new limiter use), webhook and link routes | 3 | C05, C12 |
| TEN-C26 | Scope type: widen the bound context from tenant to scope (`tenant` or `network`), keep `acting_tenant` for audit and telemetry, reserved scope-id namespace `_net-<id>`, ScopedCache keyed by scope. **Amend TEN-C01, C05** | `application/tenant.py`, `cache_redis/*` | 3 | C01, C05 |
| TEN-C27 | Network access check and claims: `networks` claim (hint), `Actor.network_ids`, `NetworkAccess` port (membership read, cached at most 30 s), uniform 404, new role rule for administrators. **Amend C02, C03** | `bff_token.py`, `auth.py`, `application/ports/outbound/networks.py` (new) | 4 | C02, C04 |
| TEN-C28 | Network read routes and SSE: `$network-board`, `/network/{id}/services`, `/network/{id}/events` bound to the network scope after the membership check; periodic re-check on the open stream; `scope-ended` message | `fhir_rest/routes_network.py` (new), `routes_events.py` | 6 | C26, C27, projector read use case |
| TEN-C29 | Network and grant administration routes (section 13.1): members, grants (request, approve, end), projection status; two-person rule; grants authoritative in the grantor scope | `fhir_rest/routes_network_admin.py` (new) | 6 | C27, graph auditor's Network and Grant nodes |
| TEN-C30 | Projection transport: queue `projection.work`, subscriptions `network-projector` on `capacity.events`, `criteria.events`, `registration.events`, `tenant` and `network` properties, composite session id and message ids, consumer binding for two scopes (read UoW in source, write UoW in network), `QUEUES` constant and `ManualEventBus`, contract cases. **Amend C07, C08** | `event_bus.py:15`, `service_bus.py`, `memory_event_bus.py`, `servicebus_runner.py`, `infra/servicebus-config.json` | 6 | C07, C08 |
| TEN-C31 | Network telemetry: `network.id`, `scope.kind`, `projection.*` attributes and metrics, allow-list, projection lag SLO. **Amend C19** | `telemetry/otel.py`, `infra/otel-allowlist.txt` | 2 | C19, C30 |
| TEN-C32 | Wall-screen board scope setting at the edge: device `boardScope`, `PUT /screens/{id}/board-scope`, server-side scope decision on `$board` and `/events`, last-known purge rule. **Amend U10, R15, W05 to W08 prompts** | `fhir_rest/routes_screens.py`, `routes_events.py` | 3 | C15, C28 |
| | **Total** | | **137** | |

### Delivered tasks that need rework (from the scope of this audit)

R01 (app, container Protocol, errors unchanged), R02 (claims, actor, tests), R03 (replay key, 3 lines plus tests), R06 (channel), I01 (prefix seam per call, tests), I02 (tenant property, session id, message ids), I06 (router and AccountSid), U09 (board cache key and channel), P09 and P12 (cache fake and contract suites), P08 (event bus fake), P10 (phone hash), F08 and G14 (container wiring, startup), U01 (an `Actor` built with no tenant in tests; check `report_capacity.py`), W01 (BFF client passes the token only; no change expected, verify).

### Not delivered, prompt must be amended

I03 (relay per tenant), I04 (consumer, in flight), I05, I07 (webhooks, DEC-131 flow), I08 (workers, tenant hook), I09 (email identity), I10 (subscription names and filters, tenant on sends), I11 and I12 (reference data stays shared; the OS Places key and quota is platform-wide, check per-tenant fair use), I13 (key shapes, tenant for the session), I14 (platform VAPID key, tenant-tagged URLs), L01 and L02 (global token resolve), U03 and U02 (in flight, migrate by sweep), U10 and R15 (pairing), U25 and R11 (pre-auth hint), W02 (in flight), W09 (tenant mapping), O01, O04, O07, O08 (tenant attribute and floor), O06 and R18 (support principal), R18, R12 and R13 route lists (every route tenant-bound).

---

## 12. WHAT I COULD NOT READ OR VERIFY

- The four unmerged branches are **local** refs (`task/I04-consumer-framework`, `task/U03-send-prompts`, `task/U02-confirm-capacity`, `task/W02-bff-session-csrf`, each checked out under `/home/user/overwatch-wt/`). The `origin/task/...` names in the request do not exist as remote refs here, so `git diff main...origin/task/...` fails with an unknown revision; I diffed `main...task/<name>` instead. These branches were at `ed3ec4c`, `b583ffe`, `e6afbe2`, `a610247`. U02 changes only capacity and use-case code and has no tenancy surface in this scope beyond its idempotency key shape (key space is shared with U01, DEC-112 item 6).
- `docs/spec/ui-screens.md` (4402 lines) was searched, not read; I did not check how screens present a tenant name or switch.
- `graph_store` and `audit_neo4j` excluded by scope; where I depend on them (outbox pending reads, `find_by_phone_hash`, `Q-LINK-GET`, Communications) I state the assumption and give it to auditor A.
- I read the goal and rules sections only of I14, U25, R11, O06, O08, R18; and did not read the P16 `credential_store.py`, `contact_store.py` or the hazard log.
- Not verified (no network, not in repo): Twilio webhook parameter list and `AccountSid` semantics, Twilio UK number regulation and lead time, the Service Bus emulator's entity limits, Azure Monitor custom-metric dimension limits, Redis cluster behaviour of the Azure products, Entra multi-tenant app behaviour, and browser push subscription rules per VAPID key. Each is flagged where used.
- The ledger on main is stale (STATUS.md says 48 delivered); I used the refreshed copy on `origin/ledger-refresh` (76 delivered) for the delivered list. I did not read that branch's ledger line by line.
- I did not run any code, tests, Docker or the app, as instructed; counts came from `grep`, `find`, and a short script over `docs/plan/tasks.json`, `infra/servicebus-config.json` and `bootstrap/settings.py`.

---

## 13. NETWORK SCOPE AT THE EDGES (DEC-132)

DEC-132 in one line for this section: a tenant is the legal entity; a `Network` groups tenants; data crosses only as **read-only projections** a projector writes into a **network scope** (an id treated like a tenant, each copied node carrying `sourceTenantId`); members read the network view through a use case bound to the network scope after a membership and grant check; a unit of work binds exactly one scope (DEC-132 items 3 to 5).

Edge consequence: the bound context is a **scope**, not a tenant. Keep two values: `acting_tenant` (from the token; used for audit, telemetry, authorisation) and `bound_scope` (tenant scope or network scope; used by `run_query`, the cache wrapper and the unit of work). They are equal on every route that exists today. Network routes and the projector write path are the only places they differ. Scope id namespaces: tenant ids match `[a-z0-9][a-z0-9-]{1,30}` (2B); network scope ids are `_net-<id>` with the reserved leading underscore, so a tenant can never be named like a network and `SCAN MATCH diucs:<scope>:` stays exact.

### 13.1 (a) Claims, sessions and new REST routes

**Token and BFF session claims** for a user of one tenant that belongs to one network:

```
{ "sub": "<entra oid>", "tenant": "dorset-icb", "networks": ["dorset-spoa"],
  "role": "advisor", "services": [], "exp": ... }          // BFF backend token (HS256, R02 codec)
Session { role, services, sub, tenant, networks, device?, backendToken, expiresAt }   // sealed cookie (W02 session.ts:23-31)
```

- `tenant` (required): authoritative. Binds the tenant scope (3.2).
- `networks` (optional list of network ids): **a hint, not authority.** Membership changes during an 8 hour token (a tenant leaves; a tenant joins). Authority is a request-time check of active membership through a `NetworkAccess` port (Neo4j read, in-process cache of at most 30 seconds [ASSUMED]). Mismatch between claim and directory: uniform 404 body (same bytes as a missing record, DEC-086 item 5). The claim lets the BFF decide whether to render the network link without a call and lets the route reject an obviously foreign id before any read. A token with no `networks` claim is valid for tenant routes.
- `role`: stays a tenant role (the ten `Role` values). Network administration is **not** a token role: it is derived at request time from facts: (i) "network owner administrator" = a token whose `tenant` equals `Network.ownerTenantId` and whose role is the tenant administrator role; (ii) "grantor administrator" = the token's own tenant. There is no tenant-administrator role among the ten `Role` values today (`domain/codes.py` Role: reporter, advisor, clinical, lead, owner, exec, wall, anonymous-link, support, audit; `owner` means criteria owner). DEC-132 uses "administrator" without naming a role. Owner decision needed: reuse `lead` or add an eleventh role `admin`. Recommendation: add `admin` (one enum member, one entry in `frontend/lib/auth/session.ts` ROLES and the W09 role mapping `DIUCS.Admin`), because `lead` is the shift lead and approving a data-sharing grant is a different accountability.
- `Actor` gains `tenant_id` (C02) and `network_ids: frozenset[str]` (hint). `actor_from_claims` copies both.
- Wall token: `role=wall`, `sub=<device id>`, `tenant`; **no network claim**. The network board setting is on the device record (13.5).
- No cross-tenant claim of any kind. `support` stays platform-only (3.6, DEC-132 item 8).

**Routes.** All bind `acting_tenant` from the token. A `networkId` in a path is a selector that is validated against membership; it is never a source of a tenant. Every refusal is the uniform 404. Mutations of grants write in the **grantor's** tenant scope (authority), with a mirror record in the network scope for the owner to see; the two writes are two units of work (one scope each), so a grant request or approval is two steps and the second step is retried by an outbox message (the same pattern as use case change plus outbox).

| Route | Purpose | Auth rule |
|---|---|---|
| `GET /network` | the networks my tenant belongs to (id, name, my membership status) | any authenticated staff role; tenant from token; returns only networks where membership is active or ended (so a leaver can see history) |
| `GET /fhir/HealthcareService/$network-board?network=<id>` | network capacity view (same Parameters shape as `$board`, plus `sourceTenant` display name per entry) | roles allowed to read the board today (`routes_events.py:36` STREAM_ROLES: wall, advisor, clinical, lead, exec; `QueryBoard` refuses only `anonymous-link`, `query_board.py:70`) **except** `wall` unless the device is set to network (13.5); reporters and link users never (DEC-132 item 5); active membership in `network`; binds the network scope; read-only use case, no write |
| `GET /network/{id}/services` and `GET /network/{id}/services/{serviceId}/criteria` | directory and current criteria projections | same as above; criteria only for the service's current version (DEC-132 item 4) |
| `GET /network/{id}/events` (SSE) | live "network board changed" messages | same as above; membership re-checked on connect and every 60 seconds [ASSUMED] while the stream is open; a `scope-ended` message or a failed re-check closes the stream (a long-lived SSE must not outlive a grant or membership) |
| `GET /network/{id}/members` | members, status, joined, left | network owner administrator: all; any other member's staff: names and status only |
| `POST /network/{id}/members` | add a tenant to the network | network owner administrator only; the new tenant must already exist; the data sharing agreement reference and version are in the body (reference only, never content); `Idempotency-Key` required |
| `POST /network/{id}/members/{tenantId}/$leave` | end membership (history stays, DEC-132 item 6) | that tenant's administrator or the network owner administrator; the owner tenant cannot leave while it owns the network |
| `GET /network/{id}/grants` | grants (scope, purpose, dates, status, version) | grantor administrator sees its own tenant's grants; network owner administrator sees all grants' **metadata** (never data); other staff: none |
| `POST /network/{id}/grants` | request a grant (scope in `capacity`, `directory`, `criteria`; purpose; dates) | grantor = **the token's tenant**, never a body field; grantor administrator; status `requested` |
| `POST /network/{id}/grants/{grantId}/$approve` | second approval | network owner administrator; must differ from the person who requested (the DEC-032 approver-is-not-requester pattern); the grant is only `active` when both approvals exist (DEC-132 item 3) |
| `POST /network/{id}/grants/{grantId}/$end` | end a grant, stops future sharing only | grantor administrator, any time; takes effect at the source immediately because the projector checks the grant in the grantor's scope |
| `GET /network/{id}/projection-status` | last projected time and lag per member and scope, counts, no data | administrators of the owner and of the member's own row |
| `PUT /screens/{deviceId}/board-scope` | wall screen setting (13.5) | the paired tenant's administrator; `If-Match` required (R03 pattern) |

Network creation and tenant creation have **no** REST route in the pilot: they are human-only provisioning (DEC-132 item 9, DEC-131 item 1), done by a script that writes the Neo4j side.

Gaps in the owner's text that the routes expose:
- **Reciprocity.** DEC-132 answer 1 says members see the network view. It does not say whether a member that has granted nothing may see what others granted. The route above does not require the viewer's own grant. Owner to confirm.
- **Role scope.** "Staff of a member tenant whose role may see the board" is read here as the roles in STREAM_ROLES plus `advisor`'s board read. Confirm `exec` and `lead`.
- **Booking across tenants.** The capacity loop in F2 is an advisor requesting a booking of a service. Under DEC-132 item 4, bookings are never shared, and under DEC-130/131 each tenant texts only its own reporters from its own number. If the advisors are in the network owner's tenant (the SPOA) and the services belong to member tenants, an advisor can **see** another tenant's capacity but cannot request a booking from it, because the booking request SMS would be sent by tenant A's subaccount to a reporter record that lives in tenant B's scope and is not readable by A. Answer 5 ("today's need is to share capacity") may mean that bookings stay within one tenant today, but this is the product's core workflow, so the owner should confirm explicitly what an advisor can do with a network row. This is the largest question the network model leaves open for the edges.

### 13.2 (b) Redis keys and channels for the network scope

Scope id `<s>` is `_net-<networkId>`. Everything else follows 4.2.

| Key or channel | TTL | Written by |
|---|---|---|
| `diucs:_net-<id>:cache:board:v1` | 60 s [ASSUMED], same backstop as the tenant board | network projector after a successful write |
| `diucs:_net-<id>:cache:services:v1` | 5 min [ASSUMED] | directory projection read model |
| `diucs:_net-<id>:chan:board.updates` | pub/sub | projector publishes `{"type":"network-board-changed","source_tenant":"<id>","service_id":"<id>","at":...}` after the network write commits; `source_tenant` is allowed because the viewer is entitled to the projected data, which already names it |
| `diucs:_net-<id>:chan:scope.control` | pub/sub | `scope-ended` and `grant-ended` control messages that close open streams |
| `diucs:<t>:lock:project:<networkId>` and `diucs:<t>:fence:project:<networkId>` | lock 30 s; fence never expires | single-flight per (source tenant, network) for backfill and rebuild; **the lock lives under the source tenant** because the projector reads that tenant's scope. The high-water fencing mark lives in Neo4j on the network-scope projection head for that source tenant, because that is where the guarded write commits (DEC-091, L118, L125) |
| `diucs:<t>:cache:network-access:<networkId>` | 30 s | `NetworkAccess` membership cache, tenant side |
| `diucs:_:rl:...` | | unchanged |

Rules:
- A tenant-scope subscription and a network-scope subscription are different channels; a wall in tenant mode never subscribes to the network channel and the reverse.
- The scoped cache (C26) reads the bound **scope**, so the same `RedisCache` wrapper serves both; reading `_net-*` with a tenant bound is refused by the wrapper (a tenant scope may only construct keys under its own id; a network scope is reached only through the network-bound path, which is entered only by the network use cases after the membership check). Test: bind tenant A, ask the wrapper for `_net-x` keys: error.
- Tenant board cache entries are **not** invalidated by network changes and the reverse.
- Flush: tests create a unique network scope per run (`_net-t<uuid8>`) as well as a unique tenant; `flush_prefix(client, f"diucs:{scope}:")`.
- Leaving: when a tenant leaves, the network board cache key is deleted so the next read rebuilds with the leave-date marking (DEC-132 item 6); history in Neo4j is untouched.

### 13.3 (c) Service Bus: how projection work is queued and carried

**Two kinds of projection work, two carriers.**

1. **Steady state (event driven): subscriptions on topics that already exist.** `CapacityReported` and `StatusChanged` are already published on `capacity.events` with `tenant`, ordered per service by session; `CriteriaApproved` goes on `criteria.events`; service activation and registration changes on `registration.events` (`RegistrationApproved`; there is **no** event for a service profile edit in `domain/events.py`, so manual directory changes by a lead, U15 and U16, would never reach the projector unless a `ServiceChanged` event is added; flag to the owner of U15 and the events module). Add one subscription named `network-projector` to each of `capacity.events` (session required, like the existing three), `criteria.events` and `registration.events`. No new topic. The message carries `tenant` (the source, set by the relay) and the usual `event_type`; it carries **no network property**, because the source event does not know about networks.
2. **Commands that are not events: a new queue `projection.work`.** Backfill when a grant becomes active, retract or mark-left when a grant ends or a tenant leaves, full rebuild after an allowlist or schema change, and the periodic reconcile. Properties: `tenant` (source scope to read), `network` (target scope to write), `event_type` in `ProjectCapacity`, `ProjectDirectory`, `ProjectCriteria`, `RetractGrant`, `MarkLeft`, `Rebuild`; body: ids only (`service_id`, `grant_id`, `grant_version`, `reason`), **never figures**, so a replayed or stale message can only cause "project the current state again", and a dead-lettered message holds no capacity data (cleaner than `messages.outbound`, 5.6). `message_id = "<tenant>:<network>:<command id>"`, no sessions, duplicate detection off (idempotence is by the Processed marker and by a monotonic `asOf` guard on the projected node), TTL PT1H like the others.

**Does the projector need its own queue? Yes, one queue (`projection.work`), not one per network and not a topic.** Reasons: (i) a backfill or rebuild for a large tenant is bursty and must not sit in front of the missed-report ladder on `scheduled.work` (reminders and phone tasks are time critical, domain-rules 1.5); (ii) it needs a second property (`network`); (iii) it has different retry and dead-letter handling (a missing grant is a permanent no-op, not an error); (iv) it keeps the steady-state subscriptions from carrying commands. Cost: `QUEUES` (`application/ports/outbound/event_bus.py:15`), `ManualEventBus`, the config (3 queues become 4, 18 subscriptions become 21) and the contract suite grow by one entity each.

**How a consumer handles it (two scopes, one unit of work each).** For a steady-state event: (1) bind the source tenant from `tenant`, open a **read-only** unit of work, check that the tenant has an active `Grant` for the scope and an active membership for each network (reading the grant in the grantor's own scope, which makes "the grantor can end it at any time" immediate), load the allowlisted fields into a plain value object, close; (2) for each target network, bind the **network scope** and open a write unit of work: `processed.mark_if_new(message.id, "network-projector")`, upsert the projected node keyed `(sourceTenantId, serviceId)` with `asOf`, refusing to overwrite a newer `asOf`, commit; (3) after commit publish `chan:board.updates` for the network and invalidate the network board cache. The Processed marker therefore lives in the **network scope**, so the marker and the write commit together; the source read has no write. A grant ended between (1) and (2): the end flow first marks the grant mirror ended in the network scope, and the write unit of work re-reads that mirror and drops the write if ended. Message order across the two streams is not guaranteed by Service Bus sessions (different session ids), so the mirror read, not ordering, is the guard.

Fan-out amplification is one projection per event per network (one network today), and the projector must not project a field outside the allowlist: the I04 framework needs a `Projector` handler type whose input is the value object, not a unit of work, so the allowlist type (D17 guard and a test, DEC-132 item 7) is the only thing that can reach a network write.

Runner and framework changes (beyond C08): `IdempotentConsumer` gets a two-scope handler variant (`ScopedHandler(read_scope, write_scope)`), `to_bus_message` reads `network` when present and validates it against the directory, and a message for a network the source tenant is not (or no longer) a member of is a `PermanentError` ("not a member") dead-lettered with a fixed reason.

### 13.4 (d) Telemetry for the network scope

New attributes (all pass the O01 `*.id` rule except the last two, which are added explicitly): `network.id`; `scope.kind` (`tenant` or `network`); `scope.id` is **not** added (it duplicates `tenant.id` or `network.id` and would double the cardinality); `projection.kind` (`capacity`, `directory`, `criteria`); `projection.outcome` (`projected`, `no-grant`, `not-member`, `stale-dropped`, `retracted`, `marked-left`); `grant.id` (an id, allowed; never the agreement reference or version text).

- Request spans on network routes: `tenant.id` = acting tenant, `network.id`, `scope.kind=network`, `fhir.search HealthcareService` operation `network-board`.
- Projector spans: `projection.project {kind}` with `tenant.id` = **source**, `network.id` = target, `grant.id`, `projection.outcome`, row counts. The write unit of work's `neo4j.query` spans carry `scope.kind=network`.
- Metrics (bounded dimensions): `projection.lag` histogram by `projection.kind` and `projection.outcome` (lag = event time to network commit; this is the network-view equivalent of the "text reply to board change p95 3 s" budget, observability.md:121; propose p95 10 s [ASSUMED] since it crosses a queue hop and two units of work); `projection.queue.depth` by `scope.kind`; with `tenant.id` allowed under the 7.1 rule and `network.id` allowed while the network count is at most about 5.
- Logs: `tenant.id`, `network.id`, `projection.outcome`, message id. Never the projected values, `sourceTenantId` of a **non-granting** tenant, the grant agreement reference, or anything from the allowlist payload.
- Collector allow-list `infra/otel-allowlist.txt` (O04) adds `network.id`, `scope.kind`, `projection.kind`, `projection.outcome`, `grant.id`.
- Aggregates (O08): usage of the network view is a network-scope aggregate; the "groups under 10 sessions" floor (observability.md:150) is evaluated across the members' staff, which makes network aggregates more usable than per-tenant ones (7.4).
- Support console: sessions are tenant-scoped (3.6); a support access never opens a network scope in this model.

### 13.5 (e) Wall screen network-board setting at the edge

- **Where the setting lives.** On the Device record in the **paired tenant's scope**: `boardScope` in `tenant` (default) or `network`, and `networkId` when `network`. It is not in the wall token, so the administrator can change it without re-pairing and a stolen token cannot widen its own view. The wall token carries `tenant`, role `wall`, `sub=<device>` only (13.1).
- **Who changes it.** `PUT /screens/{deviceId}/board-scope` (13.1), tenant administrator, `If-Match` and `Idempotency-Key`, audited in the tenant's chain. Setting `network` requires active membership of that network and at least one active grant in the network (otherwise 404 uniform; the UI task decides the control, DEC-132 item 5).
- **How the board request is decided.** `GET /fhir/HealthcareService/$board` (tenant board) is unchanged. `GET .../$network-board?network=<id>` for role `wall` is accepted only if the device's stored `boardScope` is `network` and `networkId` equals the path value and membership is active; otherwise uniform 404. The query parameter is a request for a view, never a source of authority. The server does not infer the view from the parameter alone for a wall: a wall cannot read the network board just by asking.
- **SSE.** `GET /events` stays tenant. `GET /network/{id}/events` for a wall follows the same device check on connect and on each 60 second re-check; changing the setting publishes `scope.control` so open streams close and the screen re-reads its setting. A wall in `network` mode may also need the tenant channel (to show its own pending count); that is two subscriptions held by the BFF's SSE relay, not one mixed stream, because a stream has exactly one scope.
- **Last known.** The wall page shows "Last known" when the stream and poll fail (architecture.md:272, W06). With a network setting it must not keep showing network data after membership ends or the setting returns to `tenant`: the setting response carries a `scopeVersion`; the page clears cached network state when it changes or when the network read answers 404. The cached payload is data from other organisations (a copy under a data sharing agreement) so the "Last known" copy has a maximum age [ASSUMED 2 hours, matching the stale warning `STALE_WARNING_AFTER`, `domain/rules/freshness.py`].
- **Failure modes.** Grant ended: the network board loses that tenant's rows on the next projection (retract) and the wall keeps working. Membership ended: 404 uniform, the wall shows a fixed "Network view is no longer available" and reverts to the tenant board (UI wording is for the UI task). Device revoked: 401 as in 3.1.
- **Pairing impact.** U10 and R15 are unchanged except that `ConfirmPairing` creates the Device with `boardScope=tenant`.

### 13.6 Network-scope risks added to section 10

14. **Booking across tenants is not modelled (high, owner).** 13.1, last bullet.
15. **Projection staleness is a safety issue (medium to high).** Another organisation's wall shows a figure that is a copy; lag, a stuck projector or a dead-lettered projection makes a stale number look current. Each projected node must carry the source's `asOf` and the board must compute freshness from `asOf`, not from projection time, so the existing "Not updated: treat as unknown, phone" rule (domain-rules 1.3) keeps working. A projection lag alert is a safety control, not only an operational one (hazard log entry for the clinical safety officer; I have not read the hazard log).
16. **Retraction after a grant ends (medium).** DEC-132 says a grant stops **future** sharing only and that projections stay (item 3, 6). A grantor who ends a grant because of an error expects the data to disappear from the network board now. The board must show projected nodes only while a grant is active and mark ended-grant nodes as history, not as live capacity; otherwise a former member's last figure stays on the board indefinitely. Owner to confirm that the live board hides data of ended grants while history keeps it.
17. **Two-scope atomicity (medium).** No unit of work spans a source scope and the network scope, so the read and the write are separate and the guard is the grant mirror (13.3). This needs a test with a grant ended between the read and the write.
18. **Network owner is a single point of administration (low to medium).** The owner tenant approves every grant and holds the agreement reference; its administrator accounts are the most privileged tenant accounts in the system, yet DEC-132 gives the owner no read access to members' private data. The route table enforces that, and a test must assert it (owner administrator calls a member-tenant route: 404).
19. **Entra mapping for the network owner (low).** The owner and members may share an Entra directory in practice (an ICB hosting its own provider collaborative); then `tid` alone does not name the tenant (risk 11). The same resolution applies.

### 13.7 Delivered and planned tasks touched by DEC-132

Delivered and affected beyond section 11: R06 (SSE gets a second, network route), U08 and U09 (`QueryBoard` and `BoardProjector` get a network-scope variant; `WALL_ACTOR` at `board_projector.py:46`), I02 (queue constant), P08 (queue constant in `ManualEventBus`). Planned prompts to amend: I03 (relay publishes the `tenant` property to the steady-state subscriptions, nothing new), I04 (two-scope handler), R15 and U10 (device `boardScope`), W05 to W08 (wall board and last-known behaviour, setting control), W09 (role `admin`, `networks` claim), O01, O04, O07, O08 (network attributes), U15 and U16 (a service profile edit event for the directory projection), D17 (privacy guard enforces the projection allowlist).
