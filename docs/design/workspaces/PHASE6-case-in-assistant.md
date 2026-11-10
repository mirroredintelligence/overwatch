# Phase 6: the call, the booking and the outcome in the assistant (DEC-1378, DEC-1383)

The owner's direction (2026-11-10): add to the assistant what v1 has and v2 lacks, so that v1 can be retired and advisors have only v2. This is the scope. It is a design to build from, not a build; the open questions are at the end.

## What v1 does today (the call flow, `/advisor/case/[ref]/*`)

Four steps (`CallSteps`): **Needs, Options, Request, Outcome**.

| Step | v1 | v2 now |
|---|---|---|
| Needs | Start the call (`StartCallButton`) opens a case; the needs form takes caller, age, postcode, need, urgency | The triage card takes age, postcode, need and timeframe in the thread. **Browse only: no case is opened, nothing is stored** |
| Options | The services that fit (`OptionsList`, map, compare, ways, network options, ask clinical) | Results, map, reasons, service page and the one-service check. No compare, no network options, no ask clinical |
| Request | `OptionBooking` and `BookingPanel`: a booking request to one service, its text, the state (pending, confirmed, declined, expired, withdrawn), phoned, cancel; `OpenBookingAlerts`, `WithdrawalAlert`, `DeclinedDialog`, `PhonedDialog`, `CancelBookingDialog` | **None.** "Book a slot" checks the fit and says to phone |
| Outcome | `FinishScreen`, `OutcomeForm`, `CaseSummary`, `SummaryCopy`, `CallClosed` | **None** |

The back end already has these routes and use cases (`app/api/bff/cases`, `app/api/bff/bookings`; S4 and S5 of the plan). Phase 6 is mostly the front end of the workspace plus guardrails; it is not a new back end, except where a gap below says so.

## The design

1. **One conversation, one case.** A call is a case. The assistant offers "Start the call" when the criteria are complete (a button on the triage card and a chip in the thread). It opens the case from the criteria already in memory (a write, DEC-1376 item 11: the person confirms on a card, the assistant never writes by itself). From then the thread shows "On a call" with the case reference, and the criteria become the case's data. This is the first moment the postcode, age band and needs leave memory (they go to the case, as in v1). The privacy rules for the URL, storage and logs do not change: the case reference is the only thing in a URL.
2. **Request from the service page.** "Book a slot" becomes the real request once a case is open: a confirm card ("Ask {service} to take this patient. They will be texted now.") then the booking request through the existing route, with the thread showing the state as it changes (pending, confirmed, declined, expired, withdrawn) in plain words and the next step as chips ("Phone the service", "Ask another service", "Cancel the request"). One open request per service stays (H-04). Without an open case the button keeps today's behaviour (check the fit, phone).
3. **Finish from the thread.** "Finish the call" opens the outcome card (the v1 outcome form, in the thread) and closes the case; the summary card replaces the criteria; "Start a new call" clears everything (the existing New search).
4. **Reuse, not rewrite.** The v1 components (`BookingPanel`, `BookingCard`, `OutcomeForm`, `FinishScreen`, the dialogs) are mounted in the workspace frame under `/advisor/v2/case/[ref]/...` and in the thread card, with the workspace's tokens, one-screen layout and chips. Only the layout and the assistant's turns are new; the rules and the back-end calls are v1's.
5. **Guardrails (unchanged from DEC-1376).** Every write goes through a confirm card the person presses. The role's intents decide what the assistant can offer (the registry), never a model. Free text stays off. A language model, later, may only choose from the same intents.
6. **Retirement of v1 (the gate of DEC-1378).** When the workspace does all of the above with the same audit and the same tests, the v1 pages redirect to their v2 equivalents for advisors; the v1 code stays one release, then goes. Cases already recorded stay readable (the case read is shared).

## Units (for the units.json of the kit)

| Unit | Scope | Model |
|---|---|---|
| WSP-20 | Registry and dialog: intents `advisor.call.start`, `advisor.call.request`, `advisor.call.finish`, their turns and chips; `check.py` cases | Sonnet |
| WSP-21 | Start the call: the confirm card, the open-case write, the thread's "On a call" state, the case reference in the provider (memory only) | Sonnet (a write) |
| WSP-22 | The booking request from the service page: confirm card, state turns in the thread, one open request, cancel and phoned | Sonnet (a write, and a text to a service) |
| WSP-23 | The booking alerts and withdrawal in the frame (`OpenBookingAlerts`, `WithdrawalAlert`) | Haiku tests, Sonnet build |
| WSP-24 | Finish: the outcome card and the summary | Sonnet |
| WSP-25 | v1 redirects for advisors and the home flip, behind the gate, with the hazard-log rows | Sonnet |

Each unit: tests from numbered cases first, an independent check, the hazard-log rows (H-04, H-05, H-1377 to H-1379 are touched), and a side-by-side with its board in a browser. No board exists for the case screens: a board for the confirm cards, the booking states and the outcome is drawn first.

## The owner's answers (2026-11-10) and what they change

1. **Compare and ask clinical are in scope** (not dropped). They are the Options step's two extras the pilot needs.
2. **The system of record is the other system.** This tool keeps a case for **analytics and product improvement**, not as the clinical record. So the case here is a **minimal coded record**, not v1's whole case: age band, need categories, urgency, the district (outward code, never the full postcode), how many services fitted, the service chosen, the booking's states with their times, the outcome code, whether a clinical request was made and its times. No caller name, no free text, no full postcode, no reference to the other system's record. The retention rule (the tenant's data-retention setting) applies. This is a decision for the owner to confirm (DEC-1384).
3. **Advisor v2 may open a case** and book, and v1's `advisor` session goes. Both session roles (`advisor`, `advisor-v2`) get the same v2 pages and the same case and booking rights, and v1's pages redirect; `advisor-v2` folds into Advisor as DEC-1376 says. This is a back-end and route-guard change (the case and booking routes admit `advisor` only today, DEC-860), so it follows the full standard: tests first, a tenancy and role review, an independent check and a hazard-log row.
4. **Clinical people use the same pages.** A clinical session gets the advisor workspace, and its assistant also shows the clinical requests (a queue intent behind the clinical flag, DEC-1376 item 3). The `clinical` session role is **not** retired in this phase: a clinical advisor must still hold an active clinical-lead practitioner role (DEC-394) and the approval routes name the role; merging the page does not merge the right. Folding the role into a flag is the role-consolidation work (DEC-1376, open), with its own design.

## Units, revised

| Unit | Scope | Model |
|---|---|---|
| WSP-20 | Registry and dialog: intents `advisor.call.start`, `.request`, `.compare`, `.clinical`, `.finish`, and `clinical.requests`; `check.py` cases | Sonnet |
| WSP-21 | Roles: both advisor session roles may open a case and book (routes, guard, back end), with the tenancy and role review | Sonnet, then an independent verifier |
| WSP-22 | The minimal case record (the dataset in answer 2) and its analytics read; the retention rule applied | Sonnet |
| WSP-23 | Start the call: confirm card, open-case write, "On a call" in the thread | Sonnet |
| WSP-24 | Request: confirm card, booking states in the thread, cancel, phoned; the booking alerts and withdrawal | Sonnet |
| WSP-25 | Compare: the v1 compare mounted in the frame, chosen from the results | Haiku tests, Sonnet build |
| WSP-26 | Ask clinical (advisor side) and the clinical requests queue (clinical side) | Sonnet |
| WSP-27 | Finish: the outcome card and the summary | Sonnet |
| WSP-28 | v1 redirects and the home flip, behind the gate, with the hazard-log rows | Sonnet |

## What it does not change

The back end of cases and bookings; the booking text; the audit entries; the roles that may write (the proxy guard and each route). The advisor home stays `/advisor` until WSP-25.
