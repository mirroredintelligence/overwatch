# O04 integration notes (bundle W2F, integration run)

## Decision
The collector keeps no `name` or `value` key (supersedes O04 fragment decision 3 for `name` and `value`)

1. `name` and `value` are removed from `infra/otel-allowlist.txt` `[browser]` and from every `keep_keys` statement in `infra/otel-collector.yaml`. Both are free-text words in `DENIED_FRAGMENTS`, so the back end refuses them too. The browser never sends them (`ALLOWED_ATTRIBUTES` in `frontend/lib/telemetry/events.ts` does not name them, and the O05 schema has no `ui.web_vital`).
2. The collector cannot keep them for `ui.web_vital` only: the BFF forwards events with the event name in the body, not as an attribute, so no OTTL condition can tie a `name` or `value` to that event. A future `ui.web_vital` must use keys that pass the rule, or the owner must re-admit the keys with a reviewed rule.
3. Unit test `test_collector_allowlist.py` pins the removal (red before the change). Integration test `test_free_text_under_name_and_value_never_leaves_the_collector` pins it end to end.

## Hazards
| id | hazard | source | control | tasks | verified by | status |
|---|---|---|---|---|---|---|
| H-152 | a free-text word under `name` or `value` reaches the backend store | any exporter | `name` and `value` are removed by the collector and refused by the back end | O04 | unit test (19 cases, run); `test_collector_allowlist.py` (5 cases, run, pass) | verified in integration |

## Known issues
| task | what | where | trigger |
|---|---|---|---|
| O04 | the BFF posts browser events as JSON `{events:[...]}` to `OTEL_HTTP_ENDPOINT`, but the collector's receivers are OTLP only (`/v1/traces`, `/v1/logs`); tested on the pinned image, a JSON `{events:[...]}` POST to `/v1/traces` returns 200 with `partialSuccess` and exports nothing, so browser `ui.*` events are silently dropped | `frontend/app/api/bff/telemetry/route.ts` `forward`, `infra/otel-collector.yaml` receivers | the first deployment that sets `OTEL_HTTP_ENDPOINT`: either the BFF sends OTLP, or the collector gets a JSON receiver |
| O04 | the test profile runs the collector as root (`user: "0:0"`), because the image user 10001 cannot write the root-created `./otel-out` mount | `infra/docker-compose.yml` `otel-collector` | never in production (the test profile is not started there) |
| O04 | a `ui.web_vital` event built later cannot use `name` or `value` until its keys are renamed or re-admitted by a reviewed rule | `infra/otel-allowlist.txt` | building the web-vitals event (O05 has none yet) |

## Contracts
- none new (the lists changed, the files did not)

## Tenant pending
- none

## Assumed
- none new
