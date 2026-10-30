# W7B fragment: back-end gaps found by the registration, criteria and lead front ends

Bundle W7B closes the back-end gaps in `W17`, `W18`, `W42`, `W43`, `W47`, `W23` to `W27`, `W54`,
`W28` to `W31` and the reporter fragments `W33` to `W38`, `W55` (the reporter token). Routes and
shapes: `W7B-routes.md`. Decision numbers are the block 790 to 809, hazards H-430 to H-449. No
migration was needed (0160 to 0169 are unused): every new stored value is an optional property of
an existing node (`changedOn`, `expiredCount`).

## Decision

DEC-790 (A2) · The back end issues the reporter token after a right text code; the BFF holds no
signing secret (TEN-043, DEC-134 item 2, DEC-136). 1. `POST /identity/registration/session` checks
the code and records it on the device in the same call the code route uses (`ConfirmDeviceByTextCode`),
then issues a back-end token (`aud diucs-api`) for role `reporter`: `sub` is the person (the
invitation's invitee, or the holder of the number), `services` the services that person holds an
active reporter post for, `device` the device the code was checked on, `tenant` and `epoch` the
Host's tenant's. 2. The tenant comes from the Host only (the one binder, `bind_host_tenant`); a body
that names a tenant, a role, a person or a service is a 400 and is never read. 3. [ASSUMED] the
token lasts 2 hours (a registration is filled in over a sitting; the applicant signs in again by
number and code). 4. The order is: tenant active (`may_issue`), the invitation open, then the code,
so a refused request never uses up a try. 5. A number nobody holds, or one that holds no reporter
post, answers as a code that needs asking for again: nothing says which numbers exist.

DEC-791 (A2) · An invitation is read and used by its link token, so the browser never needs the
number. `POST /identity/invitation` gives the state and, for an open link, the service name and the
last three digits; an unknown, malformed or other tenant's link is the one 404 (`EntryRefused`),
and an expired or used one is `{state}` only. `POST /identity/registration/code` sends the code to the
number the invitation holds. A returning applicant (the invitation has expired) signs in with their
mobile number and a code (`mobile` instead of `invitation`).

DEC-792 (A2) · A live PIN session is exchanged for a short back-end token (`POST
/identity/session-token`). [ASSUMED] 30 minutes: a token cannot be recalled, the session can, so the
app asks again and a signed-out person gets nothing. This replaces the BFF holding the session id
as a bearer (W33, W34, W35, W38, W55).

DEC-793 (A3) · R10 defects. 1. `open24h` is read (the route mapped camel to snake by lower-casing
capitals, which cannot give `open_24h`; it now maps by the step's own field names). 2. `"partial":
true` on `$draft` saves what is there: missing text is blank, a missing number is none; the step's
own checks say what is left (`incomplete`). A yes-or-no answer (`fixedSite`, `wanted`) is still
needed. A blank service name is the invitation's. A contact that is not a good number or address is
not stored. Submit is unchanged: every step must be complete. 3. `spokeToRole` is required only when
the call confirmed the number. 4. `Measure.OTHER` (`other`, unit "places", UCUM `{place}`) is a
measure a service can count; it is read like any other count. 5. No-reply and not-confirmed calls
record no role.

DEC-794 (A1) · The applicant reads their own registration: record (every step, with state, values
and problems), `my/registrations`, and the status page. Only a registration whose requester post
the reader holds; another person's and an unknown id are the same 404. A contact number or address
is never in a body: the last three digits and a flag stand for them.

DEC-795 (A1) · The reviewer queue has five tabs (waiting, sent-back, approved, live, not-approved);
an invited or drafting registration is not in it. The overview carries the five automatic checks,
who registered (the invitee's label and the organisation contact), the endings of the numbers the
applicant gave (so the lead can tell them from the register's), and the call-back words from the
tenant's wording: [ASSUMED] directory name is `referralSystemName` and pathway name is
`systemName`; with no wording both are null and the page names none. `numberToCall` is null: the
platform holds no register number for a service that is not yet listed, so the lead types it.

DEC-796 (A1) · The decision read gives `missing`, the four approvals with the screen's words, the
test notification mark, `canApprove` and a timeline (invited, submitted, review requested, test sent,
and the decision). The call-back and scope decisions are Provenance, which has no read: they are not
in the timeline (known issue).

DEC-797 (A4) · Test notification, review request and confirm details are marks on the draft (keys
`test_notification`, `review_request`, `details_confirmed`, as the review notes and lookups are), so no
new record is needed. The test is the new message `T1` (text, email, push), queued sealed to the
applicant's post by the channel they chose; it has no link and asks for nothing, so it cannot be
answered with a number. [ASSUMED] one test a minute per registration. The lead may send it again.
Confirm details moves reverify to live. `$start-review` and `$explain-check` routes are added: the
use cases existed with no route.

DEC-798 (A4) · The address lookup is a route over the existing `Geocoder` port (fake in tests; the OS
Places adapter when a key is configured, else `NoGeocoder`, which finds nothing, by design). A lookup
that cannot answer is a 503, never an empty list. The postcode is never logged.

DEC-799 (B) · `GET /criteria/{service}` gives the current version, the draft (a version the approver
sent back, status draft) and the change waiting, whether the review is overdue and since when (the
review-by date, judged on the London day), the shift lead's phone (the tenant's
`shift-lead-escalation` contact, never a default) and whether the reader holds the owner post. An
owner reads only a service they hold the criteria-owner post for. `GET .../pending` tells the change
in words against the current version with its reason, the author's post and `isAuthor`.

DEC-800 (B) · A criteria version keeps `changedOn` (the London day it was proposed, and again the day
it was approved); the history gives it with `authorRole` (the author's label). A version stored
before this has none.

DEC-801 (B) · The author may not approve their own change; the read says `isAuthor` so the page can
say so, and the back end still refuses an author who sends the request.

DEC-802 (C) · The lead overview reads the board (`QueryBoard`), so a status here is the status everywhere
else. Chasing: not-updated with a missed prompt, not suspended; each shows the prompt and the three
later steps with whether each ran (from the scheduled work; a step with none shows when it would
have run, not done). Getting old: reported more than the stale limit ago, not yet overdue, not
suspended. Covering: posts a cover is holding. The tenant's own policy and zone are not read yet
(as the board does not).

DEC-803 (C) · The reporter post of each service is listed with its role id (what `$change-number` and
`$remove` take), the channel, the last four digits and the cover. A cover's number is now kept in the
protected contact store under `cover-<role id>`, and an until-changed change gives the new post its
number (the change used to keep the hash only, so the lists could not show the ending).

DEC-804 (C) · Suspension state: whether, since when, the reason, how many requests it expired
(`ServiceFlag.expired_count`, kept at the suspension) and the register number to phone (the work
phone the service is listed with). The register number is a directory number, not a person's, and is
the one number given whole because the lead phones it. The closed report flags are listed by
`status=closed` (checked and accepted), newest closed first.

DEC-805 (C) · Phones are grouped by the phone that holds each service now (a cover holds the service
while it runs), shown as the last three digits; the flag above three services is the page's.
`lastSeen` is the latest report time of the phone's services (not device activity).

DEC-806 (C) · The set-up steps of an invitation are judged from what is stored: a text code checked on
a device, the channel chosen in the registration, a device set up, a push subscription, a PIN, and the
service's first report. One new statement lists a practitioner's devices (`Q-DEVICE-LIST`) and one
the invitations (`Q-REG-INVITATIONS`).

DEC-807 (C) · The reminder runs the missed-report ladder's reminder step that is scheduled for the
service, now (the step the scheduler would run: C8 with a fresh link). With none scheduled, or one
that does nothing, it is a 409, so the lead is never told a reminder went when it did not.

DEC-808 (C) · The lead's test prompt sends `T1` to the service's reporter post by its channel (or the
one named), to the post's own number. [ASSUMED] one a minute per service (a processed marker).

DEC-809 (C) · Switch to text sets the invited person's post to text when a mobile number is held;
resend is routed to `ResendInvitation` (U24).

## Hazards

| id | hazard | source | control | tasks | verified by | status |
|---|---|---|---|---|---|---|
| H-430 | A token issued from a code names the wrong person, service, device or tenant | A2 | claims come from the invitation or the number's holder, the services from the person's posts, the tenant from the Host; a body that names any is a 400 | W7B A2 | `test_routes_registration_session.py` (claims, services, refusals) | written, unit-tested |
| H-431 | An invitation link or a number is probed through the sign-in routes | A2 | one 404 for an unknown, malformed or other tenant's link; a number nobody holds answers as a wrong code; the address is counted first | W7B A2 | `test_routes_registration_session.py` | written, unit-tested |
| H-432 | A part-filled draft is read as complete, or is submitted | A3 | the record gives a state per step from the step's own checks; submit is unchanged | W7B A3 | `test_routes_registration_defects.py`, `test_routes_registration_views.py` | written, unit-tested |
| H-433 | A full mobile number reaches a response | A1, C | endings only (3 or 4 digits); no number in an audit entry | W7B | `test_routes_registration_views.py`, `test_routes_lead_views.py` | written, unit-tested |
| H-434 | A test message is taken for a capacity prompt and answered with a number (a report) | A4, C | `T1` has no link, no figure and asks for nothing; a minute between tests | W7B | `test_test_message.py`, route tests | written, unit-tested |
| H-435 | A reminder is reported as sent when none was | C | a reminder runs only when one is scheduled; otherwise 409 | W7B C | `test_routes_lead_views.py` | written, unit-tested |
| H-436 | A chase list that failed to read shows as "nothing to chase" | C | the read answers an error, never an empty list; the empty answer is the full shape | W7B C | `test_routes_lead_views.py` | written, unit-tested |
| H-437 | A suspended service is chased, or looks active | C | chasing and getting-old skip it; the suspension read says so | W7B C | `test_routes_lead_views.py` | written, unit-tested |
| H-438 | Another tenant's registration, criteria, service, phone or invitation is read | A1, B, C | tenant-scoped statements; the 404 of a record not there | W7B | `test_routes_w7b.py` (two tenants), generated `test_tenant_isolation.py` | written; run once (see report) |
| H-439 | A criteria history date is wrong or blank without saying so | B | a version stored before the date was kept has `changedOn` null, not a guess | W7B B | `test_criteria_change_date.py` | written, unit-tested |

## Known issues

| task | what | where | trigger |
|---|---|---|---|
| W7B A1 | The organisation name and ODS code the applicant sees locked are not on any read (the platform does not hold them before the application) | `GET /registrations/{id}/record` | the organisation step |
| W7B A1 | `contactRole`, "part of a larger organisation", the site ODS code, specialty, appointment and notes, cover number and bed types have no field in R10 and are not saved | `registration_draft.py` | any step save |
| W7B A1 | `numberToCall` (the register number for the call-back) is null: no source for a service that is not yet listed | `registration_views.py` | the call-back |
| W7B A1 | The decision timeline has no call-back or scope-decision entries (Provenance has no read) | `registration_views.py` | the decision step |
| W7B A4 | With no OS Places key the address lookup finds nothing (`NoGeocoder`, by design) | `bootstrap/container.py` | a process with no key |
| W7B A2 | A returning applicant after the invitation expired signs in by number: the number must be a practitioner's with an active reporter post | `registration_session.py` | an expired invitation |
| W7B B | An owner reads a service only if their token's person holds the criteria-owner post (staff tokens carry a derived subject, DEC-524); an owner with no practitioner record gets 404 | `criteria_views.py` | first owner sign-in |
| W7B B | A criteria version stored before W7B has no change date | `criteria_repository.py` | the history of an older service |
| W7B C | The reminder and the resend need a link host for the tenant: production has `_no_link_host` until TEN-028 | `bootstrap/container.py` | a reminder in production |
| W7B C | The test prompt and prompts in general go to the post's own number: a cover's number (`cover-<role id>`) is kept and shown but the sender does not read it | `message_senders.py` | a cover is running |
| W7B C | A cover made before the number was kept shows `----` for its ending; a suspension made before the count was kept has `expiredRequests` null | `lead_views.py` | older data |
| W7B C | The invitation set-up steps are approximations (for example "installed" is any active device) | `lead_views.py` | the tracker |
| W7B C | The lead overview and the board read the platform's default policy and London, not the tenant's own (as the board does) | `lead_views.py` | a tenant with its own policy |
| W7B C | Two-tenant integration tests for the four host-bound sign-in routes are not written (the unit tests cover them); the generated statement test covers the two new statements | `tests/integration` | a graph-level change to the invitation lookup |

## Contracts

- `application/use_cases/registration_session.py`: `ReadInvitation`, `RequestRegistrationCode`, `RegistrationSignIn`, `ExchangeReporterSession`, `issue_reporter_token`, `number_ending`, `reporter_services`.
- `application/use_cases/registration_views.py`: `GetMyRegistration`, `ListMyRegistrations`, `GetRegistrationStatus`, `ListRegistrationQueue`, `GetReviewOverview`, `GetDecision`, `SendTestNotification`, `RequestRegistrationReview`, `ConfirmRegistrationDetails`, `QUEUE_TABS`.
- `application/use_cases/criteria_views.py`: `GetCriteriaOverview`, `GetPendingChange`, `describe_changes`. `criteria.py`: `author_label`; `CriteriaVersionView.changed_on`, `.author_role`.
- `application/use_cases/lead_views.py`: `GetLeadOverview`, `ListReporters`, `GetSuspension`, `ListPhones`, `ListInvitations`. `lead_actions.py`: `RemindService`, `SendLeadTestPrompt`, `SwitchReporterToText`.
- Routes: `routes_registration_session.py`, `routes_registration_views.py`, `routes_criteria_views.py`, `routes_lead_views.py`; `routes_admin.py` lists closed flags; `routes_registration.py` takes `partial` and `callback_command`.
- Domain and ports: `Measure.OTHER`, `MessageId.T1`, `ServiceCriteria.changed_on`, `ServiceFlag.expired_count`, `DeviceFacts`, `DeviceRegistry.devices_of`, `RegistrationRepository.list_invitations`, `ServiceRepository.work_phone`, `FlagRepository.report_flags_with_status`.
- Statements: `Q-REG-INVITATIONS`, `Q-DEVICE-LIST` (each registered, with a scenario that marks the tenants apart).
- Test support (new files only): `tests/support/w7b_rig.py`, `tests/support/w7b_roles.py`.

## Tenant pending

- None: both new statements are converted (`tenantId: $tenant` on every node, with scenarios). The sign-in routes bind the tenant from the Host through `bind_host_tenant`.

## Assumed

- Registration token 2 hours; PIN-session token 30 minutes; one test notification a minute per registration; one lead test prompt a minute per service.
- Call-back words: directory name is `referralSystemName`, pathway name is `systemName`.
- The ending of a number: 3 digits for a person's phone on a page, 4 for a reporter's.
