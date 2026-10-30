# TEN-073 integration run (fix round F5B)

`test_tenant_suspend.py` is green on the shared Neo4j.

- Product: `ResumeTenant` stored its marker as a string (`idempotency.put(marker, "<instant>")`); the idempotency store keeps dataclasses and enum members only, so every resume of a tenant with services raised `ValueError` after the work was done and the record was never made active again. The marker is now `ResumeDone(at)`. The unit test's idempotency fake encodes its values with `encode_result` as the real store does, so the unit tests fail on the old code (11 failed before the fix).
- Resume marker reads, the stale token after a resume and the reactivation order are covered by the integration tests that failed on this.

## Known issues

None added.
