# iG integration fragment: W2G integration run

Bundle W2G (I14, U33, U31, U38, R08) plus graph_store/test_tenant_isolation.py. Run serially under
the Neo4j lock. Final run: 79 passed (the seven files), exit 0.

## Known issues
| Task | what | where | trigger |
|---|---|---|---|
| R08 | The phone is stored in plain text on a ProtectedContact node (`value`, +44 form). Encryption at rest is not built; an information-governance decision (DEC-070 item 2, DEC-072 item 4). The test checks that only that node holds it, which matches the recorded design. | backend/src/diucs/adapters/outbound/graph_store/contact_store.py | IG decision on encryption at rest and retention |
| R08 | The lead route tests build their own `test_container` (phone-hash secret) because the shared test container holds no secrets, so a mobile hash is NotFound and answers 404. | tests/integration/adapters/inbound/fhir_rest/test_routes_lead.py | any route that hashes a phone and uses the shared container |
| R08 | Tenant B's seeded rows use other codes (service category, measure, practitioner-role code, channel) because the shared harness schema keeps one Concept per code until TEN-032. | test_routes_lead.py, test_criteria_reviews.py | TEN-032 (composite Concept keys) |
| R08 | Two tenants cannot each hold an AuditHead on the shared schema (old single-property key on id). Only tenant A gets a head in these tests. | test_routes_lead.py, test_criteria_reviews.py | TEN-032 |
| I14 | RecordingPushSender.gone_next now counts (each call marks one more send gone); it was a one-shot flag. | backend/src/diucs/adapters/testing/recording_senders.py | none (fixed in this run) |
| U31 | Criteria review jobs get a new id prefix per call (itertools counter) to avoid outbox id reuse within one test. | tests/integration/application/test_criteria_reviews.py | none (fixed in this run) |
| U33 / I14 | test_push_message_sender.py does not use the Service Bus emulator, so it does not take take_emulator_lock(). | tests/integration/adapters/inbound/workers/test_push_message_sender.py | a change that makes it use the emulator |
| U38 | The service move tests run VerifyServiceMoveCode with the phone hasher (the helper had omitted it). | tests/integration/application/test_move_service.py | none (fixed in this run) |
