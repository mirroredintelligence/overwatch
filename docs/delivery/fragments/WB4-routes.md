# WB4: the routes and shapes the front-end bundles that follow can build on

Every answer is `no-store`. No tenant, person or role is ever sent in a body, query or header; the tenant is the token's (or, for the link pages, the host's).

## Back end

### GET /fhir/Task?focus=ServiceRequest/{caseId}
Roles advisor, clinical (any other role reads the 404 of an unknown id; no token is a 401). Answer: `Bundle` (`type: searchset`, `total`, `entry[].fullUrl` `Task/<id>`, `entry[].resource` the booking Task as `GET /fhir/Task/{id}` gives it). The Task carries, as `output` entries by `type.coding[0].code`: `decision`, `reason`, `confirmed-at`, `phone-prompt-at` (the tenant's prompt time), `request-message`, `request-delivery` (`queued|sent|delivered|failed`, read-time only), `acknowledged-at`, `acknowledged-by`. A reporter reading a Task never sees the last four of those, nor `focus` or `for`.

### GET /fhir/Task?alert=open
Same roles and shape. The bookings in status `withdrawn` or `not-reached` that nobody has acknowledged. Any other query (more than one parameter, another name, `alert` other than `open`, a `focus` that is not `ServiceRequest/<id>`) is a 400 that names the parameter, never the value.

### POST /fhir/Task/{id}/$acknowledge
Also accepts a `not-reached` booking now (was withdrawn only). The first acknowledgement is kept on the booking with who and when.

### Link pages (root, no session)
- `GET /links/{token}` for a closed booking link answers 410 `{state, kind: "booking", reference, closedAt, confirmedAt?, cancelledAt?, coordinationPhone?}` (times are instants; the phone is the tenant's current number). A capacity link, an unknown one and another tenant's say `{state}` alone.
- A confirm answer carries `confirmedAt`; a decline or a withdrawal answer carries `respondedAt`.
- B4, B5 and B6 echoes go to the reporter on their own channel (text, email, push).

## BFF (front end)

- `GET /api/bff/bookings?case=<caseRef>`: role advisor. `{bookings: BookingState[]}`, one per booking of the case (any service). No other parameter (400 `{code: "invalid"}`).
- `GET /api/bff/bookings?alert=open`: role advisor. `{bookings: BookingState[]}`, the open alerts. No other parameter.
- `BookingState`: `{id, caseRef, serviceId, reference, status, requestedAt, replyBy, phonePromptAt, confirmedAt, declinedAt, declineReason, expiredAt, withdrawnAt, withdrawReason, delivery: "queued"|"sent"|"delivered"|"failed"|null, acknowledgedAt}`. Never who acknowledged.
- `POST /api/bff/bookings`, `GET /api/bff/bookings/{id}`, `POST .../cancel`, `POST .../acknowledge`: unchanged in shape; the state they answer has the new fields.
- `GET /api/bff/links/{token}` (410): `{state, csrfToken?, kind?, reference?, closedAt?, confirmedAt?, cancelledAt?, coordinationPhone?}`. A recorded figure's answer carries `thanks` (sealed).
- `POST /api/bff/links/{token}`: refuses (400 `{state: "invalid"}`) an unknown action, a `value` that is not a whole 0 to 999 with `number`, and a `reason` that is not a code with the actions that take one.
- `POST /api/bff/links/{token}/renew`: needs `X-CSRF-Token` equal to the `csrfToken` of the closed link's answer (403 `{state: "forbidden"}` otherwise); 202 as before, 429 when the budget is spent.
- Page `/l/thanks?d=<sealed>`: no token in the address.
- Components: `OpenBookingAlerts` (`components/advisor`), mounted by `app/(advisor)/advisor/layout.tsx`.
