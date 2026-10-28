# Tenancy audit D: front end and UI specification

Audit of `main` (read at 1ac81b9, then DEC-131 and DEC-132 at 2cf069e), the unmerged W02 branch (`task/W02-bff-session-csrf` at a610247, local; there is no `origin/task/W02-bff-session-csrf` ref, so the diff was taken with `git diff main...task/W02-bff-session-csrf`), `docs/spec/ui-screens.md`, `docs/design/design-system.md`, `docs/spec/observability.md`, the UI tasks in `docs/plan/tasks.json` and their prompts in `docs/plan/prompts/`. Read-only audit. Nothing else was edited. All hour figures are estimates (plus or minus 30 percent).

Governing decisions: DEC-130 (tenant bound at one point, from a verified source only, one tenant per staff member, cross-tenant access explicit and audited), DEC-131 (per-tenant sender numbers, inbound number resolves the tenant), DEC-132 (tenant is the legal entity; a Network groups member tenants; sharing only by grant, as read-only projections; members' staff see the network capacity view in addition to their own tenant's; wall screens are paired to one tenant and set by that tenant's administrator to show the tenant board or the network board; reporters on phone and link see their own tenant only), DEC-014 and DEC-019 (design system and tokens), DEC-109 (BFF client), DEC-122 (base components), DEC-125 (W02, only on the W02 branch), DEC-129 (UI builds from the repo snapshot).

Wording note: "scope" below means exactly one of two things a viewer can look at: `tenant` (their own organisation) or `network` (the DEC-132 projection scope). It is never a free choice of tenant.

---

## 1. Summary

### Counts (each verified by grep or script on the date of this audit)

| Item | Count | How verified |
|---|---|---|
| Design canvas artboards in `ui-screens.md` | 62 | `grep -c "^## Artboard" docs/spec/ui-screens.md` |
| of which journey artboards / journeys | 5 artboards / 10 journeys | Journeys, Journeys2 to Journeys5, two journeys each |
| of which empathy artboard / maps | 1 / 4 | Empathy2 (line 570) |
| of which screen artboards | 56 (53 UI screens, 3 non-screens: RegisterModel, ApprovalStates, ValueCase) | read in full |
| Numbered screen panels inside artboards | 183 | script over `^[0-9]+ [A-Z]` lines outside script blocks |
| Page routes built on `main` | 2 (`/` at `app/page.tsx`, `/screen` at `app/(wall)/screen/page.tsx`, a placeholder) | `git ls-files frontend/app` |
| Page routes planned (W-series, O09, S01) | about 91 | page paths named in the prompts, plus the pages the prompts name only by ellipsis (setup/notifications, setup/pin, setup/all-set, register reporting/review/submitted, clinical x3, app/verify, app/locked, app/notifications-off, app/services/*, app/respond thanks) |
| BFF route handlers built on `main` | 0 | no `app/api` on main |
| BFF route handlers on the W02 branch | 1 file (GET and DELETE `/api/bff/session`) | `git diff --stat` |
| BFF METHOD+path pairs planned | about 125 | 109 distinct `METHOD /api/bff/...` strings in the prompts, plus 16 named by ellipsis (links x3, telemetry, W27 x2, W29 x4, W30 x3, W31 x2, W35 history) |
| Components built | 7 (Banner, Button, Card, Chip, NumberStepper, OptionButton, StatusBadge) | `frontend/components/ui/*.tsx` |
| Component files planned (named in prompts) | about 58 | regex over Build sections |
| Roles | 10 in `ROLES` (reporter, advisor, clinical, lead, owner, exec, wall, anonymous-link, support, audit), `lib/auth/session.ts:8-19` on the W02 branch | read. `observability.md:27` lists only 8 (no support, audit). DEC-132 adds two actors that no role covers: tenant administrator and network owner administrator (section 9, Q4) |
| Test files on `main` | 19 vitest files plus 1 Playwright spec (20); 114 `it`/`test` calls (2 in the e2e spec) | `git ls-files` and grep |
| Test files on W02 branch | 4 vitest files (77 calls; evidence says 88 with `it.each`) plus `test/cookies.ts` | grep |
| MSW handlers on `main` | 0 (empty array, `test/msw/handlers/index.ts:5`); 8 handler files planned (board, bookings, cases, links, registration, registrations, screens, index) | grep |
| Stable element ids (`data-el`) named in W prompts | 206 distinct (ADV 97 mentions, LEAD 35, REP 30, REG 23, ONB 13, EXEC 12, OWN 9, CON 9, SVC 7, HELP 6, TOUR 5, LEARN 5, CLIN 5, PLAN 4, WALL 2) | grep |
| UI tasks in plan | 65 (56 W + O02, O03, O05, O09, S01, X02, X03, F03, F09), 226 planned hours; delivered: F03 (4 h), F09 (3), X02 (3), X03 (2), W01 (4), W03 (4); W02 (3 h) built but unmerged | `tasks.json`, ledger |
| `tenant` in `frontend/` | 0 matches | `grep -rni tenant frontend` |

New under DEC-132 (none of these exist in the spec, the canvas, `tasks.json` or any prompt): 6 new screens or screen groups (network administration, grant approval, sharing transparency, network capacity view, which-board control with wall screen list, network unavailable states) and a network variant of 14 existing screens (section 2e).

### Overall difficulty

Medium for what is built, high for what is planned, and the order matters.

- What is built is small (59 tracked files under `frontend/`, 7 presentational components, no BFF route on main). Nothing built stores or shows tenant data. The only real rework is W02 (session shape, CSRF, no-store), a small W01 guard, and F03's strings. Doing W02 now, before it merges, costs about 5 h; doing it later as a sweep costs more because W09 onward will have built on the old `Session`.
- What is planned is large: 56 prompts written for one area ("Dorset" appears in the boilerplate of all 215 prompts, and the literal strings "Dorset urgent care capacity" and "Dorset system" in W05 and W40). Every prompt says "Where this prompt and the documents differ, follow this prompt" (for example `W02.md`, the preamble), so a DEC does not fix a literal in a prompt. The prompts have to be amended.
- The hard parts are not the screens. They are: (1) who mints the tenant-bound token (the BFF as planned in W09 holds a secret that can mint any tenant); (2) browser state that outlives a sign-out or an unpair (service worker, push subscription, localStorage, back-forward cache, CSRF cookie clobbering); (3) wall screens (pairing, revoke, last-known); (4) link pages used in a browser that holds another session; (5) the two-scope model of DEC-132, where the screen must always say which scope it is showing and which organisation each row belongs to; (6) the support console, which DEC-130 item 8 and DEC-132 item 8 leave without any role.
- Estimated extra work: about 169 h of tenancy work on top of the 226 h of planned UI (about 75 percent), listed in section 10 as 26 required tasks (TEN-D01 to TEN-D26) plus one optional (8 h). About 50 h of that lands inside tasks already in the plan (as amended prompts and estimates) and the rest is new tasks. About 61 h is the DEC-132 network scope, none of which exists in the plan today; without it the tenancy-only figure is about 108 h.
- Design gap: the canvas snapshot has no screen for the network. DEC-129 says UI tasks build from `ui-screens.md` and `docs/design/`, so the new screens need a specification first (TEN-D31).

---

## 2. Every screen and journey

Legend. Roles: rep reporter, adv advisor, clin clinical, lead shift lead, own criteria owner, exec COO and ICB, wall wall device, link anonymous-link, sup support, aud audit, app applicant (a `reporter` session with `services: []`, `W23.md:49`). Task: `built` means on main; `W02` is built but unmerged; others are planned. Tenant data: T = tenant-specific content shown (service names are data, listed once; copy that names an area, organisation, system or number is listed). Risk: H cross-tenant exposure or action if mis-bound, M exposure of tenant-specific content or an oracle, L cosmetic or none. "Net" means the screen gains a DEC-132 network variant (details in 2e). Line numbers are in `docs/spec/ui-screens.md`.

### 2a. Journeys (10) and empathy maps (4)

| Journey (artboard, line) | Roles | Task | Tenant-specific content | Change for tenancy | Risk |
|---|---|---|---|---|---|
| J1 Reporter loop by text (Journeys, 6) | rep, link | W04, backend D15/U03/U05 | service name, unit, link domain `diucs.example`, sender number | link domain and sender number come from tenant config (DEC-131: per-tenant number); tenant resolved from the link token or the number called, never from the sender | M |
| J2 Advisor call flow (Journeys, 6) | adv | W10 to W16, W20, W50 | options list, criteria, "SystmOne" | Net: options and board may include read-only network rows; booking and phoning stay tenant-only (section 2e). EPR name from config | H |
| J3 Reporter loop by email (Journeys2, 102) | rep, link | W04 | service name, "role inbox", email sender | per-tenant sender identity (DEC-131); expired and used pages must not distinguish unknown from expired | M |
| J4 Booking request by text or email (Journeys2, 102) | adv, rep, link | W19, W20, W21, W22, W36 | reference (4 digits, unique per tenant only, DEC-131 item 3), reply-by, "SystmOne" | references are per tenant: every route taking `[ref]` or `[id]` is tenant-scoped and answers 404, not 403, across tenants. Bookings are never shared (DEC-132 item 4), so no network variant | H |
| J5 Shift lead: a shift (Journeys3, 198) | lead | W09, W17, W18, W42, W43, W47 | "Trust account", ladder times, "system pressure" | one tenant only; sign-in copy from config. Net: the "watch the board" step gains the network view | M |
| J6 Clinical advisor: a request (Journeys3, 198) | clin | W09, W44, W45 | "Trust account", availability counts | queue and presence are tenant scoped unless the owner rules a shared clinical pool (Q6). Not shared by DEC-132 (cases are never shared) | H if pool shared |
| J7 COO and ICB lead (Journeys4, 322) | exec | W33, W39, W40, W41 | "Dorset system" wording, alert thresholds, ladder to "SPOA shift lead" | Net: home, pressure, alerts and week gain a scope. Own-tenant default | M |
| J8 Criteria owner (Journeys4, 322) | own, clin | W30, W31 | owner roles, review dates | tenant scoped. Criteria version is projected to the network (DEC-132 item 4); editing stays tenant-only | L |
| J9 Registration and approval (Journeys5, 446) | app, lead, own | W23 to W29, W54 | ODS code, "Dorset pathway", SPOA | tenant bound by the invitation; scope list is per tenant; copy from config | H |
| J10 One phone, several services (Journeys5, 446) | rep | W38 | service names, cover numbers | all services on one phone must be in one tenant (the device session is one tenant). A person in two tenants has two Person records and two sign-ins (DEC-131 item 3). Open Q5 | H |
| Empathy maps x4 (Empathy2, 570) | n/a | none (research) | none | none | none |

### 2b. Wall board, link pages, booking

| Screen (artboard, line) | Roles | Task | Tenant-specific content | Change for tenancy | Risk |
|---|---|---|---|---|---|
| Wall board (Main, 654) | wall; adv, lead via `/advisor/board`; exec via BFF board | W05 (`/screen` placeholder from F03 is built) | heading "Dorset urgent care capacity" and "Single point of access" (657-658; also `W05.md:51`), 9 services, "Friday 23 October" (London time), legend (fixed) | header is `{Area name} capacity` from tenant config (DEC-014 item 1 and 5, `design-system.md:199`); never literal. Always show the scope label. Page dynamic and `no-store`. Net | H |
| Wall tile: pending booking states (TileStates, 711) | wall, adv | W07 | none beyond service name | pending counts come from bookings, which are never shared. The network tile must not show a pending chip or "x pending" (Q9) | M |
| Wall board: tool offline (BoardDown, 745) | wall, adv | W06 | last-known figures, "Tool offline since 14:02" | last-known is in memory only, keyed by scope, wiped on unpair, scope change or sign-out. A 401 or revoked device is not "offline" (section 8) | H |
| Wall board: system surge (BoardSurge, 804) | wall, adv | W07 | "All 9 services are limited..." (count) | count is computed within the scope shown; label says which. Net | M |
| Wall board: overnight (BoardQuiet, 863) | wall, adv | W07 | "Reopens 08:00", clock and date | time zone from tenant config (default Europe/London, `domain-rules.md:7`). Net | L |
| Wall screen pairing: 3 panels (ScreenPairing, 1957) | wall, lead | W08 | code "482 913", screen name, location, "diucs.example/screen" and "/admin" | tenant bound at claim by the claiming admin's token; code namespace is global so claim needs a confirm step; add list, unpair, which-board control. See sections 3, 8 | H |
| Capacity request by text and link page: 3 panels (Reporter, 920) | rep, link | W04 (+ backend L01) | service name, unit phrase, usual range, sender `07700 900123` in the phone mock (927 and nine more) | link route ignores any staff session, never reads `diucs_session`, never forwards a session token, uses its own CSRF cookie or the backend's HMAC `csrfToken` (L01). Tenant resolved by the backend from the token hash. Reporters see their own tenant only (DEC-132 item 5): no network variant | H |
| Reporter edge cases (Reporter2, 954) | rep, link | W04 | texts from backend; "Send me a new link" | renew answers 202 for unknown tokens too (L01); same page for unknown and expired | M |
| Reporter first report (ReporterFirst, 993) | rep, link | W04 | service name | none beyond W04 | L |
| Capacity request by email: 3 panels (EmailCapacity, 1020) | rep, link | W04 + email adapter | "capacity@diucs.example" (1042), "Replies to this address are not read" | sender identity per tenant (DEC-131 item 1); preview text must come from the backend, not be composed in the front end | M |
| Booking: service reply and advisor card states (Booking, 1069) | rep, adv | W19, W20 | reference, service name, SMS text, "SystmOne" | tenant scoped; card states have no network variant. Net rows in the options list have no Request booking | H |
| Booking request by text, 3 panels (BookingSms, 1114) | rep, link | W19 | link `diucs.example/b4821` (reference in the URL, 1123) | the link token, not the reference, must be the secret; never build a URL from a reference. Tenant from the number or the token | M |
| Booking request by email, 3 panels (BookingEmail, 1148) | link | W19 | `[SPOA phone number]` (1200), sender | phone display from tenant config, replacing env `SPOA_PHONE_DISPLAY` (`W19.md:50`, `W22.md:50`) | M |
| Booking exceptions, 7 panels (BookingExceptions, 1203) | link, adv | W21, W22 | `[SPOA phone number]` (1235) | same; change token resolves the tenant | M |

### 2c. Advisor, clinical, shift lead

| Screen (artboard, line) | Roles | Task | Tenant-specific content | Change for tenancy | Risk |
|---|---|---|---|---|---|
| Advisor sign in and home (AdvisorStart, 1279) | adv, lead | W09, W10 | "Use your Trust staff account" (1285), "Sign in with your Trust account" (1286), counts, "Open the wall board view" | wording from config (not every tenant is a Trust); tenant mapped after Entra sign-in with no picker; home shows tenant name; Net: scope switch on "Board right now" and the board link | M |
| Advisor live call: needs and options (Advisor, 1300) | adv | W10, W11, W13 | postcode field, options, "SystmOne" | `[ref]` routes tenant scoped (404 across tenants). Net: option rows from other members are read-only, labelled with the organisation, no Request booking or I phoned | H |
| Advisor on phone (AdvisorPhone, 1395) | adv | W13, W14 | criteria text, version, owner role | as above. Criteria of a network row: Q10 | M |
| Score pickers (AdvisorScores, 1437) | adv | W12 | NHS Pathways Dx list | shared reference data (DEC-130 item 5), read-only; no tenancy change. BFF terminology route needs a tenant-bound token only because every call has one | L |
| Action dialogs (AdvisorActions, 1479) | adv | W14, W16, W45 | "2 clinical advisors available" (1510), local protocol text (1521) | availability count is tenant scoped (Q6); "local protocol" text is tenant config; I phoned and They declined never offered on network rows | M |
| Criteria, outcome, summary, call closed (AdvisorFinish, 1524) | adv | W14, W15 | "Summary for SystmOne" (1552), retention "for IG to set" (1583) | EPR name from config; outcome destination on a network row stores a copy of name and organisation (no cross-scope relationship, DEC-132 item 4), Q11 | M |
| Advisor step by step (AdvisorSteps, 1585) | adv | W09, W10, W13, W15 | URL bars show `diucs.example/admin` | none | L |
| Clinical advisor, 7 panels (ClinicalAdvisor, 1669) | clin | W09, W44, W45 | "Trust staff account" (1676), lock-screen alert (1693), counts | tenant scoped queue and presence; push carries urgency and age band only. Cases are never shared (DEC-132 item 4), so no network variant | H |
| Shift lead: who needs chasing (ShiftLead, 1748) | lead | W17 | ladder, "System now" counts, "9 services reporting today", criteria to review | chasing is own tenant by definition (own reporters). "System now" gains a scope tab; chasing and covering never show network rows. Net | M |
| Shift lead admin flows (ShiftLeadFlows, 1795) | lead | W18, W29/W31, W47 | reporter number, criteria change, audit replay, add reporter | all tenant scoped. Replay is read-only and audited | M |
| Shift lead on phone (ShiftLeadPhone, 1853) | lead | W18, W47 | same | same | M |
| Invite and track a reporter (ShiftLeadInvite, 1913) | lead | W43 | text preview with `diucs.example/i/…` (1929) | preview text returned by the backend, not composed in the browser (domain and sender are tenant config) | M |

### 2d. Registration, onboarding, reporter app, exec, other

| Screen (artboard, line) | Roles | Task | Tenant-specific content | Change for tenancy | Risk |
|---|---|---|---|---|---|
| Register: sign in to location, 4 panels (RegisterFlow1, 1985) | app | W23, W54, W24 | "SPOA shift lead", ODS code, address lookup | tenant is the invitation's tenant (`/register?invite=<token>`, `W23.md:49`); the code verify sends the invite, not just the phone | H |
| Register: service to review, 4 panels (RegisterFlow2, 2070) | app | W25, W26 | district chips DT1 to DT4 (2128-2131), "01305 123456" example (W25), categories, referral methods incl. "SystmOne" | district chips and examples from tenant config; categories are shared reference data | M |
| Register: approval and my services, 3 panels (RegisterFlow3, 2236) | app, lead | W26, W28, W29 | my services list | list is the person's own tenant | M |
| Registration fields and FHIR (RegisterModel, 2283) | none | not a UI screen | "OS Places" (2325) | none for UI | none |
| Register on mobile, 8 panels (RegisterMobile, 2329) | app | W23 to W27 | as RegisterFlow1/2 | as above | M |
| Approval: applicant, 8 panels (ApprovalApplicant, 2569) | app | W54, W27 | "SPOA shift lead", masked phone | tenant bound by the invitation | M |
| Approval: reviewer part 1 (ApprovalWeb1, 2650) | lead | W28, W29 | scope list incl. "Not on the Dorset pathway" (2671), "Address found, in Dorset" (2697), "Dorset directory" (2715) | pathway, region and directory names from config; scope list per tenant | M |
| Approval: reviewer part 2 (ApprovalWeb2, 2736) | lead, clin | W29, W31 | "Dorset urgent care pathway" (2743), "SPOA clinical lead" (2782) | role and pathway names from config | M |
| Approval: reviewer on phone (ApprovalPhone, 2815) | lead | W28, W29 | "in Dorset" (2835) | same | M |
| Approval states (ApprovalStates, 2877) | none | table, W27 | `[period]`, `[time]` targets | per-tenant policy values (Q8) | L |
| Criteria owner: 10 panels (CriteriaOwner, 2911) | own, clin | W30, W31 | districts DT1 to DT4, owner roles | districts from config. Criteria version projected to the network (read only) | M |
| Reporter set-up steps 1 to 6 (OnboardReporter1, 3033) | rep, exec | W33 | invitation text with `diucs.example/i/Qx82` (3042), "SPOA shift lead" | `/i/<token>` resolves the tenant; set-up shows the tenant name so a person in two tenants sees which | H |
| Reporter set-up steps 7 to 12 (OnboardReporter2, 3113) | rep | W34 | "Capacity requests and booking requests for UCR West", PIN rules, notification prompt for `diucs.example` (3136) | push subscription and PIN bound to (tenant, device); consent wording version | H |
| Reporter app: daily use, 7 panels (ReporterApp1, 3185) | rep | W35, W36 | service names, `[SPOA phone number]` (3261) | own tenant only (DEC-132 item 5): no network variant | H |
| Reporter app: recovery and settings, 4 panels (ReporterApp2, 3263) | rep | W37 | masked phone, 30-day re-verify | sign-out wipes browser state (section 8) | M |
| One phone, several services, 9 panels (MultiServicePhone, 3306) | rep | W38 | "UCR North has been added" | one tenant per device session (Q5) | H |
| Shift lead: phones and services (MultiServiceAdmin, 3411) | lead | W43 | phone endings, "Holds 4 services" | own tenant | M |
| Safety concern, problem report, session sharing, 5 panels (SafetyConcern, 3444) | all staff | W46, W56 | "clinical safety officer", `SC-0192` numbering, `[SPOA phone number]` (3479), support code `K7R4-92QX` | CSO contact and numbering per tenant; support-sharing flag is tenant config, not `NEXT_PUBLIC_*` (`W46.md:49`); "who opened your session" shows the actor's role and organisation | M |
| Suspend, remove, lost phone, flagged reports, 8 panels (SuspendLeaver, 3509) | lead, rep | W42, W55 | service names, phone endings | tenant scoped; lost-phone is a no-session screen so the number lookup must not reveal tenants | M |
| COO and ICB app: home, service, week, alerts, 4 panels (ExecApp1, 3603) | exec | W40, W41 | "Dorset system" (3608), counts, `[x]` minutes, "3 of 9" | heading from config; `minutesPerCall` per tenant. Net: home, pressure, service detail, alerts, week | M |
| COO and ICB app: set-up, alerts, escalation, 6 panels (ExecApp2, 3676) | exec | W33, W39, W40 | "Dorset urgent care capacity" in the invitation (3685), "5 or more services" (3711), "[Deputy role]" | thresholds and names from config. Alert scope (own or network) is Q12 | M |
| Planning view (PlanningView, 3755) | lead, own, exec | W51 | decision-log counts, "Groups under 10 are hidden" (3770) | tenant scoped; the decision log is never shared, so no network variant. Suppression threshold per tenant | M |
| Map: advisor on web, 4 panels (MapWeb, 3852) | adv | W50 | "Outside Dorset" (3903), DT districts (3894-3899), "licensed tiles" | region name from config. Net: pins for network services, each labelled with its organisation | M |
| Map: advisor on phone, 4 panels (MapPhone, 3912) | adv | W50 | DT districts (3963-3966) | same | M |
| Support and insight console A, 4 panels (ConsoleA, 3973) | sup | W48, W49 | session ids, element ids | cross-tenant privilege (DEC-130 item 8): no role holds it today. See section 4 | H |
| Support and insight console B, 4 panels (ConsoleB, 4086) | sup, product | W49 | queues and topics (`inbound.replies`, `booking.events`, 4169-4171) | platform-level queue counts are not tenant data; tenant insight is scoped. Section 4 | H |
| Product tour, 6 panels (TourPhone1, 4174) | all | W52 | "SPOA advisor", "Phone the SPOA shift lead" | roles and names from config; `localStorage` keys per user | L |
| Tour by role, 4 panels (TourRoles, 4248) | all | W52 | "SystmOne" (4262) | EPR name from config | L |
| Training and help, 5 panels (TrainingPhone, 4306) | all | W53 | "Ask your champion, [Name]", "[x] minutes" | per tenant champion and baseline; progress key per user | L |
| Selling the value (ValueCase, 4369) | none | not a screen; targets `[to agree]` | none | none | none |

### 2e. DEC-132 network variants (14 existing screens or screen groups)

Rule for every variant: same layout and same components as the tenant view; the only differences are the scope header (2g), an organisation label on every row, the removal of everything that is private to a tenant (pending counts, bookings, reporter contact, case data, audit), and no write action. Anything the allowlist in DEC-132 item 4 does not list is absent from the network view.

| Existing screen | Network variant | What is removed or restricted |
|---|---|---|
| Wall board (Main 654), W05 | board of all member services in the network scope; admin-selected per screen | no pending chip; no booking state; shows organisation under each service name |
| TileStates (711), W07 | none for pending (bookings never shared) | whole artboard does not apply to the network |
| BoardDown (745), W06 | Last known for the network board, keyed by scope | stale network figures say "Last known" with the same words |
| BoardSurge (804), W07 | "System under pressure" computed over the network's in-hours services | label names the scope; count text says "network" |
| BoardQuiet (863), W07 | out of hours per member service hours (projected opening hours) | none |
| Advisor home counts and board link (AdvisorStart 1279, W10) | tab or link "Network" beside "Our organisation" for the five counts; `/advisor/board` and `/network/board` | counts cover the scope shown |
| Options list and not-suitable list (Advisor 1300, W13), search | read-only rows for other members' services that meet criteria, labelled by organisation; sorted by travel time like the rest | no Request booking, no I phoned, no They declined, no clinical escalation per row. Phone number of the service-level contact only (allowlist). Q9, Q10, Q11 |
| Booking lists and booking card (Booking 1069, W20) | no network variant | bookings are never shared. A booking can only be made with a tenant service |
| Map and travel details (MapWeb 3852, MapPhone 3912, W50) | network pins and coverage areas, organisation in the pin card | patient postcode centre stays tenant side |
| Shift lead "System now" (ShiftLead 1748, W17) | scope tab on the counts only | chasing, covering, criteria, declined-despite-capacity stay own tenant |
| COO and ICB home, pressure chip, needs attention (ExecApp1 3603, W40) | network heading `{Network name}`; rows labelled by organisation | none beyond the allowlist |
| COO and ICB service detail (ExecApp1 3629, W40) | read-only detail of a member's service | "Reported by: Text, duty coordinator" (reporter data) and "Call the duty coordinator" are removed; service-level contact only |
| COO and ICB alerts (ExecApp2 3700-3718, W39/W40) | alerts about network services only if the owner rules so (Q12) | until then, own tenant only |
| Week summary (ExecApp1 3644, W41) | capacity-derived measures only (on-time updates, status counts) | referrals, best-fit-unavailable and time to confirmed booking come from the decision log and bookings, which are never shared; owner to define the network measures (Q13). Suppress counts under 10 within the scope |
| Criteria dialog (AdvisorFinish 1528, W14) | read-only view of a member service's current criteria version (content only if the criteria scope covers it, Q10) | "Report a problem with these criteria" goes to the service's own tenant owner, which the advisor cannot message; hide it |

Planning view (PlanningView 3755), registration, criteria editing, reporter app, link pages, clinical screens, help, tour, learn and the support console have **no** network variant.

### 2f. Screens named in prompts but not in the spec

`/forbidden` ("You do not have access to this page.", `W09.md:51`); `/offline` (`W32.md:51`); `/setup/done` (W33); "This invitation has expired" (`W33.md:49`); "Waiting for a call-back" (SuspendLeaver 5); `/help` hub (from SafetyConcern 1, W46). Default Next.js `not-found`, `error` and `global-error` pages are not planned by any task; they must be fixed text and tenant neutral (an error page must never echo a path, id or tenant). Two artboards named in prompts do not exist in the snapshot: `AdvisorDialogsPhone` (W14, W16, W45) and `AdvisorFinishPhone` (W15) (checked: zero matches in `ui-screens.md`). Not a tenancy issue, but a DEC-129 canvas difference to record.

### 2g. New screens needed by tenancy and DEC-132

| ID | Screen | Roles | Why |
|---|---|---|---|
| N1 | Network administration: members (name, status, joined, left), add and end membership, agreement reference and version (the reference only, never the content), grants overview (grantor, scope, purpose, dates, approval state, version), owner approval, history | network owner administrator | DEC-132 items 2, 3 |
| N2 | Grant approval and sharing transparency, for a member's administrator: pending grants with the exact list of fields shared (rendered from the allowlist, not typed), approve, decline, end a grant, "what stays after you end this" (history stays, no new data is shared), who the data is shared with since when | tenant administrator | DEC-132 items 3, 6 |
| N3 | Network capacity view: board grid and list, organisation filter chips, scope header | member staff (adv, lead, exec, own where the role may see the board) | DEC-132 item 5 |
| N4 | Wall screens list: name, where, status, last seen, which board (tenant or network), unpair, re-pair, change board | tenant administrator | DEC-132 item 5; DEC-130; W08 has no list or revoke (`W08.md:73`) |
| N5 | Network unavailable states: not a member, grant ended, network paused, member left (history only) | member staff, wall | DEC-132 items 3, 6 |
| N6 | Staff sign-in failures: no organisation, more than one organisation, organisation suspended, account from the wrong directory | staff | DEC-130 item 6 |
| N7 | "This phone is already set up for another organisation" (if Q5 rules one tenant per device) | rep, exec | DEC-131 item 3, DEC-130 |
| N8 | Support console elevation start, persistent support-mode banner, end elevation, and a tenant-side "who accessed my organisation" view | sup, tenant administrator | DEC-130 item 8 (section 4) |
| N9 | Tenant lifecycle (create, suspend, offboard, configure name, area name, phone, policy) | platform operator | not in any plan; owner to say whether this is UI or operator tooling (Q14) |

---

## 3. Where the tenant comes from in the UI

### 3.1 Per actor

| Actor | Verified source of the tenant | Where it is bound | What the browser holds | Gap in the plan |
|---|---|---|---|---|
| Staff sign-in, Entra ID (W09) | the verified Entra id token (`iss`, `tid`, `oid`) mapped by the back end identity adapter to exactly one tenant. Fail closed on none or several (N6) | a `tenant` claim in the signed back-end token, sealed inside `diucs_session` | the sealed cookie only; display name and area name from the session response | `W09.md:47` uses one `ENTRA_TENANT_ID` (name collision with DIUCS tenant; rename `entraDirectoryId`). `W09.md:49`: the BFF itself mints the back-end token (HS256, `BACKEND_JWT_SECRET`), so the BFF can mint any tenant. `W09.md:48`: Entra app role `DIUCS.Support` maps to `support`: in a multi-directory setup a customer's directory admin could grant it. Restrict `support` to the platform directory only. `W09.md:51` names `middleware.ts`; Next 16.3.8 deprecates it for `proxy.ts` (`node_modules/next/dist/docs/01-app/02-guides/upgrading/version-16.md:614`) |
| Link pages (W04, W19, W22) | the link token (at least 128 bits, hash stored, `architecture.md` Link tokens). The back end resolves the tenant from the hash. Under DEC-130 item 7 the hash lookup is a global statement and must be on the allowlist | back end only. The BFF holds no tenant | page display fields from the link response; no cookie carrying tenant | `W04.md:48` has the page issue the `diucs_csrf` cookie. That cookie is the same name as the staff CSRF cookie, so opening a link in a browser with a staff session rotates the staff CSRF token and the staff user's next POST fails with `csrf`. L01 already returns a token-bound `csrfToken` (HMAC of the token hash); W04 and L01 disagree on the mechanism. Link routes need their own wrapper (`withLink`) that ignores `diucs_session` |
| Reporter text code and PIN (W23, W33 to W37, W55) | the invitation token (`/i/<token>`, `W33.md:49`) gives the tenant and the service; the code is sent on that tenant's number (DEC-131 item 5) | a `reporter` session with `tenant` and `device` | sealed cookie; masked phone only | `W23.md:49` verifies `{phone, code}` with no invitation or tenant reference: a phone that is a reporter in two tenants (DEC-131 item 3) is ambiguous. Verify must carry the invite or a pre-auth cookie naming the invitation |
| Applicant (W23, W54) | the invitation | registration session role `reporter`, `services: []` | sealed cookie | tenant must be in the session from the first verify |
| Exec (W33, W39) | invitation, same path as reporter | session role `exec` | sealed cookie | none beyond the above. Network access is not a session property (3.3) |
| Wall screen (W08) | the claiming administrator's tenant, at claim time. The device never chooses | wall session `{role: "wall", sub: deviceId, device, backendToken: deviceToken}` with a tenant claim in the device token; the board choice (tenant or network) is device configuration held server side | sealed cookie. `pairingId` and `screenSecret` in a separate HTTP-only cookie while pairing (`W08.md:48-49`) | pairing code namespace is global; no list, revoke or board control (`W08.md:73`). Section 8 |
| Support (W48, W49, W56) | a platform support identity plus an explicit, audited elevation naming one target tenant | a short-lived elevated session (3.4) | sealed cookie; the support banner (section 4) | no such role may exist until DEC-130 item 8 is closed |
| Browser telemetry (O02) | the server: the telemetry route stamps `tenant.id` from the session. The browser never sends it | the BFF route | nothing | `observability.md:24-34` has no tenant attribute. Link pages have no session, so they need a signed telemetry context (section 6) |
| Push subscription (W34) | the session's tenant at subscribe time | back end record (tenant, device, endpoint) | the browser's own push subscription | must be removed on sign-out, unpair, removal of a person (W42) and tenant change |

### 3.2 The `Session` shape (`lib/auth/session.ts:23-31` on the W02 branch)

Current: `{ role, services, sub, device?, backendToken, expiresAt }`. The unseal function (`:103-113`) rebuilds a session from an explicit allow-list of claims, so a new claim has to be added in three places: the type (`:23-31`), the seal claims (`:69-76`) and the unseal destructure (`:103-113`). Unseal must return null when `tenantId` is missing (fail closed, same pattern as `:105-107`).

Proposed:

```ts
type Session = {
  role: Role;
  tenantId: string;              // sealed only; from the verified source; same value as the claim in backendToken
  services: string[];            // service ids inside the tenant. For staff, the back end's "all services of this tenant" marker, never a global wildcard (W09.md:49, R02)
  sub: string;
  device?: string;
  backendToken: string;          // carries tenant (and nothing about network membership)
  expiresAt: string;
  elevation?: { id: string; targetTenantId: string; ticket: string; expiresAt: string }; // support only, section 4
};
```

Browser-visible response of `GET /api/bff/session` (`route.ts:14-17`, currently `{role, services, sub, csrfToken}`): add `tenant: { displayName, areaName }` and `network: { name, available: boolean } | null`. Do not return `tenantId` (it is not a secret, but nothing in the browser needs it; telemetry is stamped on the server). `sub` is returned today (`route.ts:15`) and for staff will be the Entra object id: consider dropping it from the browser response; `observability.md:17` says the telemetry store never holds a person link. Existing tests that pin the body with `toEqual` must change: `route.test.ts:52-58`; round trip `session.test.ts:65`.

Network availability is not stored in the cookie. A grant can end at any time (DEC-132 item 3) and the cookie has no server-side revocation (DEC-125 item 10, residual), so a cached "member" flag would outlive the grant. Each network page and each network BFF route asks the back end, which checks membership and the grant on every call (DEC-132 item 4). The BFF may cache the answer in memory for a few seconds, keyed by tenant and role, never longer.

### 3.3 Scope is a route, not a parameter

The viewer chooses a scope by following a link to a different route family: tenant pages as planned; network pages under `/network/...` (`/network/board`, `/network/services`, `/network/week`), served by `/api/bff/network/*` BFF routes. The BFF never reads a `scope`, `tenant`, `network` or `source` value from a query string or body to decide what to fetch. The back-end token never changes between scopes; the back end binds the scope from the route it is called on (DEC-132 item 4: one unit of work binds one scope). A route family per scope gives separate HTTP cache keys, separate telemetry route templates and an unmistakable URL.

### 3.4 What the browser may and may not hold

May hold: tenant display name, area name, network name, support phone display text, role, service names the viewer may see, CSRF token, an opaque telemetry context, user interface state (current tab, filters).

Must not hold: the back-end token; `tenantId` in any readable cookie, `localStorage`, URL or DOM attribute; a network membership or grant flag; a scope preference that any code later trusts for authorization; any other tenant's name; a list of tenants; source tenant ids from projections (rows show organisation display names only; `sourceTenantId` is never rendered or sent to the browser).

### 3.5 The cookie must NOT contain

In `diucs_session` (encrypted, so contents are not readable, but still): no network membership, grants, scope choice, permissions list, or display text (stale after a config change; 4 KB limit). In any cookie the page script can read, including `diucs_csrf`: no tenant id, no tenant name, no role. No second plaintext cookie such as `diucs_tenant`: if one existed, code would eventually trust it. The pairing cookie (`W08.md:48`) must not contain the tenant either; it holds `pairingId` and `screenSecret` only.

### 3.6 CSRF and the tenant

`lib/auth/csrf.ts:14-22` issues 32 random bytes with no binding; `:34-40` checks header equals cookie. This is plain double-submit: a sibling subdomain or any script able to set a cookie on the origin can supply a matching pair. Recommended: derive the token as an HMAC over (session id or `sub`, `tenantId`, a random nonce) with a key derived from `SESSION_SECRET`, send `nonce.mac`, and verify against the live session in `withBff` (it already has the session by then, `handler.ts:36`). A token issued for tenant A then fails in a session for tenant B, and a token from the support elevation does not work in a normal session. For link pages use the back end's token-bound `csrfToken` (L01) and a distinct cookie name or path (`diucs_link_csrf`, `Path=/l`); never touch `diucs_csrf` there. Constant-time comparison (`csrf.ts:29-40`) stays.

### 3.7 How the BFF forwards the tenant

Only by the signed back-end token in `Authorization: Bearer` (`lib/fhir/client.ts:77`). Today `fhirFetch` builds its own headers and sends nothing the caller controls except those it is given; keep that: add a guard test that no `X-Tenant*`, `tenant` query or body key is ever sent, and that a browser header or query named `tenant`, `x-tenant-id`, `scope`, `network` is rejected with 400 by `withBff`. Anonymous link calls send no `Authorization`; the back end resolves the tenant from the token. The only code that may add a tenant claim is the token issuer; recommended (Q1): a back-end token exchange (BFF presents the verified Entra identity or the verified device and invitation proof, the back end looks up the tenant and signs), so the BFF holds no key able to name a tenant. If the BFF must keep signing (W09 as written), it signs only after a tenant lookup from the back-end identity adapter and never from a request value.

---

## 4. Tenant selection and switching

Recommendation: nobody chooses a tenant in the UI. One tenant per user and per device. There is no tenant switcher, no `?tenant=` and no organisation drop-down anywhere, except the support console. The only choice a viewer has is the DEC-132 scope (own organisation or network), and it is a navigation choice between two fixed routes, not a tenant selection.

| Case | Behaviour |
|---|---|
| Staff user mapped to two tenants (a data error, or a person with two accounts in different directories) | fail closed at sign-in with N6 "Your account is linked to more than one organisation. Ask your administrator." No session is created. No chooser. The attempt is logged by id only. A person who legitimately works for two organisations has two accounts; "switch" means sign out (which wipes the browser, section 8) and sign in again |
| Reporter phone in two tenants | two Person records (DEC-131 item 3). SMS and links already route correctly by number and token. The installed app is one device session per origin: either one tenant per phone with N7, or per-tenant origins (Q2, Q5) |
| Wall screen paired to one tenant | the device token carries that tenant. Showing the network board is a setting held on the server for that device and changed only by that tenant's administrator (N4); it never changes the tenant. To move the screen to another tenant: unpair, wipe, pair again |
| Link opened by someone signed in to another tenant | the link page and its routes ignore the staff session completely. The page shows the link's own service name and no tenant chrome from the signed-in user. The staff session and its CSRF cookie are untouched. Test: open tenant A's link in a tenant B session; the page is A's, the B session still works afterwards |
| Staff of a member tenant | see two scopes (own, network) as two tabs or links; the own scope is the default everywhere; the network view is read only |

### Support console: explicit, audited cross-tenant mode

DEC-130 item 8 and DEC-132 item 8: no role holds it yet. The console (W48, W49, `observability.md:157-175`) cannot be built as planned until the owner says who. When decided, the UI is:

| Screen | Must display |
|---|---|
| E1 Start elevation | choose one target tenant from a list the operator is entitled to, a ticket number, a reason (fixed list plus short note), duration; a statement that every view is logged and shown to the tenant. No silent default tenant. Approval by a lead of the target tenant where the person's session is to be opened (`observability.md:162`) |
| E2 Persistent support banner on every console and on any tenant page opened in elevation | "Support mode" (word plus shape plus the amber-tint panel tokens, no new colours), `Viewing: {tenant display name}`, the ticket, time left, button "Exit support mode". Cannot be dismissed. In the page title. Included in every export header and file name |
| E3 Find a session (ConsoleA 3978) | scoped to the elevated tenant. A support code resolves to one session in one tenant; display that tenant. Search never spans tenants |
| E4 Session timeline (3 of ConsoleA) | header "Session s-7f3a · {tenant} · Advisor ..." |
| E5 Trace (4 of ConsoleA) | tenant in the header; spans never contain tenant data values |
| E6 Funnels, paths, friction, performance (ConsoleA 4, ConsoleB 5 to 7) | tenant aggregates for the elevated tenant. A platform-wide aggregate is a separate privilege and a separate screen with its own banner ("All organisations"); no ranking of tenants (design-system section 13) |
| E7 Releases and pipeline (ConsoleB 8) | platform level counts (queue depth, dead letters), not tenant data. Message content is never shown |
| E8 Person-side "Who has opened your session" (SafetyConcern 5, W56) | shows the actor's role and organisation ("Support, platform operator" or "Lead, your organisation") |
| E9 Tenant-side "who accessed my organisation" | read only list for the tenant administrator: time, actor role, ticket, scope, duration |

Switching tenant inside the console is not a drop-down: it ends the elevation and starts a new one (new reason, new audit record). The network owner is not a support actor: being the network owner gives no console access to members (DEC-132 item 2).

---

## 5. Tenant-specific content and branding

### 5.1 Configuration versus fixed

| Item | Class | Source |
|---|---|---|
| Product name | platform constant. Conflict: DEC-014 item 5 and `design-system.md:196` say "Community Overwatch"; F03, F09 and every prompt say "DIUCS capacity" (`app/layout.tsx:14`, `page.tsx` wall `:10`, `e2e/smoke.spec.ts:8-10`, `W32.md:47` manifest). Owner to pick one (Q7) | one constant `PRODUCT_NAME` |
| Tenant legal name and display name | tenant config | profile |
| Area name for headings (`{Area name} capacity`, `design-system.md:199`) | tenant config | profile |
| Network name (heading of the network view) | network config | network record |
| Logo | optional tenant config, our own origin only (CSP `img-src 'self' data:`, S01), with alt text, header only, never in the tile grid. Owner decision (Q7) | asset store |
| Colours | **fixed**. 13 colour tokens pinned by `tokens.test.ts` and `styles.test.ts` (no hex in component CSS). No per-tenant colour, no per-tenant font. Status colours, shapes and words are fixed (design-system section 6, 13) | `app/tokens.css:5-17` |
| DEC-019 values | **fixed**: `--dur-sheet` 280 ms (`tokens.css:72`), `--type-caption-size` 16 px (`:63`), reduced motion keeps opacity (`:85-93`). A tenant cannot change motion, spacing or type | tokens |
| Support and SPOA phone display | tenant config (replaces env `SPOA_PHONE_DISPLAY`, `W19.md:50`, `W22.md:50`; and `[SPOA phone number]` at ui-screens 1200, 1235, 3261, 3479, `W32.md:51`, W36, W46) | profile |
| "SPOA" / "Single point of access" naming | tenant config (`spoaName`, 63 mentions in the spec) | profile |
| "Trust account" wording | tenant config (`staffAccountName`, 17 mentions, 1285-1286, 1592-1593, 1676-1678, 3759) | profile |
| EPR name ("SystmOne", 26 mentions; W15 `SummaryCopy`; referral methods in W25) | tenant config list | profile |
| Region and pathway names ("Dorset", 12 mentions; `W05.md:51`, `W29.md:49`, `W40.md:49`; D16 template I2; W29) | tenant config | profile |
| Postcode districts (DT1 to DT4 chips, 35 mentions; W25, W30, W50) | tenant config | profile |
| Time zone and locale (`layout.tsx:20` `en-GB`; London time in `W05` `londonTime`) | tenant config with default Europe/London and en-GB. Low risk (NHS tenants share it) | profile |
| Sender number and sender identity, link domain (`diucs.example`, 59 mentions; `07700 900123`, 10 mentions) | tenant config (DEC-131). The front end never composes SMS or email text; it asks the back end for previews | backend |
| Policy values shown in copy: 5 and 10 minute booking timers, 10 minute clinical timer, 48 h invitation, 30 day re-verify, 5 wrong tries, "5 or more services" pressure, "more than 3 services" per phone, "under 10" suppression, 2 or 4 hour not-updated alerts, `minutesPerCall` | fixed platform constants unless the owner lets them vary (Q8). Copy must take them as parameters either way (`TenantPolicy`), never literals |
| Fixed vocabulary: statuses, categories, needs, age bands, urgency, score methods, outcome codes | shared reference data (DEC-130 item 5), identical for every tenant |
| Safety officer contact, concern numbering (`SC-0192`) | tenant config |
| Champion `[Name]`, deputy role `[Deputy role]`, expected times `[time]`, `[period]` | tenant config or per-record |

### 5.2 Rules that must not change

All of `design-system.md` section 2 colour rules (`:41-44`), section 3 type, section 5 motion with DEC-019 values, section 6 status (word, shape, colour), section 8 voice, section 13 ("no ranking of services or staff"). Corollary for DEC-132: the network view is a list of facts with organisation labels; it must not sort or colour organisations as better or worse, and must keep "Sorted by travel time. Not ranked." (1347).

### 5.3 Screen text that names a specific organisation

`ui-screens.md`: "Dorset urgent care capacity" 657, 748, 807, 866; "Dorset pathway" 2671, 2743; "in Dorset" 2697, 2835; "Dorset directory" 2715; "Dorset system" 3608; invitation text 3685; "Outside Dorset" 3903. "Trust" 219, 271, 1285, 1286, 1588, 1592, 1593, 1676, 1678, 2325, 3759. "DT1 to DT4" throughout. Prompts: `W05.md:51`, `W29.md:49`, `W40.md:49`, `D16.md:59` (template I2), plus "in Dorset" in the preamble of all 215 prompts. `design-system.md` line 198-201 already prescribes the replacements for the headings; the prompts contradict it.

### 5.4 DEC-132 wording

The network view heading uses the network name; every row shows the organisation display name; the viewer's own rows carry the words "Your organisation". New copy is needed for the N1 to N5 screens; it must follow design-system section 8 (plain words, say what happens next, no urgency theatre). Example needed phrases: "Showing: Our organisation" and "Showing: Network, {name}"; "Shared by {organisation}"; "Read only. You cannot book or change this service from here."; "Network view not available. Ask your administrator."

---

## 6. Browser telemetry (O02) and element ids

Spec anchors: `observability.md:24-34` attributes, `:67-70` rules, `:140-155` privacy, `:171-175` access.

| Point | Recommendation |
|---|---|
| `tenant.id` | add to "Attributes on every event and span". Opaque, random, non-semantic id (for example `t_` plus 12 base32 characters), never a name, ODS code, area name or domain. Stamped **on the server**: `/api/bff/telemetry` (O02, `O02.md:56`) takes `tenant.id` from the session, ignores and strips any `tenant.id` the batch carries (add to the allow-list test, `O02.md` test 7). The browser never receives or sends it |
| Anonymous link pages | no session, so no server stamp. The page render issues a signed opaque telemetry context (tenant id, role `anonymous-link`, expiry, signed with a key only the BFF holds); the browser echoes it in the beacon; the route verifies the signature and stamps. The browser cannot choose it |
| Scope | add `view.scope` (enum `tenant`, `network`). The route templates differ anyway (`/network/...`). Add `network.id` (opaque) only on events from network routes. Never a member's `sourceTenantId` in any event |
| `service.id` | tenant-scoped (and network-projection ids are a different id space). Always read together with `tenant.id` and `view.scope`. Pattern in O05 (`^[A-Za-z0-9\-]{1,64}$`, `O05.md:46`) stays |
| Element ids | tenant neutral and upper-case. Two planned ids embed a dynamic service id: `REP-MULTI-STILLRIGHT-<ID>` and `REP-MULTI-CHANGE-<ID>` (`W38.md:55`), `ADV-MAP-PIN-<SERVICEID>` (`W50.md:56`). They break O05's pattern for lower-case ids, make cardinality unbounded and carry tenant data in an id. Use positional ids (`-1`, `-2`) and put the service in `service.id` |
| Network variants | same element ids with the same area prefix; `view.scope` separates them in friction and funnels. Do not invent `NET-` copies of every id |
| Metrics | the spec says ids never go on metric labels (`:68`). Tenants are few, so `tenant.id` is bounded; decide (Q15): either allow it on a short list of metrics (latency, error rate) with a cap on tenant count, or keep it off metrics and break down by tenant from spans and events only. Recommended: spans and events only, plus tenant on the two or three SLO metrics |
| Collector allow-list (O04) | add `tenant.id`, `view.scope`, `network.id`; anything else is dropped |
| Aggregates | "groups under 10 hidden" (`:150`) applies **per tenant and per scope**, and for any network aggregate a second time within the network |
| Network owner | gets no telemetry about members' staff or sessions. Insight is tenant scoped; a network-wide insight screen would need its own grant scope |
| Support actions | everything in the console is itself instrumented (`:175`): events carry the actor's role, the target `tenant.id`, the elevation id (opaque) |
| Privacy | unchanged: no field values, no page text, no tenant or organisation names, no phone numbers. `O05` schema scan: add a pattern for `tenant.id` and enums for `view.scope`; keep `isFreeText` false for all |
| `session.id` | stays random and per tab in `sessionStorage` (`O02.md:47`); its link to a person (identity adapter, `observability.md:146`) must be tenant scoped and expire |
| `ui.sse` | add scope so a stream gap on the network board is distinguishable |
| Role values | `observability.md:27` lists 8 roles; add `support`, `audit`, and whatever DEC-132 roles the owner defines |

---

## 7. Frontend tests and fixtures

### 7.1 What is there today

| File | Assumption | Change |
|---|---|---|
| `frontend/test/setup.ts:12-19` | one global MSW server, `onUnhandledRequest: 'error'`, default `handlers` | keep; add per-test tenant context reset and a leak canary (7.3) |
| `frontend/test/msw/handlers/index.ts:5` | empty array | planned handlers must be built as per-tenant factories |
| `frontend/test/msw/server.ts` | one server | keep |
| `frontend/test/msw/server.test.ts` | unhandled request fails | keep |
| `frontend/vitest.config.ts:14-16` | one environment, includes all tests | keep; node-environment tests are marked per file (DEC-125 item 1) |
| `frontend/playwright.config.ts:12,21-26` | one `baseURL`, one project, `pnpm dev` | one project per tenant with its own `storageState`; a third project for a non-member tenant |
| `frontend/e2e/smoke.spec.ts:7-10` | page title and heading "DIUCS capacity wall screen" | move to the product constant and tenant profile |
| `frontend/app/(wall)/screen/page.test.tsx:10-15` | literal heading and the no-patient line | replaced when W05 lands; use the profile |
| `frontend/app/layout.test.tsx:17-19` | `lang` is `en-GB` | read from profile default; keep a test that the default is `en-GB` |
| `frontend/app/tokens.test.ts`, `components/ui/styles.test.ts` | colour set pinned; no hex in component CSS | **keep unchanged**: they are the guard against per-tenant theming. Add one test that no CSS sets a `--c-*` custom property outside `tokens.css` |
| `frontend/components/ui/*.test.tsx` (7) | presentational, tenant free | none |
| `frontend/lib/fhir/client.test.ts`, `client.guards.test.ts`, `client.absence.test.ts` | headers asserted individually (`guards.test.ts:73-84` Authorization omitted when no token) | add: no tenant header or query ever sent; `cache: 'no-store'` set; token required for every non-link call |
| `frontend/lib/bff/errors.test.ts`, `errors.guards.test.ts` | fixed table 403 "You cannot do that." and 404 "We could not find that." (`errors.ts:128-138`) | add: a cross-tenant back-end answer is presented as the 404 text so existence is not revealed |
| W02 branch `frontend/test/cookies.ts:15-24` | `fakeCookieStore.get` always returns undefined; fixed `TEST_SESSION_SECRET` (`:50`) | the fake must support get; add `requestAs(tenant, role)` helper |
| W02 `lib/auth/session.test.ts:40-43`, `lib/bff/handler.test.ts:17-22`, `app/api/bff/session/route.test.ts:25-29,52-58` | sample sessions have no tenant; response body pinned | add tenant to samples; add "unseal without tenant returns null" |
| W02 `lib/auth/csrf.test.ts` | random unbound token | rewrite for the bound token (3.6) |

### 7.2 Fixtures

`test/tenants.ts` defines at least three scopes: tenant A and tenant B, both members of one network, and tenant C, not a member, plus the network scope. Deliberately **overlapping identifiers**: the same service id (`s1`), the same case reference (`4821`), the same phone ending, the same registration id, in A and B, so a handler that forgets the tenant returns the wrong record instead of a 404. Distinct fictional names (do not reuse the canvas sample "UCR West" for both). One grant active, one ended, one pending. Planned handler files (`board.ts`, `bookings.ts`, `cases.ts`, `links.ts`, `registration.ts`, `registrations.ts`, `screens.ts`) become factories taking the tenant and the scope. Note: W23 names `registration.ts` and W28 names `registrations.ts`; two near-identical file names will collide.

### 7.3 Leak canary and generated tests

An MSW handler placed first in the chain decodes the bearer token on every upstream call and fails the test when (a) the token's tenant is not the session's tenant, (b) any `X-Tenant*` header exists, (c) a link call carries an Authorization header, (d) a network route is called with a token whose tenant is not a member. A generated test iterates every `app/api/bff/**/route.ts` export and, as tenant B holding an id that exists only in tenant A, expects 404 (never 403, never data). A second generated test greps rendered output of every network view for a `sourceTenantId`-shaped value. The existing W47 rule, "No record for that reference" for both not found and not allowed (`W47.md:51`), becomes the rule for every id-scoped route.

### 7.4 End-to-end

New suite `e2e/tenancy/`: staff isolation; link opened in another tenant's session (staff session still works, staff CSRF token not rotated); wall pairing, change of board, grant ended while the network board is showing, unpair; sign-out wipe (service worker, Cache Storage, push, localStorage); network read-only (no Request booking on a network row). O09's synthetic checks (`O09.md:47`) must run in a dedicated `synthetic` tenant, never in a live tenant, and the synthetic tenant must not be a network member.

---

## 8. Wall screen and offline (PWA W32, last-known W06)

### 8.1 What the plan says

W32 (`W32.md:51`): precache only `/offline` and its static assets; never cache `/api/bff/*` or any HTML except `/offline`; `isCacheable` true for `/offline` and `/_next/static/...`. W06 (`W06.md:51-56`): last-known is React state in `LiveBoard`; nothing is persisted; the offline view shows the last good `Board`. `architecture.md:178` says the offline shell does not cache capacity or case data. Good: no capacity is persisted by design. The risks are in the edges.

### 8.2 Exact risks

| # | Risk | Where | Required behaviour |
|---|---|---|---|
| R1 | A revoked or unpaired device is treated as "offline" and keeps showing the last tenant board forever | `W06.md:51-56` has no 401 or 403 handling; `lib/fhir/client.ts` maps 401 to a FhirError like any other | a 401 or a "device revoked" answer clears the in-memory board and the session cookie and returns to `/screen/pair`. Only network failure and 5xx lead to Last known. Test it |
| R2 | Last known is not keyed by scope | `LiveBoard` holds one `Board` | state keyed by scope (`tenant`, `network`). When the administrator changes the screen's board, the old scope's state is dropped, not shown as Last known of the new scope. Never merge the two |
| R3 | A grant ends while the network board is showing | DEC-132 item 3 | the network call returns 403/404: show N5 "Network view not available" with an explicit banner, drop the network figures, and do not silently fall back to the tenant board (the room would think it is looking at the network). Fallback to the tenant board only with a visible scope change |
| R4 | A member leaves; projections stay for history | DEC-132 item 6 | live network board and all counts exclude departed members; history views label them with the leave date. Otherwise a departed member's last figure shows as a current service |
| R5 | Persistence added later "so the wall survives a reload" | BoardDown (745) says figures are Last known; W32 forbids caching them | if ever added, the key is `(tenant, scope)`, written only on a signed-in device, wiped on sign-out, unpair, scope change, 401. Recommended: do not add it. The reload case shows the generic offline page |
| R6 | `/offline` is one precached HTML shared by every tenant, and its text contains a phone number (`W32.md:51`: "phone the SPOA on [SPOA phone number]") | `W32.md:51` | the precached page is tenant neutral ("phone the SPOA" with no number) or reads the number from a store keyed by tenant that is written at sign-in and wiped at sign-out. Never bake a number at build time |
| R7 | One service worker, scope `/`, for the whole origin (wall, admin, console, reporter) | `W32.md:47-54`, `RegisterServiceWorker` | single origin means one worker and one Cache Storage for every tenant that ever signs in on that browser profile. Keep the cache to static assets only and add a test that `isCacheable` rejects `/screen`, `/network/*`, `/api/bff/*`. Per-tenant subdomains would isolate (Q2) |
| R8 | Push subscription outlives the person or tenant | W34, W42, W55 | sign-out, unpair, "Remove a person" and tenant offboarding must unsubscribe (`pushManager.getSubscription().unsubscribe()`) and delete the server record. A notification for tenant A shown on a device now used by tenant B names tenant A's service on a lock screen. The service worker already displays only `title`, `body`, `url` (`W32.md:49`); add a rule that `url` must be a path the current session may open |
| R9 | localStorage and sessionStorage not keyed | W52 tour state (`W52.md:53`), W53 lesson progress (`W53.md:51`), O02 `session.id` | all `localStorage` access goes through `lib/storage/tenantStore.ts`, keyed by an opaque per-user key, wiped on sign-out. `sessionStorage` is per tab and fine for `session.id` |
| R10 | Back-forward cache and the Next client router cache after sign-out | all pages | sign-out and unpair do a hard navigation (not `router.push`), and send `Clear-Site-Data: "cache", "storage"` (Chromium; Safari ignores it, so also clear in script). All pages with data send `Cache-Control: no-store` |
| R11 | Responses cached by Next or a CDN across tenants | `lib/fhir/client.ts:85-89` `fetch` has no `cache` option; `lib/bff/handler.ts:27,49` set `no-store` only on refusals and thrown errors, not on success (`:46`) | `withBff` sets `Cache-Control: private, no-store` and `Vary: Cookie` on every response; `fhirFetch` sets `cache: 'no-store'`; `/screen` and every network page set `dynamic = 'force-dynamic'`; a lint rule bans `use cache`, `unstable_cache`, `revalidate` and `force-static` under `app/` |
| R12 | SSE relay keeps running after revoke | `W06.md:48` | the relay re-validates on a timer and closes on 401. Network events use a separate relay (`/api/bff/network/events`); each carries `serviceId` only. Defence in depth: drop an event whose scope is not the page's scope |
| R13 | Device cookie lifetime | wall session has an `expiresAt` set by W08 (unspecified); DEC-125 item 10 says no server-side revocation | the back end must revoke the device token on unpair; the BFF turns the 401 into R1; lifetime documented |
| R14 | Pairing code claimed by the wrong tenant | `W08.md:48-52`: `POST /screens/pairing` is unauthenticated; the code is global; any tenant's lead who types it claims the screen, so a room could display another organisation's board | add a confirm step showing a non-secret screen hint (first-seen time, coarse class) and the tenant name being bound; rate-limit claims; the screen shows its short id; codes are single use. Wall header always shows the tenant area name and the scope so a wrong pairing is visible in the room |
| R15 | No way to unpair or move a screen | `W08.md:73` out of scope | N4: list, unpair, change board, re-pair |
| R16 | Support banner or scope header missing on a wall | wall has no URL bar | the scope header is part of the board component, not the page chrome |

---

## 9. Risks and open questions for the owner, ranked

### Risks

1. **The BFF can mint any tenant's token** (`W09.md:47-49`): one process holds `BACKEND_JWT_SECRET`, chooses `sub`, `role`, `services` and, once added, `tenant`. A BFF bug or a mapped Entra role becomes cross-tenant access. Worse, `DIUCS.Support` maps to `support` from any directory. Fix: back-end token exchange; support role only from the platform directory; no role gives console access until DEC-130 item 8 is closed.
2. **Wall screens** (R1, R14, R15): global pairing code namespace, no revoke, no unpair, and a revoked screen would show "Last known" for another or former tenant indefinitely.
3. **Browser state that outlives sign-out or unpair** (R6 to R10): single origin service worker, push subscriptions, localStorage, bfcache, and the `diucs_csrf` cookie that a link page overwrites in a browser with a staff session (`W04.md:48`).
4. **Planned prompts hard-code one area and take precedence over documents** (preamble of every prompt; `W05.md:51`, `W40.md:49`, `W29.md:49`, `W19.md:50`, `W22.md:50`, `W46.md:49`): builders will ship "Dorset" and a global `SPOA_PHONE_DISPLAY`, contradicting DEC-014 item 5. Needs amended prompts, not a DEC.
5. **Network view mistaken for own data, or private data leaking into it** (DEC-132): without a permanent scope header and organisation label on every row, advisors will read another member's figure as their own (a clinical-safety risk, hazard H-29 style) or book against it. Booking, "I phoned" and case outcome with a network row cross scope boundaries that DEC-132 item 4 forbids.
6. **Cross-tenant answers that reveal existence** (`errors.ts:128-138` 403 versus 404; `[ref]`, `[id]`, `[serviceId]` routes; reference numbers are 4 digits and only unique per tenant).
7. **Caching** (R11): no-store on success is missing in `withBff`; Next and a CDN can cache across tenants.
8. **Telemetry** (section 6): no `tenant.id`; dynamic element ids break O05 and cardinality; anonymous link pages cannot be stamped on the server without a signed context.
9. **Support console** (W48, W49, section 4): planned as if the role existed.
10. **Fixtures with unique ids** would pass every test while leaking; fixtures must overlap ids.
11. `frontend/middleware.ts` (W09, S01) is deprecated in Next 16.3.8 (use `proxy.ts`, Node runtime); a tenant check placed only there is an optimistic check, so every route handler and Server Component must check as well.

### Questions for the owner (ranked)

- **Q1** Who signs the tenant-bound token: the back end (token exchange, recommended) or the BFF (W09 as written)?
- **Q2** One origin for all tenants (the spec's `diucs.example/...`) or a sub-domain per tenant? One origin is simpler and keeps Entra to one redirect URI, but shares service worker, Cache Storage, cookies and push per browser profile; per-tenant sub-domains isolate them. Recommendation: one origin with the wipe rules in section 8; revisit for wall screens.
- **Q3** DEC-130 item 8: who may hold cross-tenant support, who approves, and does the tenant's lead approve each open? Until answered, W48, W49 and W56 stay blocked.
- **Q4** Roles. The 10 roles do not include a tenant administrator (approves grants, sets the wall board, manages screens) or a network owner administrator (members, grants, agreement reference). Add two roles to `ROLES` or give the powers to `lead`? A lead is a shift role; administration of data sharing is more senior.
- **Q5** May a reporter's phone or an exec belong to two tenants on one installed app? DEC-131 item 3 settles SMS. Recommendation: one tenant per device, N7 message, a second tenant uses text or link.
- **Q6** Are clinical advisors ever a shared pool serving several tenants (`W44.md:49` "2 clinical advisors available now")? DEC-130 says staff map to one tenant and DEC-132 does not share cases.
- **Q7** Product name ("DIUCS capacity" in all prompts and the canvas, "Community Overwatch" in DEC-014 and the design system), and branding limits: name and area name only, or also a logo? Recommendation: name and area name now; no colours.
- **Q8** Which policy values may differ per tenant (timers, thresholds, suppression, re-verify period, invitation lifetime)? Copy takes them as parameters either way.
- **Q9** DEC-132 item 4 lists "capacity status and figures". Is the projected figure net of pending bookings? A figure net of pending leaks the count of open bookings. Recommendation: project the reported figure and status only; no pending, no "Used x of y" derived from bookings.
- **Q10** Criteria: the scope `criteria` is granted, but the allowlist lists only "the current criteria version". Options filtering over network services needs the criteria content. Is content shared, or only the version?
- **Q11** Advisor outcome on a network row: the case is tenant data and the service is in the network scope. Store a denormalised copy of service name and organisation in the case (no cross-scope relationship)? Phoning is the only action possible on a network row; confirm that "Request booking" is not offered (bookings are never shared).
- **Q12** Do COO and ICB alerts cover network services, or only the own tenant until further notice?
- **Q13** Which week-summary measures exist for the network (capacity-derived only, as the decision log and bookings are private)?
- **Q14** Is tenant lifecycle (create, configure, suspend, offboard) a UI or operator tooling? It is in no plan.
- **Q15** Is `tenant.id` allowed on metric labels?
- **Q16** Pairing: accept the added confirm step on the wall pairing flow (R14)? The spec has the screen show a code and the lead type it, which is why a claim by the wrong tenant is possible.
- **Q17** What does a departed member's data look like on the live board (R4): hidden from live views, shown in history with the leave date?
- **Q18** Is "Single point of access" / "SPOA" a tenant noun or the platform's? It appears 63 times in the spec; if every tenant calls its service line something else, copy must be parameterised everywhere.

---

## 10. Proposed task breakdown

Ids are TEN-D. Hours are estimates. "Absorbed" tasks amend a planned task and its estimate rather than adding a separate task. Backend dependencies are named by the plan's task ids (R02 auth, R10, R11, R15 screens, R18 support, L01, L02, O06, O07, P10) and by DEC-130, DEC-131, DEC-132 sequence.

### 10.1 New tasks

| ID | Title | Files | Hours | Depends on |
|---|---|---|---|---|
| TEN-D01 | UI tenancy decision record and v1.1 change list (answers to Q1 to Q18 recorded; list of spec edits for the owner; no source artifact edited) | `docs/delivery/decisions.md` (new DEC), a change list | 3 | owner answers |
| TEN-D02 | W02 rework before merge: `tenantId` in Session, fail-closed unseal, browser-safe session response (display fields, network availability, no tenant id), cookie fake, tests, DEC-125 addendum | `lib/auth/session.ts`, `app/api/bff/session/route.ts`, `lib/auth/session.test.ts`, `route.test.ts`, `lib/bff/handler.test.ts`, `test/cookies.ts` | 5 | D01, back-end token claim (R02 amended) |
| TEN-D03 | Tenant-bound CSRF and a separate link CSRF (`diucs_link_csrf`, or the back end's token-bound token) | `lib/auth/csrf.ts`, `csrf.test.ts`, session route | 3 | D02 |
| TEN-D04 | BFF handler hardening: `Cache-Control: private, no-store` and `Vary: Cookie` on every response; reject `tenant`, `scope`, `network`, `x-tenant*` inputs; `withLink` wrapper (never reads the session); `withBff` option for network routes; cross-tenant answers presented as 404 | `lib/bff/handler.ts`, `lib/bff/link-handler.ts`, `lib/bff/errors.ts`, tests | 5 | D02, D03 |
| TEN-D05 | W01 rework: `fhirFetch` `cache: 'no-store'`, token required except for link calls, guard tests (no tenant header) | `lib/fhir/client.ts`, three client test files | 2 | D02 |
| TEN-D06 | Tenant profile and policy layer: server-only profile fetch cached per tenant id with a short TTL, `TenantPolicy` for copy parameters, copy templates, `TenantHeader`; removes `SPOA_PHONE_DISPLAY` and `NEXT_PUBLIC_SUPPORT_SHARING` | `lib/tenant/profile.ts`, `lib/tenant/policy.ts`, `lib/copy/*`, `components/tenant/TenantHeader.tsx`, tests | 7 | D02, back-end tenant configuration API |
| TEN-D07 | F03 rework: product-name constant, title template with area name, root page, wall placeholder, their tests and the smoke spec | `app/layout.tsx`, `app/page.tsx`, `app/(wall)/screen/page.tsx`, `layout.test.tsx`, `page.test.tsx`, `e2e/smoke.spec.ts` | 2 | D06 (may stub) |
| TEN-D08 | Test harness: `test/tenants.ts` (A, B, C, network, overlapping ids), tenant-aware MSW factories, bearer-claim leak canary, cookie fake, Playwright projects per tenant, generated "every BFF route answers 404 across tenants" test | `test/*`, `test/msw/handlers/*`, `vitest.config.ts`, `playwright.config.ts` | 8 | D02, D04 |
| TEN-D09 | Guard rails: lint rules and repo-scan tests (no `use cache`, `unstable_cache`, `revalidate`, `force-static` under `app/`; no `NEXT_PUBLIC_` for tenant config; no direct `localStorage`; no literal "Dorset", "Trust account", "SPOA phone" in `app/` and `components/`; no `fetch(` to the back end outside `lib/fhir`) | `eslint.config.mjs`, `test/guards/*.test.ts` | 4 | D06 |
| TEN-D10 | Client storage and sign-out wipe: `tenantStore`, `signOutLocal()` (unsubscribe push, delete caches, `Clear-Site-Data`, hard navigation), `bfcache` guard | `lib/storage/tenantStore.ts`, `lib/session/signOut.ts`, tests | 5 | D02 |
| TEN-D11 | Scope and row-attribution components (tokens only, no new colours): `ScopeHeader`, `ScopeSwitch` (links to two routes), `OrgLabel`, "Your organisation" marker, read-only note; axe and contrast tests; Banner tone for scope and support mode | `components/scope/*`, `components/ui/Banner.tsx` (new tone, with DEC-122 note) | 4 | D06, D31 |
| TEN-D12 | Network scope in the BFF: `/api/bff/network/*` route family and `/network/*` pages skeleton, network availability check per call (short in-memory TTL), `/api/bff/network/events` relay, tests for non-member 404 and ended grant | `app/api/bff/network/*`, `lib/network/*` | 6 | D04, D08, back-end network read use case (DEC-132 item 4) |
| TEN-D13 | Network capacity view: board grid and list (W05 to W07 components given a `scope` prop), advisor home counts tab, options rows read-only, map pins, exec home and pressure, exec service detail, week summary network measures, departed-member filtering | `components/board/*`, `components/advisor/*`, `app/(network)/network/*`, `components/exec/*` | 14 | D11, D12, W05 to W07, W13, W40, W41, W50 |
| TEN-D14 | Wall screens: list, which-board control, unpair, re-pair, pairing confirm step, 401 to pairing, scope-keyed last known, no silent fallback, `Clear-Site-Data` on unpair | `app/(lead)/lead/screens/page.tsx`, `lib/board/useBoardFeed.ts`, `app/(wall)/screen/pair/page.tsx` | 9 | W08 (amended), W06, D10, back-end R15 amended |
| TEN-D15 | Network administration screens (N1): members, add and end membership, agreement reference and version, grants overview and owner approval, history | `app/(network-admin)/network-admin/*`, `app/api/bff/network-admin/*` | 10 | D04, D11, D31, Q4, back-end network administration use cases |
| TEN-D16 | Grant approval and sharing transparency (N2): pending grants with the rendered allowlist, approve, decline, end grant, what stays after ending, who data is shared with | `app/(tenant-admin)/admin/sharing/*`, `app/api/bff/sharing/*` | 8 | D15, Q4 |
| TEN-D17 | Network unavailable states (N5) and scope-keyed offline: no network, grant ended, member left, last known per scope, SSE per scope | `components/scope/NetworkUnavailable.tsx`, `lib/board/*` | 5 | D12, D14 |
| TEN-D18 | Telemetry tenancy: server-stamped `tenant.id`, signed context for link pages, `view.scope`, schema patterns, collector allow-list note, removal of dynamic element ids | `app/api/bff/telemetry/route.ts`, `lib/telemetry/*` (with O02, O05) | 6 | D02, O02 |
| TEN-D19 | Support console cross-tenant mode (E1 to E9): elevation start, persistent banner, tenant-scoped search, tenant-side access log | `app/(console)/console/*`, `components/console/*`, `app/(tenant-admin)/admin/access/*` | 16 | DEC-130 item 8 answer (Q3), R18, O06 |
| TEN-D20 | Staff sign-in tenant mapping and failure screens (N6), `proxy.ts` instead of `middleware.ts`, support role only from the platform directory | `lib/auth/staff.ts`, `app/sign-in/*`, `proxy.ts` | 6 | W09 (amended), Q1, R02 |
| TEN-D21 | Reporter and exec device sessions: tenant from the invitation in code verify, N7, push lifecycle, PIN bound to (tenant, device) | W23, W33 to W38, W55 | 10 | W23, W33 to W37, R11, Q5 |
| TEN-D22 | PWA and offline: tenant-neutral `/offline`, `isCacheable` tests for network and wall routes, push unsubscribe on sign-out | `public/sw.js`, `lib/push/sw-handlers.ts`, `app/offline/page.tsx` | 3 | W32, D10 |
| TEN-D23 | Config-driven copy sweep: area name, SPOA and staff account names, EPR names, districts, pathway names, role titles, thresholds in copy, support and safety contacts | W05, W15, W25, W28, W29, W30, W31, W39, W40, W41, W43, W46, W50, W52, W53 | 6 | D06 |
| TEN-D24 | Prompt amendments: tenancy-neutral preamble and a tenancy ground-rules block in all 65 UI prompts; per-prompt acceptance lines (404 across tenants, two-tenant test, no literals); the amendment map (10.3) | `docs/plan/prompts/*.md` (done by the orchestrator, not a builder) | 6 | D01 |
| TEN-D25 | Two-tenant and network end-to-end suite | `e2e/tenancy/*.spec.ts`, O09 synthetic tenant | 10 | D08, D12, back-end two-tenant seed |
| TEN-D26 | Network scope spec for the UI: wireframes, wording, empty and error states for N1 to N5 and the scope header, added as a v1.1 addition for DEC-129 (no snapshot edit) | a new design note | 6 | D01 |
| TEN-D27 | Optional: tenant lifecycle UI (N9) | `app/(operator)/*` | 8 | Q14 |

Totals: required TEN-D01 to TEN-D26 = 169 h (D01 to D10 = 44 h; D11 to D26 = 125 h); optional TEN-D27 = 8 h. Network scope (D11, D12, D13, D15, D16, D17, D26 and about 4 h each inside D14 and D25) is about 61 h; tenancy without the network is about 108 h. About 50 h (D14 partly, D18 partly, D20, D21, D22, D23) lands inside amended planned tasks and would be added to their estimates instead of being new tasks.

### 10.2 Delivered and in-flight UI tasks that need rework

| Task | Verdict | Work |
|---|---|---|
| F03 (built) | small rework | TEN-D07 (title, description "single point of access" at `layout.tsx:15`, wall placeholder, smoke spec, page test) |
| F09 (built) | none | tokens and StatusBadge are tenant neutral; keep `tokens.test.ts` as the no-theming guard |
| X02 (built) | none | none |
| X03 (built) | none | DEC-019 values stay fixed for every tenant |
| W01 (built) | small rework | TEN-D05 and the 404 rule in `errors.ts` (TEN-D04) |
| W03 (built) | none | components are presentational. DEC-122 may need an addendum if a scope Banner tone is added (TEN-D11) |
| W02 (built, unmerged) | rework before merge | TEN-D02, TEN-D03, TEN-D04 (the no-store default); update DEC-125 and the H-29 residual row |

### 10.3 Planned UI tasks that need amended prompts

Codes: P preamble and acceptance lines only; L link token authority; B board and scope header; A auth, session, device; C tenant configuration copy or lists; R id-scoped routes answer 404 across tenants; X cross-tenant privilege; T telemetry or browser storage; N DEC-132 network variant; W wall; Q waits for an owner answer.

| Task | Codes |
|---|---|
| W04 | L R T (CSRF cookie clobber, `withLink`, tenant profile for phone) |
| W05 | B C N W (header literal `W05.md:51`, `cache: no-store`, scope prop) |
| W06 | B A N W (401 handling, scope keyed last known, SSE per scope) |
| W07 | B N (no pending in network, banner count per scope) |
| W08 | A W X (confirm step, tenant at claim, board setting, list and unpair move to a new page) Q |
| W09 | A X C Q (token exchange, directory to tenant mapping, N6, support role, `proxy.ts`) |
| W10 | P B N (home counts tab, tenant name) |
| W11 | P R |
| W12 | P |
| W13 | P C N (network rows read-only) Q |
| W14 | P R C N (criteria dialog for network rows) Q |
| W15 | P C (EPR name) N Q |
| W16 | P |
| W17 | B C R N |
| W18 | C R |
| W19 | L C (`SPOA_PHONE_DISPLAY`) |
| W20 | P R (no network variant) |
| W21 | P R |
| W22 | L C |
| W23 | A C (invite in verify) |
| W24 | C |
| W25 | C (districts, examples, referral methods) |
| W26 | C R |
| W27 | C R |
| W28 | C R ("Dorset" copy, scope list per tenant) |
| W29 | C R (`W29.md:49` "Dorset directory") |
| W30 | C R |
| W31 | C R (role names) |
| W32 | W T C (offline page, cache tests, push lifecycle, manifest name) |
| W33 | A L |
| W34 | A T |
| W35 | A R |
| W36 | L R C |
| W37 | A T |
| W38 | A R C T (dynamic element ids `W38.md:55`) |
| W39 | C R N Q (thresholds, alert scope) |
| W40 | B C N (`W40.md:49` "Dorset system") |
| W41 | C N Q (`minutesPerCall` per tenant, network measures) |
| W42 | R C |
| W43 | C L R (preview from back end) |
| W44 | R Q (shared clinical pool) |
| W45 | P R |
| W46 | C T X (CSO contact, numbering, flag, `NEXT_PUBLIC_SUPPORT_SHARING`) |
| W47 | R |
| W48 | X T Q |
| W49 | X T Q |
| W50 | C N T (dynamic pin ids `W50.md:56`) |
| W51 | C R (suppression per tenant; no network variant) |
| W52 | C T |
| W53 | C T |
| W54 | C L |
| W55 | A T |
| W56 | X T Q |
| O02 | T (server stamp, signed context) |
| O03 | none (pure rules; no tenant data) |
| O05 | T (patterns for `tenant.id`, `view.scope`; element id pattern vs dynamic ids) |
| O09 | T W (dedicated synthetic tenant) |
| S01 | A (`proxy.ts`, per-origin choice Q2, `img-src` for logos if Q7) |
| X02, X03, F09 | none |

All 65 UI prompts also get the preamble change (TEN-D24), because the line naming "Dorset" and "Where this prompt and the documents differ, follow this prompt" are in every one.

### 10.4 Order

1. D01 (owner answers: Q1 to Q4, Q7).
2. D02, D03, D04, D05 immediately, before W02 merges and before W09 starts.
3. D06, D07, D08, D09, D10, D24 next; then W04 to W08 can be built from amended prompts.
4. D12, D11, D26, then D13 to D17 once W05 to W07 and W40 exist.
5. D18 with O02.
6. D19 only after Q3.
7. D25 last.

---

## Other findings (not tenancy)

- W14, W15, W16 and W45 read artboards `AdvisorDialogsPhone` and `AdvisorFinishPhone`, which are not in the repo snapshot. Record under "Canvas differences" (DEC-129).
- W28 test 1 expects `href="/reporters/invite?service=s3"` while its rules say `/lead/reporters/invite?service=<id>` (`W28.md:58`).
- W04 (cookie double-submit) and L01 (token-bound `csrfToken`) specify two different CSRF mechanisms for the same page.
- `W23` and `W28` name MSW files `registration.ts` and `registrations.ts`.
- `frontend/middleware.ts` (W09, S01) is the deprecated Next 16 name; `proxy.ts` is the current convention.

## Method and what could not be read

Method: read `decisions.md` DEC-014, DEC-019, DEC-109, DEC-122, DEC-125 (branch), DEC-129, DEC-130, DEC-131, DEC-132; every tracked file under `frontend/` on main; the 15 files changed on the W02 branch; `ui-screens.md` (4,402 lines, all 62 artboards), `design-system.md`, `observability.md`; `tasks.json` and the prompts for W01 to W56, O02, O03, O05, O09, S01, X02, X03, F03, F09, L01; `architecture.md` front-end, security and sessions sections; the Next.js 16.3.8 docs under `frontend/node_modules/next/dist/docs` for the `proxy` rename and authentication guidance. Counts by `grep`, `git ls-files` and short scripts; page and BFF route counts for planned work are derived from the prompts (a derived count, not a file count), and a few routes are named in prompts only by ellipsis, so the true totals may differ by a handful.

Could not read or not read in full: the live design canvas (DEC-129: the snapshot is the specification); backend tasks R02, R10, R11, R15, R18, O06, O07, O08, L02 and their prompts (out of scope; the interfaces they must provide are listed as dependencies, not verified); `origin/task/W02-bff-session-csrf` (does not exist, the local branch was used); evidence files for W01 and W03 beyond what is cited. No model names appear in this file.
