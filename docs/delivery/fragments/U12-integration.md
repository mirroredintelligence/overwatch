# U12 integration notes

Ran `tests/integration/application/test_filter_options.py` (10 passed) and `tests/integration/graph_store/test_service_positions.py` (3 passed) on the shared harness. The generated two-tenant test (`tests/integration/graph_store/test_tenant_isolation.py`, 39 passed) covers Q-SVC-POSITIONS: no leak.

Fixes were test-side: the Location seed now uses the resource store's shape for `HealthcareService.location` (a Resource with a key, and a LOCATION relationship with its fhirPath); the filter rig calls `ensure_audit_heads`.

## Known issues

| Task | What | Where | Trigger |
|---|---|---|---|
| U12 | The positions tests seed the Location by raw Cypher that mirrors the resource store's reference shape. A change to how references are stored breaks the seed, not the product. | `tests/integration/graph_store/test_service_positions.py`, `tests/integration/application/test_filter_options.py` | a change to the reference shape in the mapper or the resource store |
