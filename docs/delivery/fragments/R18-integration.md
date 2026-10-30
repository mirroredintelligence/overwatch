# R18 integration notes (bundle W2F, integration run)

## Known issues
| task | what | where | trigger |
|---|---|---|---|
| R18 | the route tests' token helper had an expiry (24 Oct) before the fixed clock (29 Oct), so every call got 401; fixed in the test by a token that outlives the clock | `backend/tests/integration/adapters/inbound/fhir_rest/test_routes_support.py` `_headers` | none; fixed at integration |
| R18 | a person can still name another session's id in `POST /support/codes` (no session claim in the BFF token); found while reading the route, not changed here | `routes_support.py` | the BFF issuing a session claim (already known as R18 known issue 1) |
