# Redesign brief: administration, operator console and public pages

Status: design, not built. Canvas: https://claude.ai/artifact/WhA15eqK4pUFc8AiEtozb8 ("Overwatch redesign:
administration, operator and public pages", 28 boards). The look, the shell and the morph rules are those of the
first canvas (https://claude.ai/artifact/Nb8Zzui3LuDhQbqe8vjdku: the advisor call, the Administration board for
People and roles, and "The rules of the morph"). This brief covers 33 routes. Nothing here changes a back-end
endpoint unless a section says **Missing**.

Sibling briefs that share these building blocks: `provider-onboarding.md`, `reporter-app.md` (same folder).

## 0. Rules every board follows

1. **Change follows the person.** A layout changes because someone chose something. Data arriving never moves a block.
2. **Anchors stay put**: rail, top bar, role chip, page header. Only the area under them morphs.
3. **Summary first, detail on demand.** Rows say the answer; one row opens at a time (`Disclose`, grid-rows
   transition 280 to 320 ms, `--ease-drawer`). Small things (chevron, a new row, a chip) may use the spring
   (`cubic-bezier(0.34, 1.56, 0.64, 1)`, `linear()` where supported). A height never springs.
4. **Live figures never animate for style.** Counts, status words and their colours change instantly.
5. **Every state is a URL.** Back, links and reload land in the same state. State in the path or `?step=` / `?open=`.
6. **Status is shape plus word** (`StatusTag`): `● Done`/`● Live`/`● Set` (filled), `◐ Waiting` (half, amber),
   `○ To do`/`○ Not set` (dashed), `▲ Could not ...` (purple, problem). Never colour alone.
7. **Text 4.5:1, targets 44 px or more** (primary actions 52 to 60 px), 320 px wide must work. Keyboard actions
   (typing, Enter, arrows) never animate. Reduced motion: the same states appear at once (the motion tokens are
   already `0ms`).
8. **One primary action per screen**, in the brand blue `#0B5C8C`, with the soft shadow.

## 1. The shared shell: `AppFrame`

Every signed-in surface in this brief (admin, operator) uses one frame, and the staff pages use the same one in the
other brief. It is two components the boards import (`Rail.dc.html`, `Top.dc.html`) plus a page body.

| Part | What it is |
|---|---|
| `Rail` | 84 px dark rail (`#0B2A3D`), the mark, then icon-over-label items (13 px), active item a pale pill, `aria-current="page"`; Help pinned at the bottom. Items come from a list per portal. Below 900 px it becomes a bottom bar of at most five items; the rest go under "More". |
| `TopBar` | 72 px white bar: small organisation line, then the page title (20 px bold), then the **role chip** (right) and Sign out. Optional breadcrumb in the small line ("Organisations ›"). |
| `RoleChip` | Exists: `components/shell/RoleSwitcher.tsx`. Shown only when the session holds more than one role; the back end checks every choice (DEC-1324). The operator chip is a plain label (operators hold one role). |
| `PageHeader` | In the body: title when the top bar carries only the organisation; page-level actions on the right. Used by Overview, Organisations, Support. |

Rail items per portal:

- **Admin:** Overview `/admin`, People `/admin/users`, Contacts `/admin/contacts`, Settings `/admin/config`, Retention
  `/admin/retention`, Email `/admin/email`, Sharing `/admin/sharing`, Access `/admin/access`, Support `/admin/support`.
- **Operator:** Organisations `/operator`, Support `/operator/support`, Audit `/operator/audit`.

What it means for the code that exists:

- `components/admin/AdminShell.tsx` (portals `tenant`, `network`, `operator`) is replaced by `AppFrame` with a
  `portal` prop. Keep the name `AdminShell` as a thin wrapper while pages move, so the three layouts
  (`(tenant-admin)/admin/layout.tsx`, `(network-admin)/network-admin/layout.tsx`, `(operator)/operator/(area)/layout.tsx`)
  change in one line each. The header's wrapping link row (`AdminNav`, `navItems`) goes.
- `components/shell/AppShell.tsx` (staff roles) moves onto the same frame. The role chip is already wired in both.
- `components/operator/OperatorNav.tsx` is retired once the operator layout uses the rail.
- Pages stop drawing their own `<h1>` and `.page` wrapper where the top bar carries the title; the content wrapper
  becomes a `StageGrid` or a single column, per page below.
- The network portal (`/network-admin/*`) is not designed in this canvas. It adopts the same frame unchanged.

## 2. Building blocks

| Block | Status | Used by |
|---|---|---|
| `AppFrame` (Rail, TopBar, PageHeader) | New | every signed-in page here |
| `StageGrid`, `StageLayer` | New (same definition as `provider-onboarding.md`) | Operator funnel, Create organisation, Settings, Support, People |
| `StatusTag` | New (same) | every list and funnel |
| `Disclose` | Exists (`components/admin/Disclose.tsx`) | Overview "Done", Retention table, Settings groups, Contacts rows |
| `Skeleton`, `Loading` | Exists (`components/ui/Skeleton.tsx`) | every load state |
| `Avatar`, `PersonLookup` | Exist | People (first canvas) |
| `SettingGroup` | New | Settings: a group header with count and "n changed" badge, opens one at a time |
| `SettingRow` | New | Settings: "Now X, default Y" with the right control (chips, number, text) and "Use the default" |
| `ApprovalMeter` | New | version detail and Support: n of m segments with names |
| `DiffPair` | New | version detail: Was and Now chips with additions marked "+" |
| `TaskRow` | New | Overview "what needs you": tag, title, one line, one action |
| `ContactRow` | New | Contacts: icon, label and value, status, Edit that opens the form in place |
| `RetentionChips` | New | Retention summary |
| `ProgressBar5` | New | Organisations list and funnel: five segments, `aria-label="4 of 5 parts done"` |
| `TimelineList` | New | Audit chain, access log, versions |
| `SplitHero` | New | operator sign-in, staff sign-in, home and splash (dark brand half, light content half) |
| `StepCards` | New | Tour (six steps) |

## 3. Administration (10 routes)

All load through `GET /api/bff/tenant/overview` unless another call is named. Every write keeps today's
`adminSend` plus idempotency-key and CSRF pattern.

### `/admin` Overview (board A1, "Overview: what needs you")
- **Layout:** two columns, "What needs you" (task rows) left, organisation facts right (340 px).
- **States:** populated; loading (three skeleton rows); error ("We could not load your organisation", Try again);
  all done ("Nothing needs you"). The Done list is a collapsed `Disclose`.
- **Rows (derived, existing data):** support request waiting (`/tenant/support-tickets`, state `pending`), settings
  version needing approval (`/tenant/config/versions`, status pending, approvals n of m), missing coordination phone
  and clinical safety officer (`overview.contacts`), directory not verified, no group mapped (`overview.bindings`,
  `overview.mappings`). Existing `setupSteps` logic in `AdminOverview.tsx` is the source for the last three.
- **Right column:** organisation (name, ODS, zone, status, address), people (counts from `/tenant/groups`), sharing
  (`/sharing`), settings in force (`overview.config`).
- **Missing:** nothing. "Going live is done by the platform team" is fixed words when `tenant.status` is provisioning.
- **Motion/a11y:** rows are a `ul`; the urgent row has a 2 px amber edge and the word "Waiting for you". Nothing animates on load beyond the shimmer.

### `/admin/users` People and roles
Already designed (first canvas, Administration board) and built (`GroupMembers`, `PersonLookup`). The only change is
the frame. Directory binding and group mapping stay under "Directory and group settings".

### `/admin/config` Settings (board A2, interactive)
- **Layout:** left, the find box then three `SettingGroup`s (Clinical, Operational, The names your messages use);
  right (320 px), the versions timeline.
- **States:** closed groups (each says its count); one group open; filter typed (matching groups open, others show
  "n match"); a clinical value changed (group shows "1 changed", the row gets an amber edge, the notice appears
  above Save: "This changes a clinical setting. It needs 2 approvals from people other than you"); Save disabled
  with "Nothing changed yet"; saved (version number, "needs 2 approvals"); stale (409, "The settings changed while you
  were working. Reload").
- **Data:** `GET /tenant/settings` (specs, `safetyClass`, defaults), `GET /tenant/config/versions`,
  `POST /tenant/config/drafts` (`approvalsRequired` returned). The notice is computed client side from
  `spec.safetyClass`, as `ConfigVersions.tsx` already does; the back end stays the check.
- **Motion/a11y:** groups use the grid-rows transition and a springy chevron; `aria-expanded`; the filter is a
  labelled search input; the notice is `role="status"`.

### `/admin/config/[n]` Version detail (board A3)
- **Layout:** left, header (state, approvals, kind) and the `DiffPair`s; right, `ApprovalMeter`, names of approvers,
  the rule that the author cannot approve (and the same words when the viewer is the author), Approve and Withdraw.
- **States:** draft; pending (n of m); current; superseded; loading; not found.
- **Data:** `GET /tenant/config/versions/[n]` and `POST .../approval`. **Missing:** a "Withdraw this draft" call. If
  there is none, the button is omitted and the design says "Ask a platform operator to withdraw".
- **a11y:** the approval bar has an `aria-label` ("1 of 2 approvals"); Was and Now are labelled groups.

### `/admin/contacts` Contacts (board A4)
- **Layout:** four `ContactRow`s, one open at a time, and "How staff will see it" preview on the right.
- **States:** set; not set; "Needed to go live" (coordination phone, clinical safety officer); editing (phone-only kinds show
  the hint and the plain refusal for an email address; email kinds the reverse); saved (row updates, brief highlight).
- **Data:** `PUT /tenant/contacts` (existing validation messages kept).

### `/admin/retention` Data retention (board A5)
- **Layout:** one answer card ("The platform defaults are in use" or "Your own rules are in use"), the chips, then
  "Review or change" (table of eight kinds, one row editable at a time) and "Use the platform defaults".
- **States:** defaults; custom; "n of 8 kinds have a rule" (before go-live); saving; saved; error.
- **Data:** `GET/PUT /tenant/retention`. The copy of the defaults in `RetentionForm.tsx` must follow the back end's
  list (DEC-271); a test should compare them.
- **a11y:** the table is a real table inside a scroll box; the edit row keeps the label of its kind for screen readers.

### `/admin/email` Email sender (board A6, left half)
- **Layout:** two cards, Text messages (read only, set by the platform team) and Email with a two-way choice.
- **States:** not set up; own address (name, address, display name, checked); platform sender in use.
- **Data:** `GET/POST/PUT /tenant/channels`. **Missing:** "Use Overwatch's sender" has no back end today: an email channel
  needs the organisation's own sender, and the platform fallback exists only for platform mail. Build it (a shared
  sender as for texts) or drop the option from the design. Decision for the owner.

### `/admin/sharing` Sharing with the network (board A6, right half)
- **Layout:** organisation code with Copy, three scope rows (Capacity, Service directory, Criteria), History disclosure.
- **States:** not in a network; invited; per scope: not shared, waiting (n of 2), shared since; left the network.
- **Data:** `/api/bff/sharing`, `.../grants`, `.../agreement`, `.../leave` (all exist). Two-person approval words as built.

### `/admin/access` Access log and `/admin/support` Support requests (board A7)
- **Layout:** requests left (the one waiting is open: from, why, Approve or Refuse; after Approve the code card, shown once,
  "I have passed it on" or "Take it back"), access log right as a `TimelineList` with a period filter.
- **States:** a request waiting; approved with code; earlier requests (collapsed); empty ("Nobody has asked"); log empty
  ("Nobody from the platform has accessed your organisation in this time"); loading; error.
- **Data:** `/tenant/support-tickets`, `.../approval`, `.../refusal`, `.../access`, `/tenant/access-log`.
- **a11y:** the code is announced once with `role="status"` and never stored; copy button; the "shown once" words are real text.

## 4. Operator console (9 routes)

Operator pages sit on the rail with the operator item list. The role chip is a label. Requests use the `platform/*` BFF routes.

### `/operator/sign-in` (board O1)
`SplitHero`: brand half and the sign-in card. States: normal; "We could not sign you in" banner. Data: existing start route.

### `/operator` Organisations (board O2)
- **Layout:** search and status chips (All, Being set up, Live), Create an organisation (primary), then one card per
  organisation with a `ProgressBar5` and its next step in words.
- **States:** populated; loading; empty ("There are no organisations yet. Create the first one."); error.
- **Data:** `GET /platform/tenants`. **Missing:** per-organisation "parts done" and "next step" are derived from the detail
  (`lib/operator/funnel.ts`), which needs one read per row. Add `partsDone` and `nextStep` to the list payload, or read
  details lazily for the visible rows.

### `/operator/tenants/new` Create an organisation (board O3)
- **Layout:** three parts as rows (organisation, their Microsoft work accounts, who gets which role), the open part
  expanded, and a "What will be created" card that fills as parts complete.
- **Part 1** NHS name search, the matched record, organisation-type cards (NHS types default to the suggestion, otherwise
  Other), tenant id under "Details". **Part 2** email domain, Look it up, "Directory found", Use this directory; "I already
  have the directory id" is a disclosure. **Part 3** optional, skipped by default (teams are made after consent).
- **States:** searching; no match; record chosen; directory not found; creating; created (goes to the funnel); error.
- **Data:** `GET /platform/ods`, `/platform/ods/[code]`, `/platform/directory-lookup`, `POST /platform/tenants`.

### `/operator/tenants/[id]` The go-live funnel (board O4, interactive; the signature morph)
- **Layout:** `StageGrid` with the five parts on the left (400 px) and the open part on the right. Parts you finish fold to
  one line with their summary; the next part is outlined with "Next"; later parts are dashed. Opening a part swaps the
  right side with a spring settle; the left list updates in place.
- **Parts:** Organisation and sign-in, Administrator approval, Teams and people, Reach and agreements, Go live.
  Go live shows what the organisation's own administrators still have to do (approve settings, contacts, retention,
  names), each as a task, and enables Go live only when nothing is left and the four parts before are finished.
- **States:** per part: not started, in progress, waiting for them (amber, e.g. invitation sent), done; live (banner and
  chip change); error on an action (the part stays open with the problem in words).
- **Data:** `GET /platform/tenants/[id]`, `.../admin-consent` and `.../admin-consent-invitation`, `.../entra-groups`
  (and `/members`), `.../host`, `.../numbers` (+ `/shared`, `/retire`, `/test-text`), `.../references`,
  `.../directory/verification`, `.../activation`, plus `.../suspension` and `.../offboarding` under a "Look after it" menu
  after go-live. Step logic stays in `lib/operator/funnel.ts` (nothing new). The prototype's "their administrators finish"
  button is design only.
- **Motion/a11y:** left parts are buttons (`aria-current="step"`); the right layers are `inert` and `aria-hidden` when not
  current; focus moves to the open part's heading. Completion changes shape and word, not only colour.

### `/operator/support`, `/operator/support/new`, `/operator/support/tickets/[id]` (board O5)
- **Layout:** requests list left, the open request right (three stages: Asked, They approve, You open it); "Ask for access"
  is a right-hand sheet that slides over the page; the code form sits in the request.
- **States:** waiting; approved (enter the code); ended; refused; expired; empty; error; sending.
- **Data:** `GET/POST /platform/support-tickets`, `.../[ticket]`, `.../access`, `.../cancellation`.
- **a11y:** the sheet is a dialog with focus trap and Escape; the code field is a single labelled input.

### `/operator/audit` Audit chain (board O6)
`TimelineList` with filters, a "The chain is intact" card with Check again, and the broken-chain state ("broken at entry n",
nothing hidden). Data: `GET /platform/audit`, `.../audit/verification`. States: intact; broken; empty; loading; error.

### `/admin-consent/return` (board C1)
Public. Outcome page: approved (large), not approved yet (Check again), no longer valid, could not check just now, not
valid. No data beyond the existing server check; the organisation name appears only after the back end confirms.

## 5. Public and cross-cutting (14 routes)

### `/` and `/splash-preview` (board P1)
`SplitHero`: logo, one line, Sign in; "Platform console" as a quiet link. The splash (dev preview only) is one ring and a
dot settling with a single spring, then it hands over. Reduced motion: shown static.

### `/sign-in` (boards P2 desktop, Ph1 phone)
The organisation name from the host profile is the hero ("You are signing in to ..."). States: normal; no access banner;
could not sign you in banner; clinical note. Data: `currentProfile()` (exists). One button.

### `/forbidden` and `/offline` (board P3)
Two calm cards. Forbidden never says what the page is. Offline says nothing shown is current and gives the phone process;
Try again.

### `/help`, `/help/problem`, `/help/safety`, `/help/share` (boards P4, Ph2)
Desktop: a hub, the open form and the support code side by side; phone: the hub, then each form full screen. Forms keep
their fields and warnings ("No patient names or details", the patient-details nudge). States: choose; sending; sent
("Thanks. We have your report."); could not send (words are kept). Data: `/api/bff/help/problems`, `.../safety-concerns`,
and the existing support-code calls.

### `/learn`, `/learn/[lessonId]`, `/learn/[lessonId]/practice` (boards P5, Ph3)
Library left (role tabs, lessons with done, up next, draft), the open lesson right with steps and "Try it, nothing is
sent". Phone: list, then lesson, bottom bar of Home, Learn and Help. Data: client content and progress only
(`lib/learn/*`); no back end.

### `/tour` (boards P6, Ph4)
Six steps, each `?step=`; progress segments; the role step is a radio group of cards; Back, Next, Skip. Data: none
(content in `lib/tour/content.ts`; step remembered through `tenantStore`).

### `/value` (board P7)
One page: the four promises, the measures table (Target stays "[to agree]"), the savings rule and the launch kit.
Print stylesheet is a separate task.

## 6. Open design questions

1. **Email "Use Overwatch's sender"** needs a back-end choice (see `/admin/email`). Build it or drop it.
2. **Withdraw a draft version** has no call today (see `/admin/config/[n]`).
3. **Organisations list progress** needs list-level fields to avoid one read per row.
4. **Rail on a phone for admins:** a bottom bar of five items with "More", or hide the rail and use the top bar menu? The
   boards show desktop only for admin and operator.
5. **Dark rail contrast on the public pages:** the split sign-in uses the dark half for the brand and a light half for the
   action; confirm the owner is happy with a dark brand colour.
6. **The funnel's "Look after it" menu** (suspend, offboard) is described but not drawn.
7. The network portal pages and the staff pages use the same frame but are designed in other boards.

## 7. Suggested build order

1. **`AppFrame` (Rail, TopBar, PageHeader) and `StatusTag`, `StageGrid`/`StageLayer`.** Everything depends on them. Wrap
   `AdminShell` and `AppShell`; the role chip is already wired.
2. **Operator funnel** (the signature, highest value): rebuild `/operator/tenants/[id]` on the `StageGrid` with the existing
   `funnel.ts` logic; then the list (add the list fields) and Create an organisation.
3. **Admin Overview and Settings** (the two most visited admin pages): `TaskRow`, `SettingGroup`, `SettingRow`, find box.
4. **Version detail**, then **Contacts**, **Retention** (small, mostly re-skinning what was just rebuilt).
5. **Support and Access** (admin and operator): `ApprovalMeter`, `TimelineList`, the sheet.
6. **Sign-in, home, forbidden, offline, consent return** (`SplitHero`): small and independent; do early if the owner wants
   the first impression changed sooner.
7. **Help, Learn, Tour, Value:** last; they are public, low-risk and phone-first.

Each step ships on its own: the old and new pages can live side by side behind the frame wrapper.
