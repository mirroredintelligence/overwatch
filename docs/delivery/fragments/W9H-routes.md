# W9H: the routes and shapes the front-end bundles that follow can build on

All back-end paths are at the app ROOT (`/identity/...`, `/reporter/...`) or under `/fhir` as marked. Every answer is `no-store`. No tenant, person, device or role is ever sent in a body, query or header; the tenant is the token's.

## The executive's notifications (W7C-K5, DEC-1040 to DEC-1044)

An executive's token is the staff token (role `exec`, subject `stf-...`, no device, no services). They are admitted to these three back-end routes and to no other `/reporter/...` route (every other role, and the executive on any other reporter route, gets the 404 of a refused role; the platform operator is a 401 at the edge).

### POST /identity/push-subscription (root)
Roles `reporter`, `exec`. Header `Idempotency-Key`. Body `{subscription: {endpoint, keys: {p256dh, auth}, expirationTime?}, wordingVersion, deviceId}`. For an executive `deviceId` is not checked against the token (there is none); the BFF sends the SHA-256 of the endpoint, base64url (43 characters). On the first save the executive's person record is made (DEC-1042). `200 {"saved": true, "consentAt": "<iso>"}`. `401` for a removed person (no record is brought back) or a refused token; `400` for a body that names more than it takes or an endpoint that could reach an inside address.

### DELETE /identity/push-subscription (root)
Roles `reporter`, `exec`. Header `Idempotency-Key` and `X-Device-Id` (the device the subscription was saved under). `200 {"removed": true}`. Not used by a screen yet (W9H-2).

### POST /reporter/push-test (root)
Roles `reporter`, `exec`. Body `{}`. `200 {"queued": true}`; `409 {"code": "no-subscription"}`; `429` with `Retry-After` (three in ten minutes per person). For an executive it queues one K3 person push: title `Test notification`, body `Alerts are working on this phone.`, no link.

### The person push on the bus
`SendMessage` outbox payload `{message_id: "K3", channel: "push", recipient_practitioner_id, title, body[, alert_id]}`, no `recipient_role_id`, no `communication_id`, no `sealed_content`. The push sender delivers it to every installed app of that person (high urgency), deletes a subscription reported gone, and writes no Communication. Alerts (U34) use the same payload.

### BFF
- `POST /api/bff/push/subscriptions`: roles `reporter`, `exec`. Body `{subscription: {endpoint, keys}, consentWordingVersion}`: `"v1"` for a reporter, `"exec-v1"` for an executive (each role is refused the other's, 400). A body that names a device is a 400. Answer `{saved: true}`.
- `POST /api/bff/push/test`: roles `reporter`, `exec`. Body `{}`. Answers `{queued: true}`, `409 {code: "no-subscription"}`, `429` with `Retry-After`.
- `GET /api/bff/push/key`: unchanged (pre-session, the platform's public key).
- The installed app's front door `/app` sends a signed-in executive to `/planning`; `/planning/phone` is the executive's page ("Alerts on this phone", `components/exec/PhoneAlerts.tsx`); a lead on it goes to `/planning`.

## The districts of a postcode that cannot be used (W50, DEC-1045, DEC-1046)

### POST /fhir/HealthcareService/$filter-options
Unchanged request. The answer's top-level Parameters gain `{"name": "district", "valueString": "DT1"}`, one part per district, in the order to show them, at most twelve, **only** when `notFound` or `outOfArea` is `true` (and none otherwise). They are the districts of the bound tenant's unsuspended services' current criteria that the postcode locator can place; the case's own district is never among them.

### PUT /fhir/ServiceRequest/{id}
Unchanged headers (`If-Match`, `Idempotency-Key`; advisor and clinical). A district alone is carried by the extension on the contained Patient:
```
{"resourceType": "ServiceRequest",
 "contained": [{"resourceType": "Patient", "id": "p",
   "extension": [{"url": "https://diucs.example/StructureDefinition/postcode-district", "valueCode": "DT1"}]}]}
```
It is trimmed and upper-cased, must be `^[A-Z]{1,2}[0-9][A-Z0-9]?$` (a full postcode, a list or a repeated extension is `400` and is not echoed), must not come with a full `postalCode` in the same body (`400`), and is kept as the case's district. A closed case is `409`; another tenant's case is the one `404`. The read of the case answers it as `address[0].postalCode` as before.

### BFF
- `GET /api/bff/cases/[ref]/options` answers the options view with `districts: string[]` (empty unless `notFound` or `outOfArea`; only strings that are districts, once each, at most twelve).
- `PUT /api/bff/cases/[ref]/district`: advisor only, `Idempotency-Key` required, CSRF as every write. Body exactly `{district}`. Reads the case for its ETag, saves with it, answers the case view (`CaseView`). `400` for any other body or a district that is not one, `412 {code: "conflict"}` when the case changed in between, `404` for an unknown or another tenant's case.
- Components: `PostcodeNotFound` and `OutOfArea` take `districts?: string[]` and `onChooseDistrict?: (district) => Promise<boolean>`; the map (`MapScreen`) and the list (`OptionsList`) pass them and read the options again once a district is kept.
