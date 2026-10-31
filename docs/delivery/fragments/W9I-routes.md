# W9I routes: wall screens administration (for the front-end bundles that follow)

Back end (root, not under `/fhir`; `routes_screens.py`, router prefix none). `GET`: lead or tenant-admin; the revoke: lead only; every other role is 404 (the non-revealing answer), the platform operator 401. Every answer `Cache-Control: no-store`. The tenant is the token's; nothing in a body, query or header names one.

## `GET /screens`

200:
```json
{
  "scope": "tenant",
  "asOf": "2026-10-30T10:00:00Z",
  "screens": [
    {
      "deviceId": "s-1",
      "name": "Ward 4 corridor",
      "location": "Level 2",
      "status": "active",
      "state": "online",
      "boardScope": "tenant",
      "networkId": null,
      "networkName": null,
      "networkAvailable": true,
      "scopeVersion": 1,
      "pairedAt": "2026-10-27T10:00:00Z",
      "lastSeenAt": "2026-10-30T09:59:20Z",
      "revokedAt": null
    }
  ],
  "networks": [{"id": "net-...", "name": "..."}]
}
```
- Role lead or tenant-admin (the one route W9B's board-scope setting also uses). `status` is the device's own (`active | paired-unclaimed | revoked`); `networkId`, `networkName`, `networkAvailable`, `scopeVersion` are W9B's (`W9B-routes.md`).
- `state`: `online | offline | waiting | never-connected | revoked`. `location`, `pairedAt`, `lastSeenAt`, `revokedAt` may be `null`. `boardScope`: `tenant | network`.
- Order: live screens by name then id; revoked last; a screen revoked more than 30 days ago is not listed.
- Never a token, a token hash or a pairing secret.

## `POST /screens/{deviceId}/revoke`

Headers: `Idempotency-Key` (required), `Content-Type: application/json` (required by the body-type middleware), body `{}` (never read). `deviceId` is `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$` (else 400).
- 200 `{"deviceId": "s-1", "status": "revoked", "revokedAt": "2026-10-30T10:00:00Z"}`; the same answer for a screen revoked already (the first time), with no second audit entry.
- 404 for a screen the tenant does not hold (another tenant's included).
- 400 for a missing or malformed key.
- Effect: the screen's token hash is removed and its status is `revoked`; the device token gets 404 at `POST /auth/device-token`; a wall token it already holds gets 401 at its next request to any route behind `require_role` (and the three `current_actor` reads a wall may make).

## BFF (front end)

- `GET /api/bff/screens` (lead): the same body, checked and cut to the fields the page shows (`deviceId, name, location, state, boardScope, pairedAt, lastSeenAt, revokedAt`; the BFF row has `state`, not `status`). 500 for a malformed answer, the back end's own status for a failure, 401 `session-ended` when the back end no longer knows the session.
- `POST /api/bff/screens/[id]/revoke` (lead, CSRF `X-CSRF-Token`, `Idempotency-Key`): `{deviceId, status: "revoked", revokedAt}`. An id that is not an id is 404 without a back-end call.
- `POST /api/bff/screens/session` (wall display, no session): 404 `{code: "disconnected", message: "This screen was disconnected."}` when the back end refuses the screen's device token; it also forgets the device cookie and ends the wall session.

## Extension points for the network-scope part (TEN-072's other half)

- `scope` in the list body is `"tenant"`; a network list is another use case with `scope: "network"` (rows would add the organisation's label, never a person).
- `boardScope` is in every row; the which-board control (W9B / TEN-067) adds its fields to the same rows.
