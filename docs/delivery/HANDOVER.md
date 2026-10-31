# Handover: where the build stands (31 October 2026)

Written when the work moved from the cloud session to a local agent. Read `CLAUDE.md` and the `diucs-delivery` skill
first; `docs/delivery/decisions.md` overrides everything else. Nothing here is a decision; it is the state.

## 1. Where the code is

- `main` holds all merged work: the whole application as built (`integration/build` fast-forwarded into it). **Most of it is
  built but not independently verified.** The ledger says 109 of 301 tasks delivered; about 184 are built, unverified.
- Local branches and worktrees from the cloud session are NOT needed after this push: everything worth keeping is on `main`.
  The exceptions are listed in section 2.
- The delivery ledger is the append-only event log at `.git/diucs-delivery/events.jsonl` (not in git). Its backup is
  `docs/delivery/ledger.jsonl` (refreshed with `delivery.py render --out docs/delivery` at this handover). On a fresh clone:
  `delivery.py init --restore docs/delivery/ledger.jsonl`.
- Builder briefs used this session are in `docs/delivery/builder-prompts/` (shared rules: `wave2_builder_prompt.md`).
- Agent fragments (decisions, hazards, known issues with triggers, route tables) are in `docs/delivery/fragments/` and are
  NOT folded into the shared documents yet (`fragments/README.md` says how).

## 2. Not merged into `main` (kept as files, not branches)

| What | Where | State |
|---|---|---|
| **WB11**: TEN-072 and the network variants of the advisor and executive screens (38 commits, net diff against `0e901b7`) | `docs/delivery/parked/WB11-network-options-and-views.diff` (apply with `git apply` at commit `0e901b72`) | Finished by its builder (fragments `WB11.md`, `WB11-routes.md` on that branch only) but it CONFLICTS with what is on `main`: WB6 built its own `FilterNetworkOptions` (KI-349, KI-181, KI-794, DEC-1176, `network: "unavailable"`, own services first, own-only outcome form) and WB11 built another (TEN-051/053, `NetworkOption`, `NetworkNotSuitable`). Conflicts: `filter_network_options.py` (8 regions), `routes_network.py`, `test_filter_network_options_rules.py`, `frontend/components/advisor/OptionsMap.tsx`. The two designs and their front ends disagree on the row shape; one must win, or WB6's route must grow WB11's fields. Reconcile by hand with tests, then the TEN-072 pieces (network home counts, exec home, map) can land. |
| `task/neo4j-harness-slots` (one commit): N concurrent Neo4j slots for the test harness, parked on purpose | `docs/delivery/parked/neo4j-harness-slots.mbox` (`git am`) | Not needed unless the single shared Neo4j becomes the bottleneck. |
| **WB16**: the Twilio webhook forward in `web` (DEC-1302) | was running at handover in worktree `WB16` (cloud) | If it is not on `main`, rebuild from `docs/delivery/builder-prompts/wb16_prompt.md`. Until it is deployed, Twilio webhooks must NOT be pointed at the `web` host (404). |

## 3. Gaps, stubs and deferred work

**Cannot work yet (blockers for a real pilot)**
- **No real sign-in on the API.** `RefusingIdentityVerifier` (`bootstrap/api_main.py`) refuses every sign-in: the Entra identity verifier (B8) is not built.
- **Twilio webhook route** (DEC-1302): not on `web` yet (WB16).
- **Images not built or deployed**; the apps in Azure are hello-world placeholders. The web tier's Key Vault reads (WB15) and the back end's (WB14) are on `main` but have never run against a real vault.
- **Aura Neo4j**: `neo4j-password` is in Key Vault; the schema/migrations have not been run against it. Redis from the Container Apps environment is untested (internal only).
- **Service Bus**: topology re-created from the current config; the 11 stale subscriptions still exist (list in `known-issues`/the session notes: `alerts.events/{analytics,escalation-timer}`, `booking.events/{advisor-stream,analytics,notifier}`, `capacity.events/analytics-aggregator`, `criteria.events/{flag-maintainer,notifier}`, `registration.events/{analytics,lead-queue-projector,notifier}`).

**Stubs in code**
- `HttpOdsLookup` (`adapters/outbound/terminology/ods_http.py`) raises NotImplementedError: the live ODS lookup is not built.
- `NoPostcodes`, `NoGeocoder`, `NoTelemetry`, `NoSecrets` (`bootstrap/container.py`): the no-op defaults a process falls back to; the postcode centroid file and the OS Places key are deployment inputs.
- Twilio Email API request body and Operation counts are assumed (H-780) and need a live check.

**Known gaps recorded by the builders (triggers are in the fragments and `known-issues.md`)**
- Network option cards have no Criteria button; network rows are audited as `FilterNetworkOptions` (the clinician's "what the advisor saw" shows own services only).
- Advisor work phone and advisor line have routes but no tenant-admin screen; a number cannot be cleared.
- "Copy summary" before an outcome is chosen has no destination. Email and push booking echoes are text only (KI-357). The three score-correction reason labels are [ASSUMED].
- KI-1303: behind `web` every visitor shares one API rate-limit bucket (no `clientIp` passed).
- KI-1304: Service Bus still uses a connection string; identity auth later. KI-1306: a cold vault read blocks the event loop one round trip. H-831/KI-1305: tenant ids containing `--` or ending in a hyphen cannot have Twilio secrets (provisioning does not refuse them yet).
- Rotating `session-secret` signs everyone out and takes up to 10 minutes to reach a replica; no previous-key unseal. The web tier has no start-up secret check (a bad revision shows as 5xx on first use).
- `pytest -n` does not work for `tests/unit` (collection differs between workers); run the unit suite serially (about 8 minutes).

**Not yet run on the final combined tip**
- Backend integration suite (`make test-integration`), tenant isolation mutants after the late merges, Playwright (Chromium not installed here; needs the real-stack TEN-085 two-tenant e2e, not built), the screen recordings the owner asked for.
- Last runs: backend unit and architecture 15,697 passed (after WB14, before WB12); front-end vitest 7,356 passed (after WB15, before WB12); typecheck and lint clean; build clean before WB12.
- Independent verification (Sonnet verifier bundles) of the ~184 built tasks, then `deliver` in dependency order.

**Triage bundles not yet built**: B3, B5, B7, B9, B11, B12 (and the real Entra verifier, B8-rest). `OpenBookingAlerts` and other items in `known-issues.md`. TEN-085.

**Housekeeping**: fold the 47 fragments into `decisions.md`, `hazard-log.md`, `known-issues.md`, `contracts.md`; hazard and decision numbers were allocated in blocks per agent.

## 4. Decisions the owner still has to make

- Overwatch rename (`overwatch-rename-plan.md`): D2 name in the UI, D3 env prefix (`OVERWATCH_` recommended), D4 SMS prefix wording (patient-facing, needs written approval), D6 leave ledger history verbatim, D7 Entra role names, D8 crypto constants. D1/D5 are decided (DEC-1300, DEC-1301). The rename runs in a quiet window after open work merges and before verification.
- Clinical safety officer sign-off of hazard severities; Aura tier; UK West for DR; Bicep or Terraform; owner questions Q2, Q9, Q12, Q14, Q16-Q18 and the minor ones (provisional answers in DEC-1100).
- Manual Azure steps still the owner's: Entra admin consent per tenant; Twilio subaccounts, numbers, sender domains, the per-tenant `twilio--<tenant>--auth-token` secret (then delete the global `twilio-*` entries, DEC-1304 item 9); Cloudflare WAF and IP restriction once the proxy is on; real-device push check; rotate the Neo4j password and Twilio token that were pasted into chat.

## 5. Local environment notes

- Back end tests need Docker: shared Neo4j for parallel integration runs (`DIUCS_TEST_NEO4J_URI`), Redis, the Service Bus emulator (compose project `diucs-b3sb`, config must equal `infra/servicebus-config.json`). Do not remove containers named `diucs-local-*` or `diucs-test-neo4j-*` you did not start.
- Run the API and workers locally with `DIUCS_SECRETS_DIR` (the file secret store, `backend/scripts/make_local_secrets.py`); with `DIUCS_KEY_VAULT_URL` they read the vault through `az login`. See `docs/delivery/fragments/B8.md` and `infra/azure/SETUP.md` section 5a.
- Pushes to `main` have been rare on purpose (the owner's rule); CI is manual (`workflow_dispatch`).
