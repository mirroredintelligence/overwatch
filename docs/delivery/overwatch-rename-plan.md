# Plan: replace every DIUCS reference with Overwatch

Status: plan only, 2026-10-31. Nothing has been renamed. The counts come from `git grep` over `integration/build` at
`0e901b7`, which holds the whole application; `main` holds only the delivered subset and your logo and splash commits
(`9fb2a16`, `9b9b657`), which I pulled into the `main` checkout and which are not yet on `integration/build`.

"DICUS" (the typo) appears nowhere in the tracked files, so only `diucs` / `DIUCS` / `Diucs` need replacing.

## 1. What carries the old name

Totals: **1,925 files and 14,026 matching lines**, plus **492 tracked paths** with `diucs` in the name.

| Where | Size | What it is | Risk |
|---|---|---|---|
| **Python package** `backend/src/diucs/` (path and imports) | 402 source files, 8,037 import lines, 780 test files; 470 of the 492 paths | the package name itself: `from diucs.domain ...`, `.importlinter`, `pyproject.toml`, `uv.lock`, mypy and entry-point settings | mechanical, but it touches nearly every file and every open branch |
| **Skill and tooling** `.claude/skills/diucs-delivery/` | 17 paths; `CLAUDE.md` names it; ledger folder `.git/diucs-delivery` and `.diucs-delivery` | the delivery skill and its scripts | renaming the ledger folder moves the ledger: must be moved, not recreated |
| **FHIR profile files** `backend/profiles/Diucs*.json` | 5 files, plus 26 files in `backend/terminology/` | profile and code-system names | wire format (see below) |
| **Front-end page titles** | 72 lines, e.g. `'Options · DIUCS capacity'` | the browser tab and history title of every page | visible, easy |
| **Front-end copy** | about 35 lines in components: eyebrows ("DIUCS booking request", "DIUCS capacity update"), the shift lead heading, registration headers, the wall pairing heading, tour and help text, home-screen install steps, the invitation text preview, `PRODUCT_NAME` in `lib/product.ts` | what people read | visible, easy |
| **PWA** | `manifest.webmanifest` (`name`, `short_name`), `sw.js`, `sw-logic.js`, the three PNG icons in `public/icons/` | the installed app name and icon | icons are binary: regenerate from your new mark |
| **Texts sent to people** | 18 lines in `domain/messages/templates.py` and 19 more in `domain/messages/`: every SMS starts "DIUCS: ...", and the email and push bodies repeat it | patient-facing and clinician-facing wording | visible; wording change, see decision D4 |
| **Environment variables** | 184 source lines: the `DIUCS_` prefix of every setting (`DIUCS_FHIR_BASE_URL`, `DIUCS_PUBLIC_URL`, `DIUCS_NEO4J_*`, `DIUCS_SERVICEBUS_CONNECTION`, the `DIUCS_TEST_*` family, and more), CI, compose, Azure scripts, docs | configuration contract | breaks deployments and CI until set again |
| **Cookies** | 47 lines: `diucs_session`, `diucs_csrf`, `diucs_link_csrf`, and others | browser state | signs everyone out once |
| **Token audiences** | 30 lines: `diucs-api`, `diucs-ops` | JWT `aud` of every back-end token | tokens issued before the change are refused |
| **Entra role values** | 63 lines: `DIUCS.Advisor`, `DIUCS.Lead`, `DIUCS.Support`, `DIUCS.PlatformOperator` and so on | the app-role names the staff sign-in maps | must match what is configured in Entra |
| **FHIR canonical URLs** | 67 source lines and about 170 more in profiles and terminology: `https://diucs.example/CodeSystem/...`, `/StructureDefinition/...`, extension URLs | identifiers stored in resources and used in `meta.profile` | wire and stored format (see decision D1) |
| **Cryptographic constants** | 2: the HKDF salt `diucs/tenant-key/v1` (`tenant_keys.py`) and the content-seal label `diucs:prompt-content:v2` (`aes_gcm.py`) | key derivation | changing them changes every derived key: tokens, link hashes, sealed content stop verifying |
| **Telemetry names** | `SERVICE_NAME = "diucs-backend"`, instrumentation name `diucs`, a FastAPI flag | what shows in traces | dashboards and the collector allow-list |
| **Docker and compose** | 47 lines: `diucs-test-shared-neo4j`, `diucs-test-neo4j-*`, compose project `diucs-b3sb`, `diucs-local-*`, volumes | local and CI infrastructure | running containers are recreated |
| **Azure** | your `infra/azure/` scripts (15 lines): `P="diucs"`, `rg-diucs-pilot-uks`, `kv-diucs-*`, `sb-diucs-*`, `redis-diucs-*`, identities, Entra app display names "DIUCS Staff (pilot)" | resource names | an Azure resource group and most resources cannot be renamed: see decision D5 |
| **CI** | `.github/workflows/ci.yml` (comments, `DIUCS_TEST_NEO4J_*`) | pipeline | with the env var rename |
| **Documents** | `docs/plan` 231 files and 2,515 lines (the task prompts and plan); `docs/spec` 7 files, 342 lines; `docs/delivery` 128 files, about 1,000 lines (decisions 144, known issues 44, hazards 6, fragments, evidence), plus 526 lines of ledger and evidence history | product name in prose, and `backend/src/diucs/...` paths in references | prose is easy; history is a policy choice (decision D6) |
| **Logos and brand** | no tracked DIUCS logo exists; the three PWA icons are the old mark | the visual identity | replaced by your files |

There is **no About page, menu or footer** in the application that carries the name: the places a person sees it are the
page titles, the installed app name and icon, the pairing and sign-in headers, the tour and help text, the registration
screens, and the texts and emails we send.

## 2. Your brand assets (already on `main`)

`frontend/public/brand/overwatch-mark.svg` (a ring and dot over a horizon line), `overwatch-logo.svg`,
`overwatch-logo-reversed.svg`, and the splash: `components/brand/Splash.tsx` and `Splash.module.css`, with a dev-only
`/splash-preview` route.

Where they go: PWA icons (192, 512, 512 maskable) regenerated from the mark; favicon and apple-touch-icon; the wall
board and wall pairing headers (reversed logo on dark); the sign-in, registration and reporter headers (logo); the
installed-app launch (the splash); and the email template header. I need to check the splash component's behaviour
(what it renders and for how long) before wiring it to app launch.

## 3. Order of work (so nothing breaks in the middle)

The rename touches nearly every file, so it must run in a quiet window: **after** the running bundles WB6, WB11 and
WB12 are merged and **before** verification starts, in one pass with all worktrees closed. Merge `main` into
`integration/build` first (it is not currently an ancestor; the differences are your logo, splash and Azure commits).

1. **Decisions** (section 4), then freeze other work.
2. **Visible copy and brand** (front end titles and copy, `PRODUCT_NAME`, manifest, icons, splash wiring, message
   templates). Test-first: update the tests that assert the old strings (there are many), then the strings.
3. **Configuration identifiers**: env var prefix (settings, tests, CI, compose, scripts, docs), cookies, audiences,
   Entra role values, telemetry names, docker and compose names, Azure scripts. One scripted pass, with a guard test.
4. **The Python package** `diucs` to `overwatch`: `git mv`, a scripted rewrite of imports, then `.importlinter`,
   `pyproject.toml`, `uv.lock`, mypy and entry points, then the full static checks and test suites. One commit.
5. **FHIR canonical URLs, profile names and crypto constants**: a coordinated change, plus a fresh graph (there is no
   production data; test databases are rebuilt by the harness).
6. **Tooling and docs**: rename the skill folder and update `CLAUDE.md` and the skill text; move the ledger folder
   (`.git/diucs-delivery` to the new name) instead of creating a new one; rewrite prose in `docs/plan`, `docs/spec` and
   the living parts of `docs/delivery`.
7. **A guard**: a test that fails if `diucs` (any case) appears in tracked files outside an explicit allowlist (the
   append-only ledger and the historical evidence, if D6 keeps them), so the name cannot creep back.
8. **Full verification**: unit, architecture, front end, a full integration run, `pnpm build`, and Playwright with
   screenshots of the renamed screens and the installed-app view.

Method: a deterministic script (not a model rewriting files), run on a branch, reviewed by diff counts (every changed
line contains the old name; nothing else changes), then the full suites. I would use Sonnet only to review the
identifier and crypto changes (steps 3 and 5), not to make the edits.

## 4. Decisions I need from you

- **D1. FHIR canonical base URL.** Today `https://diucs.example/`. Choose the replacement: `https://overwatch.example/`
  (a placeholder, as now) or your real domain (for example `https://fhir.<your domain>/`). It is part of every stored
  resource, so it should be the real one if you know it.
- **D2. Product name in the interface.** "Overwatch" alone, or "Overwatch capacity"? Today it reads "DIUCS capacity".
  The installed-app short name needs something short (the manifest has 12 characters of room on most phones).
- **D3. Environment variable prefix.** `OVERWATCH_` (recommended).
- **D4. Text message prefix.** Every SMS begins "DIUCS: ". "Overwatch: " is 11 characters against 7, which shortens the
  room in one segment. It is also patient- and clinician-facing wording, which you asked to be approved in writing
  (DEC-1100, question 2). Say whether this prefix change counts as approved, and whether the sender name registered with
  Twilio and carriers should become Overwatch too.
- **D5. Azure resource names.** You have started building `rg-diucs-pilot-uks` and the resources named after it. Azure
  cannot rename a resource group and most resources. Either keep the infrastructure names as they are (they are never
  shown to a user) and rename only the Entra app display names, or change `P="diucs"` to `P="overwatch"` in
  `create-pilot.sh` and `redis-app.bicep` now and recreate the pilot (cheap while it is empty). I recommend deciding
  before more is created. Say which.
- **D6. History.** The append-only ledger (`ledger.jsonl`) and the old evidence files record what happened under the old
  name. I recommend leaving them verbatim (rewriting an audit log defeats it) and rewriting only the living documents.
  The guard test would allowlist those two folders.
- **D7. Entra role values.** `Overwatch.Advisor` and the rest, to be created like that when you make the app
  registration manifest (nothing is configured yet, so it is free to change).
- **D8. Crypto constants.** Changing the HKDF salt and the content-seal label is safe only because nothing is in
  production. Confirm that no environment (including your pilot) holds data sealed or tokens signed with the old ones.

## 5. Effort and risk

About two to three hours of agent time for steps 2 to 7, then the full pass. The real risk is merge conflicts with
in-flight work, hence the quiet window; the second is the name appearing in tests that assert exact strings, which the
guard and the suites will find. No behaviour changes except what is listed: cookie names (everyone signed in is signed out
once), token audiences (existing tokens are refused), the SMS prefix, and the FHIR identifiers.

## 6. Update after the as-built Azure report (31 October 2026)

- **D1 (canonical FHIR base URL):** the real domain is now known: `mirroredintelligence.com`, with the staff host
  `overwatch.mirroredintelligence.com`. Proposed canonical base: `https://overwatch.mirroredintelligence.com/`
  (identifiers do not have to resolve). Awaiting your confirmation.
- **D5 (Azure names):** the resource group and most resources are built as `*-diucs-pilot-*` and cannot be renamed, and
  nothing user-visible depends on them, so the proposal is to keep those names and rename only what can change in
  place: the two Entra app display names ("DIUCS Staff (pilot)" and "DIUCS Operator Console (pilot)", which can be edited
  in Entra without touching their app ids) and the resource tags. `infra/azure/` scripts keep `P="diucs"` for names
  that already exist; any new resource named after the product uses `overwatch`.
- The public hostnames already use the product name, so no hostname change is needed.
