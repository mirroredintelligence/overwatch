# Gap triage: the whole backlog against the code

Written 2026-10-31 on `task/triage-gaps` (merged to integration/build tip `cd8a247`, which includes W9A, W9B, W9C, W9G and W9H). Analysis only: no code, test or shared document was changed. Sources: `docs/delivery/known-issues.md` (846 rows), the open rows of `docs/delivery/hazard-log.md` (237 of 434), the open decisions (DEC-854 to DEC-856 and every status that waits on a person), the ledger, and the code.

## How to read this

- **Ids.** `KI-n` is the line number of the row in known-issues.md. `H-n` is a hazard id. `Qn` is an owner question in section 3. `B1` to `B12` are the class A bundles in section 2.
- **Classes.** A closable in code now; B needs an owner decision (a product, clinical or IG choice the orchestrator cannot make under DEC-133 because it changes a patient-facing rule, a clinical value, what another organisation may see, or what a person is told); C needs infrastructure, a credential or an external approval that does not exist here; D accepted risk or wontfix; E already closed (stale row).
- **Evidence.** An evidence cell with `file:line` was read in the code on this tree and is what the row was judged against. A cell with only a file or a task id means the row was classified from its text, its trigger and the cluster it belongs to (for example "every W-series row that says the BFF route still answers not-built" was settled by one search: no `not-built` is left outside tests), not by a separate probe. Treat the second kind as likely, not proven; the first task of every bundle should re-read its rows before changing code.
- **Severity.** Known-issues rows have none; the column is the orchestrator's reading (HIGH: a wrong, stale or missing clinical decision, patient-linked or another tenant's data, an authority that should not exist; MEDIUM: a degraded workflow or non-patient personal data; LOW: the rest). Hazard severities are the log's own.
- **Hazard status.** The hazard log has no status column; the status is the word after `Status:` in the Verified-by text. "Open" here means that word is open, partial, partly, proposed, specified, written, or absent. 197 rows read built, controlled, closed, verified, mitigated or fixed and are not triaged.

## 1. Summary

### 1.1 Counts per class

| Class | Known issues (846) | Hazards open (237) | Decisions (12 lines) | Total |
|---|---:|---:|---:|---:|
| A Closable in code now | 424 | 79 | 1 | 504 |
| B Needs an owner decision | 54 | 128 | 2 | 184 |
| C Needs infrastructure, a credential or an external approval | 21 | 7 | 2 | 30 |
| D Accepted risk or wontfix | 197 | 8 | 3 | 208 |
| E Already closed (stale row) | 150 | 15 | 4 | 169 |
| **Total** | **846** | **237** | **12** | **1095** |

Reading the numbers: 150 of the 846 known-issue rows are stale (the wave-7 back end, the wave-8 wiring, the tenancy conversion and W9A closed them); 126 of the 237 open hazards are open only because their severity still reads TBD (Q1), and the tests they name exist. About a fifth of class A (B12, 75 rows) is "tests written, never run" or harness clean-up. What is genuinely left to build sits in bundles B1 to B11.

### 1.2 Counts per area, known issues

| Area | A | B | C | D | E | Total |
|---|---:|---:|---:|---:|---:|---:|
| Advisor flow | 30 | 10 | 1 | 4 | 23 | 68 |
| Clinical | 19 | 5 | 1 | 5 | 13 | 43 |
| Reporter app | 27 | 1 | 3 | 3 | 18 | 52 |
| Registration and review | 39 | 8 | 0 | 16 | 26 | 89 |
| Lead | 14 | 5 | 0 | 7 | 14 | 40 |
| Exec | 17 | 2 | 0 | 6 | 5 | 30 |
| Network | 17 | 8 | 0 | 18 | 7 | 50 |
| Tenancy and operator | 53 | 4 | 1 | 19 | 29 | 106 |
| Harness and CI | 69 | 0 | 1 | 47 | 4 | 121 |
| Observability | 34 | 3 | 0 | 14 | 3 | 54 |
| Wall screens | 14 | 1 | 0 | 10 | 4 | 29 |
| Security and privacy | 41 | 1 | 1 | 30 | 3 | 76 |
| Infrastructure | 13 | 0 | 13 | 7 | 1 | 34 |
| Capacity loop (extra area: reports, prompts, board, workers) | 37 | 6 | 0 | 11 | 0 | 54 |
| **Total** | 424 | 54 | 21 | 197 | 150 | 846 |

### 1.3 Counts per area, open hazards

| Area | A | B | C | D | E | Total |
|---|---:|---:|---:|---:|---:|---:|
| Advisor flow | 8 | 19 | 2 | 0 | 4 | 33 |
| Clinical | 3 | 3 | 0 | 2 | 2 | 10 |
| Reporter app | 7 | 18 | 0 | 0 | 0 | 25 |
| Registration and review | 16 | 15 | 1 | 2 | 5 | 39 |
| Lead | 10 | 4 | 0 | 0 | 3 | 17 |
| Exec | 9 | 6 | 0 | 0 | 0 | 15 |
| Network | 6 | 14 | 0 | 0 | 0 | 20 |
| Tenancy and operator | 2 | 17 | 1 | 0 | 0 | 20 |
| Harness and CI | 0 | 0 | 0 | 0 | 0 | 0 |
| Observability | 2 | 7 | 1 | 2 | 0 | 12 |
| Wall screens | 0 | 6 | 0 | 0 | 0 | 6 |
| Security and privacy | 3 | 0 | 0 | 0 | 0 | 3 |
| Infrastructure | 0 | 4 | 1 | 1 | 0 | 6 |
| Capacity loop (extra area: reports, prompts, board, workers) | 13 | 15 | 1 | 1 | 1 | 31 |
| **Total** | 79 | 128 | 7 | 8 | 15 | 237 |

Area for a hazard is read from its "Where it is built" column; "Capacity loop" is an extra area (reports, prompts, replies, board, workers) that the 13 requested areas do not name (54 known-issue rows and 31 hazards).

### 1.4 What closes the most

| Bundle | Known-issue rows | Hazard rows | Size | Model |
|---|---:|---:|---|---|
| B1 SERVE: the API serving process and production composition | 28 | 0 | L, about 16 h | Sonnet (auth, secrets, tenancy) |
| B2 CAPLOOP: capacity loop rules, replies, workers | 35 | 2 | L, about 20 h | Sonnet (clinical safety, concurrency) |
| B3 TENANT-CONFIG: tenant policy, zone, closures, lifecycle and the tenancy kernel | 58 | 2 | XL, about 28 h (58 rows, most small) | Sonnet (tenancy, thresholds, lifecycle) |
| B4 BOOKING: booking pages, echoes, need wording, timers | 17 | 9 | M to L, about 14 h | Sonnet (patient-facing wording, booking safety) |
| B5 REGISTRATION-CRITERIA: registration, review and criteria back end and pages | 34 | 8 | L, about 20 h | Sonnet for approval, criteria and registration persistence; mechanical for page fields |
| B6 ADVISOR-CLINICAL: case, options, advice, summary, replay | 29 | 5 | L, about 22 h | Sonnet (clinical safety) |
| B7 LEAD-EXEC-REPORTER: alerts, safety concern, lead and reporter edges | 44 | 6 | L, about 22 h | Sonnet for alerts and the safety concern; mechanical for the rest |
| B8 SECURITY-PRIVACY: at-rest encryption, token revocation, flood and enumeration controls | 25 | 2 | L, about 28 h (two new adapters, then the hardening) | Sonnet (security, privacy) |
| B9 FRONTEND-FOUNDATION: tenant words, id-route scoping, CSRF, sign-out, polish | 23 | 0 | M, about 14 h | Mechanical, except the idScoped and CSRF tasks (Sonnet) |
| B10 NETWORK-UI: BFF network scope, views, administration screens, end-to-end suite | 17 | 5 | XL, about 53 h: 47 h of plan (TEN-068 6, 069 4, 070 8, 071 5, 080 8, 081 8, 085 8) plus about 6 h of back-end network rows | Sonnet for TEN-068 and TEN-081 (tenancy, privacy); mechanical for the screens |
| B11 OBS-SUPPORT: support access, telemetry back end, synthetic checks, console polish | 39 | 2 | L, about 18 h | Sonnet for the support-access and ticket tasks; mechanical for the rest |
| B12 VERIFY-HARNESS-DOCS: verification sweep, e2e, harness clean-up, document fold | 75 | 38 | M to L, about 16 h of work plus run time | Mechanical (a Sonnet reviewer signs the fold) |

Class A in total: 424 known-issue rows and 79 hazard rows; about 270 builder hours in all. Sizes are the orchestrator's estimates for one builder (red, green, fast checks), not measured. B12 carries 75 rows and 38 hazards because most hazards are "controlled, tests written, not yet run on a database".

### 1.5 Gaps this triage found that no row names

| Id | Finding | Evidence | Class and bundle |
|---|---|---|---|
| N1 | The topic `codes.dispatch` that every text code is published to is not in the Service Bus topology and has no consumer, so no set-up, re-verify, lost-phone or registration code is texted. Known-issues row KI-270 said this was waiting on I10 and was read as closed by the SendMessage sender; it is not. | `backend/src/diucs/application/use_cases/text_code.py:48,228`; `infra/servicebus-config.json`; `adapters/inbound/workers/message_senders.py:67` | A, HIGH, B2 task 5 (KI-270 is now an A row) |
| N2 | Subscriptions declared in the topology that no code reads: notifier (4 topics), advisor-stream, lead-queue-projector, flag-maintainer, escalation-timer, analytics, analytics-aggregator. Whatever is published to them expires. | `infra/servicebus-config.json` against a search of the code for each name | A, MEDIUM, B1 task 5 |
| N3 | `create_app` has no production caller (no `api_main`), so the whole HTTP surface, the platform routes, the network routes and the exchange have never been started by a production entry point; many rows (KI-162, 243, 527, 537, 587) are one gap. | `grep create_app src`: only app.py:77 | A, HIGH, B1 |
| N4 | W9I builds TEN-072 without TEN-068 (BFF network scope), which the plan lists as its dependency; its "our organisation or a network" choice has no network scope to call. | `docs/plan/tasks.json` deps; `frontend/app/api/bff/` has no `network` | Coordinate: B10 task 1 gives W9I the route contract |

## 2. Class A: closable in code now

### 2.1 Sequencing and the running wave-9 bundles

State of the wave-9 worktrees when this was written (`git -C /home/user/overwatch-wt/W9X log`):

| Bundle | Branch tip | What it builds (from its commits) | Files it owns that others must not edit | State |
|---|---|---|---|---|
| W9A network admin chain (TEN-056, 077, 078, 079, 061, 074, 086) | `cd8a247` | Leave and grant-end, membership, listings, grants, network admin routes, offboarding export and purge, runbooks | `routes_network_admin.py`, `use_cases/{grants,membership,network_admin,listing_admission,network_leave,tenant_offboard,tenant_purge}.py`, `export_files/`, `scripts/tenant_lifecycle.py` | **Merged into integration/build** (it is the branch tip). Do not rebuild. TEN-086 has 1 of 4 plan files; the three runbooks in `docs/delivery/runbooks/` exist, so it only needs the hazard rows folded (B12). |
| W9D tenant admin, operator, tickets screens (TEN-076, TEN-083, TEN-075 screens) | `4ce8aa6`, 10 commits ahead, plus uncommitted edits in the worktree | Tenant administration screens, operator console routes and screens, operator session, sign-in, CSRF, BFF wrapper, proxy guard | `frontend/components/{admin,operator}/`, `frontend/lib/{operator,tenantAdmin}/`, `frontend/lib/auth/` (6 files), `frontend/proxy.ts`, `frontend/lib/bff/`, `frontend/test/guards/`, `frontend/app/(tenant-admin)/`, `frontend/app/(operator)/`, `frontend/app/api/bff/platform/` | Running. Backend untouched. |
| W9F insight | `e36c2ea`, 8 commits ahead | Insight ingest and tabs (back end and page), web vitals, telemetry mount, collector allow-list | `backend/.../graph_store/{aggregate_repository,insight_repository,migrations,migrations_insight,unit_of_work}.py`, `fhir_rest/{app,routes_insight}.py`, `frontend/components/{console/insight,telemetry}/`, `frontend/lib/{telemetry,console}/`, `infra/otel-*` | Running. |
| W9I wall screens admin (TEN-072) | `2b19359`, 7 commits ahead | Screen list, revoke, live-screen check at the edge, disconnected wall display, board choice on pairing | `fhir_rest/{auth,routes_screens,routes_services,routes_validate}.py`, `credential_store.py`, `pair_wall_screen.py`, `screen_admin.py`, `domain/model/device.py`, `frontend/lib/screens/`, `frontend/components/{lead,screens}/`, `frontend/app/(wall)/`, `frontend/app/(lead)/lead/screens/` | Running. Its plan row lists TEN-068 (BFF network scope) as a dependency and TEN-068 is not built: see B10. |

Rules this plan follows: nothing below rebuilds a W9 task. Where a row belongs to a W9 bundle's subject (initTelemetry mount, web vitals, insight route, screen revoke, operator console, tenant administration screens, ticket screens) it is listed as class E with the branch that closes it ("not yet merged"), or as a verification item for after the merge, never as new work.

Order and parallelism:

- **Start now, in parallel (disjoint files):** B2, B4, B5, B6, B12 (task 1), the first two tasks of B8 (new adapters), B10 tasks 1 to 4 (TEN-068 to TEN-071 and back-end rows), B11 tasks 1, 2 (back end) and 4, B1 tasks 3 to 5.
- **After W9F and W9I merge:** B1 tasks 1 and 2 (app.py, auth wiring), B8 tasks 3 to 5 (auth.py, credential_store.py, pair_wall_screen.py, routes_screens.py, routes_services.py), B11 task 3 and the console items.
- **After W9D merges:** B10 TEN-080 and TEN-081, B11 ticket-request screen, then B9.
- **Sequenced on shared files:** B1 then B3 (container.py, areas); B3 then B7 (lead_views.py, change_reporter_number.py); B4 and B5 then B9 (component text); B6 owns the network option rows in filter_options.py and criteria_repository.py so that B10 does not edit them. B12 task 1 repeats after each merge; its task 5 (fold) is last.
- Neo4j tests run one at a time: `flock /tmp/diucs-neo4j-tests.lock <command>`. The shared container `diucs-test-shared-neo4j` is up on this host; Chromium is not installed (`~/.cache/ms-playwright` is missing), which is why e2e is a B12 task and not an assumption.

### 2.2 Bundles

#### B1 SERVE: the API serving process and production composition

- **Model:** Sonnet (auth, secrets, tenancy). **Size:** L, about 16 h.
- **Waits for:** Tasks 3 to 5 can start now (container.py, workers_main.py). Tasks 1 and 2 wait for W9F (it adds routes_insight to fhir_rest/app.py) and W9I (it changes fhir_rest/auth.py and routes_screens.py, and the screen wiring in app state). W9A and W9C are already merged and give install_platform_routes and the network admin services this bundle wires.
- **Files it owns:** backend/src/diucs/bootstrap/{api_main.py (new), container.py, settings.py, workers_main.py}, adapters/inbound/fhir_rest/app.py, backend/pyproject.toml, tests/unit/bootstrap/, tests/integration/test_api_boot.py (new)
- **Rows:** 28 known issues, 0 hazards.
- **Ordered task list** (red tests first, per the build-wave rules):
  1. Write bootstrap/api_main.py: Settings, Container.build, create_app, install_platform_routes, and set app.state.secrets, cache, token_exchange, link_pages, sms_webhook (DirectoryInboundLines), network_services (NetworkAccess, UowScreens), synthetic. Add uvicorn. Refuse to start (not answer 404) when bff-jwt, account-ref or the link-token secret is absent. Red tests first: a missing secret stops start-up; every route family has its app.state set.
  2. Trusted-proxy handling for Cloudflare (deployment-plan item 5): take the client address and original host from Cloudflare's headers only when the request comes from Cloudflare; plus a log filter that redacts the link-token and invitation path (rate limits and throttles otherwise count the proxy).
  3. Container: replace _no_link_host and _no_wording with DirectoryLinkBase and a ReadTenantConfig-backed wording; refuse a plain-string link base in a serving process; make the audit head per tenant at start; check the sealer is passed to RespondToBooking.
  4. Register the prompt-due handler (SendPrompts has no production caller), keyed with prompt_key; test set-up, first prompt, send, Y, board through the queue.
  5. Service Bus topology audit (found by this triage): subscriptions with no consumer in the code are notifier (booking, registration, criteria, alerts events), advisor-stream, lead-queue-projector, flag-maintainer, escalation-timer, analytics and analytics-aggregator; messages published to them expire after the time to live. For each, build the consumer or delete the subscription and its publisher; criteria.events has no board-projector subscription (KI-434, in B10).
  6. Start-up checks: warn or refuse for NoSecrets, NoPostcodes, NoGeocoder, NoTelemetry; ProjectionNotifier in the worker serve path; worker tenant list from container.tenants and never the platform scope.
  7. Boot smoke on the shared Neo4j under the lock: /public/profile, token exchange with the fake verifier, a report, the board.

| Rows | Area | Sev | What | Evidence |
|---|---|---|---|---|
| KI-96 | CAP | HIGH | `prompt-due` has no handler: SendPrompts has no production caller, so no prompt is ever sent by the queue | backend/src/diucs/bootstrap/container.py:224-422 (handlers registered: ladder, alerts only) |
| KI-162 | REP | HIGH | Nothing sets `app.state.link_pages` or the per-tenant link base for prompt jobs | bootstrap/container.py:570 (`link_base_url_for=_no_link_host`) |
| KI-243 | INF | HIGH | No serving entry point sets app.state.secrets (every FHIR route reads it) or trusts the proxy's forwarded address | backend/src/diucs/adapters/inbound/fhir_rest/auth.py; no api main in bootstrap/ |
| KI-387 | CAP | HIGH | prompt-due has no handler: the first prompt is not sent by the queue (same as row 96) | bootstrap/container.py:224-422 |
| KI-490, KI-492 | ADV | HIGH | Booking requests and registration invitations fail closed in production: link host and referral wording not wired from the tenant directory/config | bootstrap/container.py:294-301,570-571 |
| KI-502 | CAP | HIGH | SendPrompts has no production caller (prompt-due handler not registered): same as row 96 | bootstrap/container.py |
| KI-527 | INF | HIGH | DirectoryInboundLines not wired into a serving process; the SMS webhook still reads app.state.sms_webhook | adapters/inbound/sms_webhook/routes.py; no api main |
| KI-537 | INF | HIGH | Exchange routes not wired: app.state.secrets (bff-jwt, account-ref) and app.state.token_exchange are set by no process | backend/src/diucs/adapters/inbound/fhir_rest/routes_auth.py; bootstrap/platform_services.py:127-132 (platform only) |
| KI-587, KI-852 | INF | HIGH | No production caller sets app.state.network_services (and NetworkAccess/UowScreens wiring) | backend/src/diucs/adapters/inbound/fhir_rest/app.py; routes_network.py |
| KI-124 | TEN | MEDIUM | Container.startup() makes the audit head once, unscoped; a second tenant's head comes from provisioning | bootstrap/container.py |
| KI-161, KI-166 | SEC | MEDIUM | Rate limits count by socket peer: set the trusted-proxy flag in the serving entry point | link_access.py; bootstrap (no serving process) |
| KI-167 | INF | MEDIUM | uvicorn is not a dependency and no log redaction for the token path | backend/pyproject.toml |
| KI-191, KI-196 | INF | MEDIUM | Production with no centroid file or OS key starts and locates nothing with no start-up warning | bootstrap/container.py (NoPostcodes, NoGeocoder) |
| KI-206 | OBS | MEDIUM | No serving main calls create_app with api_instrumentation | adapters/inbound/fhir_rest/app.py:77; bootstrap/telemetry.py |
| KI-266 | ADV | MEDIUM | Wire the link base URL for booking requests from the TenantDirectory | application/use_cases/request_booking.py; container.py:570 |
| KI-401 | SEC | MEDIUM | Per-address throttle counts the socket peer (proxy address) until the serving entry trusts the forwarded address | routes_identity.py _count |
| KI-441 | SEC | MEDIUM | request.client.host is the proxy's address until the serving process trusts the forwarded address | routes_public.py |
| KI-482 | ADV | MEDIUM | Booking request links use container.link_base_url_for, which production does not configure | bootstrap/container.py:570 |
| KI-505 | TEN | MEDIUM | A plain-string link base is accepted by SendPrompts and the ladder (one base for every tenant) | send_prompts.py; missed_report_ladder.py |
| KI-576 | NET | MEDIUM | The apply step is not given a ProjectionNotifier in the worker serve path | bootstrap/workers_main.py |
| KI-845 | INF | MEDIUM | A missing link-token secret answers 404, not a start-up failure (NoSecrets raises NotFound) | bootstrap/container.py:482 |
| KI-134 | CAP | LOW | Worker tenant list is a configured stand-in (DIUCS_WORKER_TENANTS): use container.tenants | bootstrap/workers_main.py |
| KI-142 | CAP | LOW | `ScopeId.tenant('platform')` accepted by the kernel; DIUCS_WORKER_TENANTS could include it | bootstrap/workers_main.py |
| KI-358 | ADV | LOW | RespondToBooking takes a sealer the route wiring must pass: confirm it is passed | bootstrap container; routes_bookings.py |

#### B2 CAPLOOP: capacity loop rules, replies, workers

- **Model:** Sonnet (clinical safety, concurrency). **Size:** L, about 20 h.
- **Waits for:** None. It touches no file W9D, W9F or W9I changes.
- **Files it owns:** backend/src/diucs/application/use_cases/{report_capacity,confirm_capacity,handle_inbound_text,send_prompts,missed_report_ladder,resolve_report_flag,board_projector}.py, domain/rules/{freshness,report_flags}.py, adapters/inbound/workers/{outbox_relay,delivery_tracker,message_senders}.py, adapters/inbound/fhir_rest/{routes_board,routes_events,concurrency}.py, graph_store/{scheduled_work_repository,communication_repository}.py, link_pages/link_access.py, adapters/outbound/email_smtp, frontend/lib/board/useBoardFeed.ts
- **Rows:** 35 known issues, 2 hazards.
- **Ordered task list** (red tests first, per the build-wave rules):
  1. Report and confirm rules: refuse an effective time equal to the latest confirmed time, clamp the default time to the latest effective time (KI-7, KI-8); ConfirmCapacity tenant policy, guard, performer check and config_version (KI-414); tenant zone for the echo times (KI-415). Boundary-value tests.
  2. HandleInboundText: grouped refusal wording `A 40` (KI-26), _waiting (KI-30), a future-dated latest figure no longer raises (KI-31), cache key write order (KI-33), a Y after a pending out-of-range figure (KI-102, KI-104), duplicate audit events (KI-141), one number_after_prompt shared with link_access (KI-159, KI-160).
  3. SendPrompts: warm-graph race test and label (KI-23, KI-24), grouped privacy refusal test (KI-97), skip a prompt delivered after suspension (KI-388, H-137).
  4. Missed-report ladder: tell the lead when a reminder cannot be sent (KI-139), stop older prompts' ladders (KI-137).
  5. The SendCode consumer (KI-270, HIGH, found stale by this triage): add the `codes.dispatch` topic and a subscription to infra/servicebus-config.json, a sender that opens the sealed code (message id, tenant, recipient role) and texts it through the tenant's sender, and DISCARD_CODE handling; test that no code reaches a log, a body or an audit entry. Without it no reporter can set up a phone.
  6. Workers: schedule-crash dedupe, cancel not overwritten, publish timeouts (KI-88, KI-89, KI-103), a receipt before the send write (KI-133), send-once guard after a failed commit with a fault-injection test (KI-185, H-46), errorCode read back (KI-189).
  7. Live board: a named heartbeat event so the wall can tell a dead stream, and a whole-board event for the pressure banner (KI-54, KI-55).
  8. Twilio Email adapter (deployment-plan item 6): comms.twilio.com/v1/Emails behind the unchanged email port, a recording fake, 202-queued mapping to delivered or failed; the per-tenant verified-sender step is C. SMTP rows are superseded.
  9. Flags and clean-up: phoned-versus-text flag direction after Q10 (KI-99), one-open-flag guard (KI-101), ResolveReportFlag through RecordAdvisorPhoned (KI-287), email footer sentence and tests (KI-173, KI-174), shared UnitOfWorkIdempotency (KI-35, KI-36, KI-149).

| Rows | Area | Sev | What | Evidence |
|---|---|---|---|---|
| KI-7 | CAP | HIGH | Equal effective time to the latest confirmed figure is accepted; refuse <= and update DEC-140 item 3 | backend/src/diucs/application/use_cases/report_capacity.py:431 (still `explicit < confirmed_at`) |
| KI-139 | CAP | HIGH | A reminder is not sent to a reporter whose role ended or holder has no phone and nobody is told (service marked Not updated, lead not alerted) | missed_report_ladder.py (_send_reminder) |
| KI-185 | CAP | HIGH | A redelivery after a commit that failed after an accepted send sends the text again (H-46, H-47) | workers/message_sender consumer (I10-1) |
| KI-270 | REP | HIGH | No consumer of SendCode exists and the topic `codes.dispatch` is not in the Service Bus topology: no text code (set-up, PIN re-verify, lost phone, registration sign-in) is ever texted. The row said this was waiting on I10; I10 built the SendMessage sender only | backend/src/diucs/application/use_cases/text_code.py:48,228 (publishes to codes.dispatch); infra/servicebus-config.json (no such topic or subscription); adapters/inbound/workers/message_senders.py:67 (handles SendMessage only) |
| KI-414 | CAP | HIGH | ConfirmCapacity still reads no tenant policy, takes no tenant guard and does not validate its performer; its audit snapshot has no config_version | application/use_cases/confirm_capacity.py |
| KI-8 | CAP | MEDIUM | Default-time number can precede a confirmation across hosts; clamp to the latest effective time of the service's figures | report_capacity.py:430-431, confirm_capacity.py (no clamp found) |
| KI-23 | CAP | MEDIUM | Racing-send test passes on a cold graph and does not prove the idempotency guard: warm the graph first | backend/tests/integration/application/test_send_prompts.py (no warm-up found) |
| KI-26 | CAP | MEDIUM | A refused item on a grouped prompt gets single-service wording ("send 40 again" where `A 40` is needed) and becomes the phone's latest prompt | handle_inbound_text.py (_assign, _plan); D15 C7 |
| KI-31 | CAP | MEDIUM | `decide_capacity_reply` raises ValueError when the latest figure is later than the clock, so a Y or number is not answered | backend/src/diucs/domain/rules/freshness.py:77 |
| KI-54 | WALL | MEDIUM | The page cannot tell an open event stream from a dead one: send a named heartbeat event and read it | backend/src/diucs/adapters/inbound/fhir_rest/routes_events.py (no heartbeat event); frontend/lib/board/useBoardFeed.ts |
| KI-55 | WALL | MEDIUM | A whole-board change (pressure banner) reaches the wall on the next poll (up to a minute) because R06 pushes nothing without a service id | routes_events.py:5; board_projector.py |
| KI-88 | CAP | MEDIUM | Crash after bus.schedule and before the sequence is stored schedules a second message | workers/outbox_relay.py _schedule, _record_published |
| KI-89 | CAP | MEDIUM | `ScheduledWorkRepository.save` writes every field, so a cancel committed between read and save is overwritten | graph_store/scheduled_work_repository.py |
| KI-102, KI-104 | CAP | MEDIUM | After an out-of-range reply that triggers a recheck, a following Y still confirms the old figure; a lost cache entry has no test | handle_inbound_text.py |
| KI-103 | CAP | MEDIUM | Bus publish and schedule calls have no timeout; one poison row backs off its whole tenant | workers/outbox_relay.py |
| KI-133 | CAP | MEDIUM | A receipt that beats the send's provider-id write is lost and the record stays `sent` | workers/delivery_tracker.py |
| KI-137 | CAP | MEDIUM | A report cancels the ladder of the service and the latest prompt per role, not every older prompt | application/use_cases/missed_report_ladder.py |
| KI-287 | CAP | MEDIUM | Phoned path of ResolveReportFlag records through ReportCapacity, not RecordAdvisorPhoned | application/use_cases/resolve_report_flag.py |
| KI-388 | CAP | MEDIUM | A prompt delivered before a suspension is skipped only by SendPrompts' own check (H-137) | send_prompts.py |
| KI-415 | CAP | MEDIUM | The echo's times (format_hhmm, next_due) use London, not the tenant's zone | application/use_cases/report_capacity.py |
| KI-24 | CAP | LOW | A losing racer's Conflict label is misleading | send_prompts.py |
| KI-30 | CAP | LOW | `_waiting` (C10 list) compares the effective time with the prompt time | handle_inbound_text.py (_waiting) |
| KI-33 | CAP | LOW | Recheck cache key written after the commit; a failed cache write leaves a repeat out-of-range reply replaying | handle_inbound_text.py:1097 (_tidy_cache) |
| KI-35 | CAP | LOW | `_UnitOfWorkIdempotency.put` is unused (dead code) | routes_board.py |
| KI-36 | CAP | LOW | Order of authentication and path validation for an invalid service id is untested | routes_board.py |
| KI-97 | CAP | LOW | Pin the privacy-guard refusal path of the grouped C9 text with a test | application/use_cases/send_prompts.py |
| KI-101 | CAP | LOW | One-open-flag rule is only checked in the use case | report_flags.py |
| KI-141 | CAP | LOW | Duplicate inbound text can write extra "recorded" audit events | handle_inbound_text.py |
| KI-149 | CAP | LOW | `UnitOfWorkIdempotency` duplicated in routes_services and routes_board; Observation search returns only the latest report | routes_services.py, concurrency.py |
| KI-159, KI-160 | CAP | LOW | Duplicate `number_after_prompt` in link_access and HandleInboundText; RenewLink imports private send_prompts names | link_access.py, send_prompts.py |
| KI-173 | CAP | LOW | D15 email footer lacks "Replies to this address are not read." | adapters/outbound/email_smtp footer template |
| KI-174 | CAP | LOW | Email footer test asserts two of three sentences; href escaping untested | tests/unit/adapters/outbound/email_smtp |
| KI-189 | CAP | LOW | Failure `errorCode` stored but not read back into the Communication dataclass | communication_repository.py |

Hazard rows closed by this bundle (the hazard-log row is updated by B12 when the tests pass):

| Hazard | Sev | What | Evidence |
|---|---|---|---|
| H-46 | TBD | Provider accepts, commit fails, redelivery texts twice: needs a fault-injection test and a send-once guard (KI-185) | built by I10; the control gap is in What |
| H-137 | TBD | A prompt delivered before suspension still sends (KI-388); SendPrompts re-checks suspension only | built by U36; the control gap is in What |

#### B3 TENANT-CONFIG: tenant policy, zone, closures, lifecycle and the tenancy kernel

- **Model:** Sonnet (tenancy, thresholds, lifecycle). **Size:** XL, about 28 h (58 rows, most small).
- **Waits for:** After B1 (container.py and bootstrap/areas wiring). W9A is merged (offboarding, purge, network admin). No running W9 bundle touches its files.
- **Files it owns:** backend/src/diucs/application/use_cases/{report_flags,setup_service_by_lead,criteria_reviews,change_reporter_number,suspend_service,week_summary,tenant_admin,tenant_suspend,tenant_invariants}.py, application/{tenancy,tenant_settings,provisioning}.py, domain/rules/{opening_hours,holidays,tenant_lifecycle}.py, domain/model/{tenant_settings,network}.py, graph_store/{driver,mapper,resource_store,relationship_matrix,migrations_tenant,scope_list_repository,credential_store,tenant_config_repository,tenant_directory}.py, bootstrap/{areas,provisioning}.py, workers/tenant_binding.py, fhir_rest/{routes_public,routes_board}.py, adapters/testing/fixed_ids.py
- **Rows:** 58 known issues, 2 hazards.
- **Ordered task list** (red tests first, per the build-wave rules):
  1. Tenancy kernel hardening with tests: clear refusal for a unit shared by two tasks, cross-task claim test, SequentialIds prefix, canonical approver refs, planted tenantIdStart/End, Grant owner tenant, binds_tenant proof, TenantNotBound not swallowed in BoardProjector, refuse placeholder writes for ids the tenant does not hold, refusal cases for the four hand-checked relationships, empty-string tenantId backfill and DDL parameters (KI-37, 39, 48, 75, 105, 130, 143, 144, 253, 256, 338, 340, 418).
  2. Thread the tenant policy and zone: the seven use cases that still use the default policy, first_prompt_at, criteria review and cover end times, holidayRegion setting, closures honoured by is_in_hours, the ladder and the board, calendar 2028 (KI-346, 347, 447, 449, 592, 593, 594). Highest value: closures.
  3. Profile and display: organisation part on $board, support-sharing flag and policy on the public profile, minutes per avoided call per tenant, the tenant's area as a record, suspend wording (KI-50, 281, 409, 495, 511, 557, 742, 386, 500).
  4. Suspension and lifecycle: hold instead of dead-letter messages for a suspended tenant, reschedule booking timers on resume, reconcile a registry write whose audit commit failed, daily invariant job per tenant seeded at activation, status hints, second operator or network check at activation (KI-595, 596, 508, 599, 425, 426, 427, 512, 514, 510, 252).
  5. First administrator: consume the tenant-admin invitation at sign-in and give the account the tenant-admin role (KI-509, KI-532; tenant_access.py makes the invitation, nothing consumes it).
  6. Registry and tests: reconcile Tenant registry fields with the config version, host and Entra directory id (KI-334, 538); two-tenant tests that were never written (KI-93, 289, 478, 479, 480, 506, 834).

| Rows | Area | Sev | What | Evidence |
|---|---|---|---|---|
| KI-346 | TEN | HIGH | Seven use cases still call their rules without a tenant policy (flags, booking reply-by and phone prompt, ...) | application/use_cases/{report_flags,request_booking,...} |
| KI-592 | TEN | HIGH | Closures are honoured by the due times only: is_in_hours, ladder steps and the board do not take the closed predicate | domain/rules/opening_hours.py; use_cases/missed_report_ladder.py; board |
| KI-595 | TEN | HIGH | Messages for a suspended tenant are dead-lettered (tenant-unknown), not held: a reply or receipt during suspension is lost | workers/tenant_binding.py |
| KI-37 | TEN | MEDIUM | One open unit shared by two concurrent tasks raises a raw asyncio error instead of a clear refusal | backend/src/diucs/adapters/outbound/graph_store/driver.py |
| KI-50 | WALL | MEDIUM | `$board` sends no `organisation` part, so the header has no area name | routes_board.py / mapping (no "organisation" part emitted) |
| KI-252 | TEN | MEDIUM | `verify_chain` covers the bound scope only; nothing walks every tenant's chain on a schedule (TEN-031 job) | audit_neo4j/audit_log.py; tenant_invariants.py |
| KI-253 | TEN | MEDIUM | BoardProjector catches Exception and swallows TenantNotBound | application/use_cases/board_projector.py |
| KI-334 | TEN | MEDIUM | Registry fields Tenant.currentConfigVersion, host, entraDirectoryId are not written by TEN-026: reconcile | tenant_config_repository.py; tenant_directory.py |
| KI-338 | TEN | MEDIUM | Entry points that write through the resource store accept an id the tenant does not hold and create a placeholder instead of refusing | graph_store/resource_store.py _write_placeholders |
| KI-347 | TEN | MEDIUM | first_prompt_at (U15) passes the default policy: use ReadTenantConfig (TEN-026 exists) | setup_service_by_lead.py |
| KI-376 | REG | MEDIUM | Daily chain seeded only by the worker at start; tenant provisioning must seed it (TEN-028 seed_recurring_work exists: verify) | bootstrap/workers_main.py; application/provisioning.py |
| KI-386 | LEAD | MEDIUM | ReadTenantConfig is not wired into suspend_service: wording_for and policy still come from the caller | application/use_cases/suspend_service.py |
| KI-409 | TEN | MEDIUM | Tenant area is a setting keyed by tenant id, not tenant configuration, so a lead cannot change it | bootstrap/areas.py |
| KI-425 | TEN | MEDIUM | Daily invariant flag lives in the worker process; the API/console learn only from their own start-up check | application/use_cases/tenant_invariants.py |
| KI-427 | TEN | MEDIUM | Each active tenant runs the platform-wide check daily (N runs); a tenant created after start-up has no schedule until restart | Container.seed_daily_schedules; workers_main.py |
| KI-447, KI-449 | TEN | MEDIUM | Use cases and criteria review run time (07:00) and cover end time (22:00) compute London time, not the tenant's zone | application/use_cases/*; criteria_reviews.py; change_reporter_number.py |
| KI-478, KI-479, KI-480 | TEN | MEDIUM | Two-tenant tests for case/filter routes, registration review decisions and the alert workflow not written | tests/integration/adapters/inbound/fhir_rest/test_routes_cases.py etc. |
| KI-508, KI-599 | TEN | MEDIUM | A step whose registry write succeeded and audit commit failed leaves the change without its audit entry (saga): add a reconciliation | use_cases/tenant_admin.py; tenant_suspend.py |
| KI-509 | TEN | MEDIUM | (same as KI-532) the first sign-in that consumes the administrator's invitation and creates the account is not built | backend/src/diucs/application/use_cases/tenant_access.py:12-13 |
| KI-510 | TEN | MEDIUM | Activation does not require a second operator or check network membership or agreement | use_cases/tenant_admin.py |
| KI-511 | TEN | MEDIUM | ActivateTenant reads the area from settings, not a tenant record | bootstrap/areas.py |
| KI-532 | TEN | MEDIUM | The first administrator's invitation is not consumed at sign-in: the invitation is made (tenant_access.py) but nothing consumes it and gives the account the tenant-admin role (ENTRA_MAPPABLE_ROLES excludes it) | backend/src/diucs/application/use_cases/tenant_access.py:12-13; domain/model/tenant_records.py:71,283 |
| KI-557 | TEN | MEDIUM | Back-end public profile has no support-sharing flag, staff-account name or policy | routes_public.py |
| KI-593 | TEN | MEDIUM | The tenant's holidayRegion is not a stored tenant setting | domain/model/tenant_settings.py |
| KI-594 | TEN | MEDIUM | Bank-holiday calendar covers 2026 and 2027 only: add 2028 before 1 December 2027 | domain/rules/holidays.py |
| KI-596 | TEN | MEDIUM | Booking timers of a suspended tenant are not rescheduled on resume | use_cases/tenant_suspend.py |
| KI-834 | TEN | MEDIUM | Two-tenant integration tests for the four host-bound registration sign-in routes not written | tests/integration |
| KI-39 | TEN | LOW | A unit entered in one task and left in another keeps its claim: fails closed but untested; add a test | backend/src/diucs/application/tenancy.py claim_unit |
| KI-48 | TEN | LOW | `SequentialIds.scoped` does not validate the prefix, so two scopes can collide in one run | backend/src/diucs/adapters/testing/fixed_ids.py |
| KI-75 | TEN | LOW | `check_approvals` and `purge_blockers` compare approver refs as raw strings ("alice" vs "alice "): canonicalise | backend/src/diucs/domain/rules/tenant_lifecycle.py |
| KI-93 | TEN | LOW | Add the two-tenant grouped-prompt test now that people are stamped (TEN-009/011 done) | test_send_prompts_grouped.py |
| KI-105 | TEN | LOW | Backfill misses an empty-string tenantId; ROLLBACK_0031 builds DDL with f-strings | migrations_tenant.py |
| KI-116 | TEN | LOW | `deviceType` is a property, not a TYPE link to a Concept (DEC-001) | credential_store.py |
| KI-130 | TEN | LOW | `from_graph` rebuilds planted tenantIdStart/End as a period element | graph_store/mapper.py |
| KI-143 | TEN | LOW | Q-RES-MERGE-NODES scenario seeds no colliding placeholder key | resource_scenarios.py |
| KI-144 | TEN | LOW | `Q-SCOPE-ENSURE-LIST` creates the List with no `key` | scope_list_repository.py |
| KI-256 | TEN | LOW | `Grant` carries no owner tenant: owner approval check depends on the caller | domain/model/network.py |
| KI-264 | LEAD | LOW | A review date in the past is accepted by build_criteria | setup_service_by_lead.py build_criteria |
| KI-281 | EXEC | LOW | `minutes_per_avoided_call` is one process value, not per tenant | bootstrap/settings.py:19; week_summary.py:189 |
| KI-289 | TEN | LOW | Two-tenant test for the lead's flag list/resolve not written | tests/integration/application/test_resolve_report_flag.py |
| KI-335 | TEN | LOW | A draft passed by a newer draft stays `draft` for ever and cannot be discarded | ApproveTenantConfig |
| KI-340 | TEN | LOW | Four TENANT_LOCAL relationships check their target by hand with no executed refusal case | relationship_matrix.py |
| KI-418 | TEN | LOW | `binds_tenant` is a marker the runner cannot prove | workers/servicebus_runner.py |
| KI-426 | TEN | LOW | The board is not degraded by an invariant violation; per-tenant service-count reconciliation not built | tenant_invariants.py |
| KI-495 | EXEC | LOW | Time-back text not shown: minutes per avoided call not in the container | routes_alerts.py _WeekSettings |
| KI-500 | LEAD | LOW | Suspension sends no notice until a tenant's wording is set | routes_admin.py suspend_service |
| KI-503, KI-504 | TEN | LOW | DirectoryZones and DirectoryLinkBase read the directory on every call; alert evaluator reads zone inside the unit | application/tenant_settings.py; alerts.py |
| KI-512 | TEN | LOW | A tenant activated and not seeded waits for the next start for its daily jobs | application/provisioning.py |
| KI-514 | TEN | LOW | provision_tenant.py status does not suggest the command that fixes each fact | bootstrap/provisioning.py |
| KI-538 | TEN | LOW | Registry entraDirectoryId is not read by the exchange (a disagreeing value is not noticed) | exchange_token.py; tenant_directory.py |
| KI-598 | TEN | LOW | The serving process learns of a suspension at once only through the route's on_changed | bootstrap/provisioning.py |
| KI-600 | TEN | LOW | ResumeTenant reads every active service in one unit of work | use_cases/tenant_suspend.py |
| KI-742 | EXEC | LOW | Time-back line never shows a sum (minutes per avoided call not held per tenant) | frontend/lib/exec/weekServer.ts (minutesPerCall: null) |

Hazard rows closed by this bundle (the hazard-log row is updated by B12 when the tests pass):

| Hazard | Sev | What | Evidence |
|---|---|---|---|
| H-175 | TBD | Due, opening and quiet hours computed outside the tenant zone (KI-447, 449) | built by TEN-065; the control gap is in What |
| H-373 | LOW | Time-back figure shown before the tenant minutes are set (KI-742) | built by W41; the control gap is in What |

#### B4 BOOKING: booking pages, echoes, need wording, timers

- **Model:** Sonnet (patient-facing wording, booking safety). **Size:** M to L, about 14 h.
- **Waits for:** None. W9D, W9F and W9I touch no booking file.
- **Files it owns:** backend/src/diucs/application/use_cases/{request_booking,respond_to_booking,withdraw_booking,booking_reply_text,booking_effects}.py, adapters/inbound/link_pages/{booking_links,capacity_links}.py, domain/messages/templates.py, frontend/components/reporter/{BookingDecision,BookingChange,LinkLoader,LinkExpired}.tsx, frontend/components/advisor/{BookingCard,WithdrawalAlert,BookingPanel}.tsx, frontend/app/api/bff/links/, frontend/lib/links/
- **Rows:** 17 known issues, 9 hazards.
- **Ordered task list** (red tests first, per the build-wave rules):
  1. One plain-words table for the needs (DEC-134 item 2: `fall-no-injury` becomes "fall, no injury", and so on); B1, B2, B3, the booking pages and the clinical notice use it; boundary tests for one, two and three needs (KI-650, H-489).
  2. Link answers carry confirmedAt, cancelledAt and closedAt; the closed (410) page shows the coordination number; the booked, cancelled and expired views show the times (KI-169, 648, 649, 664, 665, H-486, H-488, H-499).
  3. Echoes B4, B5, B6 for email and push reporters (templates after Q2 sign-off); the reason for a decline replays (KI-356, KI-357, KI-361, H-135).
  4. Booking policy per tenant: withdrawal window, phone prompt and expiry minutes (KI-450, H-493); the change token issued in the same unit as the confirmation (KI-483); advisor acknowledgement stored (KI-451); responder and expired-booking lookups (KI-452, KI-453); an advisor who is not on the card sees the alert (H-496); a "delivered" word (H-494).
  5. Frontend: the link is read once (KI-651), validate the answer value and CSRF on renew (KI-178), the thanks address holds no token (KI-179).

| Rows | Area | Sev | What | Evidence |
|---|---|---|---|---|
| KI-357, KI-361 | ADV | HIGH | A booking echo (B4, B5, B6) to a service whose reporter is on email or push is not sent (H-135): templates exist only as text | application/booking_effects.py |
| KI-650 | REP | HIGH | Booking pages show the need as a code list ("fall-no-injury and frailty"): use plain words (DEC-134 item 2; also B1/B2 text) | backend/src/diucs/application/use_cases/request_booking.py:106-111 (`need.value` joined) |
| KI-356 | ADV | MEDIUM | SetDeclineReason has no replay record: a second submission with the same key is a Conflict | application/use_cases/respond_to_booking.py |
| KI-450 | ADV | MEDIUM | Withdrawal window is the default policy, not the tenant's | application/use_cases/withdraw_booking.py |
| KI-453 | ADV | MEDIUM | An expired booking older than the latest for its service is not reported as expired | booking_reply_text.py |
| KI-483 | ADV | MEDIUM | Change token issued in a second unit after RespondToBooking commits: a crash leaves a confirmed booking with no change link | booking_links.py BookingRequestLink.respond |
| KI-648, KI-664 | REP | MEDIUM | Booked/cancelled pages have no confirmation or cancellation time (back end adds confirmedAt/cancelledAt) | backend/src/diucs/adapters/inbound/link_pages/booking_links.py (no confirmedAt) |
| KI-649 | REP | MEDIUM | A booking opened after it closed shows no coordination (SPOA) number (H-486) | booking_links.py:132,147 (phone on live pages; 410 path has none) |
| KI-169 | REP | LOW | An expired or used link does not say when it closed (the 410 carries no closedAt) | backend/src/diucs/adapters/inbound/link_pages (closedAt not emitted) |
| KI-178 | SEC | LOW | BFF does not validate the answer `value`; renew route has no CSRF check | frontend/app/api/bff/links |
| KI-179 | SEC | LOW | Hand-made /thanks address shows a "recorded" message and holds the spent token | frontend thanks page |
| KI-451 | ADV | LOW | Advisor acknowledgement is not stored on the booking (only in the audit entry) | withdraw_booking.py |
| KI-452 | ADV | LOW | Decline attributed to a service, not the phone that declined | booking_reply_text.py |
| KI-651 | REP | LOW | A booking request reads the link twice (LinkLoader redirect) | frontend/components/reporter/LinkLoader.tsx |
| KI-665 | REP | LOW | Cancelled view has no time ("cancelled at 14:40") | BookingChange.tsx |

Hazard rows closed by this bundle (the hazard-log row is updated by B12 when the tests pass):

| Hazard | Sev | What | Evidence |
|---|---|---|---|
| H-135 | TBD | B4/B5/B6 echoes are text only; email and push reporters get none (KI-357) | built by U18, U20, U36; the control gap is in What |
| H-486 | MEDIUM | 410 carries no coordination phone (KI-649) | built by W19, W22; the control gap is in What |
| H-488 | MEDIUM | Stale coordination number on a closed page | built by W19, W22; the control gap is in What |
| H-489 | MEDIUM | Need shown as a code list (KI-650; request_booking.py:106-111) | built by W19; the control gap is in What |
| H-490 | LOW | A wave of booking links spends the 60 a minute tenant budget | built by W19, W22; the control gap is in What |
| H-493 | MEDIUM | Phone prompt and expiry use default 5 and 10 minutes, not the tenant policy (KI-450) | built by W20, W21; the control gap is in What |
| H-494 | MEDIUM | "Text sent" read as delivered: show delivery state (Communication deliveryStatus exists) | built by W20; the control gap is in What |
| H-496 | HIGH | An advisor not on the card when a withdrawal arrives does not see the alert (backstop is the shift lead escalation) | built by W21; the control gap is in What |
| H-499 | MEDIUM | Cancelled view lacks reference/time (KI-664, 665) | built by W22; the control gap is in What |

#### B5 REGISTRATION-CRITERIA: registration, review and criteria back end and pages

- **Model:** Sonnet for approval, criteria and registration persistence; mechanical for page fields. **Size:** L, about 20 h.
- **Waits for:** Needs the answers to Q6, Q38 and Q16/Q17 for four tasks; the rest is independent. Does not touch W9 files.
- **Files it owns:** backend/src/diucs/application/use_cases/{registration_draft,registration_submit,registration_record,registration_views,approve_registration,review_registration,approve_criteria,invite_reporter,scope_list}.py, graph_store/{service_repository,registration_repository}.py, fhir_rest/{routes_registration,routes_registration_views,routes_criteria,routes_criteria_views}.py, frontend/components/{register,owner}/, frontend/components/lead/registration/, frontend/lib/{register,registration,criteria}/, frontend/app/(owner)/
- **Rows:** 34 known issues, 8 hazards.
- **Ordered task list** (red tests first, per the build-wave rules):
  1. Persistence first: ServiceRepository.save keeps providedBy, location and coverage; a returned registration re-persists its edits; one Location per district; owner practitioner reuse; invitation closes at set-up; shift-lead post seeding or a clear refusal; district checked against the tenant area (KI-363, 367, 368, 370, 364, 365, 263, H-198).
  2. Fields R10 does not store: contactRole, partOf, site ODS and UPRN, specialty, appointment, notes, cover number, bed types, and the "Other" measure per Q38; remove the screen-only fields if not kept (KI-676, 680, 683, 806, 810, 823, H-354, H-357, H-359).
  3. Review: source of numberToCall per Q6 and refuse equality with the applicant's number; call-back role rule; decision timeline entries; approval-time re-check of the automatic checks; success-path test with a criteria rig; idempotency keys; registered device kept; I3 for email and push; scope-list flag after a decision (KI-700, 701, 824, 825, 455, 459, 460, 458, 373, H-144, H-363).
  4. Send-back: wording and channel per Q16, and tell the criteria owner when a change is sent back (KI-456, 278).
  5. Owner pages: /owner/criteria home and the services list, draft state per Q17, reviewed date and owner on the history, pending values on the overview, tries-left and lapsed-code answers, expected review times (KI-704, 705, 706, 820, 702, 670, 671, 685, 691).

| Rows | Area | Sev | What | Evidence |
|---|---|---|---|---|
| KI-263 | REG | MEDIUM | District list is not checked against the tenant's area (no area-districts on the Tenant node) | application/use_cases/setup_service_by_lead.py; bootstrap/areas.py |
| KI-278 | REG | MEDIUM | The owner is not told when a criteria change is sent back (no event) | application/use_cases/approve_criteria.py |
| KI-363 | REG | MEDIUM | ServiceRepository.save rewrites the whole HealthcareService, so a later profile save loses providedBy/location/coverageArea | graph_store/service_repository.py |
| KI-367 | REG | MEDIUM | Two registrations covering a new district at once can each write its Location | registration_submit.py |
| KI-368 | REG | MEDIUM | A registration sent back and submitted again is not re-persisted: edits after the first write are lost | registration_submit.py |
| KI-373 | REG | MEDIUM | A review does not change the scope list's flag (a `later` registration still has an in-pilot entry) | review_registration.py |
| KI-455 | REG | MEDIUM | Approval success path (all four checks pass, I3 queued) not tested: needs a criteria rig | tests/.../test_approve_registration.py |
| KI-458 | REG | MEDIUM | Test prompt I3 is text only; a role on email or push gets none | approve_registration.py |
| KI-459 | REG | MEDIUM | Registration commands take no idempotency key (repeat refused as InvalidTransition) | approve_registration.py |
| KI-460 | REG | MEDIUM | Registered device is not stored for the test answer; only the phone hash can match | approve_registration.py RecordTestAnswer |
| KI-676, KI-823, KI-806, KI-683 | REG | MEDIUM | Site ODS code, role, part-of, specialty, notes, cover number, bed types have no field in R10 and are collected but not saved | registration_draft.py (LocationStep/ServiceStep/ReportingStep) |
| KI-680 | REG | MEDIUM | Specialty, appointment-needed and notes are not saved (H-357) | ServiceForm.tsx |
| KI-700 | REG | MEDIUM | A call-back that is not confirmed or had no answer is refused unless a role is given (`$callback` requires spokeToRole) | backend routes_registration.py `$callback`; frontend/lib/registration/backend.ts recordCallBack |
| KI-702 | REG | MEDIUM | Overview additions (callBack, pathwayName, decision timeline) only partly served | frontend/lib/registration/types.ts; registration_views.py |
| KI-704, KI-705 | REG | MEDIUM | An owner's home /owner/criteria has no page and there is no list of the owner's services to return to | frontend/lib/auth/access.ts:22; app/(owner)/ has only criteria/[serviceId] |
| KI-262 | REG | LOW | Role names have no graph property | graph_store (PractitionerRole) |
| KI-268 | REG | LOW | Two concurrent adds of different names for one new service are not guarded beyond the list lock | application/use_cases/scope_list.py |
| KI-276 | REG | LOW | Invitation sent time taken as created_at: Registration has no separate sent time | domain/model/registration.py |
| KI-277 | REG | LOW | Reporting contact at submit read from the requester role only; a second reporter role unsupported | registration_draft.py _completeness |
| KI-279 | REG | LOW | Criteria history shows review-by, not change date (W7B DEC-800 added changedOn: verify and close) | criteria_repository.py; criteria_views.py |
| KI-364 | REG | LOW | A lead with no active shift-lead post cannot invite (NotAllowed): provisioning must seed the post or the refusal must say so | application/use_cases/invite_reporter.py |
| KI-365 | REG | LOW | An invitation whose registration was never answered stays open after set-up completes | invite_reporter.py |
| KI-370 | REG | LOW | The owner's practitioner is a new person on every registration | registration_submit.py |
| KI-457 | REG | LOW | Call-back, scope and criteria steps carry no time of their own on the record | registration_record.py |
| KI-670, KI-671 | REG | LOW | The back end gives no tries-left count on a wrong code and one answer for a lapsed code and five wrong tries (W8C K1) | routes_identity.py verify_code; reporter_identity.py:125 tries_left exists |
| KI-685 | REG | LOW | Submitted page shows no expected review time (no source) | frontend/app/register/[id]/submitted/page.tsx |
| KI-691 | REG | LOW | "We aim to review within [time]" has no source | InReview.tsx |
| KI-820 | REG | LOW | The criteria history sends no reviewed date or owner | routes_criteria.py _view_basic |
| KI-825 | REG | LOW | Decision timeline has no call-back or scope-decision entries (Provenance has no read) | registration_views.py |

Hazard rows closed by this bundle (the hazard-log row is updated by B12 when the tests pass):

| Hazard | Sev | What | Evidence |
|---|---|---|---|
| H-144 | TBD | Approval trusts a stored automatic-check flag: re-run at approval (U29) | built by U28, U29; the control gap is in What |
| H-198 | TBD | Activation loses provider/location/coverage the registration wrote (KI-363) | built by U29; the control gap is in What |
| H-357 | MEDIUM | Specialty, appointment-needed and notes are collected and not saved (KI-680) | built by W25, W26; the control gap is in What |
| H-358 | MEDIUM | District coverage check refusal not shown at review | built by W25, W26; the control gap is in What |
| H-502 | MEDIUM | Live service preview shows a fixed "Accepting" word | built by W27, W35; the control gap is in What |
| H-503 | MEDIUM | "All correct" confirms the reporting phone with no back-end check against the prompt number | built by W27, R11; the control gap is in What |
| H-363 | MEDIUM | Call-back goes to the applicant's own number: needs the register number source (Q6; KI-701) | built by W29; the control gap is in What |
| H-354 | LOW | contactRole and partOf shown, not kept (KI-676) | built by W54, W24; the control gap is in What |

#### B6 ADVISOR-CLINICAL: case, options, advice, summary, replay

- **Model:** Sonnet (clinical safety). **Size:** L, about 22 h.
- **Waits for:** None. W9G and W9H are merged; W9D, W9F and W9I touch none of these files. Tasks marked Q wait for Q5 and Q7.
- **Files it owns:** backend/src/diucs/application/use_cases/{open_case,filter_options,record_decline,advisor_phoned,clinical_advice,audit_replay,planning_analysis,record_outcome}.py, graph_store/{case_repository,criteria_repository,clinical_request_repository,service_positions}.py, adapters/outbound/travel_time/, fhir_rest/{routes_cases,case_mapping,clinical_mapping,routes_clinical,capability}.py, frontend/lib/advisor/, frontend/components/{advisor,clinical}/
- **Rows:** 29 known issues, 5 hazards.
- **Ordered task list** (red tests first, per the build-wave rules):
  1. Safety first: the score write refuses a Dx code not on the Pathways list, and the picker uses the same shape [A-Z0-9]{2,10} (KI-247, 625, 816, H-85); score correction per Q7 (KI-815).
  2. Case concurrency: a case version, ETag and 412 (H-192); the open as one unit; the phoned report and case check in one unit (KI-400, 354).
  3. Options: service phone, coverage radius, travel legs and patient point per Q5; cache failure falls back to the straight-line estimate; wire the TravelTime switch; estimate outside the unit of work; network options view-only from the projection (KI-626, 627, 801, 814, 791, 200, 202, 203, 350, 349, 181, 794).
  4. Summary and replay: route build_summary for an open case (H-322), criteria history includes drafts (KI-180), the replay shows names as shown and "+2" (KI-474, 475, H-190), planning order by travel (KI-476, 477, H-193), decline listing by use case (KI-352).
  5. Clinical queue: a lapsed lock is released, advice mapped to Task.output, presence TTL tested, the advice sentence names the service, CapabilityStatement lists HealthcareService operations (KI-233, 232, 473, 768, 399).

| Rows | Area | Sev | What | Evidence |
|---|---|---|---|---|
| KI-247 | CLIN | HIGH | The score write does not check a Dx code against the Pathways list (H-85) | Observation write path; routes_cases.py |
| KI-200 | ADV | MEDIUM | The container has no TravelTime switch: wire `travel_time_provider` now that the straight-line fallback (I11) is on the tree | bootstrap/container.py |
| KI-202 | ADV | MEDIUM | Cache errors in travel estimate fail the whole options list: fall back to the straight-line estimate | travel_time/routing.py |
| KI-232 | CLIN | MEDIUM | Advice is stored as Task properties, not Task.output, so a FHIR read of the Task does not show it (clinical_mapping now maps advice: verify) | clinical_request_repository.py; clinical_mapping.py |
| KI-233 | CLIN | MEDIUM | A lapsed clinical lock stays `taken` until return_if_idle is saved | clinical_advice.py |
| KI-349 | NET | MEDIUM | Network options (view-only services from the projection) for FilterOptions not built | application/use_cases/filter_options.py |
| KI-400 | ADV | MEDIUM | Open-case route is two units: a failure between leaves a case with no details | routes_cases.py |
| KI-475 | CLIN | MEDIUM | Replay does not show the "+2" over-capacity figure (W9G DEC-1031 records over_by for new displays; replay not updated) | audit_replay.py (H-190) |
| KI-476 | CLIN | MEDIUM | Planning best-fit rule uses board order, not travel order (H-193) | planning_analysis.py |
| KI-625 | ADV | MEDIUM | The Pathways code is shape-checked only at the BFF; a code not on the list is accepted (see H-85) | frontend/lib/advisor/scores.ts PATHWAYS_CODE; routes_cases.py |
| KI-626, KI-627, KI-801 | ADV | MEDIUM | $filter-options sends no service phone, coverage radius or travel legs; travel line is a range | backend/src/diucs/adapters/inbound/fhir_rest/case_mapping.py (no coverageRadiusKm); frontend/lib/advisor/options.ts |
| KI-768 | CLIN | MEDIUM | Advice sentence names the advice by general label, not the service: a request does not record the service under consideration | frontend/components/advisor/AskClinicalDialog.tsx; fragments/W9G.md K4 |
| KI-791 | ADV | MEDIUM | The map shows no pins: positions, coverage, patient point not sent by the back end (partly served W7A) | routes_cases.py _filter_to_fhir |
| KI-814 | ADV | MEDIUM | (duplicate of 626) $filter-options phone, coverage and legs | case_mapping.py |
| KI-816 | ADV | MEDIUM | The Pathways Dx shape the picker offers is wider than the back end's [A-Z0-9]{2,10} | backend domain/model/scores.py; frontend lib/advisor/scores.ts |
| KI-180 | ADV | LOW | Criteria `history` omits drafts/pending versions and returns nothing when no version is current | graph_store/criteria_repository.py |
| KI-181 | NET | LOW | Network variant of the candidate filter not built (TEN-051/053 now exist) | criteria_repository.py; filter_options.py |
| KI-203 | ADV | LOW | Cache key carries the tenant twice (harmless): reconcile with the Redis prefix | routing.py, redis_cache.py |
| KI-312 | ADV | LOW | R08 prompt test 5 contradicts the required refusal text: amend the test | tests/integration/.../test_routes_lead.py |
| KI-350 | ADV | LOW | Travel estimate awaited inside the unit of work | filter_options.py |
| KI-352 | CLIN | LOW | ListDeclinesSince reads every audit record of the tenant | application/use_cases/record_decline.py |
| KI-354 | ADV | LOW | Case check and phoned report run in two units: a case closed between them is still accepted | application/use_cases/advisor_phoned.py |
| KI-399 | ADV | LOW | CapabilityStatement registers ServiceRequest create/update only | fhir_rest/capability.py |
| KI-473 | CLIN | LOW | Presence TTL not tested by expiry | clinical_advice.py |
| KI-474 | CLIN | LOW | Audit replay shows current service names, not as shown | audit_replay.py |
| KI-477 | CLIN | LOW | Planning window query returns every audit entry of two use cases | planning_analysis.py |
| KI-794 | NET | LOW | Network pins carry no organisation on the card (needs the network option read) | OptionsMap.tsx; filter_options.py |

Hazard rows closed by this bundle (the hazard-log row is updated by B12 when the tests pass):

| Hazard | Sev | What | Evidence |
|---|---|---|---|
| H-85 | TBD | Score write accepts a Dx code not on the Pathways list (KI-247) | built by the score-write task (not R16); the control gap is in What |
| H-190 | TBD | Replay cannot show the "+2" over-capacity figure (KI-475; W9G records over_by for new displays) | built by U42; the control gap is in What |
| H-192 | TBD | No case version: concurrent PUTs on one open case are last-write-wins (routes_cases.py DEC-398) | built by R07; the control gap is in What |
| H-193 | TBD | Planning best-fit uses board order, not travel order (KI-476) | built by U43; the control gap is in What |
| H-322 | MEDIUM | Copied referral omits booking, destination, data age (W8A K6: build_summary not routed) | built by W15; the control gap is in What |

#### B7 LEAD-EXEC-REPORTER: alerts, safety concern, lead and reporter edges

- **Model:** Sonnet for alerts and the safety concern; mechanical for the rest. **Size:** L, about 22 h.
- **Waits for:** After B3 (lead_views.py policy, change_reporter_number.py). W9H is merged; W9I touches components/lead for screens only.
- **Files it owns:** backend/src/diucs/application/use_cases/{alerts,subscribe_alert,safety_concern,move_service,remove_person}.py, graph_store/{alert_repository,push_subscription_repository,safety_report_repository}.py, fhir_rest/{routes_alerts,routes_lead,routes_lead_views,routes_identity,routes_reporter,reporter_app}.py, workers/message_senders.py (cover rows only), frontend/components/{exec,lead}/ (not components/lead/Screens*), frontend/lib/{exec,lead}/
- **Rows:** 44 known issues, 6 hazards.
- **Ordered task list** (red tests first, per the build-wave rules):
  1. Alerts: escalated list for the deputy, lock or version on concurrent preference saves, quiet-hours default per Q15, system-pressure alert, single-alert read, acknowledger and "+N since" on the detail (KI-229, 819, 494, 731, 463, 497, 738, 739, 740, H-365, H-368).
  2. Deputies and roles: the exec role on a practitioner, exec and lead sessions' role code, a leadership picker in the escalation form (KI-384, 380, 732, 744, H-366).
  3. Safety concern: officer role and contact modelled, replay fingerprint includes the text, page route stored, requester and focus as relationships, SPOA number on the confirmation (KI-394, 395, 397, 818, 396, 774).
  4. Lead: choose the post when a service has several reporters, flag detail lines, move edge cases, the list of people awaiting a call-back, lift no-reporter on set-up, invitation steps (KI-315, 749, 389, 391, 392, 393, 469, 466, 832, 833).
  5. Reporter edges: push delete of an unknown device, duplicate push on retry, device id aliasing, lost-phone verify answers (410 and 429), pending acceptance state, cover on an email post or from a service move, service names in the set-up summary (KI-235, 292, 410, 499, 835, 855, 856, 838, 728).

| Rows | Area | Sev | What | Evidence |
|---|---|---|---|---|
| KI-229 | CLIN | MEDIUM | An escalated alert owned by the deputy is not an open alert for the deputy (open_for_owner lists new only; `status=escalated` list is empty) | graph_store/alert_repository.py Q-ALERT-OPEN-FOR-OWNER |
| KI-292 | REP | MEDIUM | A transient failure re-sends to devices that already accepted (H-157, accepted for the pilot) | PushMessageSender |
| KI-315 | LEAD | MEDIUM | A service with several reporter roles: change applies to the first active one (W8D-K: no post chosen from the list) | setup_service_by_lead.py; routes_lead.py |
| KI-380 | EXEC | MEDIUM | Exec and lead sessions have no practitioner role code: PinSignInResult.role is None for them | pin.py |
| KI-384 | EXEC | MEDIUM | The exec role is not on a practitioner in the graph, so an exec cannot be a deputy | use_cases/subscribe_alert.py DEPUTY_CODES |
| KI-389 | LEAD | MEDIUM | CodeVerifier is not adapted to U25 VerifyTextCode in the container (the move page is built) | application/use_cases/move_service.py; container.py |
| KI-391 | LEAD | MEDIUM | A move from a practitioner who holds a service only as a cover is not handled | CompleteServiceMove |
| KI-394, KI-395 | CLIN | MEDIUM | K3 push to the safety officer needs a VAPID key and the officer's role record and contact are not modelled (recorded as `no-contact`) | application/use_cases/safety_concern.py |
| KI-461 | CLIN | MEDIUM | K3 push recorded as outbound SendMessage with the owner's practitioner id: the push sender must resolve a practitioner's subscriptions (W9H built a person-push path: verify) | use_cases/alerts.py _push; workers/message_senders.py |
| KI-463 | EXEC | MEDIUM | System-pressure alert not raised (needs the pressure from the board); network-pressure alert not built | use_cases/alerts.py |
| KI-466 | LEAD | MEDIUM | Nothing lifts the no-reporter flag when a new reporter is set up | remove_person.py; setup_service_by_lead.py |
| KI-469 | LEAD | MEDIUM | The lead cannot list people with a new phone waiting for a call-back | remove_person.py |
| KI-481 | CLIN | MEDIUM | Check the alert consumer is wrapped in TenantBoundConsumer in container alert_timer_handlers | bootstrap/container.py:352 |
| KI-499 | REP | MEDIUM | The lost-phone verify answers 400 for a lapsed or locked code, not 410/429 | routes_identity.py verify_new_phone |
| KI-738, KI-739, KI-740 | EXEC | MEDIUM | Alert detail lacks "Reported by", the acknowledger, a single-alert read and "+4 since 13:10" | frontend/components/exec/ServiceDetail.tsx; lib/exec/alerts.ts; routes_alerts.py |
| KI-819 | EXEC | MEDIUM | status=escalated on the alert list is empty (open list holds new alerts only) | alert_repository.py open_for_owner |
| KI-833 | TEN | MEDIUM | Lead overview and board read the default policy and London, not the tenant's | lead_views.py |
| KI-835 | REP | MEDIUM | pendingAcceptance is always false: a service the lead adds has no stored waiting state | reporter_app.py |
| KI-855, KI-856 | REP | MEDIUM | A cover made by a service move keeps no number (text recorded no-contact); a cover on an email-channel post reaches no one | move_service.py; message_senders.py |
| KI-230 | EXEC | LOW | No unique constraint on AlertSubscription (practitionerId, tenantId) | migrations_tenant.py |
| KI-235 | REP | LOW | `delete` of an unknown push device is silent | push_subscription_repository.py |
| KI-282 | EXEC | LOW | On-time numerator counts reports and a prompt's due time is its sent time | application/use_cases/week_summary.py |
| KI-288 | LEAD | LOW | ListReportFlags raises NotFound when a flag's service/report is missing (untested) | resolve_report_flag.py |
| KI-290 | LEAD | LOW | Phoned-path integration test reads via capacity.latest and a later report would hide it | test_resolve_report_flag.py |
| KI-392 | LEAD | LOW | Start and add move commands have no idempotency key | StartServiceMove, AddServiceToPhone |
| KI-393 | LEAD | LOW | The live check before a prompt reaches a new phone is not applied in AddServiceToPhone | AddServiceToPhone |
| KI-396 | CLIN | LOW | Task statements hold requester/owner/focus as properties, not relationships (FHIR mapper) | graph_store/safety_report_repository.py |
| KI-397 | CLIN | LOW | A replay under the same key with another text returns the first report (text not in the fingerprint) | safety_concern.py |
| KI-410 | REP | LOW | Push device ids are app-<device id> at the edge: a second caller saving under the plain id makes a different device | routes_identity.py |
| KI-728, KI-838 | REP | LOW | Added-service and cover pages name the service generically; the set-up summary shows one post of several | reporter_app.py; app/(reporter)/app/services/[id] |
| KI-731, KI-494 | EXEC | LOW | Two concurrent saves of alert preferences can both pass the version check (BFF read-then-write, back end no lock) | frontend/lib/exec/subscriptions.ts; routes_alerts.py save_subscription |
| KI-732, KI-744 | EXEC | LOW | Deputy is a hand-typed practitioner id: wire the leadership picker (GET /fhir/Practitioner?role=leadership is served) | frontend/components/exec/EscalationForm.tsx |
| KI-749 | LEAD | LOW | The open-flag list carries no figure or reason detail | frontend/lib/lead/flags.ts; routes_admin.py |
| KI-774 | CLIN | LOW | The SPOA number is not on the safety-concern confirmation (coordinationPhone is served) | frontend/components/help/SafetyConcernForm.tsx |
| KI-802 | EXEC | LOW | "Your time back" weekly count not built (needs a back-end count) | frontend/components/learn |
| KI-818 | CLIN | LOW | A problem report stores no page route | safety_concern.py ReportProblem |
| KI-832 | LEAD | LOW | Invitation set-up steps are approximations (for example "installed" is any active device) | lead_views.py |

Hazard rows closed by this bundle (the hazard-log row is updated by B12 when the tests pass):

| Hazard | Sev | What | Evidence |
|---|---|---|---|
| H-365 | LOW | Lost update on a personal alert preference (KI-731) | built by W39; the control gap is in What |
| H-366 | MEDIUM | An alert is switched on with nobody to escalate to (deputy picker) | built by W39; the control gap is in What |
| H-368 | HIGH | An executive reads a stale board figure as current: show the age on every attention line | built by W40; the control gap is in What |
| H-369 | MEDIUM | Exec acknowledges another person's alert: back-end refusal tested; add route-level two-person test | built by W40; the control gap is in What |
| H-371 | MEDIUM | Service name from one board beside an alert from another | built by W40; the control gap is in What |
| H-374 | LOW | Monday summary switched on on a stale save | built by W41; the control gap is in What |

#### B8 SECURITY-PRIVACY: at-rest encryption, token revocation, flood and enumeration controls

- **Model:** Sonnet (security, privacy). **Size:** L, about 28 h (two new adapters, then the hardening).
- **Waits for:** The two adapters are new files and can start now. The rest waits for W9I: it changes fhir_rest/auth.py, credential_store.py, pair_wall_screen.py, routes_screens.py and routes_services.py, which W9I also changes. Do task 4 first if W9I is late (mapping.py and errors.py are free).
- **Files it owns:** backend/src/diucs/{domain/model/people.py, domain/rules/push_endpoint.py, application/use_cases/{pin,text_code,pair_wall_screen}.py, application/rate_limits.py, adapters/outbound/graph_store/{contact_store,credential_store,link_token_repository}.py, adapters/outbound/cache_redis/redis_cache.py, adapters/outbound/bus_servicebus/event_bus.py, adapters/inbound/fhir_rest/{auth,errors,mapping,routes_identity,routes_services}.py, adapters/inbound/link_pages/capacity_links.py}, frontend/lib/{reporter,session}/signOut.ts
- **Rows:** 25 known issues, 2 hazards.
- **Ordered task list** (red tests first, per the build-wave rules):
  1. Key Vault adapter behind the SecretStore port (deployment-plan item 3), named `<kind>/<tenant>/<name>`, against a fake transport; production no longer starts with NoSecrets (KI-186, KI-443). The live run needs a real Key Vault (C).
  2. Real Entra ID verifier behind IdentityVerifier: signature, issuer, audience, expiry and nonce against a fake JWKS; per-directory keys; the staff and operator app registrations are configuration (KI-531, KI-612). The live check needs a real tenant (C).
  3. DEC-856 option (a): seal ProtectedContact.value under a per-tenant key from the secret-store port (a fake until the vault adapter exists), with a migration, the key reference on the node, delete and retention for removed people and call-back numbers (KI-859a, 372, 468).
  4. Revocation: a removed or signed-out reporter's token stops working on every route (epoch check or short life), the session is read on each request, a sign-out ends the server session and push subscription, PIN session slides or ends (KI-402, 470, 404, 561, W8E-K1, W8E-K2).
  5. Enumeration and flood: audit cost of unknown identities, per-address throttles and the 60-call limiter, 400 versus 403 host oracle, 415 on a body-less POST, SSRF name resolution, nested link keys in the bus deny-list, device un-revoke, codes only for known numbers, a durable PIN attempt window, stolen-SIM routing (KI-379, 406, 114, 438, 118, 165, 329, 407, 332, 381, 467, H-55, H-97).
  6. Input and outage: non-ASCII digits in staff text, OverflowError on far-out dates and HEAD, a Redis outage answers 503 not 500 (KI-12, 158, 242); retention sweep of used and expired pairing link tokens (KI-111).

| Rows | Area | Sev | What | Evidence |
|---|---|---|---|---|
| KI-186 | INF | HIGH | Production has no Key Vault adapter: container.secrets is NoSecrets so every text is refused. Build the adapter against the SecretStore port with a fake transport (deployment-plan item 3); the live run is C (a real Key Vault) | backend/src/diucs/bootstrap/container.py:482 (class NoSecrets) |
| KI-402, KI-470 | SEC | HIGH | A removed or signed-out reporter's BFF token works on every route except the identity push routes until it expires (no revocation) | backend/src/diucs/adapters/inbound/fhir_rest/auth.py current_actor (DEC-094 item 4) |
| KI-443 | INF | HIGH | Production secret store is NoSecrets: no text or email is sent until the Key Vault adapter is given to build (same task as KI-186) | bootstrap/container.py:482 |
| KI-467 | SEC | HIGH | A text from the number of a person whose new phone waits for a call-back is still routed to their services (stolen SIM) | handle_inbound_text.py services_for_phone_hash |
| KI-531 | SEC | HIGH | The real Entra verifier (signature, issuer, audience, expiry, nonce) is not built: write it behind IdentityVerifier against a fake JWKS (deployment-plan item 4); the live check is C (a real Entra tenant) | backend/src/diucs/application/ports/outbound/identity_verifier.py |
| KI-612 | SEC | HIGH | No sign-in works outside the fakes until the real Entra verifier exists (same task as KI-531) | identity_verifier.py |
| KI-859a | SEC | HIGH | DEC-856 option (a): application-level encryption of ProtectedContact.value under a per-tenant key from the secret-store port, built against a fake; a condition for go-live of any tenant beyond the pilot | backend/src/diucs/adapters/outbound/graph_store/contact_store.py (no seal/encrypt) |
| KI-111 | WALL | MEDIUM | Nothing removes expired or used pairing link tokens or never-collected screens: add the retention sweep | pair_wall_screen.py, link_token_repository.py |
| KI-114 | SEC | MEDIUM | No per-address throttle on pairing routes beyond the per-tenant allowance | pair_wall_screen.py; routes_screens.py (start/claim limits exist, TEN-040 H-079) |
| KI-158 | SEC | MEDIUM | An effectiveDateTime of 9999-12-31 or 0001-01-01 with an offset returns 500 (OverflowError); HEAD answers 405 though Allow lists HEAD | backend/src/diucs/adapters/inbound/fhir_rest/mapping.py:319-322 (only ValueError caught); routes_services.py:345 |
| KI-242 | SEC | MEDIUM | A Redis outage reaches the pairing routes as redis.exceptions.ConnectionError and answers 500, not 503 | adapters/outbound/cache_redis/redis_cache.py (no RedisError mapping); fhir_rest/errors.py |
| KI-332 | SEC | MEDIUM | Deny-list stops link keys at top level only; nested link not seen | event_bus.py check_publishable |
| KI-372 | SEC | MEDIUM | Call-back numbers are stored under callback-<id> and nothing lists or deletes them (retention) | contact_store.py |
| KI-379 | SEC | MEDIUM | Audit entry of an unknown-identity attempt costs the chain head's lock, so a flood is throttled only by the limiter | pin.py |
| KI-404 | SEC | MEDIUM | The edge creates a session but nothing reads it on a request: the back end reads only the BFF bearer (token exchange TEN-043 exists) | fhir_rest/auth.py |
| KI-406 | SEC | MEDIUM | Status and PIN routes for an unknown device cost one audit entry each; a flood across many addresses is throttled only per address | pin.py |
| KI-407 | SEC | MEDIUM | A push endpoint whose name resolves to an inside address passes the structural check (SSRF) | domain/rules/push_endpoint.py |
| KI-438 | SEC | MEDIUM | Limiter takes up to 60 cache calls for the last request of a window: replace with a counter | application/rate_limits.py |
| KI-468 | SEC | MEDIUM | A removed person's protected contact rows stay: the contact store has no delete | contact_store.py |
| KI-561 | REP | MEDIUM | Sign-out does not delete the server-side push subscription (W34/W9H route exists DELETE /identity/push-subscription) | frontend/lib/session/signOut.ts |
| KI-12 | SEC | LOW | `check_staff_text` counts non-ASCII digits as digits | backend/src/diucs/domain/model/people.py:52 (`character.isdecimal()`) |
| KI-118 | SEC | LOW | Cache error at limiter release surfaces raw ConnectionError (R15 maps to 503 for the routes only) | pair_wall_screen.py |
| KI-165 | SEC | LOW | A malformed POST gets 400 on an active host and 403 on an unknown host: equalise | link_pages/capacity_links.py |
| KI-329 | SEC | LOW | A body-less POST gets 415 from the media-type middleware (client must send {}) | fhir_rest/errors.py BodyTypeMiddleware |
| KI-381 | SEC | LOW | A revoked device cannot be un-revoked: support re-pair path | credential_store.py |

Hazard rows closed by this bundle (the hazard-log row is updated by B12 when the tests pass):

| Hazard | Sev | What | Evidence |
|---|---|---|---|
| H-55 | TBD | A Redis reset restarts the PIN rate-limit window (U32 needs a durable attempt count; DEC-072 reads attempts under the write lock) | built by U32, W35; the control gap is in What |
| H-97 | TBD | A code is stored for an unknown number (I13/U25) | built by U25, I13; the control gap is in What |

#### B9 FRONTEND-FOUNDATION: tenant words, id-route scoping, CSRF, sign-out, polish

- **Model:** Mechanical, except the idScoped and CSRF tasks (Sonnet). **Size:** M, about 14 h.
- **Waits for:** Last frontend bundle. Wait for W9D (it changes frontend/lib/auth, proxy.ts, lib/bff, test/guards), W9I (components/lead, lib/screens) and W9F (app layout, lib/telemetry), and run after B4 and B5 (component text).
- **Files it owns:** frontend/{lib/auth/csrf.ts, proxy.ts, test/guards/, lib/tenant/, lib/board/format.ts, lib/reporter/times.ts, lib/session/signOut.ts, components/tour/, components/ui/Dialog.module.css, app/register/page.tsx, components/register/ (words only), components/reporter/ (words only), app/layout.tsx (TenantWords provider)}
- **Rows:** 23 known issues, 0 hazards.
- **Ordered task list** (red tests first, per the build-wave rules):
  1. idScoped on the 22 id routes with the back end answering 404 for another tenant's id (KI-543, 830, 843); a staff CSRF token tied to the sign-in (KI-547); the invitation token out of the /register address, /register/[id] guarded by the proxy, no inline style (KI-672, 673, 248).
  2. TenantWords provider in the root layout and the nine remaining epr-name files; time zone and locale from the profile (KI-553, 840, 560); sign-out and unpair controls (KI-562).
  3. Polish: wall tile wording and surge layout, live region, tour buttons, owner reload step, reporter channel form, dialog backdrop token, API details after reload (KI-151, 152, 56, 798, 799, 800, 707, 726, 631, 688).

| Rows | Area | Sev | What | Evidence |
|---|---|---|---|---|
| KI-151 | WALL | MEDIUM | Out-of-hours tile says "Closed overnight" for every closed service | frontend/lib/board/format.ts (ageLineText) |
| KI-543, KI-830 | SEC | MEDIUM | 22 BFF id routes do not say idScoped: a back-end 403 for another tenant's id is still shown as 403 (should be 404) | frontend/test/guards/bff-routes.test.ts (ID_ROUTES_NOT_YET_SCOPED) |
| KI-547 | SEC | MEDIUM | A staff CSRF token is not tied to one sign-in | frontend/lib/auth/csrf.ts |
| KI-550 | HAR | MEDIUM | Playwright per-tenant host projects and the e2e/tenancy suite not built | frontend/playwright.config.ts |
| KI-553 | REP | MEDIUM | Nine files still print "SystmOne" (the `epr-name` DEBT table; SPOA and Trust account are gone) | frontend/test/guards/scan.ts:221-231 |
| KI-672 | SEC | MEDIUM | /register?invite= puts the invitation token in the URL: redact in logs and drop it from the address after load | frontend/app/register/page.tsx |
| KI-673 | REG | MEDIUM | /register/[id]/* pages are not guarded by the edge proxy | frontend/proxy.ts; lib/auth/access.ts |
| KI-840 | REP | MEDIUM | Screens say "the coordination team"/"the shift lead", never the tenant's own name: a TenantWords provider | frontend/components/register/*; components/reporter/* |
| KI-843 | SEC | MEDIUM | (idScoped, same as 543) | frontend/test/guards/bff-routes.test.ts |
| KI-56 | WALL | LOW | A polite live region for status changes on the wall is not built (design-system 5.4 item 4) | frontend/components/board/Board.tsx |
| KI-152 | WALL | LOW | 1920x1080 surge board slips the key below the fold | frontend/components/board/Board.module.css |
| KI-248 | SEC | LOW | The CSP style-src allows only nonce/self: a component needing inline style is blocked (none found) | frontend/lib/security/csp.ts |
| KI-439 | WALL | LOW | Public profile is read in a unit of work on every request (no cache) | routes_public.py |
| KI-560 | REP | LOW | Time zone and locale of the profile are read but no page formats a time with them | frontend/lib/board/format.ts; lib/reporter/times.ts |
| KI-562 | REP | LOW | No sign-out or unpair button uses signOutLocal/unpairLocal yet | frontend/lib/session/signOut.ts |
| KI-631 | ADV | LOW | Dialog backdrop uses rgba(0,0,0,0.5): not a design token | frontend/components/ui/Dialog.module.css |
| KI-688 | REG | LOW | API details of a "Yes" are not kept after a reload | ReportingForm.tsx |
| KI-707 | REG | LOW | Status tracker only directly after a send; a reload of ?step=send opens the editor | app/(owner)/criteria/[serviceId]/page.tsx |
| KI-726 | REP | LOW | "Change how we contact me" opens /app/settings#contact which has no channel form | frontend/components/reporter/SettingsScreen.tsx |
| KI-798, KI-799, KI-800 | REP | LOW | Tour: role action buttons go to the app home, no "Skip", "Go to my app" links to the sign-in route | frontend/components/tour/Tour.tsx |

#### B10 NETWORK-UI: BFF network scope, views, administration screens, end-to-end suite

- **Model:** Sonnet for TEN-068 and TEN-081 (tenancy, privacy); mechanical for the screens. **Size:** XL, about 53 h: 47 h of plan (TEN-068 6, 069 4, 070 8, 071 5, 080 8, 081 8, 085 8) plus about 6 h of back-end network rows.
- **Waits for:** TEN-068 to TEN-071 can start now (TEN-059 and TEN-079 are on the tree after W9A). TEN-080 and TEN-081 wait for W9D (its administration layout and components). TEN-085 waits for W9I (TEN-072) and for B12 task 2 (Chromium). W9I's TEN-072 lists TEN-068 as a dependency but is built without it: its network choice needs the BFF scope, so give W9I the TEN-068 route contract or accept a stub.
- **Files it owns:** frontend/app/api/bff/network/ (new), frontend/lib/network/ (new), frontend/components/network/ (new), frontend/app/(network)/ (new), frontend/components/board/Board.tsx (heading only), backend/src/diucs/{adapters/outbound/audit_neo4j/audit_log.py (network reader), domain/rules/{projection,network_board}.py, application/{projection,network_access}.py, application/use_cases/network_*.py, domain/events.py}, infra/servicebus-config.json (criteria.events subscription)
- **Rows:** 17 known issues, 5 hazards.
- **Ordered task list** (red tests first, per the build-wave rules):
  1. TEN-068 BFF network scope: routes, availability check, stream relay; membership claim at sign-in and refresh (KI-585 follows).
  2. TEN-069 scope header and organisation label components, including the tenant's heading on the wall board (KI-545, 559, 56 if not done).
  3. TEN-070 network board UI and unavailable states; TEN-071 directory and criteria views; the generated front-end test that renders every network view and greps for a sourceTenantId-shaped value (KI-552).
  4. Back-end network rows: a network audit reader and verifier, contact phone grouping accepted, ServiceDirectoryChanged emitted, CriteriaApproved rebuilds the board, replica status in the source zone, one live revision per grant lineage, projection statement reader (KI-327, 341, 343, 345, 432, 434, 448, 564, 572, 580).
  5. TEN-080 network administration screens and TEN-081 grant approval and sharing transparency screens (after W9D).
  6. TEN-085 two-tenant and network end-to-end suite (after W9I and Chromium).

| Rows | Area | Sev | What | Evidence |
|---|---|---|---|---|
| KI-327 | NET | MEDIUM | Neo4jAuditLog.records/verify_chain refuse a network-scope chain (TenantNotBound): build a network audit reader so the network chain can be verified | backend/src/diucs/adapters/outbound/audit_neo4j/audit_log.py:597-603 |
| KI-341 | NET | MEDIUM | A contact phone in the national 3-3-4 grouping is refused (NHS-number shape): accept switchboard numbers | domain/rules/projection.py |
| KI-432 | NET | MEDIUM | ServiceDirectoryChanged is defined but no use case emits it (U15, U26, U27, profile edit) | domain/events.py |
| KI-434 | NET | MEDIUM | CriteriaApproved does not rebuild the board: no board-projector subscription on criteria.events | infra/servicebus-config.json; board_projector.py |
| KI-448 | NET | MEDIUM | Network board computes a replica's status with London: a projection holds no zone | domain/rules/network_board.py |
| KI-545, KI-559 | WALL | MEDIUM | Wall board prints a literal "Single point of access"/"urgent care capacity" heading instead of the tenant's words | frontend/components/board/Board.tsx |
| KI-552 | NET | MEDIUM | The second generated test (render every network view, grep for a sourceTenantId-shaped value) needs the network views | frontend/test/guards |
| KI-564 | NET | MEDIUM | No statement-level guard against two live revisions of one grant lineage | Q-NETWORK-GRANT-CREATE |
| KI-580 | WALL | MEDIUM | A wall screen is not in NETWORK_VIEW_ROLES (TEN-067 adds the setting; confirm role added) | application/use_cases/network_access.py |
| KI-184 | INF | LOW | The named graph per ResourceVersion is not built in the RDF export | rdf_export.py |
| KI-257, KI-258, KI-259 | NET | LOW | Network UI spec rows: control-line prefixes, plan names no file paths, amended W-prompt text is the only source | frontend/test/docs/network-ui-spec.test.ts; docs/design/network-ui.md |
| KI-343 | NET | LOW | Projection statement check reads Cypher conservatively (WITH, pattern comprehension) | application/projection.py |
| KI-345 | NET | LOW | `ProjectionValue` defined locally until TEN-038 events merge | application/projection.py |
| KI-572 | NET | LOW | Capacity source_version is the producer's read instant: two producers within one millisecond order arbitrarily | ProjectNetwork._dto |

Hazard rows closed by this bundle (the hazard-log row is updated by B12 when the tests pass):

| Hazard | Sev | What | Evidence |
|---|---|---|---|
| H-N02 | TBD | Network UI: member sees another member's private data: specified, TEN-069..071, 081 not built | built by TEN-069, TEN-070, TEN-071, TEN-081; the control gap is in What |
| H-N03 | TBD | Stale projection read as live: specified, TEN-070/071 not built | built by TEN-070, TEN-071; the control gap is in What |
| H-N04 | TBD | Wall shows the wrong network's board: TEN-072 on W9I; header sentence in TEN-069 | built by TEN-067, TEN-072; the control gap is in What |
| H-N08 | TBD | A left member still shown live: UI part TEN-070 | built by TEN-036, TEN-056, TEN-057, TEN-070; the control gap is in What |
| H-N15 | TBD | Network board shows wrong place or label: TEN-070 | built by TEN-070; the control gap is in What |

#### B11 OBS-SUPPORT: support access, telemetry back end, synthetic checks, console polish

- **Model:** Sonnet for the support-access and ticket tasks; mechanical for the rest. **Size:** L, about 18 h.
- **Waits for:** Tasks 1, 2 (back end) and 4 can start now. Task 3 and the O08 migration wait for W9F (it changes aggregate_repository.py, migrations.py and unit_of_work.py). The ticket-request screen waits for W9D. Browser telemetry items are verified after W9F merges, not rebuilt.
- **Files it owns:** backend/src/diucs/{adapters/inbound/fhir_rest/routes_support.py, application/use_cases/{support_access,telemetry_aggregates}.py, graph_store/{support_ticket_repository,aggregate_repository}.py, audit_neo4j/outbox.py, application/tracing.py, adapters/outbound/telemetry/, adapters/inbound/fhir_rest/routes_synthetic.py}, frontend/components/console/{SessionTimeline,FindSession}.tsx, frontend/e2e/synthetic/, .github/workflows/synthetic.yml
- **Rows:** 39 known issues, 2 hazards.
- **Ordered task list** (red tests first, per the build-wave rules):
  1. Support routes: session id from the signed token claim (a person cannot name another session), idempotent code creation, uniqueness on the ticket node, traceId and reference filters, route /support/* through UseTicketAccess (KI-318, 319, 321, 322, 602).
  2. Telemetry back end: traceparent stored on the outbox row and used by the relay, tenant.id set on use-case spans, explicit allow-list keys instead of db.*, Redis and Azure spans, alert on dead outbox messages (KI-205, 208, 221, 207, 92, 216).
  3. O08 daily job: uniqueness constraints on the five labels, schedule the job, VAPID-missing alert, coalesce board rebuilds (KI-307, 309, 293, 436); the KQL summary (KI-308) stays C.
  4. Synthetic checks: the advisor journey spec, a hook issuer behind an off-by-default flag, the synthetic tenant seed (KI-224, 225, 226).
  5. Console: failed-close message, timeline header and trace id, ticket request on the timeline (after W9D), device filter and tests on insight (after W9F) (KI-781, 782, 783, 784, 785, 788, 789, 112, 606).

| Rows | Area | Sev | What | Evidence |
|---|---|---|---|---|
| KI-318 | SEC | HIGH | A person can name a session id that is not theirs in POST /support/codes (no session claim in the BFF token) | backend/src/diucs/adapters/inbound/fhir_rest/routes_support.py |
| KI-92 | OBS | MEDIUM | Dead outbox messages are logged only: raise an alert (O04) | outbox_relay.py |
| KI-112 | WALL | MEDIUM | A claim whose reply is lost leaves a screen active with no token: offer re-pair (W9I list/revoke) | pair_wall_screen.py |
| KI-205 | OBS | MEDIUM | Outbox relay does not carry the originating traceparent | adapters/outbound/audit_neo4j/outbox.py (no traceparent field) |
| KI-208 | OBS | MEDIUM | `tenant.id` is allow-listed but nothing sets it on use-case spans | backend/src/diucs/application/tracing.py (no tenant attribute) |
| KI-212 | OBS | MEDIUM | initTelemetry and trackPageView not called from the app shell (W9F's branch mounts them: do not duplicate) | W9F e36c2ea (frontend/components/telemetry); wait for W9F merge |
| KI-221 | OBS | MEDIUM | `db.` prefix on the telemetry allow-list admits db.statement (Cypher text): tighten to explicit keys | adapters/outbound/telemetry/attributes.py |
| KI-224 | OBS | MEDIUM | Advisor journey synthetic spec absent although W10-W16 are now built | frontend/e2e/synthetic |
| KI-225 | OBS | MEDIUM | No hook issuer wired: POST /test/synthetic/prompt answers 404; the synthetic tenant is not seeded | bootstrap/container.py; routes_synthetic.py |
| KI-302 | OBS | MEDIUM | BFF posts JSON {events} to OTEL_HTTP_ENDPOINT but the collector takes OTLP only (W9F added an OTLP converter: verify) | frontend/app/api/bff/telemetry/route.ts; lib/telemetry/otlp.ts |
| KI-307, KI-309 | OBS | MEDIUM | O08 daily job: no uniqueness constraint on the five labels, cannot run against Azure, not scheduled | aggregate_repository.py; azure_monitor_query.py; telemetry_aggregates.py |
| KI-321 | SEC | MEDIUM | Support ticket node has no uniqueness constraint (racing second request writes twice) | support_ticket_repository.py |
| KI-436 | WALL | MEDIUM | BoardProjector rebuilds the whole board for every event: coalesce per tenant | application/use_cases/board_projector.py |
| KI-484, KI-487 | OBS | MEDIUM | initTelemetry and attachFriction are not called from any page (W9F mounts them: do not duplicate) | W9F e36c2ea; frontend/lib/telemetry/events.ts |
| KI-602 | SEC | MEDIUM | R18 /support/* routes read a tenant token with role support which the exchange never issues: rework to UseTicketAccess | routes_support.py; auth.py |
| KI-606 | WALL | MEDIUM | A wall screen whose token lapses while the back end is down shows "Connecting this screen..." not Last known | frontend/lib/screens/usePairing.ts |
| KI-783 | OBS | MEDIUM | No ticket-request UI on the support timeline (W9D builds the operator and tenant support-request screens: coordinate) | app/(console)/console/session/[id]/page.tsx; W9D |
| KI-207 | OBS | LOW | Redis and Azure SDK spans and metrics not built | cache_redis, bus_servicebus |
| KI-209, KI-210, KI-211 | OBS | LOW | Browser trace stops at the BFF: EventSource cannot set traceparent; the FHIR client mints a new traceparent; duplicate helper | frontend/components/board/LiveBoard.tsx; frontend/lib/fhir/client.ts; lib/fhir/traceparent.ts |
| KI-213 | OBS | LOW | Web vitals (ttfb_ms, lcp_ms) not sent with page views (W9F builds web vitals) | W9F 3615a6d; wait for W9F merge |
| KI-216 | SEC | LOW | Support code create/open have no idempotency key | support_access.py |
| KI-293 | OBS | LOW | No VAPID key: push messages wait with no failure mark or alert | workers_main.serve |
| KI-297, KI-298, KI-299 | OBS | LOW | Friction: HTTP error clicks not observed, route()/stream() handles uncalled, background-timer dead clicks (W9F mounts the handle: check after merge) | frontend/lib/telemetry/friction.ts; W9F |
| KI-304 | OBS | LOW | A ui.web_vital event cannot use name/value until the allow-list rule is reviewed (W9F builds web vitals) | infra/otel-allowlist.txt; W9F |
| KI-306 | OBS | LOW | initTelemetry not called by any screen (W9F) | W9F |
| KI-319 | SEC | LOW | Support code create is not idempotent under the HTTP replay cache | routes_support.py |
| KI-322 | OBS | LOW | traceId and reference filters on GET /support/sessions answer 400 | routes_support.py |
| KI-781 | OBS | LOW | A failed close of support access says "could not be closed" and gives no state | components/console/SessionTimeline.tsx |
| KI-782, KI-784, KI-785 | OBS | LOW | Support timeline: no trace id (public_event), no header (role, device, release, code expiry), trace/reference search answers 400 | backend support_console.py; routes_support.py |
| KI-788, KI-789 | OBS | LOW | Insight device filter not built; picker and tab tests thin (W9F owns the page: after merge) | frontend/components/console/insight; W9F |

Hazard rows closed by this bundle (the hazard-log row is updated by B12 when the tests pass):

| Hazard | Sev | What | Evidence |
|---|---|---|---|
| H-71 | TBD | O01 db. prefix admits db.statement (KI-221) | built by O07, O08, W48, W49; the control gap is in What |
| H-386 | LOW | Telemetry batch format: W9F OTLP converter (verify after merge) | built by O02; the control gap is in What |

#### B12 VERIFY-HARNESS-DOCS: verification sweep, e2e, harness clean-up, document fold

- **Model:** Mechanical (a Sonnet reviewer signs the fold). **Size:** M to L, about 16 h of work plus run time.
- **Waits for:** Task 1 can start now on the tree as it is (waves 6 to 8 and W9A, B, C, G, H are merged) and is repeated after each bundle merge. Task 5 (fold) runs last; it is the only writer of decisions.md, hazard-log.md and known-issues.md.
- **Files it owns:** backend/tests/ (cleanup only), frontend/e2e/, frontend/package.json (coverage), .github/workflows/ci.yml (no push), docs/delivery/{decisions,hazard-log,known-issues,STATUS}.md and fragments/, .claude/skills/diucs-delivery/references/multi-tenancy.md
- **Rows:** 75 known issues, 38 hazards.
- **Ordered task list** (red tests first, per the build-wave rules):
  1. Verification sweep under the lock (flock /tmp/diucs-neo4j-tests.lock): run the integration directories whose tests were written and never run (the rows in the A table that say "written and not run") in dependency order, a directory at a time; fix test faults only; send a product defect to the owning bundle; record the result per hazard row in the fold.
  2. e2e: install Chromium (not present here: ~/.cache/ms-playwright is missing) and run the Playwright specs that were never run; if the download is refused, mark the rows C.
  3. Harness clean-up: stale comments in about 40 integration files, mypy on tests (26 errors), front-end coverage provider and threshold, backend coverage tool, e2e port derivation, the shared container image check, test_infra_up project layout, emulator lock on the worker tests, a scan for public/ (service worker), the multi-tenancy.md transitional section, small tests (415 exemption on the real app, audit-export 404, release constant, registration rig fake).
  4. Ledger: run delivery.py evidence and verify with an independent verifier for each built task in the drift list (build-wave rules: verification is batched), then deliver; run `delivery.py render`.
  5. Fold the 18 unfolded fragments (about 128 known-issue rows, 85 hazard rows, decisions DEC-860 to DEC-868, DEC-1000 to DEC-1012, DEC-1031 to DEC-1045 and others) into the shared documents; close the E rows of this file; prune the stale Docker volumes (KI-14); fix the Turtle examples (KI-182).

| Rows | Area | Sev | What | Evidence |
|---|---|---|---|---|
| KI-188 | HAR | MEDIUM | I10 integration tests (handler, active_line, two-tenant) written and not run: run under the lock | backend/tests/integration/adapters/inbound/workers |
| KI-215 | HAR | MEDIUM | O06 Neo4j acceptance tests written and not run | tests/integration/graph_store/test_support_repository.py |
| KI-231, KI-234, KI-236, KI-238 | HAR | MEDIUM | P17-P20 integration tests written and not run | tests/integration/graph_store/test_alert_repository.py etc. |
| KI-254 | HAR | MEDIUM | Redis cache/isolation/TTL tests written and not run | tests/contract/test_redis_isolation.py |
| KI-255 | HAR | MEDIUM | Redis: the deployment plan fixes Azure Managed Redis with the Enterprise policy unless the code uses no cross-slot multi-key operations: add a test that the adapter uses only single-key operations, so hash tags are not needed | backend/src/diucs/adapters/outbound/cache_redis/redis_cache.py; deployment-plan.md (Cache row) |
| KI-261 | HAR | MEDIUM | U11 Neo4j integration file written and not run | tests/integration/application/test_open_case.py |
| KI-265, KI-267, KI-271, KI-273, KI-275, KI-280, KI-286 | HAR | MEDIUM | Integration and two-tenant test files for U15, U17, U25, U26, U30, U35 written and not run | tests/integration/application/* |
| KI-328 | HAR | MEDIUM | TEN-018 edge integration tests not run | tests/integration/adapters/inbound/fhir_rest/ |
| KI-330 | HAR | MEDIUM | Service Bus contract/integration for TEN-020 not run with the emulator | tests/contract/test_event_bus_contract.py |
| KI-337, KI-339 | HAR | MEDIUM | TEN-026 and TEN-029 integration matrices written and not run against Neo4j | tests/integration/graph_store/ |
| KI-430 | HAR | MEDIUM | test_infra_up and test_collector_allowlist need the compose stack (Neo4j on 7687, the collector on 4318) | backend/tests/integration/test_infra_up.py |
| KI-435 | HAR | MEDIUM | Two board runners unit-tested but not run against the Service Bus emulator | workers/board_consumer.py |
| KI-485 | HAR | MEDIUM | OTLP/JSON batch never sent to the pinned collector image | frontend/app/api/bff/telemetry/route.ts; infra/otel-collector |
| KI-498 | HAR | MEDIUM | R13 flows not covered by an integration test (request/advice, lock, lost-phone, sign-out) | tests/integration |
| KI-524 | HAR | MEDIUM | Wave-5 integration modules (booking, alert, clinical, criteria, admin, registration routes, provisioning, suspension, guard tests) not run | backend/tests/integration/adapters/inbound/fhir_rest/ |
| KI-609, KI-616 | HAR | MEDIUM | e2e specs for screen pairing and sign-in written and not run | frontend/e2e/screens.spec.ts; sign-in.spec.ts |
| KI-11 | HAR | LOW | Neo4j harness suite (16 tests) not re-run after rounds 7-11: run it once under the lock | backend/tests/integration/support |
| KI-14 | INF | LOW | About ten dangling anonymous Docker volumes: prune after confirming none is in use (non-code, run on this host) | docker volume ls -f dangling=true |
| KI-45 | SEC | LOW | The FHIR 415 exemption for /webhooks/ is tested only on a toy Starlette app: add a test on the real app | fhir_rest/errors.py BodyTypeMiddleware |
| KI-46 | HAR | LOW | Service Bus enqueue contract cases not re-run after the container restart: run with the emulator up | backend/tests/contract; adapters/outbound/bus_servicebus |
| KI-58, KI-59 | HAR | LOW | Wall board browser tests ran only against next dev and a stand-in: run e2e (Chromium is not installed here) | frontend/e2e/live.spec.ts |
| KI-155 | HAR | LOW | Front-end coverage is not a repo check: add @vitest/coverage-v8 and a threshold | frontend/package.json |
| KI-182 | HAR | LOW | Worked examples in fhir-data-model.md are not valid Turtle | docs/spec/fhir-data-model.md |
| KI-198 | HAR | LOW | Redis-backed identity store cases not run against the compose stack | tests/contract/test_redis_identity_store.py |
| KI-226, KI-227 | OBS | LOW | Reporter loop assumes a staff session can open /screen; never run against a stack | frontend/e2e/synthetic/reporter-loop.spec.ts |
| KI-239, KI-240 | SEC | LOW | R14 profile/route assertions compared by hand; a stored booking Task has no Task.code so it would not meet DiucsBookingRequest | profiles/*.json; validator.py |
| KI-245, KI-246 | HAR | LOW | R16 Neo4j route tests not written; test container gives the Dx route no codes | tests/unit/adapters/inbound/fhir_rest/test_routes_terminology |
| KI-249 | HAR | LOW | S01 e2e written and not run | frontend/e2e/security.spec.ts |
| KI-250 | HAR | LOW | Q-CRIT-SET-CURRENT scenario pins net change 0: run on contracted container | graph_store/criteria_scenarios.py |
| KI-320 | HAR | LOW | Expired-code refusal not covered at route level | test_routes_support*.py |
| KI-348 | HAR | LOW | No coverage tool: add coverage to dev dependencies and measure TEN-064 modules | backend/pyproject.toml |
| KI-375 | REG | LOW | "After ConfirmCriteria" test moves review-by directly instead of calling U30 | test_criteria_reviews.py |
| KI-416 | HAR | LOW | Held-lock test lacks a control showing the same lock does delay its own tenant | tests/integration/application/test_report_capacity*.py |
| KI-419 | HAR | LOW | Inbound worker emulator tests do not hold take_emulator_lock() | tests/integration/adapters/inbound/workers |
| KI-420 | HAR | LOW | mypy on tests/ reports 26 pre-existing errors in 6 files | backend/tests |
| KI-424 | HAR | LOW | multi-tenancy.md still has "The transitional rule" as a live section (history from DEC-440) | .claude/skills/diucs-delivery/references/multi-tenancy.md |
| KI-431, KI-520 | HAR | LOW | About 40 integration test files carry stale comments ("until TEN-032", "private contracted container") | backend/tests/integration/** |
| KI-445 | HAR | LOW | Test-order dependency: a telemetry test installs a filter that breaks test_the_log_holds_the_message_id | tests/unit/bootstrap/test_telemetry.py |
| KI-501 | HAR | LOW | S01 e2e written and not run (duplicate of row 249) | frontend/e2e/security.spec.ts |
| KI-506 | HAR | LOW | The tenancy differential covers six use cases; join the rest | tests/integration/application/test_tenancy_use_cases.py |
| KI-516 | HAR | LOW | A raw-Cypher test node with no tenantId is invisible to clean_graph | backend/tests/support |
| KI-519 | HAR | LOW | Shared container is not recreated when NEO4J_IMAGE changes | harness_mode.py |
| KI-523 | HAR | LOW | e2e base port from the process id can collide (1 in 3300) | frontend/e2e/support/env.ts |
| KI-555 | HAR | LOW | The guard rules do not reach public/ (service worker W32 exists): add a scan (no /api/bff or HTML in a cache) | frontend/test/guards; frontend/public/sw.js |
| KI-652, KI-667, KI-657, KI-663, KI-735, KI-741, KI-745, KI-813 | HAR | LOW | e2e not run / not written for W19-W22, W39-W41, W44-W46, W56 flows | frontend/e2e/* |
| KI-765, KI-770, KI-775 | HAR | LOW | e2e for clinical, ask-clinical and help flows written/not written, not run | frontend/e2e/exec-clinical-help.spec.ts |
| KI-779 | HAR | LOW | Add a 404 export test for the audit export route | app/api/bff/lead/audit/[ref]/export/route.ts |
| KI-812 | HAR | LOW | The release constant in lib/release.ts must match package.json by hand: add a test | frontend/lib/release.ts |
| KI-836 | HAR | LOW | registration_rig fake DeviceRegistry lacks count_active | tests/support/registration_rig.py |
| KI-853 | HAR | LOW | test_infra_up expects the whole owner stack under one compose project | backend/tests/integration/test_infra_up.py |

Hazard rows closed by this bundle (the hazard-log row is updated by B12 when the tests pass):

| Hazard | Sev | What | Evidence |
|---|---|---|---|
| H-51 | TBD | Add a test that no case path calls the geocoder (it is used only for a service site address, W24) | built by I12, U27, U28; the control gap is in What |
| H-194 | TBD | Presence isolation test with the in-memory cache that does not prefix | built by U40; the control gap is in What |
| H-470 | HIGH | A booking is answered through a link by a phone that does not hold a role for its service | the tests the row names exist; not run on this tree (built by L02) |
| H-471 | MEDIUM | A change link is used after the booking has moved on, or twice | the tests the row names exist; not run on this tree (built by L02) |
| H-472 | MEDIUM | A reporter sees another service's booking, or the advisor's focus, through the Task route | the tests the row names exist; not run on this tree (built by R09) |
| H-473 | HIGH | A booking is answered by another tenant's reporter, or read across tenants | the tests the row names exist; not run on this tree (built by R09, R17) |
| H-477 | MEDIUM | A person reads, changes or acknowledges another person's alert or preferences | the tests the row names exist; not run on this tree (built by R12) |
| H-478 | MEDIUM | A count under ten is shown as a number on the week summary | the tests the row names exist; not run on this tree (built by R12) |
| H-385 | LOW | A page is served without the per-request nonce, so a script or style is blocked, or the policy is reused across requests | the tests the row names exist; not run on this tree (built by S01) |
| H-270 | HIGH | A statement written for a tenant scope is run in a network scope (or the reverse), so a projection is written from a tenant, or private data is read f | the tests the row names exist; not run on this tree (built by TEN-037) |
| H-330 | HIGH | A read that fails shows an empty list, so a service that is overdue reads as "No services need chasing." | the tests the row names exist; not run on this tree (built by W17) |
| H-331 | MEDIUM | A full telephone number reaches the page or a response | the tests the row names exist; not run on this tree (built by W17) |
| H-485 | MEDIUM | A full phone number reaches a response, the page after save, or a log | the tests the row names exist; not run on this tree (built by W18) |
| H-332 | LOW | A double press of Save creates two services, or sends a second change of number | the tests the row names exist; not run on this tree (built by W18) |
| H-360 | MEDIUM | A reviewer sees a service that is not on the scope list and invites it | the tests the row names exist; not run on this tree (built by W28) |
| H-361 | MEDIUM | A reviewer acts on an overview that the back end did not answer, as if every check had passed | the tests the row names exist; not run on this tree (built by W28, W29) |
| H-362 | HIGH | A reviewer approves a registration with a check still missing | the tests the row names exist; not run on this tree (built by W29) |
| H-364 | MEDIUM | A service goes live before its test notification is answered | the tests the row names exist; not run on this tree (built by W29) |
| H-504 | HIGH | Advisors see the owner's change before a clinical lead has approved it | the tests the row names exist; not run on this tree (built by W30) |
| H-505 | HIGH | A need is both accepted and not accepted, so the criteria contradict themselves | the tests the row names exist; not run on this tree (built by W30) |
| H-507 | HIGH | A clinical lead approves a change they wrote | the tests the row names exist; not run on this tree (built by W31) |
| H-508 | HIGH | An overdue criteria set reads as current to advisors without a flag | the tests the row names exist; not run on this tree (built by W31) |
| H-511 | MEDIUM | A full phone number appears in the phones table, the invitation answer or a log | the tests the row names exist; not run on this tree (built by W43) |
| H-512 | MEDIUM | A cover that ends at the wrong time, because the day is computed in the server's zone or the wrong offset | the tests the row names exist; not run on this tree (built by W43) |
| H-513 | LOW | A set-up that is stuck is shown as in progress | the tests the row names exist; not run on this tree (built by W43) |
| H-517 | MEDIUM | The replay is cached by a browser, a proxy or the BFF and shown later as if current, or its existence is revealed to a person who may not see it | the tests the row names exist; not run on this tree (built by W47) |
| H-518 | HIGH | A broken audit chain is read as a sound record | the tests the row names exist; not run on this tree (built by W47) |
| H-519 | MEDIUM | A CSV opened in a spreadsheet runs a formula from a service name or a label | the tests the row names exist; not run on this tree (built by W47) |
| H-430 | HIGH | A token issued from a code names the wrong person, service, device or tenant | the tests the row names exist; not run on this tree (built by W7B A2) |
| H-431 | MEDIUM | An invitation link or a number is probed through the sign-in routes | the tests the row names exist; not run on this tree (built by W7B A2) |
| H-432 | MEDIUM | A part-filled draft is read as complete, or is submitted | the tests the row names exist; not run on this tree (built by W7B A3) |
| H-433 | MEDIUM | A full mobile number reaches a response | the tests the row names exist; not run on this tree (built by W7B) |
| H-434 | MEDIUM | A test message is taken for a capacity prompt and answered with a number (a report) | the tests the row names exist; not run on this tree (built by W7B) |
| H-435 | MEDIUM | A reminder is reported as sent when none was | the tests the row names exist; not run on this tree (built by W7B C) |
| H-436 | HIGH | A chase list that failed to read shows as "nothing to chase" | the tests the row names exist; not run on this tree (built by W7B C) |
| H-437 | MEDIUM | A suspended service is chased, or looks active | the tests the row names exist; not run on this tree (built by W7B C) |
| H-438 | HIGH | Another tenant's registration, criteria, service, phone or invitation is read | the tests the row names exist; not run on this tree (built by W7B) |
| H-439 | LOW | A criteria history date is wrong or blank without saying so | the tests the row names exist; not run on this tree (built by W7B B) |

### 2.3 Class A rows by area (index)

| Area | Rows |
|---|---|
| Advisor flow | KI-180(B6), KI-200(B6), KI-202(B6), KI-203(B6), KI-266(B1), KI-312(B6), KI-350(B6), KI-354(B6), KI-356(B4), KI-357(B4), KI-361(B4), KI-358(B1), KI-399(B6), KI-400(B6), KI-450(B4), KI-451(B4), KI-452(B4), KI-453(B4), KI-482(B1), KI-483(B4), KI-490(B1), KI-492(B1), KI-625(B6), KI-626(B6), KI-627(B6), KI-801(B6), KI-631(B9), KI-791(B6), KI-814(B6), KI-816(B6) |
| Clinical | KI-229(B7), KI-232(B6), KI-233(B6), KI-247(B6), KI-352(B6), KI-394(B7), KI-395(B7), KI-396(B7), KI-397(B7), KI-461(B7), KI-473(B6), KI-474(B6), KI-475(B6), KI-476(B6), KI-477(B6), KI-481(B7), KI-768(B6), KI-774(B7), KI-818(B7) |
| Reporter app | KI-162(B1), KI-169(B4), KI-235(B7), KI-270(B2), KI-292(B7), KI-410(B7), KI-499(B7), KI-553(B9), KI-560(B9), KI-561(B8), KI-562(B9), KI-648(B4), KI-664(B4), KI-649(B4), KI-650(B4), KI-651(B4), KI-665(B4), KI-726(B9), KI-728(B7), KI-838(B7), KI-798(B9), KI-799(B9), KI-800(B9), KI-835(B7), KI-840(B9), KI-855(B7), KI-856(B7) |
| Registration and review | KI-262(B5), KI-263(B5), KI-268(B5), KI-276(B5), KI-277(B5), KI-278(B5), KI-279(B5), KI-363(B5), KI-364(B5), KI-365(B5), KI-367(B5), KI-368(B5), KI-370(B5), KI-373(B5), KI-375(B12), KI-376(B3), KI-455(B5), KI-457(B5), KI-458(B5), KI-459(B5), KI-460(B5), KI-670(B5), KI-671(B5), KI-673(B9), KI-676(B5), KI-823(B5), KI-806(B5), KI-683(B5), KI-680(B5), KI-685(B5), KI-688(B9), KI-691(B5), KI-700(B5), KI-702(B5), KI-704(B5), KI-705(B5), KI-707(B9), KI-820(B5), KI-825(B5) |
| Lead | KI-264(B3), KI-288(B7), KI-290(B7), KI-315(B7), KI-386(B3), KI-389(B7), KI-391(B7), KI-392(B7), KI-393(B7), KI-466(B7), KI-469(B7), KI-500(B3), KI-749(B7), KI-832(B7) |
| Exec | KI-230(B7), KI-281(B3), KI-282(B7), KI-380(B7), KI-384(B7), KI-463(B7), KI-495(B3), KI-731(B7), KI-494(B7), KI-732(B7), KI-744(B7), KI-738(B7), KI-739(B7), KI-740(B7), KI-742(B3), KI-802(B7), KI-819(B7) |
| Network | KI-181(B6), KI-257(B10), KI-258(B10), KI-259(B10), KI-327(B10), KI-341(B10), KI-343(B10), KI-345(B10), KI-349(B6), KI-432(B10), KI-434(B10), KI-448(B10), KI-552(B10), KI-564(B10), KI-572(B10), KI-576(B1), KI-794(B6) |
| Tenancy and operator | KI-37(B3), KI-39(B3), KI-48(B3), KI-75(B3), KI-93(B3), KI-105(B3), KI-116(B3), KI-124(B1), KI-130(B3), KI-143(B3), KI-144(B3), KI-252(B3), KI-253(B3), KI-256(B3), KI-289(B3), KI-334(B3), KI-335(B3), KI-338(B3), KI-340(B3), KI-346(B3), KI-347(B3), KI-409(B3), KI-418(B3), KI-425(B3), KI-426(B3), KI-427(B3), KI-447(B3), KI-449(B3), KI-478(B3), KI-479(B3), KI-480(B3), KI-503(B3), KI-504(B3), KI-505(B1), KI-508(B3), KI-599(B3), KI-509(B3), KI-510(B3), KI-511(B3), KI-512(B3), KI-514(B3), KI-532(B3), KI-538(B3), KI-557(B3), KI-592(B3), KI-593(B3), KI-594(B3), KI-595(B3), KI-596(B3), KI-598(B3), KI-600(B3), KI-833(B7), KI-834(B3) |
| Harness and CI | KI-11(B12), KI-46(B12), KI-58(B12), KI-59(B12), KI-155(B12), KI-182(B12), KI-188(B12), KI-198(B12), KI-215(B12), KI-231(B12), KI-234(B12), KI-236(B12), KI-238(B12), KI-245(B12), KI-246(B12), KI-249(B12), KI-250(B12), KI-254(B12), KI-255(B12), KI-261(B12), KI-265(B12), KI-267(B12), KI-271(B12), KI-273(B12), KI-275(B12), KI-280(B12), KI-286(B12), KI-320(B12), KI-328(B12), KI-330(B12), KI-337(B12), KI-339(B12), KI-348(B12), KI-416(B12), KI-419(B12), KI-420(B12), KI-424(B12), KI-430(B12), KI-431(B12), KI-520(B12), KI-435(B12), KI-445(B12), KI-485(B12), KI-498(B12), KI-501(B12), KI-506(B12), KI-516(B12), KI-519(B12), KI-523(B12), KI-524(B12), KI-550(B9), KI-555(B12), KI-609(B12), KI-616(B12), KI-652(B12), KI-667(B12), KI-657(B12), KI-663(B12), KI-735(B12), KI-741(B12), KI-745(B12), KI-813(B12), KI-765(B12), KI-770(B12), KI-775(B12), KI-779(B12), KI-812(B12), KI-836(B12), KI-853(B12) |
| Observability | KI-92(B11), KI-205(B11), KI-206(B1), KI-207(B11), KI-208(B11), KI-209(B11), KI-210(B11), KI-211(B11), KI-212(B11), KI-213(B11), KI-221(B11), KI-224(B11), KI-225(B11), KI-226(B12), KI-227(B12), KI-293(B11), KI-297(B11), KI-298(B11), KI-299(B11), KI-302(B11), KI-304(B11), KI-306(B11), KI-307(B11), KI-309(B11), KI-322(B11), KI-484(B11), KI-487(B11), KI-781(B11), KI-782(B11), KI-784(B11), KI-785(B11), KI-783(B11), KI-788(B11), KI-789(B11) |
| Wall screens | KI-50(B3), KI-54(B2), KI-55(B2), KI-56(B9), KI-111(B8), KI-112(B11), KI-151(B9), KI-152(B9), KI-436(B11), KI-439(B9), KI-545(B10), KI-559(B10), KI-580(B10), KI-606(B11) |
| Security and privacy | KI-12(B8), KI-45(B12), KI-114(B8), KI-118(B8), KI-158(B8), KI-161(B1), KI-166(B1), KI-165(B8), KI-178(B4), KI-179(B4), KI-216(B11), KI-239(B12), KI-240(B12), KI-242(B8), KI-248(B9), KI-318(B11), KI-319(B11), KI-321(B11), KI-329(B8), KI-332(B8), KI-372(B8), KI-379(B8), KI-381(B8), KI-401(B1), KI-402(B8), KI-470(B8), KI-404(B8), KI-406(B8), KI-407(B8), KI-438(B8), KI-441(B1), KI-467(B8), KI-468(B8), KI-531(B8), KI-543(B9), KI-830(B9), KI-547(B9), KI-602(B11), KI-612(B8), KI-672(B9), KI-843(B9), KI-859a(B8) |
| Infrastructure | KI-14(B12), KI-167(B1), KI-184(B10), KI-186(B8), KI-191(B1), KI-196(B1), KI-243(B1), KI-443(B8), KI-527(B1), KI-537(B1), KI-587(B1), KI-852(B1), KI-845(B1) |
| Capacity loop (extra area: reports, prompts, board, workers) | KI-7(B2), KI-8(B2), KI-23(B2), KI-24(B2), KI-26(B2), KI-30(B2), KI-31(B2), KI-33(B2), KI-35(B2), KI-36(B2), KI-88(B2), KI-89(B2), KI-96(B1), KI-97(B2), KI-101(B2), KI-102(B2), KI-104(B2), KI-103(B2), KI-133(B2), KI-134(B1), KI-137(B2), KI-139(B2), KI-141(B2), KI-142(B1), KI-149(B2), KI-159(B2), KI-160(B2), KI-173(B2), KI-174(B2), KI-185(B2), KI-189(B2), KI-287(B2), KI-387(B1), KI-388(B2), KI-414(B2), KI-415(B2), KI-502(B1) |

## 3. Class B: owner decisions

Each question is decision-ready: the recommended answer is what the orchestrator will build if told "yes to all". Nothing is built on a B row until it is answered, except where the row says the current behaviour is kept. Priority 1 are patient-safety or pilot-blocking.

### 3.1 The question list

**Q1 (priority 1): Provisional severity for the hazards with TBD**

- Question: May the orchestrator rate the 126 hazards that still read TBD (H-01 to H-224) provisionally, as DEC-133 already allows for H-225 to H-523, and mark them "prepared, not externally certified"?
- Recommended answer: Yes. Rate conservatively on the consequence before controls, label every rating provisional, and keep the clinical safety officer's own assignment as the DCB0129 record.
- Why it is the owner's: The hazard log says severity is the clinical safety officer's; DEC-133 item 2 forbids implying that certification exists.
- Rows: 126 hazards (ids in section 7.2).

**Q2 (priority 1): End-of-build sign-off pack of [ASSUMED] clinical values and wording**

- Question: Approve, or change, the list: GROUP_WINDOW 10 min; CONFIRM_PROCESSING_LIMIT 10 min; wall STALE_AFTER 3 min; criteria review run 07:00; booking phone prompt 5 min and expiry 10 min wording; B8 and B9 texts; not-reached heading; change-link closed wording; "Out of area"; safety-concern categories; retention defaults; the fifth wrong PIN outcome and the fail-closed clock rules (DEC-044 items 1 and 4); email and push wording (IG).
- Recommended answer: Approve all as built for the pilot, with the name and date of the signer recorded in decisions.md; the email and push wording stays blocked until IG approves it in writing (DEC-042 item 3).
- Why it is the owner's: DEC-134 reserves a human sign-off of the clinical [ASSUMED] values and printed wording to the end of the build; nothing may claim approval that was not given.
- Rows: KI-32, KI-62, KI-336, KI-377, KI-398, KI-454, KI-656, KI-661, KI-662, KI-666, KI-793.

**Q3 (priority 1): The 20:00 prompt of an 08:00-20:00 service**

- Question: The last prompt of the day is skipped as "out of hours" because the window end is exclusive. Is the closing time inside the window for the last prompt?
- Recommended answer: Yes for due times only: the prompt due at the close is sent (the closing figure is what a night coordinator relies on); is_in_hours stays end-exclusive for the status rule.
- Why it is the owner's: Clinical value (when a service is asked for its figure).
- Rows: KI-22.

**Q4 (priority 1): Services that report less often than every 2 hours**

- Question: A daily ward or twice-a-day service can never confirm with Y: its figure is older than 2 hours when the prompt goes out, so every Y is refused.
- Recommended answer: Use a per-service confirmable age of the larger of 2 hours and the service's own reporting interval, capped at 26 hours, signed off with Q2. Today it is fail-closed.
- Why it is the owner's: Relaxing H-31/H-32 changes how stale a Y may confirm; clinical safety.
- Rows: KI-27.

**Q5 (priority 1): A service contact on the profile**

- Question: No service has a stored phone to confirm a booking, so option cards say "Phone to confirm" and the network phones list is empty.
- Recommended answer: Add a service contact (a role or switchboard number, never a person's mobile) at registration; unlocks W7A-K1, the network phones row and the closed-booking number.
- Why it is the owner's: Data model and what a service must supply.
- Rows: KI-571.

**Q6 (priority 1): Source of the register number for a call-back**

- Question: numberToCall is null: a registering service is not yet on any register the platform holds.
- Recommended answer: The reviewer types the number from the ODS or directory-of-services record at review time; the platform refuses it if it equals the applicant's own number.
- Why it is the owner's: Fraud control in registration (H-143, H-363).
- Rows: KI-701, KI-824.

**Q7 (priority 1): Correcting a recorded score on a call**

- Question: The picker offers a change the back end refuses.
- Recommended answer: Allow a correction as a new recorded score with a reason; the original stays in the audit; show "corrected".
- Why it is the owner's: Clinical record rule.
- Rows: KI-815.

**Q8 (priority 2): Back-dated number behind a later number**

- Question: A number whose effective time is earlier than the latest non-confirmed figure is accepted and then hidden on the board. Accept, or refuse?
- Recommended answer: Refuse it with a reply that names the latest figure's time (same rule as DEC-140 item 3), so the reporter is never told a number was taken when the board ignores it.
- Why it is the owner's: Changes what a reporter is told; a patient-facing rule.
- Rows: KI-9.

**Q9 (priority 2): Tenant suspension and offboarding rules**

- Question: (a) May a suspension move from read-only to blocked in place? (b) Offboarding from a blocked suspension becomes read-only: confirm. (c) Read-only means the administrator reads and nobody else: confirm.
- Recommended answer: (a) Yes, by an operator with a second approver. (b) Yes, with an operator confirmation. (c) Yes.
- Why it is the owner's: Lifecycle authority over a legal entity's data (DEC-136).
- Rows: KI-77, KI-325, KI-597.

**Q10 (priority 2): Phoned figure that contradicts the last text**

- Question: D12 flags a text that differs from an earlier phoned figure, not the reverse.
- Recommended answer: Flag both directions and show the lead the pair.
- Why it is the owner's: Clinical flag rule.
- Rows: KI-99.

**Q11 (priority 2): Network views beyond capacity**

- Question: Bookings and cases are not shared (DEC-132). Is a network week summary and a network pressure alert wanted beyond the capacity-derived week TEN-082 built?
- Recommended answer: No. Capacity-derived network week only; no network pressure alert until a network sets its own thresholds (Q32).
- Why it is the owner's: Information-sharing scope between organisations.
- Rows: KI-284, KI-496.

**Q12 (priority 2): Consent scope for notifications**

- Question: The R4B value closest to a notification consent is patient-privacy.
- Recommended answer: Keep it with a documented extension; ask IG to review the consent model.
- Why it is the owner's: Information governance.
- Rows: KI-294.

**Q13 (priority 2): Full postcode on a closed case**

- Question: The summary shows the district only (DEC-067).
- Recommended answer: Keep district only (data minimisation, H-092).
- Why it is the owner's: Patient-linked data rule.
- Rows: KI-355.

**Q14 (priority 2): Text wording for the criteria review reminder K2**

- Question: Text-only criteria owners get no 14-day reminder.
- Recommended answer: Add a text K2 and sign it with Q2.
- Why it is the owner's: Patient-adjacent message wording.
- Rows: KI-374.

**Q15 (priority 2): Alert quiet-hours default**

- Question: The prompt says everything during quiet hours; D24 pins critical-only.
- Recommended answer: Critical-only as pinned; amend the prompt text.
- Why it is the owner's: Alert-fatigue versus miss risk.
- Rows: KI-383.

**Q16 (priority 2): Send-back note wording and channel**

- Question: The send-back note is stored only.
- Recommended answer: Send it through the requester's channel as a new template with the note verbatim; sign the wording with Q2.
- Why it is the owner's: Message wording.
- Rows: KI-456.

**Q17 (priority 2): Draft state for criteria edits**

- Question: An owner who leaves the editor loses the edit.
- Recommended answer: Add a draft status in the graph.
- Why it is the owner's: Criteria workflow (DEC-038).
- Rows: KI-493, KI-706.

**Q18 (priority 2): Help guide and lesson content**

- Question: The one-page guide and three reporter lessons are placeholders.
- Recommended answer: The owner or a clinical champion writes them; builders never write a clinical instruction (as built).
- Why it is the owner's: Clinical content.
- Rows: KI-772, KI-804.

**Q19 (priority 2): Who is notified for a clinical advice request**

- Question: A clinician without the clinical-lead role is never notified (H-191).
- Recommended answer: Notify every clinical advisor on duty; keep the lead role for approvals.
- Why it is the owner's: Clinical role model.
- Rows: H-191.

**Q20 (priority 2): A caller number on the withdrawal alert**

- Question: "Phone the caller" has no number: the booking carries none.
- Recommended answer: Do not store the caller's number; show the instruction and let the advisor use their own call system.
- Why it is the owner's: Personal data of the caller.
- Rows: KI-660.

**Q21 (priority 3): Two practitioners of one organisation on one phone**

- Question: The reply path answers Conflict when two active practitioners of one tenant hold one phone (DEC-065).
- Recommended answer: Keep refusing; warn the lead at invitation time that the number is already used.
- Why it is the owner's: Changes who can report for a service.
- Rows: KI-145.

**Q22 (priority 3): Travel cache key and the site id**

- Question: The travel port carries two positions, not the site id; the cache key is the hashed pair of centroids.
- Recommended answer: Keep the pair-of-centroids key; no clinical difference.
- Why it is the owner's: Product choice (the owner is named in the row).
- Rows: KI-201.

**Q23 (priority 3): Synthetic 10-minute schedule**

- Question: The schedule is commented out because CI is manual-only (billing).
- Recommended answer: Keep manual until a deployed stack exists, then enable.
- Why it is the owner's: The owner's billing instruction.
- Rows: KI-228.

**Q24 (priority 3): Lead set-up parameters**

- Question: availableFrom/availableTo and the "Criteria owner" default role name are [ASSUMED].
- Recommended answer: Accept as built.
- Why it is the owner's: Naming owned by the product.
- Rows: KI-313, KI-314.

**Q25 (priority 3): Deactivated service on the network board**

- Question: A deactivated service gives no name-only row.
- Recommended answer: Keep hidden (as built).
- Why it is the owner's: Network disclosure.
- Rows: KI-344.

**Q26 (priority 3): Clinical advisor recording a phoned figure**

- Question: U01 rule: a clinical advisor cannot (DEC-292 item 5).
- Recommended answer: Keep refusing.
- Why it is the owner's: Role rule.
- Rows: KI-353.

**Q27 (priority 3): System role for the booking expiry actor**

- Question: The expiry actor is the system AUDIT role where DEC-193 names OWNER.
- Recommended answer: Keep the system role and amend DEC-193.
- Why it is the owner's: Authority model.
- Rows: KI-360.

**Q28 (priority 3): ODS role names that count as an NHS organisation**

- Question: The list is assumed until a live ODS directory exists.
- Recommended answer: Accept the list for the pilot.
- Why it is the owner's: Registration gate.
- Rows: KI-371.

**Q29 (priority 3): Moving a service to a brand-new number**

- Question: A move to a number with no invitation cannot verify.
- Recommended answer: Let the lead start an invitation at move time, verified by the text code.
- Why it is the owner's: Identity flow.
- Rows: KI-390.

**Q30 (priority 3): Service-closed alert hours**

- Question: The alert is raised only in hours.
- Recommended answer: Confirm as written.
- Why it is the owner's: Alert rule.
- Rows: KI-462.

**Q31 (priority 3): Audit of rejected network projections**

- Question: A rejected message writes no audit entry.
- Recommended answer: Audit each reject once per dedupe key.
- Why it is the owner's: Audit scope.
- Rows: KI-570, KI-851.

**Q32 (priority 3): Network pressure thresholds**

- Question: The network uses the platform default.
- Recommended answer: Default for the pilot; per-network thresholds later.
- Why it is the owner's: Policy.
- Rows: KI-578.

**Q33 (priority 3): Criteria-only sharing**

- Question: A criteria grant without a directory grant shows nothing.
- Recommended answer: Keep: criteria need the directory grant.
- Why it is the owner's: Sharing scope.
- Rows: KI-579.

**Q34 (priority 3): Days choice when adding a service**

- Question: The form has no days choice (DEC-655).
- Recommended answer: Add per-day windows.
- Why it is the owner's: Product scope.
- Rows: KI-645.

**Q35 (priority 3): Add-a-service owner fields**

- Question: The canvas has contact and criteria-owner e-mail fields the form lacks.
- Recommended answer: Role name and phone only; no e-mail.
- Why it is the owner's: Data minimisation.
- Rows: KI-646.

**Q36 (priority 3): Support roles on the console**

- Question: May engineering see traces only? Is insight guarded by the support role alone (DEC-748)?
- Recommended answer: Support sees timelines; add an engineering role later; keep as built.
- Why it is the owner's: Role model.
- Rows: KI-786, KI-790.

**Q37 (priority 3): Support code after a reload**

- Question: The code cannot be shown again.
- Recommended answer: Never re-show; a reload asks for a new code.
- Why it is the owner's: Security.
- Rows: KI-809.

**Q38 (priority 3): The "Other" measure at registration**

- Question: "Other" has no measure code.
- Recommended answer: Drop the option; a service that counts something else registers through its lead.
- Why it is the owner's: Product scope.
- Rows: H-359.

### 3.2 B rows by area

| Rows | Area | Sev | What | Question |
|---|---|---|---|---|
| KI-201 | ADV | LOW | Travel port carries two positions, not site id and patient district: does the cache key need the site id? | Q22 |
| KI-355 | ADV | LOW | Summary Postcode row is the district (DEC-067): does the owner want the full postcode stored? | Q13 |
| KI-360 | ADV | LOW | Expiry actor is timer_actor (AUDIT role) where DEC-193 names OWNER: decide the system role | Q27 |
| KI-454 | ADV | MEDIUM | B8 and B9 wording is [ASSUMED] and not IG-approved | Q2 |
| KI-656 | ADV | LOW | Booking expiry wording names 5 and 10 minutes [ASSUMED] | Q2 |
| KI-660 | ADV | MEDIUM | "Phone the caller" has no number: the booking carries no caller number | Q20 |
| KI-661, KI-662 | ADV | MEDIUM | Not-reached heading, "Reported" line, cancel-reasons note are [ASSUMED] wording | Q2 |
| KI-793 | ADV | LOW | "Out of area" wording is assumed | Q2 |
| KI-815 | ADV | HIGH | A recorded score cannot be corrected on a call (the picker offers a change the back end refuses): clinical rule on score correction | Q7 |
| KI-353 | CLIN | MEDIUM | A clinical advisor cannot record a phoned figure (DEC-100/DEC-292 item 5) | Q26 |
| KI-398 | CLIN | MEDIUM | Safety concern categories are [ASSUMED] until the clinical safety officer agrees them | Q2 |
| KI-772, KI-804 | CLIN | MEDIUM | The one-page help guide and three reporter lessons are placeholders: a clinical instruction is not written by a builder | Q18 |
| KI-809 | CLIN | LOW | A support code cannot be re-shown after a reload: does the sealed session hold the code? | Q37 |
| KI-666 | REP | LOW | Change link's closed page wording for an expired link is [ASSUMED] | Q2 |
| KI-371 | REG | MEDIUM | ODS role names that count as an NHS organisation are an assumed list | Q28 |
| KI-374 | REG | LOW | Text-only criteria owners get no 14-day reminder: K2 has no text template | Q14 |
| KI-377 | REG | MEDIUM | 07:00 criteria review run time is [ASSUMED] | Q2 |
| KI-456 | REG | MEDIUM | The send-back note has no approved wording and no channel send (note stored only) | Q16 |
| KI-493 | REG | LOW | `$submit-for-approval` confirms a waiting version; is a separate draft state wanted? | Q17 |
| KI-701, KI-824 | REG | HIGH | The register number to call back (`numberToCall`) is null: no source for a service not yet listed. Where does the reviewer's number come from? | Q6 |
| KI-706 | REG | MEDIUM | Leaving the criteria editor before sending loses the edit: no draft store (DEC-700 item 2) | Q17 |
| KI-313, KI-314 | LEAD | LOW | `availableFrom/To` parameter names and `ownerRoleName` default "Criteria owner" are [ASSUMED] | Q24 |
| KI-390 | LEAD | LOW | A move to a brand-new number cannot verify until an invitation exists for it: allow an invitation at move time? | Q29 |
| KI-645 | LEAD | LOW | The add-a-service form has no days choice (DEC-655): per-day opening windows? | Q34 |
| KI-646 | LEAD | LOW | The owner's contact and criteria-owner e-mail fields from the canvas are not on the add-a-service form | Q35 |
| KI-383 | EXEC | MEDIUM | Alert quiet-hours default: the prompt says everything during quiet hours, D24 pins critical-only | Q15 |
| KI-462 | EXEC | LOW | Service-closed alert raised only in hours: test uses hours to 23:30; owner to confirm the rule | Q30 |
| KI-284 | NET | MEDIUM | A network summary is not built: bookings and cases are not shared (DEC-132): owner's choice on the network view | Q11 |
| KI-344 | NET | MEDIUM | A deactivated service gives no name-only row on the network board | Q25 |
| KI-496 | NET | MEDIUM | The network variant of the summary (`scope=network`) is refused | Q11 |
| KI-570, KI-851 | NET | LOW | A rejected projection message writes no audit entry in the network chain: does the owner want rejects audited? | Q31 |
| KI-571 | NET | MEDIUM | A service's location and service-level contact are not projected (no repository stores them): decide the service contact (see Q5) | Q5 |
| KI-578 | NET | MEDIUM | Network pressure uses the platform's default thresholds: does a network set its own? | Q32 |
| KI-579 | NET | MEDIUM | A criteria grant without a directory grant shows nothing: allow criteria-only sharing? | Q33 |
| KI-77 | TEN | MEDIUM | Suspension read-only to blocked in place (and offboarding from blocked): confirm the rule | Q9 |
| KI-325 | TEN | MEDIUM | Read-only suspension rule (administrator reads, nobody else) is assumed | Q9 |
| KI-336 | TEN | MEDIUM | Retention defaults, longest keep period and case-audit period are assumed | Q2 |
| KI-597 | TEN | MEDIUM | Suspension has no in-place change of mode (read-only to blocked) | Q9 |
| KI-228 | OBS | LOW | The 10-minute synthetic schedule is commented out (CI is manual-only per the owner's billing instruction) | Q23 |
| KI-786, KI-790 | OBS | LOW | Role decision (DEC-748): may engineering see traces only, and is insight guarded by support alone? | Q36 |
| KI-62 | WALL | MEDIUM | STALE_AFTER_MS = 3 minutes is an [ASSUMED] wall constant | Q2 |
| KI-294 | SEC | MEDIUM | Consent scope patient-privacy is the closest R4B value for a notification consent: IG review of the consent model | Q12 |
| KI-9 | CAP | MEDIUM | A back-dated number behind a later non-confirmed number is accepted and hidden on the board | Q8 |
| KI-22 | CAP | HIGH | 20:00 prompt of an 08:00-20:00 service is skipped as out of hours every day (is_in_hours is end-exclusive) | Q3 |
| KI-27 | CAP | MEDIUM | A service that reports less often than every 2 hours can never confirm by Y (every Y gets C12) | Q4 |
| KI-32 | CAP | MEDIUM | A Y processed more than 10 minutes after receipt is refused with C12; CONFIRM_PROCESSING_LIMIT is an [ASSUMED] value | Q2 |
| KI-99 | CAP | MEDIUM | A phoned figure that contradicts the last text raises no flag (D12 is one-directional) | Q10 |
| KI-145 | CAP | MEDIUM | Two active practitioners of one tenant on one phone answer Conflict (DEC-065) | Q21 |

## 4. Class C: needs infrastructure, a credential or an external approval

Deployment is design-and-plan only (`docs/delivery/deployment-plan.md`). Where the application half is code against a port, the code is class A in B8 or B1 (the Key Vault adapter, the Entra verifier, the Twilio Email adapter, Cloudflare trusted-proxy handling); only the live half is C.

### 4.1 Cross-cutting items (not rows of the backlog, but every pilot needs them)

| Need | Blocks | Where it is designed |
|---|---|---|
| External approvals: clinical safety sign-off and hazard log (DCB0129), DPIA, DTAC, penetration test, IG written approval of email and push wording. Status stays "prepared, not externally certified" (DEC-133 item 2). | any real patient use; the email and push wording | DEC-042 item 3, DEC-133 |
| A real Entra tenant and two app registrations (staff, operator); operator directory separate (DEC-134) | live sign-in (KI-531, KI-612 live half) | deployment-plan.md |
| Azure Key Vault and a managed identity per app; per-tenant Twilio subaccounts and numbers; Twilio Email sender domains per tenant | every real text or email (KI-186, KI-443 live half, KI-513) | deployment-plan.md |
| Neo4j Aura (tier, private networking) and Azure Managed Redis (Enterprise policy) | encryption at rest of phone numbers (DEC-856 pilot basis), backups, the cache | deployment-plan.md |
| Cloudflare custom hostnames, WAF and origin allow-list; DNS per tenant host | host-based tenant resolution in production, Twilio signature checks, token-path log redaction (KI-168) | deployment-plan.md |
| Azure Service Bus namespace; the emulator tests stay local | KI-187 and the emulator runs in B12 | infra/servicebus-config.json |
| OS Places key and licence, ODS directory access, postcode centroid dataset licence, the licensed Pathways Dx list | KI-190, KI-193 to KI-195, H-48, H-49, H-52, H-86 | I11, I12, R16 |
| A real iOS or Android device, and a self-hosted routing engine | KI-171, KI-199, KI-291, KI-713, KI-769, H-57 | I14, I15, W32 |

### 4.2 Rows

| Rows | Area | Sev | What | Needs |
|---|---|---|---|---|
| KI-199 | ADV | MEDIUM | Travel-time reply shape is unverified until a self-hosted routing engine exists | adapters/outbound/travel_time/routing.py |
| KI-769 | CLIN | LOW | Focus trap and screen reader behaviour need a check on real devices | AskClinicalDialog.tsx |
| KI-171 | REP | LOW | A person has not looked at the pages on a phone (real device check) | frontend/e2e/links.spec.ts |
| KI-291 | REP | MEDIUM | No real push has been sent; iOS installed-app delivery unproven (needs a real device and VAPID key) | adapters/outbound/push/web_push.py |
| KI-713 | REP | LOW | iOS standalone focus on notification click is untested (needs a real iOS device) | frontend/public/sw.js |
| KI-125 | TEN | LOW | Migration 0035 creates a `default` tenant with no number/host: a pilot must rename or retire it (needs a real tenant record, DNS and number) | migrations_tenant.py |
| KI-525 | HAR | LOW | The shared test container holds old fixed-id tenants from before the harness rules: wipe the machine's container (host action, owner's Docker) | diucs-test-shared-neo4j |
| KI-237 | SEC | HIGH | Protected label is guarded by code only (Neo4j Community has no read roles); Enterprise read-role deny / at-rest encryption need the managed database (Aura) | protected_text_store.py |
| KI-15 | INF | LOW | 103 stale remote branches: the sandbox proxy refuses ref deletion; owner runs the script from a host with push rights | origin |
| KI-168 | INF | MEDIUM | The Next server and any reverse proxy log `/l/<token>`: redact in the proxy/hosting (deployment config) | deployment |
| KI-187 | INF | MEDIUM | Service Bus emulator `$Default` subscription rule behaviour is unverified against a real namespace | infra/servicebus-config.json |
| KI-190 | INF | MEDIUM | Dataset and NHS licence for postcode centroids (ONS/OS) is an open decision with a real licence needed; fixture is made-up data | backend/tests/fixtures/postcode_centroids_sample.csv |
| KI-193, KI-194, KI-195 | INF | MEDIUM | OS Places licence, the live ODS lookup (HttpOdsLookup raises NotImplementedError) and the OS field names need the OS and ODS accounts and network access | adapters/outbound/geocoder_os_places; terminology/ods |
| KI-295 | INF | LOW | VAPID subject is a placeholder domain (deployment config) | settings.py webpush_subject |
| KI-301 | INF | MEDIUM | Azure resource provisioning and the connection string (deployment) | infra/docker-compose.yml |
| KI-513 | INF | MEDIUM | Provisioning `invite` needs a real secret store (vault credential) | bootstrap/provisioning.py |
| KI-521 | INF | MEDIUM | CI cannot run Service Bus emulator or compose-stack tests (no runner support; run on a machine with the compose stack) | .github/workflows/ci.yml |
| KI-613 | INF | MEDIUM | One tenant host per deployment: a second tenant host needs its own redirect registration in Entra | frontend/lib/auth/oidc.ts |
| KI-617 | INF | LOW | Remove DIUCS_ENTRA_BINDINGS and BACKEND_JWT_SECRET from any deployment environment (deploy step) | deployment settings |

Hazard rows in class C:

| Hazard | Sev | What | Needs |
|---|---|---|---|
| H-48 | TBD | A district's mean is shown as the patient's house, so travel is estimated from the wrong place | needs a real postcode centroid dataset and licence |
| H-49 | TBD | A wrong centroid file (swapped columns, a foreign postcode, a duplicate) puts patients in the wrong place | needs a real postcode centroid file |
| H-52 | TBD | A service's site is placed at the wrong UPRN, so its position and travel range are wrong | needs a real OS Places key and UPRN data |
| H-57 | TBD | Patient position leaves the platform for a third-party routing service | needs a self-hosted routing engine to confirm no patient position leaves the platform |
| H-74 | TBD | The hook issues links on request, so a leaked token or a hook on a production host lets anyone make a link | needs deployment: the synthetic hook issuer must be off on a production host (real environment) |
| H-75 | TBD | A synthetic run texts a real person or number, or opens a link off the target | needs a deployed synthetic run (flag is the issuer's job) |
| H-86 | TBD | Production advisors are offered sample codes that are not real | needs the licensed Pathways Dx list (production advisors are offered sample codes) |

## 5. Class D: accepted risk or wontfix

| Rows | Area | Sev | What | Why it is accepted |
|---|---|---|---|---|
| KI-192 | ADV | LOW | Straight-line travel estimate is labelled as such and replaced by I15 when configured | adapters/outbound/travel_time/straight_line.py |
| KI-204 | ADV | LOW | Routing timeout is 3 s (owner set) | settings.py |
| KI-260 | ADV | LOW | Case reference space of 9000 values per tenant (trigger at about 9000 cases) | free_reference; migration 0022 |
| KI-817 | ADV | LOW | Patient point and map centre are the district's centre | filter_options.py |
| KI-472 | CLIN | LOW | K3 notice wording checked in a unit test only | clinical_advice.py |
| KI-796 | CLIN | LOW | The owner role cannot open /planning (DEC-746: exec and lead only) | frontend/lib/auth/access.ts:14 |
| KI-797 | CLIN | LOW | Heat grid computes busiest in the component | HeatGrid.tsx |
| KI-810, KI-811 | CLIN | LOW | Strict-mode double request; who-opened refreshes every 15 s | SupportCode.tsx |
| KI-61 | REP | LOW | Old 22-character link tokens still resolve | link_access.py |
| KI-170 | REP | LOW | Link page shows "Opening your link..." for one round trip | frontend/components/reporter/LinkLoader.tsx |
| KI-803 | REP | LOW | Learning progress is per browser (LessonProgress store deferred) | frontend/lib/learn/progress.ts |
| KI-674 | REG | LOW | Registration sign-in is a public page limited by the back end's address limit | app/api/bff/identity/code/route.ts |
| KI-677 | REG | LOW | Choosing a new postcode clears the chosen address (the address is the lookup's answer) | LocationForm.tsx |
| KI-682 | REG | LOW | Browser district list accepts any valid district: the back end decides | ServiceForm.tsx |
| KI-686 | REG | LOW | "Save draft" on review changes nothing (drafts saved per step) | ReviewList.tsx |
| KI-692 | REG | LOW | "Phone the shift lead" is a tel: link; no call logged | NeedsChanges.tsx |
| KI-693 | REG | LOW | Edit link on My services goes to the status page | MyServices.tsx |
| KI-694, KI-697 | REG | LOW | My services Edit link goes to the status page; scope list is read through FHIR List (both served) | frontend/components/register/MyServices.tsx |
| KI-712 | REG | LOW | "Review now" goes to the confirm step, not a full edit (owner choice, recorded) | CriteriaOverview.tsx |
| KI-808, KI-827, KI-828, KI-829, KI-831, KI-826 | REG | LOW | Documented edges: changed invitation needs a reload; returning applicant by number; owner with no practitioner record gets 404 on first sign-in; older data; no OS key finds nothing | OrganisationForm.tsx; registration_session.py; criteria_views.py |
| KI-822 | REG | LOW | Organisation name and ODS the applicant sees locked come from the invitation | OrganisationForm.tsx |
| KI-471 | LEAD | LOW | A person made inactive cannot be reactivated; re-invite makes a new practitioner (by design) | remove_person.py |
| KI-641 | LEAD | LOW | Overview first read comes one tick after mount (lint rule) | LeadOverview.tsx |
| KI-647 | LEAD | LOW | District validation is uppercase-only as the back end refuses a district it would change | frontend/lib/lead/serviceForm.ts |
| KI-757 | LEAD | LOW | LeadOverview test timeout 4 s | LeadOverview.test.tsx |
| KI-776, KI-778, KI-780 | LEAD | LOW | Audit CSV and replay display notes (null criteria version; decision time is the shown-at time; malformed reference page) | frontend/lib/lead/auditCsv.ts |
| KI-283 | EXEC | LOW | Integration samples small; pure tests pin the prompt figures | test_week_summary.py |
| KI-285 | EXEC | LOW | Prompt kinds counted are C1 and C9 only | communication_repository.py |
| KI-385 | EXEC | LOW | A replay returns the subscription as stored now | SaveAlertPreferences._replay |
| KI-464 | EXEC | LOW | Daily/weekly summaries out of scope | n/a |
| KI-465 | EXEC | LOW | Escalation runs by the scheduled-work consumer only (deployment of the consumer) | container.py alert_timer_handlers |
| KI-734 | EXEC | LOW | "If nobody acknowledges" heading is builder wording pending the canvas check | SetupFlow.tsx |
| KI-342 | NET | LOW | Cannot enforce by shape that a contact is a role/switchboard number | registration form wording |
| KI-433 | NET | LOW | Event classes not yet emitted have only payload tests | domain/events.py |
| KI-565 | NET | LOW | Registry nodes carry no scope; isolation shown by integration test | test_network_registry.py |
| KI-566 | NET | LOW | networks_of index not built: memberships_of serves the claim | network_registry.py |
| KI-567 | NET | LOW | ProjectionCursor key declared, no statement uses it (reconciliation uses the heartbeat) | migrations_network.py |
| KI-568 | NET | LOW | A network capacity row is the current one only; a history is not kept (TEN-082 samples hourly) | Q-PROJ-CAPACITY-UPSERT |
| KI-569 | NET | LOW | Leave marks rows in separate statements in one unit of work | mark_ended |
| KI-577 | NET | LOW | No bus duplicate detection on projection.work: a repeat costs one marker read | infra/servicebus-config.json |
| KI-581, KI-584 | NET | LOW | Registry view is three whole-network reads per board read: fine for tens of members | network_access.py |
| KI-582 | NET | LOW | A cached network board can be up to 60 s older than a fresh read (clinical review may lower) | network_board_projector.py |
| KI-585 | NET | LOW | A tenant that joined a network after sign-in reads it from the next token | routes_network.ensure_in_claim |
| KI-586 | NET | MEDIUM | A member who left can receive content-free changed events for up to 30 s | routes_network_events.py RECHECK_INTERVAL_SECONDS |
| KI-620, KI-639, KI-743, KI-756 | NET | LOW | Network variants of the advisor board counts, lead System now, phones, audit replay: stated limits (the network shows capacity only, DEC-132, DEC-136) | fragments/W17-W43-network.md |
| KI-777 | NET | LOW | Audit replay is not shown in a network variant (network is capacity-only) | AuditReplay.tsx |
| KI-76 | TEN | LOW | `Tenant` is keyword-only by design | domain/model/tenant.py |
| KI-106 | TEN | LOW | Q-RES-MERGE-RELS is label-less and anchored on the tenant: slow only at large scale | resource_store.py |
| KI-109 | TEN | LOW | Duplicate IN_SYSTEM edges from old data stay; repair only if it matters | Q-RES-LINK-SHARED |
| KI-122 | TEN | LOW | Global statements pinned by SHA-256 of their text (the guarantee) | test_global_allowlist.py |
| KI-123 | TEN | LOW | Tenant directory has no cache by design (suspension takes effect at once) | tenant_directory.py |
| KI-126 | TEN | LOW | Receipt for a text sent just before its number was retired is dropped (retired numbers are not matched) | tenant_directory.py Q-TENANT-BY-ACCOUNT |
| KI-127 | TEN | MEDIUM | `get` / `by_host` return a suspended tenant; every edge answers by status (TEN-018/040/041) | tenant_directory.py |
| KI-128 | TEN | LOW | Relay lists active tenants only; TEN-073/074 drain before suspend | tenant_directory.py |
| KI-136 | TEN | LOW | Registered NamedQuery can be changed with object.__setattr__ (hostile code only; enforce mode TEN-030 done) | queries.py |
| KI-324 | TEN | MEDIUM | Record cache is per process: a suspend takes up to 60 s per process (documented bound) | fhir_rest/tenant_gate.py |
| KI-331 | TEN | LOW | Runner dead-letters a message with no usable tenant as `malformed message` | servicebus_runner.py |
| KI-382 | TEN | LOW | Q-RES-CLEAR-ROOT-RELS spares HAS_CREDENTIAL/HAS_DEVICE; any new store hanging nodes must be added | resource_store.py |
| KI-428 | TEN | LOW | The invariant scan is a full scan; only matters at millions of nodes | Q-INVARIANT-UNSTAMPED |
| KI-437 | TEN | LOW | require_actor_in_bound_tenant is defence in depth with no mutant that isolates it | routes_events.py |
| KI-440, KI-529 | TEN | LOW | Pairing routes and link pages bind the tenant themselves because body and CSRF refusals come first (DEC-167 item 3) | routes_screens.py; capacity_links.py |
| KI-528 | TEN | LOW | A receipt for a text sent just before its number retired is dropped (same as 126) | tenant_directory.py |
| KI-530 | TEN | LOW | Link/pairing routes bind inside handlers (DEC-370 item 6) | capacity_links.py |
| KI-558 | TEN | LOW | Profile cache is per server process (1 minute) | frontend/lib/tenant/profile.ts |
| KI-10 | HAR | LOW | Verifier-authored evidence file wording (code correct) | evidence file; no fix by design |
| KI-16, KI-17, KI-19, KI-20 | HAR | LOW | Documented limits of the raw-run and registration scans (hostile code only); the generated isolation test is the proof | backend/tests/architecture/; TEN-004 generated test |
| KI-21 | HAR | LOW | Tests added after green and never ran red | evidence only |
| KI-25 | HAR | LOW | Evidence cites a removed helper (docs only) | docs/delivery/evidence/U03.md |
| KI-40, KI-41, KI-42, KI-47, KI-49 | HAR | LOW | Test-harness coverage and red-run notes: documented, no clinical effect | evidence files; tests/conftest.py |
| KI-69, KI-78, KI-79, KI-80, KI-81, KI-86 | HAR | LOW | Documented limits of the generated isolation test and equivalent mutants (proof is the generated test plus integration cases) | tests/support/query_probes.py, scenario.py |
| KI-70 | HAR | LOW | Cypher-in-tests lint not built: DEC-142 withdrew it | row text |
| KI-72, KI-73, KI-74 | HAR | LOW | Framework limits (predicate-removal form, `SET m += $props` prefix, `new` key proves creation only) | tests/support/predicate_removal.py |
| KI-129 | HAR | LOW | `main()` guard uncovered | outbox_relay_main.py |
| KI-172 | HAR | LOW | jsdom canvas getContext notice | tests |
| KI-296 | HAR | LOW | One push test does not take the emulator lock (does not use it) | tests |
| KI-317 | HAR | LOW | Lead route tests build their own container | tests |
| KI-351 | HAR | LOW | Positions tests seed Location by raw Cypher | test_service_positions.py |
| KI-421, KI-422 | HAR | LOW | Unanchored resource-store statements held by a pinned table and the generated test | test_tenancy*.py; resource_scenarios.py |
| KI-423 | HAR | LOW | Architecture rule keeping ratchet names out of src cannot be mutated through a scratch copy | test_single_execution_point.py |
| KI-491 | HAR | LOW | Route tests override test_container for the link-token secret | tests |
| KI-515, KI-518 | HAR | LOW | Sweeper and locks are per machine; shared harness used from one machine only | tests/support/sweeper.py |
| KI-517 | HAR | LOW | Shared test container left running (1 GB idle) | harness_mode.py |
| KI-522 | HAR | LOW | --dist loadfile bounds speed-up | pyproject.toml |
| KI-526 | HAR | LOW | Label check reads labels by regular expression, not a Cypher parser | queries.py statement_labels |
| KI-549 | HAR | LOW | Two fixture sets side by side | frontend/test |
| KI-551 | HAR | LOW | Leak canary knows only tenants a test signed in as | frontend/test/leak-canary.ts |
| KI-554, KI-556 | HAR | LOW | Text-rule scans can be bypassed by deliberate string concatenation or aliasing; FETCH_ALLOWLIST names files | frontend/test/guards/scan.ts |
| KI-590, KI-591 | HAR | LOW | Network universe shares scenarios; crashed run leaves its world until the next build cleans the same ids | projection_scenarios.py; network_world.py |
| KI-844 | HAR | LOW | Tests' own sample data still carries "SPOA shift lead" | frontend/test |
| KI-846, KI-847, KI-848 | HAR | LOW | Test token no longer expires; whole-database invariant on a shared database; mutants via raw Cypher | backend/tests/support |
| KI-854 | HAR | LOW | Racing-save tests must use ReadBarrier and write_once | tests/support/races.py |
| KI-218 | OBS | MEDIUM | Azure Monitor logs client not wired: the owner's deployment plan says Log Analytics and Application Insights are not used for now; the collector exporter stays configurable | docs/delivery/deployment-plan.md (Observability row) |
| KI-219 | OBS | MEDIUM | KQL parameter binding unverified: deferred with the Log Analytics decision (deployment-plan.md) | backend/src/diucs/bootstrap/container.py (NoTelemetry); adapters/outbound/telemetry/sdk_logs_client.py |
| KI-220 | OBS | MEDIUM | Application Insights table and column names unverified: deferred with the Log Analytics decision | backend/src/diucs/bootstrap/container.py (NoTelemetry); adapters/outbound/telemetry/sdk_logs_client.py |
| KI-223 | OBS | LOW | Nothing reads a real workspace: deferred with the Log Analytics decision | backend/src/diucs/bootstrap/container.py (NoTelemetry); adapters/outbound/telemetry/sdk_logs_client.py |
| KI-222 | OBS | LOW | Fixture span name differs from O01's `neo4j.query {id}` | tests/fixtures/telemetry |
| KI-300 | OBS | LOW | trace_id on the browser allow-list (recorded) | infra/otel-allowlist.txt |
| KI-305 | OBS | LOW | isFreeText is a heuristic over spec shapes | frontend/lib/telemetry/schema.ts |
| KI-308 | OBS | LOW | The daily O08 job cannot run against Azure (KQL summary not built): deferred with the Log Analytics decision | aggregate_repository.py; azure_monitor_query.py; telemetry_aggregates.py |
| KI-310, KI-311 | OBS | LOW | Multi-day sessions counted once per day; no cross-release comparison | telemetry_insights.py |
| KI-323 | OBS | MEDIUM | Live Azure read of events, traces and sessions unverified: deferred (no workspace by decision) | azure_monitor_query.py |
| KI-486 | OBS | LOW | BFF telemetry answers 401 without a session (by design) | app/api/bff/telemetry/route.ts |
| KI-488 | OBS | LOW | Kind name `abandonment` (schema enum) | friction.ts |
| KI-489 | OBS | LOW | Schema check covers the front end only; back end has its own tests | backend |
| KI-51, KI-52, KI-53 | WALL | LOW | Contrast of the hatched tile proved by styles.test; unknown `$board` parts ignored by design; dev-only badge overlap | frontend/components/board/styles.test.ts |
| KI-57, KI-63, KI-64 | WALL | LOW | Wall board uses the BFF Date header for age; clock-step edge cases fail safe or are bounded; trigger is multi-host only | frontend/lib/board/client.ts |
| KI-153, KI-154 | WALL | LOW | Parser compares organisation display names; free text not checked: the back end is the control (tenant-scoped reads) | frontend/lib/board/parse.ts |
| KI-610 | WALL | LOW | Displays behind a shared proxy share the back end's per-address pairing limits | frontend/lib/screens/usePairing.ts |
| KI-611 | WALL | LOW | Device cookie is kept 400 days, never refreshed | frontend/lib/screens/cookies.ts |
| KI-34 | SEC | LOW | The 409 answer carries the service name (reference data the caller already holds, DEC-145 item 4) | routes_board.py |
| KI-43 | SEC | LOW | Replay guard is the MessageSid marker (24 h): Twilio signs no timestamp, so this is the strongest available control | sms_webhook/routes.py |
| KI-44 | SEC | LOW | Two equivalent surviving mutants | sms_webhook/routes.py |
| KI-60 | SEC | LOW | A UUID4 matches the NHS-number shape in 0.83 percent of draws; no id is passed to a free-text field | adapters/outbound/ids_uuid/uuid_ids.py |
| KI-115 | SEC | LOW | Q-SCREEN-GET lock on a caller-chosen pairing id: brief hold only | pair_wall_screen.py |
| KI-117, KI-119, KI-120 | SEC | LOW | Pairing timing, limiter release and window-boundary test notes | pair_wall_screen.py |
| KI-164 | SEC | LOW | Link hit/miss timing not equalised; `used` shown to the holder of a valid token | link_access.py |
| KI-214 | SEC | LOW | No platform-wide support role that searches all tenants: deliberate (DEC-134 item 5) | application/use_cases/support_access.py |
| KI-217 | SEC | LOW | Lead role codes recorded as [ASSUMED] | domain/rules/support.py LEAD_ROLE_CODES |
| KI-241 | SEC | LOW | FHIR profiles are hand-written, not run through the HL7 publisher | backend/profiles/*.json |
| KI-269 | SEC | LOW | Residual timing of request-code endpoint for a known number (H-96) accepted | text_code.py |
| KI-316 | SEC | HIGH | Staff phone numbers kept in plain text on ProtectedContact (accepted for the pilot, DEC-856 option b; application-level encryption is the A row for DEC-856) | graph_store/contact_store.py; DEC-856 |
| KI-378 | SEC | LOW | Known person on a fresh device with a PIN gets a different answer from an unknown identity (requires holding both ids already) | application/use_cases/pin.py |
| KI-405 | SEC | LOW | 429 says the address is throttled, not that a number is known | routes_identity.py |
| KI-411, KI-412, KI-413 | SEC | LOW | Sealer key derivation outside Container.build; hashKeyVersion 0 tenant refused at start-up; platform-secret rotation changes every key at once (documented; version 2 plus re-hash is a future task) | adapters/outbound/content_seal/aes_gcm.py; domain/rules/tenant_keys.py |
| KI-533 | SEC | LOW | No Practitioner/accountRef stored at sign-in; derived subject (DEC-524) | exchange_token.py |
| KI-540 | SEC | LOW | Staff/wall sessions made before TEN-044 were signed out once | frontend/lib/auth/session.ts |
| KI-541 | SEC | MEDIUM | BFF reads the tenant claim without a signature check (no secret); trusted BFF-to-back-end link | frontend/lib/auth/tokenClaims.ts |
| KI-542 | SEC | LOW | withBff refuses tenant/scope/network field names by design | frontend/lib/bff/inputGuard.ts |
| KI-546 | SEC | LOW | A FHIR search with a raw space or quote must be percent-encoded by the caller | frontend/lib/fhir/client.ts |
| KI-548 | SEC | LOW | Link routes answer no-store (stops every cache); no withLink wrapper | app/api/bff/links |
| KI-563 | SEC | LOW | A browser that ignores Clear-Site-Data keeps its HTTP cache; data pages are no-store | browsers |
| KI-605 | SEC | LOW | An access held in the cache is lost on a flush (by design, DEC-530) | cross_tenant_guard.py |
| KI-841 | SEC | LOW | Pre-session CSRF token is bound to host and device only (until an authenticated pre-session factor exists) | frontend/lib/reporter/bff.ts |
| KI-842 | SEC | LOW | Registration code routes rely on JSON-only bodies and SameSite=Strict | app/api/bff/identity/code* |
| KI-859 | SEC | HIGH | Staff phone numbers in plain text on ProtectedContact: accepted for the pilot only (DEC-856 option b, Aura at-rest encryption); see A row 859a | contact_store.py |
| KI-13 | INF | LOW | 633 old commits carry model co-author trailers; pushed history is not rewritten | git history; new commits are clean (check-messages) |
| KI-83 | INF | LOW | Stamp scan is one pass per batch; fine for dev data | migrations_tenant.py |
| KI-176 | INF | MEDIUM | SMTP password as a setting: SMTP is superseded by Twilio Email, whose credentials come from the Key Vault adapter (KI-186) | settings.py |
| KI-183 | INF | LOW | Catch-all Basic gets no profile class (heuristic) | rdf_export.py _classes |
| KI-197 | INF | LOW | terminology_dir found from the source layout; an installed package sets DIUCS_TERMINOLOGY_DIR | bootstrap/settings.py |
| KI-303 | INF | LOW | Test profile runs the collector as root; never in production | infra/docker-compose.yml |
| KI-442 | INF | LOW | SMTP login name: SMTP is superseded; email goes through Twilio's Email API (deployment-plan.md) | bootstrap/tenant_senders.py |
| KI-28, KI-29 | CAP | MEDIUM | Y after the reporter's own number, or in the same whole second as the prompt, is refused with C12: fail closed by design (H-32, DEC-148 items 17, 20); nothing recorded wrongly | handle_inbound_text.py (_number_after_prompt, recorded_since_prompt) |
| KI-87 | CAP | MEDIUM | Fencing token high-water mark is in memory only (H-26); accepted until the outbox head node exists | workers/outbox_relay.py |
| KI-90 | CAP | LOW | A retried outbox row can reach the bus after newer ones: consumers are order-independent (DEC-157 item 10) | outbox_relay.py |
| KI-94 | CAP | LOW | A service with no figure is not grouped (C9 never shows "?"): chosen by DEC-158 item 3 | send_prompts.py |
| KI-95 | CAP | LOW | A reporter on another phone is prompted on their own (documented) | send_prompts.py |
| KI-132 | CAP | LOW | TenantBoundConsumer in place; later consumers must wrap (convention) | workers/tenant_binding.py |
| KI-146, KI-148 | CAP | LOW | Ladder stop costs about 4(1+R) extra reads per report | missed_report_ladder.py |
| KI-417 | CAP | LOW | Tenant directory read per message (uncached by design) | workers/tenant_binding.py |
| KI-444 | CAP | LOW | Sender consumer reads the tenant's channels per email | message_senders.py |

Hazard rows in class D:

| Hazard | Sev | Reason |
|---|---|---|
| H-72 | TBD | A session or trace id is spliced into KQL and changes the query: deferred by the deployment plan (no Log Analytics workspace for now); KQL binding stays unverified |
| H-73 | TBD | A console user reads another tenant's telemetry: deferred by the deployment plan (no Log Analytics workspace for now); KQL binding stays unverified |
| H-157 | TBD | A duplicate push after a transient failure: accepted risk: a duplicate push after a transient failure (decision in the row) |
| H-506 | MEDIUM | A patient detail is typed into the reason for a change, where it is logged: accepted: the reason-for-change rule is a hint |
| H-379 | HIGH | Patient details are typed into a free-text report, where the tool holds them: accepted: patient detail in free text can only be hinted, not recognised |
| H-521 | MEDIUM | A support code is seen by someone standing near the screen and used to open the session: accepted: shoulder-surfing of a support code is not controlled by the tool (the code expires and opens one session, shown who opened) |
| H-414 | HIGH | Patient detail typed into a problem report is kept readably: accepted: the back end cannot recognise patient detail in free text; hint and guidance only |
| H-523 | HIGH | A staff phone number (a reporter's, a cover's, a registration call-back, a tenant administrator's) is kept in plain text on a ProtectedContact node, s: accepted for the pilot (DEC-856 option b); application-level encryption is KI-859a (A) |

## 6. Class E: already closed (stale rows)

These rows can be struck from known-issues.md by B12 (task 5). The "closed by" cell names the closing work; "not yet merged" means the closing code is on a running W9 branch.

| Rows | Area | What the row said | Closed by |
|---|---|---|---|
| KI-359 | ADV | BookingPhonePrompt consumer: the advisor's "No reply" card is built (W20, W8A DEC-867) | frontend/components/advisor/BookingCard.tsx; fragments/W8A.md |
| KI-618 | ADV | Case segment is the four-digit reference (W8A DEC-862) | fragments/W8A.md; app/(advisor)/advisor/case/[ref] |
| KI-619, KI-621, KI-622, KI-623, KI-624 | ADV | Open, read, save (age band, referrer, planned) and scores are served and wired (W7A DEC-770 to DEC-781, W8A) | backend routes_cases.py; frontend app/api/bff/cases/route.ts (no not-built left) |
| KI-628 | ADV | overBy is sent and wired (W7A DEC-779) | case_mapping.py:305-306 |
| KI-629, KI-630 | ADV | Criteria history admits advisors; accepts/excludes served (DEC-864 W8A) | fragments/W8A.md |
| KI-632, KI-633, KI-634, KI-635, KI-636 | ADV | Case summary, $close, scores, widen are served and wired (W7A, W8A) | routes_cases.py; fragments/W8A.md |
| KI-653, KI-654, KI-655 | ADV | BookingPanel mounted in options list and map; Requested card and finish-summary routes built (W8A DEC-867) | fragments/W8A.md |
| KI-658, KI-659 | ADV | Shared Dialog and See-options-again are wired (W8A DEC-866/DEC-865) | fragments/W8A.md |
| KI-792 | ADV | District chips built (W9H DEC-1045) | fragments/W9H.md |
| KI-821 | ADV | Lead's case call: the case routes and the advisor guard are decided (DEC-860: a shift lead does not work a call) | fragments/W8A.md DEC-860 |
| KI-857 | ADV | DEC-854 is built: only "I have phoned the caller" or "The caller is already being helped" acknowledge (awaiting verification) | frontend/components/advisor/WithdrawalAlert.tsx:12-13,74-77 |
| KI-758, KI-759, KI-760, KI-761, KI-762, KI-764, KI-766, KI-767, KI-771, KI-773 | CLIN | Single-request read, Mine/Done lists, case glance on the queue Task, presence, return time, layouts, dialog wiring, advisor read of a request, problem report and HelpLink placement are served and wired (W7A DEC-774 to DEC-780, W8B) | backend routes_clinical.py; frontend/app/api/bff/clinical; fragments/W8B.md |
| KI-763 | CLIN | The advisor's work phone is on the clinician's case view (W9G) | fragments/W9G.md |
| KI-795 | CLIN | GET /planning exists | backend/src/diucs/adapters/inbound/fhir_rest/routes_planning.py |
| KI-858 | CLIN | DEC-855 is built: no advice form without the case; the dialog shows the advice or says it could not read it (awaiting verification) | frontend/components/clinical/CaseView.tsx:147-150; fragments/W8B.md |
| KI-403 | REP | The BFF calls the reporter routes and sends the host, device and session (W6D/W6J, W8E) | frontend/lib/reporter/bff.ts |
| KI-714, KI-715, KI-716, KI-717, KI-719, KI-720, KI-721, KI-723, KI-724, KI-725, KI-727, KI-730 | REP | Invitation lookup, code request/verify, channel, push key and subscriptions, set-up summary, prompt/report/history, booking decision, reverify, settings, cover, batch, accept routes are served and wired (W7B DEC-792 to DEC-826, W7C, W8E); no not-built left | frontend/app/api/bff/reporter/*; invitations/[token]/route.test.ts:102 |
| KI-718, KI-722, KI-729, KI-534, KI-839 | REP | The reporter BFF exchanges the PIN session for a back-end token (no more session-id bearer) | frontend/lib/reporter/exchange.ts:52 (POST /identity/session-token) |
| KI-272 | REG | U24 invitation shape is on the tree (invite_reporter.py) | application/use_cases/invite_reporter.py |
| KI-366 | REG | Communication about_id fix is in the code (service id) | invite_reporter.py |
| KI-369 | REG | PersistRegistration is wired into R10's route | routes_registration.py |
| KI-408 | REG | R10 route calls submit_registration; review use cases are wired (W8C) | bootstrap/wiring.py |
| KI-668, KI-669 | REG | Registration sign-in session and invitation check served and wired (W7B DEC-790/791, W8C) | routes_registration_session.py |
| KI-675, KI-679, KI-684, KI-687, KI-689, KI-805 | REG | Registration record, review, mine, status reads served and wired (W7B DEC-794, W8C) | routes_registration_views.py |
| KI-678 | REG | 24-hour services and partial draft saves served (W7B DEC-793) | routes_registration.py |
| KI-681 | REG | Service name and fixed-site answer come from the registration read (served W7B DEC-794) | backend routes_registration_views.py |
| KI-690, KI-699, KI-753 | REG | Notification, review-request, confirm-details, resend served and wired (W7B DEC-797/809, W8C) | routes_registration_views.py |
| KI-695, KI-696, KI-698, KI-703, KI-708, KI-709, KI-710, KI-711 | REG | Registrations queue, overview, decision, criteria current values, pending approval read and history change date/author are served and wired (W7B DEC-795 to DEC-800, W8C) | backend routes_registration_views.py, routes_criteria_views.py; no not-built left in frontend/app/api/bff |
| KI-807 | REG | Partial draft saves are served (W7B DEC-793 item 2) | routes_registration.py |
| KI-637 | LEAD | Lead overview served and wired (W7B DEC-807, W8D) | routes_lead_views.py; frontend/app/api/bff/lead/overview |
| KI-638 | LEAD | Reminder route served and wired (W7B DEC-807, W8D) | routes_lead_views.py |
| KI-640 | LEAD | Phoned dialog is W14's dialog (W8D) | frontend/components/advisor/PhonedDialog.tsx |
| KI-642, KI-644 | LEAD | Change of reporter number and its last-four digits served and wired (W7B DEC-803, W8D) | routes_lead_views.py |
| KI-643 | LEAD | Test prompt and test text served and wired (W7B DEC-808, W8D) | routes_lead_views.py |
| KI-746, KI-747, KI-748, KI-750, KI-754, KI-755, KI-751 | LEAD | Suspension read, people list (GET /lead/reporters), closed flags, phones and phoned dialog are served and wired (W7B DEC-803 to DEC-805, W8D) | routes_lead_views.py; frontend/app/api/bff/lead |
| KI-752 | LEAD | Set-up tracker served (W7B DEC-806) and wired (W8D) | routes_lead_views.py |
| KI-497 | EXEC | Acknowledged and closed alerts are listed by GET /fhir/Task (W7A DEC-775) | backend/src/diucs/adapters/inbound/fhir_rest/routes_alerts.py:85-87,216 |
| KI-733 | EXEC | The home-screen step exists (W34/W9H PhoneAlerts) | frontend/components/exec/PhoneAlerts.tsx |
| KI-736, KI-737 | EXEC | coordinationPhone and the Acknowledged/Closed alert tabs are served and wired (W7A DEC-775/777) | backend routes_alerts.py; no not-built in frontend |
| KI-837 | EXEC | Exec reporter routes: decided not built (DEC-1040) | fragments/W9H.md |
| KI-573 | NET | Backfill is started when a grant becomes effective and a listing is admitted (TEN-077/078, W9A) | application/use_cases/grants.py; listing_admission.py |
| KI-574 | NET | A network's audit chain head is created on network creation (W9A TEN-077) | application/use_cases/network_admin.py:253 |
| KI-575 | NET | network-projector reader started (TEN-056, W9A network_governance_consumer) | adapters/inbound/workers/network_governance_consumer.py |
| KI-583 | NET | GrantEffective and governance events are published by the governance use cases (W9A) | network_governance.py |
| KI-589 | NET | Network administration routes built (TEN-079, W9A) | routes_network_admin.py |
| KI-849, KI-850 | NET | Network audit head created at network creation; reconciliation and governance events built (W9A TEN-056, TEN-077) | application/use_cases/network_admin.py:253; projection_reconcile.py |
| KI-38 | TEN | Idempotency, outbox and audit rows now carry tenantId: the UNCONVERTED ratchet is empty (TEN-016, TEN-017, TEN-030) | git a4b95a3 (TEN-030); unconverted.py removed; idempotency_store.py:189 |
| KI-67 | TEN | Milestone-slice statements are converted (TEN-010); ratchet empty | a4b95a3 |
| KI-68 | TEN | Outbox relay and processed-message consumer now bind each tenant (TEN-016, TEN-020, TEN-025) | workers/tenant_binding.py |
| KI-82 | TEN | Writers stamp tenantId and composite keys exist (TEN-010 to TEN-017, TEN-031 invariant) | migrations_tenant.py; tenant_invariants.py |
| KI-84 | TEN | Case reference statements converted (TEN-010/TEN-032) | a4b95a3 |
| KI-98 | TEN | Q-IDEM statements converted (TEN-016); prompt_key carries the tenant | idempotency_store.py:189 |
| KI-100 | TEN | Flag, report and look-back statements converted; generated isolation test covers them | a4b95a3 |
| KI-108 | TEN | Q-PERSON-PHONE-FIND is tenant-scoped (TEN-011) | person_repository.py |
| KI-110 | TEN | Closed unless a caller appears: none in src | resource_store.py |
| KI-113 | TEN | Q-LINK and Q-IDEM statements converted (TEN-013, TEN-016) | link_token_repository.py:204 |
| KI-131 | TEN | Resolved by TEN-015 (row text) | DEC-171 item 4 |
| KI-135 | TEN | Reply processor person/service reads converted (TEN-010, TEN-011) | a4b95a3 |
| KI-138 | TEN | Ladder person/capacity reads converted (TEN-010, TEN-011) | a4b95a3 |
| KI-156 | TEN | Service and capacity reads are tenant-scoped (TEN-010) | a4b95a3 |
| KI-157 | TEN | Q-IDEM keys carry the tenant (TEN-016) | idempotency_store.py:189 |
| KI-163 | TEN | Link-side reads converted (TEN-009 to TEN-016) | a4b95a3 |
| KI-175 | TEN | Per-tenant senders built (TEN-042) | bootstrap/tenant_senders.py |
| KI-251 | TEN | Link requests resolve the tenant from the host (DEC-167, TEN-041); a request with no known host is an unknown link by design | link_token_repository.py; link_pages |
| KI-274 | TEN | Replay and audit statements converted (TEN-016, TEN-017) | a4b95a3 |
| KI-326 | TEN | tenant-admin and network-admin now have routes (TEN-075, TEN-079) | routes_platform.py; routes_network_admin.py |
| KI-333 | TEN | tenant-admin role now in CONFIGURATION_ROLES (TEN-018/075) | tenant_config.py |
| KI-429 | TEN | Superseded constraints dropped by TEN-032 (the six range indexes remain by design: only the planner uses them) | graph_store/migrations_contract.py:1-17 |
| KI-507 | TEN | Platform audit chain built (TEN-075 DEC-1002) | graph_store/platform_audit.py |
| KI-536 | TEN | Operator sign-ins audited on the platform chain (TEN-075 DEC-1002) | platform_audit.py |
| KI-539 | TEN | Operator console door built on W9D's branch (TEN-083 session kind, sign-in) | W9D 3e8f9bc (not yet merged) |
| KI-601 | TEN | Platform audit chain has a graph adapter (TEN-075) | graph_store/platform_audit.py |
| KI-603 | TEN | Tenant administrator signs in through the exchange (TEN-043/075) | exchange_token.py |
| KI-604 | TEN | Tenant administrator's access log screen read from the tenant chain (TEN-075 DEC-1008) | tenant_admin_views.py |
| KI-615 | TEN | Administrator pages built on W9D's branch (TEN-076, TEN-083) | W9D 540f3f4 (not yet merged) |
| KI-18 | HAR | Closed by TEN-005 (DEC-159 item 3): the architecture test names the three files | row text; test_single_execution_point.py |
| KI-66 | HAR | Resolved by TEN-005 (row text) | DEC-159 item 2 |
| KI-71 | HAR | Resolved by TEN-009 (row text) | DEC-164 item 9 |
| KI-446 | HAR | Fixed (row text) | - |
| KI-544 | OBS | Moved to lib/telemetry/otlp.ts | route.ts |
| KI-614 | OBS | Operator console sign-in built on W9D's branch (TEN-083) | W9D 3e8f9bc (not yet merged) |
| KI-787 | OBS | The insight route and tabs are built on W9F's branch | W9F 3615a6d (not yet merged) |
| KI-244 | WALL | W8 pairing page polls the claim from the moment the code shows (W08, W6J) | frontend/lib/screens/usePairing.ts |
| KI-588 | WALL | Wall screen has a network view setting (TEN-067) | fragments/TEN-067.md |
| KI-607 | WALL | Revoke and live-screen check at the edge (TEN-072, W9I branch) | W9I 6385273 (not yet merged) |
| KI-608 | WALL | Board choice and claim confirmation built (TEN-072, W9I branch) | W9I 08040d1 (not yet merged) |
| KI-177 | SEC | Referrer-Policy header is set by the proxy and the sign-in flow | frontend/lib/security/csp.ts:58 |
| KI-362 | SEC | Outbox publish refuses a payload with a live link (TEN-020 check_publishable); invitation text is sealed (U03/I10) | backend/src/diucs/application/ports/outbound/event_bus.py:235 check_publishable |
| KI-535 | SEC | The front end no longer mints a token with BACKEND_JWT_SECRET (exchange, W6J) | frontend/lib/auth/staff.ts |
| KI-91 | INF | Closed by TEN-007 (row text); an end-to-end run needs the stack (B12) | outbox_relay_main.py |

Hazard rows in class E (built; the hazard-log status text is stale or waits only for the verification run):

| Hazard | Sev | Closed by |
|---|---|---|
| H-329 | MEDIUM | A lead opens a call, and the back end refuses it, so the advisor sees a failure with no clear cause: closed in code: DEC-860 (a lead no longer works a call; W8A) |
| H-320 | MEDIUM | The case is opened with nothing in it (the prompt's empty case), which the back end refuses because it needs a referrer-type. Age band and referrer ar: closed in code: W7A DEC-770: an empty case opens; wired W8A |
| H-321 | HIGH | "Planned" is sent as routine and read back as "Today" (DEC-397), so the advisor sees a different urgency from the one chosen: closed in code: W7A DEC-773: planned is stored and answered as planned |
| H-323 | MEDIUM | A referrer's score is shown as recorded but the back end does not store it: after a reload it is gone, and it is missing from the summary: closed in code: W7A DEC-773: scores stored and read back |
| H-495 | HIGH | The shift lead's escalation stops when an advisor presses an action on the withdrawal alert without phoning the caller: closed in code: DEC-854 option (a) built: frontend/components/advisor/WithdrawalAlert.tsx:12-13,74-77 |
| H-350 | MEDIUM | An applicant is shown "signed in" without a reporter session, so the registration routes refuse every save: closed in code: W7B DEC-790 session after a right code, wired W8C |
| H-351 | MEDIUM | The code request does not check the invitation, so a text code can be asked for any UK mobile: closed in code: W7B DEC-791 invitation checked on the code request |
| H-355 | LOW | A 24-hour service cannot be saved: R10's `LocationStep` field is `open_24h`, and `_snake('open24h')` gives `open24h`, so `parse_draft` refuses the val: closed in code: W7B DEC-793 open24h read |
| H-356 | LOW | The postcode lookup cannot run: no back-end route calls the geocoder, so every lookup is a 503: closed in code: address route and BFF built (app/api/bff/addresses/route.ts) |
| H-509 | MEDIUM | A suspended service looks active on a fresh visit to its page, so a lead does not know it is suspended: closed in code: W7B served the suspension read (routes_lead_views.py), wired W8D |
| H-510 | MEDIUM | A removal of access sent to the wrong person, because the person is typed: closed in code: GET /lead/reporters gives role ids; remove picks a person (W7B DEC-803, W8D) |
| H-333 | MEDIUM | A flag or a refusal from the BFF reads as "nothing to check": closed in code: closed-flag list served (W7B DEC-804), wired W8D |
| H-375 | HIGH | A clinical advisor gives advice without the case's details on the screen: closed in code: DEC-855 built: frontend/components/clinical/CaseView.tsx:147-150 |
| H-514 | HIGH | Advice is given on the request, but the advisor's dialog still says "Waiting for a clinical advisor", so the advisor calls again or acts without it: closed in code: DEC-855 built: dialog shows advice or says it could not read it (W8B) |
| H-353 | LOW | A part-filled organisation cannot be saved as a draft: R10's `parse_draft` treats each required field that is missing as an error, so "Save draft" wit: closed in code: W7B DEC-793 item 2 partial saves |

## 7. Open hazards

### 7.1 HIGH first (every open hazard rated HIGH)

| Hazard | Class | Bundle or question | What | Evidence or reason |
|---|---|---|---|---|
| H-470 | A | B12 | A booking is answered through a link by a phone that does not hold a role for its service | the tests the row names exist; not run on this tree (built by L02) |
| H-473 | A | B12 | A booking is answered by another tenant's reporter, or read across tenants | the tests the row names exist; not run on this tree (built by R09, R17) |
| H-270 | A | B12 | A statement written for a tenant scope is run in a network scope (or the reverse), so a projection is written from a tenant, or private data is read f | the tests the row names exist; not run on this tree (built by TEN-037) |
| H-321 | E | - | "Planned" is sent as routine and read back as "Today" (DEC-397), so the advisor sees a different urgency from the one chosen | closed in code: W7A DEC-773: planned is stored and answered as planned |
| H-330 | A | B12 | A read that fails shows an empty list, so a service that is overdue reads as "No services need chasing." | the tests the row names exist; not run on this tree (built by W17) |
| H-495 | E | - | The shift lead's escalation stops when an advisor presses an action on the withdrawal alert without phoning the caller | closed in code: DEC-854 option (a) built: frontend/components/advisor/WithdrawalAlert.tsx:12-13,74-77 |
| H-496 | A | B4 | An advisor not on the card when a withdrawal arrives does not see the alert (backstop is the shift lead escalation) | built by W21; the control gap is in What |
| H-362 | A | B12 | A reviewer approves a registration with a check still missing | the tests the row names exist; not run on this tree (built by W29) |
| H-504 | A | B12 | Advisors see the owner's change before a clinical lead has approved it | the tests the row names exist; not run on this tree (built by W30) |
| H-505 | A | B12 | A need is both accepted and not accepted, so the criteria contradict themselves | the tests the row names exist; not run on this tree (built by W30) |
| H-507 | A | B12 | A clinical lead approves a change they wrote | the tests the row names exist; not run on this tree (built by W31) |
| H-508 | A | B12 | An overdue criteria set reads as current to advisors without a flag | the tests the row names exist; not run on this tree (built by W31) |
| H-368 | A | B7 | An executive reads a stale board figure as current: show the age on every attention line | built by W40; the control gap is in What |
| H-375 | E | - | A clinical advisor gives advice without the case's details on the screen | closed in code: DEC-855 built: frontend/components/clinical/CaseView.tsx:147-150 |
| H-514 | E | - | Advice is given on the request, but the advisor's dialog still says "Waiting for a clinical advisor", so the advisor calls again or acts without it | closed in code: DEC-855 built: dialog shows advice or says it could not read it (W8B) |
| H-379 | D | - | Patient details are typed into a free-text report, where the tool holds them | accepted: patient detail in free text can only be hinted, not recognised |
| H-518 | A | B12 | A broken audit chain is read as a sound record | the tests the row names exist; not run on this tree (built by W47) |
| H-414 | D | - | Patient detail typed into a problem report is kept readably | accepted: the back end cannot recognise patient detail in free text; hint and guidance only |
| H-430 | A | B12 | A token issued from a code names the wrong person, service, device or tenant | the tests the row names exist; not run on this tree (built by W7B A2) |
| H-436 | A | B12 | A chase list that failed to read shows as "nothing to chase" | the tests the row names exist; not run on this tree (built by W7B C) |
| H-438 | A | B12 | Another tenant's registration, criteria, service, phone or invitation is read | the tests the row names exist; not run on this tree (built by W7B) |
| H-523 | D | - | A staff phone number (a reporter's, a cover's, a registration call-back, a tenant administrator's) is kept in plain text on a ProtectedContact node, s | accepted for the pilot (DEC-856 option b); application-level encryption is KI-859a (A) |

### 7.2 Severity TBD

157 open hazards read TBD. 126 of them (listed here) carry no gap other than the severity: they are open on Q1 only, and the verification run in B12 task 1 covers them whatever the answer. The tests they name exist.

H-01, H-02, H-03, H-04, H-05, H-06, H-07, H-08, H-09, H-10, H-11, H-12, H-13, H-14, H-15, H-16, H-17, H-18, H-19, H-20, H-21, H-22, H-23, H-24, H-25, H-26, H-27, H-30, H-28, H-31, H-32, H-29, H-36, H-T02, H-T01, H-33, H-34, H-T14, H-T15, H-T21, H-T22, H-35, H-37, H-38, H-39, H-41, H-40, H-42, H-47, H-50, H-53, H-54, H-56, H-58, H-59, H-61, H-65, H-77, H-78, H-79, H-80, H-81, H-88, H-89, H-90, H-91, H-92, H-93, H-95, H-98, H-99, H-100, H-101, H-102, H-103, H-104, H-105, H-113, H-120, H-121, H-122, H-123, H-124, H-125, H-126, H-127, H-128, H-130, H-131, H-132, H-133, H-134, H-136, H-138, H-140, H-141, H-142, H-143, H-145, H-146, H-147, H-148, H-149, H-150, H-151, H-153, H-154, H-180, H-181, H-182, H-183, H-184, H-195, H-196, H-197, H-199, H-201, H-202, H-203, H-204, H-205, H-206, H-207, H-208, H-222, H-223.

The remaining TBD rows have a specific class:

| Hazard | Class | Bundle | What |
|---|---|---|---|
| H-46 | A | B2 | Provider accepts, commit fails, redelivery texts twice: needs a fault-injection test and a send-once guard (KI-185) |
| H-48 | C | - | A district's mean is shown as the patient's house, so travel is estimated from the wrong place |
| H-49 | C | - | A wrong centroid file (swapped columns, a foreign postcode, a duplicate) puts patients in the wrong place |
| H-51 | A | B12 | Add a test that no case path calls the geocoder (it is used only for a service site address, W24) |
| H-52 | C | - | A service's site is placed at the wrong UPRN, so its position and travel range are wrong |
| H-55 | A | B8 | A Redis reset restarts the PIN rate-limit window (U32 needs a durable attempt count; DEC-072 reads attempts under the write lock) |
| H-57 | C | - | Patient position leaves the platform for a third-party routing service |
| H-71 | A | B11 | O01 db. prefix admits db.statement (KI-221) |
| H-72 | D | - | A session or trace id is spliced into KQL and changes the query |
| H-73 | D | - | A console user reads another tenant's telemetry |
| H-74 | C | - | The hook issues links on request, so a leaked token or a hook on a production host lets anyone make a link |
| H-75 | C | - | A synthetic run texts a real person or number, or opens a link off the target |
| H-85 | A | B6 | Score write accepts a Dx code not on the Pathways list (KI-247) |
| H-86 | C | - | Production advisors are offered sample codes that are not real |
| H-97 | A | B8 | A code is stored for an unknown number (I13/U25) |
| H-N02 | A | B10 | Network UI: member sees another member's private data: specified, TEN-069..071, 081 not built |
| H-N03 | A | B10 | Stale projection read as live: specified, TEN-070/071 not built |
| H-N04 | A | B10 | Wall shows the wrong network's board: TEN-072 on W9I; header sentence in TEN-069 |
| H-N08 | A | B10 | A left member still shown live: UI part TEN-070 |
| H-N15 | A | B10 | Network board shows wrong place or label: TEN-070 |
| H-135 | A | B4 | B4/B5/B6 echoes are text only; email and push reporters get none (KI-357) |
| H-137 | A | B2 | A prompt delivered before suspension still sends (KI-388); SendPrompts re-checks suspension only |
| H-144 | A | B5 | Approval trusts a stored automatic-check flag: re-run at approval (U29) |
| H-157 | D | - | A duplicate push after a transient failure |
| H-175 | A | B3 | Due, opening and quiet hours computed outside the tenant zone (KI-447, 449) |
| H-190 | A | B6 | Replay cannot show the "+2" over-capacity figure (KI-475; W9G records over_by for new displays) |
| H-191 | B | Q19 | A clinician who does not hold the clinical-lead role is never notified: confirm the role model |
| H-192 | A | B6 | No case version: concurrent PUTs on one open case are last-write-wins (routes_cases.py DEC-398) |
| H-193 | A | B6 | Planning best-fit uses board order, not travel order (KI-476) |
| H-194 | A | B12 | Presence isolation test with the in-memory cache that does not prefix |
| H-198 | A | B5 | Activation loses provider/location/coverage the registration wrote (KI-363) |

### 7.3 Everything else that is open

Rows whose tests exist and have not been run on a database (class A, B12 task 1):

H-470(H), H-471(M), H-472(M), H-473(H), H-477(M), H-478(M), H-385(L), H-270(H), H-330(H), H-331(M), H-485(M), H-332(L), H-360(M), H-361(M), H-362(H), H-364(M), H-504(H), H-505(H), H-507(H), H-508(H), H-511(M), H-512(M), H-513(L), H-517(M), H-518(H), H-519(M), H-430(H), H-431(M), H-432(M), H-433(M), H-434(M), H-435(M), H-436(H), H-437(M), H-438(H), H-439(L).

(H = HIGH, M = MEDIUM, L = LOW.) The B1 to B11 hazard rows are in the bundle sections.

## 8. Open decisions

`decisions.md` has 11 single decisions and one group of 57 builder decisions whose status waits on a person (60 status lines match "owner to confirm"). DEC-854, DEC-855 and DEC-856 were all decided on 2026-10-30; the "OPEN" in their status text is history, and what remains is building and verifying DEC-854 and DEC-855 (class E: built) and the go-live encryption of DEC-856 (A row KI-859a).

| Decision | Subject | Class | State | Evidence |
|---|---|---|---|---|
| DEC-854 | Withdrawal or not-reached alert acknowledged only by an explicit answer | E | Built (W8A DEC-865): only "I have phoned the caller" or "The caller is already being helped" acknowledge. Awaiting the verification run; H-495 closes with it. | frontend/components/advisor/WithdrawalAlert.tsx:12-13,74-77 |
| DEC-855 | Clinical advice screens not offered without the case; advisor sees the answer | E | Built (W8B): no advice form when the case read fails; the dialog shows the advice or says it could not read it. Awaiting verification; H-375, H-514, H-412 close with it. | frontend/components/clinical/CaseView.tsx:147-150 |
| DEC-856 | Phone numbers in plain text on ProtectedContact | D | Accepted for the pilot only (option b, Aura encrypts at rest). Go-live of any further tenant needs option (a): A row KI-859a in bundle B8. | backend/src/diucs/adapters/outbound/graph_store/contact_store.py |
| DEC-029 | No report ever: Monday overdue reading | E | Resolved by DEC-134 item 3 (accepted as written). | decisions.md DEC-134 |
| DEC-048 | GROUP_WINDOW of 10 minutes is [ASSUMED] | B | Kept as a named constant (DEC-134 item 1); clinical sign-off is in Q2. | backend/src/diucs/domain/rules/multi_service.py |
| DEC-047 item 9 | Printed need wording in B1 | A | Decided (DEC-134 item 2) but not built: B1 still prints the raw code. Bundle B4 task 1. | backend/src/diucs/application/use_cases/request_booking.py:106-111 |
| DEC-044 items 1, 4 | Fifth wrong PIN outcome and fail-closed clock rules | B | In force; pending owner confirmation. Part of Q2. | domain/rules/identity_policy.py |
| DEC-034 items 3, 4 / DEC-042 item 3 | Email and push wording | C | Needs IG written approval (an external approval, never claimed). Wording stays IG-pending; no real send uses it. | domain/messages/templates.py |
| DEC-097 | Staff identity provider design sign-off | C | The design sign-off is human only; the Entra verifier is KI-531 (A, B8) and the live run needs a real tenant. | decisions.md DEC-097 |
| DEC-632 | Shift lead and the advisor call guard | E | Closed by DEC-860 (W8A): a shift lead does not work a call. | fragments/W8A.md |
| DEC-405 item 1 | Requester cannot approve their own registration (H-199) | D | Accepted and built (unit test named in H-199); the hazard stays open only for the verification run. | tests/unit/application/use_cases/test_approve_registration.py |
| 57 builder decisions marked "owner to confirm" or "owner to reconcile" | DEC-015, 038, 055 to 057, 063 to 066, 068, 071 to 076, 080 to 089, 094 to 096, 098 to 101, 104 to 111, 115, 122, 125, 680 to 692 | D | Accepted by the orchestrator under DEC-133; nothing waits for a person. The only items that need a human are the [ASSUMED] values and wording gathered in Q2. | decisions.md status lines |

## 9. Ledger drift

The ledger (`delivery.py status`, shared state in `/home/user/overwatch/.git/diucs-delivery`) reads 109 delivered, 187 not-started, 5 stale of 301. Of the 192 that are not delivered, **174 have their `implement` commit on integration/build** (built, unit-tested, not verified: the build-wave rules defer evidence and verification), 8 have their code under another label (section 9.2), 3 are built on a running W9 branch and not merged, and 7 are not built (section 9.3). Nothing below was changed in the ledger; the ledger update is B12 task 4.

### 9.1 Stale ledger entries (held, no heartbeat) whose code is merged

| Task | Ledger | Code on integration/build |
|---|---|---|
| I05 Scheduled work consumer | stale | `implement` 246cfb5, files 1/1 |
| R15 Wall screen pairing endpoints | stale | `implement` a212a90, files 1/1 |
| U11 OpenCase use case | stale | `implement` 26e5f78, files 1/1 |
| R16 Pathways Dx code lookup endpoint | stale | `implement` 4298a4b, files 2/2 |
| W09 Staff sign-in with Entra ID and role guard | stale | `implement` 9cac9aa, files 2/3 |

### 9.2 Built under another label (no `<ID>: implement` commit, code present)

| Task | Ledger | Where the code is |
|---|---|---|
| R07 Case endpoints and $filter-options | not-started | W7A (routes_cases.py, case_mapping.py, DEC-770 to DEC-781) |
| R17 Advisor acknowledgement of a withdrawn booking | not-started | `$acknowledge` in routes_alerts.py; DEC-854/865 built the screen rule |
| TEN-013 Link token record and store carry the tenant (reworks D | not-started | link_token_repository.py carries tenantId (checked :204) |
| TEN-061 Two-member network tests: grant lifecycle, leave, histo | not-started | W9A bundle (test_grant_lifecycle.py, test_network_history.py) |
| TEN-062 Two-member network tests: privacy scan, scope binding,  | not-started | W9B (two-member network tests) |
| TEN-074 Tenant offboarding, export and purge | not-started | W9A (tenant_offboard.py, tenant_purge.py, export_files/) |
| TEN-079 Network and grant administration API | not-started | W9A (routes_network_admin.py) |
| TEN-086 Hazard log rows and tenancy runbooks | not-started | W9A: runbooks only; the hazard rows are still in fragments/TEN-086.md |

### 9.3 Not built on integration/build

| Task | Ledger | State |
|---|---|---|
| TEN-068 BFF network scope: routes, availability check, stream r | not-started | not started (B10) |
| TEN-069 Scope header and organisation label components | not-started | not started (B10) |
| TEN-070 Network board UI and unavailable states | not-started | not started (B10) |
| TEN-071 Network directory and criteria views | not-started | not started (B10) |
| TEN-072 Wall screen administration and last-known by scope | not-started | built on W9I, not merged |
| TEN-076 Tenant administration screens | not-started | built on W9D, not merged |
| TEN-080 Network administration screens | not-started | not started (B10, after W9D) |
| TEN-081 Grant approval and sharing transparency screens | not-started | not started (B10, after W9D) |
| TEN-083 Operator console screens (last, droppable) | not-started | built on W9D, not merged |
| TEN-085 Two-tenant and network end-to-end suite | not-started | not started (B10, after W9I and Chromium) |

### 9.4 The 174 built tasks (evidence and verification outstanding)

Each has `<ID>: failing tests (red)` and `<ID>: implement` on integration/build. B12 task 4 records evidence and an independent verification, then `delivery.py deliver`. Listed by stage; the cell is the `implement` commit.

- **S10** (7): I15 d334abd, W50 1b168f6, U43 ada9a04, W51 1a4af99, W52 e4f8035, W53 84906a8, G13 2f2dd83
- **S2** (26): I05 246cfb5, TEN-012 0af49af, TEN-014 e5baea1, TEN-016 0440654, TEN-017 d85cc96, TEN-018 0582fa1, TEN-019 1c0da3c, TEN-020 8f87a0b, TEN-021 ac40e73, TEN-022 af97e6a, TEN-023 7d5799f, TEN-024 1d0e093, TEN-025 ccd18ed, TEN-026 6c0e695, TEN-027 e21fca9, TEN-028 e25f9c8, TEN-029 364f73b, TEN-030 a4b95a3, TEN-031 e9bb125, TEN-032 2e19791, TEN-033 b562153, TEN-034 a255df1, TEN-035 4f49369, TEN-036 231db46, TEN-037 4aec1d5, TEN-038 ea4810e
- **S3** (27): I10 9e3db48, R15 a212a90, W08 80f4f81, O01 a792324, TEN-039 9e50c35, TEN-040 4f18d9d, TEN-041 aeffcdc, TEN-042 b36157e, TEN-043 71abce2, TEN-044 7dea50c, TEN-045 b2317c1, TEN-046 ebb7507, TEN-047 b8e1d2b, TEN-048 0edbe62, TEN-049 110916e, TEN-050 094cd82, TEN-051 e0c4a65, TEN-052 d9d24ec, TEN-053 33b3b54, TEN-054 78ca2aa, TEN-055 f3c3e3b, TEN-056 0e1c75d, TEN-057 270ef1e, TEN-058 d2c696c, TEN-059 552c5c9, TEN-060 26b6307, TEN-063 95b5ea8
- **S4** (25): U11 26e5f78, U12 141858e, U13 d08cebe, U14 bd6c9ec, U15 0e5a87a, U16 e42872b, G11 6b4afab, I11 aecd6c6, R08 64af7ec, R16 4298a4b, W09 9cac9aa, W10 b68777c, W11 5b6eb7f, W12 a1cb209, W13 88cede2, W14 e785ad8, W15 5c4bf0b, W16 7e14110, W17 7e38eb0, W18 cbc1b2f, S01 a3319b0, TEN-064 d5b297d, TEN-065 ff224ba, TEN-066 c2cb541, TEN-067 b455a6f
- **S5** (12): U17 fdec943, U18 6bce828, U19 88ce9ab, U20 167929d, U21 18c948b, U22 b776784, R09 c69a890, L02 3f8a77c, W19 ba0ca7d, W20 5c335e5, W21 f2794ad, W22 3bbc991
- **S6** (25): U23 bac433e, U24 e2bed27, U25 45ad102, U26 eabe0a9, I12 bdec295, U27 c91a515, U28 8a37e64, U29 3bc98b4, U30 7946dc7, U31 0ccc480, R10 febdd6c, W23 7d79fb4, W54 cd7bd91, W24 7dc125d, W25 5f857c3, W26 a18dd41, W27 b91ff3c, W28 f4146d8, W29 f29f524, W30 4632998, W31 8ed7b02, TEN-073 401b5ba, TEN-075 ff8e4ef, TEN-077 c1a93e9, TEN-078 eeed8f0
- **S7** (21): P17 f2bdee4, P19 ff9dc6c, U32 1c6ad66, I13 f515eea, I14 277e61b, R11 c43b001, W32 7538379, W33 e08ba62, W34 a06ea13, W35 3077011, W36 b7eb9e2, W37 53cca75, W38 17933bf, U33 a3063dd, U34 3a4af35, U35 cf69f8c, R12 d3f577b, W39 f459b03, W40 ad736a1, W41 cece7de, TEN-082 4c1dc87
- **S8** (18): P18 02fd363, P20 9193348, U36 afedda5, U37 a94f92a, U38 2eb0ecf, U39 1c0d37b, U40 2e5ec1d, U41 598cc21, U42 19da2e8, R13 627ee21, R14 0bd8806, W42 553cc83, W43 57ffba3, W44 a7ce018, W45 06b01c5, W46 48fd855, W47 8146df4, W55 2dbea06
- **S9** (13): O02 0ca43a7, O03 95c1180, O04 1d87ff2, O05 2b72e1b, O06 2bbacc9, O07 0dacffb, O08 a0c85c4, R18 2c8153d, W48 f9cf7a5, W49 e9939d6, W56 09b4ba9, O09 ab0b730, TEN-084 fa0923d

## 10. Unfolded fragments

18 files in `docs/delivery/fragments/` have not been folded into the shared documents: about 128 known-issue rows and 85 hazard rows, and decisions numbered DEC-860 to DEC-868 (W8A), DEC-1000 to DEC-1012 (TEN-075) and later. They are outside the 846 rows triaged above. Their known-issue rows are still true as a rule (they are the newest) and map to the same bundles: W8A, W8B and W9G rows to B6 and B7, W8C to B5, W8D, W8E and W9H to B7 and B8, TEN-056, 061, 062, 067, 074, 075, 077, 078, 079, 082, 086 and W17-W43-network to B10, B3 and B1 (the "no process builds the app" rows are KI-587 in B1). B12 task 5 folds them; the first action of each bundle is to read its fragments.

## 11. Limits of this triage

- 846 rows were each read and given one class; about a quarter have a probe with `file:line`. The rest rest on the row text and on cluster searches (not-built answers, tenant-pending statements, the UNCONVERTED ratchet, the wave-8 and wave-9 fragments). A bundle builder re-reads its rows first and moves a row to E if it is already true.
- No test was run. Counts of closed rows are therefore "closed in code", not "verified".
- Hazard severities were not changed. The hazard classes follow the status words in the log; a hazard marked A (B12) is "tests exist, not run", which is the honest state, not a claim of closure.
- The ledger-drift table counts a task as built when an `implement` commit with its id exists on the tree; a task built under a bundle label is listed in 9.2.
