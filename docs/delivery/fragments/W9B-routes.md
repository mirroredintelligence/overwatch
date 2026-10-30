# W9B: the new back-end routes and their shapes

Every route is JSON, outside `/fhir`, at the app root, `Cache-Control: no-store` (the screens routes too). Every refusal of a network route is the one OperationOutcome 404 of the API (`The requested resource was not found.`): a network outside the token's `networks` claim, a tenant that is not an active member, a member that left, an unknown network, a role the route does not allow and a wall that is not set to a network cannot be told apart. A request that names a tenant or a network that the server did not offer is never an authority. The BFF uses `root: true` for all of these paths. Times are ISO 8601. Bodies name no tenant, grant, source tenant or member's own service id.

## Wall screens: which board (TEN-067)

Roles in brackets. Staff routes use the lead's or tenant administrator's token; the wall routes use the wall token (`sub` = the device id).

### `GET /screens` (lead, tenant-admin)
200
```
{ "screens": [ { "deviceId": "screen-1", "name": "Ward 4 corridor", "location": "Level 2" | null,
                 "status": "active" | "paired-unclaimed" | "revoked",
                 "boardScope": "tenant" | "network",
                 "networkId": "net-..." | null, "networkName": "..." | null,
                 "networkAvailable": true | false,   // false: set to a network the tenant is no longer an active member of
                 "scopeVersion": 1 } ],
  "networks": [ { "id": "net-...", "name": "..." } ] }     // the networks the tenant may choose
```
Screens are ordered by name then id. `networks` is the registry's active memberships; the page offers only these.

### `PUT /screens/{deviceId}/board-scope` (lead, tenant-admin)
Headers: `If-Match: W/"<scopeVersion>"` (required: none 428, stale 412), `Idempotency-Key` (required: none 400), `Content-Type: application/json`.
Body: `{"boardScope": "tenant"}` or `{"boardScope": "network", "networkId": "net-..."}`. Unknown fields are 400 (`extra="forbid"`), a tenant is never a field; `network` needs `networkId`, `tenant` must not have one.
200 `{deviceId, name, location, status, boardScope, networkId, networkName, networkAvailable, scopeVersion}` as in the list, with `ETag: W/"<scopeVersion>"`. The same key and body again returns the first answer (`Idempotent-Replay: true`). The same board again changes nothing and keeps the version.
404: an unknown or revoked screen, another tenant's screen, a network the tenant is not an active member of, one it left, an unknown network, a role other than lead or tenant-admin. 409: the key used for another command.

### `GET /screens/me/board-scope` (wall)
200 `{"boardScope": "tenant" | "network", "fallback": false, "scopeVersion": 2, "networkName": "..."}`; `networkName` only when the screen shows a network now. When the screen is set to a network it can no longer read: `{"boardScope": "tenant", "fallback": true, "fallbackReason": "network-unavailable", "scopeVersion": 2}` (show the tenant board and the banner). The page re-reads this on every refresh and clears any cached network copy when `scopeVersion` changes or `fallback` is true. 404: a revoked, unclaimed or unknown screen, or a token that is not a wall's.

### `GET /screens/me/network-board` (wall)
200 the network board, exactly the body of `GET /network/{id}/board` (below). 404 for a screen on its own board, a screen whose tenant left, a revoked screen and every other refusal. A wall has no network id to give and `/network/{id}/...` stays closed to it.

### `GET /screens/me/network-events` (wall)
`text/event-stream` as `GET /network/{id}/events`: `event: network-board` with `data: {"changedAt": "..."}`, keep-alive comments every 15 s, and one `event: scope-ended` then close when the screen's record or its tenant's membership no longer allows it (checked on connect and every 30 s). On `scope-ended` the screen reads `/screens/me/board-scope` again.

### Changed: `POST /screens` (lead)
`boardScope` accepts `"tenant"` only (default). `"network"` is a 400 and stores nothing; the network is chosen after pairing with the PUT above.

## The lead's network reads (W17, W43, TEN-082)

Roles for the first two: advisor, clinical, lead, owner, exec (the roles that see a network). For the week: exec and lead. All three check the claim, then the registry.

### `GET /network/{id}/system-now`
200
```
{ "generated_at": "...", "services": 6, "organisations": 3,
  "by_status": { "accepting": 2, "limited": 1, "not-accepting": 0, "over-capacity": 0,
                 "not-updated": 2, "out-of-hours": 0, "unavailable": 1 },   // every key always present
  "pressure": "normal" | "watch" | "high", "all_limited_or_worse": false,
  "alert": { "raised": false, "level": "normal", "limited_or_worse": 1, "watch_from": 3, "high_from": 5 },
  "system_name": "...", "pathway_name": "...", "time_zone": "Europe/London" }
```
`alert.raised` is true while the pressure is high; it is a state, never a push (DEC-982).

### `GET /network/{id}/phones`
200
```
{ "phones": [ { "row_ref": "lst-...", "organisation_name": "...", "service_name": "...", "category": "...",
                "presentation": "shown" | "unavailable",
                "status": "accepting" | ... | null, "stale_warning": false, "reported_at": "..." | null,
                "contact_label": "..." | null, "contact_phone": "..." | null } ],
  "organisations": 3, "system_name": "...", "pathway_name": "...", "time_zone": "Europe/London" }
```
Ordered by organisation, service, reference. `contact_*` is null when the organisation shared no service line (today every row: no source yet): show "Phone to confirm". No reporter's number, no move controls.

### `GET /network/{id}/week?weekStart=YYYY-MM-DD`
`weekStart` required, a Monday (400 otherwise). 200
```
{ "week_start": "2026-10-26", "withheld": false,
  "hours_sampled":  { "label": "hours sampled", "value": 13, "hidden": false },
  "on_time_pct":    { "label": "capacity updates on time", "value": 75, "hidden": false },
  "status_share":   { "accepting": {label, value, hidden}, "limited": {...}, "not-accepting": {...},
                      "over-capacity": {...}, "not-updated": {...}, "out-of-hours": {...} },
  "pressure_hours": { "normal": {label, value, hidden}, "watch": {...}, "high": {...} },
  "pressure_over_time": [ { "hour": "2026-10-26T00:00:00+00:00", "pressure": "normal" } ],
  "system_name": "...", "pathway_name": "...", "time_zone": "Europe/London" }
```
A hidden measure has `value: null, hidden: true` (fewer than 10): the page says "Not shown: fewer than 10." When `withheld` is true (fewer than 3 organisations) every measure is hidden and the series is empty. No per-member breakdown exists. `value` of a share is a whole per cent.

## Existing network routes (TEN-059), for reference
`GET /networks` `{ "networks": [ {id, name, system_name, pathway_name, time_zone} ] }`. `GET /network/{id}/board` `{ "entries": [ {row_ref, organisation_name, service_name, category, presentation, status, unit_label, effective_available, over_by, used, established, reported_at, stale_warning, was_due_at, source} ], "pressure", "all_limited_or_worse", "generated_at", "system_name", "pathway_name", "time_zone" }`. `GET /network/{id}/directory` and `/criteria` (`?history=true`). `GET /network/{id}/events` (stream).
