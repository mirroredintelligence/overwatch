# WB10: the BFF network routes and the network pages (front end of TEN-068 to TEN-071, W17, W43, TEN-082)

Every route is a `withBff` route: the signed-in session's tenant only, CSRF and the input guard as every other route, `private, no-store`, and every answer rebuilt from the fields the pages use (a field the back end added never passes). All are GET. Every refusal is the one 404 `{"code":"not-found","message":"We could not find that."}` (the routes say `idScoped`): a network the tenant is not an active member of, one it left, an unknown id, and a role the back end refuses cannot be told apart. The back end is called at the app ROOT (`root: true`): `/networks`, `/network/{id}/...`.

## The one place a network id is accepted

`networkId` is allowed as a QUERY key only on the seven read routes below (`withBff(..., { allowNetworkId: true })`): once, holding a network id (`^net-[a-z0-9][a-z0-9-]{1,26}$`). Any other key that starts with `tenant`, `scope`, `network` or `source`, any header, any body key, a second `networkId`, or a value that is not a network id is a 400 `{"code":"invalid"}` before any work. `GET /api/bff/network` (the list) refuses the key too: it offers networks, it takes none. `test/guards/bff-routes.test.ts` names the seven files (`TAKES_NETWORK_ID`) and fails if another route says `allowNetworkId` or one of these stops.

The id is the opaque `net-...` the server offered in the list. It is a choice among the offered networks and never an authority: every call first asks the back end `GET /networks` (the registry, not the token's claim) and goes on only for a network in that answer, then the back end checks the token's claim and the registry again. No page holds it in an address, a cookie or storage; it is in the query of the BFF data calls only.

## Routes

| Route | Roles | Back end | Answer |
|---|---|---|---|
| `GET /api/bff/network` | advisor, clinical, lead, owner, exec | `GET /networks` and the tenant profile | `{ ownOrganisation: string \| null, networks: [{ id, name, systemName, pathwayName, timeZone }] }`. `ownOrganisation` is the viewer's own organisation's display name (from its profile), used only to mark its rows. A tenant in no network: `networks: []`, 200. |
| `GET /api/bff/network/board?networkId=` | same five | `GET /network/{id}/board` | `{ entries: [{ rowRef, organisationName, serviceName, category, presentation: 'shown'\|'unavailable', status \| null, unitLabel, effectiveAvailable, overBy, used, established, reportedAt, staleWarning, wasDueAt }], pressure, allLimitedOrWorse, generatedAt, systemName, pathwayName, timeZone }` in the back end's order |
| `GET /api/bff/network/events?networkId=` | same five | `GET /network/{id}/events` (stream) | `text/event-stream`: `event: network-board` `data: {"changedAt": "..."}`; `event: scope-ended` `data: {}`; keep-alive comments. The registry is asked BEFORE the stream is opened. |
| `GET /api/bff/network/directory?networkId=[&history=true]` | same five | `GET /network/{id}/directory` | `{ entries: [{ rowRef, organisationName, serviceName, category, active, source, contactLabel, contactPhone, location: { name, postalDistrict, city, latitude, longitude } \| null, openingHours: [{ position, days: number[], allDay, start, end }], presentation, endedAt, endReason }], systemName, pathwayName, timeZone }` |
| `GET /api/bff/network/criteria?networkId=[&history=true]` | same five | `GET /network/{id}/criteria` | `{ entries: [{ rowRef, organisationName, serviceName, version, ageMin, ageMax, districts, accepts, excludes, reviewBy, endedAt, endReason }], ... }` |
| `GET /api/bff/network/system-now?networkId=` | same five | `GET /network/{id}/system-now` | `{ generatedAt, services, organisations, byStatus: { accepting, limited, 'not-accepting', 'over-capacity', 'not-updated', 'out-of-hours', unavailable }, pressure, allLimitedOrWorse, alert: { raised, level, limitedOrWorse, watchFrom, highFrom }, systemName, pathwayName, timeZone }` |
| `GET /api/bff/network/phones?networkId=` | same five | `GET /network/{id}/phones` | `{ phones: [{ rowRef, organisationName, serviceName, category, presentation, status, staleWarning, reportedAt, contactLabel, contactPhone }], organisations, ... }` |
| `GET /api/bff/network/week?networkId=&weekStart=YYYY-MM-DD` | exec, lead | `GET /network/{id}/week` | `{ weekStart, withheld, hoursSampled, onTimePct: { label, value, hidden }, statusShare: { <status>: measure }, pressureHours: { normal, watch, high: measure }, pressureOverTime: [{ hour, pressure }], ... }`. `weekStart` is a Monday: another day, a date that is not one, or none is a 400 before the back end is asked. |

`history=true` is the only other query value a route takes (`false` or none is the live list; any other value is a 400).

## Pages (route group `(network)`; the proxy lets in advisor, clinical, lead, owner and exec; the week page, exec and lead)

`/network/board` (TEN-070), `/network/history` (TEN-070), `/network/services` and `/network/services/[id]` where `[id]` is the opaque `rowRef` (TEN-071), `/network/system-now` (W17), `/network/phones` (W43), `/network/week` (TEN-082). Not built here (later bundles): `/network-admin` (TEN-080), `/admin/sharing` (TEN-081), `/lead/screens` network choice (TEN-072, W9I).

## For the bundles that follow

- TEN-072 (W9I): the wall's network board can use `ScopeHeader` (`variant="wall"`, `scope="network"`, `networkName`) and `NetworkBoard`'s tiles (`NetworkTile`); the wall's own routes are `GET /screens/me/network-board` and `/screens/me/network-events` (W9B), not these.
- TEN-080/081: use `NetworkScope` (the gate: list, one-refusal panel, chooser) only for network reads; the administration routes are a different family and need their own BFF routes (they must not take `networkId` through this list).
- `lib/network/browser.ts` is the browser's one place for these reads (`readNetworkList`, `readNetworkView`, `fetchNetworkBoard`, `networkEventsUrl`).
