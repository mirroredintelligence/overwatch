# DEC-1367 The service detail page: evidence

Branch `claude/angry-einstein-bae342` (not merged, not pushed). It sits on top of the roles branch (`claude/roles-analytics-advisor-v2-a6a327`, DEC-1362) because the page needs those roles and the guard: merge the roles branch first. The red commit is `8d599806` (tests only); the green commits follow it.

## What was built
- Back end: `ReadServiceDetail` (`application/use_cases/service_detail.py`) and `GET /clinical/services/{id}/detail`; the day chart's `ReadCapacityHistory` and its route admit Advisor v2 and the Analytics User.
- Front end: the read (`app/api/bff/advisor/services/[id]/detail`), the history route's roles, `lib/advisor/serviceDetail.ts`, `components/service/ServiceDetail.tsx`, the two pages.

## Tests (written first, red at `8d599806`)
- `backend/tests/unit/adapters/inbound/fhir_rest/test_routes_service_detail.py`: each reader gets exactly the listed keys; the reporting facts are the board's; no number and no criteria are null; no `@` or mobile in the answer; every other role is 404; unknown and inactive services are 404; the day chart is open to both new roles.
- `backend/tests/integration/application/test_service_detail.py` (real Neo4j): the three readers get the service, its number, criteria and districts; no number is None; another tenant's service and an unknown one are the same NotFound; lead, clinical, reporter and exec are refused.
- Front end: `lib/advisor/serviceDetail.test.ts`, `components/service/ServiceDetail.test.tsx` (order, current and unavailable capacity, chart, strip, copy number, no number, criteria, catchment, no personal data, failure, axe), the two page tests, the detail and history route tests, and the guard paths in `lib/auth/access.test.ts`.

## Results (run on Windows, local)
- Back end: `tests/unit/domain`, `tests/unit/application`, `tests/architecture`: 10811 passed, 2 failed. The 2 are `tests/architecture/test_single_execution_point.py` (`inbound_reply_repository.py` has 2 built-Cypher statements, the ratchet says 0): a file of DEC-1359 on `main`, not touched here. The whole `tests/unit/adapters/inbound/fhir_rest` folder passed (1334) with the service detail tests in it. The other `tests/unit` folders were not run in full (an xdist run aborted on a collection mismatch). New Neo4j scenario file `tests/integration/application/test_service_detail.py`: 9 passed against the shared container. `ruff check` (src and unit tests and the new file) clean, `ruff format --check` clean, `mypy src` clean, `lint-imports` 5 kept.
- Front end: `tsc --noEmit` and `eslint` clean on the touched folders. New and touched files: 552 tests passed. Full `vitest` (11221 tests, run twice): the first run showed 7 failures and the second 11, all but two timeouts under load that pass when the files are re-run alone (`AddServiceForm`, `ServiceForm`, `CreateTenantForm`, `eslint-rules`, `PinScreen`). Two do not go away: `test/guards/no-literals.test.ts` (place names in `lib/map/landRings.ts`, from DEC-1361, not this change) and one third file of the 3 that still failed in the re-run, not identified. `UsersAndRoles.test.tsx` (12) and `CreateTenantForm.test.tsx` (16) pass with `7e555fec` in.

## Round 2: the verifier's blocking defects (S2, S3, S6, S7, S8, N1, N3)
Merged `rename-overwatch` first (it fast-forwarded: the tokens of DEC-1365 and the merged pages were in). Red commit first (tests for the layout, "in use", the breadcrumb, a mobile number refused, the use case's own tenant check), then the back end, then the page.
- S2 capacity beside the chart (stacked under 720 px), S3 "n <unit> in use", S6/S7 one criteria panel with a divider, chips at natural height, the caveat last, Catchment inside the contact panel's list, S8 breadcrumb and back control. Checked in a browser at 1280 and 390 px, both mounts: `docs/delivery/evidence/DEC-1367-shots/built-{analytics,advisor-v2}-{desktop,mobile}.png`; no horizontal overflow (measured 0).
- N1: `tests/unit/application/test_service_detail_tenant.py`; with the `require_actor_in_bound_tenant` line replaced by `pass` all three cases fail (checked), restored.
- N3: a UK mobile shape is dropped by the use case and by the page (tests for four spellings, and three landline or switchboard numbers still shown). The decision (7a) says what this cannot catch.
- Results after the change: back end `test_service_detail_tenant.py`, `test_routes_service_detail.py`, `test_aggregate_roles_not_granted.py` 28 passed; `ruff check`, `ruff format`, `mypy src` clean. Front end: `tsc --noEmit` and `eslint` clean on the touched folders; 31 files, 2058 tests passed (the service page, its lib, the pages, the BFF routes, access guard, all `test/guards`).
- Design pairs: `mark-desktop-3-service-detail.png` and `spoa-desktop-3-service-detail.png` (in the side-session notes `design-shots` folder) against `built-analytics-desktop.png`, `built-advisor-v2-desktop.png`; the design has no mobile service-detail shot in that folder, so `built-*-mobile.png` stand alone. Remaining differences: no contact role, email or indicative response (not held, DEC-1367 item 6); a plain status badge, not the design's pastel chip; the chart is the existing `DayChart`.

## How the back end was run here
Windows has no `fcntl` or `O_NOFOLLOW`, so a stub `fcntl` and a `sitecustomize` setting `O_NOFOLLOW` were put on `PYTHONPATH`, and the Neo4j tests attached to the running shared container through `OVERWATCH_TEST_NEO4J_URI`, `_USER` and `_PASSWORD`. `make` is not installed (L1), so the commands under the Makefile targets were run directly.

## Not verified
A real device; the Playwright suite (only a throwaway screenshot spec ran, since deleted); the full Neo4j integration suites (only the new scenario file ran); an independent verifier has not re-checked this.
