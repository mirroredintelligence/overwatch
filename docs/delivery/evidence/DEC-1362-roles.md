# DEC-1362 Analytics User and Advisor v2 roles: evidence

Branch `claude/roles-analytics-advisor-v2-a6a327` (not merged, not pushed). The red commit is `f690a6a7` (tests only); the green commits follow it.

## What was built
- Back end: `Role.ANALYTICS_USER`, `Role.ADVISOR_V2`; both in `ENTRA_MAPPABLE_ROLES` and `HAND_MAPPABLE_ROLES`; both in `STAFF_ROLE_PRIORITY` (token issue through `POST /auth/token`: the staff exchange issues any role in that list); the `role` code system (15 concepts).
- Front end: `ROLES`, `STAFF_ROLES`, the telemetry role list; the proxy guard (`/analytics`; `/advisor/v2` for `advisor` and `advisor-v2`), role homes, header labels and navigation, role chip words, the tenant administrator's mapping list and group list, the operator's group choices; guarded placeholder pages `/analytics` and `/advisor/v2`.

## Tests (written first)
- `backend/tests/unit/domain/test_aggregate_roles_not_granted.py`: no source file other than the three that define and map the roles names either of them. Reporting a problem (`PROBLEM_ROLES`) is open to them only because it is "every role but wall and link"; it reads nothing.
- `test_token_exchange_rules.py`, `test_tenant_records.py`, `test_codes.py`: priority, mapping, the role list. The existing all-roles route matrices (which loop over `Role`) now run against both and expect the 404 for each; hard-coded counts updated (13 to 15).
- `frontend/lib/auth/access.test.ts` (the guard, including encoded and dot-segment paths), `lib/shell/nav.test.ts`, `lib/shell/roleWords.test.ts`, `lib/tenantAdmin/newRoles.test.ts`, `proxy.test.ts`, page tests for both landing pages.

## Results (run on Windows, local)
- Back end `tests/unit`: 16566 passed; 44 failed, all in `tests/unit/support` (Docker and `/proc` helpers that need Linux), none touching roles. `fcntl` is missing on Windows, so a stub module was put on `PYTHONPATH` for the run. The Neo4j integration suites were NOT run (their role matrices were updated by reading, and the unit matrices cover the same roles). `ruff check`: one error in `tests/integration/application/test_retire_service.py`, a file this change does not touch. `ruff format --check` clean, `mypy src` clean.
- Front end: `tsc --noEmit` clean, `eslint` clean. Full `vitest`: 3 failures in the first full run: `test/guards/no-literals.test.ts` (`lib/map/landRings.ts` line 2, from DEC-1361, not this change), `test/guards/bff-routes.test.ts` (20 s timeout under full-suite load; passes alone, 1142 tests), and two tests that pinned the role list (`UsersAndRoles`, `CreateTenantForm`), now updated and passing; `session.test.ts` was also updated.

## Not verified
Integration tests against Neo4j; a real sign-in with a mapped group; an independent verifier has not yet re-checked this.
