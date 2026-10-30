# W8C fragment: registration and review wired to the back end (W23 to W31)

Branch task/build-W8C, merged with integration/build (no conflicts beyond the expected). The stubs in
the applicant, reviewer and criteria areas are replaced by the back end's real routes. Commits are
red/implement pairs where the rule was followed; two back-end and two front-end changes were made in
one commit (see "Commits" below).

## Decision

### DEC-900 The applicant signs in from the invitation: the number is never typed (W23)
1. The registration page reads the link first (`POST /api/bff/identity/invitation` -> back end
   `POST /identity/invitation`), shows the service and the last three digits of the number the code
   goes to, and asks for a code (`POST /api/bff/identity/code` -> `POST /identity/registration/code`,
   body `{invitation}` only). The check is `POST /api/bff/identity/code/verify` `{code}` ->
   `POST /identity/registration/session` `{invitation, code, deviceId}`. The invitation and the device
   come from the sealed pending cookie, never from the body.
2. The mobile field of W23 is removed. The back end sends the code to the number the invitation holds
   and offers no mobile-typed route for a new applicant; the typed number could only disagree with it.
   The page holds the three digits and never the number. Departure from the W23 screen wording
   ("Enter your mobile number"), recorded here.
3. The back end's `POST /identity/invitation` 404 (unknown link) is answered 404 `not-found`; expired
   and used links are 200 `{state}` and the page says so with no send button.

### DEC-901 The sign-in answer carries the host's tenant; the session carries tenant and host (back end + W23)
1. Back end (one line, `routes_registration_session.py`): the 200 answer of
   `POST /identity/registration/session` gains `"tenant"`, the tenant the host bound, as the PIN answer
   already does (F6A). Test: `tests/unit/adapters/inbound/fhir_rest/test_routes_registration_session.py`.
2. The BFF seals a reporter session only when `tenant` is a tenant id, the request host is a host, the
   token names a subject, and the expiry is a future instant within twelve hours (lib/register/signin.ts
   `reporterSessionFor`, the same rule as the staff exchange). `tenantId` = the answer's tenant, `host` =
   the request's Host, `services` = the invited service, `sub` = the token's subject, `device` = the
   pending device, `backendToken` = the token. The browser gets the registration id only.
3. Anything the BFF cannot vouch for is 503 and no session is written (fail closed). Negative tests:
   missing tenant, bad tenant, no host, unreadable token, expiry in the past, not a date, more than
   twelve hours, back-end 503, unreachable back end.

### DEC-902 A wrong code shows no count of tries; a throttle says "Too many attempts"
The registration session answer gives no tries left (the device route does). So the page says
"That code is not right. Check it and try again." (W23 said "You have 3 tries left"). A 429 from the
back end is a rate limit on the address, not a locked code, so it reads "Too many attempts. Try again
later." (W23 said "Too many wrong tries. Ask for a new code.").

### DEC-903 "My services" states from the registration status
live and paused are Active; reverify is Review due; submitted, in-review, needs-changes and approved
are Pending approval with the words the page shows; not-approved is listed as Not approved; draft and
invited are not listed (nobody has sent them). A registration the back end answers in a status the
BFF does not know is left out, never shown as active.

### DEC-904 The applicant's record is passed on in the screens' names, with no number
`viewFromRecord` (lib/register/applicant.ts) keeps each step's state, values and problems. A stored
phone is never passed on: the page gets `contactPhoneEnding` (three digits). The review rows are
derived from the record's step states (the back end has no separate applicant review route): one row
per step that is complete or needs attention, with the problem messages as the words. The applicant's
status is `statusFrom`: the note as a one-item list with its sender's role, the details the page shows.

### DEC-905 "Save draft" is a partial $draft
Every step's Save draft sends `partial: true`; the BFF passes it to `PUT /fhir/Task/{id}/$draft`
and answers the back end's `incomplete` list with the page's field names. Continue checks on the
screen and sends the full step. A partial save has no client validation (W54).

### DEC-906 Fields the back end cannot keep stay on screen and are never sent
Never sent by the BFF (the step mappers drop them, tested): the organisation's contact role
(`contactRole`) and part-of answer (`partOf`), the location's site ODS code (`siteOdsCode`) and the
address id (UPRN, `addressId`; the address label is sent), the reporting screen's bed types and cover
number, and the service screen's specialty and notes. The contact role stays required on screen
(W54 says so) although it is not stored: known issue K-W8C-3.

### DEC-907 The reviewer's queue, overview and decision are the back end's answers, mapped
The queue uses the back end's tabs (`waiting`, `sent-back`, `approved`, `live`, `not-approved`), its
counts and its rows; the front end's old tabs (to-review, go-live, done) are gone and the default is
waiting. The overview's checks come from the back end's review; the manual checks are done or not
done from the back end's flags (criteria done when approved; the waiting state is not given by the
back end). The decision read gives what is missing, who has approved (approvals done), the test
and the timeline. Mapping in lib/registration/mapping.ts, read by the BFF; the browser parsers read
the page shapes.

### DEC-908 The criteria overview and the waiting change are mapped to the criteria pages' shapes
`criteriaOverviewFromBackend` gives the current version's values as codes (the back end's `{code,label}`
items are reduced to the code), the review date, the shift lead, the overdue day, and a draft: a version
the approver sent back is `sent-back` with its reason; a waiting change is `waiting` with its version
and day, and no values (the back end gives none in the overview; the approval page has them).
`pendingFromBackend` gives the change as words, the reason, the author's role and whether the caller
wrote it; with no earlier version it gives the whole criteria. No author's name or id is kept. The
approval uses the pending read's `criteriaId` (`$approve` and `$send-back` take it).

### DEC-909 The lead's test notification is served (W29)
`POST /registrations/{id}/test-notification` is the lead's and the applicant's route on the back end;
the BFF no longer answers not-supported for the lead.

### DEC-910 The organisation's name and ODS code are typed by the applicant (W54)
The back end holds no organisation fact from the invitation: the invitation gives the service, and the
organisation is the step's own values (`name`, `odsCode`), which the back end checks for shape and the
reviewer's automatic checks (CHECK_ODS, CHECK_NAME) confirm. So the W54 locked rows for organisation
name and ODS code are inputs, and only the service is locked (it is set by the shift lead). Departure
from W54's locked-invitation wording, recorded here.

## Hazards

| id | hazard | source | control | tasks | verified by | status |
|---|---|---|---|---|---|---|
| H-570 | The applicant types the wrong organisation name or ODS code | DEC-910 | the reviewer's automatic checks CHECK_ODS and CHECK_NAME; the call-back uses the register number only | W23, W54, W28 | route tests (ods required); reviewer's checks (back end) | open, mitigated by review |
| H-571 | A session is sealed for a tenant or host the BFF cannot vouch for | DEC-901 | reporterSessionFor fails closed; route writes nothing on 503 | W23 | verify route negative tests; signin unit tests | controlled |
| H-572 | A phone number reaches a browser or a log from the record or the status | DEC-904 | viewFromRecord keeps the last three digits only; statusFrom keeps no phone; overview keeps no applicant number | W24 to W29 | applicant, status and overview tests (leak guards) | controlled |
| H-573 | The invitation token is in the URL of the sign-in page | W23 spec (invitation link) | link token only; never shown; the BFF reads it in a body | W23 | page test "never renders the invitation token" | accepted (the link is the sign-in) |
| H-574 | A call-back is recorded against a number the back end did not give | DEC-907 | the call-back screen records nothing when no register number is held | W29 | CallBackCheck (existing tests) | controlled; see K-W8C-2 |
| H-575 | An applicant believes a partial save was checked | DEC-905 | the saved notice says "Draft saved"; Continue is the only check | W54 to W26 | OrganisationForm save tests | controlled |
| H-576 | An approver sees no values for a waiting change in the overview | DEC-908 | the overview says the change is waiting; values come from the pending read | W30, W31 | criteria mapping tests | controlled |
| H-577 | A field on screen is taken to be saved when the back end keeps none of it | DEC-906 | the BFF never sends it; known issue lists each | W24 to W26, W54 | step-save tests (contact role not sent) | open, see K-W8C-3 |

## Known issues

| id | what | where | trigger |
|---|---|---|---|
| K-W8C-1 | No tries-left count on a wrong code (DEC-902) | `app/api/bff/identity/code/verify`, `components/register/SignInForm.tsx` | the registration session answer carries `triesLeft` |
| K-W8C-2 | The call-back number is not given: the overview's `callBack.numberToCall` is null, so the call-back cannot be recorded (the screen says "Not on the register") | `components/lead/registration/CallBackCheck.tsx`, `lib/registration/mapping.ts` | the back end serves the register number on the overview |
| K-W8C-3 | Contact role and part-of are on screen and never stored (required on screen for the role) | `components/register/OrganisationForm.tsx` | the back end keeps the organisation's contact role and part-of |
| K-W8C-4 | Site ODS code and UPRN are not kept; the address label is | `LocationForm.tsx`, `lib/register/draft.ts` | the back end's LocationStep takes them |
| K-W8C-5 | Specialty, notes (service), bed types and cover number are on screen and never stored | `ServiceForm.tsx`, `ReportingForm.tsx` | the back end keeps them |
| K-W8C-6 | The note's sender shows the role only, with no time (the back end gives no time for the note) | `components/register/status/NeedsChanges.tsx` | the back end gives `noteFrom.at` |
| K-W8C-7 | The overview's waiting change has no values (the approval page has them) | `lib/criteria/mapping.ts`, `components/owner/CriteriaFlow` | the back end's overview gives the pending values |
| K-W8C-8 | `test/guards/eslint-rules.test.ts` ("no rule fires on the application") times out at 120 s under full-suite load (it passes alone) | `frontend/test/guards/eslint-rules.test.ts` | the lint of the whole app is faster, or the test gets a longer timeout |

## Contracts

- BFF (new): `POST /api/bff/identity/invitation` (body `{inviteToken}`; answers `{state, serviceName, numberEnding, expiresAt}` or `{state}`; 404 unknown, 503).
- BFF (changed): `POST /api/bff/identity/code` body `{purpose:'registration', inviteToken}` (no number); `POST /api/bff/identity/code/verify` body `{code}` (no invitation, no number; answers `{registrationId}` and seals the session).
- BFF (changed): `GET /api/bff/registrations/[id]` (applicant) answers `{id, status, serviceName, steps}` (no `invitation`); the lead's `GET` answers the overview (`lib/registration/mapping.ts`).
- BFF (changed): `GET /api/bff/registrations?tab=` answers `{tab, counts, tabs, items}`; tabs `waiting | sent-back | approved | live | not-approved`.
- BFF (changed): `PUT /api/bff/registrations/[id]/steps/[step]` accepts `partial: true`; answers `{status, incomplete?}`; organisation takes `name`, `odsCode`.
- BFF (served): `GET …/status`, `GET /api/bff/registrations/mine`, `GET …/review`, `POST …/test`, `POST …/review-request`, `POST …/confirm-details`, `GET /api/bff/addresses`, `GET …/decision`, `GET /api/bff/criteria/[serviceId]`, `GET …/pending`.
- Back end (changed): `POST /identity/registration/session` answers `tenant`.
- Back-end routes called (mounts checked against app.py): root (no `/fhir`): `/identity/invitation`, `/identity/registration/code`, `/identity/registration/session`, `/registrations/{id}/record|status|overview|decision|test-notification|review-request|confirm-details`, `/registrations?tab=`, `/my/registrations`, `/addresses`, `/criteria/{id}`, `/criteria/{id}/pending`. Under `/fhir`: `/fhir/Task/{id}/$draft|$submit|$callback|$scope-decision|$approve|$send-back|$not-approve|$set-live`, `/fhir/Basic/{id}/$approve|$send-back`, `/fhir/HealthcareService/...`. (The root routes go through `fhirFetch` with `root: true`.)
- Lib: `lib/register/signin.ts` (`reporterSessionFor`), `lib/register/applicant.ts` (`viewFromRecord`, `reviewRowsFrom`, `myServicesFrom`, `statusFrom`, `addressesFrom`), `lib/register/backend.ts` (`readInvitation`, `requestRegistrationCode`, `verifyRegistrationCode`, `readRegistration`, `readAddresses`, `readMine`, `readStatus`, `sendTestNotification`, `askForReview`, `confirmDetails`, `readQueue`, `readOverview`, `readDecision`; `unreadable`), `lib/registration/mapping.ts` (`queueFromBackend`, `overviewFromBackend`, `decisionFromBackend`, `QUEUE_TAB_KEYS`), `lib/criteria/mapping.ts` (`criteriaOverviewFromBackend`, `pendingFromBackend`), `lib/criteria/backend.ts` (`readCriteria`, `readPending`; `decidePending` uses the pending criteria id).
- Test support (new): `test/applicant/backend.ts` (`answerBackend`, `breakBackend`, `unsignedToken`, `seen`), `test/applicant/session.ts` (`callerRequest`, `sessionCookie`), MSW `invitationState`, `bffInvitationHandlers`.
- Types: `RegistrationView` is `{id, status, serviceName, steps}`; `QueueTab` is the back end's five; `CallBackDetails.numberToCall` optional.

## Tenant pending

None in this bundle's code paths beyond the transitional rule: every call is to the bearer's own
tenant (the back end binds it from the token) or the host (sign-in). No statement is written here.

## Assumed

- The reviewer's manual checks are done or not done: `scope` done when any flag is set; `criteria` done when approved; `callback` done when confirmed.
- A session lasts as the answer's expiry or the token's, whichever is first, capped at twelve hours (the staff rule).

## Not run

- Playwright e2e (`e2e/registration.spec.ts`, `e2e/registration-review.spec.ts`, `e2e/criteria-owner.spec.ts`): the sign-in and organisation flows were updated to the real shapes; written, not run (the orchestrator runs e2e once).
- The Neo4j-backed back-end suites were not run: only `tests/unit/adapters/inbound/fhir_rest/test_routes_registration_session.py` (23 tests) was run, for the one-line tenant answer.

## Commits

- The back-end tenant answer was committed as one commit with its red assertion (the red run was observed first: it failed on the missing key). Frontend red commits were separate for: the sign-in, the applicant reads, the applicant routes, the reviewer reads and the criteria mappers. The sign-in form and the organisation form were implemented and committed with their tests in the same commit after the red run (red observed for the form tests). Test corrections made during implementation (token lifetime and whole-second expiries in the session tests; the organisation test's shape) are noted in the commit messages.
