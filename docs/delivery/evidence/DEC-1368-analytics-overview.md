# DEC-1368 Analytics User overview at /analytics: evidence

Branch `claude/friendly-gates-0e0f54` (not merged, not pushed), built on `claude/roles-analytics-advisor-v2-a6a327` (DEC-1362), which it contains. The red commit is `a19c8ad0` (tests only); the green commits follow it.

## What was built
- Back end: `GET /analytics/overview` (`routes_analytics.py`, `analytics_views.py`): the board (`QueryBoard`) plus the tenant's coverage districts (`positions.coverage_districts`), the lead's `under_pressure` / `underutilised` re-sorted by name. Analytics User only.
- BFF: `app/api/bff/analytics/overview/route.ts` (role `analytics-user`, shape-checked, known fields only).
- Front end: `/analytics` page: five status counts, Location groups (a card per district plus "Not placed"), Service groups (eight), Needs attention (the lead's two lists, each name a link to `/analytics/services/<id>`), drill-down with breadcrumb and Back. `PressureLists` gained an optional link; `lib/lead/parse.ts` exports its two list readers.
- Shape: no "places available" total; status as count, word and shape (the bar is aria-hidden).

## Tests (written first, commit `a19c8ad0`)
- `tests/unit/application/use_cases/test_analytics_overview.py`: role check over every `Role`, the five counts and no total, districts sorted and empty for an unplaced service, no number for a stale/late/unknown figure, lists by name, a stale figure never spare capacity.
- `tests/unit/adapters/inbound/fhir_rest/test_routes_analytics.py`: every role but the Analytics User refused (404; the platform operator 401); answer keys exact; body scanned for patient-level words.
- `tests/unit/domain/test_aggregate_roles_not_granted.py`: exactly two new files may name the role; neither names Advisor v2.
- `lib/analytics/{groups,parse}.test.ts`, `app/api/bff/analytics/overview/route.test.ts`, `components/analytics/AnalyticsOverview.test.tsx` (counts, Not placed, shapes and words, eight groups, links, drill and Back, unavailable figure, failure, axe on both views), `PressureLists.test.tsx` (the link).

## Results (Windows, local)
- Back end: `uv run pytest` of the three new files plus `tests/unit/domain` and `tests/unit/adapters/inbound`: 8428 passed (fcntl stubbed on `PYTHONPATH`). `ruff check` and `ruff format` clean for `src` and `tests/unit`; `mypy` clean on the two new source files (the existing `tests/support/w7b_rig.py` has 13 old mypy errors under `tests/`, untouched).
- Front end: the five new/changed test files, 34 tests, pass; `tsc --noEmit` clean; `eslint` clean on the changed paths. Full `vitest`: see the final report line below.

## Not verified
- Integration tests against Neo4j (not run here); the real graph's coverage read is the existing `Q-SVC-COVERAGE`, unchanged.
- A real sign-in as an Analytics User, and the page in a browser (the proxy guard is DEC-1362's and tested there). No independent verifier has re-checked this yet.
- `/analytics/services/<id>` is another session's page; the links 404 until it lands.

## Addendum: guard run
`pnpm vitest run test/guards lib/auth lib/shell proxy.test.ts`: 2310 passed, 2 failed. One was this change (`no-literals`, rule `fetch-call`: the page's fetch address must be written out in the call); fixed in the next commit. The other, `no-literals` for `lib/map/landRings.ts` line 2 (place-name, DEC-1361), is not from this change. The second failing file was not re-read after the fix; the earlier session noted `bff-routes.test.ts` times out under full-suite load. The whole-suite `vitest run` never returned output and was abandoned.

## Round 2: the independent verifier's blocking design defects (branch merged with `rename-overwatch` first)
Report: `verify-analytics-detail.md` in the verifier's worktree. Fixed in `frontend/components/analytics/*` (new `AttentionPanel`, `GroupBlocks`, `Drill`, `Pager`; `lib/analytics/useNarrow.ts`; `Analytics.module.css` rewritten). `components/lead/PressureLists.tsx` is untouched in this round (the overview no longer uses it); `components/service/*` untouched.

| Verifier item | Fix |
|---|---|
| O5 Needs attention last | Directly under the counts (DOM and screen order: counts, attention, groups); a test checks the order |
| O6 two cards, blue links, big badges | One panel, Under pressure beside Underutilised, each with an "N services" pill and compact rows (shape, name link, "% used" or "Unknown" pill, reason); no status badge; "Show all N" beyond five |
| O8 groups stacked | Location groups (2fr) beside Service groups (3fr) at wide widths; the status legend (count, word, shape) and "Not placed" kept |
| O9 header pills | "32 services" on Location groups, "8 groups" on Service groups, "N services" on both attention columns |
| O3 count cards | Five cards: shape and word, number and "services"; order as the advisor board uses (Accepting, Limited, Over capacity, Not accepting, Not updated) |
| O12 mobile column | At 640 px and under: tabs Locations, Attention, Groups; a list of locations or groups pages five at a time with "1–5 of 7 locations" and Previous/Next. Full page 390 px: about 1,650 px tall (the verifier measured 3,785) |
| O14 default links | Palette ink, no underline until hover, 3 px focus ring, in Needs attention and the drill rows |
| D1 to D4 drill-down | Heading is the area, group or status name with an "N services" pill; breadcrumb with Back; a strip of the five counts of the set; two-column card grid (one column on a phone); "1–6 of 8 services" with Previous/Next, six to a page |
| N2 | `groups.test.ts`: a figure with `figureCurrent:false` and a number reads null (`available` and `overBy`) |
| h1 | "Capacity overview" (the page test follows) |
DEC-1343 kept: no places total (test), shapes plus words, no text under 14 px (measured in the browser: none, at 1280 and 390), stale never spare capacity (back end unchanged).

Tests: `AnalyticsOverview.test.tsx` rewritten for the new behaviour (counts and order, block order, header pills, attention, groups, phone tabs and paging, drill heading, strip, grid links, paging, empty set, failure, axe on the wide, phone and drill views), `groups.test.ts`, `page.test.tsx`. The tests were written before the components in this round but committed with them (one commit, `b69372c1`), so there is no separate red commit for round 2; the earlier failures I saw were two faulty test assertions, fixed before the commit.

Screenshots (Playwright, sample data, the BFF read answered by the test; the throwaway spec is deleted): `docs/delivery/evidence/DEC-1368-shots/`. Pairs against the design shots in `side-session-notes/local_9d2a7d81-.../design-shots/`:
- `built-desktop-1-overview-full.png` vs `mark-desktop-1-overview.png`
- `built-desktop-2-drill.png` vs `mark-desktop-2-area-list.png`
- `built-mobile-1-overview-locations.png` vs `mark-mobile-1-overview.png`
- `built-mobile-1-tab-attention.png` vs `mark-mobile-1-tab-attention.png`
- `built-mobile-1-tab-groups.png` vs `mark-mobile-1-tab-groups.png`
- `built-mobile-2-drill.png` (no design counterpart)
Known differences left: the app's own shell (sidebar, role chip) instead of the design's "Command Centre" header and Capacity / Find a Service switch; no "patient places available" pills (DEC-1343); our eight category names; the design's single-screen fit is not a goal (DEC-1343). In the full-page captures the fixed bottom bar and the sticky header show mid-page: that is the capture, not the layout.

Results this round: `vitest` on `components/analytics lib/analytics "app/(analytics)" app/api/bff/analytics test/guards`: 1307 passed; `tsc --noEmit` and `eslint` on the changed paths clean (after `pnpm install` for the merged map dependencies).
