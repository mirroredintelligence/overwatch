# Redesign run log

One entry per merged unit: what the agent reported, in a form meant for the validation pass. Deviations are where the built page differs from its artboard; gaps are where the board shows something the data does not have. Everything here is from agent reports and from tests; nothing has been looked at in a browser.

Base: `rename-overwatch`. Foundation merged first (DEC-1326).

## Steering notes (what the early reports taught the prompts)

- A quoted heredoc silently cut two test files (ADM-00a/b agents): the rules now ban heredocs for files.
- Agents change a board's layout where it conflicts with a rule (an add panel that was open on the board is closed until chosen; a primary button of 48px becomes 52px). They say so in the report; the rule wins.
- A unit that is told to build one thing sometimes needs a shared piece that does not exist (a status shape, a card); it builds a local one and says so. Collect these and promote them in a cleanup unit.
- Several boards show their own sample numbers and times: agents correctly did not hard-code them.

## Units

### NET-00 (sonnet) scope header, notices
Red 7, green 191 in scope and network folders. Deviations: refusal panels are single neutral panels, not the board's tile grid; raw `#fff` for switch and link surfaces. Wanted but left: `ui/Banner.module.css` (board's notices differ: 10px radius, full 2px border, 15px body; the offline Banner keeps the old look).

### OPR-12 (haiku) administrator approval return page
Red 6, green 12. Deviations: shows only the outcome the server returns, not the catalogue of five; non-approved outcomes use the board's fixed copy, not the server's reason string (assertions that the reason text appears were replaced with the board's sentences); "Check again" is 52px; raw `#7A3500`. Open: "Check again" is a GET form that re-runs the server check with the same state: confirm the back end accepts the same state twice.

### ADM-00a (sonnet) SettingGroup, SettingRow, ApprovalMeter, DiffPair
New folder `components/blocks`, 21 tests. SettingGroup is built on `Disclose` (its card style, not the board's white 2px card). `open`/`onToggle` are passed by the page so only one group is open.

### ADM-00b (sonnet) TaskRow, ContactRow, RetentionChips, TimelineList, ProgressBar5
22 tests. Narrow layouts added below 40rem (boards show only 1280px). ContactRow has a `nameAction` prop for repeated "Edit" buttons.

### LDR-10 (haiku) audit search and replay
Red 10, green 20 (167 in the folder). Deviations: "Looked at today" not built (memory-only, optional); the kicker moved to the shell top bar; kept the "Read-only... a log of who looked" line the board omits; moved `<main>` into the two page files. `lib/lead/format.ts replayStampText` may now be unused.

### LDR-05 (haiku) services in scope
Red 10 of 12, green 12 (210 in folders). Deviations: add panel closed until the person asks (the board shows it open); category is a radio-chip group from the 8 real categories; on phones the panel is a full-screen sheet (CSS only); `StatusMark` is local to `ScopeList.tsx` (the shared StatusTag has no ring or diamond). Unverified: the two-column layout inside the centred `.page` column at 1280px.

### (shared) StatusTag gains `confirmed` (tick) and `due` (clock)
Added by the orchestrator for the reporter units.

## Wave log (units merged, with what to look at)

Merged after the foundation and the first pilot (above): ADV-00, ADV-01..04, ADV-06, ADV-07, ADV-12, ADM-01, ADM-02, ADM-07, ADM-08, BRD-01, CLN-01, CON-01..03, COV-01, CRI-01, CRI-05, CRI-06, LDR-02, LDR-03, LDR-05, LDR-06, LDR-08, LDR-10, LDR-11, LDR-12, LED-00a/b, LRV-01, NAD-01, NET-00, NET-03..05, NET-07, ONB-00..02, ONB-04, ONB-01, OPR-01, OPR-04, OPR-11, OPR-12, PLN-00a/b, PLN-01, PUB-00, REP-00a/b. Every merge was followed by tsc and the tests of the touched folders plus `test/guards`; the full suite ran green apart from two known map-page tests (to be fixed by the advisor map unit, ADV-10).

### Decisions and questions for the owner (collected from agent reports)

- **Admin overview (ADM-01)** now makes four reads; a failure of any fails the whole page. Change to degrade per section.
- **Criteria history (CRI-06)** cannot show who sent or approved a version, or what changed (not in the data). **Second approval (CRI-05)** has no version numbers or send time.
- **Support requests (ADM-08)** cannot show a request number or the requester; access log and requests stay on separate routes (the board shows them side by side).
- **Console (CON-01..03)**: "When" chips and the Exec chip are not supported by the data; "Show example sessions" and "Open the query in the matrix" have no route. The console had no layout at all; one was added (frame with Sessions and Insight).
- **Needs form (ADV-03)**: the live count is not wired (the case page makes no options read), so the card says "No count yet" and the button stays "See options".
- **Booking exceptions (ADV-06)**: "I have phoned the caller" stays primary (DEC-854 wants an explicit acknowledgement), against the board's "See options again". No caller phone in the data, so no "Phone the caller" button.
- **Action dialogs (ADV-07)**: the board's full postcode in "ask a clinical advisor" conflicts with the district-only policy; district kept.
- **Outcome (ADV-12)**: "Anything free-typed on the call" is listed as cleared because the board says so; confirm the app really clears it before release.
- **Clinical (CLN-01)**: "2 on duty" not shown (the read returns "available now", not "on duty"); the phone push alert has no endpoint.
- **Add a service (LDR-03)**: three steps built; the fourth (Check) is LDR-04; "who owns these criteria" dropped (not in the body).
- **Phones (LDR-06)**: the board says "last four digits", fixtures give three: confirm what the BFF returns. "Remove access" links with `?person=<digits>`; the remove page (LDR-08) does not read that parameter yet.
- **Remove access (LDR-08)**: the "who" field stays a select of reporter posts (the BFF needs the role id), not the board's typed field.
- **Network admin (NAD-01)**: "a second administrator must confirm" when ending a membership has no endpoint; health shows source state only (no last update, delay or refused count).
- **Network history (NET-07)**: "last shown" time and last known figure are not in the data.
- **Operator audit (OPR-11)**: the verification endpoint returns only intact or not, so "214 entries checked, last check at 09:00" and "broken at entry n" cannot be shown.
- **Operator sign-in (OPR-01)**: the h1 stays "Platform console" because a test outside the unit asserts it; the board headline is the lead's first sentence.
- **Operator funnel (OPR-04)**: extracted into one file per step with no behaviour change (155 tests, same names before and after).
- **Planning home (PLN-01)**: the figure changes size at once (no animation, as the rules say); the morph between routes is not browser-tested.
- **Set-up (ONB-01, ONB-02, ONB-04)**: number check and code entry remain two states; the telemetry `data-el` ids on the home-screen and notification buttons were dropped because the provider shell has no `dataEl` prop (see follow-ups); `e2e/reporter.spec.ts` asserts two old strings (expired invitation text, channel heading).
- **Clinical wording**: staff header says "Clinical advisor", admin says "Clinical lead".

### Follow-ups the orchestrator must do (not given to a unit)

1. Add a `dataEl` prop to the provider shell's action controls so telemetry ids work again (ONB-02 dropped five).
2. Promote shared pieces several units wanted: `Dialog` (`className`, a slot above the title, an `initialFocus`), `Button` (a dark/danger variant), `Disclose` (white surface), `Chip` (light selected variant), `StageGrid` (an in-flow current layer; a two-track mode), `MorphStage` (stage landmark vs the panels' `<main>`), `Network.module.css` page ground (`--c-ground`).
3. Make the admin overview degrade per section.
4. `app/(advisor)/advisor/board/loading.tsx` (3 lines) so the new `BoardLoading` is used.
5. Update `e2e/*.spec.ts` strings the redesign changed, and run Playwright if possible.
6. Make the remove-access page read `?person=`.
7. Move `LadderTimeline`/`StatusMark`/`StackedBar` duplicates into shared files if a later unit needs them.
