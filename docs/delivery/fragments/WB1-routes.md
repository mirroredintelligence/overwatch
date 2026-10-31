# WB1: routes and process facts for the bundles that follow

WB1 adds no route and changes no response shape. It adds the process that serves the routes that already existed, and the edge in front of them. What a front-end or deployment bundle needs to know:

## What is served, and from where

`python -m diucs.bootstrap.api_main` (or `uvicorn diucs.bootstrap.api_main:app_factory --factory`) serves one ASGI app, `create_app`, with every router of `fhir_rest/app.py` at the root or under `/fhir` exactly as `bootstrap/app.py`'s router prefixes say (`/health`, `/fhir/...`, `/public/tenant-profile`, `/auth/token`, `/auth/device-token`, `/auth/operator-token`, `/networks`, `/network/{id}/...`, `/network-admin/...`, `/platform/...`, `/tenant/...`, `/webhooks/sms/twilio` and `/webhooks/sms/twilio/status`, `/l/{token}`, `/test/synthetic/prompt` (404 until a synthetic link issuer is built)). The ASGI app listens on `DIUCS_API_HOST` and `DIUCS_API_PORT` (default `0.0.0.0:8000`).

## What a caller must send, behind Cloudflare

- The tenant is the HOST the request is addressed to (`Host` header only; DEC-134 item 3). Behind Cloudflare the BFF and the browser address the tenant's own hostname; Cloudflare must pass the original host to the origin in `X-Forwarded-Host` (a request-header transform rule: `http.host`), because Cloudflare may rewrite `Host` to the origin's name. The edge reads `X-Forwarded-Host` only from a request that comes from Cloudflare (its published ranges, a range in `DIUCS_EDGE_TRUSTED_PEERS`, or a request carrying the origin secret in `X-Edge-Auth`), and replaces `Host` with it. The BFF's own server-to-server calls to the API (the token exchange, every route) are addressed the same way: the BFF sends the tenant's host as `Host` (or `X-Forwarded-Host` through Cloudflare) and the visitor's address in `CF-Connecting-IP` if the BFF is itself behind Cloudflare; a BFF that calls the API directly (not through Cloudflare) is not trusted for either header, so the rate limits count the BFF's address.
- Twilio's webhooks must reach `DIUCS_BASE_URL + /webhooks/sms/twilio` unchanged: the signature is checked against `DIUCS_BASE_URL` and the path, so a WAF rule must not rewrite either.

## Settings and secrets the deployment must set

`DIUCS_PROFILE=production`, `DIUCS_BASE_URL` (the public https URL), `DIUCS_NEO4J_*`, `DIUCS_REDIS_URL`, `DIUCS_SERVICEBUS_CONNECTION`, `DIUCS_OPERATOR_DIRECTORY_ID` (the operator's Entra directory GUID, or the operator sign-in stays unconfigured), `DIUCS_EDGE` (`cloudflare`, the default, or `none`), optionally `DIUCS_EDGE_CLOUDFLARE_RANGES_FILE`, `DIUCS_EDGE_TRUSTED_PEERS`, and the secrets named in `api_main.REQUIRED_SECRETS` plus the optional `edge-origin`. The process exits at start-up with a message when a required secret is missing or under 32 bytes, when there is no secret store (until the Key Vault adapter exists) and when `DIUCS_BASE_URL` is not a public https URL in production.

## Worker side

`workers_main.serve` now also reads `capacity.events/alert-evaluator` (raises the alerts of a status change) and `alerts.events/notifier` (pushes an escalation to the tenant's active shift leads), and the dispatch table has a `prompt-due` handler. The topology file no longer declares eleven subscriptions that nothing read (DEC-1111): a bundle that needs a notifier on bookings, registrations or criteria adds the subscription and its reader together.
