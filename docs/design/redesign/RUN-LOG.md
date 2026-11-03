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
