# Redesign: provider onboarding and registration

Implementation brief for the boards in the canvas **Overwatch redesign: provider onboarding**
(https://claude.ai/artifact/WWVRqNtenEKms9PGRps1c8). It is written for the people who will plan and build the
work. Nothing here changes the back end; where the design needs something the back end or the BFF does not give
today, it is listed under "Gaps" and the design says what to show until it exists.

The visual language, the staff shell (rail, top bar, role chip) and the morph rules are those of the main
redesign canvas (https://claude.ai/artifact/Nb8Zzui3LuDhQbqe8vjdku, board "The rules of the morph"). This brief
covers only what is specific to this surface.

## What this surface is

Four journeys, one product look:

| Journey | Who | Where | Phone or desktop |
|---|---|---|---|
| Invite and track | Shift lead | `/lead/reporters`, `/lead/reporters/invite`, `/lead/reporters/number` | Desktop first, phone works |
| First-run set-up | The person who reports capacity | `/i/[token]`, `/setup/*` | Phone only (a centred 480px column on a desktop) |
| Register a service | The service's own staff | `/register/*` | Phone and desktop equally |
| Review a registration | Shift lead | `/lead/registrations`, `/lead/registrations/[id]` | Desktop first, phone for the call-back |

## Rules that apply to every route here

1. **Layout changes only when the person chooses something.** Data arriving never moves a block.
2. **Anchors stay put.** Staff pages: rail, top bar, role chip. Provider phone pages: the top bar with the service
   chip, the five-segment progress, and the sticky action at the bottom.
3. **One primary action per screen**, the one big blue button. Everything else is a secondary or a text link.
4. **Status is a word plus a shape**, never colour alone: `◔ In review`, `▲ Needs changes / Stuck / Needs
   attention`, `✓ Complete / Approved`, `● Live / In progress / Active`, `✕ Not approved`, `◆ Review due`,
   `○ Invited / Not started`. One shared `StatusTag` component draws all of them.
5. **Every state has an address.** A step or a check is a URL or a `?step=` value, so Back, reload and a link land
   in the same place. No state lives only in component memory.
6. **Motion** uses the existing tokens (`--dur-*`, `--ease-*`, zero under reduced motion). Grid tracks ease
   (`--ease-drawer`, about 0.55 s) when a column opens or narrows; the content inside settles with a short spring
   (`cubic-bezier(0.34, 1.56, 0.64, 1)`); a height never springs. Typing, Enter and arrow keys never animate.
7. **Text 4.5:1, targets 44px or more** (the primary buttons are 52 to 60px), 320px must work.

## Shared building blocks

| Block | Status | Notes |
|---|---|---|
| `StageGrid` | New | The layout-morph primitive: a grid with named areas and a `data-stage` value; each stage sets `grid-template-columns` (animated) and which areas are visible. Areas are `list`, `stage`, `side`. Used by Reg, Review and the lead's reporters page. |
| `StageLayer` | New | One absolutely stacked content layer in the stage: opacity and a small translate by whether it is before, at or after the current stage; `inert` and `aria-hidden` when not current. |
| `ProviderShell` | New | The phone frame: top bar (mark, service chip), `SetupProgress`, content, `StickyAction`. Used by `/i`, `/setup/*` and `/register/*`. |
| `SetupProgress` | New | Five segments, `aria-label="Step 2 of 5"`. |
| `StickyAction` | New | Bottom action bar with a fade, safe-area padding, one primary and one optional text link. |
| `StatusTag` | New | The shapes and words above. |
| `Disclose` | Exists (`components/admin/Disclose.tsx`) | Progressive disclosure row with the grid-rows transition. Reused for "More about your organisation", "Who it is for", the API question. |
| `Skeleton`, `Loading` | Exists (`components/ui/Skeleton.tsx`) | The shared shimmer. Every list and detail below uses it while loading. |
| `Avatar` | Exists (`components/admin/Avatar.tsx`) | Not needed here. |

## Journey 1: shift lead, invite and track

Routes: `/lead/reporters`, `/lead/reporters/invite`, `/lead/reporters/number` (boards: **Shift lead: invite a
reporter**, **Shift lead: track set-up and fix a stuck one**). These three routes become **three states of one
page**, so the list of invitations never goes away.

| State | URL | Grid areas |
|---|---|---|
| Browse | `/lead/reporters` | `list` full width; `stage` collapsed (0px) |
| Compose | `/lead/reporters/invite?service=<id>` | `list` 420px, `stage` 1fr = the compose panel (form left, the text preview right) |
| Detail | `/lead/reporters?invitation=<id>` | `list` 340px, `stage` 1fr = the timeline left, the actions right |
| Change number | `/lead/reporters/number?service=<id>` | the Detail state with the "Change their number" row open |

- **Components.** Existing: `SetupTracker` (data parsing, `stuckAt`, `SETUP_STEPS`), `InviteForm`,
  `ChangeNumberForm`. Change: split `SetupTracker` into a `ReporterList` (rows with `StatusTag` and a 7-segment
  bar) and a `ReporterDetail` (timeline plus actions). New: `InvitePreview` (the text bubble that follows the form),
  `StageGrid` use. The filter chips (All, Stuck, In progress, Complete) are client side over the same list.
- **Data (existing).** `GET /api/bff/lead/reporters` (rows: service, role, `steps` booleans, `invitedAt`,
  `lastSeen`), `POST /api/bff/lead/invitations`, `POST …/lead/invitations/[id]/resend`,
  `POST …/lead/invitations/[id]/switch-to-text`, `POST /api/bff/lead/reporters/number`,
  `GET /api/bff/lead/services` (the service choices; only pilot services can be invited).
- **Gaps.** The detail timeline in the design shows a time per step and the channel chosen. The tracker data has a
  boolean per step, `invitedAt` and `lastSeen` only. Until the back end adds per-step times and the chosen channel,
  show the time only for "Invited" and the last-seen line, and omit the channel text. The masked number in the
  detail header is also not in the row today; show the role and the invited time only if it is not added.
- **Phone.** The list is the page; choosing a row pushes the detail as a full-screen step (a back arrow at the top
  left), and the actions become a sticky bottom stack with Resend as the primary. The compose form is one column and
  the text preview sits under the Send button, collapsed to one line with a Show text disclosure.
- **A11y and motion.** The list is a `ul` of buttons (`aria-current` on the open row). The preview is a polite live
  region updated on blur, not on each key. The stuck row's amber is a border plus the word and the `▲` shape.
  Opening the stage uses the grid-track morph; on the phone it is a normal route push.

## Journey 2: provider first-run set-up (phone)

Routes: `/i/[token]`, `/setup?step=welcome|number|code|channel`, `/setup/home-screen`, `/setup/notifications`,
`/setup/pin`, `/setup/all-set`, `/setup/done` (boards **1 The invitation text** to **8 All set**, and **States**
for the expired link and the text or email ending).

- **One screen, eight states.** The same `ProviderShell` stays; the middle slides 24px and fades with the spring
  settling, and the progress segment fills. Step 1 of 5 is the number check; the code entry is the same step (the
  masked number collapses into a summary row above the code boxes). Steps 3 and 4 (home screen, notifications) are
  skipped for text and email, exactly as `SetupFlow` does today (including the exec shortcut from the code step to the
  home screen).
- **Components.** Existing: `InvitationLoader`, `SetupFlow`, `Welcome`, `NumberStep`, `CodeStep` (inside SetupFlow),
  `HomeScreen`, `Notifications`, `PinSetup`, `AllSet`. Change: wrap them in `ProviderShell` and replace each page's
  own header and button row with `SetupProgress` and `StickyAction`; the channel choice becomes three radio cards
  (`role="radiogroup"`, Recommended tag on App notification); the PIN keypad becomes 92px keys with auto-advance at
  six digits and no Continue button (the existing confirm-once-more behaviour stays).
- **Data (existing).** `GET /api/bff/invitations/[token]` (what `InvitationLoader` reads),
  `POST /api/bff/identity/invitation-code` and `/verify`, `GET /api/bff/reporter/setup-summary`
  (`service`, `contactBy`, `maskedPhone`, `nextUpdateDue`, `textCodeInDays`). The PIN and channel writes are the
  existing ones.
- **Gaps.** The All set board shows "Your role" and "PIN set". `setup-summary` has neither; show the summary the
  endpoint gives (service, contact by, phone, next update) and drop the role and PIN rows if they are not added.
- **Phone, 320px.** Written for 390px; the code boxes use `repeat(6, minmax(0, 1fr))` and the keypad
  `repeat(3, minmax(0, 76px))` at 320px. A desktop browser shows the same column at 480px centred.
- **A11y and motion.** The progress is `aria-label="Step 2 of 5"`, never colour alone. The code boxes are one
  `input` with `inputmode="numeric"` and `autocomplete="one-time-code"` drawn as six boxes (not six inputs). Focus
  moves to the page heading on each step. Slides and springs are off under reduced motion; the keypad has none.
  `i/[token]` with a bad or expired token shows the Expired state (States board) with no request made.

## Journey 3: register a service

Routes: `/register`, `/register/services`, `/register/[id]/start|organisation|location|service|reporting|review|
submitted|status` (boards **Prototype: register a service**, **Phone: sign in / a step with problems / review**,
**After submitting: every status, and My services**). A service is registered **only from an invitation** (the
existing `MyServices` rule): there is no "Register another service" button; the design says "A new service comes by
invitation from your shift lead".

- **Desktop layout states** (one prototype, six stages, a `StageGrid` with `list | stage | side`):

  | Stage | URL | list (checklist) | stage | side (help) |
  |---|---|---|---|---|
  | Start | `…/start` | 300px | start card | 0 |
  | Organisation | `…/organisation` | 300px | form | 300px |
  | Location | `…/location` | 300px | form | 300px |
  | Service | `…/service` | 300px | form with disclosures | 300px |
  | Reporting | `…/reporting` | 300px | form | 300px |
  | Review | `…/review` | 300px | five rows | 0 |
  | Submitted | `…/submitted` | 0 | confirmation | 0 |

  The checklist (Organisation, Location, Service, Capacity reporting, Review) is both the progress and the
  navigation; it stays visible so no one loses their place. Each entry shows `StatusTag` words: Not started, In
  progress, Complete, Needs attention.
- **Progressive disclosure inside a step.** The Service step is the heavy one: "The service" is open;
  "Who it is for", "Criteria owner and review date" and "Area you cover" are `Disclose` rows that summarise their
  content when closed and flag `▲ Needs a review date` when something is missing. The Organisation step hides role,
  parent organisation and similar fields under "More about your organisation". The API question is a closed row.
- **Components.** Existing: `SignInForm`, `OrganisationForm`, `LocationForm`, `ServiceForm`, `ReportingForm`,
  `ReviewList`, `StatusPage` with `status/*` (`InReview`, `NeedsChanges`, `Approved`, `Live`, `NotApproved`,
  `Reverify`), `MyServices`, `StatusTracker`. Change: put the forms in the `StageGrid`; add the checklist
  (`RegistrationChecklist`, new) and the help column (`StepHelp`, new, a short "Why we ask" per step). The status
  screens become cards in the same shell (the board shows all of them side by side for review). Review: Submit stays
  disabled until all five sections are complete and says how many need attention (existing rule), with a **Fix this**
  button on the section that needs it.
- **Data (existing).** `GET /api/bff/registrations/mine`, `GET /api/bff/registrations/[id]` and
  `…/steps/[step]` (the step reads and writes), `POST …/submit`, `GET …/status`, `GET /api/bff/addresses?postcode=`
  (the address picker), `POST /api/bff/identity/invitation`, `/identity/code`, `/identity/code/verify` (sign-in),
  `…/test` (send the test notification), `…/confirm-details`, `…/review-request`.
- **Gaps.** (1) The design shows an ODS lookup result on the Organisation step ("Found on the register: UCR East ·
  RXX01 · active"). There is no applicant-side ODS lookup route; the registration is checked on the review side.
  Until there is one, show the plain input and the "checked by your shift lead" note. (2) The "Saved a moment ago"
  note needs the save call's result to be shown; the steps routes already return on success. (3) "We aim to review
  within a working day" is copy that must come from configuration, not be hard-coded.
- **Save and return.** "Save and come back later" is in the top bar at every step (not only at the end), keeps the
  existing `?saved=1` landing, and the invitation link returns to the same step.
- **Phone.** Steps stack one at a time with `SetupProgress`, the checklist becomes the review page, the help column
  is a "Why we ask" disclosure under each step's title, and Continue is the `StickyAction`. Errors: a polite
  summary at the top (`role="alert"`, "▲ 3 problems to fix", each a link to its field) and inline messages under
  each field; the field border and the `▲` shape carry it, not colour alone.
- **A11y and motion.** Step changes move focus to the step heading; the checklist is a `nav` with `aria-current="step"`.
  Disclosure rows are `button` + `aria-expanded`. The layer transition is skipped under reduced motion.

## Journey 4: review a registration (shift lead)

Routes: `/lead/registrations`, `/lead/registrations/[id]` with `?step=callback|scope|decide|go-live`
(boards **Prototype: review a registration**, **The automatic checks, every state**, **Phone: the queue**, **Phone:
review and decide**).

| Stage | URL | list (queue) | stage |
|---|---|---|---|
| Queue | `/lead/registrations` | 1fr (cards up to 760px) | 0 |
| Overview | `…/[id]` | 380px | automatic checks left, "Checks you do" right |
| Call back | `…/[id]?step=callback` | 300px | the call-back check |
| Scope | `…?step=scope` | 300px | four answers and a decision |
| Decide | `…?step=decide` | 300px | what is missing, a note, three buttons |
| Go live | `…?step=go-live` | 300px | the approval, the test and Set live |

- **Components.** Existing: `RegistrationQueue`, `RegistrationOverview`, `registration/CallBackCheck`, `ScopeCheck`,
  `DecideStep`, `GoLive`. Change: render the queue and the detail together in a `StageGrid` (the queue narrows when
  a registration opens); the "Checks you do" list becomes the stepper (each row is a link to its `?step=`). New: a
  `CheckList` for the automatic checks (shape plus word, the first problem copied into the queue card).
- **Automatic checks and DEC-1323.** The design shows every state of every check (board **The automatic checks**).
  The address check has a new state: with **no area set on the organisation, the address check passes
  ("No area limit is set") whenever an address was found**, so providers can join from anywhere. The queue card
  shows only the first problem; the overview shows all. A check that needs attention never blocks the review: the
  existing back-end list of what is missing before Approve is the only gate (`DecideStep` reads it, it is never
  worked out in the page).
- **Data (existing).** `GET /api/bff/registrations` (the queue, one answer per tab with counts),
  `GET /api/bff/registrations/[id]/review`, `POST …/callback`, `POST …/scope`, `GET|POST …/decision`,
  `POST …/go-live`, `GET …/test`.
- **Gaps.** The clinical lead's second approval is a different person on a different screen (the spec's
  "Second approval" board); it is not designed here. "Approved today 15:00" and the test times need the review
  answer to carry them; show only what it returns.
- **Phone.** Queue as cards with a full-width Review button, the overview as a short list with the first problem
  first and "Show 2 more checks that passed" folded, "Checks you do" as four tappable rows, each check a full screen;
  the call-back screen puts **Phone** (a `tel:` link to the register's number) as the primary action.
- **A11y and motion.** The queue is a `ul`; the open row has `aria-current`. Each check is a heading level 2 with
  "Check n of 4" above it. The grid-track morph is reduced-motion safe. "Approve" is a real disabled button that says
  what it waits for, not a hidden one.

## States on every list and detail

Board **States**: loading (the shared shimmer in the shape of the content, with a spoken "Loading the …"), empty
(says what to do next and offers the one action), error (`▲`, says nothing was lost, one Try again), a refused
send (inline under the field, plus the pilot-scope message), success (a `✓` banner that says what happens next),
the expired link, and the text or email ending of the set-up. These replace each page's ad hoc messages.

## Gaps (what the design needs that does not exist yet)

1. Per-step times and the chosen channel in the set-up tracker row; the masked number.
2. `role` and PIN state in `/reporter/setup-summary`.
3. An applicant-side ODS lookup (for the "Found on the register" confirmation on the Organisation step).
4. The expected review time as configuration.
5. The second-approval screen for the clinical lead (outside this surface).

None blocks the build: each has a fallback noted above, and the design reads the same without it.

## Suggested build order

1. **Primitives:** `StatusTag`, `StageGrid` and `StageLayer`, `ProviderShell`, `SetupProgress`, `StickyAction`.
   Everything else depends on these. (Skeleton and Disclose exist.)
2. **Provider set-up (Journey 2).** Highest value and fully phone: wrap the existing steps in `ProviderShell`, new
   channel cards and PIN keypad. No back-end change.
3. **Registration forms (Journey 3, forms only).** Put the existing forms in the `StageGrid` with the checklist and
   the help column; add the disclosures; keep the data calls unchanged.
4. **Registration status and My services** (needs the `StatusTag` and cards only).
5. **Review (Journey 4).** The queue and detail in a `StageGrid`; then the automatic checks list including the
   no-area state; then the phone variant. Depends on 1 only.
6. **Invite and track (Journey 1).** Merge the three routes into one page with the `StageGrid`. Depends on 1; the
   data gaps do not block it.
7. **States pass.** Replace each page's loading, empty and error messages with the shared ones.

Steps 2 and 5 can run in parallel after step 1; step 3 before 4; step 6 any time after 1.

## Open design questions

1. **Desktop for the provider set-up.** Designed phone-first with a 480px centred column on a desktop. Should a
   desktop show a side panel with "what we will ask"? Not designed.
2. **"Register another service".** The canvas text has this button; the built `MyServices` says new services come
   by invitation only. The boards follow the built behaviour. Which is right?
3. **ODS lookup on the applicant side** (Gap 3): is it wanted, given the shift lead already checks the code?
4. **Review time copy** ("within a working day"): who owns the wording?
5. **Wall board and criteria owner onboarding** (`ScreenPairing`, `CriteriaOwner`) are separate surfaces and are
   not on these boards.

## Not in this surface

`/lead/scope`, `/lead/services/new`, `/lead/services/[id]/suspend` (service set-up), `/criteria/*`, `/app/*` (the
reporter app proper), `/screen/*`, the operator and administration consoles. They have their own boards.
