# Redesign brief: planning, analytics, network and the support console

Status: design brief for implementation planning. Nothing here is built. The boards are in the design canvas
"Overwatch redesign: planning, analytics, network and console" (https://claude.ai/artifact/5StMaksTdjCW2VkdDLpUKa,
private to the owner until shared). Board names in this file (PHome, NBoard and so on) are the names on that canvas.
It follows the visual language and morph rules of the advisor and administration canvas
(https://claude.ai/artifact/Nb8Zzui3LuDhQbqe8vjdku). It changes how things look and move, not what they are for: the
words in `docs/design/network-ui.md` and `docs/spec/ui-screens.md` stay as they are, and a decision against DEC-014 is
needed before the shell changes (section 6).

Everything below was checked against the code in `frontend/` and the BFF routes in `frontend/app/api/bff/`. Where a
board shows something the code does not provide, it is listed in section 4. Those are the places to be careful.

## 1. What is being designed

| Surface | Roles | Routes |
|---|---|---|
| Planning (executive and shift lead) | exec, lead | `/planning`, `/planning/services`, `/planning/services/[id]`, `/planning/week`, `/planning/alerts`, `/planning/alerts/[id]`, `/planning/phone`, `/planning/setup`, `/planning/settings`, `/planning/flows`, `/planning/coverage` |
| Network (read only) | advisor, exec, lead (week: exec, lead) | `/network/home`, `/board`, `/services`, `/services/[id]`, `/system-now`, `/phones`, `/week`, `/history` |
| Network administration | network administrator of the owner | `/network-admin`, `/grants`, `/listings`, `/history` |
| Support console | support | `/console`, `/console/session/[id]`, `/console/trace/[traceId]`, `/console/insight` |

No route is skipped. Two have no board of their own because they are the same page in another mode:
`/planning/setup` is the first-run mode of `/planning/settings` (board PSettings, the stepper is the only difference), and
`/network/services/[id]` is the detail pane of the directory (board NServices).

## 2. Shared pieces, built once and used by every route

Build these first. Every route below uses them.

1. **Shell by role.** A dark rail (84 px) with icon and label, a white top bar with the organisation and the role chip
   (the `RoleSwitcher` from DEC-1324), and a content area. The rail items per surface: planning (Home, Services, Week,
   Alerts, Analysis), network (Home, Board, Services, System now, Phones, Week, History), network administration
   (Members, Grants, Listings, History), console (Sessions, Insight, Help). On a phone the rail becomes a bottom bar of
   four items. Replaces `AdminShell` and `AppShell` for these surfaces. No wrapping link rows.
2. **`StageGrid` (the morph primitive).** One container with named regions whose column and row sizes depend on a state
   (`data-stage`), animated with `grid-template-columns` and `grid-template-rows` transitions (`--ease-drawer`,
   `--dur-sheet`), with a spring only on small things (chevron, a row arriving, a chip). Regions cross-fade by opacity and
   a small translate. The state is a route or a search parameter, so Back and links work. Used by: planning home
   to service to alert, network board to service, console session to trace.
3. **`StatusChip` and `StatusTile`.** Status as a glyph plus a word plus colour: ● Accepting, ◐ Limited, ■ Not accepting,
   ▲ Over capacity (hatched), ◌ Not updated (dashed). One component, used on every board. Replaces the several local
   copies. The seven words of the existing status badge are unchanged (no tone or status is added).
4. **`ScopeHeader`.** Already specified in `network-ui.md`; restyle only. A tinted band under the top bar on every network
   route, with the switch (Our organisation, Network). It never disappears, including in every degraded state.
5. **`Notice`.** Banner tones `info`, `warning`, `offline` only (as `network-ui.md`), restyled.
6. **`Disclose`.** Already built for the administration pages (`components/admin/Disclose.tsx`); move it to
   `components/ui/` and reuse for "Show as a table", "More filters", "Show the sum", "Details".
7. **`Skeleton`.** Built (`components/ui/Skeleton.tsx`, `app/skeleton.css`). Use `Loading` + `SkeletonRows`, plus new
   shapes for tiles and chart blocks (a `block` shape exists).
8. **Charts, with no library.** CSS and inline SVG only:
   - `BarChart` (CSS flex bars, axis from zero, value on each bar, a threshold line with its own label);
   - `LineChart` (inline SVG polyline, labelled peak and threshold);
   - `StackedBar` (one bar split by share, patterns, legend with numbers);
   - `HeatGrid` (exists, `components/planning/HeatGrid.tsx`: keep, add the pattern/number rule);
   - `Funnel` (CSS bars, the biggest drop hatched and named);
   - `Waterfall` (exists, `components/console/Waterfall.tsx`: keep, restyle).
   Every chart takes a `table` prop (the same rows) and renders it behind a "Show as a table" disclosure; a screen reader
   gets the table by default. No chart library is needed, and adding one is not recommended: the shapes are simple and
   a library would add weight and an accessibility burden.
9. **`DataTable`.** One table with sticky header, `overscroll-behavior: contain` and a viewport-aware max height, used for
   every table below.

Rules every route follows (from the design system and the earlier canvas): a layout changes only when the person chooses
something; the shell, the scope header and the role chip never move; live figures never animate for style; every
state has a URL; targets of 44 px or more; text at 4.5:1; status never by colour alone; stale figures are dashed, in
words, and carry their time; counts under 10 read "under 10", never zero; motion tokens are zero under reduced motion so
every state still appears.

## 3. Route by route

"Existing" means the component or endpoint is in the repository today. "New" means it has to be built.

### Planning

| Route | Board | Layout states | Components | Data |
|---|---|---|---|---|
| `/planning` | PHome, Morph (stage 1), phone PH1 | **Home**: five status tiles large, a "Needs attention" list, a "This week" glance. Opening a service goes to the service state (below). Phone: status line, five tiles in a grid, attention rows, bottom bar. | `StageGrid` (new), `StatusTile` (new), `ExecHome` (existing, rework) | `GET /api/bff/board` (existing, `readBoard`). Needs-attention is derived client-side from the board. The week glance uses `exec/week` (existing). |
| `/planning/services` | PServices | One list, filter chips (All, Needs attention, ● ◐ ...), a "Find a service" box, rows with status chip and figure. | `ServiceList` (existing, rework), `DataTable` (new) | `board` (existing). |
| `/planning/services/[id]` | PService, Morph (stage 2) | **Service in place**: tiles fold to a strip, the list becomes a rail, the service takes the stage, the alert for it opens beside it. | `StageGrid`, `ServiceDetail` (existing, rework) | `exec/services/[id]` (existing) and `exec/alerts` (existing). The "Today" strip needs a status history for the day: see section 4, item 1. |
| `/planning/week` | PWeek | Four figures, a pressure chart, "Time back (estimate)" with the sum behind a disclosure, "Send me this each Monday". | `BarChart` (new), `WeekSummary` (existing, rework) | `exec/week` (existing: referrals, best-fit-unavailable %, on-time %, median minutes, updates). The per-day pressure series is not provided: section 4, item 2. |
| `/planning/alerts` | PAlerts, phone PH2 | List on the left with Open, Acknowledged, Closed; the selected alert on the right. Phone: list with Acknowledge on each card. | `AlertList` (existing, rework), `AlertDetail` (existing) | `exec/alerts` (existing), `acknowledge` and `snooze` (existing). |
| `/planning/alerts/[id]` | PAlert, Morph (stage 3), phone PH3 | **Alert in place**: the alert opens beside the service; acknowledge, call, snooze. On a phone it is the screen opened from the notification. | `StageGrid`, `AlertDetail` | as above. `exec/leaders` (existing) for the duty coordinator. |
| `/planning/phone` | phone PH5 | One screen: what we send and never send, "On an iPhone" disclosure, Allow, Send a test, Change which alerts. | `PhoneAlerts` (existing, rework) | `push/key`, `push/subscriptions`, `push/test` (existing). |
| `/planning/setup`, `/planning/settings` | PSettings | Six switches with state in words, "After 2 or 4 hrs" revealed under its switch, quiet hours and escalation in a disclosure. Setup adds the left stepper. | `AlertSwitches`, `EscalationForm`, `SetupFlow`, `SettingsForm` (all existing, rework) | `exec/alert-preferences` (existing). |
| `/planning/flows` | PFlows | Filters (period, need), three figures, the flows table with inline bars, the day-by-time grid with numbers in cells, "declined despite showing capacity", cohort and "how to read" behind disclosures, Export CSV. | `PlanningView`, `FlowsTable`, `HeatGrid` (existing, rework), `StackedBar` (new, optional) | `GET /api/bff/planning` and `planning/export` (existing). |
| `/planning/coverage` | PCoverage | District tiles (No cover, One service, Two or more) for a chosen part of the day, three facts, an opened tile showing who covers it. Tiles use a hatched border for "No cover" and a number-free pattern, never colour alone. | `CoverageByTime` (existing, rework) | `GET /api/bff/planning/coverage?window=` (existing). The tile's "who covers it" is `services` on each district (existing). |

### Network

All network routes render the `ScopeHeader` and the read-only notice. No route sends a tenant, network or scope
identifier from the browser (unchanged, `network-ui.md` section 1).

| Route | Board | Layout states | Components | Data |
|---|---|---|---|---|
| `/network/home` | NHome, phone PH4 | Counts by status, "Who shares" chips, two actions. | `StatusTile`, `NetworkHomeView` (existing, rework) | `network/board` counts (existing). The organisation chips with service counts come from the board entries (existing). |
| `/network/board` | NBoard | Organisation chips filter in place; tiles or list; each tile has name, organisation, own-row marker, status, figure, age, service line. Paused and not-updated tiles are dashed. | `NetworkBoardView` (existing, rework) | `network/board` (existing). "Used 2 of 6" is in the spec but not in the parsed types: section 4, item 3. |
| `/network/services`, `/network/services/[id]` | NServices | Master list (organisation and category chips) and detail pane (about, source, hours, line, read-only criteria). | `NetworkServicesView`, `NetworkServiceDetail` (existing, rework), `StageGrid` | `network/directory`, `network/criteria` (existing). |
| `/network/system-now` | NSystemNow | Pressure notice, a stacked status bar with every status and its number, what this is, what a failed read looks like. | `StackedBar` (new), `NetworkSystemNowView` (existing, rework) | `network/system-now` (existing: counts, services, organisations, alert level, `generatedAt`). |
| `/network/phones` | NPhones | A table: service, organisation, service line (phone link), last reported. | `DataTable`, `NetworkPhonesView` (existing, rework) | `network/phones` (existing). |
| `/network/week` | NWeek | Hours sampled, on-time %, a status share bar, hours at each pressure, pressure over time as a 7 by 24 grid with patterns and a table. The withheld week is its own card. | `StackedBar`, a new `PressureStrip` (CSS grid), `NetworkWeekView`, `NetworkWeek` (existing, rework) | `network/week` (existing: hours sampled, on-time, status share, pressure hours, `pressureOverTime`, each measure with `hidden`). |
| `/network/history` | NHistory | Warning notice, filter (All, Left, Stopped), rows with the date and a "Last known" tag. | `NetworkHistoryView` (existing, rework) | `network/events` or history read (existing view; confirm the field for "last shown"). |
| every refusal and degraded state | NStates | Not available, paused, membership ended, source stopped, source delayed, offline (last known), wall fallback, empty and empty-filter. | `Notice`, `NetworkScope` (existing), the existing `NetworkUnavailable` | no new data. Wording is `network-ui.md` section 5, unchanged. |

### Network administration

| Route | Board | Layout states | Components | Data |
|---|---|---|---|---|
| `/network-admin` | NAdmin | Members table with status chips and "Behind v3", Add an organisation opening in place, agreement, health table. Ending a membership asks a second administrator. | `NetworkMembers` (existing, rework), `DataTable` | `network-admin/members`, `network-admin/agreement`, `network-admin/members/[id]/remove` (existing). The health table: section 4, item 4. |
| `/network-admin/grants` | NGrants | Filter by approval state, a table with Approve and Decline, the decline confirmation in place, "what each scope shares" and "never shared". | `NetworkGrants` (existing, rework) | `network-admin/grants`, `.../approve`, `.../decline` (existing). |
| `/network-admin/listings` | NListings | Filter by status, a table with the buttons that apply to each state, the reason chips in place for Decline and Pause. | `NetworkListings` (existing, rework) | `network-admin/listings`, `admit`, `decline`, `suspend`, `reinstate` (existing). |
| `/network-admin/history` | NAdminHistory | A dated list of decisions that names roles, never people. | `NetworkAdminHistory` (existing, rework) | the existing read (confirm that it carries the role and the date for each decision). |

### Support console

| Route | Board | Layout states | Components | Data |
|---|---|---|---|---|
| `/console` | CFind | The support code is the first and largest control; search is a second card with filters behind "More filters". The result table shows only aggregates and session ids. | `FindSession` (existing, rework), `DataTable` | `console/sessions`, `console/sessions/open` (existing). |
| `/console/session/[id]` | CSession | Timeline on the left with filter chips; "What stands out" and the selected event on the right, with "View trace" and "Copy link to this moment". | `SessionTimeline` (existing, rework), `StageGrid` | `console/sessions/[id]`, `.../events`, `.../ticket` (existing). |
| `/console/trace/[traceId]` | CTrace | Waterfall with the slowest span hatched and named, a table of spans, "Open the query in the matrix", "Back to the session". | `Waterfall` (existing, rework) | `console/traces/[traceId]` (existing). |
| `/console/insight` | CInsightA (Funnels), CInsightB (Paths, Friction, Performance, Releases) | One tab per view, a range and a device filter. Funnels: steps with the biggest drop hatched and named, a split table, Export CSV. | `InsightTabs` and its five tabs (existing, rework), `Funnel` (new) | `console/insight/[tab]` (existing). "Show example sessions" on Friction: confirm it exists in the allow-list. |

### Everywhere

| Board | What it fixes |
|---|---|
| PStates | One look for loading (the synchronized shimmer), empty (says why and what to do), error (what did not happen, what is safe, a way forward), stale or offline (dashed, with its time). |
| PCharts | How charts are drawn: axes from zero, a label on every mark, patterns beside colour, a table beside every chart, no library. |

## 4. Where the boards need data the code does not provide

These are the things to settle before building the route. Each is a gap between a board and the existing endpoints.

1. **A service's status through the day** (`/planning/services/[id]`, the "Today" strip on PService and Morph). The existing
   service read gives the current state and the since-time as a sentence. A strip needs the status intervals of the day. Either extend `exec/services/[id]`
   with a list of `{ from, to, status }`, or draw only the "since 13:10" marker and drop the strip.
2. **System pressure per day for the week** (`/planning/week`, the bar chart on PWeek). The tenant week summary has
   referrals, best-fit-unavailable %, on-time %, median minutes and updates. It has no pressure series. The network week
   does (`pressureOverTime`). Either extend `$week-summary` with the peak count of services limited or worse per
   day, or draw the network-style strip, or drop the chart from the first release.
3. **"Used 2 of 6" on a network tile** (NBoard). `network-ui.md` specifies it, but the parsed network entry types do not
   carry a used and total. Confirm with the back end, or remove the line.
4. **Network health: last update received, delay, updates refused** (NAdmin). `network-ui.md` specifies these three columns.
   The existing health projection (`parseProjection`) returns, per organisation, each shared kind and whether it is active or ended,
   with an end reason. It does not carry a timestamp, a delay or a refused count. The board shows the specified columns;
   either extend the projection or show the source state (active or ended) only.
5. **Coverage tile detail** (PCoverage). The district tile already lists its `services`; the board's wording "Covered by
   X and Y between 12:00 and 18:00" uses only that. It does not show hours per service; do not promise that.
6. **Alert history on the alert detail** (PAlerts). The existing alert item has the state and times used on the board;
   the ladder (you, deputy at 15 min, shift lead by phone) is configuration from the alert preferences. If the deputy's name
   must show, `exec/leaders` provides names; confirm they may be shown there.
7. **Console "Show example sessions"** (CInsightB, Friction). Not found in the BFF route list as its own route; it may be inside
   `console/insight/friction`. Confirm before drawing it.

None of these needs a patient-level or personal field. Nothing in the redesign adds one.

## 5. Motion and accessibility notes

- **Morph** is only for these moves: planning home to a service to an alert; network directory list to a service;
  console session to a trace; administration list to a role (earlier canvas). Everything else is a normal page.
- **Durations and easing** are the existing tokens. Under reduced motion they are zero, so each state appears at once.
- **Live figures** (tiles, counts, status words) are never animated for style. A region may resize around them; the
  figure itself does not move or change colour with a transition.
- **Charts** carry `role="img"` with an `aria-label` that says the finding in words, and the table is the accessible form.
  Pattern fills (hatch for over capacity, dashed for not updated, solid for the rest) in addition to colour, and a number
  or word on every mark.
- **Phone**: columns become steps and sheets. The planning home is one column; the alert acknowledgement is a full screen
  opened from the notification, and Back returns to the alert list.
- **Keyboard**: every disclosure is a native `details` or a button with `aria-expanded`; no custom focus traps; the role chip
  closes on Escape and returns focus to itself.
- **Language**: placeholders such as "[x] minutes" stay visible where the baseline is not measured. No saving is claimed
  before it is measured, and every estimate shows its sum and a range.

## 6. Decisions to record before building

1. **The shell** (rail, top bar, role chip) replaces the current white strip with wrapping links for these surfaces. This is a
   new decision against DEC-014. The advisor and administration canvas needs the same decision, so decide it once.
2. **Clinical-safety review of the morphs** for the planning home and the alert: the alert opens in place beside the service
   and keeps the Acknowledge, Call and Snooze actions in the same positions as the standalone alert page.
3. **Charts without a library** is the recommendation. Record it so nobody adds one for a single chart.
4. **Which data gaps in section 4 are closed** (extend an endpoint) and which are dropped from the first release.

## 7. Suggested build order

1. Shared pieces: shell by role, `StatusChip` and `StatusTile`, `Disclose` moved to `ui`, `DataTable`, the chart set, skeleton shapes.
2. `StageGrid` and the planning home to service to alert morph (the highest-value, highest-stakes path), with the phone
   versions of home, alerts and acknowledge.
3. Alerts list and detail, alert settings and set-up, alerts on this phone.
4. Network read-only views: home, board, directory and service, system now, phones, week, history, then the degraded states.
5. Network administration: members, grants, listings, history.
6. Planning analysis: week, flows, coverage, all services.
7. Support console: find a session, session timeline to trace, insight tabs.

Each step ends with the route's unit tests, an accessibility check (axe), the phone width, and the reduced-motion state.

## 8. What this brief does not cover

The advisor call, administration, the reporter app, registration, criteria, clinical, the operator console and the wall
screen are in other canvases. Nothing here has been built, run in a browser or tested.
