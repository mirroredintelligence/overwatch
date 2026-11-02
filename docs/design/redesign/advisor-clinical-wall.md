# Redesign brief: advisor, clinical advisor and wall screen

Status: design for review. Not built. Nothing in `frontend/` or the back end has changed.
Canvas: https://claude.ai/artifact/3bTmmzxLvvCyF6AJnwRcu7 (30 boards; Main is an index with a link per route).
Companion canvas (shell, morph rules, administration): https://claude.ai/artifact/Nb8Zzui3LuDhQbqe8vjdku.
Sources read for this brief: `docs/design/design-system.md`, `docs/spec/ui-screens.md` (artboards Main, TileStates, BoardDown/Surge/Quiet, AdvisorStart/Advisor/AdvisorPhone/AdvisorActions/AdvisorFinish/AdvisorSteps, ClinicalAdvisor, ScreenPairing, BookingExceptions, MapWeb/MapPhone), and the pages and components named below. A design that changes a decision in `docs/delivery/decisions.md` needs a new decision first (DEC-014 owns the design system).

## 1. What changes, in one paragraph

The advisor call stops being three stacked cards on one scrolling page. It becomes one stage with four layout states (Overview, Needs, Options, Request) in a fixed shell. A step changes only because the advisor chose it; the needs fold into a pinned summary; one option takes the stage and the rest fold into a rail. The board, the wall screen and the clinical queue use the same tile, status and shell language. Every sub-view of the options (list, compare, map, radar, ways, other organisations) is a tab of one segmented control, not a separate-feeling page.

## 2. Shared contract (build first, used by every route below)

| Piece | Spec | Where it lives today | Change |
|---|---|---|---|
| Shell | Dark rail 84 px (Calls, Board, Services, Help), white top bar 72 px (organisation line, page name, call chip, role chip). Rail never moves; top bar never moves. | `components/shell/AppShell.tsx` (header with nav links) | Replace the header nav with the rail. Role chip already built (`components/shell/RoleSwitcher.tsx`, DEC-1324). Phone: bottom tab bar, 68 px, same four items. |
| Tokens | Add: `--c-rail #0B2A3D`, three surface levels (page `#EEF2F3`, card white with `0 1px 2px / 0 10px 28px` shadow, raised), `--ease-spring` (the `linear()` spring with a `cubic-bezier(.34,1.56,.64,1)` fallback). Reuse `--dur-*`, `--ease-*`. | `app/tokens.css` | Additive only. Reduced motion already zeroes `--dur-*`. |
| Status language | Six states, each a shape plus a word, never colour alone: Accepting (filled circle), Limited (half circle), Not accepting (square), Over capacity (triangle), Not updated (dashed ring, hatched tile), Out of hours (crescent, quiet tile). "Last known" is an overlay on any state (dashed pill, hatched tile), never a seventh state. | `BoardStatus` in `lib/board/types.ts` already has all six; `NetworkTile.tsx` words them | New shared `StatusChip` (shape + word) and `Tile` used by Board, Wall, Options, Compare. Out of hours must render as in the Quiet board, not as Not accepting. |
| Stale figures | A figure older than 2 hrs shows "old" in words and weight on the card and the list; the wall uses `lib/board/liveness.ts` (stale after 180 s, reasons offline / unreadable / old). | `lib/board/liveness.ts`, `Board.tsx` | Design only: the 'Last known' overlay (see Wall, section 6). |
| Segmented control | List, Compare, Map, Radar, Ways, Other organisations over one options read. Current tab `aria-current="page"`. | Separate pages today | One component, links to the existing routes (keep the URLs). |
| Skeleton | Shared shimmer (`app/skeleton.css`, `components/ui/Skeleton.tsx`, commit ec7d49dd) with a spoken label. | Built, admin pages only | Use for every loading state below. |

## 3. The advisor call: states and URLs

URL is the state. A state change is a navigation (client-side, `history.pushState`) so Back and reload land in the same place. Existing routes are kept; two additions are proposed and need a decision.

| State | URL | Source board | Trigger to enter |
|---|---|---|---|
| Overview | `/advisor` | Call (step 1), BoardNormal | Open Calls |
| Needs | `/advisor/case/[ref]` | Call (step 2) | Start a new call (creates the case) |
| Options | `/advisor/case/[ref]/options` | Call (step 3) | See matching services |
| Options views | `.../compare`, `.../map`, `.../radar`, `.../ways`, `.../network-options`, `.../network-map` | Compare, Map, Radar, Ways, NetworkOptions | The segmented control |
| Request | **proposed** `.../options?service=[id]` (query, not a new route) | Call (step 4) | Open on an option |
| Outcome | `/advisor/case/[ref]/finish` | Finish | Record outcome |
| Closed | `.../finish?closed=1` (replace, not push) | Closed | Save outcome |

Grid per state (desktop, main area under the top bar and step bar; columns are `summary | stage | side`):

| State | `grid-template-columns` | Stage shows | Side shows | Summary |
|---|---|---|---|---|
| Overview | `0 1fr 340px` | Ready for calls, one primary button | Open cases | hidden |
| Needs | `0 1fr 320px` | The needs form | Live count of matching services | hidden |
| Options | `300px 1fr 0` | Options (list or a sub-view) | none | pinned patient card with Edit |
| Request | `270px 1fr 300px` | One option, full detail | The other options, folded | pinned, narrower |

Transition rules: columns ease over 520 to 560 ms with `--ease-drawer`; stage content crossfades with a 120 to 160 ms delay and a small spring translate; side layers slide 18 px; the board tiles above the stage shrink from 124 px to 48 px high in step 1 to 2. Never animate a live number; resize the box around it. Edit needs returns to Needs and expands the summary back into the form.

State machine (events are the person's, nothing else changes a state):

```
Overview --startCall--> Needs --seeOptions--> Options <--editNeeds-- (Request, Options)
Options --openService--> Request --requestBooking--> Request(waiting) --confirmed--> Request(confirmed)
Options|Request --noFit--> NoFit --widenTime|phone|askClinical|otherRoute--> Options|Request|dialog
Request(confirmed) --recordOutcome--> Outcome --save--> Closed --startNext--> Needs (new case)
Request --withdrawn(alert)--> Withdrawn alert --seeOptions--> Options
```

## 4. Route by route

Existing components: names from `frontend/components/advisor/`, `board/`, `radar/`, `clinical/`. "New" means a new component; "Reshape" means the existing one is restructured, not rewritten.

### 4.1 Advisor

| Route | Board | Layout states | Components | Data (existing unless flagged) |
|---|---|---|---|---|
| `/advisor` | Call, S1 | Overview (above) | Reshape `StartCallButton`, `BoardCounts`; new `CallStage` (the grid) | `/api/bff/board`, `/api/bff/cases` |
| `/advisor/board` | BoardNormal / Surge / Quiet / Down / Loading, PBoard | Single column grid of 9 tiles; banner row above (pressure, quiet, offline); phone: compact rows that open one at a time | Reshape `Board`, `PressureBanner`, `BoardUnavailable`; new `Tile`, `StatusChip` | `lib/board/read` (`$board`); liveness helpers; `pending` already on `BoardEntry` |
| `.../case/[ref]` | Call step 2, P1 | Needs (above) | Reshape `NeedsForm`, `ScorePickers`, `PostcodeStates`, `DistrictChoice`; new `LiveCount` | PUT `/api/bff/cases/[ref]` (If-Match); **missing: a count while typing** (see section 8, gap 1) |
| `.../options` | Call step 3, P2 | Options | Reshape `OptionsList`, `ServiceCard`, `NotSuitableList`, `CaseSummary` (becomes the pinned card), `CallSteps` | `/api/bff/cases/[ref]/options` (list, not-suitable with reasons) |
| `.../options?service=` | Call step 4, P3, P4 | Request | Reshape `BookingPanel`, `OptionBooking`, `BookingCard`; new `OptionRail` | POST `/api/bff/bookings`, events stream `/api/bff/events`, `/api/bff/bookings/[id]` |
| `.../compare` | Compare | Options layout, table in the stage | Reshape `radar/CompareScreen` (keeps the no-score, no-rank rule and the Not available rows) | Same options read |
| `.../map` | Map, MapLost | Options layout, map and list side by side; phone: map above list | Reshape `MapScreen`, `map.module.css`; district chooser as its own card (MapLost) | Options read; PUT `/api/bff/cases/[ref]/district` |
| `.../radar` | Radar | Options layout, key panel at the right | Reshape `radar/RadarScreen` | Options read. Drive-time rings and traffic stay shown as off |
| `.../ways` | Ways, PWays | Three lanes; lane order follows the optional can-travel answer, never hides a lane | Reshape `radar/WaysScreen` | Options read |
| `.../network-options`, `.../network-map` | NetworkOptions | Read-only list, one phone action per row | Reshape `NetworkOptions`, `NetworkMap`, `NetworkTile` | `/api/bff/network/options`; only the network id and case ref are sent |
| (empty state) | NoFit, PNoFit | Options layout, four next steps as large rows | New `NoFit` (today: a banner in `OptionsList`) | Options read (empty result); the four actions reuse existing calls |
| Dialogs | Actions | Three dialogs over the call | Reshape `PhonedDialog`, `DeclinedDialog`, `AskClinicalDialog` | FHIR `$advisor-phoned`, `$declined` (`lib/advisor/service-api.ts`), `/api/bff/cases/[ref]/clinical-requests` |
| Exceptions | Exceptions | A full alert (withdrawn), a dialog (cancel) | Reshape `WithdrawalAlert`, `CancelBookingDialog` | `/api/bff/bookings/[id]/cancel`, events |
| `.../finish` | Finish, PFinish, Closed | Two cards (outcome, summary); then a closed state | Reshape `FinishScreen`, `OutcomeForm`, `SummaryCopy`, `CallClosed` | `/api/bff/cases/[ref]/outcome`, `.../summary` |

### 4.2 Clinical advisor

| Route | Board | Layout states | Components | Data |
|---|---|---|---|---|
| `/clinical` | ClinDuty | One card (Available, Busy, Away) plus a "right now" card | Reshape `clinical/*` duty form | `/api/bff/clinical/presence` (**check it holds a Busy state**, gap 7) |
| `/clinical/requests` | ClinQueue, PClinAlert | List with Waiting, Mine, Done tabs; urgency tag (Now solid, Within 15 min outline) | Reshape the queue list | `/api/bff/clinical/requests`, `.../take`; **Done tab is new** (gap 8) |
| `/clinical/requests/[id]` | ClinCase, ClinSent | Three columns: slim queue, case, advice. After sending: one confirmation card | Reshape `CaseView`, `Advice` form | `/api/bff/clinical/requests/[id]` (+ `/seen`, `/advice`, `/advisor-contact`) |

Clinician rules kept: no postcode and no name is ever shown (DEC-396); advice is offered only when the read loaded and the request is held by this clinician (DEC-855, DEC-1179); the advisor's number is asked for only when Call the advisor is pressed.

### 4.3 Wall screen

| Route | Board | Layout | Components | Data |
|---|---|---|---|---|
| `/screen` | WallBoard (1600 x 900 shown) | 3 x 3 tiles on a dark ground, header (title, clock, date), footer (key, "No patient information") | Share `Tile` with the board at a larger scale; keep `Board` as the one renderer | `wall/board`, `screens/session`, `lib/board/liveness.ts` |
| `/screen/pair` | WallPair | Left: the code at 210 px; right: the three steps | Reshape the pairing screen | `/api/bff/screens/pairing` |
| `/screen/reconnect` | WallReconnect | Banner (amber, spinner, "Trying again in n seconds") over hatched Last known tiles | Reshape the reconnect/stale view | `lib/board/liveness.ts`: `offline`, `unreadable`, `old` reasons |

Legibility at 3 m (derived from a 1080p display; confirm on the real screen): tile numbers 100 px or more, service names 30 px, status words 22 px, no text under 20 px, status always shape plus word. The wall never plays motion except the reconnect spinner, which stops under reduced motion.

## 5. Phone

Same four states, rewritten as steps and sheets: columns become a progress bar (four segments) and a pinned one-line patient summary with Edit; a card becomes a bottom sheet; the board becomes compact rows that open one at a time; the primary action is sticky at the bottom (58 px). Navigation is the bottom tab bar. The first canvas has the Needs, Options, Detail sheet and Requested boards; this canvas adds Board, Ways, No fit, Outcome and the clinical alert.

## 6. Motion and accessibility

- Frequency decides motion: keyboard actions (typing, Enter, arrows) and high-frequency actions have none; steps and sheets get the morph; everything respects `prefers-reduced-motion` through the tokens (the same layout appears at once).
- Morph focus: after a step the focus moves to the new stage heading (`tabindex="-1"`), the current step carries `aria-current="step"`, the stage is a labelled region, and the step change is announced politely ("Step 2 of 4: Options").
- Folded content (the rail, hidden columns) is `inert`, so Tab never lands in something invisible.
- A target is 44 px or more, a primary action 52 px or more; text 4.5:1 (the status colours were contrast-checked in DEC-014); the board's pending state, old data and Last known are carried by words and shape, not colour.
- No live number animates: counts and ages change in place; the box around them may resize.
- Screen readers: tiles are list items with the status word first ("Accepting. UCR West. 4 referrals in the next 2 hrs. Updated 9 minutes ago").

## 7. Suggested build order

1. Tokens, rail shell, `StatusChip`, `Tile` (with the six states and Last known). Unit and axe tests per state.
2. Board and wall board on the new `Tile`: Normal, Surge, Quiet (Out of hours), Offline/Last known, Loading, plus the phone list.
3. `CallStage` (the grid and the four layout states) with the pinned summary and step bar; migrate Needs and Options into it. URL state and focus management here.
4. Options sub-views behind the segmented control: Compare, Map and district chooser, Radar, Ways, Network.
5. Request, the dialogs, the exceptions, Finish and Closed.
6. Clinical: duty, queue, case and advice; phone alert.
7. Wall pairing and reconnect.
8. Phone pass for each; Playwright journeys for the advisor call (Needs to Closed) at desktop and phone width.

Each step ships behind the existing routes; the old screens stay until its replacement passes the existing tests (they are the behaviour contract) plus the new state tests.

## 8. Data gaps and checks (existing endpoints only; nothing here is built)

1. **Live count while filling the needs.** The Needs state shows "3 services meet the criteria so far". Today the options read needs a saved case. A count needs either a debounced PUT of the partial case then an options read, or a new count-only read. The first works with no back-end change but writes a draft on each pause; decide.
2. **Request deep link.** `?service=[id]` is a front-end addition only; it must resolve to a service in the case's options and be ignored otherwise.
3. **Compare rows.** "Adds to today's round" and "Patients already near" need service rounds the system does not hold; they stay Not available (not zero).
4. **Radar.** Drive-time rings and traffic have no data; they stay shown as off with the reason.
5. **Out of hours.** The board already has the status and the reopen time; confirm the reopen time is on `BoardEntry` for every out-of-hours service.
6. **Hold timer.** The clinical case shows "You hold this request, 8:42 left" (10-minute hold). Confirm the request read carries the hold expiry; if not, the timer is cosmetic and must be removed.
7. **Duty states.** The canvas has Available, Busy and Away; confirm `clinical/presence` stores three states.
8. **Done tab and alerts.** A Done list of requests and a push alert on a phone are not confirmed in the BFF (push keys exist; the clinical alert is not read). Both are optional first cuts.
9. **Pairing code refresh.** The wall design says a new code appears after 10 minutes; confirm the screen polls and replaces an expired code.
10. **Phone summary line, wall night mode** are presentation only.

## 9. Open design questions

1. Does Out of hours get its own chip on the advisor list and the wall legend (as drawn), or is it shown as Not accepting with the reopen time? The existing tests count it separately (it is not counted in the pressure number).
2. The Request state as a query on Options, or its own route `/options/[serviceId]`? A route is cleaner for Back, a query keeps the options in view.
3. Should Compare offer a Request per column? Drawn as outlined buttons so no column looks recommended; a clinical-safety decision.
4. Wall: light or dark ground? Drawn dark for glare at distance; the current wall is light. Test in the real room.
5. The clinical queue order: oldest first or most urgent first? Drawn with Now before Within 15 min.
6. The staff header says "Clinical advisor" and the admin pages say "Clinical lead" for the same role; pick one word.

## 10. What this design does not cover

Service-side booking pages (`/l/[token]/booking`, withdraw and not-reached) belong to the provider onboarding surface; adding a wall screen (`/lead/screens/new`) belongs to the shift lead surface. The Exceptions board shows only what reaches the advisor.
