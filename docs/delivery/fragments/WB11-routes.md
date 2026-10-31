# WB11 routes: what the front-end bundles that follow can build on

## Back end (root, `Cache-Control: no-store`)

### `POST /screens/preview` (lead only)
Headers: `Content-Type: application/json` (no Idempotency-Key: it changes nothing). Body `{"code": "482 913"}` (spaces and hyphens allowed; any other field is 400).
- 200 `{"firstSeenAt": "2026-10-30T09:56:00Z", "deviceClass": "wall-display"}`.
- 404: the one refusal of pairing (wrong, short, expired, used, another tenant's code; a role that is not the lead). 429 after five wrong codes (previews and connects together) in ten minutes, with `Retry-After`. 401 no token.
- Burns nothing, writes nothing, names no organisation (the BFF adds the tenant's own display name from its profile).

### `GET /network/{network_id}/options?case={case id}` (advisor, clinical)
`case` is the advisor's own case id (`^[A-Za-z0-9_-]{1,64}$`), required; a bad or missing one is 400. Every other role, a non-member, a network outside the claim, an unknown network, another tenant's case and a case that is not there are the one 404 of the network routes; a closed case is 409; an incomplete case (no age band or district) is 400. The network of the path must be in the token's `networks` claim and the registry (the registry is the authority). 200:
```json
{
  "options": [
    { "row_ref": "lst-...", "organisation_name": "...", "service_name": "...", "category": "hospital-at-home-or-virtual-ward",
      "status": "accepting|limited|over-capacity", "effective_available": 1, "over_by": null, "unit_label": "beds" | null,
      "data_age_seconds": 1200 | null, "fits": ["Covers this postcode", "Takes frailty"], "warnings": ["Limited: phone to confirm"],
      "criteria_version": 3, "review_by": "2027-04-29", "contact_label": "Service line" | null, "contact_phone": "..." | null,
      "position": {"lat": 52.0, "lon": -1.5} | null, "travel": {"low_minutes": 12, "high_minutes": 24} | null }
  ],
  "not_suitable": [ { "row_ref": "lst-...", "organisation_name": "...", "service_name": "...", "reason": "not accepting | out of hours | not updated for 4 hrs. Phone to confirm. | outside criteria | not available on the network. Phone to confirm. | criteria not shared. Phone to confirm." } ],
  "generated_at": "...", "patient": {"lat": 52.0, "lon": -1.4} | null, "not_found": false, "out_of_area": false,
  "system_name": "...", "pathway_name": "...", "time_zone": "Europe/London"
}
```
Options are ordered travel (low end) first, rows with no travel last, then organisation, service, reference. Not suitable: organisation, service, reference. The advisor's own organisation's services are never in it. No comment, pending count, reporter, tenant, grant or source service id. One tenant audit entry (`FilterNetworkOptions`, action `R`, entity the case) per read. There is no booking, request or escalation behind a row.

## BFF

| Route | Roles | Notes |
|---|---|---|
| `POST /api/bff/screens/preview` | lead | CSRF. Body `{code}` only (any other key is 400). 200 `{organisationName: string \| null, firstSeenAt, deviceClass: "wall-display"}`; 404 `{code: "not-found", message: "That code is not valid or has expired. Check the screen for a new code."}`; 429; 503 |
| `GET /api/bff/screens` | lead, tenant-admin | `{scope: "tenant", asOf, screens: [{deviceId, name, location, state, boardScope, networkId, networkName, networkAvailable, scopeVersion, pairedAt, lastSeenAt, revokedAt}], networks: [{id, name}]}` |
| `PUT /api/bff/screens/[id]/board-scope` | lead, tenant-admin | CSRF; `If-Match: W/"<scopeVersion>"` and `Idempotency-Key` required; body `{boardScope: "tenant"}` or `{boardScope: "network", networkId}` (the one route that takes `networkId` in a body: `allowNetworkIdInBody`); 200 `{deviceId, boardScope, networkId, networkName, networkAvailable, scopeVersion}`; 412 stale; 404 |
| `GET /api/bff/wall/board` | wall (and advisor, lead, exec: their own board) | `{scope: {boardScope, scopeVersion, fallback, networkName}, board}`; the network's board is a wall `Board` whose entries also have `organisation`, `ownOrganisation`, `paused` |
| `GET /api/bff/wall/network-events` | wall | `text/event-stream`: `network-board`, `scope-ended` |
| `GET /api/bff/network/options?networkId=&case=` | advisor, clinical | the options in camelCase (`rowRef`, `organisationName`, `serviceName`, `dataAgeSeconds`, `contactPhone`, `travel: {lowMinutes, highMinutes}`, `notSuitable: [...]`, `patient`, `notFound`, `outOfArea`, `generatedAt`, `systemName`, `pathwayName`, `timeZone`); the query holds these two keys once each and nothing else |

## Pages

`/lead/screens` (list, Change board, Unpair, Re-pair, Add a wall screen), `/lead/screens/new` (form and the confirm step), `/screen` (the wall: own board, network board or fall back), `/network/home` (advisor and executive: counts over the network), `/advisor/case/[ref]/network-options`, `/advisor/case/[ref]/network-map`; the advisor's home, own options and map pages and the executive's home, services and service detail carry the scope header.
