# Rollout and retirement plan (DEC-1376)

Status: proposal for the owner. It sits on the build kit in this folder (`README.md`, `units.json`) and changes nothing by itself. Facts below come from the code and `docs/design/redesign/RUN-LOG.md` as read on 2026-11-10; where I have not checked something it says so.

## What "the old ones" are

The app has 151 pages. Three different things could be called old, and only the first is retired by the new design:

1. **Code the new workspace replaces outright.** `components/advisor-v2/FindService.tsx` (the finder form) once `AdvisorWorkspace` is live and verified.
2. **Roles that exist only as rollout flags.** `advisor-v2` (DEC-1362) folds into `advisor`.
3. **The v1 advisor call flow** (`/advisor`, `/advisor/board`, `/advisor/case/[ref]/*`: options, compare, ways, map, finish). The new design does **not** replace it. v2 is browse-only (no case is opened, nothing is stored), so v1 is the only place a call is recorded and finished. Retiring it needs a design that does not exist yet.

The earlier rail-based redesign (132 units) is mostly merged: the run log lists units from the advisor, admin, lead, planning, network, onboarding, console and public surfaces as merged (for the reporter, only the shared REP-00a and REP-00b), but `units.json` still says `todo` for 131 of them. The log is the better record; reconcile `units.json` before anyone plans from it. Those pages stay as they are. The new design changes the shell (no rail) only for the two workspaces.

## Disposition by area (proposed)

| Area | Disposition | When |
|---|---|---|
| Advisor find, capacity and service detail (`/advisor/v2/*`) | **Replace** with the workspace (WSP-01 to WSP-12). Delete `FindService` after verification. | Phase 1 |
| Overview (`/analytics/*`) | **Wrap** in the workspace (WSP-13). Nothing deleted. | Phase 2 |
| v1 call flow (`/advisor/*`) | **Keep.** Decide separately (decision 1 below). | Not planned |
| Clinical (`/clinical/*`) | **Keep** until the clinical flag exists on Advisor. | With roles |
| Lead, planning, criteria, admin, network-admin, network | **Keep** as the hubs. Add go-to intents and the pre-fill hand-overs. | Phase 3 |
| Operator, console, wall, public, register, help | **Keep unchanged.** | none |
| Reporter app (`/app/*`, `/setup/*`) | **Keep.** My reporter boards are a sketch; compare with the merged REP and ONB units before changing anything. | Decide |

## How a retirement is done (the gate)

Nothing is deleted on a date. A retirement happens only when all hold, and is its own commit so it can be reverted alone:

1. The replacement is live and an independent session has verified it against its cases.
2. Usage shows people are on it. The console Insight funnels and the `data-el` telemetry exist for this; read them before deleting, do not assume.
3. The end-to-end specs that name the old pages are moved or removed in the same change (about 30 files sit in `frontend/e2e`; none has been run in this work).
4. The old address redirects for one release (the pattern DEC-1372 used for the Radar address), so bookmarks and links keep working.
5. The repository guards, type check and the full suite pass after the deletion.

## Phases

| Phase | What | Retires | Model |
|---|---|---|---|
| 0 Housekeeping | Reconcile `units.json` with the run log. Do the orchestrator follow-ups in the run log that the new frame also needs (shared `Dialog`, `Button`, `Disclose`, `Chip` variants). Decide the v1 question. | nothing | Haiku for the reconciliation, Sonnet for the shared components |
| 1 Advisor workspace | WSP-01 to WSP-12. Pilot with the `advisor-v2` role (it already opens `/advisor/v2`). Then change the advisor's home from `/advisor` to `/advisor/v2` (a one-line, reversible change in `lib/auth/access.ts` `HOMES`). | `FindService` and the `StaffShell` wrapping of the v2 pages | Kit plan: Haiku tests, Haiku or Sonnet build, Sonnet verify |
| 2 Overview workspace | WSP-13, after phase 1 is verified. | nothing | Sonnet |
| 3 Hubs | Go-to intents (registry phase 3), pre-fill hand-overs. Needs a hub frame decision and screens specified to build level. | nothing | Opus designs, Haiku builds the table-driven parts |
| 4 Map and reasons | Back end first: positions, coverage and a not-suitable list in `/advisor-v2/find`. Then the map and reasons intents. | the Radar redirect address, once old links have expired | Sonnet for the back end and tenancy tests, Haiku for the screens |
| 5 Roles | Consolidate 14 session roles into 6 with flags (see below). | `advisor-v2`, then the old names | Opus designs and records the decision, Sonnet builds, independent Sonnet verifies |
| 6 Call recording | Only if the owner wants v1 retired: a design for opening, booking and finishing a case inside the workspace. | the v1 call flow | Opus designs; separate plan |

Phases 0 to 2 can start now. Phases 3 and 4 wait on decisions and back-end fields. Phases 5 and 6 are separate programmes.

## The role migration (phase 5), step by step

The route guard, the tenant's group-to-role mapping (DEC-523) and the token the back end issues all carry today's role names, so this is a back-end change with a front-end follow.

1. The front end maps today's roles to personas and flags (`registry.json` `adapter`). This is what phase 1 ships. No back-end change.
2. Add the flags to the tenant mapping model and the token, accepting old and new role names together.
3. Show each tenant administrator a diff of their mapping against the new roles, and migrate each mapping with a script that is dry-run first.
4. Switch the route guard from role names to persona and flags, one route group at a time.
5. Remove the old names (`advisor-v2` first, since it is only a flag).

Tenancy applies throughout (DEC-130 to DEC-134): a mapping change must never widen access or cross a tenant, so each step has isolation tests and an independent verifier.

## Decisions I need from the owner

1. **Is v1 to be retired, and if so what replaces call recording?** Until the workspace can open, book and finish a case, v1 stays. If yes, phase 6 is a design task first.
2. **Pilot and gate.** Who is in the first pilot (the `advisor-v2` role?), how long, and what counts as success before the advisor's home changes.
3. **Role consolidation: go, no-go, or later.** It buys a simpler admin mapping screen and removes rollout-flag roles; it costs a back-end migration across tenants.
4. **Hubs.** Whether the Manager and Admin pages move to the rail-less frame, or keep the rail with only the assistant button added.
5. **Reporter.** Whether the phone flow changes at all.

## Weak points

- **The slice is small.** The new design covers the advisor's browse flow and the overview. Most of the 151 pages are untouched, so "retire" applies to little of the code.
- **The map and not-suitable screens in the boards cannot be built** until the back end returns that data.
- **Nothing here has been run.** No TypeScript for the kit exists, and the end-to-end suite has not been run in this work.
- **Independent verification is the bottleneck.** Every unit needs a different session to verify; the plan assumes that capacity.
- **Clinical safety.** Removing v1 removes the only call-recording path. That is why it is not on the list until a replacement exists.
