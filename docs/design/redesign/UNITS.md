# Work units for the frontend redesign

Generated for the parallel implementation run. Machine-readable twin: `units.json` (same ids and fields). Every unit is one task for one small-model agent in its own git worktree, run under `AGENT-GROUND-RULES.md` (read it first). Paths below are repo-relative; `modify` and `tests` paths are relative to `frontend/`, boards to `docs/design/redesign/boards/`, briefs to `docs/design/redesign/`.

Assumed to exist already (foundation, built by someone else, not a unit here): `AppFrame`/`Rail`/`TopBar`/`PageHeader` (`components/shell/`), `StageGrid`/`StageArea`/`StageLayer` and `StatusTag` (`components/ui/`), the new tokens, the staff layouts and the shell wrappers (`AdminShell`, `AdminNav`, `AdminFooter`, `OperatorNav`, `OperatorFooter`, `NetworkAdminNav`, `AppShell`, `StaffShell`, the `(group)/layout.tsx` files of the staff areas, `app/layout.tsx`). No unit touches those.

## Rules that make the units safe to run side by side

1. **One owner per file.** Every existing component, css and test file is in the `modify` or `tests` list of exactly one unit, or of several units that are chained by `depends_on` (the later one runs only after the earlier one is merged). `build.py` checked this: no two units that can run at the same time share a file. New files go in `add`; no two units add the same path.
2. **Frozen shared stylesheets.** A css module imported by files of more than one unit is read-only for every unit (it appears as `shared_read_only`). A unit that needs different styles puts them in its own new `*.module.css` and stops importing the shared one for its own files. The `CSS-A/B/C` units at the very end delete the classes nobody uses any more. Frozen files: `app/skeleton.css`, `app/tokens.css`, `components/admin/Disclose.module.css`, `components/admin/Disclose.tsx`, `components/admin/People.module.css`, `components/admin/admin.module.css`, `components/advisor/dialog-body.module.css`, `components/advisor/map.module.css`, `components/console/Console.module.css`, `components/exec/Exec.module.css`, `components/lead/ErrorSummary.module.css`, `components/lead/ErrorSummary.test.tsx`, `components/lead/ErrorSummary.tsx`, `components/lead/Lead.module.css`, `components/lead/lead-forms.module.css`, `components/network/Network.module.css`, `components/operator/Tenant.module.css`, `components/register/register.module.css`, `components/reporter/Reporter.module.css`, `components/reporter/parts/Panel.tsx`, `components/reporter/parts/Parts.module.css`, `components/reporter/parts/StatusMark.tsx`, `components/reporter/parts/StepCards.tsx`, `components/reporter/parts/SummaryRows.tsx`, `components/reporter/setup/Setup.module.css`, `components/ui/Skeleton.module.css`, `components/ui/Skeleton.tsx`.
3. **Shared page-level tests.** `pages.test.tsx` files that cover many routes belong to a `*-99` sweep unit that runs after the route units of its surface. A route unit that breaks one of those assertions says so in its report; it does not edit the file.
4. **Do not change another unit's exports.** Where a unit imports a component that another unit restyles, the notes say which props and exports must stay. `depends_on` orders the pairs that matter.
5. **Layouts of non-staff areas** (`(reporter)/layout.tsx`, `l/layout.tsx`, `i/layout.tsx`, `register/layout.tsx`, `help/layout.tsx`, `learn/layout.tsx`) currently wrap everything in the staff header (`StaffShell`). They are assigned to REP-00a, ONB-00, REG-01, PUB-05 and PUB-04 respectively.

## All units (132)

| Wave | Id | Surface | Title | Routes | Size | Model | Depends on |
|---|---|---|---|---|---|---|---|
| 0 | ADM-00a | admin | Settings blocks: SettingGroup, SettingRow, ApprovalMeter, DiffPair | (components only) | M | sonnet | (foundation only) |
| 0 | ADM-00b | admin | Admin blocks: TaskRow, ContactRow, RetentionChips, TimelineList, ProgressBar5 | (components only) | M | sonnet | (foundation only) |
| 0 | ADV-00 | advisor | Tile and StatusChip: the six statuses with Last known overlay | (components only) | M | sonnet | (foundation only) |
| 0 | ADV-01 | advisor | Call kit: CallStage grid, step bar, pinned summary, options view switch | (components only) | L | sonnet | (foundation only) |
| 0 | LED-00a | lead | Morph kit: StepBar, MorphStage, SummaryPin | (components only) | M | sonnet | (foundation only) |
| 0 | LED-00b | lead | Blocks: ConfirmDialog, DiffTable, VersionTimeline, LadderTimeline | (components only) | M | sonnet | (foundation only) |
| 0 | NET-00 | network | Scope header, notices and unavailable states (network and own scope) | (components only) | M | sonnet | (foundation only) |
| 0 | ONB-00 | onboarding | Provider phone shell: ProviderShell, SetupProgress, StickyAction | (components only) | M | sonnet | (foundation only) |
| 0 | PLN-00a | planning | Charts without a library: BarChart, LineChart, StackedBar, Funnel, PressureStrip | (components only) | L | sonnet | (foundation only) |
| 0 | PLN-00b | planning | StatusTile and DataTable | (components only) | S | sonnet | (foundation only) |
| 0 | PUB-00 | public | SplitHero block (dark brand half, light content half) | (components only) | S | sonnet | (foundation only) |
| 0 | REP-00a | reporter | Reporter shared frames, banners, reason chips, notifications nudge | (components only) | L | sonnet | (foundation only) |
| 0 | REP-00b | reporter | FigureCard, NumberStepper, ReplyByTag; restyle CoverUntil and MobileNumberField | (components only) | M | sonnet | (foundation only) |
| 1 | ADM-01 | admin | Administration overview: what needs you | `/admin` | M | haiku | ADM-00b |
| 1 | ADM-02 | admin | Settings grouped | `/admin/config` | M | sonnet | ADM-00a |
| 1 | ADM-07 | admin | Sharing with the network | `/admin/sharing` | M | sonnet | (foundation only) |
| 1 | ADM-08 | admin | Support requests to approve and the access log | `/admin/access`<br>`/admin/support` | M | sonnet | ADM-00a, ADM-00b |
| 1 | ADM-09 | admin | People and roles (already built) | `/admin/users`<br>**SKIP** | S | haiku | (foundation only) |
| 1 | ADV-02 | advisor | Calls overview: ready for calls and open cases | `/advisor` | S | sonnet | ADV-00, ADV-01, NET-00 |
| 1 | ADV-03 | advisor | Needs: the patient-needs form with live count | `/advisor/case/[ref]` | L | sonnet | ADV-01 |
| 1 | ADV-04 | advisor | No service fits right now, and the not-suitable list | (components only) | S | haiku | ADV-01 |
| 1 | ADV-06 | advisor | Booking exceptions: withdrawn alert, cancel dialog, open booking alerts | (components only) | M | sonnet | ADV-01 |
| 1 | ADV-07 | advisor | Advisor action dialogs: phoned, declined, criteria, ask clinical | (components only) | M | sonnet | ADV-01 |
| 1 | ADV-12 | advisor | Record outcome, summary for SystmOne and call closed | `/advisor/case/[ref]/finish` | M | sonnet | ADV-01 |
| 1 | BRD-01 | advisor | Live board and board states | `/advisor/board` | L | sonnet | ADV-00, NET-00 |
| 1 | CLN-01 | advisor | Clinical advisor: go on duty and the request queue | `/clinical`<br>`/clinical/requests` | M | sonnet | ADV-00 |
| 1 | CON-01 | planning | Console: find a session | `/console` | S | haiku | PLN-00b |
| 1 | CON-02 | planning | Console: session timeline and trace | `/console/session/[id]`<br>`/console/trace/[traceId]` | M | sonnet | (foundation only) |
| 1 | CON-03 | planning | Console: insight tabs | `/console/insight` | M | sonnet | PLN-00a, PLN-00b |
| 1 | COV-01 | lead | Where a service goes and coverage by time of day | `/lead/coverage/[serviceId]`<br>`/planning/coverage` | M | sonnet | PLN-00b |
| 1 | CRI-01 | lead | Criteria owner: landing and the review flow shell | `/criteria`<br>`/criteria/[serviceId]` | M | sonnet | LED-00a |
| 1 | CRI-05 | lead | Second approval | `/criteria/[serviceId]/approve` | M | sonnet | LED-00b |
| 1 | CRI-06 | lead | Criteria history | `/criteria/[serviceId]/history` | S | haiku | LED-00b |
| 1 | LDR-02 | lead | Chase card with inline ladder and phoned side sheet | (components only) | M | sonnet | LED-00b |
| 1 | LDR-03 | lead | Add a service: steps 1 and 2 on one form state | `/lead/services/new` | L | sonnet | LED-00a |
| 1 | LDR-05 | lead | Services in scope | `/lead/scope` | M | haiku | (foundation only) |
| 1 | LDR-06 | lead | Phones and services; move a service | `/lead/phones`<br>`/lead/phones/move` | M | sonnet | LED-00b, NET-00 |
| 1 | LDR-08 | lead | Remove someone's access | `/lead/people/remove` | S | haiku | LED-00b |
| 1 | LDR-10 | lead | Audit search and replay | `/lead/audit`<br>`/lead/audit/[ref]` | S | haiku | (foundation only) |
| 1 | LDR-11 | lead | Wall screens list | `/lead/screens` | M | haiku | LED-00b |
| 1 | LDR-12 | lead | Add a wall screen (pairing flow) | `/lead/screens/new` | M | sonnet | LED-00a |
| 1 | LRV-01 | onboarding | Review a registration: queue and overview in one stage | `/lead/registrations`<br>`/lead/registrations/[id]` | L | sonnet | (foundation only) |
| 1 | NAD-01 | network | Network administration: members, agreement and health | `/network-admin` | M | sonnet | PLN-00b |
| 1 | NET-03 | network | Network directory and service detail | `/network/services`<br>`/network/services/[id]` | M | sonnet | NET-00 |
| 1 | NET-04 | network | Network system now | `/network/system-now` | S | haiku | NET-00, PLN-00a |
| 1 | NET-05 | network | Network phones | `/network/phones` | S | haiku | NET-00, PLN-00b |
| 1 | NET-07 | network | Network history (left or stopped sharing) | `/network/history` | S | haiku | NET-00 |
| 1 | ONB-01 | onboarding | Invitation page and set-up steps: welcome, number, code, channel | `/i/[token]`<br>`/setup` | L | sonnet | ONB-00 |
| 1 | ONB-02 | onboarding | Set-up: add to home screen and notifications | `/setup/home-screen`<br>`/setup/notifications` | S | haiku | ONB-00 |
| 1 | ONB-03 | onboarding | Set-up: PIN keypad (92px keys, auto-advance) | `/setup/pin` | M | sonnet | ONB-00 |
| 1 | ONB-04 | onboarding | Set-up: all set and set up by text or email | `/setup/all-set`<br>`/setup/done` | S | haiku | ONB-00 |
| 1 | OPR-01 | admin | Operator sign-in | `/operator/sign-in` | S | haiku | PUB-00 |
| 1 | OPR-02 | admin | Operator organisations list | `/operator` | M | sonnet | ADM-00b |
| 1 | OPR-03 | admin | Create an organisation | `/operator/tenants/new` | M | sonnet | ADM-00b |
| 1 | OPR-04 | admin | Go-live funnel: extract the seven steps into one file each (no behaviour change) | (components only) | L | sonnet | (foundation only) |
| 1 | OPR-10 | admin | Operator support requests | `/operator/support`<br>`/operator/support/new`<br>`/operator/support/tickets/[id]` | L | sonnet | ADM-00a, ADM-00b |
| 1 | OPR-11 | admin | Operator audit chain | `/operator/audit` | S | haiku | ADM-00b |
| 1 | OPR-12 | admin | Administrator approval return page | `/admin-consent/return` | S | haiku | (foundation only) |
| 1 | PLN-01 | planning | Planning home and the planning stage | `/planning` | L | sonnet | PLN-00b, NET-00 |
| 1 | PLN-04 | planning | This week | `/planning/week` | S | sonnet | PLN-00a, NET-00 |
| 1 | PLN-05 | planning | Alerts on this phone | `/planning/phone` | S | haiku | (foundation only) |
| 1 | PLN-06 | planning | Alert settings and first-run set-up | `/planning/settings`<br>`/planning/setup` | M | sonnet | (foundation only) |
| 1 | PLN-07 | planning | Right-sizing flows | `/planning/flows` | M | sonnet | PLN-00a, PLN-00b |
| 1 | PRA-01 | reporter | Practitioner shift, round and location | `/app/practitioner`<br>`/app/practitioner/round`<br>`/app/practitioner/location` | M | sonnet | REP-00a, REP-00b |
| 1 | PUB-01 | public | Home page and splash preview | `/`<br>`/splash-preview` | M | haiku | PUB-00 |
| 1 | PUB-02 | public | Staff sign-in (desktop and phone) | `/sign-in` | S | haiku | PUB-00 |
| 1 | PUB-03 | public | Forbidden and offline | `/forbidden`<br>`/offline` | S | haiku | (foundation only) |
| 1 | PUB-04 | public | Learn: library, lesson and practice | `/learn`<br>`/learn/[lessonId]`<br>`/learn/[lessonId]/practice` | L | sonnet | (foundation only) |
| 1 | PUB-06 | public | Product tour | `/tour` | S | haiku | (foundation only) |
| 1 | PUB-07 | public | Value case | `/value` | S | haiku | (foundation only) |
| 1 | REG-01 | onboarding | Register frame: stage grid, checklist, help column, start and submitted | `/register/[id]/start`<br>`/register/[id]/submitted` | L | sonnet | ONB-00 |
| 1 | REG-05 | onboarding | Register: sign in with the invitation and My services | `/register`<br>`/register/services` | M | sonnet | ONB-00 |
| 1 | REG-06 | onboarding | Register: status after submitting (all six states) | `/register/[id]/status` | M | haiku | ONB-00 |
| 1 | REP-01 | reporter | Capacity link loop and thank-you | `/l/[token]`<br>`/l/thanks` | L | sonnet | REP-00a, REP-00b |
| 1 | REP-07 | reporter | My services, service added, hand over cover | `/app/services`<br>`/app/services/[id]/added`<br>`/app/services/[id]/cover` | M | haiku | REP-00a, REP-00b |
| 1 | REP-08 | reporter | Settings and sign out of every phone | `/app/settings`<br>`/app/sign-out-all` | M | sonnet | REP-00a, REP-00b |
| 1 | WAL-02 | advisor | Wall pairing and reconnect | `/screen/pair`<br>`/screen/reconnect` | M | sonnet | (foundation only) |
| 2 | ADM-03 | admin | Settings version detail and approval | `/admin/config/[n]` | M | sonnet | ADM-00a, ADM-02 |
| 2 | ADM-04 | admin | Contacts | `/admin/contacts` | S | haiku | ADM-00b, ADM-01 |
| 2 | ADM-05 | admin | Data retention | `/admin/retention` | S | haiku | ADM-00b, ADM-01 |
| 2 | ADM-06 | admin | Email and text senders | `/admin/email` | S | haiku | ADM-01 |
| 2 | ADV-05 | advisor | Request state: option detail, booking panel and option rail | (components only) | M | sonnet | ADV-01, ADV-06 |
| 2 | CLN-02 | advisor | Clinical case: review and give advice | `/clinical/requests/[id]` | M | sonnet | CLN-01 |
| 2 | CRI-02 | lead | Criteria owner: review and confirm panels | (components only) | S | haiku | CRI-01 |
| 2 | CRI-03 | lead | Criteria owner: change and preview panels | (components only) | M | sonnet | CRI-01 |
| 2 | CRI-04 | lead | Criteria owner: send for second approval and waiting | (components only) | S | haiku | CRI-01 |
| 2 | INV-01 | onboarding | Invite and track: reporter list and detail stage | `/lead/reporters` | L | sonnet | LDR-02 |
| 2 | LDR-01 | lead | Shift lead overview: counters, chase cards, covering, system now | `/lead` | L | sonnet | LDR-02, NET-00 |
| 2 | LDR-04 | lead | Add a service: steps 3 and 4, check and added | `/lead/services/new` | M | sonnet | LDR-03 |
| 2 | LDR-07 | lead | Suspend and resume a service | `/lead/services/[id]/suspend` | M | sonnet | LED-00a, LDR-02 |
| 2 | LDR-09 | lead | Reports to check | `/lead/flags` | M | sonnet | LED-00b, LDR-02 |
| 2 | LRV-02 | onboarding | Review: call-back check and scope check | `/lead/registrations/[id]?step=callback`<br>`/lead/registrations/[id]?step=scope` | M | sonnet | LRV-01 |
| 2 | LRV-03 | onboarding | Review: decide and go live | `/lead/registrations/[id]?step=decide`<br>`/lead/registrations/[id]?step=go-live` | M | sonnet | LRV-01 |
| 2 | NAD-02 | network | Network administration: grants and decisions history | `/network-admin/grants`<br>`/network-admin/history` | M | haiku | PLN-00b, NAD-01 |
| 2 | NAD-03 | network | Network administration: listings | `/network-admin/listings` | S | haiku | PLN-00b, NAD-01 |
| 2 | NET-01 | network | Network home | `/network/home` | S | haiku | NET-00, PLN-00b, ADV-02 |
| 2 | NET-02 | network | Network capacity board | `/network/board` | M | sonnet | NET-00, PLN-00b, ADV-00, BRD-01 |
| 2 | NET-06 | network | Network week summary | `/network/week` | M | sonnet | NET-00, PLN-00a, PLN-04 |
| 2 | OPR-05 | admin | Go-live funnel: the stage shell and the left part list | `/operator/tenants/[id]` | L | sonnet | OPR-04, ADM-00b |
| 2 | OPR-06 | admin | Go-live funnel: organisation, sign-in and administrator approval panels | (components only) | M | sonnet | OPR-04 |
| 2 | OPR-07 | admin | Go-live funnel: teams and roles panels | (components only) | M | sonnet | OPR-04 |
| 2 | OPR-08 | admin | Go-live funnel: reach and agreements panels | (components only) | M | sonnet | OPR-04 |
| 2 | OPR-09 | admin | Go-live funnel: go live and look after it | (components only) | M | sonnet | OPR-04 |
| 2 | PLN-02 | planning | All services and a service opened in place | `/planning/services`<br>`/planning/services/[id]` | M | sonnet | PLN-01, PLN-00b |
| 2 | PRA-02 | reporter | Practitioner visit offer and visit | `/app/practitioner/offers/[id]`<br>`/app/practitioner/visits/[id]` | M | sonnet | REP-00a, REP-00b, PRA-01 |
| 2 | PUB-05 | public | Help hub, problem, safety concern and share a support code | `/help`<br>`/help/problem`<br>`/help/safety`<br>`/help/share` | L | sonnet | PUB-04 |
| 2 | REG-02 | onboarding | Register: organisation and location steps | `/register/[id]/organisation`<br>`/register/[id]/location` | M | sonnet | REG-01 |
| 2 | REG-03 | onboarding | Register: service and reporting steps | `/register/[id]/service`<br>`/register/[id]/reporting` | M | sonnet | REG-01 |
| 2 | REG-04 | onboarding | Register: review and submit | `/register/[id]/review` | S | sonnet | REG-01 |
| 2 | REP-02 | reporter | Booking request: one BookingDecisionView for the link and the app | `/l/[token]/booking`<br>`/app/booking/[ref]` | L | sonnet | REP-00a, REP-00b, REP-01 |
| 2 | REP-04 | reporter | PIN screen and the /app front door | `/app/pin`<br>`/app` | S | sonnet | REP-00a, ONB-03 |
| 2 | REP-05 | reporter | Respond to one service and its thank-you | `/app/respond/[serviceId]`<br>`/app/respond/[serviceId]/thanks` | M | sonnet | REP-00a, REP-00b, REP-01 |
| 2 | REP-06 | reporter | Update every service at once | `/app/update` | M | sonnet | REP-00a, REP-00b, REP-01, REP-07 |
| 2 | REP-09 | reporter | 30-day verify and locked PIN | `/app/verify`<br>`/app/locked` | M | sonnet | REP-00a, ONB-01, ONB-03 |
| 2 | REP-10 | reporter | Lost phone and notifications off | `/app/lost-phone`<br>`/app/notifications-off` | M | sonnet | REP-00a, REP-00b, ONB-01 |
| 2 | WAL-01 | advisor | Wall board (large format) | `/screen` | M | sonnet | ADV-00, BRD-01 |
| 3 | ADM-99 | admin | Administration page tests sweep | (components only) | S | haiku | ADM-01, ADM-02, ADM-03, ADM-04, ADM-05, ADM-06, ADM-07, ADM-08 |
| 3 | ADV-08 | advisor | Options list, not-suitable list and the request deep link | `/advisor/case/[ref]/options` | L | sonnet | ADV-01, ADV-03, ADV-04, ADV-05, ADV-06, ADV-07, NET-00 |
| 3 | ADV-09 | advisor | Compare, radar and ways | `/advisor/case/[ref]/compare`<br>`/advisor/case/[ref]/radar`<br>`/advisor/case/[ref]/ways` | L | sonnet | ADV-01, ADV-03, ADV-04, ADV-05, ADV-07 |
| 3 | INV-02 | onboarding | Invite a reporter: compose state with text preview | `/lead/reporters/invite` | M | sonnet | INV-01 |
| 3 | INV-03 | onboarding | Change a reporter's number: the detail state with the row open | `/lead/reporters/number` | S | sonnet | INV-01 |
| 3 | NAD-99 | network | Network administration page tests sweep | (components only) | S | haiku | NAD-01, NAD-02, NAD-03 |
| 3 | NET-99 | network | Network page tests sweep | (components only) | S | haiku | NET-01, NET-02, NET-03, NET-04, NET-05, NET-06, NET-07 |
| 3 | OPR-99 | admin | Operator page tests sweep | (components only) | S | haiku | OPR-01, OPR-02, OPR-03, OPR-05, OPR-10, OPR-11 |
| 3 | PLN-03 | planning | Alerts and an alert acknowledged in place | `/planning/alerts`<br>`/planning/alerts/[id]` | M | sonnet | PLN-01, PLN-02 |
| 3 | REP-03 | reporter | Booking change: withdraw, not reached, cancelled and closed words | `/l/[token]/booking/change` | M | sonnet | REP-00a, REP-00b, REP-01, REP-02 |
| 4 | ADV-10 | advisor | Options on a map and the postcode-not-found state | `/advisor/case/[ref]/map` | M | sonnet | ADV-01, ADV-03, ADV-05, ADV-07, ADV-08, NET-00 |
| 4 | PLN-99 | planning | Planning page tests sweep | (components only) | S | haiku | PLN-01, PLN-02, PLN-03, PLN-04, PLN-05, PLN-06, PLN-07 |
| 5 | ADV-11 | advisor | Other organisations' options, list and map (read only) | `/advisor/case/[ref]/network-options`<br>`/advisor/case/[ref]/network-map` | M | sonnet | ADV-01, NET-00, ADV-04, ADV-08, ADV-10 |
| 6 | CSS-A | cleanup | Dead css: lead, advisor map and dialog css | (components only) | M | haiku | every other unit |
| 6 | CSS-B | cleanup | Dead css: admin, exec, console, network, operator | (components only) | M | haiku | every other unit |
| 6 | CSS-C | cleanup | Dead css: reporter, setup, register | (components only) | M | haiku | every other unit |

## Units by wave, surface and model

| Wave | Units | sonnet | haiku |
|---|---|---|---|
| 0 | 13 | 13 | 0 |
| 1 | 63 | 39 | 24 |
| 2 | 39 | 31 | 8 |
| 3 | 10 | 6 | 4 |
| 4 | 2 | 1 | 1 |
| 5 | 1 | 1 | 0 |
| 6 | 3 | 0 | 3 |

Per surface: admin 25, advisor 18, cleanup 3, lead 21, network 13, onboarding 17, planning 13, public 8, reporter 14.

## The units

### ADM-00a: Settings blocks: SettingGroup, SettingRow, ApprovalMeter, DiffPair

- **Surface:** admin. **Wave:** 0. **Size:** M. **Model:** sonnet (Shared blocks with disclosure/aria-expanded logic and chips/number/text controls used by settings, version detail, support.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/admin-operator-public.md > "2. Building blocks" (SettingGroup, SettingRow, ApprovalMeter, DiffPair)`
- **Boards:** `boards/admin/A2.dc.html`, `boards/admin/A3.dc.html`, `boards/admin/A7.dc.html`
- **Add:**
  - frontend/components/blocks/SettingGroup.tsx (+ .module.css, .test.tsx)
  - frontend/components/blocks/SettingRow.tsx (+ .module.css, .test.tsx)
  - frontend/components/blocks/ApprovalMeter.tsx (aria-label "1 of 2 approvals") (+ .module.css, .test.tsx)
  - frontend/components/blocks/DiffPair.tsx (+ .module.css, .test.tsx)
- **Gaps:** none
- **Notes:** Use components/admin/Disclose.tsx for the open/close transition by importing it (it is frozen: do not move it to components/ui as the brief suggests).

### ADM-00b: Admin blocks: TaskRow, ContactRow, RetentionChips, TimelineList, ProgressBar5

- **Surface:** admin. **Wave:** 0. **Size:** M. **Model:** sonnet (Shared blocks imported by admin and operator units.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/admin-operator-public.md > "2. Building blocks" (TaskRow, ContactRow, RetentionChips, TimelineList, ProgressBar5)`
- **Boards:** `boards/admin/A1.dc.html`, `boards/admin/A4.dc.html`, `boards/admin/A5.dc.html`, `boards/admin/A7.dc.html`, `boards/admin/O2.dc.html`, `boards/admin/O6.dc.html`
- **Add:**
  - frontend/components/blocks/TaskRow.tsx (+ .module.css, .test.tsx)
  - frontend/components/blocks/ContactRow.tsx (+ .module.css, .test.tsx)
  - frontend/components/blocks/RetentionChips.tsx (+ .module.css, .test.tsx)
  - frontend/components/blocks/TimelineList.tsx (+ .module.css, .test.tsx)
  - frontend/components/blocks/ProgressBar5.tsx (aria-label "4 of 5 parts done") (+ .module.css, .test.tsx)
- **Gaps:** none
- **Notes:** Status shapes use the foundation StatusTag; do not re-implement it.

### ADV-00: Tile and StatusChip: the six statuses with Last known overlay

- **Surface:** advisor. **Wave:** 0. **Size:** M. **Model:** sonnet (Shared by board, wall, options, compare and network board; status-never-by-colour and Out of hours rendering are safety rules.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "2. Shared contract" (Status language, Stale figures)`
- **Boards:** `boards/advisor/BoardNormal.dc.html`, `boards/advisor/BoardSurge.dc.html`, `boards/advisor/BoardQuiet.dc.html`, `boards/advisor/BoardDown.dc.html`, `boards/advisor/PBoard.dc.html`, `boards/advisor/WallBoard.dc.html`
- **Modify:** `components/board/Tile.tsx`, `components/board/Tile.module.css`, `components/board/Legend.tsx`, `components/board/Legend.module.css`
- **Add:**
  - frontend/components/board/StatusChip.tsx (shape + word; six states) (+ .module.css, .test.tsx)
- **Tests to update:** `components/board/Tile.test.tsx`, `components/board/Tile.network.test.tsx`, `components/board/Legend.test.tsx`, `components/board/styles.test.ts`
- **Gaps:** Out of hours: confirm the reopen time is on BoardEntry for every out-of-hours service (brief gap 5).
- **Notes:** Out of hours must render as in BoardQuiet (crescent, quiet tile), not as Not accepting. board/styles.test.ts reads Tile.module.css AND Board.module.css: you update the Tile assertions; BRD-01 (Board.module.css) runs after you and edits the Board assertions. NetworkTile.tsx imports Tile.module.css: keep existing class names working. Tile.tsx imports scope/OrgLabel, which NET-00 restyles at the same time (wave 0): keep its props. Legend is included because it draws the six states; BRD-01 must not edit it.

### ADV-01: Call kit: CallStage grid, step bar, pinned summary, options view switch

- **Surface:** advisor. **Wave:** 0. **Size:** L. **Model:** sonnet (The grid state machine, focus-to-heading, inert folded columns and aria-current steps wrap every call page.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "3. The advisor call: states and URLs" and "2. Shared contract" (Segmented control)`
- **Boards:** `boards/advisor/Call.dc.html`, `boards/advisor/Main.dc.html`, `boards/core-morph/S1.dc.html`, `boards/core-morph/S2.dc.html`, `boards/core-morph/S3.dc.html`, `boards/core-morph/S4.dc.html`, `boards/core-morph/P1.dc.html`, `boards/core-morph/P2.dc.html`, `boards/core-morph/Rules.dc.html`
- **Modify:** `components/advisor/CallSteps.tsx`, `components/advisor/CallSteps.module.css`, `components/advisor/CaseSummary.tsx`, `components/advisor/CaseSummaryLine.tsx`, `components/advisor/CaseSummaryLine.module.css`, `components/advisor/ViewToggle.tsx`
- **Add:**
  - frontend/components/advisor/CallStage.tsx (summary | stage | side grid with data-stage over the foundation StageGrid) (+ .module.css, .test.tsx)
- **Tests to update:** `components/advisor/CallSteps.test.tsx`, `components/advisor/CaseSummary.test.tsx`, `components/advisor/CaseSummaryLine.test.tsx`, `components/advisor/ViewToggle.test.tsx`
- **Read only (shared):** `components/advisor/map.module.css`
- **Gaps:** Request state as ?service=[id] is a front-end addition (brief open question 2): implement only the stage; deep-link wiring is in the options unit.
- **Notes:** CallSteps is imported by all nine /advisor/case pages: keep its props. ViewToggle becomes the one segmented control (List, Compare, Map, Radar, Ways, Other organisations) over the existing routes, current tab aria-current="page"; it is imported by MapScreen, NetworkMap, NetworkOptions, OptionsList (other units), so keep its exports. CaseSummary becomes the pinned patient card with Edit; it is imported by the options and network-options pages. advisor/map.module.css (imported by ViewToggle) is frozen: give ViewToggle its own css.

### LED-00a: Morph kit: StepBar, MorphStage, SummaryPin

- **Surface:** lead. **Wave:** 0. **Size:** M. **Model:** sonnet (Core morph primitives; inert layers, lazy mounting, focus management, reduced motion.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/lead-and-setup.md > "2. Shared pieces this surface needs" (StepBar, MorphStage, SummaryPin)`
- **Boards:** `boards/lead/AddService.dc.html`, `boards/lead/Suspend.dc.html`, `boards/lead/ScreenPair.dc.html`, `boards/lead/OwnerReview.dc.html`
- **Add:**
  - frontend/components/morph/StepBar.tsx (nav, aria-current="step") (+ .module.css, .test.tsx)
  - frontend/components/morph/MorphStage.tsx (layers in one cell, inactive layers inert, must not mount inactive fetches) (+ .module.css, .test.tsx)
  - frontend/components/morph/SummaryPin.tsx (left card that grows from width 0, read-only list with Change links) (+ .module.css, .test.tsx)
- **Gaps:** none
- **Notes:** StageGrid/StageLayer come from the foundation: build MorphStage as a thin consumer of them where they fit, otherwise self-contained. Keyboard Next/Enter changes step with no animation. Phone: SummaryPin becomes a one-line pill opening a sheet (props, not a separate component).

### LED-00b: Blocks: ConfirmDialog, DiffTable, VersionTimeline, LadderTimeline

- **Surface:** lead. **Wave:** 0. **Size:** M. **Model:** sonnet (Shared blocks with dialog focus trapping and safety wording rules used by about eight units.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/lead-and-setup.md > "2. Shared pieces this surface needs" (ConfirmDialog, DiffTable, VersionTimeline; LadderTimeline from "/lead" and "/lead/phones")`
- **Boards:** `boards/lead/RemoveAccess.dc.html`, `boards/lead/Approve.dc.html`, `boards/lead/History.dc.html`, `boards/lead/OverviewChase.dc.html`, `boards/lead/Phones.dc.html`, `boards/lead/States.dc.html`
- **Add:**
  - frontend/components/blocks/ConfirmDialog.tsx (role=alertdialog, safe choice same size and initial focus) (+ .module.css, .test.tsx)
  - frontend/components/blocks/DiffTable.tsx (what / was / now, "everything else is the same") (+ .module.css, .test.tsx)
  - frontend/components/blocks/VersionTimeline.tsx (+ .module.css, .test.tsx)
  - frontend/components/blocks/LadderTimeline.tsx (ordered list, each step state in words) (+ .module.css, .test.tsx)
- **Gaps:** none
- **Notes:** Build ConfirmDialog on components/ui/Dialog.tsx (do not edit it). The brief says lift Field/ErrorSummary into components/forms: do NOT, forms/ErrorSummary.tsx and lead/ErrorSummary.tsx both already exist and lead/ErrorSummary is imported by admin and operator forms (frozen).

### NET-00: Scope header, notices and unavailable states (network and own scope)

- **Surface:** network. **Wave:** 0. **Size:** M. **Model:** sonnet (Imported by about twelve units; refusal wording from network-ui.md must not change; the header never disappears in any degraded state.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/planning-analytics-network.md > "2. Shared pieces" items 4 (ScopeHeader), 5 (Notice) and "Network" > "every refusal and degraded state"`
- **Boards:** `boards/planning/NStates.dc.html`, `boards/planning/NHome.dc.html`, `boards/planning/NBoard.dc.html`
- **Modify:** `components/scope/ScopeHeader.tsx`, `components/scope/OwnScopeHeader.tsx`, `components/scope/ScopeSwitch.tsx`, `components/scope/ScopeNotice.tsx`, `components/scope/OrgLabel.tsx`, `components/scope/PhoneLink.tsx`, `components/scope/ReadOnlyNote.tsx`, `components/scope/NetworkUnavailable.tsx`, `components/network/NetworkScope.tsx`, `components/scope/Scope.module.css`
- **Tests to update:** `components/scope/ScopeHeader.test.tsx`, `components/scope/OwnScopeHeader.test.tsx`, `components/scope/NetworkUnavailable.test.tsx`, `components/network/NetworkScope.test.tsx`
- **Read only (shared):** `components/network/Network.module.css`
- **Gaps:** none
- **Notes:** Restyle only: the words in docs/design/network-ui.md section 5 stay. board/Tile.tsx (ADV-00, same wave) imports OrgLabel: keep its props. ui/Banner (the brief calls it Notice) is a shared ui file used everywhere: not changed by any unit; flag in the report if the board needs a Banner change. Keep exported props stable.

### ONB-00: Provider phone shell: ProviderShell, SetupProgress, StickyAction

- **Surface:** onboarding. **Wave:** 0. **Size:** M. **Model:** sonnet (Shared phone frame imported by /i, /setup and /register units; sticky safe-area action and focus-to-heading contract.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Shared building blocks" (ProviderShell, SetupProgress, StickyAction)`
- **Boards:** `boards/onboarding/R2.dc.html`, `boards/onboarding/R3.dc.html`, `boards/onboarding/R4.dc.html`, `boards/onboarding/R7.dc.html`, `boards/onboarding/RP2.dc.html`, `boards/onboarding/Reg.dc.html`
- **Modify:** `app/i/layout.tsx`
- **Add:**
  - frontend/components/provider/ProviderShell.tsx (+ .module.css, .test.tsx)
  - frontend/components/provider/SetupProgress.tsx (aria-label "Step 2 of 5") (+ .module.css, .test.tsx)
  - frontend/components/provider/StickyAction.tsx (+ .module.css, .test.tsx)
- **Gaps:** none
- **Notes:** i/layout.tsx currently wraps in StaffShell: replace so the invitation page uses no staff header. ProviderShell takes the service chip, current step (1..5) and children; StickyAction takes one primary and one optional text link. A desktop shows the same column at 480px centred. No dependency on the register StageGrid (that lives in REG-01).

### PLN-00a: Charts without a library: BarChart, LineChart, StackedBar, Funnel, PressureStrip

- **Surface:** planning. **Wave:** 0. **Size:** L. **Model:** sonnet (Charts with role=img, pattern fills, a table prop behind a disclosure; accessibility and number-on-every-mark rules.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/planning-analytics-network.md > "2. Shared pieces" item 8 (Charts) and "5. Motion and accessibility notes"`
- **Boards:** `boards/planning/PCharts.dc.html`, `boards/planning/PWeek.dc.html`, `boards/planning/NSystemNow.dc.html`, `boards/planning/NWeek.dc.html`, `boards/planning/CInsightA.dc.html`
- **Add:**
  - frontend/components/charts/BarChart.tsx (CSS flex bars, axis from zero, threshold line) (+ .module.css, .test.tsx)
  - frontend/components/charts/LineChart.tsx (inline SVG polyline) (+ .module.css, .test.tsx)
  - frontend/components/charts/StackedBar.tsx (patterns, legend with numbers) (+ .module.css, .test.tsx)
  - frontend/components/charts/Funnel.tsx (biggest drop hatched and named) (+ .module.css, .test.tsx)
  - frontend/components/charts/PressureStrip.tsx (7 by 24 CSS grid) (+ .module.css, .test.tsx)
- **Gaps:** none (data series come from the consumers)
- **Notes:** No chart library (do not add a dependency). Every chart takes a table prop (same rows) and renders it behind a "Show as a table" disclosure (import components/admin/Disclose, frozen). HeatGrid and Waterfall exist already and are restyled by PLN-07 and CON-02: not here.

### PLN-00b: StatusTile and DataTable

- **Surface:** planning. **Wave:** 0. **Size:** S. **Model:** sonnet (Shared parts imported by about ten units.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/planning-analytics-network.md > "2. Shared pieces" items 3 (StatusChip/StatusTile) and 9 (DataTable)`
- **Boards:** `boards/planning/PHome.dc.html`, `boards/planning/PServices.dc.html`, `boards/planning/NPhones.dc.html`, `boards/planning/NBoard.dc.html`, `boards/planning/PStates.dc.html`
- **Add:**
  - frontend/components/status/StatusTile.tsx (glyph + word + colour; dashed for not updated; hatched for over capacity) (+ .module.css, .test.tsx)
  - frontend/components/data/DataTable.tsx (sticky header, overscroll-behavior: contain, viewport-aware max height) (+ .module.css, .test.tsx)
- **Gaps:** none
- **Notes:** StatusTag is the foundation component; StatusTile is the large tile. The seven words of the existing status badge are unchanged.

### PUB-00: SplitHero block (dark brand half, light content half)

- **Surface:** public. **Wave:** 0. **Size:** S. **Model:** sonnet (Shared block imported by home, sign-in and operator sign-in units; dark brand colour on public pages needs contrast checks.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/admin-operator-public.md > "2. Building blocks" (SplitHero)`
- **Boards:** `boards/admin/O1.dc.html`, `boards/admin/P1.dc.html`, `boards/admin/P2.dc.html`, `boards/admin/Ph1.dc.html`
- **Add:**
  - frontend/components/blocks/SplitHero.tsx (+ .module.css, .test.tsx)
- **Gaps:** none
- **Notes:** Brand colour contrast: text on the dark half must pass 4.5:1 (axe). Phone: stacks, brand half becomes a short band.

### REP-00a: Reporter shared frames, banners, reason chips, notifications nudge

- **Surface:** reporter. **Wave:** 0. **Size:** L. **Model:** sonnet (Shared parts imported by every later reporter unit; layout work and a tab bar that hides by route; radiogroup keyboard handling.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/reporter-app.md > "Shared pieces" (LinkFrame, AppFrame, StateBanner, ReasonChips) and "Gaps and flags" 5`
- **Boards:** `boards/reporter/B3.dc.html`, `boards/reporter/B4.dc.html`, `boards/reporter/B6.dc.html`, `boards/reporter/B9.dc.html`, `boards/reporter/St.dc.html`, `boards/reporter/Main.dc.html`
- **Modify:** `components/reporter/parts/index.ts`, `app/(reporter)/layout.tsx`, `app/l/layout.tsx`
- **Add:**
  - frontend/components/reporter/parts/LinkFrame.tsx (+ .module.css, .test.tsx)
  - frontend/components/reporter/parts/ReporterAppFrame.tsx (dark top bar + bottom TabBar; hidden on pin, verify, locked, lost-phone, practitioner) (+ .module.css, .test.tsx)
  - frontend/components/reporter/parts/TabBar.tsx (+ .module.css, .test.tsx)
  - frontend/components/reporter/parts/StateBanner.tsx (+ .module.css, .test.tsx)
  - frontend/components/reporter/parts/ReasonChips.tsx (+ .module.css, .test.tsx)
  - frontend/components/reporter/parts/NotificationsNudge.tsx (+ .module.css, .test.tsx)
  - frontend/app/(reporter)/app/layout.tsx (new nested layout that mounts ReporterAppFrame for /app/*)
- **Gaps:** none for the parts themselves. The nudge needs only the client notification-permission check.
- **Notes:** Name the reporter frame ReporterAppFrame: the foundation owns a different AppFrame (staff shell). The (reporter)/layout.tsx and l/layout.tsx currently wrap in StaffShell (staff header); change them so the reporter and link pages are NOT inside the staff header (/setup/* pages mount ProviderShell themselves, /l/* pages mount LinkFrame themselves). The Update tab must reuse the /app redirect logic (link to /app). Do not edit parts/Panel, StatusMark, StepCards, SummaryRows or Parts.module.css (frozen, used by other units); new parts get their own css. Export the new parts from parts/index.ts here and nowhere else.

### REP-00b: FigureCard, NumberStepper, ReplyByTag; restyle CoverUntil and MobileNumberField

- **Surface:** reporter. **Wave:** 0. **Size:** M. **Model:** sonnet (Shared parts imported by many later units; the figure must never animate; stepper keyboard and empty-state rules.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/reporter-app.md > "Shared pieces" (FigureCard, NumberStepper, ReplyByTag) and Rule 1`
- **Boards:** `boards/reporter/B1.dc.html`, `boards/reporter/B2.dc.html`, `boards/reporter/B7.dc.html`, `boards/reporter/D1.dc.html`
- **Modify:** `components/reporter/CoverUntil.tsx`, `components/reporter/MobileNumberField.tsx`
- **Add:**
  - frontend/components/reporter/parts/FigureCard.tsx (+ .module.css, .test.tsx)
  - frontend/components/reporter/parts/ReplyByTag.tsx (+ .module.css, .test.tsx)
  - frontend/components/reporter/parts/NumberStepper.tsx (76px controls, dashed empty box; + .module.css, .test.tsx)
- **Gaps:** none
- **Notes:** components/ui/NumberStepper.tsx already exists (used by CapacityResponder, CapacityResponseForm, CriteriaEditor): do NOT change it; the brief means a new reporter-specific stepper, so put it in reporter/parts and keep the name NumberStepper there. Do not export from parts/index.ts (REP-00a owns it): later units import by file path. CoverUntil and MobileNumberField have no tests of their own: add parts-style tests next to them if you change markup.

### ADM-01: Administration overview: what needs you

- **Surface:** admin. **Wave:** 1. **Size:** M. **Model:** haiku (Task rows derived from existing reads; no new behaviour.).
- **Routes:** `/admin`
- **Depends on:** FOUNDATION, ADM-00b
- **Brief:** `docs/design/redesign/admin-operator-public.md > "3. Administration" > /admin Overview`
- **Boards:** `boards/admin/A1.dc.html`
- **Modify:** `components/admin/AdminOverview.tsx`, `app/(tenant-admin)/admin/page.tsx`
- **Tests to update:** `components/admin/AdminOverview.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`
- **Gaps:** none
- **Notes:** AdminOverview exports (setupSteps and others) are imported by AdminNav, ContactsForm, EmailSender, RetentionForm, UsersAndRoles, AdminShell: keep every export. Loading: three skeleton rows. All done: "Nothing needs you". admin/pages.test.tsx is owned by ADM-99.

### ADM-02: Settings grouped

- **Surface:** admin. **Wave:** 1. **Size:** M. **Model:** sonnet (Clinical-setting changes need two approvals: notice, stale (409) handling and the grouped interactive form.).
- **Routes:** `/admin/config`
- **Depends on:** FOUNDATION, ADM-00a
- **Brief:** `docs/design/redesign/admin-operator-public.md > Administration > /admin/config (board A2)`
- **Boards:** `boards/admin/A2.dc.html`
- **Modify:** `components/admin/ConfigVersions.tsx`, `app/(tenant-admin)/admin/config/page.tsx`
- **Tests to update:** `components/admin/ConfigVersions.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`, `components/admin/Disclose.tsx`, `components/lead/ErrorSummary.tsx`
- **Gaps:** none
- **Notes:** Keep POST /tenant/config/drafts and the client-side safetyClass notice (the back end stays the check). Filter typed opens matching groups and shows "n match" on others. VersionDetail imports ConfigVersions (ADM-03 runs after you): keep exports. Uses lead/ErrorSummary and admin/Disclose (frozen).

### ADM-07: Sharing with the network

- **Surface:** admin. **Wave:** 1. **Size:** M. **Model:** sonnet (Two-person approval of grants and leave-network; per-scope states.).
- **Routes:** `/admin/sharing`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/admin-operator-public.md > Administration > /admin/sharing (board A6 right half)`
- **Boards:** `boards/admin/A6.dc.html`
- **Modify:** `components/sharing/SharingOverview.tsx`, `components/scope/AllowlistFields.tsx`, `app/(tenant-admin)/admin/sharing/page.tsx`
- **Tests to update:** `components/sharing/SharingOverview.test.tsx`, `components/scope/AllowlistFields.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`
- **Gaps:** none
- **Notes:** States: not in a network, invited, per scope (not shared, waiting n of 2, shared since), left. Organisation code with Copy; History disclosure. Keep the two-person approval wording as built.

### ADM-08: Support requests to approve and the access log

- **Surface:** admin. **Wave:** 1. **Size:** M. **Model:** sonnet (Approving platform access and a one-time access code shown once (never stored).).
- **Routes:** `/admin/access`, `/admin/support`
- **Depends on:** FOUNDATION, ADM-00a, ADM-00b
- **Brief:** `docs/design/redesign/admin-operator-public.md > Administration > /admin/access and /admin/support (board A7)`
- **Boards:** `boards/admin/A7.dc.html`
- **Modify:** `components/admin/AccessLog.tsx`, `components/admin/SupportRequests.tsx`, `app/(tenant-admin)/admin/access/page.tsx`, `app/(tenant-admin)/admin/support/page.tsx`
- **Tests to update:** `components/admin/AccessLog.test.tsx`, `components/admin/SupportRequests.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`
- **Gaps:** none
- **Notes:** After Approve the code card shows the code once (announced once via role=status, copy button, "I have passed it on" or "Take it back"). SupportRequests.test.tsx is a known local-storage failure on this machine: do not "fix" it unless it fails differently.

### ADM-09: People and roles (already built)

- **Surface:** admin. **Wave:** 1. **Size:** S. **Model:** haiku (n/a).
- **SKIP:** Already designed and built (GroupMembers, PersonLookup, DEC-1325). Only the frame changes, which the foundation AppFrame wiring handles.
- **Routes:** `/admin/users`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/admin-operator-public.md > Administration > /admin/users`
- **Boards:** `boards/admin/Main.dc.html`
- **Gaps:** none
- **Notes:** Do not touch components/admin/UsersAndRoles, GroupMembers, PersonLookup, Avatar or People.module.css.

### ADV-02: Calls overview: ready for calls and open cases

- **Surface:** advisor. **Wave:** 1. **Size:** S. **Model:** sonnet (Starts a call (creates the case) inside the call stage.).
- **Routes:** `/advisor`
- **Depends on:** FOUNDATION, ADV-00, ADV-01, NET-00
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.1 Advisor" > /advisor and "3. The advisor call" (Overview state)`
- **Boards:** `boards/advisor/Call.dc.html`, `boards/advisor/BoardNormal.dc.html`, `boards/core-morph/S1.dc.html`, `boards/core-morph/Today.dc.html`
- **Modify:** `components/advisor/BoardCounts.tsx`, `components/advisor/BoardCounts.module.css`, `components/advisor/StartCallButton.tsx`, `app/(advisor)/advisor/page.tsx`
- **Tests to update:** `app/(advisor)/advisor/page.test.tsx`
- **Gaps:** none
- **Notes:** BoardCounts.module.css is also imported by network/NetworkHomeView (NET-01 runs after you): keep its class names or tell NET-01 in your report. OwnScopeHeader (NET-00) is imported by the page.

### ADV-03: Needs: the patient-needs form with live count

- **Surface:** advisor. **Wave:** 1. **Size:** L. **Model:** sonnet (Clinical needs entry with If-Match PUT, postcode states, per-step validation and a live count.).
- **Routes:** `/advisor/case/[ref]`
- **Depends on:** FOUNDATION, ADV-01
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.1 Advisor" > .../case/[ref] and "8. Data gaps" 1`
- **Boards:** `boards/advisor/Call.dc.html`, `boards/core-morph/S2.dc.html`, `boards/core-morph/P1.dc.html`
- **Modify:** `components/advisor/NeedsForm.tsx`, `components/advisor/NeedsForm.module.css`, `components/advisor/ScorePickers.tsx`, `components/advisor/ScorePickers.module.css`, `components/advisor/PostcodeStates.tsx`, `components/advisor/CallBar.tsx`, `components/advisor/CallBar.module.css`, `app/(advisor)/advisor/case/[ref]/page.tsx`
- **Add:**
  - frontend/components/advisor/LiveCount.tsx (+ .module.css, .test.tsx)
- **Tests to update:** `components/advisor/NeedsForm.test.tsx`, `components/advisor/NeedsForm.recorded.test.tsx`, `components/advisor/ScorePickers.test.tsx`, `components/advisor/PostcodeStates.test.tsx`, `components/advisor/CallBar.test.tsx`, `app/(advisor)/advisor/case/[ref]/page.test.tsx`, `components/advisor/PostcodeSearch.test.tsx`
- **Read only (shared):** `components/advisor/map.module.css`
- **Gaps:** A count while typing needs either a debounced PUT of the partial case plus an options read (writes a draft each pause) or a new count-only read: decide; default to showing the count only after Save needs. DistrictChoice is named in the brief but there is no such component: the district choice lives in OptionsList and MapScreen.
- **Notes:** PostcodeStates is imported by MapScreen, OptionsList and RadarFrame (ADV-08, ADV-09, ADV-10 depend on you): keep exports (PostcodeNotFound etc.). PostcodeSearch.test.tsx tests PostcodeNotFound inside MapScreen: you own the PostcodeNotFound part, ADV-10 (map) edits it afterwards. map.module.css (imported by PostcodeStates) is frozen: give PostcodeStates its own css. Keep CallBar behaviour used by NeedsForm.

### ADV-04: No service fits right now, and the not-suitable list

- **Surface:** advisor. **Wave:** 1. **Size:** S. **Model:** haiku (Four large next-step rows reusing existing calls.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, ADV-01
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.1 Advisor" > (empty state) NoFit, and Options (not suitable, and why)`
- **Boards:** `boards/advisor/NoFit.dc.html`, `boards/advisor/PNoFit.dc.html`
- **Modify:** `components/advisor/NoServiceFits.tsx`, `components/advisor/NoServiceFits.module.css`, `components/advisor/NotSuitableList.tsx`, `components/advisor/NotSuitableList.module.css`
- **Tests to update:** `components/advisor/NoServiceFits.test.tsx`, `components/advisor/NoServiceFits.recorded.test.tsx`, `components/advisor/NotSuitableList.test.tsx`
- **Gaps:** none
- **Notes:** Not a route: a state of options (rendered by OptionsList, ADV-08) and of RadarFrame (ADV-09). Keep the exported props. Four next steps: widen the time, phone, ask clinical, other route. NotSuitableList is imported by OptionsList (ADV-08), WaysScreen (ADV-09) and NetworkOptions (ADV-11): keep its exports.

### ADV-06: Booking exceptions: withdrawn alert, cancel dialog, open booking alerts

- **Surface:** advisor. **Wave:** 1. **Size:** M. **Model:** sonnet (A service withdrawing or the SPOA cancelling after the advisor booked is patient-flow critical; alerts via events.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, ADV-01
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.1 Advisor" > (Exceptions) WithdrawalAlert, CancelBookingDialog`
- **Boards:** `boards/advisor/Exceptions.dc.html`
- **Modify:** `components/advisor/BookingCard.tsx`, `components/advisor/WithdrawalAlert.tsx`, `components/advisor/CancelBookingDialog.tsx`, `components/advisor/OpenBookingAlerts.tsx`, `components/advisor/OpenBookingAlerts.module.css`, `components/advisor/Advisor.module.css`
- **Tests to update:** `components/advisor/BookingCard.test.tsx`, `components/advisor/OpenBookingAlerts.test.tsx`, `components/advisor/BookingCancel.test.tsx`
- **Gaps:** none
- **Notes:** Advisor.module.css is imported by options/page.tsx too (ADV-08 reads it): keep every class that page uses. BookingPanel (ADV-05) imports BookingCard: keep exports. OpenBookingAlerts is mounted by advisor/layout.tsx (foundation touches the layout, not this component).

### ADV-07: Advisor action dialogs: phoned, declined, criteria, ask clinical

- **Surface:** advisor. **Wave:** 1. **Size:** M. **Model:** sonnet (FHIR $advisor-phoned and $declined writes and clinical-request creation inside dialogs; focus traps.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, ADV-01
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.1 Advisor" > Dialogs`
- **Boards:** `boards/advisor/Actions.dc.html`
- **Modify:** `components/advisor/PhonedDialog.tsx`, `components/advisor/DeclinedDialog.tsx`, `components/advisor/CriteriaDialog.tsx`, `components/advisor/AskClinicalDialog.tsx`, `components/advisor/AskClinicalPanel.tsx`
- **Tests to update:** `components/advisor/PhonedDialog.test.tsx`, `components/advisor/DeclinedDialog.test.tsx`, `components/advisor/CriteriaDialog.test.tsx`, `components/advisor/AskClinicalDialog.test.tsx`, `components/advisor/AskClinicalPanel.test.tsx`, `components/advisor/AskClinicalWiring.test.tsx`
- **Read only (shared):** `components/advisor/dialog-body.module.css`, `components/exec/Exec.module.css`
- **Gaps:** none
- **Notes:** Not a route unit. OptionsList (ADV-08), MapScreen (ADV-10) and RadarFrame (ADV-09) import these: keep exports. dialog-body.module.css (frozen, shared with lead dialogs) and exec/Exec.module.css (frozen, imported by AskClinicalDialog): use your own css.

### ADV-12: Record outcome, summary for SystmOne and call closed

- **Surface:** advisor. **Wave:** 1. **Size:** M. **Model:** sonnet (Outcome write closes the case; summary must contain no patient name; closed state replaces history.).
- **Routes:** `/advisor/case/[ref]/finish`
- **Depends on:** FOUNDATION, ADV-01
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.1 Advisor" > .../finish`
- **Boards:** `boards/advisor/Finish.dc.html`, `boards/advisor/Closed.dc.html`, `boards/advisor/PFinish.dc.html`
- **Modify:** `components/advisor/FinishScreen.tsx`, `components/advisor/OutcomeForm.tsx`, `components/advisor/SummaryCopy.tsx`, `components/advisor/CallClosed.tsx`, `app/(advisor)/advisor/case/[ref]/finish/page.tsx`, `components/advisor/finish.module.css`
- **Tests to update:** `components/advisor/FinishScreen.test.tsx`, `components/advisor/OutcomeForm.test.tsx`, `components/advisor/OutcomeForm.destination.test.tsx`, `components/advisor/SummaryCopy.test.tsx`, `app/(advisor)/advisor/case/[ref]/finish/page.test.tsx`
- **Gaps:** none
- **Notes:** Closed state is .../finish?closed=1 (replace, not push). POST /api/bff/cases/[ref]/outcome and .../summary. "Start next" returns to Needs for a new case.

### BRD-01: Live board and board states

- **Surface:** advisor. **Wave:** 1. **Size:** L. **Model:** sonnet (Live board: liveness, Last known overlay, pressure banner, announcements; screen readers get status word first.).
- **Routes:** `/advisor/board`
- **Depends on:** FOUNDATION, ADV-00, NET-00
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.1 Advisor" > /advisor/board and "6. Motion and accessibility"`
- **Boards:** `boards/advisor/BoardNormal.dc.html`, `boards/advisor/BoardSurge.dc.html`, `boards/advisor/BoardQuiet.dc.html`, `boards/advisor/BoardDown.dc.html`, `boards/advisor/BoardLoading.dc.html`, `boards/advisor/PBoard.dc.html`
- **Modify:** `components/board/Board.tsx`, `components/board/Board.module.css`, `components/board/BoardUnavailable.tsx`, `components/board/PressureBanner.tsx`, `components/board/LastKnownBanner.tsx`, `components/board/LastKnownBanner.module.css`, `app/(advisor)/advisor/board/page.tsx`
- **Tests to update:** `components/board/Board.test.tsx`, `components/board/Board.network.test.tsx`, `components/board/Board.scope.test.tsx`, `components/board/BoardUnavailable.test.tsx`, `components/board/PressureBanner.test.tsx`, `components/board/LastKnownBanner.test.tsx`, `app/(advisor)/advisor/board/page.test.tsx`, `components/board/styles.test.ts`
- **Gaps:** Out of hours: the reopen time must be on BoardEntry for every out-of-hours service (brief gap 5).
- **Notes:** Board.module.css is yours; it is also imported by NetworkBoard and StatusAnnouncer (NET-02 and WAL-01 run after you). Board.tsx is rendered by LiveBoard on the wall: keep its props. Legend is owned by ADV-00. board/styles.test.ts: ADV-00 edits the Tile assertions first, you edit the Board assertions. The board never animates a live number.

### CLN-01: Clinical advisor: go on duty and the request queue

- **Surface:** advisor. **Wave:** 1. **Size:** M. **Model:** sonnet (Presence and queue ownership (take) in a clinical-safety workflow.).
- **Routes:** `/clinical`, `/clinical/requests`
- **Depends on:** FOUNDATION, ADV-00
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.2 Clinical advisor" (/clinical, /clinical/requests)`
- **Boards:** `boards/advisor/ClinDuty.dc.html`, `boards/advisor/ClinQueue.dc.html`, `boards/advisor/PClinAlert.dc.html`
- **Modify:** `components/clinical/DutyForm.tsx`, `components/clinical/QueueList.tsx`, `app/(clinical)/clinical/page.tsx`, `app/(clinical)/clinical/requests/page.tsx`
- **Tests to update:** `components/clinical/DutyForm.test.tsx`, `components/clinical/QueueList.test.tsx`
- **Read only (shared):** `components/exec/Exec.module.css`
- **Gaps:** Check /api/bff/clinical/presence stores Busy (gap 7). The Done tab and a phone push alert are not confirmed in the BFF (gap 8): optional first cut; show Waiting and Mine only if Done has no endpoint.
- **Notes:** Urgency tags: Now solid, Within 15 min outline. No postcode and no name is ever shown (DEC-396). exec/Exec.module.css is frozen (imported here and by 7 other files): use your own css. CaseView (CLN-02) imports QueueList for the slim queue: keep exports. Clinical lead vs clinical advisor wording is an open question: do not change words.

### CON-01: Console: find a session

- **Surface:** planning. **Wave:** 1. **Size:** S. **Model:** haiku (Re-skin of search plus a DataTable; support code is the first control.).
- **Routes:** `/console`
- **Depends on:** FOUNDATION, PLN-00b
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Support console > /console`
- **Boards:** `boards/planning/CFind.dc.html`
- **Modify:** `components/console/FindSession.tsx`, `app/(console)/console/page.tsx`
- **Tests to update:** `components/console/FindSession.test.tsx`
- **Read only (shared):** `components/console/Console.module.css`
- **Gaps:** none
- **Notes:** Results show only aggregates and session ids. Console.module.css is frozen (also used by learn and planning pages): use your own css.

### CON-02: Console: session timeline and trace

- **Surface:** planning. **Wave:** 1. **Size:** M. **Model:** sonnet (Master-detail morph and a waterfall chart with the slowest span hatched and named.).
- **Routes:** `/console/session/[id]`, `/console/trace/[traceId]`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Support console > /console/session/[id], /console/trace/[traceId] and "5. Motion" (session to trace morph)`
- **Boards:** `boards/planning/CSession.dc.html`, `boards/planning/CTrace.dc.html`
- **Modify:** `components/console/SessionTimeline.tsx`, `components/console/Waterfall.tsx`, `app/(console)/console/session/[id]/page.tsx`, `app/(console)/console/trace/[traceId]/page.tsx`
- **Tests to update:** `components/console/SessionTimeline.test.tsx`, `components/console/Waterfall.test.tsx`
- **Read only (shared):** `components/console/Console.module.css`
- **Gaps:** none
- **Notes:** Session: timeline with filter chips, "What stands out", selected event, "View trace", "Copy link to this moment". Trace: waterfall plus span table, "Open the query in the matrix", "Back to the session".

### CON-03: Console: insight tabs

- **Surface:** planning. **Wave:** 1. **Size:** M. **Model:** sonnet (Charts (funnel with biggest drop hatched and named) and tabs.).
- **Routes:** `/console/insight`
- **Depends on:** FOUNDATION, PLN-00a, PLN-00b
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Support console > /console/insight`
- **Boards:** `boards/planning/CInsightA.dc.html`, `boards/planning/CInsightB.dc.html`
- **Modify:** `components/console/insight/InsightTabs.tsx`, `components/console/insight/FunnelsTab.tsx`, `components/console/insight/FrictionTab.tsx`, `components/console/insight/PathsTab.tsx`, `components/console/insight/PerformanceTab.tsx`, `components/console/insight/ReleasesTab.tsx`, `app/(console)/console/insight/page.tsx`
- **Tests to update:** `components/console/insight/InsightTabs.test.tsx`, `components/console/insight/FunnelsTab.test.tsx`, `components/console/insight/FrictionTab.test.tsx`, `components/console/insight/ReleasesTab.test.tsx`
- **Read only (shared):** `components/console/Console.module.css`
- **Gaps:** "Show example sessions" on Friction is not found as its own BFF route (brief 4 item 7): confirm it exists in the allow-list before drawing it.
- **Notes:** Funnels: steps, split table, Export CSV. Paths and Performance have no tests: add them. Console.module.css is frozen.

### COV-01: Where a service goes and coverage by time of day

- **Surface:** lead. **Wave:** 1. **Size:** M. **Model:** sonnet (Two routes share one component folder, css and test; tiles with patterns not colour alone; save keeps values on failure.).
- **Routes:** `/lead/coverage/[serviceId]`, `/planning/coverage`
- **Depends on:** FOUNDATION, PLN-00b
- **Brief:** `docs/design/redesign/lead-and-setup.md > "/lead/coverage/[serviceId]"; docs/design/redesign/planning-analytics-network.md > Planning > /planning/coverage`
- **Boards:** `boards/lead/Coverage.dc.html`, `boards/planning/PCoverage.dc.html`
- **Modify:** `components/areas/CoverageForm.tsx`, `components/areas/CoverageByTime.tsx`, `app/(lead)/lead/coverage/[serviceId]/page.tsx`, `app/(planning)/planning/coverage/page.tsx`, `components/areas/coverage.module.css`
- **Tests to update:** `components/areas/Coverage.test.tsx`
- **Read only (shared):** `components/console/Console.module.css`, `components/lead/ErrorSummary.tsx`
- **Gaps:** "No service covers DT7 to DT11 at weekends" needs planning coverage gaps for the lead role: reuse GET /api/bff/planning/coverage if the lead may read it, otherwise omit the card. Tile detail shows services only, not hours per service.
- **Notes:** Coverage.test.tsx tests both components: you own it. lead/ErrorSummary (frozen) is imported by CoverageForm. planning/coverage page imports Console.module.css (frozen): use your own css. No Console.module.css edits.

### CRI-01: Criteria owner: landing and the review flow shell

- **Surface:** lead. **Wave:** 1. **Size:** M. **Model:** sonnet (The owner morph (review, confirm, change, preview, send, waiting) lives in CriteriaFlow.).
- **Routes:** `/criteria`, `/criteria/[serviceId]`
- **Depends on:** FOUNDATION, LED-00a
- **Brief:** `docs/design/redesign/lead-and-setup.md > "/criteria, /criteria/[serviceId], ... Criteria owner" (states and landing)`
- **Boards:** `boards/lead/OwnerReview.dc.html`, `boards/lead/OwnerPhone.dc.html`, `boards/lead/States.dc.html`
- **Modify:** `components/owner/CriteriaFlow.tsx`, `app/(owner)/criteria/page.tsx`, `app/(owner)/criteria/[serviceId]/page.tsx`
- **Tests to update:** `app/(owner)/criteria/page.test.tsx`
- **Read only (shared):** `components/lead/lead-forms.module.css`
- **Gaps:** The landing lists services by id only (the session carries ids); names and review dates need the criteria overview per service or a list endpoint: show what exists.
- **Notes:** CriteriaFlow becomes the MorphStage using StepBar and SummaryPin. The step panels (Overview, Editor, Confirm, Preview, Send, Status) are in CRI-02 to CRI-04 which run after you: keep their props. With several services a list ordered by what is due; with one go straight in; with none "No services to review" and Help. criteria/page.tsx imports lead-forms.module.css (frozen). CriteriaFlow has no test today: add one.

### CRI-05: Second approval

- **Surface:** lead. **Wave:** 1. **Size:** M. **Model:** sonnet (Clinical approval screen: the diff is the screen, approve is never the initial focus, two-person rule in words.).
- **Routes:** `/criteria/[serviceId]/approve`
- **Depends on:** FOUNDATION, LED-00b
- **Brief:** `docs/design/redesign/lead-and-setup.md > Criteria "Second approval" (approver diff)`
- **Boards:** `boards/lead/Approve.dc.html`, `boards/lead/ApprovePhone.dc.html`
- **Modify:** `components/owner/CriteriaApproval.tsx`, `app/(owner)/criteria/[serviceId]/approve/page.tsx`
- **Tests to update:** `components/owner/CriteriaApproval.test.tsx`
- **Read only (shared):** `components/lead/lead-forms.module.css`
- **Gaps:** none
- **Notes:** Diff (what, was, now) via DiffTable, reason and sender, "Approve version n" and "Send it back with a note"; the full criteria open on request. The diff does not animate. GET /pending, POST /pending/decision.

### CRI-06: Criteria history

- **Surface:** lead. **Wave:** 1. **Size:** S. **Model:** haiku (Read-only timeline of versions.).
- **Routes:** `/criteria/[serviceId]/history`
- **Depends on:** FOUNDATION, LED-00b
- **Brief:** `docs/design/redesign/lead-and-setup.md > Criteria "Criteria history"`
- **Boards:** `boards/lead/History.dc.html`
- **Modify:** `components/owner/CriteriaHistory.tsx`, `app/(owner)/criteria/[serviceId]/history/page.tsx`
- **Tests to update:** `components/owner/CriteriaHistory.test.tsx`
- **Read only (shared):** `components/lead/lead-forms.module.css`
- **Gaps:** Who sent and approved each version, when, and what changed are not in the history parse: show version, state and review-by only.
- **Notes:** Use VersionTimeline (LED-00b).

### LDR-02: Chase card with inline ladder and phoned side sheet

- **Surface:** lead. **Wave:** 1. **Size:** M. **Model:** sonnet (Records what a service said by phone; side sheet traps focus and returns it.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, LED-00b
- **Brief:** `docs/design/redesign/lead-and-setup.md > "/lead" (States 2: a chase opens; LadderTimeline; LeadPhonedDialog becomes a side sheet)`
- **Boards:** `boards/lead/OverviewChase.dc.html`, `boards/lead/PhoneOverview.dc.html`
- **Modify:** `components/lead/ChaseCard.tsx`, `components/lead/LeadPhonedDialog.tsx`
- **Tests to update:** `components/lead/ChaseCard.test.tsx`, `components/lead/LeadPhonedDialog.test.tsx`
- **Read only (shared):** `components/lead/Lead.module.css`, `components/advisor/dialog-body.module.css`
- **Gaps:** none
- **Notes:** Not a route unit: it supplies components for LDR-01 (overview), INV-01 (SetupTracker), LDR-09 (flags) and LDR-07 (suspend), all of which import LeadPhonedDialog: keep its exported props unchanged. dialog-body.module.css is frozen (also used by advisor dialogs and ScreenBoardChoice/ScreenUnpair): use your own css for the sheet.

### LDR-03: Add a service: steps 1 and 2 on one form state

- **Surface:** lead. **Wave:** 1. **Size:** L. **Model:** sonnet (Multi-step morph form; per-step validation; single Idempotency-Key submit.).
- **Routes:** `/lead/services/new`
- **Depends on:** FOUNDATION, LED-00a
- **Brief:** `docs/design/redesign/lead-and-setup.md > "/lead/services/new" (steps The service and Who reports)`
- **Boards:** `boards/lead/AddService.dc.html`
- **Modify:** `components/lead/AddServiceForm.tsx`, `app/(lead)/lead/services/new/page.tsx`
- **Add:**
  - frontend/components/lead/addservice/useServiceFormState.ts (+ .test.ts)
  - frontend/components/lead/addservice/StepService.tsx (+ .module.css, .test.tsx)
  - frontend/components/lead/addservice/StepReporting.tsx (+ .module.css, .test.tsx)
- **Tests to update:** `components/lead/AddServiceForm.test.tsx`
- **Read only (shared):** `components/lead/Lead.module.css`, `components/lead/ErrorSummary.tsx`
- **Gaps:** "Who owns these criteria" is not in the body (lib/lead/serviceBody.ts has reviewBy only): drop the field until the back end adds criteriaOwner.
- **Notes:** Split AddServiceForm into step components over one form state (in memory only, nothing stored in the browser); each step is a ?step= value so Back and reload work. In THIS unit build steps 1 and 2 and leave steps 3 and 4 rendered by the existing field code; LDR-04 then builds steps 3 and 4, Check and Added. Reuse lib/lead/serviceForm.ts validation. Lead.module.css is frozen.

### LDR-05: Services in scope

- **Surface:** lead. **Wave:** 1. **Size:** M. **Model:** haiku (List with filter chips and an add panel over existing data.).
- **Routes:** `/lead/scope`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/lead-and-setup.md > "/lead/scope"`
- **Boards:** `boards/lead/Scope.dc.html`, `boards/lead/States.dc.html`
- **Modify:** `components/lead/ScopeList.tsx`, `components/lead/AddScopeForm.tsx`, `app/(lead)/lead/scope/page.tsx`
- **Tests to update:** `components/lead/ScopeList.test.tsx`
- **Read only (shared):** `components/lead/lead-forms.module.css`
- **Gaps:** none
- **Notes:** Filters are aria-pressed buttons with the count in their name; the add form opens in a right panel (a labelled region, not a modal). Reason required unless in pilot, 280 character count. Invite only for in-pilot services not yet invited.

### LDR-06: Phones and services; move a service

- **Surface:** lead. **Wave:** 1. **Size:** M. **Model:** sonnet (Move texts a code to a new phone and changes who receives a service.).
- **Routes:** `/lead/phones`, `/lead/phones/move`
- **Depends on:** FOUNDATION, LED-00b, NET-00
- **Brief:** `docs/design/redesign/lead-and-setup.md > "/lead/phones and /lead/phones/move"`
- **Boards:** `boards/lead/Phones.dc.html`, `boards/lead/Move.dc.html`
- **Modify:** `components/lead/PhonesList.tsx`, `components/lead/MoveServiceForm.tsx`, `app/(lead)/lead/phones/page.tsx`, `app/(lead)/lead/phones/move/page.tsx`
- **Tests to update:** `components/lead/PhonesList.test.tsx`, `components/lead/MoveServiceForm.test.tsx`
- **Read only (shared):** `components/lead/Lead.module.css`
- **Gaps:** "Usual reports" is not on the phones row: drop it from the open row unless the back end adds it.
- **Notes:** Row opens with the height ease (Disclose) and shows services, coverage area, actions (change number, move, edit coverage, remove access). Mobile numbers only ever as last four digits. Move: right panel always shows the three steps (LadderTimeline) and "Nothing moves until step 3". Pre-fill for remove access: link to /lead/people/remove?... (read by LDR-08).

### LDR-08: Remove someone's access

- **Surface:** lead. **Wave:** 1. **Size:** S. **Model:** haiku (One form plus the shared ConfirmDialog; wording rules from the brief.).
- **Routes:** `/lead/people/remove`
- **Depends on:** FOUNDATION, LED-00b
- **Brief:** `docs/design/redesign/lead-and-setup.md > "/lead/people/remove"`
- **Boards:** `boards/lead/RemoveAccess.dc.html`, `boards/lead/States.dc.html`
- **Modify:** `components/lead/RemovePersonForm.tsx`, `app/(lead)/lead/people/remove/page.tsx`
- **Tests to update:** `components/lead/RemovePersonForm.test.tsx`
- **Read only (shared):** `components/lead/Lead.module.css`
- **Gaps:** No people search exists for reporters: the who field takes a role or the last four digits.
- **Notes:** Confirm is an alertdialog naming the person and reason; the destructive button names them ("Remove access for ···0377"); focus starts on the safe button, same size. POST /api/bff/lead/people/remove.

### LDR-10: Audit search and replay

- **Surface:** lead. **Wave:** 1. **Size:** S. **Model:** haiku (Read-only display of an existing replay answer.).
- **Routes:** `/lead/audit`, `/lead/audit/[ref]`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/lead-and-setup.md > "/lead/audit and /lead/audit/[ref]"`
- **Boards:** `boards/lead/Audit.dc.html`
- **Modify:** `components/lead/AuditSearch.tsx`, `components/lead/AuditReplay.tsx`, `app/(lead)/lead/audit/page.tsx`, `app/(lead)/lead/audit/[ref]/page.tsx`
- **Tests to update:** `components/lead/AuditSearch.test.tsx`, `components/lead/AuditReplay.test.tsx`
- **Read only (shared):** `components/lead/Lead.module.css`
- **Gaps:** none
- **Notes:** Integrity result is a status in words, not only an icon; timeline is an ordered list. "Looked at today" is optional and memory only (never store references in the browser). [ref] page imports Lead.module.css (frozen): use your own css.

### LDR-11: Wall screens list

- **Surface:** lead. **Wave:** 1. **Size:** M. **Model:** haiku (Cards per screen with per-state actions over existing data; inline confirm uses ConfirmDialog.).
- **Routes:** `/lead/screens`
- **Depends on:** FOUNDATION, LED-00b
- **Brief:** `docs/design/redesign/lead-and-setup.md > "/lead/screens and /lead/screens/new" (list states)`
- **Boards:** `boards/lead/Screens.dc.html`
- **Modify:** `components/lead/ScreenList.tsx`, `components/lead/ScreenUnpair.tsx`, `components/lead/ScreenBoardChoice.tsx`, `app/(lead)/lead/screens/page.tsx`
- **Tests to update:** `components/lead/ScreenList.test.tsx`, `app/(lead)/lead/screens/page.test.tsx`
- **Read only (shared):** `components/lead/Lead.module.css`, `components/advisor/dialog-body.module.css`
- **Gaps:** none
- **Notes:** Thumbnail is drawn from the board counts, not a screenshot. Unpair opens an inline confirm on the card. A screen set to a network that is no longer open says so. advisor/dialog-body.module.css (used by ScreenBoardChoice, ScreenUnpair) is frozen: use your own css.

### LDR-12: Add a wall screen (pairing flow)

- **Surface:** lead. **Wave:** 1. **Size:** M. **Model:** sonnet (Pairing code entry and approval; refused-code states keep values; preview crossfades when connected.).
- **Routes:** `/lead/screens/new`
- **Depends on:** FOUNDATION, LED-00a
- **Brief:** `docs/design/redesign/lead-and-setup.md > "/lead/screens and /lead/screens/new" (pair states)`
- **Boards:** `boards/lead/ScreenPair.dc.html`, `boards/lead/States.dc.html`
- **Modify:** `components/screens/ScreenForm.tsx`, `components/screens/ScreenForm.module.css`, `app/(lead)/lead/screens/new/page.tsx`
- **Tests to update:** `components/screens/ScreenForm.test.tsx`, `app/(lead)/lead/screens/new/page.test.tsx`
- **Gaps:** none
- **Notes:** States: enter the code, name, place -> refused code (words, values kept) -> check ("Is this the right screen?") -> connected. The pairing endpoints are unchanged (GET/POST screens, screens/pairing).

### LRV-01: Review a registration: queue and overview in one stage

- **Surface:** onboarding. **Wave:** 1. **Size:** L. **Model:** sonnet (The review morph; DEC-1323 address check with no area set passes ("No area limit is set").).
- **Routes:** `/lead/registrations`, `/lead/registrations/[id]`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 4: review a registration (shift lead)" (stages, automatic checks, DEC-1323)`
- **Boards:** `boards/onboarding/Rev1.dc.html`, `boards/onboarding/RevChecks.dc.html`, `boards/onboarding/RvP1.dc.html`, `boards/onboarding/RvP2.dc.html`, `boards/onboarding/States.dc.html`
- **Modify:** `components/lead/RegistrationQueue.tsx`, `components/lead/RegistrationOverview.tsx`, `app/(lead)/lead/registrations/page.tsx`, `app/(lead)/lead/registrations/[id]/page.tsx`
- **Add:**
  - frontend/components/lead/registration/RegistrationStage.tsx (StageGrid list | stage; queue narrows on open) (+ .module.css, .test.tsx)
  - frontend/components/lead/registration/CheckList.tsx (automatic checks; shape plus word; first problem copied to the queue card) (+ .module.css, .test.tsx)
- **Tests to update:** `components/lead/RegistrationQueue.test.tsx`, `components/lead/RegistrationOverview.test.tsx`
- **Read only (shared):** `components/lead/lead-forms.module.css`
- **Gaps:** The second approval by the clinical lead is not designed here. "Approved today 15:00" and test times only if the review answer carries them.
- **Notes:** A check that needs attention never blocks the review: the back-end list of what is missing is the only gate (DecideStep reads it). The [id] page also renders the four step components (owned by LRV-02 and LRV-03): keep their props. lead-forms.module.css is frozen: use your own css.

### NAD-01: Network administration: members, agreement and health

- **Surface:** network. **Wave:** 1. **Size:** M. **Model:** sonnet (Ending a membership asks a second administrator; add an organisation in place.).
- **Routes:** `/network-admin`
- **Depends on:** FOUNDATION, PLN-00b
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Network administration > /network-admin`
- **Boards:** `boards/planning/NAdmin.dc.html`
- **Modify:** `components/networkAdmin/NetworkMembers.tsx`, `components/networkAdmin/OwnedNetworkGate.tsx`, `app/(network-admin)/network-admin/page.tsx`
- **Tests to update:** `components/networkAdmin/NetworkMembers.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`
- **Gaps:** Health columns last update received, delay and updates refused are not in the projection (brief 4 item 4): show the source state (active or ended) only.
- **Notes:** OwnedNetworkGate is imported by the other three network-admin components: keep exports. admin.module.css is frozen: use your own css. network-admin/pages.test.tsx is owned by NAD-99.

### NET-03: Network directory and service detail

- **Surface:** network. **Wave:** 1. **Size:** M. **Model:** sonnet (Master list and detail pane in a StageGrid with organisation and category chips; read-only criteria.).
- **Routes:** `/network/services`, `/network/services/[id]`
- **Depends on:** FOUNDATION, NET-00
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Network > /network/services, /network/services/[id]`
- **Boards:** `boards/planning/NServices.dc.html`
- **Modify:** `components/network/NetworkServicesView.tsx`, `components/network/NetworkServiceDetail.tsx`, `components/scope/NetworkServiceCard.tsx`, `app/(network)/network/services/page.tsx`, `app/(network)/network/services/[id]/page.tsx`
- **Tests to update:** `components/network/NetworkServicesView.test.tsx`, `components/network/NetworkServiceDetail.test.tsx`, `components/scope/NetworkServiceCard.test.tsx`
- **Read only (shared):** `components/network/Network.module.css`
- **Gaps:** none
- **Notes:** Imports network/Network.module.css (frozen): use your own css. network/pages.test.tsx is owned by NET-99.

### NET-04: Network system now

- **Surface:** network. **Wave:** 1. **Size:** S. **Model:** haiku (One stacked bar and a notice over an existing read.).
- **Routes:** `/network/system-now`
- **Depends on:** FOUNDATION, NET-00, PLN-00a
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Network > /network/system-now`
- **Boards:** `boards/planning/NSystemNow.dc.html`
- **Modify:** `components/network/NetworkSystemNowView.tsx`, `app/(network)/network/system-now/page.tsx`
- **Tests to update:** `components/network/NetworkSystemNowView.test.tsx`
- **Read only (shared):** `components/network/Network.module.css`
- **Gaps:** none
- **Notes:** Pressure notice, stacked status bar with every status and its number, what this is, what a failed read looks like.

### NET-05: Network phones

- **Surface:** network. **Wave:** 1. **Size:** S. **Model:** haiku (A DataTable of existing rows with phone links.).
- **Routes:** `/network/phones`
- **Depends on:** FOUNDATION, NET-00, PLN-00b
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Network > /network/phones`
- **Boards:** `boards/planning/NPhones.dc.html`
- **Modify:** `components/network/NetworkPhonesView.tsx`, `app/(network)/network/phones/page.tsx`
- **Tests to update:** `components/network/NetworkPhonesView.test.tsx`
- **Read only (shared):** `components/network/Network.module.css`
- **Gaps:** none
- **Notes:** Table: service, organisation, service line (tel: link via scope/PhoneLink), last reported.

### NET-07: Network history (left or stopped sharing)

- **Surface:** network. **Wave:** 1. **Size:** S. **Model:** haiku (Warning notice, filter and rows over an existing read.).
- **Routes:** `/network/history`
- **Depends on:** FOUNDATION, NET-00
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Network > /network/history`
- **Boards:** `boards/planning/NHistory.dc.html`
- **Modify:** `components/network/NetworkHistoryView.tsx`, `app/(network)/network/history/page.tsx`
- **Tests to update:** `components/network/NetworkHistoryView.test.tsx`
- **Read only (shared):** `components/network/Network.module.css`
- **Gaps:** Confirm the field for "last shown" (brief table note).
- **Notes:** Filter All, Left, Stopped; rows with the date and a "Last known" tag.

### ONB-01: Invitation page and set-up steps: welcome, number, code, channel

- **Surface:** onboarding. **Wave:** 1. **Size:** L. **Model:** sonnet (Identity: invitation code, verify, device codes; exec shortcut; skip rules; six-box single-input code.).
- **Routes:** `/i/[token]`, `/setup`
- **Depends on:** FOUNDATION, ONB-00
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 2: provider first-run set-up (phone)"`
- **Boards:** `boards/onboarding/R1.dc.html`, `boards/onboarding/R2.dc.html`, `boards/onboarding/R3.dc.html`, `boards/onboarding/R4.dc.html`, `boards/onboarding/States.dc.html`
- **Modify:** `components/reporter/setup/InvitationLoader.tsx`, `components/reporter/setup/SetupFlow.tsx`, `components/reporter/CodeEntry.tsx`, `components/reporter/CodeInput.tsx`, `components/reporter/CodeInput.module.css`, `app/i/[token]/page.tsx`, `app/(reporter)/setup/page.tsx`
- **Tests to update:** `components/reporter/setup/InvitationLoader.test.tsx`, `components/reporter/setup/SetupFlow.test.tsx`, `components/reporter/CodeInput.test.tsx`
- **Read only (shared):** `components/reporter/setup/Setup.module.css`, `components/reporter/parts/Parts.module.css`
- **Gaps:** none for this unit.
- **Notes:** Keep the skip of steps 3 and 4 for text and email and the exec shortcut from the code step to the home screen. Code boxes are ONE input (inputmode numeric, autocomplete one-time-code) drawn as six boxes, repeat(6, minmax(0,1fr)) at 320px. Expired or bad token shows the Expired state with no request made. CodeEntry and CodeInput are imported by REP-09 and REP-10 (they run after): keep exports. Setup.module.css and Parts.module.css are frozen: use your own css.

### ONB-02: Set-up: add to home screen and notifications

- **Surface:** onboarding. **Wave:** 1. **Size:** S. **Model:** haiku (Mechanical re-skin into ProviderShell with StickyAction; existing permission logic unchanged.).
- **Routes:** `/setup/home-screen`, `/setup/notifications`
- **Depends on:** FOUNDATION, ONB-00
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 2" (steps 3 and 4)`
- **Boards:** `boards/onboarding/R5.dc.html`, `boards/onboarding/R6.dc.html`
- **Modify:** `components/reporter/setup/HomeScreen.tsx`, `components/reporter/setup/Notifications.tsx`, `app/(reporter)/setup/home-screen/page.tsx`, `app/(reporter)/setup/notifications/page.tsx`
- **Tests to update:** `components/reporter/setup/HomeScreen.test.tsx`, `components/reporter/setup/Notifications.test.tsx`
- **Read only (shared):** `components/reporter/setup/Setup.module.css`
- **Gaps:** none
- **Notes:** Wrap in ProviderShell, replace the page header and button row with SetupProgress and StickyAction. Keep every existing permission and storage behaviour.

### ONB-03: Set-up: PIN keypad (92px keys, auto-advance)

- **Surface:** onboarding. **Wave:** 1. **Size:** M. **Model:** sonnet (PIN entry and confirm-once-more security behaviour.).
- **Routes:** `/setup/pin`
- **Depends on:** FOUNDATION, ONB-00
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 2" (PIN keypad)`
- **Boards:** `boards/onboarding/R7.dc.html`
- **Modify:** `components/reporter/setup/PinSetup.tsx`, `components/reporter/PinPad.tsx`, `components/reporter/PinPad.module.css`, `app/(reporter)/setup/pin/page.tsx`
- **Tests to update:** `components/reporter/setup/PinSetup.test.tsx`, `components/reporter/PinPad.test.tsx`
- **Gaps:** none
- **Notes:** Keypad 92px keys (repeat(3, minmax(0,76px)) at 320px), auto-advance at six digits, no Continue button; keep the confirm-once-more behaviour. PinPad is imported by REP-04 (PinScreen) and PinSetup by REP-09 (LockedScreen): keep exports.

### ONB-04: Set-up: all set and set up by text or email

- **Surface:** onboarding. **Wave:** 1. **Size:** S. **Model:** haiku (Static summary pages in ProviderShell.).
- **Routes:** `/setup/all-set`, `/setup/done`
- **Depends on:** FOUNDATION, ONB-00
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 2" (All set) and "States on every list and detail"`
- **Boards:** `boards/onboarding/R8.dc.html`, `boards/onboarding/States.dc.html`
- **Modify:** `components/reporter/setup/AllSet.tsx`, `app/(reporter)/setup/all-set/page.tsx`, `app/(reporter)/setup/done/page.tsx`
- **Tests to update:** `components/reporter/setup/AllSet.test.tsx`, `app/(reporter)/setup/done/page.test.tsx`
- **Read only (shared):** `components/reporter/setup/Setup.module.css`
- **Gaps:** The board shows "Your role" and "PIN set"; setup-summary has neither (brief gap 2): show service, contact by, phone, next update and drop role and PIN rows.
- **Notes:** setup/done/page.tsx imports Setup.module.css (frozen): move its styles to your own css.

### OPR-01: Operator sign-in

- **Surface:** admin. **Wave:** 1. **Size:** S. **Model:** haiku (Re-skin into SplitHero; the start route is unchanged.).
- **Routes:** `/operator/sign-in`
- **Depends on:** FOUNDATION, PUB-00
- **Brief:** `docs/design/redesign/admin-operator-public.md > Operator console > /operator/sign-in (board O1)`
- **Boards:** `boards/admin/O1.dc.html`
- **Modify:** `app/(operator)/operator/sign-in/page.tsx`, `app/(operator)/operator/sign-in/page.module.css`
- **Gaps:** none
- **Notes:** States: normal; "We could not sign you in" banner. Page tests are in operator/pages.test.tsx (OPR-99). Platform operators, not staff: keep the existing start route.

### OPR-02: Operator organisations list

- **Surface:** admin. **Wave:** 1. **Size:** M. **Model:** sonnet (Per-row progress needs lazy detail reads for visible rows (no list payload yet).).
- **Routes:** `/operator`
- **Depends on:** FOUNDATION, ADM-00b
- **Brief:** `docs/design/redesign/admin-operator-public.md > Operator console > /operator (board O2)`
- **Boards:** `boards/admin/O2.dc.html`
- **Modify:** `components/operator/TenantList.tsx`, `app/(operator)/operator/(area)/page.tsx`
- **Tests to update:** `components/operator/TenantList.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`
- **Gaps:** Per-organisation partsDone and nextStep are derived from the detail (lib/operator/funnel.ts) which needs one read per row: read lazily for visible rows, or add the fields to the list payload.
- **Notes:** Search and status chips (All, Being set up, Live), one card per organisation with ProgressBar5 and its next step in words. The page imports admin.module.css (frozen): use your own css.

### OPR-03: Create an organisation

- **Surface:** admin. **Wave:** 1. **Size:** M. **Model:** sonnet (NHS name search, directory lookup and tenant creation (platform identity).).
- **Routes:** `/operator/tenants/new`
- **Depends on:** FOUNDATION, ADM-00b
- **Brief:** `docs/design/redesign/admin-operator-public.md > Operator console > /operator/tenants/new (board O3)`
- **Boards:** `boards/admin/O3.dc.html`
- **Modify:** `components/operator/CreateTenantForm.tsx`, `app/(operator)/operator/(area)/tenants/new/page.tsx`
- **Tests to update:** `components/operator/CreateTenantForm.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`, `components/lead/ErrorSummary.tsx`
- **Gaps:** none
- **Notes:** Three parts as rows with a "What will be created" card. Part 3 optional, skipped by default. "I already have the directory id" is a disclosure. GET /platform/ods, /ods/[code], /directory-lookup, POST /platform/tenants. Uses lead/ErrorSummary (frozen).

### OPR-04: Go-live funnel: extract the seven steps into one file each (no behaviour change)

- **Surface:** admin. **Wave:** 1. **Size:** L. **Model:** sonnet (Mechanical but large (911-line TenantPanels and an 860-line test) and must lose no assertion.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/admin-operator-public.md > Operator console > /operator/tenants/[id] (board O4)`
- **Boards:** `boards/admin/O4.dc.html`
- **Modify:** `components/operator/TenantPanels.tsx`, `components/operator/TenantLifecycle.tsx`, `components/operator/TenantPhases.tsx`
- **Add:**
  - frontend/components/operator/funnel/shared.tsx (Detail, PanelProps, StepSection, useWrite, helpers)
  - frontend/components/operator/funnel/OrganisationStep.tsx, SignInStep.tsx, InviteStep.tsx, TeamStep.tsx, RolesStep.tsx, ReachStep.tsx, AgreementsStep.tsx, GoLiveStep.tsx, LifecyclePanel.tsx
  - frontend/components/operator/funnel/*.test.tsx (the describes of TenantDetail.test.tsx moved, not weakened)
- **Tests to update:** `components/operator/TenantDetail.test.tsx`
- **Read only (shared):** `components/operator/Tenant.module.css`, `components/admin/admin.module.css`
- **Gaps:** The brief says five parts; the code has seven steps inside five phases (PhaseId): keep the seven steps.
- **Notes:** Pure refactor so that OPR-05..OPR-09 own disjoint files. TenantPanels.tsx and TenantLifecycle.tsx remain as thin re-export files so imports keep working. Split TenantDetail.test.tsx by its describe blocks (what the page shows stays in TenantDetail.test.tsx; each step_n describe moves to funnel/<Step>.test.tsx). Run the full operator folder before and after; counts must match.

### OPR-10: Operator support requests

- **Surface:** admin. **Wave:** 1. **Size:** L. **Model:** sonnet (Requests access to a customer organisation; right-hand dialog sheet with focus trap and Escape; access code entry.).
- **Routes:** `/operator/support`, `/operator/support/new`, `/operator/support/tickets/[id]`
- **Depends on:** FOUNDATION, ADM-00a, ADM-00b
- **Brief:** `docs/design/redesign/admin-operator-public.md > Operator console > /operator/support, /new, /tickets/[id] (board O5)`
- **Boards:** `boards/admin/O5.dc.html`
- **Modify:** `components/operator/SupportRequestList.tsx`, `components/operator/SupportTicketDetail.tsx`, `components/operator/NewSupportRequest.tsx`, `app/(operator)/operator/(area)/support/page.tsx`, `app/(operator)/operator/(area)/support/new/page.tsx`, `app/(operator)/operator/(area)/support/tickets/[id]/page.tsx`
- **Tests to update:** `components/operator/SupportRequestList.test.tsx`, `components/operator/SupportTicketDetail.test.tsx`, `components/operator/NewSupportRequest.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`, `components/lead/ErrorSummary.tsx`
- **Gaps:** none
- **Notes:** Three stages in a request: Asked, They approve, You open it. Ask for access is a right-hand sheet (dialog, focus trap, Escape). States: waiting, approved (enter the code), ended, refused, expired, empty, error, sending. Uses lead/ErrorSummary (frozen).

### OPR-11: Operator audit chain

- **Surface:** admin. **Wave:** 1. **Size:** S. **Model:** haiku (Read-only timeline and an integrity card.).
- **Routes:** `/operator/audit`
- **Depends on:** FOUNDATION, ADM-00b
- **Brief:** `docs/design/redesign/admin-operator-public.md > Operator console > /operator/audit (board O6)`
- **Boards:** `boards/admin/O6.dc.html`
- **Modify:** `components/operator/AuditChain.tsx`, `app/(operator)/operator/(area)/audit/page.tsx`
- **Tests to update:** `components/operator/AuditChain.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`
- **Gaps:** none
- **Notes:** Broken chain shows "broken at entry n" and hides nothing. Check again re-verifies (GET /platform/audit/verification).

### OPR-12: Administrator approval return page

- **Surface:** admin. **Wave:** 1. **Size:** S. **Model:** haiku (Public outcome page over an existing server check; five outcomes.).
- **Routes:** `/admin-consent/return`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/admin-operator-public.md > Operator console > /admin-consent/return (board C1)`
- **Boards:** `boards/admin/C1.dc.html`
- **Modify:** `app/admin-consent/return/page.tsx`
- **Tests to update:** `app/admin-consent/return/page.test.tsx`
- **Gaps:** none
- **Notes:** Approved (large), not approved yet (Check again), no longer valid, could not check just now, not valid. The organisation name appears only after the back end confirms.

### PLN-01: Planning home and the planning stage

- **Surface:** planning. **Wave:** 1. **Size:** L. **Model:** sonnet (The home -> service -> alert morph (highest-stakes path); layout changes only on the person's choice.).
- **Routes:** `/planning`
- **Depends on:** FOUNDATION, PLN-00b, NET-00
- **Brief:** `docs/design/redesign/planning-analytics-network.md > "3. Route by route" > Planning > /planning and "5. Motion"`
- **Boards:** `boards/planning/PHome.dc.html`, `boards/planning/Morph.dc.html`, `boards/planning/PH1.dc.html`, `boards/planning/PStates.dc.html`
- **Modify:** `components/exec/ExecHome.tsx`, `app/(exec)/planning/page.tsx`
- **Add:**
  - frontend/components/exec/PlanningStage.tsx (StageGrid with data-stage home|service|alert; the three planning units render into it) (+ .module.css, .test.tsx)
- **Tests to update:** `components/exec/ExecHome.test.tsx`
- **Read only (shared):** `components/exec/Exec.module.css`
- **Gaps:** none for home. Needs-attention is derived client-side from the board; week glance uses exec/week.
- **Notes:** PlanningStage is used by PLN-02 and PLN-03 (they run after you): define its slots and keep them. State is the route (services/[id], alerts/[id]). Clinical-safety review of the morph (brief 6.2): Acknowledge, Call and Snooze keep their positions. Exec.module.css is frozen. pages.network.test.tsx (page tests of planning, services, services/[id]) is owned by PLN-99.

### PLN-04: This week

- **Surface:** planning. **Wave:** 1. **Size:** S. **Model:** sonnet (Chart and estimate rules: no saving claimed before measured; sum behind a disclosure; range shown.).
- **Routes:** `/planning/week`
- **Depends on:** FOUNDATION, PLN-00a, NET-00
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Planning > /planning/week`
- **Boards:** `boards/planning/PWeek.dc.html`
- **Modify:** `components/exec/WeekSummary.tsx`, `app/(exec)/planning/week/page.tsx`
- **Tests to update:** `components/exec/WeekSummary.test.tsx`
- **Read only (shared):** `components/exec/Exec.module.css`
- **Gaps:** There is no per-day pressure series in the tenant week summary (brief 4 item 2): drop the chart from the first release unless the back end extends $week-summary.
- **Notes:** "Time back (estimate)" shows its sum behind a disclosure; "[x] minutes" placeholders stay visible where the baseline is not measured. WeekSummary is imported by exec/NetworkWeek (NET-06 runs after you): keep exports.

### PLN-05: Alerts on this phone

- **Surface:** planning. **Wave:** 1. **Size:** S. **Model:** haiku (Re-skin of an existing push-permission screen; logic unchanged.).
- **Routes:** `/planning/phone`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Planning > /planning/phone`
- **Boards:** `boards/planning/PH5.dc.html`
- **Modify:** `components/exec/PhoneAlerts.tsx`, `app/(exec)/planning/phone/page.tsx`
- **Tests to update:** `components/exec/PhoneAlerts.test.tsx`, `app/(exec)/planning/phone/page.test.tsx`
- **Read only (shared):** `components/exec/Exec.module.css`
- **Gaps:** none
- **Notes:** What we send and never send; "On an iPhone" disclosure; Allow; Send a test; Change which alerts. Keep push/key, push/subscriptions, push/test.

### PLN-06: Alert settings and first-run set-up

- **Surface:** planning. **Wave:** 1. **Size:** M. **Model:** sonnet (Switches with state in words and reveal logic; setup is the same page with a stepper.).
- **Routes:** `/planning/settings`, `/planning/setup`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Planning > /planning/setup, /planning/settings`
- **Boards:** `boards/planning/PSettings.dc.html`
- **Modify:** `components/exec/SettingsForm.tsx`, `components/exec/SetupFlow.tsx`, `components/exec/AlertSwitches.tsx`, `components/exec/EscalationForm.tsx`, `app/(exec)/planning/settings/page.tsx`, `app/(exec)/planning/setup/page.tsx`
- **Tests to update:** `components/exec/SettingsForm.test.tsx`, `components/exec/SetupFlow.test.tsx`, `components/exec/AlertSwitches.test.tsx`, `components/exec/EscalationForm.test.tsx`
- **Read only (shared):** `components/exec/Exec.module.css`
- **Gaps:** none
- **Notes:** Six switches with state in words; "After 2 or 4 hrs" revealed under its switch; quiet hours and escalation in a disclosure. GET/PUT exec/alert-preferences. ui/Banner is shared (do not edit).

### PLN-07: Right-sizing flows

- **Surface:** planning. **Wave:** 1. **Size:** M. **Model:** sonnet (Charts, filters, numbers in cells, CSV export; table beside every chart.).
- **Routes:** `/planning/flows`
- **Depends on:** FOUNDATION, PLN-00a, PLN-00b
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Planning > /planning/flows`
- **Boards:** `boards/planning/PFlows.dc.html`, `boards/planning/PCharts.dc.html`
- **Modify:** `components/planning/PlanningView.tsx`, `components/planning/FlowsTable.tsx`, `components/planning/HeatGrid.tsx`, `app/(planning)/planning/flows/page.tsx`, `components/planning/Planning.module.css`
- **Tests to update:** `components/planning/PlanningView.test.tsx`, `components/planning/FlowsTable.test.tsx`, `components/planning/HeatGrid.test.tsx`
- **Read only (shared):** `components/console/Console.module.css`
- **Gaps:** none
- **Notes:** Filters (period, need), three figures, flows table with inline bars, day-by-time grid with numbers in cells, "declined despite showing capacity", cohort and how-to-read behind disclosures, Export CSV. Counts under 10 read "under 10", never zero. Page imports Console.module.css (frozen): use your own css.

### PRA-01: Practitioner shift, round and location

- **Surface:** reporter. **Wave:** 1. **Size:** M. **Model:** sonnet (Shift status writes and the location promise; shared test file with the visit screens.).
- **Routes:** `/app/practitioner`, `/app/practitioner/round`, `/app/practitioner/location`
- **Depends on:** FOUNDATION, REP-00a, REP-00b
- **Brief:** `docs/design/redesign/reporter-app.md > "Per route" > Practitioner (/app/practitioner, /round, /location, B10)`
- **Boards:** `boards/reporter/B10.dc.html`, `boards/reporter/St.dc.html`
- **Modify:** `components/practitioner/ShiftScreen.tsx`, `components/practitioner/RoundScreen.tsx`, `components/practitioner/LocationScreen.tsx`, `components/practitioner/PhoneScreen.tsx`, `app/(reporter)/app/practitioner/page.tsx`, `app/(reporter)/app/practitioner/round/page.tsx`, `app/(reporter)/app/practitioner/location/page.tsx`, `components/practitioner/practitioner.module.css`
- **Tests to update:** `components/practitioner/Practitioner.test.tsx`
- **Gaps:** Location text points to a Settings route that does not exist (brief gap 4): add a small page or change the sentence (decide with the lead developer; prefer changing the sentence).
- **Notes:** Practitioner.test.tsx covers all five screens: you own it first and update the shift, round and location describes; PRA-02 edits the visit describes afterwards. practitioner.module.css is yours; PRA-02 only reads it.

### PUB-01: Home page and splash preview

- **Surface:** public. **Wave:** 1. **Size:** M. **Model:** haiku (Static page in SplitHero; splash is one ring and a dot with a single spring.).
- **Routes:** `/`, `/splash-preview`
- **Depends on:** FOUNDATION, PUB-00
- **Brief:** `docs/design/redesign/admin-operator-public.md > "5. Public and cross-cutting" > / and /splash-preview (board P1)`
- **Boards:** `boards/admin/P1.dc.html`
- **Modify:** `app/page.tsx`, `app/splash-preview/page.tsx`, `app/page.module.css`, `app/splash-preview/SplashPreview.tsx`, `components/brand/Splash.tsx`, `components/brand/Splash.module.css`
- **Tests to update:** `app/page.test.tsx`
- **Gaps:** none
- **Notes:** Logo, one line, Sign in; "Platform console" as a quiet link. Splash (dev preview only): reduced motion shows it static. Do not edit LaunchSplash (mounted in the root layout).

### PUB-02: Staff sign-in (desktop and phone)

- **Surface:** public. **Wave:** 1. **Size:** S. **Model:** haiku (Re-skin of a page with one button; host-profile name as hero.).
- **Routes:** `/sign-in`
- **Depends on:** FOUNDATION, PUB-00
- **Brief:** `docs/design/redesign/admin-operator-public.md > Public > /sign-in (boards P2, Ph1)`
- **Boards:** `boards/admin/P2.dc.html`, `boards/admin/Ph1.dc.html`
- **Modify:** `components/tenant/TenantHeader.tsx`, `components/tenant/TenantHeader.module.css`, `app/sign-in/page.tsx`, `app/sign-in/page.module.css`
- **Tests to update:** `components/tenant/TenantHeader.test.tsx`, `app/sign-in/page.test.tsx`
- **Gaps:** none
- **Notes:** States: normal; no access banner; could not sign you in banner; clinical note. Data: currentProfile().

### PUB-03: Forbidden and offline

- **Surface:** public. **Wave:** 1. **Size:** S. **Model:** haiku (Two calm static cards.).
- **Routes:** `/forbidden`, `/offline`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/admin-operator-public.md > Public > /forbidden and /offline (board P3)`
- **Boards:** `boards/admin/P3.dc.html`
- **Modify:** `app/forbidden/page.tsx`, `app/offline/page.tsx`, `app/offline/Offline.module.css`
- **Tests to update:** `app/forbidden/page.test.tsx`, `app/offline/page.test.tsx`
- **Gaps:** none
- **Notes:** Forbidden never says what the page is. Offline says nothing shown is current and gives the phone process (keep the coordination number: DEC-660 item 3), with Try again.

### PUB-04: Learn: library, lesson and practice

- **Surface:** public. **Wave:** 1. **Size:** L. **Model:** sonnet (Master-detail with role tabs and progress; practice is "nothing is sent". Local progress storage is a known failing area on this machine.).
- **Routes:** `/learn`, `/learn/[lessonId]`, `/learn/[lessonId]/practice`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/admin-operator-public.md > Public > /learn, /learn/[lessonId], /practice (boards P5, Ph3)`
- **Boards:** `boards/admin/P5.dc.html`, `boards/admin/Ph3.dc.html`
- **Modify:** `components/learn/HelpPanel.tsx`, `components/learn/LearnLibrary.tsx`, `components/learn/LessonView.tsx`, `components/learn/PracticeView.tsx`, `app/learn/page.tsx`, `app/learn/[lessonId]/page.tsx`, `app/learn/[lessonId]/practice/page.tsx`, `app/learn/layout.tsx`, `components/learn/Learn.module.css`
- **Tests to update:** `components/learn/HelpPanel.test.tsx`, `components/learn/LearnLibrary.test.tsx`, `components/learn/LessonView.test.tsx`, `components/learn/PracticeView.test.tsx`
- **Read only (shared):** `components/console/Console.module.css`
- **Gaps:** none
- **Notes:** Client content and progress only (lib/learn/*, no back end). lib/learn/progress.test.ts and components/learn tests that use local storage fail on this machine without the flag: ignore ONLY if they fail the same way. HelpPanel is also imported by help/page.tsx (PUB-05 runs after you): keep its exports. learn/layout.tsx currently wraps in StaffShell. Pages import console/Console.module.css (frozen): use your own css.

### PUB-06: Product tour

- **Surface:** public. **Wave:** 1. **Size:** S. **Model:** haiku (Six static steps with URL state.).
- **Routes:** `/tour`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/admin-operator-public.md > Public > /tour (boards P6, Ph4)`
- **Boards:** `boards/admin/P6.dc.html`, `boards/admin/Ph4.dc.html`
- **Modify:** `components/tour/Tour.tsx`, `components/tour/Tour.module.css`, `app/tour/page.tsx`
- **Tests to update:** `components/tour/Tour.test.tsx`
- **Gaps:** none
- **Notes:** Six steps each ?step=; progress segments; role step is a radio group of cards; Back, Next, Skip. Content in lib/tour/content.ts; step remembered through tenantStore. The brief names a new StepCards block but reporter/parts/StepCards exists for another purpose: build tour cards inside components/tour.

### PUB-07: Value case

- **Surface:** public. **Wave:** 1. **Size:** S. **Model:** haiku (One static page.).
- **Routes:** `/value`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/admin-operator-public.md > Public > /value (board P7)`
- **Boards:** `boards/admin/P7.dc.html`
- **Modify:** `components/value/ValueCase.tsx`, `app/value/page.tsx`, `components/value/Value.module.css`
- **Tests to update:** `components/value/ValueCase.test.tsx`
- **Gaps:** none
- **Notes:** Four promises, measures table (Target stays "[to agree]"), savings rule, launch kit. Print stylesheet is a separate task.

### REG-01: Register frame: stage grid, checklist, help column, start and submitted

- **Surface:** onboarding. **Wave:** 1. **Size:** L. **Model:** sonnet (The register morph (six stages, checklist is progress and navigation) that four units build on.).
- **Routes:** `/register/[id]/start`, `/register/[id]/submitted`
- **Depends on:** FOUNDATION, ONB-00
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 3: register a service" (desktop layout states, save and return, phone)`
- **Boards:** `boards/onboarding/Reg.dc.html`, `boards/onboarding/RP2.dc.html`
- **Modify:** `app/register/[id]/start/page.tsx`, `app/register/[id]/submitted/page.tsx`, `app/register/layout.tsx`
- **Add:**
  - frontend/components/register/RegisterStage.tsx (StageGrid list | stage | side wrapper + phone ProviderShell) (+ .module.css, .test.tsx)
  - frontend/components/register/RegistrationChecklist.tsx (nav, aria-current="step", StatusTag words) (+ .module.css, .test.tsx)
  - frontend/components/register/StepHelp.tsx (short "Why we ask" per step; disclosure on phone) (+ .module.css, .test.tsx)
- **Tests to update:** `app/register/[id]/start/page.test.tsx`, `app/register/[id]/submitted/page.test.tsx`
- **Read only (shared):** `components/register/register.module.css`
- **Gaps:** "We aim to review within a working day" must come from configuration, not hard-coded (gap 4). Applicant-side ODS lookup does not exist (gap 3): plain input and "checked by your shift lead".
- **Notes:** register/layout.tsx currently wraps in StaffShell: replace. "Save and come back later" is in the top bar at every step and keeps the ?saved=1 landing. register.module.css is frozen (imported by every register page): use your own css and stop importing it in your two pages. Other register units (REG-02..REG-06) put their form inside RegisterStage.

### REG-05: Register: sign in with the invitation and My services

- **Surface:** onboarding. **Wave:** 1. **Size:** M. **Model:** sonnet (Invitation and code sign-in (identity/invitation, identity/code, identity/code/verify).).
- **Routes:** `/register`, `/register/services`
- **Depends on:** FOUNDATION, ONB-00
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 3" (sign in, My services; invitation only rule)`
- **Boards:** `boards/onboarding/RP1.dc.html`, `boards/onboarding/RegStatus.dc.html`
- **Modify:** `components/register/SignInForm.tsx`, `components/register/MyServices.tsx`, `app/register/page.tsx`, `app/register/services/page.tsx`
- **Tests to update:** `components/register/SignInForm.test.tsx`, `components/register/MyServices.test.tsx`, `app/register/page.test.tsx`, `app/register/services/page.test.tsx`
- **Read only (shared):** `components/register/register.module.css`
- **Gaps:** none
- **Notes:** There is no "Register another service" button; copy: "A new service comes by invitation from your shift lead". This register MyServices is a different component from reporter/multi/MyServices. register.module.css is frozen: use your own css.

### REG-06: Register: status after submitting (all six states)

- **Surface:** onboarding. **Wave:** 1. **Size:** M. **Model:** haiku (Static status cards with StatusTag shapes; existing data unchanged.).
- **Routes:** `/register/[id]/status`
- **Depends on:** FOUNDATION, ONB-00
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 3" (status screens as cards)`
- **Boards:** `boards/onboarding/RegStatus.dc.html`
- **Modify:** `components/register/StatusPage.tsx`, `components/register/StatusTracker.tsx`, `components/register/status/InReview.tsx`, `components/register/status/NeedsChanges.tsx`, `components/register/status/Approved.tsx`, `components/register/status/Live.tsx`, `components/register/status/NotApproved.tsx`, `components/register/status/Reverify.tsx`, `app/register/[id]/status/page.tsx`
- **Tests to update:** `components/register/StatusPage.test.tsx`, `app/register/[id]/status/page.test.tsx`
- **Read only (shared):** `components/register/register.module.css`
- **Gaps:** none
- **Notes:** Words: In review, Needs changes, Approved, Live, Not approved, Re-verify. Never colour alone. register.module.css is frozen: use your own css.

### REP-01: Capacity link loop and thank-you

- **Surface:** reporter. **Wave:** 1. **Size:** L. **Model:** sonnet (Link tokens, one-read-per-view CSRF rule, idempotency key, out-of-range confirm, bad-signal behaviour and live regions.).
- **Routes:** `/l/[token]`, `/l/thanks`
- **Depends on:** FOUNDATION, REP-00a, REP-00b
- **Brief:** `docs/design/redesign/reporter-app.md > "Per route" > Capacity links (/l/[token], /l/thanks) and "Bad signal and offline"`
- **Boards:** `boards/reporter/B1.dc.html`, `boards/reporter/B2.dc.html`, `boards/reporter/B3.dc.html`, `boards/reporter/D1.dc.html`, `boards/reporter/St.dc.html`
- **Modify:** `components/reporter/LinkLoader.tsx`, `components/reporter/CapacityResponder.tsx`, `components/reporter/CapacityResponseForm.tsx`, `components/reporter/LinkExpired.tsx`, `components/reporter/LinkUnavailable.tsx`, `components/reporter/closed.tsx`, `app/l/[token]/page.tsx`, `app/l/thanks/page.tsx`
- **Tests to update:** `components/reporter/LinkLoader.test.tsx`, `components/reporter/CapacityResponder.test.tsx`, `components/reporter/LinkExpired.test.tsx`, `app/l/[token]/page.test.tsx`, `app/l/thanks/page.test.tsx`, `components/reporter/resultMarks.test.tsx`
- **Gaps:** LinkView has no capacity text line field: "Send it by text instead" cannot be built (brief gap 1); ship the rest. Check a confirmed out-of-range report reaches the lead's Reports to check before the page says the lead will be told (gap 2). Closed-to-referrals confirm is UI only (gap 3).
- **Notes:** Keep the one-read-per-view rule (CSRF cookie set by the browser read), the same idempotency key on Try again, and number only in component memory (the address holds a bearer token: never store it). /offline cannot name the coordination number: keep the number on every offline surface. CapacityResponseForm is also used by app/RespondScreen and multi/GroupedUpdate (REP-05, REP-06 depend on this unit): keep its exports. closed.tsx and LinkUnavailable are also imported by the booking units (REP-02, REP-03). resultMarks.test.tsx covers BookingChange, BookingDecision and LinkExpired: you own it first; REP-02 and REP-03 edit it afterwards (depends_on order).

### REP-07: My services, service added, hand over cover

- **Surface:** reporter. **Wave:** 1. **Size:** M. **Model:** haiku (Cards and simple forms over existing data; cover uses existing CoverUntil.).
- **Routes:** `/app/services`, `/app/services/[id]/added`, `/app/services/[id]/cover`
- **Depends on:** FOUNDATION, REP-00a, REP-00b
- **Brief:** `docs/design/redesign/reporter-app.md > "Per route" > App > /app/services, /added, /cover (B7)`
- **Boards:** `boards/reporter/B7.dc.html`, `boards/reporter/St.dc.html`
- **Modify:** `components/reporter/multi/MyServices.tsx`, `components/reporter/multi/AddedService.tsx`, `components/reporter/multi/ServiceCover.tsx`, `app/(reporter)/app/services/page.tsx`, `app/(reporter)/app/services/[id]/added/page.tsx`, `app/(reporter)/app/services/[id]/cover/page.tsx`, `components/reporter/multi/serviceState.ts`
- **Tests to update:** `components/reporter/multi/MyServices.test.tsx`, `components/reporter/multi/ServiceCover.test.tsx`
- **Gaps:** none
- **Notes:** Cards: Confirmed (tick), Due now (own Update primary), Paused (dashed). Empty state "You have no services yet". Cover: mobile number then Until (Tonight, This week, A date). serviceState.ts is also imported by GroupedUpdate (REP-06 runs after): keep its exports.

### REP-08: Settings and sign out of every phone

- **Surface:** reporter. **Wave:** 1. **Size:** M. **Model:** sonnet (Touches the channel, cover number and sign-out-everywhere session calls.).
- **Routes:** `/app/settings`, `/app/sign-out-all`
- **Depends on:** FOUNDATION, REP-00a, REP-00b
- **Brief:** `docs/design/redesign/reporter-app.md > "Per route" > App > /app/settings (B8) and /app/sign-out-all (B9)`
- **Boards:** `boards/reporter/B8.dc.html`, `boards/reporter/B9.dc.html`
- **Modify:** `components/reporter/app/SettingsScreen.tsx`, `components/reporter/app/SignOutAll.tsx`, `app/(reporter)/app/settings/page.tsx`, `app/(reporter)/app/sign-out-all/page.tsx`
- **Tests to update:** `components/reporter/app/SettingsScreen.test.tsx`
- **Gaps:** none
- **Notes:** Add a visible "Sign out of every phone" link on settings. Sign-out-all confirm uses a dark (not red) primary. Keep GET reporter/settings, PUT .../channel, PUT .../cover, identity/sign-out-everywhere.

### WAL-02: Wall pairing and reconnect

- **Surface:** advisor. **Wave:** 1. **Size:** M. **Model:** sonnet (Pairing code refresh/polling and reconnect timers; spinner stops under reduced motion.).
- **Routes:** `/screen/pair`, `/screen/reconnect`
- **Depends on:** FOUNDATION
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.3 Wall screen" > /screen/pair, /screen/reconnect`
- **Boards:** `boards/advisor/WallPair.dc.html`, `boards/advisor/WallReconnect.dc.html`
- **Modify:** `components/screens/PairingScreen.tsx`, `components/screens/PairingScreen.module.css`, `app/(wall)/screen/pair/page.tsx`, `app/(wall)/screen/reconnect/page.tsx`
- **Tests to update:** `components/screens/PairingScreen.test.tsx`, `app/(wall)/screen/pair/page.test.tsx`, `app/(wall)/screen/reconnect/page.test.tsx`
- **Gaps:** Pairing code refresh: the wall design says a new code appears after 10 minutes; confirm the screen polls and replaces an expired code (brief gap 9).
- **Notes:** Code at 210px, three steps at the right. Reconnect: amber banner with "Trying again in n seconds" over hatched Last known tiles. Keep /api/bff/screens/pairing.

### ADM-03: Settings version detail and approval

- **Surface:** admin. **Wave:** 2. **Size:** M. **Model:** sonnet (Two-person approval of settings: the author cannot approve, said in words for author and approver.).
- **Routes:** `/admin/config/[n]`
- **Depends on:** FOUNDATION, ADM-00a, ADM-02
- **Brief:** `docs/design/redesign/admin-operator-public.md > Administration > /admin/config/[n] (board A3)`
- **Boards:** `boards/admin/A3.dc.html`
- **Modify:** `components/admin/VersionDetail.tsx`, `components/admin/ConfigDiff.tsx`, `app/(tenant-admin)/admin/config/[n]/page.tsx`
- **Tests to update:** `components/admin/VersionDetail.test.tsx`, `components/admin/ConfigDiff.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`
- **Gaps:** There is no "Withdraw this draft" call: omit the button and say "Ask a platform operator to withdraw".
- **Notes:** States: draft, pending (n of m), current, superseded, loading, not found. POST .../approval. ApprovalMeter and DiffPair come from ADM-00a.

### ADM-04: Contacts

- **Surface:** admin. **Wave:** 2. **Size:** S. **Model:** haiku (Rows that open one at a time over an existing PUT.).
- **Routes:** `/admin/contacts`
- **Depends on:** FOUNDATION, ADM-00b, ADM-01
- **Brief:** `docs/design/redesign/admin-operator-public.md > Administration > /admin/contacts (board A4)`
- **Boards:** `boards/admin/A4.dc.html`
- **Modify:** `components/admin/ContactsForm.tsx`, `app/(tenant-admin)/admin/contacts/page.tsx`
- **Tests to update:** `components/admin/ContactsForm.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`, `components/admin/Disclose.tsx`
- **Gaps:** none
- **Notes:** Phone-only kinds show the hint and refuse an email address; email kinds the reverse (keep the existing validation messages). Needed to go live: coordination phone, clinical safety officer. Uses admin/Disclose (frozen).

### ADM-05: Data retention

- **Surface:** admin. **Wave:** 2. **Size:** S. **Model:** haiku (Answer card, chips and a table with one editable row at a time.).
- **Routes:** `/admin/retention`
- **Depends on:** FOUNDATION, ADM-00b, ADM-01
- **Brief:** `docs/design/redesign/admin-operator-public.md > Administration > /admin/retention (board A5)`
- **Boards:** `boards/admin/A5.dc.html`
- **Modify:** `components/admin/RetentionForm.tsx`, `app/(tenant-admin)/admin/retention/page.tsx`
- **Tests to update:** `components/admin/RetentionForm.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`, `components/admin/Disclose.tsx`, `components/lead/ErrorSummary.tsx`
- **Gaps:** none
- **Notes:** The copy of platform defaults in RetentionForm must follow the back end list (DEC-271): add a test comparing them. Table is a real table in a scroll box.

### ADM-06: Email and text senders

- **Surface:** admin. **Wave:** 2. **Size:** S. **Model:** haiku (Two cards over existing channel calls.).
- **Routes:** `/admin/email`
- **Depends on:** FOUNDATION, ADM-01
- **Brief:** `docs/design/redesign/admin-operator-public.md > Administration > /admin/email (board A6 left half)`
- **Boards:** `boards/admin/A6.dc.html`
- **Modify:** `components/admin/EmailSender.tsx`, `app/(tenant-admin)/admin/email/page.tsx`
- **Tests to update:** `components/admin/EmailSender.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`
- **Gaps:** "Use Overwatch's sender" has no back end today: omit that option unless the owner decides to build it (brief open question 1).
- **Notes:** Text messages read only; Email with a two-way choice: own address (name, address, display name, checked) or not set up. GET/POST/PUT /tenant/channels.

### ADV-05: Request state: option detail, booking panel and option rail

- **Surface:** advisor. **Wave:** 2. **Size:** M. **Model:** sonnet (Booking creation, waiting and confirmed states over the events stream; double-booking guard.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, ADV-01, ADV-06
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.1 Advisor" > .../options?service= (Request)`
- **Boards:** `boards/advisor/Call.dc.html`, `boards/core-morph/S4.dc.html`, `boards/core-morph/P3.dc.html`, `boards/core-morph/P4.dc.html`
- **Modify:** `components/advisor/BookingPanel.tsx`, `components/advisor/OptionBooking.tsx`
- **Add:**
  - frontend/components/advisor/OptionRail.tsx (the other options, folded, inert when hidden) (+ .module.css, .test.tsx)
- **Tests to update:** `components/advisor/BookingPanel.test.tsx`
- **Gaps:** The request deep link ?service=[id] must resolve to a service in the case's options and be ignored otherwise: wiring is in ADV-08.
- **Notes:** POST /api/bff/bookings, events /api/bff/events, /api/bff/bookings/[id]. OptionBooking is imported by ServiceCard, OptionsMap and CompareScreen: keep exports. BookingCard is in ADV-06.

### CLN-02: Clinical case: review and give advice

- **Surface:** advisor. **Wave:** 2. **Size:** M. **Model:** sonnet (DEC-855/DEC-1179: advice only when the read loaded and the request is held by this clinician; advisor number asked only on Call.).
- **Routes:** `/clinical/requests/[id]`
- **Depends on:** FOUNDATION, CLN-01
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.2 Clinical advisor" (/clinical/requests/[id])`
- **Boards:** `boards/advisor/ClinCase.dc.html`, `boards/advisor/ClinSent.dc.html`
- **Modify:** `components/clinical/CaseView.tsx`, `components/clinical/AdviceForm.tsx`, `app/(clinical)/clinical/requests/[id]/page.tsx`
- **Tests to update:** `components/clinical/CaseView.test.tsx`
- **Read only (shared):** `components/exec/Exec.module.css`
- **Gaps:** The hold timer "8:42 left" must be removed if the request read carries no hold expiry (brief gap 6).
- **Notes:** CaseView.test.tsx is a known local-storage failure on this machine: do not touch that area. Three columns (slim queue, case, advice); after sending, one confirmation card. Phone alert is optional.

### CRI-02: Criteria owner: review and confirm panels

- **Surface:** lead. **Wave:** 2. **Size:** S. **Model:** haiku (Panels with existing rules in lib/criteria.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, CRI-01
- **Brief:** `docs/design/redesign/lead-and-setup.md > Criteria owner (states 1 Review, 2 Confirm)`
- **Boards:** `boards/lead/OwnerReview.dc.html`, `boards/lead/OwnerPhone.dc.html`
- **Modify:** `components/owner/CriteriaOverview.tsx`, `components/owner/OverdueNotice.tsx`, `components/owner/CriteriaConfirm.tsx`
- **Tests to update:** `components/owner/CriteriaOverview.test.tsx`, `components/owner/CriteriaConfirm.test.tsx`
- **Read only (shared):** `components/lead/lead-forms.module.css`
- **Gaps:** none
- **Notes:** Panels inside CriteriaFlow (CRI-01). Review again in 3, 6 or 12 months. OverdueNotice has no test: add one.

### CRI-03: Criteria owner: change and preview panels

- **Surface:** lead. **Wave:** 2. **Size:** M. **Model:** sonnet (Changed fields are marked "Changed" with what they were: diff against the saved version.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, CRI-01
- **Brief:** `docs/design/redesign/lead-and-setup.md > Criteria owner (states 3 Change, 4 Preview)`
- **Boards:** `boards/lead/OwnerReview.dc.html`
- **Modify:** `components/owner/CriteriaEditor.tsx`, `components/owner/CriteriaPreview.tsx`
- **Tests to update:** `components/owner/CriteriaEditor.test.tsx`, `components/owner/CriteriaPreview.test.tsx`
- **Read only (shared):** `components/lead/lead-forms.module.css`
- **Gaps:** none
- **Notes:** "Changed" is a word, not colour. Uses ui/NumberStepper (do not edit). Preview shows what advisors will see and what changed.

### CRI-04: Criteria owner: send for second approval and waiting

- **Surface:** lead. **Wave:** 2. **Size:** S. **Model:** haiku (Existing submit call and wording; two-person rule said in words.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, CRI-01
- **Brief:** `docs/design/redesign/lead-and-setup.md > Criteria owner (states 5 Send, 6 Waiting)`
- **Boards:** `boards/lead/OwnerReview.dc.html`
- **Modify:** `components/owner/CriteriaSend.tsx`, `components/owner/CriteriaStatus.tsx`
- **Tests to update:** `components/owner/CriteriaSend.test.tsx`
- **Read only (shared):** `components/lead/lead-forms.module.css`
- **Gaps:** none
- **Notes:** Say in words that the author cannot approve. Version 2 stays live while waiting. CriteriaStatus has no test: add one.

### INV-01: Invite and track: reporter list and detail stage

- **Surface:** onboarding. **Wave:** 2. **Size:** L. **Model:** sonnet (Master-detail morph with URL state; resend and switch-to-text actions.).
- **Routes:** `/lead/reporters`
- **Depends on:** FOUNDATION, LDR-02
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 1: shift lead, invite and track" (states, components, gaps, phone)`
- **Boards:** `boards/onboarding/LI2.dc.html`, `boards/onboarding/States.dc.html`
- **Modify:** `components/lead/SetupTracker.tsx`, `app/(lead)/lead/reporters/page.tsx`
- **Add:**
  - frontend/components/lead/ReporterList.tsx (ul of buttons, aria-current, StatusTag, 7-segment bar, filter chips All/Stuck/In progress/Complete) (+ .module.css, .test.tsx)
  - frontend/components/lead/ReporterDetail.tsx (timeline left, actions right; phone full-screen step) (+ .module.css, .test.tsx)
  - frontend/components/lead/ReporterStage.tsx (StageGrid; takes the state browse|compose|detail|number) (+ .module.css, .test.tsx)
- **Tests to update:** `components/lead/SetupTracker.test.tsx`
- **Read only (shared):** `components/lead/Lead.module.css`
- **Gaps:** Per-step times and the chosen channel and the masked number are not in the tracker row: show the time for "Invited" and the last-seen line only.
- **Notes:** Detail state is /lead/reporters?invitation=<id>. SetupTracker keeps its data parsing, stuckAt and SETUP_STEPS exports (used elsewhere). ReporterStage is also used by the invite and number pages (INV-02, INV-03 run after you). LeadPhonedDialog (owned by LDR-02) is imported by SetupTracker: keep that import working. Lead.module.css is frozen: use your own css.

### LDR-01: Shift lead overview: counters, chase cards, covering, system now

- **Surface:** lead. **Wave:** 2. **Size:** L. **Model:** sonnet (Live overview with events refresh, failed-read behaviour (H-330) and the chase morph.).
- **Routes:** `/lead`
- **Depends on:** FOUNDATION, LDR-02, NET-00
- **Brief:** `docs/design/redesign/lead-and-setup.md > "3. Routes" > "/lead"`
- **Boards:** `boards/lead/Overview.dc.html`, `boards/lead/OverviewChase.dc.html`, `boards/lead/OverviewQuiet.dc.html`, `boards/lead/OverviewLoading.dc.html`, `boards/lead/PhoneOverview.dc.html`
- **Modify:** `components/lead/LeadOverview.tsx`, `components/lead/OldFigureCard.tsx`, `components/lead/CoveringList.tsx`, `components/lead/SystemCounts.tsx`, `app/(lead)/lead/page.tsx`
- **Add:**
  - frontend/components/lead/AttentionStat.tsx (+ .module.css, .test.tsx)
  - frontend/components/lead/DisclosureRow.tsx (+ .module.css, .test.tsx)
- **Tests to update:** `components/lead/LeadOverview.test.tsx`, `components/lead/OldFigureCard.test.tsx`, `components/lead/CoveringList.test.tsx`, `components/lead/SystemCounts.test.tsx`
- **Read only (shared):** `components/lead/Lead.module.css`
- **Gaps:** (a) lead-level "criteria reviews due soon" and (b) "declined despite showing capacity" are not in the overview data; (c) "Send review reminder to owners" has no route. Show those rows only when data is present.
- **Notes:** An empty list is never shown for a failed read: keep the last good page dimmed with actions disabled. Counters never animate. Announce politely only new chases. ChaseCard and LeadPhonedDialog are in LDR-02 (merged first): import them, do not edit. Lead.module.css is frozen: use your own css.

### LDR-04: Add a service: steps 3 and 4, check and added

- **Surface:** lead. **Wave:** 2. **Size:** M. **Model:** sonnet (Final submit and the warning that advisors will see the criteria at once.).
- **Routes:** `/lead/services/new`
- **Depends on:** FOUNDATION, LDR-03
- **Brief:** `docs/design/redesign/lead-and-setup.md > "/lead/services/new" (steps Who it takes, Check, Added)`
- **Boards:** `boards/lead/AddService.dc.html`
- **Modify:** `components/lead/AddServiceForm.tsx`, `app/(lead)/lead/services/new/page.tsx`
- **Add:**
  - frontend/components/lead/addservice/StepCriteria.tsx (+ .module.css, .test.tsx)
  - frontend/components/lead/addservice/StepCheck.tsx (three summary cards with Change) (+ .module.css, .test.tsx)
  - frontend/components/lead/addservice/ServiceAdded.tsx (+ .module.css, .test.tsx)
- **Tests to update:** `components/lead/AddServiceForm.test.tsx`
- **Read only (shared):** `components/lead/Lead.module.css`
- **Gaps:** Criteria owner (see LDR-03).
- **Notes:** Runs after LDR-03 (same files). Success state moves focus to its heading and offers the existing /lead/reporters/invite?service=... link.

### LDR-07: Suspend and resume a service

- **Surface:** lead. **Wave:** 2. **Size:** M. **Model:** sonnet (Safety-relevant state changes (suspend, resume with two checks) in a four-state morph.).
- **Routes:** `/lead/services/[id]/suspend`
- **Depends on:** FOUNDATION, LED-00a, LDR-02
- **Brief:** `docs/design/redesign/lead-and-setup.md > "/lead/services/[id]/suspend"`
- **Boards:** `boards/lead/Suspend.dc.html`
- **Modify:** `components/lead/SuspendService.tsx`, `app/(lead)/lead/services/[id]/suspend/page.tsx`
- **Tests to update:** `components/lead/SuspendService.test.tsx`
- **Read only (shared):** `components/lead/Lead.module.css`
- **Gaps:** none
- **Notes:** Four states: Suspend, Suspended, Resume (two checks both needed), Resumed. Pinned card with a state chip that changes shape and word. Confirm button is not the default focus; resumed state announces "<service> is back". Danger-toned button names the service. Imports LeadPhonedDialog (LDR-02): do not edit.

### LDR-09: Reports to check

- **Surface:** lead. **Wave:** 2. **Size:** M. **Model:** sonnet (Tab pattern with list/detail, accept-the-figure and suspend actions.).
- **Routes:** `/lead/flags`
- **Depends on:** FOUNDATION, LED-00b, LDR-02
- **Brief:** `docs/design/redesign/lead-and-setup.md > "/lead/flags"`
- **Boards:** `boards/lead/Flags.dc.html`, `boards/lead/PhoneFlags.dc.html`
- **Modify:** `components/lead/ReportFlags.tsx`, `app/(lead)/lead/flags/page.tsx`
- **Add:**
  - frontend/components/lead/FlagList.tsx (+ .module.css, .test.tsx)
  - frontend/components/lead/FigureStrip.tsx (last five figures; render only when data exists) (+ .module.css, .test.tsx)
- **Tests to update:** `components/lead/ReportFlags.test.tsx`
- **Read only (shared):** `components/lead/Lead.module.css`
- **Gaps:** The "last reports" strip and usual range are not in the flag resource: leave the strip out unless the back end adds a lead read of a service's last five figures.
- **Notes:** Tabs To check (n) and Checked follow the tab pattern; footnote "flagged by rules, never used to assess advisors" stays visible. Phone: list first, a tap opens the flag full screen with "Phone to confirm" fixed at the bottom. Imports LeadPhonedDialog (LDR-02).

### LRV-02: Review: call-back check and scope check

- **Surface:** onboarding. **Wave:** 2. **Size:** M. **Model:** sonnet (Check results posted to the review back end; tel: primary on phone.).
- **Routes:** `/lead/registrations/[id]?step=callback`, `/lead/registrations/[id]?step=scope`
- **Depends on:** FOUNDATION, LRV-01
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 4" (Call back, Scope stages; phone: Phone is a tel: primary)`
- **Boards:** `boards/onboarding/Rev1.dc.html`, `boards/onboarding/RvP2.dc.html`
- **Modify:** `components/lead/registration/CallBackCheck.tsx`, `components/lead/registration/ScopeCheck.tsx`
- **Tests to update:** `components/lead/registration/CallBackCheck.test.tsx`, `components/lead/registration/ScopeCheck.test.tsx`
- **Read only (shared):** `components/lead/lead-forms.module.css`
- **Gaps:** none
- **Notes:** Each check is a heading level 2 with "Check n of 4" above. POST .../callback and .../scope.

### LRV-03: Review: decide and go live

- **Surface:** onboarding. **Wave:** 2. **Size:** M. **Model:** sonnet (Approval decision and Set live (patient-facing clinical safety gate; test answered).).
- **Routes:** `/lead/registrations/[id]?step=decide`, `/lead/registrations/[id]?step=go-live`
- **Depends on:** FOUNDATION, LRV-01
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 4" (Decide, Go live stages)`
- **Boards:** `boards/onboarding/Rev1.dc.html`, `boards/onboarding/RvP2.dc.html`
- **Modify:** `components/lead/registration/DecideStep.tsx`, `components/lead/registration/GoLive.tsx`
- **Tests to update:** `components/lead/registration/DecideStep.test.tsx`, `components/lead/registration/GoLive.test.tsx`
- **Read only (shared):** `components/lead/lead-forms.module.css`
- **Gaps:** "Approved today 15:00" and test times only if returned.
- **Notes:** "Approve" is a real disabled button that says what it waits for. The missing-before-approve list is read from the back end, never worked out in the page. GET|POST .../decision, POST .../go-live, GET .../test.

### NAD-02: Network administration: grants and decisions history

- **Surface:** network. **Wave:** 2. **Size:** M. **Model:** haiku (Tables with approve and decline in place over existing endpoints.).
- **Routes:** `/network-admin/grants`, `/network-admin/history`
- **Depends on:** FOUNDATION, PLN-00b, NAD-01
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Network administration > /grants, /history`
- **Boards:** `boards/planning/NGrants.dc.html`, `boards/planning/NAdminHistory.dc.html`
- **Modify:** `components/networkAdmin/NetworkGrants.tsx`, `components/networkAdmin/NetworkAdminHistory.tsx`, `app/(network-admin)/network-admin/grants/page.tsx`, `app/(network-admin)/network-admin/history/page.tsx`
- **Tests to update:** `components/networkAdmin/NetworkGrants.test.tsx`, `components/networkAdmin/NetworkAdminHistory.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`
- **Gaps:** Confirm the history read carries the role and date for each decision.
- **Notes:** History names roles, never people. "What each scope shares" and "never shared" stay as drawn.

### NAD-03: Network administration: listings

- **Surface:** network. **Wave:** 2. **Size:** S. **Model:** haiku (Table whose buttons depend on state; reason chips in place.).
- **Routes:** `/network-admin/listings`
- **Depends on:** FOUNDATION, PLN-00b, NAD-01
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Network administration > /listings`
- **Boards:** `boards/planning/NListings.dc.html`
- **Modify:** `components/networkAdmin/NetworkListings.tsx`, `app/(network-admin)/network-admin/listings/page.tsx`
- **Tests to update:** `components/networkAdmin/NetworkListings.test.tsx`
- **Read only (shared):** `components/admin/admin.module.css`
- **Gaps:** none
- **Notes:** Buttons that apply to each state: admit, decline, suspend, reinstate.

### NET-01: Network home

- **Surface:** network. **Wave:** 2. **Size:** S. **Model:** haiku (Counts and chips over the existing network board read.).
- **Routes:** `/network/home`
- **Depends on:** FOUNDATION, NET-00, PLN-00b, ADV-02
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Network > /network/home`
- **Boards:** `boards/planning/NHome.dc.html`, `boards/planning/PH4.dc.html`
- **Modify:** `components/network/NetworkHomeView.tsx`, `app/(network)/network/home/page.tsx`
- **Tests to update:** `components/network/NetworkHomeView.test.tsx`
- **Read only (shared):** `components/network/Network.module.css`, `components/advisor/BoardCounts.module.css`
- **Gaps:** none
- **Notes:** NetworkHomeView imports advisor/BoardCounts.module.css and Network.module.css: both frozen/shared; copy what you need into your own css.

### NET-02: Network capacity board

- **Surface:** network. **Wave:** 2. **Size:** M. **Model:** sonnet (Organisation chips filter in place; tiles or list; paused and not-updated dashed; read-only scope rules.).
- **Routes:** `/network/board`
- **Depends on:** FOUNDATION, NET-00, PLN-00b, ADV-00, BRD-01
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Network > /network/board`
- **Boards:** `boards/planning/NBoard.dc.html`, `boards/planning/NStates.dc.html`
- **Modify:** `components/network/NetworkBoardView.tsx`, `components/board/NetworkBoard.tsx`, `components/board/NetworkTile.tsx`, `app/(network)/network/board/page.tsx`
- **Tests to update:** `components/network/NetworkBoardView.test.tsx`, `components/board/NetworkBoard.test.tsx`
- **Read only (shared):** `components/network/Network.module.css`, `components/board/Tile.module.css`, `components/board/Board.module.css`
- **Gaps:** "Used 2 of 6" is in the spec but not in the parsed network entry types (brief 4 item 3): remove the line.
- **Notes:** Imports Tile.module.css (ADV-00) and Board.module.css (BRD-01): do not edit. Network scope: no tenant or network identifier from the browser. Tests: NetworkBoardView.test, NetworkBoard.test (NetworkTile has none: Tile.network.test belongs to ADV-00).

### NET-06: Network week summary

- **Surface:** network. **Wave:** 2. **Size:** M. **Model:** sonnet (Charts: stacked share bar, pressure over time 7x24 grid with patterns and a table; withheld week card.).
- **Routes:** `/network/week`
- **Depends on:** FOUNDATION, NET-00, PLN-00a, PLN-04
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Network > /network/week`
- **Boards:** `boards/planning/NWeek.dc.html`
- **Modify:** `components/network/NetworkWeekView.tsx`, `components/exec/NetworkWeek.tsx`, `app/(network)/network/week/page.tsx`
- **Tests to update:** `components/network/NetworkWeekView.test.tsx`, `components/exec/NetworkWeek.test.tsx`
- **Read only (shared):** `components/network/Network.module.css`
- **Gaps:** none
- **Notes:** Each measure carries hidden; a withheld week is its own card. exec/NetworkWeek imports exec/WeekSummary (PLN-04) and network css: do not edit them.

### OPR-05: Go-live funnel: the stage shell and the left part list

- **Surface:** admin. **Wave:** 2. **Size:** L. **Model:** sonnet (The signature morph: parts fold, next part outlined, later parts dashed, layers inert, focus to the open part heading.).
- **Routes:** `/operator/tenants/[id]`
- **Depends on:** FOUNDATION, OPR-04, ADM-00b
- **Brief:** `docs/design/redesign/admin-operator-public.md > Operator console > /operator/tenants/[id] (StageGrid, five parts, states)`
- **Boards:** `boards/admin/O4.dc.html`
- **Modify:** `components/operator/TenantDetail.tsx`, `components/operator/TenantPhases.tsx`, `app/(operator)/operator/(area)/tenants/[id]/page.tsx`
- **Tests to update:** `components/operator/TenantDetail.test.tsx`
- **Read only (shared):** `components/operator/Tenant.module.css`
- **Gaps:** none
- **Notes:** Left parts are buttons (aria-current="step") with StatusTag shape and word; right layers inert and aria-hidden when not current. Step logic stays in lib/operator/funnel.ts. The step panels are the files from OPR-04 (owned by OPR-06..OPR-09): do not edit them. The prototype's "their administrators finish" button is design only. Tenant.module.css is frozen: use your own css.

### OPR-06: Go-live funnel: organisation, sign-in and administrator approval panels

- **Surface:** admin. **Wave:** 2. **Size:** M. **Model:** sonnet (Platform actions: sign-in connection, admin-consent invitation (identity).).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, OPR-04
- **Brief:** `docs/design/redesign/admin-operator-public.md > Operator console > funnel parts 1 and 2`
- **Boards:** `boards/admin/O4.dc.html`
- **Modify:** `components/operator/funnel/OrganisationStep.tsx`, `components/operator/funnel/SignInStep.tsx`, `components/operator/funnel/InviteStep.tsx`
- **Tests to update:** `components/operator/funnel/OrganisationStep.test.tsx`, `components/operator/funnel/SignInStep.test.tsx`, `components/operator/funnel/InviteStep.test.tsx`
- **Gaps:** none
- **Notes:** Files created by OPR-04 (check they exist; if a test file name differs use the one OPR-04 created). States per part: not started, in progress, waiting for them (amber, invitation sent), done. Error on an action: the part stays open with the problem in words. admin-consent, admin-consent-invitation, directory/verification are the endpoints.

### OPR-07: Go-live funnel: teams and roles panels

- **Surface:** admin. **Wave:** 2. **Size:** M. **Model:** sonnet (Entra group and member management writes.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, OPR-04
- **Brief:** `docs/design/redesign/admin-operator-public.md > Operator console > funnel part 3 (Teams and people)`
- **Boards:** `boards/admin/O4.dc.html`
- **Modify:** `components/operator/funnel/TeamStep.tsx`, `components/operator/funnel/RolesStep.tsx`
- **Tests to update:** `components/operator/funnel/TeamStep.test.tsx`, `components/operator/funnel/RolesStep.test.tsx`
- **Gaps:** none
- **Notes:** Part 3 is optional and skipped by default (teams are made after consent). Endpoints: entra-groups and members.

### OPR-08: Go-live funnel: reach and agreements panels

- **Surface:** admin. **Wave:** 2. **Size:** M. **Model:** sonnet (Phone numbers (shared, retire, test text) and references: patient-contact infrastructure.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, OPR-04
- **Brief:** `docs/design/redesign/admin-operator-public.md > Operator console > funnel part 4 (Reach and agreements)`
- **Boards:** `boards/admin/O4.dc.html`
- **Modify:** `components/operator/funnel/ReachStep.tsx`, `components/operator/funnel/AgreementsStep.tsx`
- **Tests to update:** `components/operator/funnel/ReachStep.test.tsx`, `components/operator/funnel/AgreementsStep.test.tsx`
- **Gaps:** none
- **Notes:** Endpoints: host, numbers (+/shared, /retire, /test-text), references. The test-text and stop-using forms are inside ReachStep.

### OPR-09: Go-live funnel: go live and look after it

- **Surface:** admin. **Wave:** 2. **Size:** M. **Model:** sonnet (Activation, suspension and offboarding of an organisation.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, OPR-04
- **Brief:** `docs/design/redesign/admin-operator-public.md > Operator console > funnel part 5 (Go live) and "Look after it" menu`
- **Boards:** `boards/admin/O4.dc.html`
- **Modify:** `components/operator/funnel/GoLiveStep.tsx`, `components/operator/funnel/LifecyclePanel.tsx`
- **Tests to update:** `components/operator/funnel/GoLiveStep.test.tsx`, `components/operator/funnel/LifecyclePanel.test.tsx`
- **Gaps:** The "Look after it" menu (suspend, offboard) is described but not drawn (brief open question 6): keep the current lifecycle controls and restyle.
- **Notes:** Go live shows what the organisation's own administrators still have to do (approve settings, contacts, retention, names) as tasks and enables Go live only when nothing is left and the four parts before are done. Endpoints: activation, suspension, offboarding.

### PLN-02: All services and a service opened in place

- **Surface:** planning. **Wave:** 2. **Size:** M. **Model:** sonnet (Master-detail in the planning stage; filter chips and find box over the board.).
- **Routes:** `/planning/services`, `/planning/services/[id]`
- **Depends on:** FOUNDATION, PLN-01, PLN-00b
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Planning > /planning/services and /planning/services/[id]`
- **Boards:** `boards/planning/PServices.dc.html`, `boards/planning/PService.dc.html`, `boards/planning/Morph.dc.html`
- **Modify:** `components/exec/ServiceList.tsx`, `components/exec/ServiceDetail.tsx`, `app/(exec)/planning/services/page.tsx`, `app/(exec)/planning/services/[id]/page.tsx`
- **Tests to update:** `components/exec/ServiceList.test.tsx`, `components/exec/ServiceDetail.test.tsx`
- **Read only (shared):** `components/exec/Exec.module.css`
- **Gaps:** The "Today" strip needs status intervals of the day: either extend exec/services/[id] with { from, to, status } or draw only the "since 13:10" marker (brief section 4 item 1). Draw the marker only.
- **Notes:** ServiceDetail is composed by the alert unit (PLN-03): keep its exports. The tiles fold to a strip, the list becomes a rail.

### PRA-02: Practitioner visit offer and visit

- **Surface:** reporter. **Wave:** 2. **Size:** M. **Model:** sonnet (Live expiry countdown, accept/decline, status updates; address shown only after accept.).
- **Routes:** `/app/practitioner/offers/[id]`, `/app/practitioner/visits/[id]`
- **Depends on:** FOUNDATION, REP-00a, REP-00b, PRA-01
- **Brief:** `docs/design/redesign/reporter-app.md > "Per route" > Practitioner (/offers/[id], /visits/[id], B11)`
- **Boards:** `boards/reporter/B11.dc.html`, `boards/reporter/St.dc.html`
- **Modify:** `components/practitioner/VisitScreens.tsx`, `app/(reporter)/app/practitioner/offers/[id]/page.tsx`, `app/(reporter)/app/practitioner/visits/[id]/page.tsx`
- **Tests to update:** `components/practitioner/Practitioner.test.tsx`
- **Gaps:** none
- **Notes:** Countdown with tabular numerals (live figure: it counts, it does not animate for style). The "About how long?" chips (10 to 60) open only on "On my way". The phone position is never read or sent. Address only after accept.

### PUB-05: Help hub, problem, safety concern and share a support code

- **Surface:** public. **Wave:** 2. **Size:** L. **Model:** sonnet (Four routes in one hub layout; safety concern and problem reports; patient-details nudge must stay.).
- **Routes:** `/help`, `/help/problem`, `/help/safety`, `/help/share`
- **Depends on:** FOUNDATION, PUB-04
- **Brief:** `docs/design/redesign/admin-operator-public.md > Public > /help, /problem, /safety, /share (boards P4, Ph2)`
- **Boards:** `boards/admin/P4.dc.html`, `boards/admin/Ph2.dc.html`
- **Modify:** `components/help/ProblemForm.tsx`, `components/help/SafetyConcernForm.tsx`, `components/help/SupportCode.tsx`, `components/help/SupportCode.module.css`, `app/help/page.tsx`, `app/help/problem/page.tsx`, `app/help/safety/page.tsx`, `app/help/share/page.tsx`, `app/help/layout.tsx`, `components/help/Help.module.css`
- **Tests to update:** `components/help/ProblemForm.test.tsx`, `components/help/SafetyConcernForm.test.tsx`, `components/help/SupportCode.test.tsx`, `app/help/page.test.tsx`
- **Read only (shared):** `components/exec/Exec.module.css`
- **Gaps:** none
- **Notes:** Desktop: hub, open form and support code side by side; phone: the hub, then each form full screen. States: choose, sending, sent ("Thanks. We have your report."), could not send (words kept). Keep "No patient names or details" warnings and the patient-details nudge. SupportCode.test.tsx is a known local-storage failure on this machine. help/page.tsx imports exec/Exec.module.css (frozen) and Help.module.css is shared by the two forms (yours). Do not edit learn/HelpPanel (PUB-04).

### REG-02: Register: organisation and location steps

- **Surface:** onboarding. **Wave:** 2. **Size:** M. **Model:** sonnet (Address picker (postcode lookup, combobox-like keyboard), per-step saves and error summaries.).
- **Routes:** `/register/[id]/organisation`, `/register/[id]/location`
- **Depends on:** FOUNDATION, REG-01
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 3" (Organisation, Location steps; More about your organisation disclosure)`
- **Boards:** `boards/onboarding/Reg.dc.html`, `boards/onboarding/RP2.dc.html`
- **Modify:** `components/register/OrganisationForm.tsx`, `components/register/LocationForm.tsx`, `app/register/[id]/organisation/page.tsx`, `app/register/[id]/location/page.tsx`
- **Tests to update:** `components/register/OrganisationForm.test.tsx`, `components/register/LocationForm.test.tsx`, `app/register/[id]/organisation/page.test.tsx`, `app/register/[id]/location/page.test.tsx`
- **Read only (shared):** `components/register/register.module.css`
- **Gaps:** ODS lookup result ("Found on the register") has no applicant route: plain input plus the "checked by your shift lead" note. "Saved a moment ago" needs the step save result.
- **Notes:** Put the form in RegisterStage; role and parent organisation fields go under a "More about your organisation" Disclose (import components/admin/Disclose). Errors: polite summary at top (role=alert, "3 problems to fix", links to fields) and inline messages. Keep GET/PUT registrations/[id]/steps/[step] and addresses?postcode=.

### REG-03: Register: service and reporting steps

- **Surface:** onboarding. **Wave:** 2. **Size:** M. **Model:** sonnet (The heavy form: disclosure rows that summarise when closed and flag "Needs a review date"; per-step validation.).
- **Routes:** `/register/[id]/service`, `/register/[id]/reporting`
- **Depends on:** FOUNDATION, REG-01
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 3" (Service step with disclosures, Reporting step, API question)`
- **Boards:** `boards/onboarding/Reg.dc.html`, `boards/onboarding/RP2.dc.html`
- **Modify:** `components/register/ServiceForm.tsx`, `components/register/ReportingForm.tsx`, `app/register/[id]/service/page.tsx`, `app/register/[id]/reporting/page.tsx`
- **Tests to update:** `components/register/ServiceForm.test.tsx`, `components/register/ReportingForm.test.tsx`, `app/register/[id]/service/page.test.tsx`, `app/register/[id]/reporting/page.test.tsx`
- **Read only (shared):** `components/register/register.module.css`
- **Gaps:** none specific
- **Notes:** "The service" open; "Who it is for", "Criteria owner and review date", "Area you cover" are Disclose rows. The API question is a closed row. Keep the test-notification, confirm-details and review-request calls.

### REG-04: Register: review and submit

- **Surface:** onboarding. **Wave:** 2. **Size:** S. **Model:** sonnet (Submit gating rule and the review prototype stage.).
- **Routes:** `/register/[id]/review`
- **Depends on:** FOUNDATION, REG-01
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 3" (Review: Submit disabled until five sections complete, Fix this)`
- **Boards:** `boards/onboarding/Reg.dc.html`, `boards/onboarding/RP3.dc.html`
- **Modify:** `components/register/ReviewList.tsx`, `app/register/[id]/review/page.tsx`
- **Tests to update:** `components/register/ReviewList.test.tsx`, `app/register/[id]/review/page.test.tsx`
- **Read only (shared):** `components/register/register.module.css`
- **Gaps:** none
- **Notes:** Submit stays a real disabled button saying how many sections need attention, with a Fix this button on each section that needs it. POST registrations/[id]/submit.

### REP-02: Booking request: one BookingDecisionView for the link and the app

- **Surface:** reporter. **Wave:** 2. **Size:** L. **Model:** sonnet (Booking decisions via link tokens and the app; decline reasons, double-submit and closed states.).
- **Routes:** `/l/[token]/booking`, `/app/booking/[ref]`
- **Depends on:** FOUNDATION, REP-00a, REP-00b, REP-01
- **Brief:** `docs/design/redesign/reporter-app.md > "Per route" > Booking requests (B4)`
- **Boards:** `boards/reporter/B4.dc.html`, `boards/reporter/St.dc.html`
- **Modify:** `components/reporter/BookingDecision.tsx`, `components/reporter/app/BookingDecision.tsx`, `app/l/[token]/booking/page.tsx`, `app/(reporter)/app/booking/[ref]/page.tsx`
- **Add:**
  - frontend/components/reporter/booking/BookingDecisionView.tsx (+ .module.css, .test.tsx; wrapped by LinkFrame or ReporterAppFrame)
- **Tests to update:** `components/reporter/BookingDecision.test.tsx`, `components/reporter/app/BookingDecision.test.tsx`, `components/reporter/resultMarks.test.tsx`
- **Gaps:** none (coordinationPhone is already in the link view). Open design question 2: Decline needs no second confirm as drawn.
- **Notes:** Confirm is the single primary; Decline, closed-to-referrals and withdraw are outlined or dark, never a red danger button. Keep both existing data paths (link purpose booking-request; app GET /api/bff/reporter/bookings/[ref] and POST .../respond). Replace both old components in this change (the brief says remove the old component in the same change): the two existing component test files are updated to the new view. REP-03 runs after you and imports closed.tsx (owned by REP-01).

### REP-04: PIN screen and the /app front door

- **Surface:** reporter. **Wave:** 2. **Size:** S. **Model:** sonnet (PIN verification, lockout and session; the redirect logic is security-relevant.).
- **Routes:** `/app/pin`, `/app`
- **Depends on:** FOUNDATION, REP-00a, ONB-03
- **Brief:** `docs/design/redesign/reporter-app.md > "Per route" > App > /app and /app/pin (B6)`
- **Boards:** `boards/reporter/B6.dc.html`, `boards/reporter/Main.dc.html`
- **Modify:** `components/reporter/app/PinScreen.tsx`, `app/(reporter)/app/pin/page.tsx`, `app/(reporter)/app/page.tsx`
- **Tests to update:** `components/reporter/app/PinScreen.test.tsx`, `app/(reporter)/app/page.test.tsx`
- **Gaps:** none
- **Notes:** /app stays a redirect-only page: keep the exact decision order (no session -> pin, exec -> planning, one service -> respond, several -> update, none -> services). PinPad is owned by ONB-03; import it, do not edit it. The PIN page hides the TabBar.

### REP-05: Respond to one service and its thank-you

- **Surface:** reporter. **Wave:** 2. **Size:** M. **Model:** sonnet (Report posting with idempotency, same states as the link page; offline words.).
- **Routes:** `/app/respond/[serviceId]`, `/app/respond/[serviceId]/thanks`
- **Depends on:** FOUNDATION, REP-00a, REP-00b, REP-01
- **Brief:** `docs/design/redesign/reporter-app.md > "Per route" > App > /app/respond/[serviceId] and /thanks (B6, B2)`
- **Boards:** `boards/reporter/B6.dc.html`, `boards/reporter/B2.dc.html`, `boards/reporter/St.dc.html`
- **Modify:** `components/reporter/app/RespondScreen.tsx`, `components/reporter/app/ThanksScreen.tsx`, `app/(reporter)/app/respond/[serviceId]/page.tsx`, `app/(reporter)/app/respond/[serviceId]/thanks/page.tsx`
- **Tests to update:** `components/reporter/app/RespondScreen.test.tsx`, `components/reporter/app/ThanksScreen.test.tsx`
- **Gaps:** none
- **Notes:** Same states as REP-01 inside ReporterAppFrame. Wire in NotificationsNudge (REP-00a) while notifications are off. Uses CapacityResponseForm (REP-01): do not edit it. Thanks reads GET .../services/[id]/history.

### REP-06: Update every service at once

- **Surface:** reporter. **Wave:** 2. **Size:** M. **Model:** sonnet (Batch posting with partial failure on its own line; inline stepper per service.).
- **Routes:** `/app/update`
- **Depends on:** FOUNDATION, REP-00a, REP-00b, REP-01, REP-07
- **Brief:** `docs/design/redesign/reporter-app.md > "Per route" > App > /app/update (B6)`
- **Boards:** `boards/reporter/B6.dc.html`, `boards/reporter/St.dc.html`
- **Modify:** `components/reporter/multi/GroupedUpdate.tsx`, `app/(reporter)/app/update/page.tsx`
- **Tests to update:** `components/reporter/multi/GroupedUpdate.test.tsx`
- **Gaps:** none
- **Notes:** One primary "Both still right", per service Still right or Change (stepper opens inline), each service confirmed separately. Imports serviceState.ts (owned by REP-07). Wire in NotificationsNudge.

### REP-09: 30-day verify and locked PIN

- **Surface:** reporter. **Wave:** 2. **Size:** M. **Model:** sonnet (Device-code identity flow and PIN lock; resend countdown; same-screen morph to six-digit entry.).
- **Routes:** `/app/verify`, `/app/locked`
- **Depends on:** FOUNDATION, REP-00a, ONB-01, ONB-03
- **Brief:** `docs/design/redesign/reporter-app.md > "Per route" > App > /app/verify and /app/locked (B8)`
- **Boards:** `boards/reporter/B8.dc.html`
- **Modify:** `components/reporter/app/VerifyScreen.tsx`, `components/reporter/app/LockedScreen.tsx`, `app/(reporter)/app/verify/page.tsx`, `app/(reporter)/app/locked/page.tsx`
- **Tests to update:** `components/reporter/app/VerifyScreen.test.tsx`, `components/reporter/app/LockedScreen.test.tsx`
- **Gaps:** none
- **Notes:** After Send code the screen morphs to the six-digit entry with a resend countdown (identity/device-code and .../verify). Locked: "Text me a code" is the primary. CodeEntry/CodeInput are owned by ONB-01 and PinSetup (imported by LockedScreen) by ONB-03: import, do not edit. Both screens hide the TabBar.

### REP-10: Lost phone and notifications off

- **Surface:** reporter. **Wave:** 2. **Size:** M. **Model:** sonnet (New-phone identity flow (number, code, call-back wait, sign-out-everywhere) and the browser permission check.).
- **Routes:** `/app/lost-phone`, `/app/notifications-off`
- **Depends on:** FOUNDATION, REP-00a, REP-00b, ONB-01
- **Brief:** `docs/design/redesign/reporter-app.md > "Per route" > App > /app/lost-phone and /app/notifications-off (B9)`
- **Boards:** `boards/reporter/B9.dc.html`
- **Modify:** `components/reporter/app/LostPhone.tsx`, `components/reporter/app/NotificationsOff.tsx`, `app/(reporter)/app/lost-phone/page.tsx`, `app/(reporter)/app/notifications-off/page.tsx`
- **Tests to update:** `components/reporter/app/LostPhone.test.tsx`, `components/reporter/app/NotificationsOff.test.tsx`
- **Gaps:** none
- **Notes:** Lost phone: number, code, then "Waiting for a call-back" (identity/new-phone, .../verify, identity/sign-out-everywhere). Notifications off: three steps (identity/channel, reporter/channel, client permission check). The one-line nudge banner itself is built in REP-00a and wired into respond and update by REP-05 and REP-06, not here.

### WAL-01: Wall board (large format)

- **Surface:** advisor. **Wave:** 2. **Size:** M. **Model:** sonnet (Wall liveness (stale after 180 s) and 3 m legibility rules; shares Board as the one renderer.).
- **Routes:** `/screen`
- **Depends on:** FOUNDATION, ADV-00, BRD-01
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.3 Wall screen" > /screen`
- **Boards:** `boards/advisor/WallBoard.dc.html`
- **Modify:** `components/board/LiveBoard.tsx`, `components/board/StatusAnnouncer.tsx`, `app/(wall)/screen/page.tsx`
- **Tests to update:** `components/board/LiveBoard.test.tsx`, `components/board/StatusAnnouncer.test.tsx`, `app/(wall)/screen/page.test.tsx`, `app/(wall)/screen/page.network.test.tsx`
- **Gaps:** Wall light vs dark ground is an open question (brief 9.4): draw dark as the board does.
- **Notes:** Tile numbers 100px or more, service names 30px, status words 22px, no text under 20px. No motion except the reconnect spinner (WAL-02). Keep lib/board/liveness.ts reasons (offline, unreadable, old). BoardUnavailable is owned by BRD-01.

### ADM-99: Administration page tests sweep

- **Surface:** admin. **Wave:** 3. **Size:** S. **Model:** haiku (Fix the shared page test after the route units.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, ADM-01, ADM-02, ADM-03, ADM-04, ADM-05, ADM-06, ADM-07, ADM-08
- **Brief:** `docs/design/redesign/admin-operator-public.md > "7. Suggested build order"`
- **Boards:** `boards/admin/Main.dc.html`
- **Tests to update:** `app/(tenant-admin)/admin/pages.test.tsx`
- **Gaps:** none
- **Notes:** layout.test.tsx belongs to the foundation. Only edit assertions that broke and report each.

### ADV-08: Options list, not-suitable list and the request deep link

- **Surface:** advisor. **Wave:** 3. **Size:** L. **Model:** sonnet (The core advisor decision list: not ranked, sorted by travel time, deep link into the Request state.).
- **Routes:** `/advisor/case/[ref]/options`
- **Depends on:** FOUNDATION, ADV-01, ADV-03, ADV-04, ADV-05, ADV-06, ADV-07, NET-00
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.1 Advisor" > .../options and .../options?service=`
- **Boards:** `boards/advisor/Call.dc.html`, `boards/core-morph/S3.dc.html`, `boards/core-morph/P2.dc.html`
- **Modify:** `components/advisor/OptionsList.tsx`, `components/advisor/OptionsList.module.css`, `components/advisor/ServiceCard.tsx`, `components/advisor/ServiceCard.module.css`, `components/advisor/ServicePhone.tsx`, `app/(advisor)/advisor/case/[ref]/options/page.tsx`
- **Tests to update:** `components/advisor/OptionsList.test.tsx`, `components/advisor/OptionsList.askService.test.tsx`, `components/advisor/ServiceCard.test.tsx`, `app/(advisor)/advisor/case/[ref]/options/page.test.tsx`, `components/advisor/DistrictChoice.test.tsx`
- **Read only (shared):** `components/advisor/Advisor.module.css`, `components/advisor/map.module.css`
- **Gaps:** none
- **Notes:** Resolve ?service=[id] to a service in this case's options and ignore it otherwise. Keep "Sorted by travel time. Not ranked." DistrictChoice.test.tsx tests district choice on the list (yours) and on the map (ADV-10 edits it afterwards). Advisor.module.css is read-only here (ADV-06). ServiceCard is imported by NetworkOptions (ADV-11): keep exports. NotSuitableList and NoServiceFits are owned by ADV-04 (import only). OwnScopeHeader (NET-00) is imported by the page.

### ADV-09: Compare, radar and ways

- **Surface:** advisor. **Wave:** 3. **Size:** L. **Model:** sonnet (No-score, no-rank rule in Compare, lane order that never hides a lane, charts/map, shared RadarScreens test.).
- **Routes:** `/advisor/case/[ref]/compare`, `/advisor/case/[ref]/radar`, `/advisor/case/[ref]/ways`
- **Depends on:** FOUNDATION, ADV-01, ADV-03, ADV-04, ADV-05, ADV-07
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.1 Advisor" > .../compare, .../radar, .../ways`
- **Boards:** `boards/advisor/Compare.dc.html`, `boards/advisor/Radar.dc.html`, `boards/advisor/Ways.dc.html`, `boards/advisor/PWays.dc.html`
- **Modify:** `components/radar/CompareScreen.tsx`, `components/radar/WaysScreen.tsx`, `components/radar/RadarScreen.tsx`, `components/radar/RadarFrame.tsx`, `components/radar/RadarTabs.tsx`, `components/radar/RadarMap.tsx`, `app/(advisor)/advisor/case/[ref]/compare/page.tsx`, `app/(advisor)/advisor/case/[ref]/radar/page.tsx`, `app/(advisor)/advisor/case/[ref]/ways/page.tsx`, `components/radar/radar.module.css`
- **Tests to update:** `components/radar/RadarMap.test.tsx`, `app/(advisor)/advisor/case/[ref]/radar/page.test.tsx`, `components/radar/RadarScreens.test.tsx`
- **Read only (shared):** `components/advisor/map.module.css`
- **Gaps:** Compare rows "Adds to today's round" and "Patients already near" stay Not available (not zero). Radar drive-time rings and traffic stay shown as off with the reason.
- **Notes:** RadarScreens.test.tsx covers all three screens: you own it. RadarTabs is replaced by the shared ViewToggle (ADV-01): delete RadarTabs.tsx if nothing else imports it. Lane order follows the optional can-travel answer, never hides a lane. Compare offers outlined Request buttons so no column looks recommended. RadarMap imports advisor/map.module.css (frozen). OptionBooking (ADV-05) and PostcodeStates (ADV-03) are imported: do not edit.

### INV-02: Invite a reporter: compose state with text preview

- **Surface:** onboarding. **Wave:** 3. **Size:** M. **Model:** sonnet (Sends invitations (links, pilot-scope refusal); idempotent POST.).
- **Routes:** `/lead/reporters/invite`
- **Depends on:** FOUNDATION, INV-01
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 1" (Compose state, InvitePreview)`
- **Boards:** `boards/onboarding/LI1.dc.html`
- **Modify:** `components/lead/InviteForm.tsx`, `app/(lead)/lead/reporters/invite/page.tsx`
- **Add:**
  - frontend/components/lead/InvitePreview.tsx (text bubble, polite live region updated on blur) (+ .module.css, .test.tsx)
- **Tests to update:** `components/lead/InviteForm.test.tsx`
- **Read only (shared):** `components/lead/Lead.module.css`
- **Gaps:** none
- **Notes:** URL: /lead/reporters/invite?service=<id>. Only pilot services can be invited. Phone: preview under Send, collapsed to one line with a Show text disclosure. POST /api/bff/lead/invitations.

### INV-03: Change a reporter's number: the detail state with the row open

- **Surface:** onboarding. **Wave:** 3. **Size:** S. **Model:** sonnet (Changes the number a reporter is reached on (identity-sensitive).).
- **Routes:** `/lead/reporters/number`
- **Depends on:** FOUNDATION, INV-01
- **Brief:** `docs/design/redesign/provider-onboarding.md > "Journey 1" (Change number state)`
- **Boards:** `boards/onboarding/LI2.dc.html`
- **Modify:** `components/lead/ChangeNumberForm.tsx`, `app/(lead)/lead/reporters/number/page.tsx`
- **Tests to update:** `components/lead/ChangeNumberForm.test.tsx`
- **Read only (shared):** `components/lead/Lead.module.css`
- **Gaps:** none
- **Notes:** URL: /lead/reporters/number?service=<id> renders the Detail state with the "Change their number" row open. POST /api/bff/lead/reporters/number.

### NAD-99: Network administration page tests sweep

- **Surface:** network. **Wave:** 3. **Size:** S. **Model:** haiku (Fix the shared page test after the route units.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, NAD-01, NAD-02, NAD-03
- **Brief:** `docs/design/redesign/planning-analytics-network.md > "7. Suggested build order" step 5`
- **Boards:** `boards/planning/Main.dc.html`
- **Tests to update:** `app/(network-admin)/network-admin/pages.test.tsx`
- **Gaps:** none
- **Notes:** Layout test (layout.test.tsx) belongs to the foundation. Only edit assertions that broke and report each.

### NET-99: Network page tests sweep

- **Surface:** network. **Wave:** 3. **Size:** S. **Model:** haiku (Fix the shared page test for the network pages after the route units.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, NET-01, NET-02, NET-03, NET-04, NET-05, NET-06, NET-07
- **Brief:** `docs/design/redesign/planning-analytics-network.md > "7. Suggested build order" step 4`
- **Boards:** `boards/planning/Main.dc.html`
- **Tests to update:** `app/(network)/network/pages.test.tsx`
- **Gaps:** none
- **Notes:** Only edit assertions that broke because of the redesign and report each.

### OPR-99: Operator page tests sweep

- **Surface:** admin. **Wave:** 3. **Size:** S. **Model:** haiku (Fix the shared operator page test after the route units.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, OPR-01, OPR-02, OPR-03, OPR-05, OPR-10, OPR-11
- **Brief:** `docs/design/redesign/admin-operator-public.md > "7. Suggested build order"`
- **Boards:** `boards/admin/Main.dc.html`
- **Tests to update:** `app/(operator)/operator/pages.test.tsx`
- **Gaps:** none
- **Notes:** OperatorNav, OperatorFooter and the (area) layout are the foundation's. Only edit assertions that broke and report each.

### PLN-03: Alerts and an alert acknowledged in place

- **Surface:** planning. **Wave:** 3. **Size:** M. **Model:** sonnet (Acknowledge, call and snooze in place; patient-flow escalation alert; phone full-screen from a notification.).
- **Routes:** `/planning/alerts`, `/planning/alerts/[id]`
- **Depends on:** FOUNDATION, PLN-01, PLN-02
- **Brief:** `docs/design/redesign/planning-analytics-network.md > Planning > /planning/alerts and /planning/alerts/[id]`
- **Boards:** `boards/planning/PAlerts.dc.html`, `boards/planning/PAlert.dc.html`, `boards/planning/PH2.dc.html`, `boards/planning/PH3.dc.html`, `boards/planning/Morph.dc.html`
- **Modify:** `components/exec/AlertList.tsx`, `components/exec/AlertDetail.tsx`, `app/(exec)/planning/alerts/page.tsx`, `app/(exec)/planning/alerts/[id]/page.tsx`
- **Tests to update:** `components/exec/AlertList.test.tsx`, `components/exec/AlertDetail.test.tsx`
- **Read only (shared):** `components/exec/Exec.module.css`
- **Gaps:** The alert ladder (you, deputy at 15 min, shift lead by phone) is configuration from alert preferences; the deputy name only if exec/leaders may show it (brief 4 item 6).
- **Notes:** Acknowledge, Call and Snooze keep the same positions as the standalone page. Tabs Open, Acknowledged, Closed. Imports ui/Banner (shared).

### REP-03: Booking change: withdraw, not reached, cancelled and closed words

- **Surface:** reporter. **Wave:** 3. **Size:** M. **Model:** sonnet (Link token answers (withdraw, not-reached with reason), reason chips, tel: link, closed-state words.).
- **Routes:** `/l/[token]/booking/change`
- **Depends on:** FOUNDATION, REP-00a, REP-00b, REP-01, REP-02
- **Brief:** `docs/design/redesign/reporter-app.md > "Per route" > Booking requests > /l/[token]/booking/change (B5)`
- **Boards:** `boards/reporter/B5.dc.html`, `boards/reporter/St.dc.html`
- **Modify:** `components/reporter/BookingChange.tsx`, `app/l/[token]/booking/change/page.tsx`
- **Tests to update:** `components/reporter/BookingChange.test.tsx`, `components/reporter/resultMarks.test.tsx`
- **Gaps:** none
- **Notes:** Use ReasonChips (REP-00a). tel: link when coordinationPhone is present, otherwise "phone the number on the register". Closed states come from lib/links/model.ts.

### ADV-10: Options on a map and the postcode-not-found state

- **Surface:** advisor. **Wave:** 4. **Size:** M. **Model:** sonnet (Map pins, areas, route and district chooser (PUT cases/[ref]/district); search-again saves the postcode.).
- **Routes:** `/advisor/case/[ref]/map`
- **Depends on:** FOUNDATION, ADV-01, ADV-03, ADV-05, ADV-07, ADV-08, NET-00
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.1 Advisor" > .../map`
- **Boards:** `boards/advisor/Map.dc.html`, `boards/advisor/MapLost.dc.html`
- **Modify:** `components/advisor/MapScreen.tsx`, `components/advisor/OptionsMap.tsx`, `components/advisor/TravelDetails.tsx`, `app/(advisor)/advisor/case/[ref]/map/page.tsx`
- **Tests to update:** `components/advisor/OptionsMap.test.tsx`, `components/advisor/OptionsMap.route.test.tsx`, `components/advisor/TravelDetails.test.tsx`, `app/(advisor)/advisor/case/[ref]/map/page.test.tsx`, `components/advisor/DistrictChoice.test.tsx`, `components/advisor/PostcodeSearch.test.tsx`
- **Read only (shared):** `components/advisor/map.module.css`
- **Gaps:** none
- **Notes:** District chooser as its own card (MapLost). map.module.css is frozen (used by 7 files across units): add your own css and stop importing it in your files. NetworkMap (ADV-11) renders OptionsMap: keep its props. Phone: map above list.

### PLN-99: Planning page tests sweep

- **Surface:** planning. **Wave:** 4. **Size:** S. **Model:** haiku (Fix the shared page-level test for the planning pages after the route units.).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION, PLN-01, PLN-02, PLN-03, PLN-04, PLN-05, PLN-06, PLN-07
- **Brief:** `docs/design/redesign/planning-analytics-network.md > "7. Suggested build order"`
- **Boards:** `boards/planning/Main.dc.html`
- **Tests to update:** `app/(exec)/planning/pages.network.test.tsx`
- **Gaps:** none
- **Notes:** Only edit assertions that broke because of the redesign and report each. Do not weaken them.

### ADV-11: Other organisations' options, list and map (read only)

- **Surface:** advisor. **Wave:** 5. **Size:** M. **Model:** sonnet (Read-only network scope: only the network id and case ref are sent; one phone action per row.).
- **Routes:** `/advisor/case/[ref]/network-options`, `/advisor/case/[ref]/network-map`
- **Depends on:** FOUNDATION, ADV-01, NET-00, ADV-04, ADV-08, ADV-10
- **Brief:** `docs/design/redesign/advisor-clinical-wall.md > "4.1 Advisor" > .../network-options, .../network-map`
- **Boards:** `boards/advisor/NetworkOptions.dc.html`
- **Modify:** `components/advisor/NetworkOptions.tsx`, `components/advisor/NetworkMap.tsx`, `components/advisor/NetworkCriteriaDialog.tsx`, `components/advisor/NetworkServiceLine.tsx`, `app/(advisor)/advisor/case/[ref]/network-options/page.tsx`, `app/(advisor)/advisor/case/[ref]/network-map/page.tsx`
- **Tests to update:** `components/advisor/NetworkOptions.test.tsx`, `components/advisor/NetworkMap.test.tsx`, `components/advisor/NetworkCriteriaDialog.test.tsx`, `app/(advisor)/advisor/case/[ref]/network-options/page.test.tsx`, `app/(advisor)/advisor/case/[ref]/network-map/page.test.tsx`
- **Read only (shared):** `components/advisor/map.module.css`
- **Gaps:** none
- **Notes:** Reads /api/bff/network/options. No tenant, network or scope identifier from the browser. ScopeHeader and ReadOnlyNote (NET-00) stay on the page. Imports ServiceCard, OptionsList.module.css, NotSuitableList (ADV-08) and OptionsMap (ADV-10): do not edit them.

### CSS-A: Dead css: lead, advisor map and dialog css

- **Surface:** cleanup. **Wave:** 6. **Size:** M. **Model:** haiku (Mechanical: delete CSS classes that no file imports any more (grep before deleting).).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION and every other unit
- **Brief:** `docs/design/redesign/AGENT-GROUND-RULES.md > "5. Code rules that bite"`
- **Boards:** `boards/admin/Main.dc.html`
- **Modify:** `components/lead/Lead.module.css`, `components/lead/lead-forms.module.css`, `components/advisor/map.module.css`, `components/advisor/dialog-body.module.css`
- **Gaps:** none
- **Notes:** OPTIONAL and LAST. Frozen shared stylesheets were read-only for every other unit, which added their own css instead. For each class in the files you own, grep the whole of frontend/ for its use (a module is imported as styles.<name> or styles[...]); delete only classes with no use. Never delete a file still imported by a file that is not part of the redesign (for example components/admin/UsersAndRoles, AdminShell, AppShell). Run the lead, owner, advisor and radar folders afterwards.

### CSS-B: Dead css: admin, exec, console, network, operator

- **Surface:** cleanup. **Wave:** 6. **Size:** M. **Model:** haiku (Mechanical: delete CSS classes that no file imports any more (grep before deleting).).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION and every other unit
- **Brief:** `docs/design/redesign/AGENT-GROUND-RULES.md > "5. Code rules that bite"`
- **Boards:** `boards/admin/Main.dc.html`
- **Modify:** `components/admin/admin.module.css`, `components/exec/Exec.module.css`, `components/console/Console.module.css`, `components/network/Network.module.css`, `components/operator/Tenant.module.css`
- **Gaps:** none
- **Notes:** OPTIONAL and LAST. Frozen shared stylesheets were read-only for every other unit, which added their own css instead. For each class in the files you own, grep the whole of frontend/ for its use (a module is imported as styles.<name> or styles[...]); delete only classes with no use. Never delete a file still imported by a file that is not part of the redesign (for example components/admin/UsersAndRoles, AdminShell, AppShell). Run the admin, networkAdmin, operator, exec, clinical, help, console, learn, planning, network and scope folders afterwards.

### CSS-C: Dead css: reporter, setup, register

- **Surface:** cleanup. **Wave:** 6. **Size:** M. **Model:** haiku (Mechanical: delete CSS classes that no file imports any more (grep before deleting).).
- **Routes:** none (shared components, no route of its own)
- **Depends on:** FOUNDATION and every other unit
- **Brief:** `docs/design/redesign/AGENT-GROUND-RULES.md > "5. Code rules that bite"`
- **Boards:** `boards/admin/Main.dc.html`
- **Modify:** `components/reporter/Reporter.module.css`, `components/reporter/setup/Setup.module.css`, `components/register/register.module.css`
- **Gaps:** none
- **Notes:** OPTIONAL and LAST. Frozen shared stylesheets were read-only for every other unit, which added their own css instead. For each class in the files you own, grep the whole of frontend/ for its use (a module is imported as styles.<name> or styles[...]); delete only classes with no use. Never delete a file still imported by a file that is not part of the redesign (for example components/admin/UsersAndRoles, AdminShell, AppShell). Run the reporter, practitioner and register folders afterwards.


## How to run

**Before anything:** the foundation (AppFrame and the shell wrappers, StageGrid/StageLayer, StatusTag, tokens, the staff layouts) is merged into `main`. Every unit branches from that `main`. If the foundation's `StatusTag` lacks a shape a brief names (the reporter brief draws a tick for Confirmed and a clock for Due now; the foundation has done, waiting, todo, problem, live, closed, over, paused), that is a foundation change, not a unit change: units say so in their report ("shared files I wanted to change").

**Scheduling.** Run at most 6 agents at once. Inside a wave any order is fine (units of one wave never share a file). A unit may start as soon as every id in its `depends_on` is merged into `main`, which lets waves overlap, but the simple, safe way is to finish and merge a wave before starting the next. After each merge run the touched folders' tests on `main`; a unit whose branch was cut earlier needs no rebase because it shares no file with units merged after it (units that do share files are chained).

**Order of waves.**

0. **Shared parts** (13 units, all `sonnet`): REP-00a, REP-00b (reporter frames, figure, stepper, chips), ONB-00 (ProviderShell, SetupProgress, StickyAction), LED-00a (StepBar, MorphStage, SummaryPin), LED-00b (ConfirmDialog, DiffTable, VersionTimeline, LadderTimeline), ADM-00a (settings blocks), ADM-00b (task, contact, retention, timeline, progress blocks), PLN-00a (charts), PLN-00b (StatusTile, DataTable), NET-00 (scope header and notices), PUB-00 (SplitHero), ADV-00 (Tile and StatusChip), ADV-01 (CallStage, step bar, pinned summary, view switch). Run in three batches of at most six; nothing in wave 0 depends on another wave 0 unit (ADV-00 and NET-00 both touch neighbours of `OrgLabel` and `Tile`: their notes say keep props).
1. **Independent pages** (63 units plus one skip). Everything that needs only wave 0 parts or nothing.
2. **Pages that need a wave 1 unit** (39 units). Examples: REP-02, REP-04, REP-05, REP-06 (need REP-01 or ONB-03/REP-07), ONB's REG-02..REG-04 (need REG-01), LRV-02/03 (need LRV-01), INV-01 (needs LDR-02), CRI-02..04 (need CRI-01), OPR-05..OPR-09 (need the extraction unit OPR-04), PLN-02 (needs PLN-01), ADV-05 (needs ADV-06), PRA-02 (needs PRA-01), WAL-01 (needs BRD-01), CLN-02 (needs CLN-01), PUB-05 (needs PUB-04), NET-01, NET-02, NET-06, ADM-03..ADM-06, NAD-02, NAD-03, LDR-01, LDR-04, LDR-07, LDR-09.
3. **Deeper pages and first sweeps** (10): ADV-08 (options list), ADV-09 (compare, radar, ways), REP-03, PLN-03, INV-02, INV-03, and the sweeps ADM-99, NAD-99, NET-99, OPR-99.
4. ADV-10 (map; edits tests shared with ADV-03 and ADV-08) and PLN-99.
5. ADV-11 (network options and map; imports ADV-08 and ADV-10 output).
6. **Optional, last, alone:** CSS-A, CSS-B, CSS-C (delete dead rules from the frozen stylesheets once nothing imports them). Skip them if time is short: nothing depends on them.

**Critical paths** (longest chains, start them early within their wave): advisor call ADV-01 -> ADV-06 -> ADV-05 -> ADV-08 -> ADV-10 -> ADV-11; reporter links REP-00a/b -> REP-01 -> REP-02 -> REP-03; planning PLN-00b -> PLN-01 -> PLN-02 -> PLN-03 -> PLN-99; operator funnel OPR-04 -> OPR-05..09 -> OPR-99; set-up and recovery ONB-01 + ONB-03 -> REP-04, REP-09, REP-10.

**Merge order rule inside a chain:** merge each unit before the next one starts. The notes of the earlier unit name the exports the later unit imports.

**Units I think are risky, and why**

- **OPR-04** (extract the funnel steps). 911-line `TenantPanels.tsx` and an 860-line `TenantDetail.test.tsx` are split with no behaviour change. If any assertion is dropped or the step order changes, OPR-05..09 build on a broken base. Verify before and after: the operator folder's test counts must match.
- **REP-00a** (reporter layouts). It removes the staff header from `(reporter)/layout.tsx` and `l/layout.tsx`; `(reporter)` also covers `/setup/*`, so ONB units depend on the same decision. A wrong layout change affects every reporter page at once.
- **REP-01** and **REP-02/03** (capacity link and booking link). Bearer tokens in the address, one-read-per-view CSRF rule, idempotency keys, out-of-range confirm; patient-flow impact if a figure is lost. The text fallback cannot be built (no field in `LinkView`).
- **ADV-01** (CallStage). Wraps nine advisor pages; the grid state machine, `inert` folded columns and focus-to-heading must work before the others are merged. ADV-08 (options list) is the biggest unit by dependencies and the home of the `?service=` deep link.
- **ADV-03** (needs form). The brief wants a live count while typing; the data does not support it without writing drafts (a decision is needed; the unit defaults to no live count). It also owns `PostcodeStates`, which three later units import.
- **ONB-01, ONB-03, REP-04, REP-09, REP-10** (identity: invitation code, device code, PIN, lost phone). Security-relevant flows; tests first and no change to the calls.
- **PLN-01/02/03** (home to service to alert). The brief asks for a clinical-safety review of this morph before building; Acknowledge, Call and Snooze must keep their positions.
- **LDR-03/LDR-04** (add a service, 509-line `AddServiceForm` with one 500-line test, built in two sequential units) and **CRI-01..04** (the owner flow is a morph across ten files).
- **LRV-01** (review stage): the `[id]` page renders four step components owned by LRV-02/LRV-03; their props must stay.
- **CLN-02** (clinical case): DEC-855/DEC-1179 gating and a hold timer that may have no data.
- **ADV-00** and **BRD-01**: `board/styles.test.ts` reads both `Tile.module.css` and `Board.module.css`, so the two units edit the same test (chained).
- **PUB-04** (learn): local-storage tests already fail on this machine without the flag; do not mistake them for regressions.
- **Sweep units (`*-99`)** fix shared page tests after the fact; if a route unit changed a heading or landmark, expect a few red assertions until its sweep runs.
