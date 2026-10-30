# W7C routes: what the reporter-app BFF can now call

For the front end to drop its `not-built` stubs. Every path is the back end's own (JSON, not FHIR,
outside `/fhir`). Times are UTC with a `Z` and whole seconds. Every response is `Cache-Control:
no-store`. A refusal is a FHIR `OperationOutcome` (`issue[0].code`, `issue[0].diagnostics`) unless a
route says otherwise. The BFF never sends the browser a tenant, a person, a device id, a session id,
a token or a number.

Two kinds of caller.

- **Host-bound** (no `Authorization`): the tenant is the host of the request, so the BFF forwards the
  host the browser addressed (as `identityCall` already does). Marked `host`.
- **Bearer** (`Authorization: Bearer <back-end token>`, role `reporter`): the tenant, the person and the
  phone are the token's. Marked `bearer`. No token is `401`; another role is `404`; a phone that was signed
  out is `401`. Writes marked `key` need `Idempotency-Key` (a missing one is `400`).

A body names only the fields shown: any other field (a tenant, a person, a number, a role) is `400`.

## Set-up (host)

### `GET /invitations/{token}` -> BFF `GET /api/bff/invitations/[token]`
- `200 {"state":"valid","service":"UCR West","role":"Duty manager","maskedPhone":"07xxx xxx456","expiresAt":"2026-10-31T06:00:00Z"}`
  (the shape of `parseInvitation`).
- `410 {"state":"expired"}` for anything that cannot be used (unknown, malformed, expired, used, another
  tenant's, another purpose's, unknown host). One body; the BFF may map it to its own `expired`.
- `429` when one address reads more than 60 in 10 minutes.

### `POST /identity/invitations/{token}/code` -> BFF `POST /api/bff/identity/code` with `{invite}`
- Body `{}`. `202 {"accepted":true,"resendAfterSeconds":60}` always, for a real, an unusable and an unknown
  token alike. `429` over 10 requests from one address in 10 minutes.

### `POST /identity/invitations/{token}/code/verify` -> BFF `POST /api/bff/identity/code/verify` with `{invite, code}`
- Body `{"code":"482913","deviceId":"<the phone's device id>"}` (the BFF adds the device id from its cookie).
- `200 {"verified":true}`: the code is recorded on the device. The BFF answers the browser `{ok:true}`.
- `400` with `issue[0].diagnostics` `"That code is not right"` and a top-level `"triesLeft": 4` (5 tries; 0 on
  the last); `"Ask for a new code"` with `triesLeft: 0` when five wrong tries or a lapsed code. The BFF answers
  `{ok:false, triesLeft}`.
- `409` the code is right but this device cannot be set up with it ("start again on this phone").

### `POST /identity/device/code` -> BFF `POST /api/bff/identity/code` with `{purpose}` (`reverify`, `pin-reset`)
- Body `{"deviceId":"...","purpose":"reverify"|"pin-reset"}`. `202` as above, always (an unknown device is
  the same answer). Any other purpose is `400`.

### `POST /identity/device/code/verify` -> BFF `POST /api/bff/identity/code/verify` with `{purpose, code}`
- Body `{"deviceId":"...","purpose":"reverify"|"pin-reset","code":"482913"}`. `200 {"verified":true}`
  (the device's last verification is now: the PIN routes follow), `400` as above, `409` as above.

### `POST /identity/channel` -> BFF `POST /api/bff/reporter/channel` before sign-in (set-up, locked PIN "text me")
- Body `{"deviceId":"...","channel":"app"|"text"|"email"}`. `200 {"channel":"app"}`.
  `403` (one answer: unknown device, a device not verified by a text code in the last ten minutes, nobody
  who reports); `400` for any other channel word. The change is on every reporter post the person owns.

### `GET /public/push-key` -> BFF `GET /api/bff/push/key`
- `200 {"publicKey":"<base64url>"}` (the `applicationServerKey`); host-bound; `Vary: Host`. `503
  {"code":"not-configured"}` when the platform has no key. `404` for a host no tenant owns.

### `POST /identity/new-phone/verify` (existing) now carries the SPOA number
- `200 {"status":"pending-callback","spoaPhone":"01305 000111"}`; `spoaPhone` is `null` when the tenant has
  set none. The BFF passes it on so the wait screen can show "Phone the SPOA on ...". The route's other
  answers are unchanged (`400` wrong or lapsed, `409` device refused, `429` throttled).

## The reporter's app (bearer)

The BFF sends the **back-end token** it holds for the reporter as the bearer (the issue of that token is W7B's).

### `GET /reporter/services` -> BFF `GET /api/bff/reporter/services`
- `200 {"services":[{"id","name","state":"due"|"confirmed"|"paused","recordedValue":4|null,"unitLabel",
  "at":"..."|null,"nextDue":"..."|null,"pendingAcceptance":false,"letter":"A"?,"replyBy":"..."?}]}`,
  by name. `letter` only when two or more are due; `replyBy` only on a due row. This is the `ServiceRow`.

### `GET /reporter/services/{id}/prompt` -> BFF `.../services/[serviceId]/prompt`
- `200 {"service","unitLabel","recordedValue","asOf","low","high","replyBy","nextDue"}` (the `Prompt`);
  `replyBy` is null unless the service is due. A service the reporter does not hold is `404`.

### `POST /reporter/services/{id}/report` (key) -> BFF `.../services/[serviceId]/report`
- Body `{"kind":"confirm"|"number"|"closed","value":5,"confirmOutOfRange":true}` (`value` only with `number`,
  0 to 999; `confirmOutOfRange` only with `number`).
- `200 {"result":"recorded","serviceName","value","recordedAt","nextDue"}`.
- `200 {"result":"outOfRange","serviceName","value","low","high"}`: nothing recorded; the same figure sent
  again with `confirmOutOfRange:true` is recorded (and flagged).
- `409 {"result":"confirmLimit","serviceName"}`: two confirms in a row already.
- `409 {"result":"sendNumber","serviceName","reason":"no-figure"|"stale"|"changed"}`: a Y cannot be used,
  send the number.
- `404` a service not held; `400` a body the screens cannot send.

### `GET /reporter/services/{id}/history?day=today` -> BFF `.../services/[serviceId]/history`
- `200 {"items":[{"at","value","kind":"number"|"confirmed"}]}`, today in the tenant's zone, newest first.
  Any `day` but `today` is `400`.

### `POST /reporter/reports/batch` (key) -> BFF `POST /api/bff/reporter/reports/batch`
- Body `{"items":[{"serviceId","kind":"confirm"}]}` (1 to 10 different services; only confirms).
- `200 {"results":[{"serviceId","result":"recorded"|"sendNumber"|"confirmLimit","at"?,"reason"?}]}` in the
  order sent. `404` (nothing written) if any service is not the reporter's.

### `GET /reporter/settings` -> BFF `GET /api/bff/reporter/settings`
- `200 {"channel":"app"|"text"|"email","maskedPhone":"07xxx xxx123","maskedCover":"07xxx xxx456"|null,
  "reverifyInDays":27,"otherDevices":1}`. `otherDevices` is the number of other phones signed in.

### `POST /reporter/cover` -> BFF `POST /api/bff/reporter/cover`; `POST /reporter/services/{id}/cover` -> BFF `.../services/[serviceId]/cover`
- Body `{"phone":"07700 900456","until":"tonight"|"this-week"|"date","date":"2026-11-05"}` (`until` defaults to
  `this-week`; `date` only with `until:"date"`, today to 14 days ahead). The first covers every post the
  reporter owns, the second one service.
- `200 {"coveredUntil":"2026-11-01T23:59:00Z","services":2}`. `400` a number that is not a UK mobile, the
  reporter's own number, a bad length or date (nothing echoed). `404` a service the reporter does not own.

### `POST /reporter/channel` -> BFF `POST /api/bff/reporter/channel` (settings, after sign-in)
- Body `{"channel":"app"|"text"|"email"}`. `200 {"channel":"..."}`. `400` for `email` with no address on record.

### `POST /reporter/services/{id}/accept` -> BFF `.../services/[serviceId]/accept`
- Body `{"accept":true|false}`. `200 {"accepted":true}`. `false` ends the reporter's own post on that service.

### `GET /reporter/setup-summary` -> BFF `GET /api/bff/reporter/setup-summary`
- `200 {"service","contactBy":"app"|"text"|"email","maskedPhone","nextUpdateDue":"..."|null,"textCodeInDays":30}`.

### `POST /reporter/push-test` -> BFF `POST /api/bff/push/test`
- Body `{}`. `200 {"queued":true}`; `409 {"code":"no-subscription"}` (save the subscription first);
  `429` over three in ten minutes.

### `GET /reporter/bookings/{reference}` -> BFF `GET /api/bff/reporter/bookings/[ref]`
- `200 {"reference":"1001","taskId":"<Task id>","service","ageBand","need","urgency","replyBy",
  "status":"requested"|"confirmed"|"declined"|"expired","bookingStatus":"<exact state>","multiService":true,
  "spoaPhone":"01305 000111"|null,"confirmedAt":"..."?}`. This is the screen's `Booking` (plus `taskId`,
  `bookingStatus`; `spoaPhone` may be null). Not four digits, unknown, another service's: `404`.

### `POST /reporter/bookings/{reference}/respond` (key) -> BFF `.../bookings/[ref]/respond`
- Body `{"decision":"confirm"|"decline","reason":"full"|"outside-criteria"|"staffing-or-transport"|"other"}`
  (`reason` only with `decline`). `200 {"status":"confirmed","confirmedAt":"..."}` or `{"status":"declined"}`
  (the shape the BFF already returns). `409` the booking was already answered or is no longer open. The BFF can
  call this route with the reference as it is, so it needs no reference-to-Task-id mapping of its own; the read
  gives `taskId` for any use of `$respond`.

## Moving the BFF off its stubs

| BFF route | back end |
|---|---|
| `invitations/[token]` | `GET /invitations/{token}` (410 -> its `expired`) |
| `identity/code` with `invite` | `POST /identity/invitations/{token}/code` |
| `identity/code/verify` with `invite` | `POST /identity/invitations/{token}/code/verify` (adds `deviceId` from the cookie) |
| `identity/code` with `purpose` | `POST /identity/device/code` (adds `deviceId`) |
| `identity/code/verify` with `purpose` | `POST /identity/device/code/verify` |
| `reporter/channel` before sign-in | `POST /identity/channel`; after sign-in `POST /reporter/channel` |
| `push/key` | `GET /public/push-key` |
| `push/test` | `POST /reporter/push-test` |
| `reporter/setup-summary`, `settings`, `services` | the three GETs above |
| `reporter/services/[id]/prompt`, `report`, `history`, `accept`, `cover` | the routes of the same names |
| `reporter/reports/batch`, `reporter/cover` | `POST /reporter/reports/batch`, `POST /reporter/cover` |
| `reporter/bookings/[ref]`, `.../respond` | `GET` and `POST /reporter/bookings/{reference}[/respond]` |
| `identity/new-phone/verify` | adds `spoaPhone` to its 200 |

The BFF's own `ownService` check stays as a first line; the back end is the authority and answers `404`
for a service the reporter does not hold, so a BFF that skips it fails closed.
