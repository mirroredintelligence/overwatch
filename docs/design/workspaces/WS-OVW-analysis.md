# WS-OVW analysis: what the overview workspace (WSP-13) needs before it can be built

Source: a read-only Sonnet analysis of the analytics code on 2026-11-10, recorded here so the builder has it. Paths are under `frontend/`. Items marked "not checked" were not read. WSP-13 is **blocked** until the dialog changes in section 3 are made (they alter `dialog.json`, `dialog.ts` and the WS-DLG tests, which are outside WSP-13).

## 1. Facts about the existing code

- The overview data is the type `AnalyticsOverview` in `lib/analytics/types.ts` (fields `counts`, `outOfHours`, `services`, `areas`, `underPressure`, `underutilised`), parsed by `parseAnalyticsOverview` in `lib/analytics/parse.ts`, fetched from `GET /api/bff/analytics/overview` inside `components/analytics/AnalyticsOverview.tsx`. The helpers `areaCards`, `areaFromQuery`, `areaHref`, `attentionShown` in `lib/advisor/v2/overview.ts` are for the advisor's capacity type and do **not** fit this data. Use `lib/analytics/groups.ts` (`areaGroups`, `NOT_PLACED` = `'__not-placed'`), `parse.ts` and `types.ts`.
- `AnalyticsOverview` takes no props and owns its fetch, its drill state (`target`) and its phone tab (`locations`, `attention`, `groups`); nothing reads the URL. `AttentionPanel` (props `underPressure`, `underutilised`) always shows both columns, pressure first. `Drill` (props `overview`, `target`, `now`, `title`, `onBack`) and `drillTitle` are exported pure pieces. The URL `tab` (pressure or under) has nothing to do with `AnalyticsOverview`'s internal `tab`.
- `WorkspaceProvider`, `WorkspaceShell` and `WorkspacePage` are not yet built (WSP-08, WSP-09).
- Wrapping is feasible without editing `AnalyticsOverview.tsx`, `AttentionPanel.tsx` or `Drill.tsx`: a client `OverviewWorkspace` does its own fetch through `parseAnalyticsOverview`; `view=attention` renders `AttentionPanel`; `view=area` renders `Drill` with `{ kind: 'area', key }`, `now` from `Date.parse(overview.generatedAt)` (fallback `Date.now()`), and `onBack` pushing the home href; `view=home` renders `AnalyticsOverview` unchanged (a second request to the same endpoint). Limit: clicks inside the wrapped home still set internal state, not the URL, so the thread keeps saying "Showing the … overview" while a drill is open, and browser Back does not close it; status and group drills have no URL form. Recommendation: wrap, use the thread chips as the only way into `view=area`, and record the limit as a known gap. (The smallest edit, if the frozen rule can bend, is an optional `onOpen` prop on `AnalyticsOverview`; recomposing its 45 lines would drift from it.)
- `app/(analytics)/layout.tsx` must use `WorkspaceShell`. That layout covers two pages: `analytics/page.tsx` (render `OverviewWorkspace`; drop its `<main>` and `<h1>`) and `analytics/services/[id]/page.tsx` (wrap its `ServiceDetail` in `WorkspacePage` with title "Service detail", `backHref="/analytics"`, `withThread={false}`). `analytics/page.test.tsx` asserts a level-1 heading "Capacity overview" and must change; `services/[id]/page.test.tsx` asserts a link "Back to the overview" to `/analytics` (ServiceDetail's own), which still passes. WSP-13's file lists must add: `lib/workspace/overviewContext.ts` and its test, `analytics/services/[id]/page.tsx` and its test, `analytics/page.test.tsx`, and `app/(analytics)/layout.test.tsx`.
- The frame renders its title as a `<p>`, so these pages have no `<h1>` (not checked: whether `runAxe` requires one). The spec gives no overview title, back link or footer; proposals: title "Capacity overview", back link `/analytics?view=home` on the attention and area views only, no footer text (do not reuse `V2_BROWSE_NOTE`, which is advisor wording).

## 2. Where each dialog context key comes from

| Key | Source |
|---|---|
| `organisation` | `identity.organisation` from the provider (`currentProfile().displayName`); null with no profile |
| `total` | `overview.services.length` (not the sum of `counts`, which omits out-of-hours and last-known) |
| `areaCount` (home) | `overview.areas.length`; 0 with no area table; "Not placed" not counted |
| `attentionTotal` | distinct service ids in `underPressure` plus `underutilised` (not checked: whether one service can be in both) |
| `pressure`, `under` | `overview.underPressure.length`, `overview.underutilised.length` |
| `tab` (effective) | new pure function: the requested tab, except that when its list is empty and the other is not, the other |
| `areaName` | the label of the matching group from `areaGroups(overview.services, overview.areas)`, never the URL text; unknown id means unknown area |
| `areaCount` (area view) | `group.services.length` (a different quantity from the home `areaCount`; see 3.2) |
| `counts` | `countsLine(group.counts)` (statuses accepting, limited, not-accepting, over-capacity, not-updated; out-of-hours and last-known are not tallied, so it can sum to less than the count, or be empty) |
| `topAttentionArea` | new: among real areas (not `NOT_PLACED`), the one with most distinct attention services; ties go to the earlier area in `overview.areas`; omit when the highest is 0 or there is no area table (matches D14) |
| `topAttentionAreaId` | new, needed by 3.1 |
| `firstAttention` | new: first row (in received order) of `underPressure` in the area's group, else first of `underutilised` in it, else omit |

The glue is one pure file, `lib/workspace/overviewContext.ts`, with three builders whose key sets match D13 to D21: `homeContext = {organisation?, total, areaCount, attentionTotal, topAttentionArea?, topAttentionAreaId?}`, `attentionContext = {tab, attentionTotal, pressure, under, topAttentionArea?, topAttentionAreaId?}`, `areaContext = {areaName, areaCount, counts, firstAttention?, attentionTotal}` (null for an unknown area).

## 3. Spec defects to fix first

1. **Blocker: the area chip cannot carry the area id.** The chips "Show {topAttentionArea}" in `overview.home` and `overview.attention` have no `params`, and `renderTurn` copies params without filling them, so the href is `/analytics?view=area` with no `area=`. Fix: give the chip `"params": {"area": "{topAttentionAreaId}"}`, have `renderTurn` fill param values with the same template rule, and add the context key `topAttentionAreaId` (changes `dialog.json`, `dialog.ts` and the WS-DLG tests).
2. **`areaCount` means two things** (areas on home, services in an area on the area view). Add a second key for the area view (for example `areaServiceCount`) and change `areaServices` to read it.
3. **A null organisation throws** `dialog: missing {organisation}`. Add a first `overview.home` variant for `{organisation: {present: false}}`: "Showing the overview: {total} {totalServices} in {areaCount} {areasWord}. What would you like to look at?" (and the form without areas).
4. **An area with no countable services** gives "Area One has 0 services: ." Add a variant for an empty `counts`, or treat an empty area as unknown.
5. **Order.** For `tab=under` the reply says "Showing the {under} underutilised first" but `AttentionPanel` always puts pressure first. Reword the reply, or allow an edit to `AttentionPanel`.
6. The "reply says so" wording for a fallback tab in WS-OVW-T02 is wrong: the reply does not mention the empty tab. Reword.
7. With no area table every area id is unknown (decided here). `area=__not-placed` is valid and never the top area.
8. **Thread chips must be client navigation.** (Fixed in the spec and the components: WS-CONV item 9.) With plain anchors every chip click reloaded the page and emptied the provider, so the echo, in-place replace and history never happened in the real app.
9. Do not mix the advisor's area-id pattern (`/^[a-z0-9][a-z0-9-]{0,39}$/`, not-placed token `none`) with `AREA_PATTERN` in `lib/workspace/url.ts` (`/^[A-Za-z0-9_-]{1,64}$/`, `__not-placed`).
10. Home makes two requests (the context fetch and `AnalyticsOverview`'s own), so the figures can differ between them. Loading and failure rule proposed: no `visit` until the data has loaded; on failure the canvas says "The overview could not be read. Reload the page to try again." and the thread is empty.
11. `T05` cannot assert "no navigation landmark" on the area view or the service page: `Drill` and `ServiceDetail` each draw a Breadcrumb `<nav>`.

## 4. Aggregate-only risks

- `AttentionPanel.tsx:91` contains the word "patient" ("not a recommendation of where to send a patient"), so a body-wide "no patient" assertion fails; scope any such assertion to the thread (the Assistant aside), not the canvas.
- The area name must come from the matched group label, never from URL text; an unknown id redirects home. Area ids can be district keys such as an outward code: districts are outward-code aggregates, shown today by design.
- Service names reach the thread (organisation service names, not patient data). The second fetch must go through `parseAnalyticsOverview`. No dialog key carries a postcode, case, patient or outcome.
- The existing `AnalyticsOverview.test.tsx` guards still pass while the three components stay unedited but exercise only `AnalyticsOverview`; `OverviewWorkspace` needs its own assertions.

## 5. Replacement test cases (to become WS-OVW-T01 onward once section 3 is done)

Fixtures from `test/fixtures/analytics.ts`: A = `ANALYTICS_OVERVIEW_AREAS` (5 services; areas `area-one` "Area One", `area-two` "Area Two", `network` "Network-wide"; `underPressure` = Hospital at home (`svc-hah`, no area) and Ward Z (`svc-ward`, area-one); `underutilised` = Poole UTC (area-one); so total 5, areaCount 3, attentionTotal 3, pressure 2, under 1, top area Area One). B = `ANALYTICS_OVERVIEW` (no areas: total 5, areaCount 0, attentionTotal 3).

Pure, `lib/workspace/overviewContext.test.ts`:
- `homeContext(A, 'Test Organisation')` equals `{ organisation: 'Test Organisation', total: 5, areaCount: 3, attentionTotal: 3, topAttentionArea: 'Area One', topAttentionAreaId: 'area-one' }`.
- `homeContext(B, 'Test Organisation')` equals `{ organisation: 'Test Organisation', total: 5, areaCount: 0, attentionTotal: 3 }`.
- With both attention lists empty, `attentionTotal` is 0 and there is no `topAttentionArea` key.
- `attentionContext(A, 'pressure')` equals `{ tab: 'pressure', attentionTotal: 3, pressure: 2, under: 1, topAttentionArea: 'Area One', topAttentionAreaId: 'area-one' }`.
- Effective tab: requested pressure with `underPressure` empty gives `under`; requested under with `underutilised` empty gives `pressure`; both empty or both full keep the requested tab.
- `areaContext(A, 'area-one')` equals `{ areaName: 'Area One', areaCount: 2, counts: '1 accepting and 1 over capacity', firstAttention: 'Ward Z', attentionTotal: 3 }`; `areaContext(A, 'network')` equals `{ areaName: 'Network-wide', areaCount: 1, counts: '1 limited', attentionTotal: 3 }` with no `firstAttention`; `areaContext(A, '__not-placed')` has name "Not placed", count 1, counts '1 not updated', firstAttention 'Hospital at home'; `areaContext(A, 'nope')` and `areaContext(B, 'BH15')` are null.
- Tie rule: with A but `underPressure` only the `svc-reab` row and `underutilised` only the Poole row, `topAttentionArea` is 'Area One' (earlier area wins).

Component, `components/workspace/OverviewWorkspace.test.tsx` (mock `next/navigation` as in WS-ADV; msw `GET /api/bff/analytics/overview`; real `WorkspaceProvider role="analytics-user" organisation="Test Organisation"`; helpers `thread()` = the paragraphs in the log "Conversation", `chips()` = the link label and href pairs in "Suggested replies"):
- A, no query: thread is exactly "Showing the Test Organisation overview: 5 services in 3 areas. What would you like to look at?"; B: "Showing the Test Organisation overview: 5 services. What would you like to look at?".
- A, no query: chips are `[Show Area One, /analytics?view=area&area=area-one]` and `[What needs attention?, /analytics?view=attention]` (needs 3.1); the canvas contains `[data-el="AN-COUNTS"]` and `[data-el="AN-LOCATIONS"]`.
- `?view=attention`, A: thread "3 services need attention: 2 under pressure and 1 underutilised. Showing the 2 under pressure first."; canvas contains `[data-el="AN-ATTENTION"]` and no `AN-COUNTS`; `?view=attention&tab=under`: "…Showing the 1 underutilised first."; chips for pressure: `Show the underutilised` (`/analytics?view=attention&tab=under`), `Show Area One`, `Back to the overview` (`/analytics?view=home`); for under: `Show those under pressure` (`/analytics?view=attention`), then the same two.
- `?view=attention` with `underPressure` empty: "1 service needs attention: 0 under pressure and 1 underutilised. Showing the 1 underutilised first."; with both empty: "Nothing needs attention right now." and one chip `Back to the overview`.
- `?view=area&area=area-one`, A: thread "Area One has 2 services: 1 accepting and 1 over capacity. Ward Z needs attention first."; the canvas has a level-2 heading "Area One" and `[data-el="AN-DRILL-COUNT"]` reads "2 services"; `area=network`: "Network-wide has 1 service: 1 limited."; chips `What needs attention?` and `Back to the overview`.
- `?view=area&area=nope`, `?view=area`, and `?view=area&area=BH15` over B: `router.replace` once with `/analytics?view=home` after the data has loaded. Before the response, the thread is empty and `replace` has not been called. A 503 shows the failure text and an empty thread.
- Aggregate-only (scoped to the Assistant aside): its text matches none of `/patient|case|postcode|outcome/i` or a UK postcode pattern, over all three views.
- Landmarks: home and attention have no `navigation` and exactly one `main`; the area view has exactly one `navigation`, named "Breadcrumb".
- Page and layout: `/analytics` renders `OverviewWorkspace`; `app/(analytics)/layout.tsx` renders `WorkspaceShell` and not `StaffShell`; `services/[id]/page.tsx` renders `ServiceDetail` inside `WorkspacePage` with `backHref="/analytics"` and `withThread={false}`.
