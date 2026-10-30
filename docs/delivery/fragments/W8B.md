# W8B: clinical advice, help, exec, support and planning screens wired to the back end (wiring wave)

Bundle W8B: W44, W45, W46, W56, W39, W40, W41, W48, W49, W51. Branch `task/build-W8B` off `integration/build`.

## Decisions

### DEC-880 The support code is made on request, not when the page opens (W56, DEC-772)
Status: accepted (wiring wave 8, bundle W8B; under DEC-133). The back end can now say whether a code is live and until when (`GET /support/codes/current`) but never gives the code back (only its keyed hash is kept). The share page therefore reads that state on opening and makes no code by itself: with no live code it offers "Make a support code"; once made, the code is held in the page's memory only and shown once; after a reload it says "A code is live until HH:MM" and that the code is shown only once, with "Stop sharing now". A refused second code (409) re-reads the state. Making the code needs a press because opening a page must not grant support a view of the person's session, and because a second code is refused while one is live (the old open-time request failed twice under React strict mode).

### DEC-881 The clinical advice form needs the request read, the case's details and a held request (W44, implements DEC-855 item 4)
Status: accepted. The case page reads the request itself (`GET /fhir/Task/{id}`, DEC-774) and the address carries the request id only (the queue's `?urgency&why&case` context of DEC-719 is gone). The advice form is offered only when that read loaded, carries the case number (the glance) and the request is `in-progress` (held). Read failed: "This request could not be read, so it cannot be answered from here." No glance: "The case could not be read, so no advice can be given from here." Back in the queue: "Take it again from the queue". Completed: the advice given is shown and no second one is offered. A queue card whose case could not be read has no "Take it" (the request would be locked for 10 minutes and still not answerable). The case is shown as the advisor recorded it: age band, needs, NEWS2, case urgency and the reason; never a postcode (DEC-774, DEC-396). Mine and Done are the back end's lists (DEC-774 item 4); the on-duty page starts on the clinician's own presence (DEC-780); the 10-minute return is a live region updated each minute.

### DEC-882 The advisor's dialog shows the advice from the request read, or says it could not read it (W45, implements DEC-855 item 4)
Status: accepted. `GET /api/bff/cases/[ref]/clinical-requests/[id]` reads the Task and answers waiting, taken (with when it returns to the queue) or advised (choice, reason if given, the clinician's note, when). A request of another case than the one in the path is the same 404 as one that is nowhere. A read that fails is a failure: the dialog says "The answer could not be read. Check again, or use the escalation route under local protocol.", offers "Check again", and never says "Waiting" while the read fails or once advice exists. A taken request that reads as waiting again is said to have gone back to the queue (a lapsed lock reads as waiting). The back end sends no taken-by role or taken-at time, so the dialog no longer prints them (it printed values the back end never sent). The dialog says to keep it open until the advice arrives; the request id is not stored anywhere. The dialog is opened from the options list (footer and no-fit state) and from the map's postcode-not-found and out-of-area states by a new component, `AskClinicalPanel`, which reads the case itself, so those screens hold no case; the summary shows the postcode district only.

### DEC-883 Clinical, help and support routes are at the back end's root (W44, W46, W56)
Status: accepted. `/clinical/presence`, `/clinical/available`, `/help/problems` and `/support/...` are mounted without the `/fhir` prefix (routes_clinical.py, routes_support.py). The BFF called them under `/fhir` and the stand-ins matched that, so the wiring could not have worked against the real back end; the BFF now passes `root: true` and the stand-ins serve the root paths.

### DEC-884 `GET /planning` is built on the back end (W51, U43)
Status: accepted. `routes_planning.py`: lead and executive only (any other role the non-revealing 404, refused before any read), `period=30d|90d|12m`, `need=all|falls-frailty|iv-therapy|palliative`, over `RunPlanningAnalysis`. Aggregates only: a count under 10 is `null` with `suppressed: true`, a share whose base is under 10 likewise, and every grid cell under 10 is `null` (a hidden cell is shown as "fewer than 10", never as a zero). The busiest cell is the back end's (day index, band index, count of at least 10). No new graph statement (the use case's audit reads are registered); tests: role matrix and shape (unit), two-tenant and small-count (Neo4j).

### DEC-885 Insight (O08) is not served over HTTP: left as a known issue (W49)
Status: accepted. The page's five tabs need figures the aggregates do not hold (web vitals p75 per route, the delivery pipeline, release comparison) and a different shape per tab; mapping the aggregates that exist (funnels, friction, routes, queries) would be a design task of its own, not a small route. The insight page now says "Insight is not available yet: the back end does not serve it." on a 404 instead of a generic failure.

### DEC-886 The week summary's time-back line shows no placeholder (W41)
Status: accepted. With no tenant baseline (TEN-026) the line said "Each replaces about one phone call of [x] minutes". It now says how many updates there were and "The time this saved is not measured yet."; the back end's own `timeBackText` is shown when it sends one.

### DEC-887 The deputy is chosen from the leadership list (W39, DEC-776)
Status: accepted. `GET /api/bff/exec/leaders` (id and name only) feeds a select on the set-up and settings screens. A saved deputy who is no longer on the list is not carried over ("Your saved deputy is no longer a leader. Choose another."). An empty list says so and saves nothing. If the list cannot be read the typed id remains, with a message, so a person is never locked out (the back end checks the deputy holds a leadership role).

### DEC-888 Acknowledged and closed alerts are the back end's lists; the duty coordinator's number is the board's (W40, DEC-775, DEC-777)
Status: accepted. The Acknowledged and Closed tabs read `?status=acknowledged|closed` when opened (not only this visit's); an unreadable list is said, never shown as empty. "Call the duty coordinator" (a `tel:` link and the number) shows on the service and alert screens only when the board carries `coordinationPhone`; a value that is not a phone number is dropped. The alert detail reads the three lists (the back end has no single-alert read). The exec home links to `/planning/flows` (W51).

### DEC-889 Safety concern confirmation names the tenant's coordination team (W46)
Status: accepted. The confirmation and the warning print "Phone <team> on <number>." from the tenant's public profile when it holds them, and nothing when it does not (H-T15).

## Hazards

| id | hazard | source | control | tasks | verified by | status |
|---|---|---|---|---|---|---|
| H-550 | A clinical advisor gives advice on a case they cannot see, or on a request they no longer hold | DEC-855, H-375 | The form is offered only for a request that was read, has the case glance and is held; the 409/404 on send says the request is no longer theirs | W44 | `CaseView.test.tsx` (DEC-855 block), `AdviceForm` 409 test | built, to be verified |
| H-551 | An advisor closes the escalation dialog before the advice arrives and never sees it | H-514 | The dialog says to keep it open; the advice is read from the back end every 5 seconds; nothing is stored in the browser | W45 | `AskClinicalDialog.test.tsx` | open: no way back to a request after the dialog closes (known issue) |
| H-552 | A planning figure under 10 identifies a small group | DEC-393 | The back end sends no count, share or grid cell under 10; the screen and the CSV show "fewer than 10" | W51 | `test_routes_planning.py` (unit and Neo4j), `PlanningView.test.tsx`, `HeatGrid.test.tsx` | built, to be verified |
| H-553 | A person believes support can see nothing when a code is live, or that a lost code is recoverable | DEC-772 | The page states whether a code is live and until when; the code is shown once; stop and make a new one | W56 | `SupportCode.test.tsx` | built, to be verified |
| H-554 | A clinical request whose case cannot be read waits unanswered | DEC-855 | The queue says so and offers no Take; the asking advisor's dialog keeps reading and shows nothing as advice | W44, W45 | `QueueList.test.tsx`, `AskClinicalDialog.test.tsx` | open: nobody is told (known issue) |

## Known issues

| ID | what | where | trigger |
|---|---|---|---|
| W44 | "What the advisor saw at HH:MM" and "Call the advisor" are not built: the request read carries no list of what was shown and there is no contact route | `components/clinical/CaseView.tsx` | the back end records what a display showed against a request, or a contact route exists |
| W44 | A queue request whose case could not be read cannot be taken and nobody is told; it waits | `components/clinical/QueueList.tsx` | such a request in the field (raise it to the lead, or return it to the asking advisor) |
| W45 | Closing the dialog loses the way back to the request's answer (the id is deliberately not stored) | `components/advisor/AskClinicalDialog.tsx` | an advisor reports advice they never saw; a "my requests" read for the advisor would fix it |
| W45 | The dialog is wired to the options list and the map's postcode states only; the withdrawal alert's "Ask a clinical advisor" (`BookingPanel`) is not mounted anywhere yet | `components/advisor/BookingPanel.tsx` | the booking panel is mounted on a case screen (the booking bundle) |
| W46 | The problem report sends no page route and does not say whether the session was shared | `app/api/bff/help/problems/route.ts` | support wants the page of a report (W7A-K5) |
| W49 | `GET /support/insight/{tab}` (O08 read) is not a back-end route; every tab says insight is not available | backend `routes_support.py`, `telemetry_aggregates.py` | the O08 route task: map funnels, friction, routes and queries to the tab shapes, and add vitals, pipeline and release figures |
| W48 | Search by trace id or reference is refused by the back end ("not supported"); the page says so | `components/console/FindSession.tsx` | the back end indexes trace id and reference |
| W48 | No ticket request or ticket approval screen (BFF route for the request exists; the lead's approval has no screen) | `app/(console)/console/session/[id]/page.tsx` | the ticket flow is designed |
| W51 | The owner role cannot open `/planning` (DEC-746) | `lib/auth/access.ts` | a role decision |
| W41 | The network variant of the week summary is not built | `app/api/bff/exec/week/route.ts` | DEC-132 network views (TEN-N13) |
| W40 | "Reported by", the service's acknowledger and "+4 since 13:10" are not shown (the board and alert carry neither) | `components/exec/ServiceDetail.tsx` | the board carries when a service went over |

## Contracts

- BFF (new): `GET /api/bff/clinical/requests/[id]` (the clinician's read of one request), `GET /api/bff/clinical/presence`, `GET /api/bff/exec/leaders`, `GET /api/bff/support/code?sessionId=`; `GET /api/bff/exec/alerts?state=open|acknowledged|closed` (all three answered); `GET /api/bff/clinical/requests?tab=waiting|mine|done` (all three answered); `GET /api/bff/cases/[ref]/clinical-requests/[id]` (the real read). `POST /api/bff/help/problems` now sends. `GET /api/bff/planning` and `/export` read the real route.
- Back end (new): `GET /planning` (`routes_planning.py`: `query_from`, `cohort_text`, `planning_json`).
- Components: `AskClinicalPanel` (reads the case, opens `AskClinicalDialog`; `summaryOfCase`), `CaseView` takes `{requestId, request | null}`, `DutyForm` takes `presence`, `EscalationForm` takes `leaders`, `ServiceDetail` and `AlertDetail` take `coordinationPhone`, `HeatGrid` takes `grid` with nulls and `busiest`.
- Libs: `lib/clinical/task.ts` (`clinicalRequestFromTask`), `lib/exec/leaders.ts`, `lib/exec/call.ts`; `Board.coordinationPhone` (optional).
- Test support: `test/msw/handlers/clinical.ts`, `exec.ts`, `support.ts` serve the real paths and shapes.

## Not run

Playwright (`e2e/exec-clinical-help.spec.ts`: queue tabs, an unreadable request, the share page): written, not run. The Neo4j test of `GET /planning` was run (7 passed) on the shared Neo4j.
