# U14 integration notes

Ran `tests/integration/application/test_record_outcome.py`: 8 passed. The module now runs on a private contracted container (DEC-159): the two-tenant test saves a service in tenant B with the category Concept tenant A already holds, which the shared harness schema refuses (single-property keys until TEN-032).

No product change. No cross-tenant leak found.

## Known issues

| Task | What | Where | Trigger |
|---|---|---|---|
| U14 | Any two-tenant write that shares a Concept (the category codes) fails on the shared harness schema, so such tests need a private contracted container until the schema change. | `tests/integration/application/test_record_outcome.py` | TEN-032 (the shared schema drops the single-property keys) |
