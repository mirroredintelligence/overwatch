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
RESULTS_PLACEHOLDER

## How the back end was run here
Windows has no `fcntl` or `O_NOFOLLOW`, so a stub `fcntl` and a `sitecustomize` setting `O_NOFOLLOW` were put on `PYTHONPATH`, and the Neo4j tests attached to the running shared container through `OVERWATCH_TEST_NEO4J_URI`, `_USER` and `_PASSWORD`. `make` is not installed (L1), so the commands under the Makefile targets were run directly.

## Not verified
A browser look at the page and at phone width; the Playwright suite; the full Neo4j integration suites (only the new scenario file ran); an independent verifier has not re-checked this.
