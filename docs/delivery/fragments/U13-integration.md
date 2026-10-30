# U13 integration notes

Ran `tests/integration/application/test_advisor_phoned_and_decline.py`: 8 passed. The tenant-B tests read through a second tenant's unit of work and write nothing in tenant B, so they run on the shared harness.

Fix was test-side: the id generators are scoped with the tenant id (`ACTOR_TENANT`), not the literal "a" or "d", which the tenant scope refuses (ScopeInvalid).

No product change. No cross-tenant leak found.

## Known issues

No new known issues beyond the fragment `U13.md`.
