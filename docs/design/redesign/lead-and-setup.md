# Redesign brief: shift lead, service setup and criteria owner

Canvas (private): https://claude.ai/artifact/MJysSmYu6cKJ2nmEMS4Ty1 ("Overwatch redesign: shift lead, service setup and criteria", 24 boards).
Companion canvas for the advisor call, the shell and the morph rules: https://claude.ai/artifact/Nb8Zzui3LuDhQbqe8vjdku.

This brief says, for each route on this surface, what the board shows, what to build, which data each state needs, and what is missing. It is written so each section can be taken as one task. Nothing here changes a back end rule: where a screen needs data that does not exist yet, it says so under **Missing**, and the screen is designed so it still works without it.

Status of the design: boards were written from the page code and the original canvas text (`docs/spec/ui-screens.md`: ShiftLead, ShiftLeadFlows, ShiftLeadPhone, CriteriaOwner, SuspendLeaver, SafetyConcern, ScreenPairing, MultiServiceAdmin). Nothing has been looked at in a browser, and every figure, name and date on a board is sample data. The wording is a draft for the owner to read.

## 1. The rules every board follows

These come from the morph canvas and `docs/design/design-system.md`. They are the acceptance test for each route below.

1. **Change follows the person.** A layout changes only because someone chose something. Data arriving never moves a block.
2. **Anchors stay put:** the rail, the top bar, the role chip. Inside a screen, a pinned summary (what has been entered so far, the service being changed) stays on the left.
3. **Live figures are fixed.** Counts, status words and their shapes do not animate for style. A block may resize around a figure, never the figure.
4. **One primary action per screen**, named for what it does ("Suspend UCR East", never "Submit").
5. **Status is shape plus word, never colour alone:** accepting a filled circle, limited a square, over capacity a diamond, not accepting a filled dark circle, not updated a dashed circle. Warnings are amber with an icon and a sentence.
6. **Destructive acts name what will happen first,** then ask. The safe choice is the same size as the destructive one.
7. **Progressive disclosure.** A card shows the answer; the ladder, the diff, the group name, the history open on request, one at a time.
8. **Every state has an address** (a URL), so Back, a link and a reload land in the same place.
9. **Targets 44px or more, text 4.5:1,** headings in order, one `h1` per screen, every icon-only control labelled.
10. **Motion tokens only:** `--dur-*`, `--ease-*`, and the local spring from `People.module.css`. They are zero under reduced motion, so nothing needs a second rule; the states themselves must still read.

## 2. Shared pieces this surface needs

| Piece | New or existing | Notes |
|---|---|---|
| App frame (rail, top bar, role chip) | **New, shared.** Built by the shell work, not here | Lead rail: Shift, Services, Phones, Flags, Screens, Audit. Owner rail: Services, History, Help. Phone: bottom bar with four items and a More. The role chip is `components/shell/RoleSwitcher.tsx` (exists). |
| Loading placeholders | **Existing:** `components/ui/Skeleton.tsx` (`Loading`, `SkeletonRows`, `Skeleton`) | Use `Loading label="Loading the …"`; shapes keep the page's layout. |
| `StepBar` (numbered pills that also work as the state switch in a prototype) | New | Used by add a service, pair a screen, owner review. In the product the pills are links to steps already visited. |
| `MorphStage` (layers stacked in one cell, one active; opacity, translate and spring on enter) | New | The CSS the prototypes use (`Main.dc.html` of the morph canvas). Inactive layers are `inert`. Must not mount inactive forms' data fetches. |
| `SummaryPin` (left card: what has been entered; grows from width 0) | New | Column width animates with `grid-template-columns`; content is a read-only list with "Change" links. |
| `ChoiceChips` (single or multi, `aria-pressed`, shape for selected) | **Existing:** `components/ui/Chip.tsx` | Reuse; add a selected tick so state is not colour alone. |
| `Field` with hint and error | **Existing:** `components/lead/AddServiceForm.tsx` has a local `Field`, `ErrorSummary` | Lift into `components/forms`. |
| `StatusMark` (shape + word) | **Existing:** `components/ui/StatusBadge.tsx` | Add shapes for the five board states and for the service lifecycle states (live, paused, in review, not invited, re-verify due). |
| `Disclosure` (row that opens one panel, height eases, content springs) | **Existing from the admin work:** `components/admin/Disclose.tsx` | Reuse. Move to `components/ui` when a second surface needs it. |
| `ConfirmDialog` (`role="alertdialog"`, names the act and the thing, equal-size safe choice) | New | Replaces ad hoc confirm states in `ScreenUnpair`, `RemovePersonForm`. |
| `DiffTable` (what / was / now, with "everything else is the same") | New | Used by second approval and the history detail. |
| `VersionTimeline` | New | Used by criteria history. |

## 3. Routes

### `/lead` — the home of the shift
Boards: **Overview**, **A service to chase opens**, **A quiet shift**, **Loading and a failed read**, **Phone: the shift**.

- **States.**
  1. *Busy:* three attention counters (to chase, to check, reviews due), the chase cards in order of how overdue, "getting old" cards, two closed disclosure rows (criteria to review, declined despite capacity). Right column fixed: System now (five counts with shapes, "n services reporting today") and Covering today.
  2. *A chase opens:* the chosen card takes the left area with the full ladder (text, reminder, advisor phone task, escalation); "Enter what they told me by phone" opens in a right sheet over the counters column (the counters stay visible and fixed). Closing returns to state 1.
  3. *Quiet:* "Nothing needs chasing", "Due next" by time, the same right column. Never an empty card.
  4. *Loading:* skeleton in the same layout. *Failed read:* amber alert with "Try again"; the last good page stays, dimmed, with actions that need fresh data disabled; an empty list is never shown for a failed read (H-330).
- **Components.** Reuse `ChaseCard` (rework: ladder inline as four steps, opens full), `OldFigureCard`, `CoveringList`, `SystemCounts`, `LeadPhonedDialog` (becomes a side sheet). New: `AttentionStat`, `LadderTimeline`, `DisclosureRow`.
- **Data.** Existing: `GET /api/bff/lead/overview` (chasing with ladder, gettingOld, covering, counts, reportingToday), `POST /api/bff/lead/services/[id]/remind`, `POST /api/bff/lead/services/[id]/phoned`, the events stream `/api/bff/events` for refresh, `GET /api/bff/lead/flags` for the "to check" count.
  **Missing:** (a) the aggregate "criteria reviews due soon" for the lead (the original ShiftLead artboard has it; `LeadOverview` does not): needs either a new field on the overview or a list endpoint over the services' `reviewBy`; (b) "declined despite showing capacity today" (the original artboard has it; the planning analysis computes something similar, not in the lead overview); (c) "Send review reminder to owners" has no route. Until (a) and (b) exist, show those two rows only when data is present, and keep the "reviews due" counter to the flags and chase counts.
- **Motion.** Chase card opens with the height ease and the content spring; the sheet slides in over 280 ms; counters never animate. The clock updates by the minute with no animation.
- **A11y.** The overview refresh is announced politely only for new chases ("A service needs chasing"), never for count changes. Ladder steps are an ordered list with each step's state in words, not only a dot. The sheet traps focus and returns it to the card button.
- **Phone.** One column: attention chips in a row, the chase card with the primary button full width, "System now" as five small counts, bottom bar. The ladder is one line of text ("Text 12:00 done · Reminder 12:30 done · Phone task not done · Escalated to you").

### `/lead/services/new` — add a service
Board: **Add a service: four steps that morph** (interactive).

- **States.** Step 1 *The service* (name, category, what is counted, unit label, established capacity, usual low and high, hours) → step 2 *Who reports* (text or email, number or address, role holding the phone, cadence) → step 3 *Who it takes* (needs accepted and not accepted, ages, districts, review-by date, criteria owner) → step 4 *Check* (three summary cards, each with "Change", a warning that advisors will see the criteria at once) → *Added* (next action: invite the reporter). From step 2 the summary pins on the left.
- **Components.** Reuse the field set and validation in `AddServiceForm.tsx` and `lib/lead/serviceForm.ts`, split into four step components over one form state. New: `StepBar`, `MorphStage`, `SummaryPin`. Validation runs per step on "Next", summary of problems at the top of the step, focus to the first. The steps are real routes or a `?step=` query so Back and a reload work; the form state lives in the page, saved on each step in memory only (nothing stored in the browser).
- **Data.** Existing: `POST /api/bff/lead/services` with an `Idempotency-Key` per attempt (one key for the final submit); the body already carries every field on steps 1 to 3 except the owner.
  **Missing:** "Who owns these criteria" is not in the body (`lib/lead/serviceBody.ts` has `reviewBy` only). Either add `criteriaOwner` (the role or the reporter by default) end to end, or drop the field from the design. The `Invite the reporter` link uses the existing `/lead/reporters/invite?service=…`.
- **Motion.** Step to step: columns ease about 0.5 s, the new layer springs in last. Keyboard "Next" with Enter changes step with no animation.
- **A11y.** Each step is a labelled group; the step bar is a nav with `aria-current="step"`; errors are linked from the summary. The success state moves focus to its heading.
- **Phone.** One step per screen, the summary becomes a one-line pill under the bar that opens a sheet, "Next" fixed at the bottom.

### `/lead/scope` — services in scope
Board: **Services in scope**.

- **States.** List with filters (All, In pilot, Later, Out of scope) and a state mark per service (live, paused, in review, not invited, re-verify due); "Invite" only for in-pilot services not yet invited; the add form opens in a right panel (reason required unless in pilot, with the "no patient information" hint and the 280 character count); success banner "Added … to the scope list. It can be invited now." with Invite. Failed read: banner with "Try again", list absent.
- **Components.** Reuse `ScopeList`, `AddScopeForm` (move to a panel), `Banner`. New: filter chips, `StatusMark` for lifecycle.
- **Data.** Existing: `GET /api/bff/scope`, scope add (`/api/bff/scope`), `canInvite`, `flagLabel`, `stateLabel`, `categoryLabel` in `lib/registration/model.ts`. Counts in the filter chips are computed on the client.
- **Motion.** Panel slides in; filters do not animate list items beyond a 120 ms fade.
- **A11y.** Filters are `aria-pressed` buttons with the count in their name. The panel is a labelled region, not a modal, so the list stays readable.
- **Phone.** Cards instead of rows; the panel is a full-screen sheet.

### `/lead/coverage/[serviceId]` — where a service goes
Board: **Where a service goes**.

- **States.** Districts, days and response target on the left; a live preview on the right ("How advisors will see it", the overlap warning with the other service named, and "Where coverage runs out" linking to `/planning/coverage`). Saved banner; failed save keeps the values.
- **Components.** Reuse `components/areas/CoverageForm.tsx` and `overlapWith`; new preview card.
- **Data.** Existing: `GET/PUT /api/bff/lead/services/[id]/coverage` (the form, `available` districts, `overlapWith`). **Missing:** the "no service covers DT7 to DT11 at weekends" sentence needs the planning coverage gaps for this service's tenant; `GET /api/bff/planning/coverage` exists for the planning surface, so reuse it if the lead role may read it, otherwise omit the card.
- **Motion.** Preview updates in place with no animation (it is a figure); the overlap panel opens with the height ease.
- **A11y.** The overlap panel is a polite status; the district chips are a labelled group with "n of 11 chosen".
- **Phone.** The preview collapses under the form as a disclosure.

### `/lead/phones` and `/lead/phones/move`
Boards: **Phones and services**, **Move a service**.

- **States (phones).** Row per phone (last four digits, role and services, channel, last seen, flag); one row opens to show services on the phone, coverage area, usual reports and the actions (change number, move, edit coverage, remove access). A flagged phone says why in words with a shape.
- **States (move).** One card: which service, to which phone, for how long (for good, or until a date), "Start the move"; the right panel always shows the three steps (we text the new phone a code, you phone the service on the register number, the service goes to the new phone) and "Nothing moves until step 3".
- **Components.** Reuse `PhonesList`, `MoveServiceForm`. New: the opening row, `LadderTimeline` for the three steps (reused from the chase ladder).
- **Data.** Existing: `GET /api/bff/lead/phones`, `POST /api/bff/lead/services/[id]/move`, `/api/bff/lead/reporters/number` for change number. **Missing:** "Usual reports" (cadence and time) is not on the phones row; add it or drop it from the open row.
- **Motion.** The row opens with the height ease. The move steps do not animate; the first step gets its done mark when the code is sent.
- **A11y.** The table becomes a list with real headings per row; the open row is a disclosure with `aria-expanded`. The mobile numbers are only ever the last four digits.
- **Phone.** Phones as cards, tap to open.

### `/lead/services/[id]/suspend`
Board: **Suspend and resume a service** (interactive).

- **States.** 1 *Suspend* (what happens at once, then "Why?" with four reasons, one danger-toned button naming the service) → 2 *Suspended* (since when, how many open requests expired, the service was told by text; "Phone the service", "Resume") → 3 *Resume* (two checks, both needed: I phoned on the register number; the reason is resolved) → 4 *Resumed*. A pinned card carries the service and its state chip, which changes shape and word (circle "Reporting" to square "Suspended").
- **Components.** Reuse `SuspendService.tsx` and its copy; new `MorphStage`, the pinned state card.
- **Data.** Existing: `POST /api/bff/lead/services/[id]/suspend` (reason), `/resume` (`reasonResolved`), `/phoned` for the call. All counts shown (expired requests, since) are in the existing answer.
- **Motion.** The chip's shape change is the one expressive moment; the rest is the standard step morph.
- **A11y.** The reason is a radio group; the confirm button is not the default focus; the resumed state announces "UCR East is back".
- **Phone.** Same four screens; the two checks are large rows.

### `/lead/people/remove`
Board: **Remove someone's access**.

- **States.** Form (who, why) with a "What happens" panel beside it; the confirm is an `alertdialog` naming the person and the reason; success banner.
- **Components.** Reuse `RemovePersonForm`; new `ConfirmDialog`.
- **Data.** Existing: `POST /api/bff/lead/people/remove`. The "who" field takes a role or the last four digits; a lookup would need a people search for reporters, which does not exist (use the phones list's open row "Remove access" to pre-fill instead).
- **A11y.** Dialog focus on the safe button; the destructive button names the person ("Remove access for ···0377").
- **Phone.** Same, full-width buttons.

### `/lead/flags`
Boards: **Reports to check**, **Phone: reports to check**.

- **States.** Tabs To check (n) and Checked; master list of flags on the left, the open flag on the right with the reason in words, the last reports, and the actions explained (phone to confirm, mark as checked, accept the figure, suspend). Empty: "No reports to check". Failed read: alert with Try again.
- **Components.** Reuse `ReportFlags`, `LeadPhonedDialog`. New: `FlagList`, a small `FigureStrip` (last five figures).
- **Data.** Existing: `GET /api/bff/lead/flags?tab=`, `POST /api/bff/lead/flags/[id]` (checked or accept), `phoned`. **Missing:** the "last reports" strip and the usual range are not in the flag resource (id, service, reason only). They need the service's recent figures; the reporter history endpoint is for the reporter. Add a lead read of a service's last five figures, or leave the strip out (the screen still works with the reason and the actions).
- **Motion.** None beyond the list/detail swap fade.
- **A11y.** The tabs follow the tab pattern; the footnote ("flagged by rules…, never used to assess advisors") stays visible.
- **Phone.** List first; a tap opens the flag full screen with the primary "Phone to confirm" fixed at the bottom. (The board shows the first flag already open.)

### `/lead/audit` and `/lead/audit/[ref]`
Board: **Audit replay**.

- **States.** Search (reference field) and the replay side by side on wide screens, one after the other on phones. Replay: integrity banner (passed, or a warning "do not rely on it"), services shown with state mark, figure and age, criteria versions, timeline, export.
- **Components.** Reuse `AuditSearch`, `AuditReplay`; new `StatusMark` in the rows.
- **Data.** Existing: `GET /api/bff/lead/audit/[ref]`, `/export`. "Looked at today" is optional and would have to be kept for the session only, in memory; do not store references in the browser.
- **A11y.** The integrity result is a status, not only an icon. The timeline is an ordered list.
- **Phone.** Not required (an investigation task); the layout stacks.

### `/lead/screens` and `/lead/screens/new`
Boards: **Wall screens**, **Add a wall screen** (interactive).

- **States (list).** Card per screen with a small preview thumbnail, status (online, not showing the board, waiting for a code, never connected), where it is, last seen, which board it shows; actions per state (change the board, pair again, unpair); unpair opens an inline confirm on the card. A screen set to a network that is no longer open says so.
- **States (pair).** 1 enter the code, name, place → refused code (words, values kept) → check ("Is this the right screen?": for whom, when it first asked, what kind) → connected. The screen preview on the left changes from the code to the live board.
- **Components.** Reuse `ScreenList`, `ScreenUnpair`, `ScreenBoardChoice`, `components/screens/ScreenForm`. New: `ScreenCard`, `ConfirmDialog` use.
- **Data.** Existing: `GET/POST /api/bff/screens`, `screens/preview`, `screens/[id]/board-scope`, `screens/[id]/revoke`, `screens/pairing`. The thumbnail is drawn from the board's counts, not a screenshot (no new data).
- **Motion.** The preview crossfades when connected; nothing on the list moves.
- **A11y.** Code input announces the format; the refusal is an alert; "last seen" is a time element.
- **Phone.** Not required for the list; the pairing flow works as a stack.

### `/criteria`, `/criteria/[serviceId]`, `/criteria/[serviceId]/approve`, `/criteria/[serviceId]/history`
Boards: **Criteria owner: review, change, send** (interactive), **Second approval**, **Criteria history**, **Phone: second approval**, **Phone: review due**; the landing is on **Patterns**.

- **States.** Owner: 1 *Review* (due notice, the criteria, "Still right", "Change") → 2 *Confirm* (review again in 3, 6 or 12 months, "I confirm") or 3 *Change* (changed fields marked "Changed" with what they were) → 4 *Preview* (what advisors will see, what changed) → 5 *Send* (why, review again in, "Send for second approval", a line that the author cannot approve) → 6 *Waiting* (version 2 stays live). The pinned card carries the live version and a state chip that changes when a change is waiting.
  Approver: the diff is the screen (what, was, now), the reason and the sender, "Approve version n", "Send it back with a note"; the full criteria open on request.
  History: a timeline of versions with state (waiting, live, replaced), review-by, and what changed for the live one.
  Landing: with several services, a list ordered by what is due; with one, straight in; with none, "No services to review" and Help.
- **Components.** Reuse `CriteriaOverview`, `CriteriaEditor`, `CriteriaPreview`, `CriteriaConfirm`, `CriteriaSend`, `CriteriaStatus`, `CriteriaApproval`, `CriteriaHistory`, `OverdueNotice` and their `lib/criteria` rules; the flow (`CriteriaFlow`) becomes the `MorphStage`. New: `DiffTable`, `VersionTimeline`, `StepBar`.
- **Data.** Existing: `GET/PUT /api/bff/criteria/[serviceId]`, `/submit`, `/confirm`, `/pending`, `/pending/decision`, `/history`. **Missing for the history board:** who sent and who approved each version, when, and what changed from the previous version (the history parse reads version, status and review-by only). The board shows them as a better design; without them show version, state and review-by. The landing page lists services by id only (the session carries ids); showing names and review dates needs the criteria overview per service or a list endpoint.
- **Motion.** Step morph as above; the approver's diff does not animate (it is the content being judged).
- **A11y.** The two-person rule is said in words on both sides. "Changed" is a word, not a colour. The approve button is never the initial focus on the approver's screen; the diff is.
- **Phone.** Review due and second approval are designed for the phone (the owner and the approver are often not at a desk).

## 4. Routes on this surface and the board that shows each

| Route | Board |
|---|---|
| `/lead` | Overview, A service to chase opens, A quiet shift, Loading and a failed read, Phone: the shift |
| `/lead/services/new` | Add a service (interactive) |
| `/lead/scope` | Services in scope |
| `/lead/coverage/[serviceId]` | Where a service goes |
| `/lead/phones` | Phones and services |
| `/lead/phones/move` | Move a service |
| `/lead/services/[id]/suspend` | Suspend and resume (interactive) |
| `/lead/people/remove` | Remove someone's access |
| `/lead/flags` | Reports to check, Phone: reports to check |
| `/lead/audit`, `/lead/audit/[ref]` | Audit replay |
| `/lead/screens` | Wall screens |
| `/lead/screens/new` | Add a wall screen (interactive) |
| `/criteria` | Patterns (landing) |
| `/criteria/[serviceId]` | Criteria owner (interactive), Phone: review due |
| `/criteria/[serviceId]/approve` | Second approval, Phone: second approval |
| `/criteria/[serviceId]/history` | Criteria history |

Out of this surface (provider onboarding canvas): `/lead/registrations`, `/lead/registrations/[id]`, `/lead/reporters`, `/lead/reporters/invite`, `/lead/reporters/number`. The overview and phones list link to them.

## 5. Suggested build order

Each step can ship on its own; later steps reuse earlier pieces.

1. **Shared pieces** (needs the app frame from the shell work): `StatusMark` shapes, `ConfirmDialog`, lifted `Field`/`ErrorSummary`, `Disclosure` moved to `components/ui`, `MorphStage`, `StepBar`, `SummaryPin`. Everything below depends on these.
2. **Suspend and resume, remove access, wall screens (list and pairing).** Self-contained, existing data, and they prove `MorphStage`, `ConfirmDialog` and `StatusMark`.
3. **Flags, audit, phones, move.** List/detail pattern and the open row; reuses `LadderTimeline`. The flags strip waits on the missing data.
4. **Criteria owner flow, approval, history.** Reuses `MorphStage`, adds `DiffTable` and `VersionTimeline`. Phone variants for review due and approval ship with it.
5. **Add a service, scope, coverage.** The longest forms; depends on `StepBar`, `SummaryPin`. Ship the owner field only if the back end change is agreed.
6. **The shift lead overview.** Last, because it links to everything above and has the open data gaps (criteria reviews due, declined despite capacity). Ship the chase card, the counters and the right column first; add the two disclosure rows when their data exists. Include the loading and failed states from the first release.

Back end gaps to decide before steps 3, 5 and 6: (a) last five figures and usual range for a flagged service; (b) criteria owner on service creation; (c) lead-level criteria reviews due and declined-despite-capacity; (d) phones row "usual reports"; (e) approvers, times and diffs in the criteria history.

## 6. Open design questions

1. **The pinned summary on phones.** It becomes a one-line pill that opens a sheet. Is that enough, or should the steps be separate screens with a progress bar?
2. **"Who owns these criteria".** Default to the reporter's role, or ask for a named person at setup? (Needs the back end answer above.)
3. **Counters on the overview** are three at the top plus the System now column. Are three the right three (to chase, to check, reviews due), or should "getting old" be one?
4. **Interactive boards switch state with buttons** so the morph can be judged; in the product each state is reached by the person's own action. The boards do not show Back-button behaviour; the build must.
5. **Role chip contents on the owner rail:** the owner can also hold other roles; it follows the shell work.

## 7. What was not verified

- Nothing was opened in a browser; the canvas follows the page code and the original canvas text.
- Sample copy (service names, times, the reason text, the "Looked at today" list) is illustrative.
- No endpoint was called. Each "Existing" claim is from the BFF route files and the page components, not a live call.
- Contrast was chosen from the design system's tokens and not measured on these boards.
