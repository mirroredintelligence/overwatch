# DEC-1366 Advisor v2 (Capacity, Find a Service): evidence

Branch `claude/sharp-kepler-9a26a1`, based on the roles branch (DEC-1362, fast-forwarded in). Not merged, not pushed, not deployed.

## Commits
- Red, back end: `c405c956` (tests for the matcher, the overview, the roles; module absent, so the import failed).
- Red, front-end readers: `498f8f1e`.
- Green back end, readers and BFF routes: `9603b938`. The two BFF route test files were written first and committed in this commit, not before it.
- Red, components: `7aa92950`, then green with the components and pages (next commit).

## Tests
- `backend/tests/unit/application/use_cases/test_find_services.py` (14): the v1 criteria decide; suspended and no criteria never found; status does not exclude; late, old, unknown or never-reported figures unavailable with the last figure kept; order is travel then name, never status; roles; the overview counts, Needs attention, no stale figure as spare.
- Front end: `lib/advisor/v2/*.test.ts` (22), BFF routes (8: roles, CSRF, 400 without echo, postcode only in the body, 502 on a bad answer), `components/advisor-v2` (19, including axe, "Current capacity unavailable", no postcode in the address or storage), the two pages (4).

## Results (Windows, local)
- Back end: `pytest tests/unit/adapters/inbound tests/unit/domain tests/unit/application`: 12516 passed. `ruff check` and `ruff format` clean, `mypy src` clean. Neo4j integration tests NOT run; there is no integration test of `FindServices` against Neo4j (the use case is covered through its pure parts and review only).
- Front end: the new files pass; tsc and eslint clean on them. Full vitest: see the note at the foot.

## Not verified
Browser look at 1280 and 375 px; a real sign-in as `advisor-v2`; the audit entry against a real store; an independent verifier has not re-checked this.
