# Workspace build spec (DEC-1376)

Status: design, ready to build in phases 1 and 2 (phase 2 is an outline). Nothing here is built. This file is the specification a build agent works from; `registry.json` and `dialog.json` are its data; `units.json` cuts it into units; `check.py` checks the three agree. Read `README.md` first.

Headings that start with `WS-` are the anchors the units point at. Every line that starts with a test id in backticks is one test (one `it(...)`), and every test id is assigned to exactly one unit.

## WS-CONV Conventions for every unit

1. **Ground rules.** `docs/design/redesign/AGENT-GROUND-RULES.md` applies in full (worktree, test first with stubs, commands, git rules, report shape, never write files with a heredoc). Where this file names a path, it wins over the ground rules' examples. Boards for these screens are in `docs/design/workspaces/boards/` (open them to see the look; the spec below wins where they differ, see WS-DEV).
2. **New files, not edits.** A unit adds the files in its `add` list and edits only the files in its `modify` list. It never edits a file in its `forbidden` list. `components/advisor-v2/FindService.tsx` stays as it is: the new workspace is a new component tree in `frontend/components/workspace/` and `frontend/lib/workspace/`.
3. **Styles.** CSS modules and tokens only (`--space-*`, `--radius*`, `--type-*`, `--c-*`, `--dur-*`, `--ease-*`). No `style` attribute in any rendered element: every test of a component asserts `container.querySelector('[style]')` is null. Touch targets 44px or more, primary actions 52px or more. Status is shape plus word.
4. **Product name.** Never type the product name or a place name. The mark is `<Logo height={28} />` from `@/components/brand/Logo` (it reads `PRODUCT_NAME`). The repository guards (`test/guards`) fail on hard-coded system names, phone numbers and places, so tests use neutral words such as "Test Organisation", "Area One" and "Service A".
5. **Privacy (WS-PRIV).** v2 is browse-only and its finder says the postcode lives only in its form. So: patient criteria (age, postcode, needs, timeframe) are held in memory in the workspace provider only. They are never written to the URL, `localStorage`, `sessionStorage`, a cookie or a log. The only network call that carries the postcode is the existing `findServices`. The postcode is shown in full only inside its own field; everywhere else (thread, summary) only its outward code, from `outwardCode(...)` in `lib/advisor/postcode`. The one value this feature stores is the assistant's hidden flag, through `tenantStore` (never raw storage).
6. **Tests.** Vitest and Testing Library, as in `components/advisor-v2/AdvisorV2.test.tsx`: `render`, `screen`, `userEvent`, `msw` handlers from `@/test/msw/server`, `runAxe` from `@/test/a11y`. Query by role and accessible name. A component test never asserts a CSS class name.
7. **`data-el` names** are exactly those given below (they are the hooks for the end-to-end tests).
8. **One main landmark.** `WorkspaceFrame` renders the only `<main>`. A page that uses the frame does not render its own.

## WS-DATA Where each value comes from

The advisor workspace builds the dialog context (see `dialog.json`) like this. Anything not listed is omitted from the context, never sent as `undefined` text.

| Context key | Value |
|---|---|
| `age` | `AGE_BANDS.find(b => b.code === criteria.age).label`, for example "65 to 79" |
| `district` | `outwardCode(normalisePostcode(criteria.postcode))`, for example "DT4" |
| `count` | `read.services.length` (services, not groups) |
| `order` | `'travel'` or `'name'` from the URL |
| `failed` | `true` when the search failed |
| `postcodeNotPlaced` | `read.notFound` when it is true |
| `notSuitable` | not sent in phase 1 (v2 does not return it) |
| `summaryLine` | `${age} · ${district} · ${needs labels joined ", "} · ${urgency label}` using `NEEDS` and `URGENCIES` labels |
| `serviceName` | `opened.serviceName` (set when the person taps a service tile; see WS-ADV-T05) |
| `updated` | `${overdueText(Math.floor(dataAgeSeconds / 60))} ago` (`overdueText` from `lib/lead/format`) |
| `stale` | `option.figureUnavailable \|\| option.staleWarning` |
| `noReport` | `true` when `dataAgeSeconds === null` |

The overview workspace (phase 2) context: `organisation` (tenant profile display name), `total`, `areaCount`, `attentionTotal`, `pressure`, `under`, `tab` (the effective tab, see `dialog.json` grammar), `topAttentionArea` (the area with most attention services, ties by area order, omitted when none), `areaName`, `counts` (`countsLine(tally)`), `firstAttention` (name of that area's first attention service, omitted when none).

## WS-MATRIX Access matrix (independent of the implementation)

The services offered to each session role, in registry order. "Now" is `livePhase` 2; "All" is with every phase on. The test builds its expectation from this table, not from the registry, so a wrong registry fails it.

| Session role | Persona | Flags | Workspace | Now | All |
|---|---|---|---|---|---|
| advisor | advisor | none | yes | advisor.intake.age, advisor.intake.need, advisor.results, advisor.service, advisor.new-search | those, plus advisor.map and advisor.reasons (in registry order: intake.age, intake.need, results, map, reasons, service, new-search) |
| advisor-v2 | advisor | none | yes | same as advisor | same as advisor |
| clinical | advisor | clinicalSignOff | no | none | none |
| analytics-user | overview | none | yes | overview.home, overview.attention, overview.area | same |
| lead | manager | peopleAndPhones, planningAndAlerts, auditReplay | no | none | go.people-and-phones, go.planning, go.audit-replay |
| exec | manager | planningAndAlerts | no | none | go.planning |
| owner | manager | ownCriteria | no | none | go.criteria |
| audit | manager | auditReplay | no | none | none |
| reporter | reporter | none | no | none | none |
| tenant-admin | admin | none | no | none | go.admin.access, go.admin.users, go.admin.config, go.admin.contacts, go.admin.email, go.admin.retention, go.admin.sharing, go.admin.support |
| network-admin | admin | none | no | none | none |
| support | platform | none | no | none | none |
| wall | display | none | no | none | none |
| anonymous-link | display | none | no | none | none |

## WS-REG The registry library

File `frontend/lib/workspace/registry.ts`, with `registry.json` beside it (an exact copy of `docs/design/workspaces/registry.json`), and `registry.test.ts`. Pure functions, no React.

```ts
import registryJson from './registry.json';
export type Persona = 'advisor' | 'overview' | 'manager' | 'reporter' | 'admin' | 'platform' | 'display';
export type Flag = 'clinicalSignOff' | 'peopleAndPhones' | 'planningAndAlerts' | 'ownCriteria' | 'auditReplay';
export type DataClass = 'patient' | 'aggregate' | 'none';
export type Intent = {
  id: string; label: string; kind: 'view' | 'action' | 'nav'; phase: number;
  personas: Persona[]; requires: Flag | null; sessionRoles?: string[]; dataClass: DataClass;
  route: string; params: Record<string, string>; layout: string | null;
};
export type Identity = { persona: Persona; flags: readonly Flag[]; workspace: boolean };
export const LIVE_PHASE: number; // registryJson.livePhase
export function identityOf(sessionRole: string): Identity | null; // unknown role: null
export function intentById(id: string): Intent | undefined;
export function intentsFor(sessionRole: string, opts?: { phase?: number }): Intent[]; // registry order; phase defaults to LIVE_PHASE
export function canOpen(sessionRole: string, intentId: string, opts?: { phase?: number }): boolean;
export function routeOf(intent: Intent, vars?: { id?: string }): string; // replaces "[id]"; throws Error('routeOf: missing id') when [id] is present and vars.id is not
```

An intent is offered to a session role only when all hold: the role has an identity; `intent.phase <= phase`; the identity's persona is in `intent.personas`; `intent.requires` is null or in the identity's flags; `intent.sessionRoles` is absent or includes the role; and `intent.kind === 'nav'` or `identity.workspace` is true.

- `WS-REG-T01` `identityOf` returns, for each of the 14 session roles, the persona, flags and workspace value of the WS-MATRIX table (assert against a literal table written in the test), and `null` for `'nobody'`.
- `WS-REG-T02` `intentsFor(role)` equals the "Now" column of WS-MATRIX for all 14 roles, ids in the order shown.
- `WS-REG-T03` `intentsFor(role, { phase: 99 })` equals the "All" column for all 14 roles.
- `WS-REG-T04` `canOpen(role, id)` is true exactly when `id` is in `intentsFor(role)`; an unknown role or unknown intent id is false; the `phase` option is respected.
- `WS-REG-T05` Guard contract: for every intent and every session role with `canOpen(role, id, { phase: 99 })` true, `canAccess(role, routeOf(intent, { id: 'x' }))` from `@/lib/auth/access` is true. (The registry may offer less than the route guard allows, never more.)
- `WS-REG-T06` Intent ids are unique; every non-null `layout` is a key of `registry.layouts`; every `personas` entry is a key of `registry.personas`; every `requires` is in `registry.flags`.
- `WS-REG-T07` The runtime `registry.json` deep-equals `docs/design/workspaces/registry.json` (read with `fs` from `path.resolve(process.cwd(), '..', 'docs/design/workspaces/registry.json')`).
- `WS-REG-T08` `routeOf` replaces `[id]` (`'/advisor/v2/services/[id]'` with `{ id: 'svc-1' }` gives `'/advisor/v2/services/svc-1'`), throws `Error('routeOf: missing id')` without an id, and returns other routes unchanged.

## WS-DLG The dialog renderer

File `frontend/lib/workspace/dialog.ts`, with `dialog.json` beside it (exact copy of `docs/design/workspaces/dialog.json`) and `dialog.test.ts`. The grammar is in `dialog.json` under `grammar` and `derived`; `check.py` holds a Python reference implementation that renders every example, and the TypeScript must give the same answers.

```ts
import dialogJson from './dialog.json';
export type DialogContext = Readonly<Record<string, string | number | boolean | null | undefined>>;
export type ChipSpec = { label: string; intent: string; params?: Record<string, string> };
export type RenderedTurn = { echo: string | null; reply: string; card: string | null; summaryBox: boolean; chips: ChipSpec[] };
export function renderTurn(intentId: string, ctx: DialogContext, opts?: { withEcho?: boolean }): RenderedTurn | null; // withEcho defaults to true; null for a turn that is null (advisor.new-search); unknown id: throws Error(`dialog: no turn for ${id}`)
export function holds(when: Readonly<Record<string, unknown>>, ctx: DialogContext): boolean;
export function derivedValue(name: string, ctx: DialogContext): string | undefined;
export function joinCounts(parts: readonly string[]): string;
export function countsLine(tally: Readonly<Partial<Record<'accepting' | 'limited' | 'not-accepting' | 'over-capacity' | 'not-updated', number>>>): string;
```

`joinCounts`: no parts gives `''`; one part gives it; two give `'a and b'`; three or more give `'a, b and c'`. `countsLine`: for each status with a count above zero, in the order accepting, limited, not-accepting, over-capacity, not-updated, the text `${n} ${word}` with words `accepting`, `limited`, `not accepting`, `over capacity`, `not updated`, joined with `joinCounts`.

- `WS-DLG-T01` Table test: for every row of `dialog.json` `examples`, `renderTurn(intent, context, { withEcho: row.withEcho ?? true })` gives exactly the row's `echo`, `reply`, and the row's `chips` (labels) and `chipIntents` (the chips' `intent` values), in order.
- `WS-DLG-T02` Table test: for every row of `dialog.json` `errors`, `renderTurn` throws an `Error` whose message is exactly the row's `throws`.
- `WS-DLG-T03` `holds`: `{}` holds; a literal key holds only on strict equality (`{count: 0}` does not hold for `'0'`, `false`, or a missing key); `{gt: n}` holds only for a number above n (not for a string or boolean); `{present: true}` holds only for a non-empty string; `{present: false}` holds for a missing, empty or non-string value; a missing key never holds except for `{present: false}`.
- `WS-DLG-T04` `derivedValue` for each of the nine keys in `derived`: `one` when its source is exactly 1, `other` for 0 and 2; `undefined` when the source key is missing.
- `WS-DLG-T05` `renderTurn('advisor.new-search', {})` returns `null`; an unknown intent id throws `dialog: no turn for nope`.
- `WS-DLG-T06` With `withEcho: false`, the echo is `null` and a context without the echo's placeholders does not throw (row D26); with `withEcho: true` and a missing placeholder it throws.
- `WS-DLG-T07` The runtime `dialog.json` deep-equals `docs/design/workspaces/dialog.json`.
- `WS-DLG-T08` `joinCounts`: `[]` gives `''`, `['a']` gives `'a'`, `['a','b']` gives `'a and b'`, `['a','b','c']` gives `'a, b and c'`.
- `WS-DLG-T09` `countsLine`: `{accepting:2, limited:1, 'over-capacity':1}` gives `'2 accepting, 1 limited and 1 over capacity'`; `{accepting:1}` gives `'1 accepting'`; `{}` and all zeros give `''`; `{'not-accepting':3,'not-updated':1}` gives `'3 not accepting and 1 not updated'`.

## WS-URL URL state

File `frontend/lib/workspace/url.ts` and `url.test.ts`. Pure. The URL holds only where the person is, never who the patient is (WS-PRIV).

```ts
export type AdvisorUrl = { view: 'find' | 'list' | 'map' | 'why'; step: 'age' | 'need'; group: string | null; order: 'travel' | 'name' };
export type OverviewUrl = { view: 'home' | 'attention' | 'area'; tab: 'pressure' | 'under'; area: string | null };
export function parseAdvisorUrl(search: string | URLSearchParams): AdvisorUrl;
export function parseOverviewUrl(search: string | URLSearchParams): OverviewUrl;
export function workspaceHref(intentId: string, over?: { group?: string | null; order?: 'travel' | 'name'; tab?: 'pressure' | 'under'; area?: string | null }): string;
```

Parsing: an unknown or invalid value gives the default (`view` find, `step` age, `group` null, `order` travel; overview `view` home, `tab` pressure, `area` null). `group` is valid when it matches `/^[a-z][a-z0-9-]{0,63}$/`; `area` when it matches `/^[A-Za-z0-9_-]{1,64}$/`. Unknown keys, including `age`, `postcode`, `need` and `when`, are ignored and never appear in the result.

`workspaceHref` builds `route?` plus parameters in this order: advisor intents start with `mode=find`, then `view` (`find`, `list`, `map`, `why`), then `step` (only for view find; `age` or `need`), then `group` (only for view list or map, when set), then `order=name` (only for view list or map, and only when `name`). Overview intents: `view` (`home`, `attention`, `area`), then `tab=under` (attention only, only when `under`), then `area` (area only, when set). A `nav` intent returns its route with no query. `advisor.service` throws `Error('workspaceHref: advisor.service has no query form')`; an unknown id throws `Error('workspaceHref: unknown intent')`.

- `WS-URL-T01` `parseAdvisorUrl('')` gives `{ view: 'find', step: 'age', group: null, order: 'travel' }`.
- `WS-URL-T02` `parseAdvisorUrl('?mode=find&view=list&group=inpatient-beds&order=name')` gives `{ view: 'list', step: 'age', group: 'inpatient-beds', order: 'name' }`; a `URLSearchParams` gives the same.
- `WS-URL-T03` Invalid values fall back: `'view=x&step=y&group=Bad%20Group&order=z'` gives the defaults.
- `WS-URL-T04` Criteria keys are ignored: `'age=65-79&postcode=DT4%208XX&need=frailty&when=today&view=list'` gives `{ view: 'list', step: 'age', group: null, order: 'travel' }` and the result has exactly the four keys.
- `WS-URL-T05` Advisor hrefs, exactly: `advisor.intake.age` gives `/advisor/v2?mode=find&view=find&step=age`; `advisor.intake.need` gives `/advisor/v2?mode=find&view=find&step=need`; `advisor.results` gives `/advisor/v2?mode=find&view=list`; `advisor.results` with `{ group: 'inpatient-beds' }` gives `/advisor/v2?mode=find&view=list&group=inpatient-beds`; with `{ order: 'name' }` gives `/advisor/v2?mode=find&view=list&order=name`; with both gives `/advisor/v2?mode=find&view=list&group=inpatient-beds&order=name`; `advisor.map` gives `/advisor/v2?mode=find&view=map`; `advisor.reasons` gives `/advisor/v2?mode=find&view=why`; `advisor.new-search` gives the same as `advisor.intake.age`; `advisor.intake.age` with `{ group: 'x' }` ignores the group.
- `WS-URL-T06` `workspaceHref` never emits `age`, `postcode`, `need` or `when`, even when they are passed in `over` (cast to any).
- `WS-URL-T07` `parseOverviewUrl`: `''` gives `{ view: 'home', tab: 'pressure', area: null }`; `'?view=attention&tab=under'` gives `{ view: 'attention', tab: 'under', area: null }`; `'?view=area&area=area-one'` gives `{ view: 'area', tab: 'pressure', area: 'area-one' }`; invalid values give the defaults.
- `WS-URL-T08` Overview hrefs, exactly: `overview.home` gives `/analytics?view=home`; `overview.attention` gives `/analytics?view=attention`; with `{ tab: 'under' }` gives `/analytics?view=attention&tab=under`; with `{ tab: 'pressure' }` gives `/analytics?view=attention`; `overview.area` with `{ area: 'area-one' }` gives `/analytics?view=area&area=area-one`.
- `WS-URL-T09` Errors: `workspaceHref('advisor.service')` throws the message above; `workspaceHref('nope')` throws `workspaceHref: unknown intent`.
- `WS-URL-T10` A `nav` intent returns its route: `workspaceHref('go.planning')` gives `/planning`.

## WS-FRM The frame (no side rail)

Files `frontend/components/workspace/WorkspaceFrame.tsx`, `WorkspaceFrame.module.css`, `WorkspaceFrame.test.tsx`. Presentational. Replaces the rail with a top bar, a left drawer slot and a canvas. It reuses `RoleSwitcher` and `SignOutButton` as `components/shell/TopBar.tsx` does (read it; copy its role-chip logic).

```tsx
export type WorkspaceFrameProps = {
  title: string; organisation?: string | null;
  backHref?: string; backLabel?: string;            // label defaults to 'Back'
  action?: { label: string; href: string };         // the one secondary action
  role?: string; roles?: readonly string[]; roleWords?: Readonly<Record<string, string>>;
  signOut?: SignOutFn; showSignOut: boolean;
  thread: ReactNode;                                // the drawer, or null when hidden or absent
  assistantButton: ReactNode;                       // rendered only when `thread` is null
  footer?: string;
  children: ReactNode;                              // the canvas
};
```

Markup, in order: `<header data-noprint data-el="WS-FRAME-TOP">` holding the back link (when `backHref`: `<a data-el="WS-FRAME-BACK">` with a decorative `‹` (aria-hidden) and the label, first in tab order), `<Logo height={28} />`, a heading block (organisation small line when given, then `<p>` with the title), a spacer, the action link (`data-el="WS-FRAME-ACTION"`), the role chip (a `RoleSwitcher` when `role` is in `roles` and there are two or more, otherwise a `<span data-el="FRAME-ROLE">` with `roleWords?.[role] ?? staffRoleWord(role)`), and `SignOutButton` when `showSignOut`. Then a body holding `<aside aria-label="Assistant" data-el="WS-THREAD">` (only when `thread` is not null) and `<main aria-label="Canvas" data-el="WS-CANVAS">`. Then `assistantButton` (only when `thread` is null). Then `<footer data-el="WS-FRAME-FOOT">` with `footer` when given.

- `WS-FRM-T01` Renders a banner containing the title and the organisation, exactly one `main` landmark named "Canvas" holding the children, and a footer containing the footer text.
- `WS-FRM-T02` There is no `navigation` landmark in the frame.
- `WS-FRM-T03` With `backHref` there is a link named "Back" (or `backLabel`) with that href, and it is the first link in the banner; without it there is no such link.
- `WS-FRM-T04` With `action` there is a link with its label and href; without it none.
- `WS-FRM-T05` A single role renders its plain word (no menu); two or more roles including `role` render the `RoleSwitcher` (a button).
- `WS-FRM-T06` With `thread` there is a `complementary` landmark named "Assistant" containing it and `assistantButton` is not rendered even if passed; with `thread` null there is no complementary landmark and `assistantButton` is rendered.
- `WS-FRM-T07` `showSignOut` true renders the sign-out control (button named "Sign out"); false renders none.
- `WS-FRM-T08` No element has a `style` attribute; the frame passes `runAxe` with every prop set.

## WS-THD The thread drawer and the assistant button

Files `frontend/components/workspace/ThreadDrawer.tsx`, `AssistantButton.tsx`, `Thread.module.css`, `ThreadDrawer.test.tsx`. Presentational. Free text is off: the drawer has no text box.

```tsx
export type ThreadMessage = { id: string; from: 'assistant' | 'person'; text: string };
export type ThreadChip = { label: string; href: string };
export type ThreadSummary = { line: string; changeHref: string };
export type ThreadDrawerProps = { messages: readonly ThreadMessage[]; summary?: ThreadSummary | null; chips: readonly ThreadChip[]; card?: ReactNode; onHide: () => void };
export function ThreadDrawer(props: ThreadDrawerProps): JSX.Element;
export function AssistantButton(props: { onShow: () => void }): JSX.Element;
```

Markup of `ThreadDrawer` in order: a head with `<h2>Assistant</h2>` and `<button type="button" aria-label="Hide the assistant">Hide</button>`; a `<div role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation">` holding one `<p data-from="assistant|person">` per message in order; then the summary block (when given): a label "Criteria set", the line, and `<a href={changeHref}>Change criteria</a>`; then `card`; then `<ul aria-label="Suggested replies">` of `<li><a href>label</a></li>` (only when there are chips); then `<p>Pick an option above</p>`. `AssistantButton` is `<button type="button" aria-label="Show the assistant" data-el="WS-ASSISTANT-BUTTON">` with a decorative `✦` (aria-hidden) and the visible word "Assistant". Root `data-el="WS-THREAD-DRAWER"`.

- `WS-THD-T01` Renders a level-2 heading "Assistant" and a button named "Hide the assistant"; clicking it calls `onHide` once.
- `WS-THD-T02` Messages render in order; each paragraph has `data-from` equal to the message's `from`.
- `WS-THD-T03` The log region (`role="log"`, name "Conversation") has `aria-live="polite"` and contains exactly the messages and nothing else (not the summary, card or chips).
- `WS-THD-T04` With chips there is a list named "Suggested replies" of links with each label and href, in order; with none, no such list.
- `WS-THD-T05` With a summary there is the text "Criteria set", the line, and a link "Change criteria" with `changeHref`; with `null`, none of these.
- `WS-THD-T06` `card` is rendered when given, after the log in document order.
- `WS-THD-T07` The text "Pick an option above" is present and there is no `textbox` in the drawer.
- `WS-THD-T08` `AssistantButton` is a button named "Show the assistant" whose visible text includes "Assistant"; clicking it calls `onShow` once.
- `WS-THD-T09` No element in either component has a `style` attribute.
- `WS-THD-T10` `ThreadDrawer` (with every part) and `AssistantButton` pass `runAxe`.

## WS-TRI The triage card

Files `frontend/components/workspace/TriageCard.tsx`, `TriageCard.module.css`, `TriageCard.test.tsx`. Presentational and controlled. It is the card in the thread (the existing `FindService` form, split in two steps). It reuses `AGE_BANDS`, `NEEDS`, `URGENCIES` and the types from `@/lib/advisor/codes`. There is no Find button: the search starts by itself once the criteria are complete (see WS-ADV).

```tsx
export type TriageCardProps = {
  step: 'age' | 'need';
  age: AgeCode | null; needs: readonly NeedCode[]; urgency: UrgencyCode | null;
  postcodeSlot: ReactNode;      // age step only: the parent's label, PostcodePicker and help text
  canNext: boolean;             // age step: an age is chosen and the postcode is a full one
  onAge: (code: AgeCode) => void; onToggleNeed: (code: NeedCode) => void; onUrgency: (code: UrgencyCode) => void;
  onNext: () => void;
};
```

Age step: `<h3>Step 1 of 2 · Age and postcode</h3>`; a `<fieldset>` with legend "Patient age" holding one `<button type="button" aria-pressed>` per `AGE_BANDS` entry (name = `band.label`); then `postcodeSlot`; then a `<button type="button">Next</button>` with `aria-disabled="true"` while `canNext` is false (a click then does nothing) and the visible hint "Choose an age and a full postcode" while it is false. Need step: `<h3>Step 2 of 2 · Need and timeframe</h3>`; a fieldset "Patient need" with one toggle button per `NEEDS` entry (name = `need.label`); a fieldset "Required timeframe" with one button per `URGENCIES` entry (name = `item.label`); the always-visible hint "Results appear when you choose a need and a timeframe." No Next and no Find button. A pressed button shows a decorative `✓` (aria-hidden) before its label, so its accessible name does not change.

- `WS-TRI-T01` Age step: the heading text; four buttons named "0 to 15", "16 to 64", "65 to 79", "80+", all `aria-pressed="false"` when `age` is null; no need or timeframe controls.
- `WS-TRI-T02` With `age='65-79'` only that button is pressed and it contains an aria-hidden `✓`; clicking a button calls `onAge` with its code (`'16-64'`).
- `WS-TRI-T03` `postcodeSlot` is rendered inside the age step, after the age fieldset and before the Next button.
- `WS-TRI-T04` With `canNext` false, Next has `aria-disabled="true"`, the hint "Choose an age and a full postcode" is visible and clicking does not call `onNext`; with `canNext` true there is no `aria-disabled="true"`, no hint, and clicking calls `onNext` once.
- `WS-TRI-T05` Need step: the heading text; one button per `NEEDS` entry (count equals `NEEDS.length`), named by label, `aria-pressed` reflecting `needs`; clicking calls `onToggleNeed` with the code (`'frailty'`); no age controls.
- `WS-TRI-T06` Two selected needs are both pressed.
- `WS-TRI-T07` Timeframe: buttons "Within 2 hrs", "Today", "Planned"; the chosen one is pressed; clicking calls `onUrgency` with its code (`'planned'`).
- `WS-TRI-T08` The need step shows "Results appear when you choose a need and a timeframe." and has no button named Next or matching /find/i.
- `WS-TRI-T09` Every button has `type="button"`; no element has a `style` attribute.
- `WS-TRI-T10` Both steps pass `runAxe`.

## WS-CRS The criteria summary widget

Files `frontend/components/workspace/CriteriaSummary.tsx`, `CriteriaSummary.module.css`, `CriteriaSummary.test.tsx`. Presentational.

```tsx
export type CriteriaSummaryProps = { age: string | null; district: string | null; needs: readonly string[]; urgency: string | null }; // display labels
```

A `<section aria-label="Criteria">` holding a `<dl>` with four pairs, in order: "Age", "Postcode", "Need", "Timeframe". A set value renders `● value` (the dot is aria-hidden); an unset one renders `○ Not set`. Needs are joined with `, `.

- `WS-CRS-T01` With nothing set there are four terms and four definitions each reading "Not set".
- `WS-CRS-T02` With everything set the definitions read "65 to 79", "DT4", "Frailty" and "Today".
- `WS-CRS-T03` Two needs read "Frailty, Wound care".
- `WS-CRS-T04` The terms are exactly "Age", "Postcode", "Need", "Timeframe", in that order.
- `WS-CRS-T05` No element has a `style` attribute; the component passes `runAxe`.

## WS-PRV The workspace provider

Files `frontend/components/workspace/WorkspaceProvider.tsx` and `WorkspaceProvider.test.tsx`. Client component, React state. It holds the criteria, the opened service, the thread, and the hidden flag.

```tsx
export type Criteria = { age: AgeCode | null; postcode: string; needs: NeedCode[]; urgency: UrgencyCode | null };
export type Opened = { serviceName: string; updated: string; stale: boolean; noReport: boolean };
export type WorkspaceValue = {
  identity: { role: string | null; roles: readonly string[]; organisation: string | null };
  criteria: Criteria; setCriteria(patch: Partial<Criteria>): void; resetCriteria(): void; criteriaComplete: boolean;
  opened: Opened | null; remember(opened: Opened): void;
  messages: ThreadMessage[]; chips: ThreadChip[]; summary: ThreadSummary | null;
  visit(intentId: string, context: DialogContext): void;
  hidden: boolean; hide(): void; show(): void;
};
export function WorkspaceProvider(props: { role: string | null; roles?: readonly string[]; organisation?: string | null; children: ReactNode }): JSX.Element;
export function useWorkspace(): WorkspaceValue; // outside a provider: throws Error('useWorkspace: no provider')
```

Rules. **History** is a list of entries `{ id: `${intentId}#${n}`, intent, echo, reply, chips, card, summaryBox, summaryLine }`. `visit(intentId, ctx)` calls `renderTurn(intentId, ctx, { withEcho: history.length > 0 })`. If the last entry has the same intent, its text is replaced in place (same id); otherwise a new entry is appended with the next counter. `visit('advisor.new-search', ...)` clears the history and the criteria, then visits `advisor.intake.age` with `{}`. **Messages** are every entry flattened as an optional person message (id `${id}:echo`) then an assistant message (id `${id}:reply`), keeping only the last 6 messages. **Chips and summary** come from the last entry only (the triage card is not the provider's: the page renders it). A chip becomes `{ label, href: workspaceHref(chip.intent, chip.params) }` and is dropped when `canOpen(role, chip.intent)` is false (and always when `role` is null). The summary is `{ line: summaryLine, changeHref: workspaceHref('advisor.intake.need') }` when the last entry's turn has `summaryBox` and `ctx.summaryLine` is a string, otherwise null. **Hidden**: the initial value is `tenantStore.get('workspace.assistant.hidden', (v): v is true => v === true) === true`; `hide()` sets it to true with `tenantStore.set(name, true)` and updates state; `show()` calls `tenantStore.remove(name)` and updates state. A throwing store means shown. **`criteriaComplete`** is `normalisePostcode(postcode) !== null && age !== null && needs.length > 0 && urgency !== null`.

- `WS-PRV-T01` The first `visit` yields one assistant message and no person message, even for a turn that has an echo (`advisor.intake.need` with `{ age: '65 to 79', district: 'DT4' }`).
- `WS-PRV-T02` A second `visit` to a different intent appends a person message (the echo) then an assistant message; ids are unique and unchanged across re-renders.
- `WS-PRV-T03` Visiting the same intent as the last entry again with a changed context replaces its reply in place: same ids, same number of messages.
- `WS-PRV-T04` Chips belong to the last entry only. After `visit('advisor.results', { count: 3, order: 'travel' })` the chips are exactly `[{ label: 'List by name', href: '/advisor/v2?mode=find&view=list&order=name' }]` for role `advisor`.
- `WS-PRV-T05` A chip whose target intent the role cannot open at the live phase is dropped: with `{ count: 3, order: 'travel' }` there is no "List and map" chip for role `advisor`; with role `null` there are no chips at all.
- `WS-PRV-T06` `visit('advisor.new-search', {})` empties the criteria and history, then leaves exactly the `advisor.intake.age` reply, with no person message.
- `WS-PRV-T07` After ten visits to alternating intents only the last 6 messages remain.
- `WS-PRV-T08` `setCriteria` never calls `localStorage.setItem` or `sessionStorage.setItem` and never changes `window.location`; a second `WorkspaceProvider` instance starts with empty criteria.
- `WS-PRV-T09` `hidden` is false with an empty store; `hide()` makes it true and `tenantStore.get('workspace.assistant.hidden', ...)` returns true; `show()` makes it false and removes the key; a provider mounted with the key present starts hidden.
- `WS-PRV-T10` When `tenantStore.get` and `set` throw, `hidden` starts false and `hide()` still sets it true without throwing.
- `WS-PRV-T11` `criteriaComplete` is true for age `'65-79'`, postcode `'DT4 8XX'`, needs `['frailty']`, urgency `'today'`; false when any one is missing, and false for postcode `'DT4'`.
- `WS-PRV-T12` After `visit('advisor.results', { count: 3, order: 'travel', summaryLine: '65 to 79 · DT4 · Frailty · Today' })` the summary is `{ line: '65 to 79 · DT4 · Frailty · Today', changeHref: '/advisor/v2?mode=find&view=find&step=need' }`; for any other intent it is null.
- `WS-PRV-T13` `useWorkspace()` outside a provider throws `useWorkspace: no provider`.

## WS-SHL The shell and the page wrapper

Files `frontend/components/workspace/WorkspaceShell.tsx` (server component), `WorkspacePage.tsx` (client component), `WorkspaceShell.test.tsx`, `WorkspacePage.test.tsx`; modify `frontend/app/(advisor-v2)/layout.tsx` and add `frontend/app/(advisor-v2)/layout.test.tsx`. `WorkspaceShell` is `StaffShell` (`frontend/app/StaffShell.tsx`, read it) without the rail: it reads `getSession()` and `currentProfile()` (a failure of either is the same as none) and renders `<WorkspaceProvider role roles organisation>{children}</WorkspaceProvider>`. `WorkspacePage` is the page-level client wrapper:

```tsx
export function WorkspacePage(props: { title: string; backHref?: string; backLabel?: string; action?: { label: string; href: string }; withThread: boolean; card?: ReactNode; children: ReactNode }): JSX.Element;
```

It reads `useWorkspace()` and renders `WorkspaceFrame` with `organisation`, `role`, `roles` from `identity`, `showSignOut` true exactly when `identity.role` is not null, `footer` the existing `V2_BROWSE_NOTE` from `lib/advisor/v2/overview`, `thread` a `ThreadDrawer` (messages, summary and chips from the provider, `card` from its own `card` prop, `onHide={hide}`) when `withThread && !hidden`, otherwise null, and `assistantButton` an `AssistantButton` (`onShow={show}`) when `withThread && hidden`, otherwise null.

- `WS-SHL-T01` `WorkspaceShell` with a session `{ role: 'advisor-v2' }` and a profile `{ displayName: 'Test Organisation' }` renders its children inside the provider: a child calling `useWorkspace()` sees `identity` `{ role: 'advisor-v2', roles: ['advisor-v2'], organisation: 'Test Organisation' }` (mock `@/lib/auth/session` and `@/lib/tenant/profile`).
- `WS-SHL-T02` With no session (`getSession` rejects) `identity.role` is null and `identity.organisation` still comes from the profile; with no profile it is null.
- `WS-SHL-T03` `WorkspacePage` with `withThread` and the provider not hidden renders the drawer (complementary "Assistant") with the provider's messages; clicking "Hide the assistant" removes the drawer and shows the "Show the assistant" button.
- `WS-SHL-T04` `WorkspacePage` with `withThread={false}` renders neither the drawer nor the assistant button, even when `hidden` is true.
- `WS-SHL-T05` The frame receives the title, organisation, the role's word and a "Sign out" control when `identity.role` is set; with a null role there is no sign-out control and no role word.
- `WS-SHL-T06` `app/(advisor-v2)/layout.tsx` renders `WorkspaceShell` around its children and no longer renders `StaffShell`.

## WS-ADV The advisor workspace (find a service)

Files `frontend/components/workspace/AdvisorWorkspace.tsx`, `AdvisorWorkspace.module.css`, `AdvisorWorkspace.test.tsx`. Client component that fills `WorkspacePage` for `mode=find`. It reads `useSearchParams()`, `useRouter()` from `next/navigation` and `useWorkspace()`. Tests mock `next/navigation` (`useRouter` gives `{ push, replace }` spies, `useSearchParams` gives a `URLSearchParams` from a variable the test sets) and use msw for the find endpoint exactly as `AdvisorV2.test.tsx` does.

Behaviour, exactly:

1. **State.** `parseAdvisorUrl(searchParams)`; criteria and the opened service come from the provider. A view of `map` or `why` is treated as `list` (those intents are not live).
2. **Gate.** When the view is `list` and `criteriaComplete` is false, or the step is `need` and age or a full postcode is missing, call `router.replace` once with `workspaceHref('advisor.intake.need')` when an age is chosen and the postcode is a full one, otherwise `workspaceHref('advisor.intake.age')`.
3. **Intake, age step.** The canvas shows `CriteriaSummary` and a "Services" panel whose status text is the existing "Choose the postcode, age, need and time to list services.". The thread card is `TriageCard step="age"`; `postcodeSlot` is the label "Postcode", the existing `PostcodePicker` and the help paragraph, with the same ids, suggestion and lookup behaviour and help texts as `FindService` (copy that logic: `suggestPostcodes`, `locatePostcode`, blur normalises with `normalisePostcode`). `canNext` is "an age is chosen and `normalisePostcode(postcode) !== null`". Next calls `router.push(workspaceHref('advisor.intake.need'))`.
4. **Intake, need step.** `TriageCard step="need"`. The search runs without a button: when `criteriaComplete`, after 250 ms, once per distinct (normalised postcode, age, sorted needs, urgency), call `findServices({ postcode, ageBand, needs, urgency })`. On success or failure call `router.push(workspaceHref('advisor.results'))`. A change of criteria after results discards the old result.
5. **Results.** The canvas shows `CriteriaSummary`, the status text (`"{groups} service groups · {total} services"`, or `"{n} matching services"` inside a group), then, with no group, a `PagedGrid` of group cards (label "Service groups", noun "service groups", the pill `"{n} of {max} services"`, exactly as `FindService`), or, with a group, a "Return to service groups" button (pushes the href without `group`), the existing sort toolbar and a `PagedGrid` of `ServiceTile`. Opening a group pushes `workspaceHref('advisor.results', { group, order })`. The order buttons push the href with `order`. Each tile is wrapped in an element with `onClickCapture` that calls `remember({ serviceName, updated, stale, noReport })` (WS-DATA) without altering `ServiceTile`. A failed search shows the existing alert text; zero services show the existing note.
6. **Thread.** An effect calls `visit(...)`: `advisor.intake.age` with `{}`; `advisor.intake.need` with `{ age, district }`; `advisor.results` with the WS-DATA context. The `TriageCard` is passed to `WorkspacePage` through its `card` prop (intake views only; none on results).

- `WS-ADV-T01` Hard load with no parameters: the frame title is "Find a service", the drawer shows the assistant message "Let's find a service for your patient. Two short steps, then I will show who can take them.", the age-step card is shown, the criteria summary reads "Not set" four times, and there is no `navigation` landmark.
- `WS-ADV-T02` Choosing "65 to 79" and typing and accepting a full postcode (msw suggestion `DT4 8XX`) enables Next; clicking it pushes `/advisor/v2?mode=find&view=find&step=need`; the thread then shows a person message "65 to 79 · DT4" and the assistant message "What does the patient need, and by when?"; the summary cell reads "DT4" and the full postcode appears only inside the postcode field.
- `WS-ADV-T03` On the need step, choosing "Frailty" and "Today" and advancing timers by 250 ms sends exactly one `POST /api/bff/advisor-v2/find` whose JSON body is `{ postcode: 'DT4 8XX', ageBand: '65-79', needs: ['frailty'], urgency: 'today' }`; no button matching /find/i exists on the screen.
- `WS-ADV-T04` After a successful search the router is pushed to `/advisor/v2?mode=find&view=list`; with that URL the thread shows "N services meet this patient's criteria, sorted by travel time. Not ranked." (N is the number of services in the answer) and the summary block reads "65 to 79 · DT4 · Frailty · Today" with a "Change criteria" link to `/advisor/v2?mode=find&view=find&step=need`.
- `WS-ADV-T05` Results canvas: the group cards show pills like "3 of 5 services"; clicking a group pushes `…&view=list&group=<category>`; with that URL the service tiles show and a "Return to service groups" button pushes the href without `group`; clicking a tile calls the provider's `remember` with that service's name.
- `WS-ADV-T06` The thread chip "List by name" links to `/advisor/v2?mode=find&view=list&order=name`; with that URL the thread reply is "N services meet this patient's criteria, listed by name. Not ranked." and the tiles are ordered by name.
- `WS-ADV-T07` A failed search (msw 500) shows the alert "The services could not be searched. Change a choice to try again, or phone the services." and the thread reply is the same sentence.
- `WS-ADV-T08` An answer with no services shows the note "No service takes this patient on its criteria. Phone to confirm, or change the criteria." and the thread reply is the same sentence.
- `WS-ADV-T09` Privacy: through a whole flow no URL passed to `push` or `replace` contains `age`, `postcode`, `need`, `when` or the text `DT4`; `localStorage.setItem` and `sessionStorage.setItem` are never called except for the key `overwatch:v1:workspace.assistant.hidden` after "Hide the assistant"; the only request carrying the postcode is the find request.
- `WS-ADV-T10` Clicking "Hide the assistant" removes the drawer and shows "Show the assistant"; clicking that restores the drawer with the same messages; remounting the provider keeps it hidden.
- `WS-ADV-T11` Hard load at `?view=list` with no criteria calls `router.replace` once with `/advisor/v2?mode=find&view=find&step=age`; with an age and a full postcode set but no needs, once with `…step=need`.
- `WS-ADV-T12` `?view=map` with complete criteria is shown as the list and does not call `replace`.
- `WS-ADV-T13` The age step, the need step and the results all pass `runAxe`.

## WS-SVC The service page inside the workspace

Files `frontend/components/workspace/ServiceWorkspace.tsx`, `ServiceWorkspace.test.tsx`; modify `frontend/app/(advisor-v2)/advisor/v2/services/[id]/page.tsx` and `page.test.tsx`. `ServiceWorkspace({ serviceId })` is a client component that renders `WorkspacePage` (title "Service detail", `backHref={workspaceHref('advisor.results')}`, `withThread`) around the existing `ServiceDetail` (`backHref` the same href, `backLabel="Back to results"`, `rootLabel="Find a service"`), and calls `visit('advisor.service', context)` in an effect with the WS-DATA service context from the provider's `opened` (empty context when `opened` is null). The page stays a server component that awaits `params` and renders `<ServiceWorkspace serviceId={id} />`.

- `WS-SVC-T01` Renders `ServiceDetail` for the id inside the frame titled "Service detail" (mock `ServiceDetail` and assert its `serviceId`).
- `WS-SVC-T02` The frame's back link is named "Back" and points to `/advisor/v2?mode=find&view=list`.
- `WS-SVC-T03` With an earlier results turn in the thread and `opened` `{ serviceName: 'Alpha', updated: '1 hr 55 min ago', stale: false, noReport: false }`, the thread shows the person message "Open Alpha" and the assistant message "Here is Alpha. Last updated 1 hr 55 min ago. If the call allows, check that it is current."
- `WS-SVC-T04` On a hard load (no `opened`, empty history) the thread shows only the assistant message "Here is the service. If the call allows, check that its figure is current." and a chip "Back to results" linking to `/advisor/v2?mode=find&view=list`.
- `WS-SVC-T05` The page component renders `ServiceWorkspace` with the `id` from its `params`.

## WS-RTE The other pages of the group

Files modify `frontend/app/(advisor-v2)/advisor/v2/page.tsx` and its `page.test.tsx`, `frontend/app/(advisor-v2)/advisor/v2/services/page.tsx` (and add `services/page.test.tsx` if none exists). Read each page and its test first.

- `/advisor/v2` with no `mode` or `mode=capacity` renders `<WorkspacePage title="Capacity" withThread={false}>` holding the existing `V2Switch current="capacity"` and `CapacityOverview`; `mode=find` renders `<AdvisorWorkspace />` and nothing else (it supplies its own frame). The page no longer renders `<main>` or the `<h1>Advisor v2</h1>`.
- `/advisor/v2/services` renders `<WorkspacePage title="Services" backHref="/advisor/v2" withThread={false}>` holding the existing `V2Services` with the same props as today.

- `WS-RTE-T01` Capacity: with no `mode` the output contains the frame titled "Capacity", `V2Switch` with `current="capacity"` and `CapacityOverview`, and no "Assistant" complementary landmark.
- `WS-RTE-T02` `mode=find` renders `AdvisorWorkspace` (mock it) and not `FindService`, `CapacityOverview` or a second frame.
- `WS-RTE-T03` The services page renders `V2Services` inside the frame titled "Services" with a "Back" link to `/advisor/v2`, passing the same `initial`, `group`, `district` and `area` as before.
- `WS-RTE-T04` Rendered with the real components, each of the three page outputs contains exactly one `main` landmark.

## WS-OVW The overview workspace (phase 2, outline)

Status: outline. A builder starts by reading `components/analytics/AnalyticsOverview.tsx`, `AttentionPanel.tsx`, `Drill.tsx` and their tests, then refines these cases in a short plan before any code (Sonnet only). It wraps the existing aggregate components in `WorkspacePage` for the role `analytics-user`, with the thread, and adds `searchParams` handling to `app/(analytics)/analytics/page.tsx` through `parseOverviewUrl`. Its layout must stop using `StaffShell` for these pages in the same way as `(advisor-v2)`. It adds no new data and never shows a case, patient, postcode or outcome.

- `WS-OVW-T01` `/analytics` (view home) shows the existing overview inside the frame with the drawer, and the thread shows the `overview.home` reply for its context (`dialog.json` D13 or D14).
- `WS-OVW-T02` `view=attention` shows the attention list and the thread reply matches `overview.attention` for the effective tab; when the requested tab is empty and the other is not, the other tab is shown and the reply says so (D19).
- `WS-OVW-T03` `view=area&area=<known id>` shows that area and the `overview.area` reply (D20 or D21); an unknown area id calls `router.replace` to the home href.
- `WS-OVW-T04` The existing aggregate-only assertions of `AnalyticsOverview.test.tsx` still pass unchanged, and the thread never contains a postcode, case or patient word.
- `WS-OVW-T05` The overview pages have no `navigation` landmark from a rail and exactly one `main`.

## WS-DEV Where the boards and this spec differ (the spec wins)

| Board | Board shows | Spec | Why |
|---|---|---|---|
| A1, A2 (intake) | Postcode "DT4", a "Find services" button | A full postcode; no Find button; search starts by itself after 250 ms | `FindService` already decides this (DEC-1366) |
| A1, A2 | Age chips "65–79", "0–15" | `AGE_BANDS` labels: "65 to 79", "0 to 15" | Reuse the existing codes and labels |
| A3 | A flat list of services | Group cards first, then the services of one group | The existing finder works this way |
| A3 | Five rows, a fixed "1–5 of 7" | `PagedGrid`: as many rows as fit; "Page 1 of 2 · 7 services" | Existing component fits rows to the height |
| A4 (map), A6 (not suitable) | Screens | Not built: `/advisor-v2/find` returns no positions, coverage or not-suitable list (registry phase 4) | Needs back-end fields first |
| A5 | "Choose this service" panel; "matches on age, need, area, timeframe" | Not built; the thread says "Here is …. Last updated …" | v2 is browse-only; the data has no match statement to quote |
| All | Mark "O" | `<Logo height={28} />` | The brand mark and name come from one place |
| All | Page number in the URL | Not in the URL | `PagedGrid` keeps its page itself; Back returns to page 1 of the same list |
| O1 to O3 | Chips "Service groups", "Compare two areas" | Not drawn until those views exist | No dead chips |
| M, D, P, R, W | Hub, reporter, platform, wall screens | Not specified here (phase 3 and later) | See `README.md` |
