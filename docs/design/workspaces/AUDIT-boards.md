# Artboards against the implementation (2026-11-10)

Owner's request: look at each artboard, find its implementation and match it, using real data in place of the fixtures. This is that audit. A board is **Built** when the screen exists and follows the board, **Partly** when it exists but differs, **Not built** when there is no screen. "Why" is the real reason, not a guess. Checked against the code on `rename-overwatch`, not against the units' `status` field (which is stale: it says `todo` for units that were built).

## Advisor

| Board | State | What is there | What differs from the board | Why / what it needs |
|---|---|---|---|---|
| AdvisorIntake1 | Built | Triage card, age and postcode, in the thread. | - | - |
| AdvisorIntake2 | Built | Need and timeframe, criteria tiles. | - | - |
| AdvisorResults | **Partly** | Group cards, then the services of a group, paged. | Board: one flat list of all matching services, sorted by travel, "1-5 of 7" with Previous and Next, a **List / List and map** switch, a "Why were 3 not suitable?" chip. Built: group cards first; no switch; no chip. | The group cards come from the owner's SPoA design (DEC-1366). The board was drawn before that code was read (WS-DEV). The owner now says match the board: DEC-1379. |
| AdvisorMap | **Not built** | The thread and the results shown as the list. | The whole screen: pins, the "Who covers this area" layer, the list beside the map, tap a service to open it. | Needs service positions and the coverage area in the find answer (both exist in the back end; the v1 options already use them). Phase 4, never started. |
| AdvisorWhy | **Not built** | - | The whole screen: the services that were not suitable, each with its reason, paged; "nothing is hidden". | Needs the find answer to return the services that failed, with their reasons (`check_hard_criteria` already produces them; `/find` discards them). Phase 4, never started. |
| AdvisorService | **Partly** | Tabs (Capacity, Criteria, Contact), Book a slot (check one patient), Request capacity update. | Board: a "Why it matches this patient" panel (age, need, coverage, timeframe, each "Accepted"/"Covered"), a **Choose this service** button, a contact block. Built: no match panel; no Choose button; "Book a slot" asks the questions again even when the criteria are already set. | The match panel is what the new check returns (`reasons`, `fitsNeeds`): when criteria are set, call it on arrival. "Choose this service" opens a case, which is phase 6 (DEC-1378). |
| TriageChat, TriageResults | Superseded | - | Early chat prototypes; AdvisorIntake1/2 and AdvisorResults replace them. | - |

Not on any board and not data: the board labels "Visits the patient / Goes to a place / Remote" have no source field in the back end (no delivery-mode code exists). They are **not shown** until the directory holds one; nothing is invented. The boards' "Demonstration data" strip and "Dorset" label are fixtures and are not built.

The board's "Why" rows include status reasons ("Over capacity", "Not accepting"). In v2 a service's status never excludes it (DEC-1366), so those services stay on the list with their status; "not suitable" means it failed the hard criteria (area, age, need) or is suspended or has no current criteria.

## The other boards

| Board | State | Notes |
|---|---|---|
| Shell | Built | One frame, no rail (WorkspaceFrame). |
| Main, Pages, Capabilities | Reference | Index and role-capability boards, not screens. |
| OverviewHome, OverviewAttention, OverviewArea, Overview | **Not built** | Phase 2, WSP-13, blocked on four dialog fixes (WS-OVW-analysis.md). |
| ManagerHome, ManagerPeople, ManagerRemove | **Not built** | Phase 3, go-to intents only; the existing lead pages stay. |
| AdminHome, AdminAccess, AdminLayouts | **Not built** | Phase 3; the existing admin pages stay. AdminLayouts is the no-code builder (later). |
| PlatformHome | **Not built** | Not specified (its own door and session, DEC-528). |
| ReporterServices, ReporterCount, ReporterConfirm, ReporterStatus, ReporterDone | **Not built here** | The reporter app has its own units; check them before changing it. |
| WallScreen | **Not built here** | The wall display exists separately; not part of this kit. |

## What this means

Phase 1 delivered the advisor find path (intake, results, service) and the shell. The boards for the map, the reasons, the overview, the hubs and the reporter were never built; that was the plan (README, Phases), but it was not said clearly enough to the owner, and AdvisorResults and AdvisorService were marked done while differing from their boards. This file is the record.

## Work, in order

1. **Back end (find answer).** Add to `POST /advisor-v2/find`: each found service's `position` (latitude, longitude, or null), the `coverage` (district list; the circle if the v1 rule is reused), and `notSuitable[]` (service id, name, category, status, the reasons) for every service that failed the hard criteria, was suspended or had no criteria. Nothing about the patient is stored or audited (as now).
2. **AdvisorResults** to the board: a flat list sorted by travel, 5 rows a page, the List / List and map switch, the not-suitable chip. Groups become a label on the row.
3. **AdvisorMap** to the board, reusing the existing map components (`TileMap`, `Basemap`, `OptionsMap`) and the "Who covers this area" layer.
4. **AdvisorWhy** to the board, paged.
5. **AdvisorService** match panel from the check (when criteria are set); the contact block.
6. Then phase 2 (overview), after the dialog fixes.

Each step: tests from numbered cases in `screens.md`, build, then an independent check, and a side-by-side with the board in a browser before it is called done.
