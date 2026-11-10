# Independent verification: Analytics overview (DEC-1368) and service detail page (DEC-1367)

Verifier session: `elated-tu-3f309b` (did not build either). Tree: `rename-overwatch` at `c1c433a1`. Nothing committed, merged, pushed or deployed; no Azure. Advisor v2 finder not verified (as instructed).

## Verdict

| Area | Result |
|---|---|
| 1. Against the owner's design | **FAIL.** Content is mostly present, but the layout, hierarchy and look are not the Mark design (list below). The owner's complaint stands for these two pages. |
| 2. Safety and tenancy | **PASS** with notes. Stale figures never spare capacity, Analytics User refused elsewhere, no person contact, no new Cypher; four of five back-end mutants and three of four front-end mutants were caught; one survived (N1). |
| 3. Tests and guards | **PASS** for everything that could run here. Neo4j integration, the Playwright suite and the full vitest run were **not run** (see below). |

## 1. Design comparison

Method: Playwright with the project's e2e test cookie sign-in (`e2e/support/session.ts`, role `analytics-user`, no real credentials) and fixture JSON fulfilled by route interception for `/api/bff/analytics/overview`, `.../detail` and `.../history`. Fixture: 32 services (18/7/4/2/1 by status), 6 districts, one service in two districts, one with none, a stale service. Spec was throwaway and is deleted. Screenshots: `docs/delivery/evidence/verify-analytics-detail-shots/` (`built-desktop-*`, `built-mobile-*`; 1280 and 390 px). The pages were reached at `/analytics`, `/analytics/services/svc-1`. The Advisor mount `/advisor/v2/services/[id]` renders the same component and was not separately rendered (its page test passes). Chart "Capacity unknown" hatching in my shots is my fixture (history 5 h old), not a defect.

### Overview (`/analytics`) against `mark-desktop-1-overview.png` and `mark-mobile-1-*`

| # | Design | Built | Status |
|---|---|---|---|
| O1 | Own "Command Centre" header (logo, Capacity / Find a Service switch, snapshot time, area chip) | Stock app shell (dark sidebar, "Home", role chip, Sign out). No Capacity / Find switch | Difference. Shell is the app's; the switch belongs to Advisor v2 |
| O2 | Title "Capacity Overview" | Title "Analytics", then small-caps section labels | Difference |
| O3 | Five status cards: dot, name, "N services", plus icon, order Accepting, Limited, Not accepting, Over capacity, Not updated | Five compact buttons, shape + word + number, no "services" word, order Accepting, Limited, **Over capacity**, Not accepting, Not updated | Shapes+words intended (DEC-1343). Order and card form differ |
| O4 | "N Patient places available" pill on each card and "Unknown" on Not updated | None | **Intended** (DEC-1343: no places total). A test asserts it |
| O5 | Needs attention is the second block, directly under the counts | Needs attention is the **last** block, below both group sections (about 1100 px down at 1280) | Difference, the most visible one |
| O6 | Needs attention: one panel, Under pressure and Underutilised side by side, each with an "N services" pill, rows are compact pills (name, % used pill, reason, +) | Two cards; rows are a default-blue underlined link, a large status badge, and a caption line; no count pill; no "+" affordance; Under pressure rows show the large badge, so three rows take about 300 px | Difference |
| O7 | Under pressure row: "Unknown" pill plus reason for a stale figure | "Unknown" is shown in the caption; never a percentage | Equivalent, stale rule kept |
| O8 | Location groups and Service groups side by side in one row (6 area rows with a thin bar, then 8 tiles) | Stacked full-width sections. Location cards are large (name, "5 services", bar, legend of every status with count/shape/word). Extra "Not placed" card and an explanatory sentence | Legend is intended (words+shapes). Layout differs. "Not placed" is a deliberate addition (DEC-1368) |
| O9 | Group headers carry "32 services" and "8 groups" pills | None | Difference |
| O10 | Service group names: UTC / MIU, Urgent Community Response, SDEC, Hospital at Home, Community Hospitals, Virtual Wards, Reablement, Crisis Response | Our eight category codes: Urgent community response, Same day emergency care, Inpatient beds, **Virtual beds**, **Care packages**, Urgent treatment, Mental health crisis, Other | Difference in names and set (Hospital at Home and Virtual Wards are one code; "Other" has no design counterpart). Not a Overwatch-wide decision made here |
| O11 | Footer "Demonstration data · Not live NHS information" and snapshot date | None | Not applicable to live data; note only |
| O12 | Mobile: counts in a 3+2 grid, then three tabs (Locations, Attention, Groups) and a paged list with Previous/Next | Mobile: one single column about 3,785 px tall; no tabs, no paging | **Difference**, large. No horizontal overflow at 390 px (measured 0) |
| O13 | Page fits one 1280x800 screen | Page is about 1,560 px tall at 1280 | Intended in part (DEC-1343: no no-scroll paged layout) |
| O14 | Plain navy/black text on tinted background; links not underlined | Default browser-blue underlined links (`#0000ee`) in Needs attention and the drill list, outside the app palette | Defect D3 |
| O15 | Text size 11 to 12 px | No rendered text under 14 px in `main` (measured) | Intended (DEC-1343) |

### Drill-down (`mark-desktop-2-area-list.png`)

| # | Design | Built | Status |
|---|---|---|---|
| D1 | Breadcrumb "Capacity Board › Geographical Area 1"; heading with area name; "6 services" pill; a back arrow | "Back" button + "Overview / Location: Geographical Area 1"; heading is still "Analytics" | Breadcrumb present; heading and pill differ |
| D2 | A strip of the five status counts for the area | None. Only a sentence "5 services. Listed by name, not ranked." | Difference |
| D3 | Two-column grid of service cards (name, group, status chip, "Updated 9 min ago", big number with unit) | Single column of full-width cards: link name, group and updated, large status badge, big number with unit | Content equal, layout differs. A stale figure reads "Current capacity unavailable" (verified in unit tests) |
| D4 | "1-6 of 6 services" footer, paging | None | Difference |

### Service detail (`mark-desktop-3-*`, `spoa-desktop-3-*`)

| # | Design | Built | Status |
|---|---|---|---|
| S1 | Name, one-line description, status chip right | Name, group, districts, large status badge | Description not held (DEC-1367 6) |
| S2 | "Capacity remaining n / normal" and the day chart **side by side** | Stacked: capacity card (full width), then the chart | Difference |
| S3 | "6 appointment slots in use" under the figure | Missing | Difference |
| S4 | Stale: not specified in the design; ours: "Current capacity unavailable", "Last reported: 4 appointment slots · 3 hrs 53 min ago", "Normal capacity: 12" | Verified for status not updated, overdue | Intended (DEC-1343) |
| S5 | Reporting strip (Last update, Frequency, Next due with "On schedule") | Four items (adds Schedule); "Overdue" in words | Matches in content |
| S6 | Service and contact: role, phone, Copy number, **email**, operating hours, catchment, indicative response | Phone, Copy number, opening hours. **Catchment is a separate panel on a second row, alone**. No role, email, indicative response | Email: intended and safe (DEC-1367 4). Others: stated gaps (DEC-1367 6). The orphan Catchment panel is a layout defect (D2) |
| S7 | Referral criteria panel: "Potentially accepts" chips, divider, "Example exclusions" chips, caveat at the bottom | Three panels (Potentially accepts, Exclusions, Catchment). **Chips stretch to the full row height** (about 100 px tall, text at the top), which looks broken | Defect D2 |
| S8 | Breadcrumb "Capacity Board › area › Service capacity" | "Back to the overview" link only | Difference |
| S9 | Mobile layout | Single column, no horizontal overflow at 390 px (measured 0). Day chart is small but legible | Pass (unseen by the builder; DEC-1367 8 left this unchecked) |

## 2. Safety and tenancy

| Rule | Evidence | Result |
|---|---|---|
| A stale, late or unknown figure is never spare capacity or Underutilised | `underutilised()` skips `figure_unusable` (`lead_views.py:205`); analytics read nulls `available` / `overBy` when not current (`analytics_views.py:_service`). Mutant M1 (always current) failed `test_a_stale_late_or_unknown_figure_carries_no_number`; mutant M5 (underutilised ignores stale) failed `test_the_lists_are_by_name_and_a_stale_figure_is_never_spare_capacity`. In the browser the stale detail shows "Current capacity unavailable" and the last figure small; the stale overview service shows in the Not updated count and under pressure as Unknown | PASS |
| Detail page: stale never the big number | Page shows the figure only if `!figureUnavailable && effectiveAvailable !== null`. Mutant F1 (drop overdue / stale tests) failed two `detailAsOption` tests | PASS |
| Analytics User refused every patient-level route and case | Back end: no route or use case names `Role.ANALYTICS_USER` except the two files and the detail readers (`test_aggregate_roles_not_granted.py`, passes). The wider unit run (`tests/unit/adapters/inbound` + `tests/unit/domain`, which contains the all-roles matrices) passed, 8437 tests. Front end proxy: `lib/auth/access.ts` maps `/analytics` to `analytics-user`, `/advisor/v2` to advisor and advisor-v2. Mutant F2 (analytics-user on `/advisor`) failed 12 `access.test.ts` tests. Mutant M2 (drop the role check) and M3 (add Role.LEAD to the detail readers) each failed a test | PASS |
| No person's phone or email as the contact | Read goes through `work_phone` (the service resource's own telecom), never a practitioner, reporter hash or contact store; no `email` field in the route; the browser page text had no `@` or `mailto:` (checked on both fixtures); the BFF and page keep only named fields. Mutant F3 (phone filter off) failed a test | PASS, with N3 |
| Every new Cypher names `tenantId: $tenant` | The diff from `f690a6a7` (before DEC-1362) to HEAD in `backend/src` adds **no** `MATCH`, `MERGE`, `CREATE` or `tenantId` line: the new reads use the existing tenant-scoped repositories (`positions.coverage_districts`, `services.get`, `services.work_phone`, `criteria.current_for_service`, `QueryBoard`). The statement guard is therefore vacuously satisfied | PASS |
| No cross-tenant read, another tenant's service reads as NotFound | `ReadServiceDetail` binds via `require_actor_in_bound_tenant`; the integration test for it (`tests/integration/application/test_service_detail.py`) **could not run** here. Mutant M4 (remove that bind line) was **not caught** by any unit test | See N1 |

## 3. Tests and guards (clean install: `pnpm install --frozen-lockfile`, `uv sync --frozen`; Windows, Python 3.14 via uv, `fcntl` stubbed from a scratch folder)

| Command | Result |
|---|---|
| Back end new files: `test_analytics_overview.py`, `test_routes_analytics.py`, `test_routes_service_detail.py`, `test_aggregate_roles_not_granted.py` | 24 passed |
| Back end `tests/unit/adapters/inbound` + `tests/unit/domain`, serial (`-n 0`) | 8437 passed, 0 failed |
| `ruff format --check src tests` | clean (1502 files) |
| `ruff check src tests` | 1 error: `tests/integration/application/test_retire_service.py:3` E501. **Pre-existing**: from DEC-1356 (`c07c7545`), present before the work (`f690a6a7`) and not touched by it |
| `mypy src` | clean (545 files). `mypy` over `tests/` **not run** |
| Front end: 53 files (every new or changed test file of the two features, `test/guards`, `lib/auth`, `lib/shell`, `proxy.test.ts`, board and attention tests) | 53 files, 2879 tests, all passed, including `no-literals` and the other guards |
| `tsc --noEmit` | clean |
| `eslint .` | 0 errors in the repo's files, 1103 warnings (**not compared** with a prior commit). The one error was in my own throwaway spec, now deleted |
| **Not run** | Neo4j integration tests (the Windows harness fails: `os.O_NOFOLLOW` missing in `tests/support/harness_mode.py:229`, so the builders could not run them either); the whole `pnpm vitest run` (only the 53 relevant files ran); the Playwright suite; `make test-parallel`; a baseline run on a commit before the work (the pre-existing label above rests on git history, not a baseline run); a real sign-in as an Analytics User; a real device |

Other claims checked: DEC-1368's evidence says the analytics links "404 until the service page lands". It has landed (`/analytics/services/svc-1` renders). The evidence notes a `no-literals` failure for `lib/map/landRings.ts` (DEC-1361): it did not reproduce here (guards all passed).

## Ranked defects

Classification: BLOCKING = fails the owner's goal or a safety rule; NOTE = known issue.

1. **BLOCKING (design fidelity), Overview layout and hierarchy**: O5 (Needs attention last, not second), O8 (groups stacked, not side by side), O6 (Needs attention rows are blue default links with large badges, no count pills), O3/O9 (count cards and header pills), O12 (no mobile tabs or paging; a 3,785 px column). Files: `frontend/components/analytics/AnalyticsOverview.tsx`, `frontend/components/analytics/Analytics.module.css`, `frontend/components/lead/PressureLists.tsx`, `frontend/components/analytics/StatusBar.tsx`. Why: this is the page the owner measures against the Mark design.
2. **BLOCKING (visible bug), Service detail**: potentially-accepts and exclusions chips stretch to the full row height; Catchment sits alone on a second row; capacity and chart stacked instead of side by side; "N in use" line missing (S2, S3, S6, S7). Files: `frontend/components/service/ServiceDetail.tsx`, `frontend/components/service/ServiceDetail.module.css`.
3. **BLOCKING (look), links**: Needs attention and drill rows use default browser-blue links outside the palette (O14). Files: `Analytics.module.css`, `components/lead/PressureLists.tsx`.
4. **BLOCKING (design), Drill-down**: no status strip for the set, heading still "Analytics", no card grid or paging (D1 to D4). File: `AnalyticsOverview.tsx` (`Drill`).
5. **NOTE**: Service group set and names differ from the design (O10); status order has Over capacity before Not accepting (O3). `frontend/lib/board/format.ts`, `frontend/lib/advisor/servicesBrowse.ts`.
6. **N1, NOTE (tenancy)**: mutant M4 survived. Removing `require_actor_in_bound_tenant(actor)` from `service_detail.py:63` passes all unit tests. Only the Neo4j integration test would catch it, and it was not run. The route's `require_role` still binds the tenant, so this is defence in depth. Classified NOTE because the route-level bind is intact. Add a unit test with an actor whose tenant is unbound.
7. **N2, NOTE**: mutant F4 survived: `figureText` in `frontend/lib/analytics/groups.ts:89` (return null when the figure is not current) is not tested against a hostile payload (`figureCurrent:false` with a number). The back end already nulls the figure, so the guard is redundant defence.
8. **N3, NOTE (privacy)**: the service phone is free text on the service profile and the page's check (`PHONE_PATTERN`, `lib/advisor/options.ts:106`) accepts any number, including a personal mobile (DEC-1367 7a says the platform does not check). It is the service's own telecom, never a reporter's, so I classed it NOTE. If the owner wants a hard guarantee, reject `07` numbers in the back end.
9. **NOTE (not run)**: Neo4j integration tests, Playwright suite, full vitest, mypy over `tests/`, no baseline run, and no real device (the Windows harness limit above).

## Left in the worktree
`docs/delivery/evidence/verify-analytics-detail.md` (this file) and the folder `docs/delivery/evidence/verify-analytics-detail-shots/` (untracked). Mutants were restored with `git checkout` and `git status` was clean apart from these.
