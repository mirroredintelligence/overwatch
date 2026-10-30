# W7C fragment: reporter app routes (back end)

The back-end gaps the reporter-app front end (W32 to W38, W55) reported against the real API, closed
(W7C-1 to W7C-4). Decision numbers DEC-810 to DEC-826, hazards H-450 to H-459, migrations none (0170
to 0179 unused: the one new statement needs no schema). The exact paths and shapes are in
`W7C-routes.md`. The issuing of a reporter bearer token after a verified code and PIN is W7B's: every
route here assumes a reporter token (role `reporter`, the person as `sub`, the phone as `device`) and
checks the person and the device on every use (`CheckReporterAccess`, R11).

## Decision

1. **DEC-810 Invitation lookup.** `GET /invitations/{token}` needs no token but the invitation's, and the
   tenant is the host (DEC-134 item 3). It answers the service, the post label, the masked number and the
   expiry, and nothing of the person. An unknown, malformed, expired, used, another tenant's or another
   purpose's token, and a host no tenant owns, all get the one answer `410 {"state":"expired"}` (the front
   end words "used" and "expired" alike, W33). The number is shown as its first two and last three digits
   (`07xxx xxx456`); a value that is not a UK mobile shows no digit. 60 reads per address in 10 minutes
   [ASSUMED]. The access log hides the token (`/invitations/` joins `/links/` in `RedactLinkTokens`).
2. **DEC-811 Codes without a number in the browser.** The browser at set-up holds a token or a device id,
   never a number. `POST /identity/invitations/{token}/code` and `/code/verify` run the number-based use
   cases (U25, U32) with the keyed hash of the number the invitation was sent to (`KnownPhoneHash`);
   `POST /identity/device/code` and `/device/code/verify` do the same for the owner of a device. A token or
   a device that cannot be used gets a stand-in hash no practitioner holds, so the request does the same
   work and gets the same answer as a real one (H-96, H-451). The request is always 202; a wrong code names
   the tries left (`triesLeft` on the 400), as the front end's set-up and locked screens need.
3. **DEC-812 Device codes are for the 30-day check and a PIN reset only.** Purposes `reverify` and
   `pin-reset`; a code of another purpose does not verify a device. A right code stamps the device
   (`RecordTextCodeVerified`), so the PIN routes that follow work as before.
4. **DEC-813 Channel before sign-in.** `POST /identity/channel` records `app`, `text` or `email` for a
   device a text code verified in the last ten minutes (the window of a PIN), on every reporter post the
   person owns; the set-up channel step and the locked PIN's "text me" both call it, and neither has a
   session. Any device that cannot be used is one `403`. `app` is the push channel. `POST
   /reporter/channel` is the same change behind a session (settings); `email` needs an address on record
   for every post.
5. **DEC-814 What a reporter holds is read from the graph.** Every `/reporter/...` route asks the graph which
   services the person holds a reporter post for now (their own, and those they cover) and ignores the
   token's `services` claim, so a cover that began after the token was made takes effect at once. A service
   the person does not hold, an unknown one and another tenant's are one `404`. A role other than
   `reporter` is the `404` of every refused role; a phone that was signed out is `401` at once.
6. **DEC-815 Service rows.** A row is `due` when the service's latest due time (the tenant's zone and policy,
   DEC-353) has had no report since, `paused` when the service is suspended, `confirmed` otherwise;
   a service that is not live is not listed (a reporter invited to a service not yet live sees it only on
   the set-up summary). When two or more rows are due they carry the letters of a grouped prompt (D28).
   `pendingAcceptance` is always false (see known issues).
7. **DEC-816 A report from the app.** Confirm, number and closed go through `ReportCapacity` and
   `ConfirmCapacity` (source `app`) under the same reply policy as a text or a link: a figure out of the
   usual range is asked for once (`outOfRange`) and recorded, with a flag, on the second send with
   `confirmOutOfRange`; a third confirm in a row is `confirmLimit` (409); a Y with no figure, or on a
   figure older than two hours, or after a number was written, is `sendNumber` (409, with the reason), so
   a Y never makes an old figure current (H-31, H-32, H-454). The app is open whenever the reporter is in it:
   there is no prompt to be late for, and the figure is judged at the time of the request. An
   `Idempotency-Key` is required (the use case's own replay record and the route's replay cache).
8. **DEC-817 History** is the reports of the tenant's local day, newest first, numbers and confirms, and
   only `day=today` exists.
9. **DEC-818 Batch.** Only confirms, one to ten different services; every service must be the reporter's or
   nothing is written (one `404`). Each confirm then runs on its own (a digest of the key and the service),
   so one service that must send a number does not stop the others and a repeat repeats nothing (H-458).
10. **DEC-819 Settings** show the channel, the masked number, the masked cover (only while a cover runs),
    the whole days until the text code is next needed (the device's last verification and the tenant's
    period) and the other phones that are signed in. The count is the one new statement,
    `Q-DEVICE-ACTIVE-COUNT` (read, tenant on both nodes, a Scenario with the same ids in both tenants), behind
    `DeviceRegistry.count_active`.
11. **DEC-820 A reporter hands their own posts to a cover.** Amends the letter of DEC-136 item 5 ("the
    provider's own lead changes reporter numbers and cover") within its intent (no cross-tenant write): a
    reporter may set a cover on the posts they own, for `tonight`, `this-week` (the default when none is
    named) or a `date`, at most a fortnight ahead [ASSUMED], ending 23:59 in the tenant's zone. The cover
    practitioner is found by the number's hash or made; the audit holds the hash, never the number; the
    number is kept as the post's cover contact `cover-<role id>`, so the post's own number is not
    replaced. A post already handed on can be handed to another cover; a post the reporter only covers
    cannot be passed on (H-456). The shift lead's own change (U16) is unchanged.
12. **DEC-821 Booking read by reference.** The notification carries the four-digit reference, not the Task
    id. `GET /reporter/bookings/{reference}` maps it to the tenant's booking (`BookingRepository.
    get_by_reference`) for a service the reporter holds, and answers the reference, the Task id, the
    service, the age band, the need, the urgency, reply-by, the status, the SPOA phone and whether the
    reporter holds more than one service; never the case, the postcode or the requester. A reference that
    is not four digits, unknown, another tenant's or for another service is the one `404` (H-455). The
    status is one of `requested`, `confirmed`, `declined`, `expired`; every closed state the screen cannot
    answer is `expired`, and `bookingStatus` holds the exact word. `spoaPhone` is null when the tenant has
    set none (never a default).
13. **DEC-822 Booking decision by reference.** `POST /reporter/bookings/{reference}/respond` runs
    `RespondToBooking` (source `app`, as `$respond` and the link do); a booking already answered is `409`;
    the decline reason is one of the four of the screen.
14. **DEC-823 Answer to a service the lead added.** `accept: true` is recorded (audit) and changes no post;
    `accept: false` ends the reporter's own post on that service now. Only a post the reporter owns can be
    answered.
15. **DEC-824 Push key and test push.** `GET /public/push-key` serves the platform's VAPID public key from the
    secret `webpush-vapid-public-key` (not a secret, platform-wide like the private key, DEC-340), tenant by
    host, `no-store`, `Vary: Host`; 503 when it is not configured. `POST /reporter/push-test` queues a
    `K3` push to the reporter's own post through the sealed send (DEC-116): a title and a body that name no
    service, figure or person, no link; `409 no-subscription` when no subscription is saved; three per ten
    minutes per person [ASSUMED] (H-457).
16. **DEC-825 The SPOA number on the lost-phone wait.** The `200` of `POST /identity/new-phone/verify` carries
    `spoaPhone`, the tenant's coordination phone or null (H-459); a refused code carries nothing.
17. **DEC-826 Set-up summary.** `GET /reporter/setup-summary` names the first post's service by name (a service
    not live yet is allowed), how the reporter is contacted, the masked number, the next update due and the
    days until the text code is needed again.

## Hazards

| id | hazard | source | control | tasks | verified by | status |
|---|---|---|---|---|---|---|
| H-450 | An unknown invitation token is told apart from an expired or used one, or a whole number is shown | invitation lookup | one 410 body for every unusable token and an unknown host; the number is masked; no token, hash or number in a body or log | W7C-2 | test_routes_reporter_setup.py (unusable cases, redaction, log test), test_redact_invitation_paths.py | controlled; run |
| H-451 | A code request or a code check says whether an invitation or a device is real | set-up and device codes | a stand-in hash for anything unusable, the same work and answer (202; the same 400 for a wrong code) | W7C-2 | test_routes_reporter_setup.py (known and unknown get the same answer), test_routes_reporter_tenants.py | controlled; run |
| H-452 | A reporter reads or changes a service they do not hold, or one of another tenant | every reporter route | the graph is asked what the person holds at the time of the request; not held, unknown and another tenant's are one 404; the token's claim is not read | W7C-3 | test_routes_reporter.py (role matrix, not held, token claim wider than the graph) | controlled; run |
| H-453 | A reporter of one tenant reads, writes, covers or books in another's graph | all new routes | the tenant is the token's or the host's; two-tenant tests with the same ids, device, person and booking reference | W7C-2, W7C-3 | test_routes_reporter_tenants.py; test_tenant_isolation.py for `Q-DEVICE-ACTIVE-COUNT` | controlled; run |
| H-454 | A confirm makes an old figure current | report from the app | the reply policy of a text or a link; stale, no figure, a number since, the limit of two | W7C-3 | test_routes_reporter.py (confirm limit, stale, no figure) | controlled; run |
| H-455 | A booking reference opens another service's or tenant's booking, or shows the patient | booking read and decision | the booking is read in the tenant for a service the person holds; age band, need and urgency only | W7C-3 | test_routes_reporter.py (booking tests), test_routes_reporter_tenants.py | controlled; run |
| H-456 | A cover number gives a stranger reporting access, or the number is kept in clear in the graph or a log | cover | own posts only, at most a fortnight, ends 23:59; hash in the audit; number only in the protected contact store; no number in a body or a log | W7C-3 | test_routes_reporter.py (cover tests, log test) | controlled; run; see known issue W7C-K2 |
| H-457 | The test push buzzes a phone or leaks service data | push test | three per ten minutes; fixed words; no link; needs a saved subscription | W7C-3 | test_routes_reporter.py (push tests) | controlled; run |
| H-458 | A batch confirms a service the reporter did not answer for, or twice | batch | confirms only, owned services only (else nothing is written), one key per service | W7C-3 | test_routes_reporter.py (batch tests) | controlled; run |
| H-459 | The lost-phone wait shows another tenant's number, or a default | SPOA number | the number is the bound tenant's coordination phone or null | W7C-4 | test_routes_lost_phone.py | controlled; run |

## Known issues

| ID | what | where | trigger |
|---|---|---|---|
| W7C-K1 | `pendingAcceptance` is always false: a service the lead adds to a reporter has no stored "waiting for the reporter's answer" state (it would be a new property on the post and a new statement), so the screen `/app/services/[id]/added` has nothing that leads to it | `reporter_app.py` | the lead-adds-a-service flow |
| W7C-K2 | The text senders address a message by the recipient post's own stored number (`contacts.get_phone(role)`), so during a cover the prompt text still goes to the original number while the link carries the cover's hash; the cover number is kept as `cover-<role id>` for the sender to read. This predates W7C (U16's cover has the same gap) | `adapters/inbound/workers/message_senders.py` | a cover set by a reporter or a lead |
| W7C-K3 | `tests/support/registration_rig.py` has a fake `DeviceRegistry` without `count_active`; it is not called there, so nothing fails, but mypy on the tests would flag it | `tests/support/registration_rig.py` | a type check of the tests |
| W7C-K4 | `/reporter/...` routes take the reporter token; the issue of that token after a verified code and PIN is W7B's. Until it lands the integration tests mint it with `issue_test_token` | `routes_reporter.py` | none until the front end runs against the real back end |
| W7C-K5 | `exec` role (the executive's app) has no `/reporter/...` routes: the exec set-up skips the channel step and has no services | `routes_reporter.py` | an exec who opens the reporter app |
| W7C-K6 | The set-up summary uses the first post by service name; a reporter invited for two services at once is shown one | `reporter_app.py` | an invitation for several services |

## Contracts

- Rules: `domain/rules/reporter_app.py` (`mask_mobile`, `channel_for`, `channel_word`, `cover_end`,
  `local_day_bounds`, `RowState`, `assess_row`, `check_report`, `MAX_COVER_DAYS`).
- Use cases: `application/use_cases/reporter_setup.py` (`InvitationReader`, `DeviceReader`, `KnownPhoneHash`,
  `stand_in_hash`, `SetDeviceChannel`, `CoordinationPhone`, `InvitationUnusable`);
  `reporter_app.py` (`held_services`, `ReporterReader`, `ReporterReporter`, `ReporterSettingsWriter`);
  `reporter_booking.py` (`ReporterBookingReader`, `ReporterBookingResponder`, `app_status`);
  `reporter_push.py` (`SendPushTest`, `NoPushSubscription`).
- Port: `DeviceRegistry.count_active(practitioner_id) -> int`; statement `Q-DEVICE-ACTIVE-COUNT`.
- Routes: `routes_reporter_setup.py`, `routes_reporter.py` (paths and shapes in `W7C-routes.md`); `routes_identity.py`:
  `spoaPhone` on the `new-phone/verify` 200.
- Secret: `webpush-vapid-public-key`.

## Tenant pending

None. The one new statement is converted (`tenantId: $tenant` on both nodes, with a Scenario). Every route
binds the tenant from the token or from the host, and the replay keys, rate-limit keys and codes carry it
through the existing seams.

## Assumed

- 60 invitation reads per address in 10 minutes; at most 14 days of cover and "this week" as the default
  cover; three test pushes in 10 minutes; at most ten services in a batch (the phone load limit, D28).
- The app judges a confirm at the time of the request, not at a prompt's time.

## Not run

- Nothing is unrun: the integration files below were run, once each, on the shared Neo4j and the compose
  Redis (counts in the report). The front end's BFF has not been moved onto these routes (W7C-routes.md says
  how); Playwright against the real back end is the orchestrator's.

## Zone ratchet

No new entry. The new use cases read the tenant's zone (`DirectoryZones`) and policy (`read_settings`)
and pass them to the rules; none calls a time-of-day rule with the default zone.
