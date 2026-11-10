# Workspaces: the design and build kit (DEC-1376)

The chat-and-canvas workspaces, the assistant's intents, and the no-rail shell, cut into units that small models can test and build. Nothing here is built. The look is in `boards/` (exported from the design canvas); the decision is DEC-1376 in `docs/delivery/decisions.md`.

| File | What it is |
|---|---|
| `registry.json` | Who may open which intent: personas, flags, the session-role adapter, layouts, 22 intents with phases. Runtime copy goes to `frontend/lib/workspace/`. |
| `dialog.json` | Every assistant line as a template, every chip as an intent id, and 27 worked examples. Runtime copy goes to `frontend/lib/workspace/`. |
| `screens.md` | The spec: conventions, data rules, the access matrix, and 13 components or screens with 106 numbered test cases. |
| `units.json` | 13 build units: files, dependencies, the cases each owns, and which model tests, builds and verifies. |
| `check.py` | `python docs/design/workspaces/check.py`. Renders every dialog example, checks the registry against the real route guard, and checks units against screens. Run it before and after any change here. |
| `boards/` | The canvas boards (`*.dc.html`, `shell.css`) as the visual reference. Where a board and `screens.md` differ, `screens.md` wins (WS-DEV lists them). |

## What the spec found in the existing code, and changed

Reading the v2 finder before specifying it changed the plan. These are decisions about what is buildable now, not preferences.

- **No Find button.** `FindService` searches by itself once a full postcode, age, need and time are set (DEC-1366). The triage card follows that.
- **Criteria never go in the URL.** The finder keeps the postcode only in its form. The workspace keeps criteria in memory and the URL holds only where you are (`view`, `step`, `group`, `order`).
- **Map and "not suitable, and why" cannot be built yet.** `/advisor-v2/find` returns no positions, no coverage areas and no not-suitable list, so those two intents are phase 4 and need back-end fields first.
- **v2 is browse-only.** No "choose this service" and no match statement exist; the boards show them, the spec does not.
- **Paging is height-fit.** `PagedGrid` fits as many rows as the height allows. The page number is not in the URL, so Back returns to page 1 of the same list.

## Phases

| Phase | Scope | Units |
|---|---|---|
| 1 | Advisor find workspace on today's data: intake in the thread, results (groups, then services), service detail, no rail, capacity and services pages in the new frame. | WSP-01 to WSP-12 |
| 2 | Overview workspace on `/analytics` (aggregate data that exists). Outline only. | WSP-13 |
| 3 | Go-to intents for Manager and Admin hubs, and "pre-fill then you confirm" hand-overs. Registry entries exist; no screens specified. | none yet |
| 4 | Map and reasons. Back end first: positions, coverage and not-suitable reasons in the find answer. | none yet |

What to retire, in what order and behind which gates is in `ROLLOUT.md`.

Not specified here: the reporter flow (the reporter app has its own units, check them before changing it), the platform console, the wall display, and the consolidation of the 14 session roles into 6 (a back-end and mapping change that needs its own design). Until then the registry's `adapter` maps today's session roles to personas and flags in the front end only.

## How a unit runs

Each unit runs under `docs/design/redesign/AGENT-GROUND-RULES.md` (worktree, test first, commands, report). The steps and the model for each:

| Step | Who | Output |
|---|---|---|
| 1. Write the tests | Haiku, from the unit's case list in `screens.md` only | Test files that load against stubs and fail by name (the red run) |
| 2. Build | Haiku for 9 units, Sonnet for 4 (WSP-08, 09, 10, 13) | Code that turns the red run green; tsc, eslint and `test/guards` clean |
| 3. Verify | Sonnet in a different session, from a clean worktree | Pass or fail against the cases, the privacy rules and the guards |
| 4. Escalate | Sonnet builds the fix round after a FAIL on logic, tenancy, security or concurrency; the orchestrator rules on a second FAIL (DEC-141) | A fix and a line in the evidence |

Haiku writes the tests for all 13 units, including the four Sonnet builds, because the cases are written out to the assertion. Sonnet is used where the work is judgement: the stateful core, the server-side session reads, the composition with the router, and the outline unit.

## Why a unit is Haiku-ready

`check.py` fails a Haiku unit that lacks any of these:

1. Exact files to add and modify, and files it must not touch (`forbidden`).
2. A spec anchor in `screens.md` with props as TypeScript, exact strings and exact DOM order.
3. Numbered test cases, each one assertion, with the expected text written out.
4. Table-driven tests where possible (`dialog.json` examples, the access matrix, URL hrefs), so the test is a loop and not a design.
5. No choices left: libraries, endpoints and existing components to reuse are named, and nothing may be invented.

A unit that cannot meet these is Sonnet's (WSP-13 is an outline, so it is).

## Waves

| Wave | Units |
|---|---|
| 0 | WSP-01, 02, 04, 05, 06, 07 (independent, run in parallel) |
| 1 | WSP-03 (needs 01) |
| 2 | WSP-08 (needs 01, 02, 03, 05) |
| 3 | WSP-09 (needs 04, 05, 08) |
| 4 | WSP-10 (needs 02, 03, 06, 07, 08, 09), WSP-11 (needs 08, 09) |
| 5 | WSP-12 (needs 09, 10), WSP-13 (outline; start after WSP-10 is verified) |

## Open items

- **Back end for phase 4.** Add `position`, `coverage` and a not-suitable list with reasons to `/advisor-v2/find`.
- **`ServiceDetail` has its own back link** as well as the frame's Back; both go to the same place. Removing one is a change to `ServiceDetail`.
- **Page number in the URL** needs `PagedGrid` to take a controlled page.
- **Product name.** The UI still says what `lib/product.ts` and `public/brand` say; the AQIKO rename is separate. The frame takes the mark and name from `Logo`, so it follows the rename.
- **A user-facing wording review** of `dialog.json` (it is the product's voice) before release.
