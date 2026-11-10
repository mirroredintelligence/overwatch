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
