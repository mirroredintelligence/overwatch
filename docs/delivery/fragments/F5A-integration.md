# F5A integration notes: wave 5 route bundles (R09, R10, R12, R13, R17) run green

Branch `task/fix-F5A`, off integration/build 998c907. Integration files run on the shared Neo4j
(TEN-033 to TEN-035), plain `uv run pytest`, no lock.

## Failures and their causes

| group | cause | kind | fix | files |
|---|---|---|---|---|
| 401 on every call after the test moved the clock (bookings, 13 tests) | the shared default test token expired 24 Oct 2026 13:12 UTC, one day after the route clock (23 Oct) and before the wave 5 clocks (29 Oct and later) | test support | default expiry moved to 31 Dec 2030; a test of expiry passes its own `expires_at` (test_auth, test_edge_binding already do) | `backend/src/diucs/adapters/testing/tokens.py` |
| 415 on bodyless operation POSTs (bookings, alerts, clinical `$take`, criteria `$approve`) | the middleware refuses a POST with no Content-Type before routing (DEC-086 item 1); R17 says an empty `Parameters` body is accepted | test | the 14 operation calls send `json={"resourceType": "Parameters"}` | `test_routes_bookings.py`, `test_routes_alerts.py`, `test_routes_clinical.py`, `test_routes_criteria.py` |
| `Internal error`, `UnitOfWorkAlreadyOpen`, every suspension (admin) | PRODUCT: the suspend route's `wording_for` called `ReadTenantConfig.wording()`, which opens a unit, inside SuspendService's own unit; the route now reads the wording first, as it already reads the policy | product | `routes_admin.suspend_service` | `backend/src/diucs/adapters/inbound/fhir_rest/routes_admin.py` |
| `KeyError 'parameter'` (registration, flag `later`) | test: a service not in the pilot needs a `reason` (U23); the test sent none, the add was 400 | test | `_entry` takes a reason; the test sends one; the add asserts 201 | `test_routes_registration.py` |
| `400 is required when an alert kind is on` (alerts, subscription save) | test: a kind on needs a deputy (U33); the body named none | test | the body references `prac-deputy`, seeded as an active shift lead in `alert_world` | `test_routes_alerts.py` |
| `404 not-found` on a safety concern (clinical) | test rig: the notice is sealed under the link-token secret (queue_message); the rig's secret store had only the phone-hash secret, so `FixedSecretStore` raised NotFound | test rig | the rig gives `LINK_TOKEN_SECRET` | `test_routes_clinical.py` |
| `assert 0 >= 1` (clinical count) | test rig: the count reads active clinical leads in the graph; the clinician was never seeded | test rig | the clinician is seeded as an active clinical lead | `test_routes_clinical.py` |

POST /fhir/Task dispatch (R09 create_booking vs R13 clinical): checked. `routes_clinical` is mounted
before `routes_bookings`, so it takes every POST /fhir/Task. A code of `clinical-advice` or
`safety-concern` stays in R13; any other body goes to `create_booking` after the same role check
(`CREATE_ROLES`), so the role is not lost. No change needed.

No tenancy or privacy defect was found in these routes. The cross-tenant tests in the files
(bookings, alerts, registration, clinical) pass against the second tenant.

## Pass counts (final run, after formatting)

| file | passed |
|---|---|
| fhir_rest/test_routes_bookings.py | 15 |
| fhir_rest/test_routes_alerts.py | 8 |
| fhir_rest/test_routes_clinical.py | 4 |
| fhir_rest/test_routes_criteria.py | 5 |
| fhir_rest/test_routes_admin.py | 7 |
| fhir_rest/test_routes_registration.py | 7 |
| fhir_rest/test_routes_identity.py + test_routes_identity_tenants.py | 15 |
| link_pages/test_booking_links.py | 6 |
| **target set** | **67 passed** |

Wider checks: `tests/integration/adapters/inbound` 727 passed (token default change checked
against every inbound route suite); `tests/unit tests/architecture` 12520 passed; `ruff check`,
`ruff format`, `mypy src` and `lint-imports` clean.

## Known issues (not fixed here)

- A missing secret answers 404 `not-found` (`NoSecrets` and the fixed store raise `NotFound`).
  A safety concern in a process with no secret is refused with a 404, not a 500 or 503. It fails
  closed (nothing is written), but the client sees "not found" for a configuration fault.
  Trigger: any deployment without the link-token secret. Owner: whoever owns the secret store.
- The shared test token no longer expires in route tests. A test that wants expiry must pass
  `expires_at`; the default is documented in `tokens.py`.
