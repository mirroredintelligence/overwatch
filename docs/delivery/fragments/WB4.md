# WB4: bundle B4 of the gap triage (booking pages, the B4/B5/B6 echoes, the plain-words table for needs, timers, the 415 class)

Bundle WB4, branch `task/build-WB4` off `integration/build`. Numbers: DEC-1150 to DEC-1159, H-800 to H-819 (DEC-1150 to DEC-1158 and H-800 to H-803 used). Back end and front end. All new patient- and clinician-facing wording is `[ASSUMED]` pending written approval (DEC-1100, Q2).

## Decisions

### DEC-1150 One table of plain words for the needs; every printed need uses it and none is left off (B4 task 1, DEC-062 item 2, DEC-047 item 9; KI-650, H-489)
Status: accepted (wave 9). `domain/rules/need_words.py` holds `NEED_WORDS` (`fall-no-injury` is "fall, no injury", and so on) and `need_words(needs)` (the last joined with " and ", the others with ", "). B1 to B3, the booking pages (request and change views), the clinical advice notice, the case summary and the fit lines of an option ("Takes frailty and wound care") take their words from it. `is_need_words` accepts exactly what the table can write, so a raw code or free text cannot ride in a need field. One, two and three needs are boundary-tested. The labels are the owner's of DEC-062; `[ASSUMED]` for clinical safety and information governance review.

### DEC-1151 A closed prompt link says nothing beyond its state word; a closed booking link says more (KI-169, KI-648, KI-649, KI-664, KI-665; H-486, H-488, H-499)
Status: accepted. An expired capacity (L01) link must answer as an unknown one does, so `LinkAccess.closed` returns nothing. A closed booking link (L02) carries `kind: "booking"`, `reference`, `closedAt`, `confirmedAt`, `cancelledAt` and `coordinationPhone` (the tenant's current number, read when the page is opened, so a stale number is not shown), because its holder is told by the state word anyway and needs the number to phone. Every field is optional and shown only when sent; an unknown or another tenant's link says `expired` alone. A confirm answer carries `confirmedAt`; a decline or a withdrawal answer carries `respondedAt`.

### DEC-1152 The booking echoes B4, B5 and B6 go to an email or push reporter too, on the reporter's own channel (KI-357, KI-361; H-135)
Status: accepted. `echo_role` returns the role a request goes to (the lowest id) and its channel (text when none is named); the echo is rendered for that channel. Email and push templates carry no link and no patient data (an echo asks for nothing); the email has a one-line footer ("This email has no patient information. Replies to this address are not read."). `[ASSUMED]` wording, approved in writing before a real send (DEC-1100). `reporter_role_for_text` stays text-only for the K4 suspension notice.

### DEC-1153 The booking keeps what the pages and the card need; the delivery state of the request is a read-time output, never stored (KI-450, KI-451; H-493, H-494)
Status: accepted. `Booking` gains `phone_prompt_at` (the tenant's policy at the time of the request, so no page guesses 5 minutes), `request_message_id`, `acknowledged_at` and `acknowledged_by`. The reply-by time, the phone prompt and the withdrawal escalation use the tenant's `read_policy`, not the default. The first acknowledgement stands (a later one by another advisor changes nothing); a not-reached report is acknowledged like a withdrawal. `booking_to_fhir(booking, delivery_status=...)` adds `request-delivery` (queued, sent, delivered, failed) only when the booking is read, from the message's own state. The reporter's view of a Task drops `request-message`, `request-delivery`, `acknowledged-by` and `acknowledged-at` (the SPOA's own records). The advisor card says "Text delivered" only when the state is `delivered`, and a failed text brings the phone prompt at once.

### DEC-1154 `GET /fhir/Task` with no `code` searches bookings: one case's, or the open alerts (H-496, KI-451, B4 task 4)
Status: accepted. `?focus=ServiceRequest/<case id>` returns the bookings of that case and `?alert=open` the withdrawals and not-reached reports nobody has acknowledged; one parameter or the other and nothing else (anything else is a 400 that names the parameter, never the value). Advisor and clinician only (any other role reads the 404 of an unknown id). Both read the bound tenant's bookings only (every statement is a registered `NamedQuery` with `tenantId: $tenant`). It is a searchset Bundle of the same Tasks a single read gives.

### DEC-1155 The change token is issued in the unit that records the confirmation; a decline reason has a replay record (KI-483, KI-356)
Status: accepted. `RespondToBooking` takes an optional `ChangeLinkRequest` and issues the change link in its own unit (a crash cannot leave a confirmed booking with no change link, or a link for a booking that is not confirmed); the bearer is never stored in the replay record, so a replay returns no token. `SetDeclineReason` stores a fingerprint under a tenant-named key: the same command under the same key replays and changes nothing; another command under that key is a Conflict. A reason belongs to the phone's latest decline, not the first service in the list (KI-452); an expired booking older than the service's latest is named by its reference (KI-453).

### DEC-1156 The advisor's booking card comes back after a reload, and a request waits for that read (front end; closes the "booking card lost on reload" gap)
Status: accepted. `useBooking` reads `GET /api/bff/bookings?case=<ref>` once on mount and shows this service's newest booking. "Request booking" stays on screen while the read is out, but the request waits for it: if the read finds a booking, that is shown and nothing is posted. A read that fails leaves the card empty and the button on offer; the back end still refuses a second open request for the service (409), so nothing is doubled. A withdrawal the back end already holds an acknowledgement for does not open its alert again after a reload ("Withdrawn. Alert answered at 14:43."). The phone prompt and expiry minutes on the card are the booking's own, from its prompt time and reply-by time (5 minutes only for a booking made before the back end kept the prompt time).

### DEC-1157 A strip of open booking alerts above every advisor page (H-496)
Status: accepted. `app/(advisor)/advisor/layout.tsx` mounts `OpenBookingAlerts`, which reads `GET /api/bff/bookings?alert=open` on load and every 30 seconds and names each unanswered withdrawal or not-reached report (reference, the way to its case; no patient detail). It answers nothing: the answer is only given on the card (DEC-854). A read that fails says "We could not check for booking alerts." and keeps what was shown, so nothing shown never reads as "everything answered". The shift lead's escalation (R17) remains the backstop.

### DEC-1158 The booking pages' BFF: the link is read once, the answer is validated, a renewal carries a CSRF token, and the thank-you address holds no token (KI-651, KI-178, KI-179)
Status: accepted. The page reads the link once (LinkLoader no longer redirects into a second read). The BFF refuses an answer whose `action` is unknown, whose `value` is not a whole figure 0 to 999 (and only with `number`), or whose `reason` is not a code (only with the actions that take one), before the back end is asked. A closed link's answer carries `csrfToken`, an HMAC of the link made with the BFF's own secret; the renew route refuses (403) a request without it (nothing is stored; every closed or unknown link gets one, so it says nothing of which links exist). The thank-you page is `/l/thanks?d=<sealed>`: the detail (service, figure, time, next update) is encrypted by the BFF (`typ` `diucs-link-thanks`, 10 minutes); an address made by hand or with an expired seal says thank you and nothing about a figure.

### DEC-1159 The back end's body-type rule is modelled in the test harness, and a POST or PUT always names its body type (the 415 class)
Status: accepted. The real back end refuses a POST or PUT whose Content-Type is not `application/json` or `application/fhir+json` before any route runs, with or without a body (`BodyTypeMiddleware`; the paths under `/links/` and `/webhooks/` are exempt). The lead routes remind, test-prompt (no channel), invitation resend and switch-to-text, and the advisor acknowledge, posted with none, so they answered 415 on a real stack while every test passed. `test/backend-edge.ts` models the rule, `test/setup.ts` installs it on the MSW server and asserts after every test that no call the real back end would refuse was made; `test/backend-edge.test.ts` reads the back end's source and fails if the two differ. `fhirFetch` and `callBackend` now send the type on every POST and PUT. The e2e stand-in back end refuses the same calls.

## Hazards

- **H-800** (MEDIUM) A booking card that reloads empty offers a second request for a service that already has one. Control: the request waits for the case's read; a failed read still meets the back end's 409 for an open request; tests for both.
- **H-801** (HIGH) The strip of open alerts is empty because the read failed, and is read as "all answered". Control: a failed read says so and keeps what was shown; the shift lead's escalation (R17) is the backstop.
- **H-802** (LOW) Echo wording on email and push is `[ASSUMED]` and could be sent before it is approved. Control: no real send in tests or dev (recording fakes); approval in writing before a real send (DEC-1100).
- **H-803** (LOW) A text shown as "Text sent" for a booking from before the delivery state was read. Control: an unknown state reads as the plain "sent", never "delivered"; a failed text brings the prompt to phone at once.

## Known issues (with triggers)

- A booking made before the back end kept `phone_prompt_at` shows the 5-minute assumed prompt, whatever the tenant's policy then was. Trigger: a tenant changes its policy while requests are open.
- The open-alert strip polls every 30 seconds and does not listen to the live stream. Trigger: the shift lead wants an alert within seconds on every page.
- The strip lists alerts for the whole tenant, not only the advisor's own calls (the back end holds no owner of a case). Trigger: a tenant with many advisors asks for per-advisor alerts.
- Email and push echo templates are text-led and unbranded. Trigger: written approval of wording and design (DEC-1100, Q2).
- The decline-reason replay record is kept by the idempotency store's lifetime. Trigger: the store's retention is shortened below the SPOA's session length.

## Contracts

See `WB4-routes.md`.

## Not run

- Playwright: `e2e/links.spec.ts`, `e2e/booking.spec.ts`, `e2e/advisor.spec.ts` and the stand-in back end `e2e/support/advisor.ts` are updated, written, not run.
