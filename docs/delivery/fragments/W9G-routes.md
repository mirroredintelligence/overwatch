# W9G routes: what the advisor saw and the way to reach the advisor (for the front-end bundles that follow)

Both routes are at the back end's ROOT (not under `/fhir`, like `/clinical/presence`): the BFF passes `root: true` to `fhirFetch`. Both need a bearer token of the role `clinical`. Both answer `Cache-Control: no-store`. Both answer the same 404 (an OperationOutcome with `code: not-found`, the fixed text "The requested resource was not found.") for: every other role, a clinician who does not hold the request, a request that is waiting, a request whose 10-minute lock has lapsed, an unknown id, another tenant's request. The platform operator is refused at the edge (401). Nothing here takes a tenant from the path, query, header or body.

"Holds" is the queue's own rule: the request is locked to this clinician (`taken_by`) and the lock has not lapsed (taken less than 10 minutes ago), or (for `seen` only) the clinician advised it.

## GET /clinical/requests/{id}/seen

What the advisor saw when they asked: the display of the options the advisor had of this case, as it was (the last options display by the asking advisor at or before the moment they asked; DEC-1030). Read only; no audit entry.

```json
{
  "state": "shown",
  "shownAt": "2026-10-23T13:13:20Z",
  "options": 3,
  "noneFitted": false,
  "lines": [
    { "service": "UCR West", "shownAs": "option", "status": "accepting", "statusText": "Accepting",
      "figure": "4", "age": "9 min old", "stale": false, "why": null, "criteriaVersion": 3 },
    { "service": "Hospital at home", "shownAs": "option", "status": "over-capacity", "statusText": "Over capacity",
      "figure": "+2", "age": "14 min old", "stale": false, "why": null, "criteriaVersion": 3 },
    { "service": "UCR East", "shownAs": "not-suitable", "status": "not-accepting", "statusText": "Not accepting",
      "figure": null, "age": "3 min old", "stale": false, "why": "Not accepting", "criteriaVersion": 3 }
  ]
}
```

- `state`: `shown` (a display was read), `none` (the request kept none: say "No options display is recorded", never "nothing fitted") or `unreadable` (a display is named and cannot be read; say so and show no line). `shownAt` is an ISO 8601 UTC instant (shown in London time) and is null unless `shown`. `lines` is empty unless `shown`. `options` is the number of lines shown as `option`. `noneFitted` is true only when a display was read and none of its lines is an `option`.
- A line: `service` is the current name ("A service that is no longer listed" if it has gone; never an id). `shownAs` is `option` or `not-suitable`. `status` is one of `accepting|limited|not-accepting|over-capacity|not-updated|out-of-hours` and `statusText` the word for it. `figure` is text: what the service could take, `+n` for how far over capacity it was, or null (a status with no figure, or an over-capacity service whose display pre-dates `over_by`): say "no figure", never zero. `age` is how old the figure was then ("9 min old", "2 hrs 10 min old", "just now", "no time given"). `stale` is true when the figure was over 2 hours old (say it in words). `why` is a closed phrase for a not-suitable line (`Not accepting`, `Out of hours`, `Not updated`, `Suspended`, `Outside its criteria`, `Criteria not current`; "Not suitable" for an older display with no reason) and null for an option. `criteriaVersion` is the criteria version in force or null.
- No postcode, district, service id, criteria id, person id, audit id or case reference is in the answer.

## GET /clinical/requests/{id}/advisor-contact

The number to phone the advisor who asked, for the clinician who holds the request while it is being worked (a 404 once it is advised). Writes one audit entry (`ReadAdvisorContact`; the request id and only `via`); the number is never in an audit entry, a log or telemetry. Ask for it when the clinician presses "Call the advisor", not when the page opens.

```json
{ "available": true, "via": "work-phone", "phone": "07700 900123", "name": "Sample Advisor" }
{ "available": true, "via": "advisor-line", "phone": "01305 900000", "name": null }
{ "available": false, "via": null, "phone": null, "name": null }
```

- `via: "work-phone"`: the advisor's own work phone, held for an active advisor (a ProtectedContact, `work-<practitioner id>`); `name` is the advisor's name. `via: "advisor-line"`: the tenant's advisor line (tenant contact kind `advisor-line`); no name. `available: false`: neither exists: say so ("No number is held for the advisor, and this organisation has no advisor line set"). The number is returned whole.
- Keep it in memory only. Never put it in a URL, storage, a cookie, a log or a telemetry attribute.

## Changed: the options display snapshot (FilterOptions audit rows)

Each row gains `over_by` (int or null) and, for a not-suitable row, `reason` (a code). Additive; old rows lack both.

## Changed: tenant contacts

`ContactKind.ADVISOR_LINE = "advisor-line"`: a desk or switchboard number (phone validation as the coordination phone), set with the existing tenant-contact use case (`RecordContact`).

## BFF (front end)

`GET /api/bff/clinical/requests/[id]/seen` answers `{ "seen": <the object above> }`; `GET /api/bff/clinical/requests/[id]/advisor-contact` answers `{ "contact": { "via", "phone", "name" } }` (`via` null for none). Role `clinical` only (403 otherwise, no back-end call); an id not shaped `[A-Za-z0-9-]{1,64}` and every back-end refusal is the one 404 `{code:"not-found", message:"We could not find that."}`; a back-end failure is the BFF's usual 5xx.
