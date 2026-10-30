## Known issues

| Task | what | where | trigger |
|---|---|---|---|
| TEN-018 | A POST with no body and no JSON content type (for example `/support/tickets/{id}/approve`) is answered 415 by the FHIR media-type middleware, so a client must send `{}` with a JSON type; `/links/` and `/webhooks/` are exempt, `/support/` is not. | `fhir_rest/errors.py` `BodyTypeMiddleware` | the BFF calling a bodiless support or lead action without a content type |
| TEN-018 | The lead and support route tests write only as the run tenant: a second tenant's audit head needs the contracted container (DEC-159), so no case there writes as tenant B. | `tests/integration/adapters/inbound/fhir_rest/test_routes_lead.py` | TEN-032 |
