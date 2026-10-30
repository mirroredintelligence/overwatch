# W8D: shift lead pages wired to the back end (wiring wave)

Bundle W8D: W17, W18, W42, W43, W47, W08 (the lead's screen pairing form), and the lead's phoned entry with no case. Branch `task/build-W8D` off `integration/build`. Tests run: back end (lead views unit and role matrix, W7B integration under the Neo4j lock); front end `pnpm typecheck`, `pnpm lint`, `pnpm test` (all directories, green), `pnpm build` (exit 0). Playwright not run.

## Decisions

### DEC-920 The lead may record what a service said by phone with no case, through its own route (W17, W42, W43; closes the W7A-K8 gap for phoned answers only)
Status: accepted (wiring wave 8, bundle W8D; under DEC-133). The lead's "Enter what they told me by phone" has no case reference, and the advisor's case routes stay advisor and clinical (DEC-632, W7A-K8 is unchanged for cases). The lead's phoned answer is a new route, `POST /lead/services/{id}/phoned` (`routes_lead_views.py`), lead only, Idempotency-Key required, body `{"told": accepting|limited|not-accepting, "value"?}`. It runs `RecordAdvisorPhoned` with no case id, so the report goes through `ReportCapacity` (source advisor-phoned, no echo, the same figure rules as W14: "not accepting" stores 0 and takes no figure, accepting and limited take a whole number, 0 to 9999 on the BFF). The audit entry carries `told`, and no `case_id`. Tests: unit (record, not-accepting, bad shape, unknown service, no key, the role matrix), integration (own tenant records; another tenant's service is a 404 and nothing is stored). Its BFF is `POST /api/bff/lead/services/[id]/phoned` (`{said, value?}`, CSRF, key, 201 `{recorded, value}`); the shared dialog is `components/lead/LeadPhonedDialog.tsx`.

### DEC-921 The lead's pages hold the reporter post's role id (W18, W42)
Status: accepted. The back end's own read (`GET /lead/reporters`, W7B C) gives each post's role id for the change-number and remove routes. The role id is an internal id of a post, not a person's number, not a secret and not a tenant id; the back end refuses another tenant's id as a 404. So the lead's remove form is a picker of posts ("UCR East, Duty manager, ending 4821") whose value is the role id, and the browser sends it back. The change-number route does not trust a role id from the browser: it reads the posts of the service it was asked about and changes the first one it finds (see the known issue on services with more than one post).

### DEC-922 A lead read that is malformed is an error, never an empty or partly filled page (W17, W43, W42)
Status: accepted. Every lead read the BFF now passes on is checked against the shape the page knows (`parseOverview`, `postsFrom`, `phonesFrom`, `invitationsFrom`, the flag bundle, the service's name and suspension). A back end that is down answers 503 (its own status); a malformed answer answers 500. A page shows "could not be loaded" for either, never "No services need chasing." or an empty list. The `notBuilt` helper (501 "not-built") is removed: no lead route answers it.

### DEC-923 The checked reports are the back end's closed flags; "Phone to confirm" records a figure and leaves the flag open (W42)
Status: accepted. `GET /api/bff/lead/flags?state=checked` reads `/admin/report-flags?status=closed` and gives `counts.checked`. "Phone to confirm" on a flag opens the lead's phoned dialog and records the figure as advisor-phoned; it does not resolve the flag, which stays open until the lead marks it checked or accepted (`$resolve`). Reason: the back end's resolve with outcome phoned needs its own figure field and the lead's dialog already records one, so the two are kept apart rather than guessed together (known issue W8D-K4).

### DEC-924 The service page reads the suspension from the back end (W42)
Status: accepted. `GET /api/bff/lead/services/[id]` gives the name (FHIR read) and the suspension (`GET /lead/services/{id}/suspension`): `suspended`, `since`, `expiredRequests`, and `registerPhone`, the service's register number, which the lead needs to phone it (W42 "Phone the service"). The register number is the service's own work phone and is shown only on the lead's suspended-service page; it is never in a URL, a log or local storage.

### DEC-925 The invitation list carries the service id (W43)
Status: accepted. `GET /lead/invitations` gains `serviceId` (`InvitationView.service_id`; the unit test pins it). Without it, "Phone them" on the set-up tracker could not name the service the phoned answer is for. Additive change; the tenant is still bound at the edge.

### DEC-926 The change-number form shows the number's last four digits for the service it was read for (W18)
Status: accepted. The form reads `GET /api/bff/lead/reporters?service=` when a service is chosen and shows "Current number ends 4821"; after a successful change it shows the new ending. A reading for another service is never shown (the reading is kept with its service id).

## Hazards

| id | hazard | source | control | tasks | verified by | status |
|----|--------|--------|---------|-------|-------------|--------|
| H-590 | A lead records a phoned figure for a service that the advisors then rely on, with no case to tie it to | W17 "Enter what they told me by phone", DEC-920 | recorded as advisor-phoned with its audit entry (`told`), 0 to 9999, not-accepting stores 0, no echo; the lead's role only | W8D | unit and integration tests of the phoned route; role matrix | open until the owner confirms the lead may enter a figure by phone (DEC-920) |
| H-591 | A change of number or a removal names the wrong reporter post when a service has more than one | W18, W42, DEC-921 | the post is found by service and role id from the back end's own list; the back end refuses another tenant's id with 404 | W8D | route tests (post found, no post 404, nothing changed) | open: first post listed is used (known issue W8D-K3) |
| H-592 | A lead page shows a stale or partial answer as current (overview, phones, invitations, flags) | W17, W42, W43 | shape checks in the BFF (DEC-922); a failed read says so | W8D | route tests (malformed 500, unavailable 503, never an empty list) | closed for the BFF; the browser still shows the last answer until the next read |
| H-593 | The register number of a suspended service is shown to a lead who should only see that the service is suspended | W42, DEC-924 | the lead's role only; no URL, log or storage holds it | W8D | route tests | closed for this release; a number is held only in the response to the lead |

## Known issues

| id | what | where | trigger |
|----|------|-------|---------|
| W8D-K1 | The browser stand-in (`e2e/support/backend.ts`) does not serve the lead routes, so the e2e lead spec exercises only the "could not load" path. The flows against the real back end are not in e2e | `frontend/e2e/lead.spec.ts`, `frontend/e2e/support/backend.ts` | the verification run, or a stand-in that serves the lead routes |
| W8D-K2 | "System now" counts show the organisation's own counts only; the network variant is not built | `components/lead/SystemCounts.tsx`, `GET /lead/overview` | the network variant of the overview (W17 tenancy amendment) |
| W8D-K3 | A service with more than one reporter post: change-number and remove act on the first post the back end lists, not on a post the lead chose from the list | `app/api/bff/lead/reporters/number/route.ts`, `routes_lead_views.py` | a service with two posts, and a change to one of them |
| W8D-K4 | "Phone to confirm" on a flag records the figure but does not resolve the flag: the lead still marks it checked or accepted | `components/lead/ReportFlags.tsx`, `components/lead/LeadPhonedDialog.tsx` | a flag raised by a many-changes rule |
| W8D-K5 | The phones and the moves are not shown for the network variant | `components/lead/PhonesList.tsx` | the network variant (later) |
| W8D-K6 | The screens administration (a list of screens, revoke) is not built: out of scope for W08 | `app/(lead)/lead/screens/new` | a lead asks to see or revoke a screen (U37 revoke) |
| W8D-K7 | The e2e spec for the screen pairing (`e2e/screens.spec.ts`) is written, not run | `frontend/e2e/screens.spec.ts` | the orchestrator's e2e run |
| W8D-K8 | Commit history: the lead's phoned dialog implementation is in commit f3d1fc7, which is labelled as the failing tests of the group; the red and implement steps for the dialog were not split | git history of `task/build-W8D` | none; disclosed for the reviewer |
| W8D-K9 | The overview's "Reporting today" and the counts are the back end's board read; a service suspended is counted as not updated (the back end's rule), so the counts can read higher than the chase list | `GET /lead/overview` | a suspended service |

## Contracts

- Back end: `POST /lead/services/{service_id}/phoned` (`routes_lead_views.py`), body `{told, value?}`, 201 `{reportId, value}`; `GET /lead/invitations` items gain `serviceId`.
- BFF, new: `GET /api/bff/lead/reporters[?service=]` (`{reporters:[{serviceId, serviceName, roleId, role, channel, numberEnding, coveredUntil}]}`), `POST /api/bff/lead/reporters/number` (`{serviceId, newNumber, until}` → `{numberEnding, coverUntil}`), `POST /api/bff/lead/services/[id]/phoned` (`{said, value?}` → 201 `{recorded, value}`).
- BFF, wired (no longer 501): `GET /api/bff/lead/overview`, `POST .../services/[id]/remind`, `POST .../services/[id]/test-prompt`, `GET .../services/[id]` (name, suspended, since, expiredRequests, registerPhone), `POST .../people/remove` (`{person: roleId, reason}` → `{rolesEnded, devicesRevoked, servicesWithoutReporter}`), `GET .../phones`, `GET .../invitations` (items with serviceId), `POST .../invitations/[id]/resend`, `POST .../invitations/[id]/switch-to-text`, `GET .../flags?state=checked`.
- Root paths (DEC-883): `/lead/*`, `/admin/*`, `/screens/*` are at the back end's root; `/fhir/PractitionerRole/{id}/$remove` and `$change-number`, `/fhir/Task/$invite-reporter`, `/fhir/HealthcareService/*` under `/fhir`. Every call checked against its router prefix (`routes_lead_views` prefix `/lead`, `routes_admin` and `routes_lead` as their paths state).
- Components: `LeadPhonedDialog` takes `serviceId`, `serviceName`, `open`, `onClose`, `onRecorded?`; `SetupTracker`'s `Invitation` carries `serviceId`; `RemovePersonForm` is a picker of posts.
- Libraries: `lib/lead/reporters.ts` (`postsFrom`), `lib/lead/phones.ts` (`phonesFrom`), `lib/lead/invitations.ts` (`invitationsFrom`), `lib/lead/phonedBody.ts` (`readPhonedBody`, `phonedPayload`, `MAX_FIGURE`). Removed: `lib/lead/notBuilt.ts`.

## Not run

- Playwright (`pnpm e2e`): `e2e/lead.spec.ts` header updated; the specs were not run (W8D-K1, K7).
- The full back-end suite: only the lead views (unit, role matrix), the W7B integration file (7 passed under the Neo4j lock), and the mapping services unit file were run.
- `pnpm build` ran (exit 0); `next-env.d.ts` reverted after it (lesson L16).
- Ruff reports one line-length finding in `backend/src/diucs/adapters/inbound/fhir_rest/app.py:185`, which is from integration/build (W51), not from this bundle.
