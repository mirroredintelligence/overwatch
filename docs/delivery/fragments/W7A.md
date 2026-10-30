# W7A fragment: back-end gaps found by the front-end bundles (advisor call flow, clinical, help, exec)

Build W7A. Numbers: decisions DEC-770 to DEC-781, hazards H-410 to H-414. No migration (0150 to 0159 unused): every change is a property or a new read statement. Route paths and shapes are in `W7A-routes.md`.

## Decision

DEC-770 A case opens with nothing in it, and the referrer type is optional until the case is complete (A2, A3).
1. `POST /fhir/ServiceRequest` with a body of only `{ "resourceType": "ServiceRequest" }` opens an empty case (W10 sends exactly that). DEC-067 and DEC-068 say the advisor opens an empty case at the start of a call and fills it in later; the old route demanded a referrer at the open, which contradicted the use case (U11) and the screen.
2. `Case.referrer_type` is `ReferrerType | None`. `OpenCaseCommand.referrer_type` and `UpdateCaseCommand.referrer_type` are optional. `missing_fields` names `referrer_type` last, so `UpdateCaseResult.complete` and `FilterOptions` need it (`$filter-options` answers 400 naming the missing field, as it does for age band, postcode, needs and urgency).
3. A PUT now saves the referrer and the age band (it ignored both, H-320). A PUT that leaves a part out leaves the stored value as it is: a part not said is not "empty". `POST` with details runs the second unit only when there is something to save.
4. A referrer or age band that is not a listed code is a 400 that does not echo the value.

DEC-773 Planned is stored and answered as planned; a referrer's scores are stored and read back (A4, A5). This supersedes the "planned is answered as routine" part of DEC-397.
1. The case already held `Urgency.PLANNED`; only the FHIR mapping lost it. The ServiceRequest now carries the extension `https://diucs.example/StructureDefinition/urgency` (`within-2-hrs`, `today` or `planned`). The FHIR `priority` stays (urgent for within-2-hrs, routine for today and planned) because FHIR has no planned priority.
2. On a write, the extension wins. A body with a priority and no extension reads as before (urgent is within 2 hrs, routine is today), so an older client still works. A priority that disagrees with the extension (urgent with planned, routine with within-2-hrs) is a 400.
3. A score is one complex extension, `https://diucs.example/StructureDefinition/score`, with a `method` (valueCode: news2, cfs, ambulance-category, manchester, pathways-dx) and a `value` (valueInteger for the first three, valueString for the others). This is the shape W12 proposed. The route now passes the scores to `UpdateCase`; the case repository's first-recording path writes them. Once recorded they cannot change (the Observation store refuses a rewrite): repeating them unchanged is accepted, changing them is a 400 "recorded scores cannot change" (known issue W7A-K2).
4. The answer also carries the case reference (`identifier`, system `https://diucs.example/case-reference`) and the open time (`authoredOn`), which W10 and W11 had no way to read.

DEC-781 `GET /fhir/ServiceRequest/{id}` reads one case (A1) and `$close` answers the close time (A8).
1. The read is for the advisor and the clinical roles (DEC-397); another tenant's id, an unknown id and any other role answer the same 404. The ETag is the constant `W/"1"` (DEC-398). `Cache-Control: no-store`.
2. A closed case answers `status: completed`, the extension `closed-at` (valueDateTime, UTC) and the extension `outcome` (valueCode), and no postcode and no needs (DEC-398). The same shape is answered by `$close` and by the read. The front end may drop its own stamp of the close time (DEC-640).
3. The mapping is a pure module, `adapters/inbound/fhir_rest/case_mapping.py`, with unit tests both ways.

DEC-779 `$filter-options` sends what the domain holds (A6).
1. Per option: `category` (valueCode), `unitLabel`, `overBy` (when over capacity), `lat` and `lon` (valueDecimal, the site's place from its Location), with the existing travel range and source. At the top: `patientLat` and `patientLon` (the centre of the case's postcode district: only the district is stored, DEC-067), `notFound` (valueBoolean true when the locator does not know the district) and `outOfArea` (true when no service with current criteria covers the district). A flag is sent only when true.
2. The age filter needed no change: it reads the case's age band, which the PUT now saves (DEC-770). It is tested through `$filter-options` (a 0-15 band is outside UCR West's criteria, an 80+ band is an option).
3. Not sent, because the domain does not hold it: a service phone (only a hash of a person's phone is stored), a coverage radius for a visiting service, travel legs (a travel estimate is one range with a source), and a network organisation (the options are the tenant's own board). See the known issues.

DEC-771 The criteria history is readable by the advisor, with the accepts and excludes (A7).
1. `GET /fhir/Basic?subject=HealthcareService/{id}` admits the advisor as well as the owner, clinical and lead roles.
2. An advisor reads the version in force only (status current): a change waiting for approval, and old versions, are for the owner and the leads. This is the clinical-safety choice: the criteria dialog must never show an advisor text that is not yet approved.
3. Every role now reads `ageMin`, `ageMax`, `accepts` and `excludes` on each version (H-325). The districts, the author and the change reason are not in the history.

DEC-774 A clinical advice request can be read, and a clinician has Mine and Done lists (B1, B2).
1. `GET /fhir/Task/{id}` answers a clinical advice request to the advisor who asked it and to any clinical advisor. Any other advisor, and every other role, read the same 404 as an unknown id. The path is shared with the booking read, so the booking route asks the clinical use case first and falls through to the booking when the id is not a clinical request.
2. The Task carries the case's number (`case-reference`), age band, needs, urgency (`case-urgency`) and NEWS2, and never the postcode, the district, a practitioner id (requester or taker) or any identifier of a person. It carries the request's urgency and reason, when a held lock ends (`returns-at`, taken time plus the take timeout) and, once advised, the choice, the reason, the clinician's note and when (`advice-choice`, `advice-reason`, `advice-note`, `advised-at`). The advice answers who asked and any clinician, not the queue: the lists do not carry the note.
3. A lock that has lapsed reads as waiting again (the same rule as the queue).
4. `GET /fhir/Task?code=clinical-advice&status=requested|in-progress|completed` is the queue, Mine and Done of the calling clinician (the role is checked first, any other role is a 404; an unlisted status is a 400). Mine is the requests the clinician holds, oldest first; a lapsed lock is not held. Done is the requests the clinician advised on, the latest advice first, at most 50 (DEC-774). Each entry carries the case glance of item 2, so the queue now shows age band, needs and NEWS2.
5. The statement `Q-CLIN-ADVISED-BY` is new; the others are reads the use cases already made.

DEC-780 A clinician reads their own presence (B3).
1. `GET /clinical/presence` answers `{ "presence": available|busy|away|null, "available": n }`: the caller's own presence (null when none is set or it has lapsed after its 120 seconds) and the count of clinical advisors available. No name. The on-duty screen starts where it was left.
2. The count that advisors read already existed: `GET /clinical/available` (advisor, clinical, lead). B3 as written ("a presence read: how many clinicians are available, names none") was already built; the gap W44 reported was the clinician's own state, which this adds.

DEC-778 The problem report is mounted (B4): `POST /help/problems`.
1. Body `{ "category": screen-slow|button-does-not-work|figure-looks-wrong|something-else, "text"?: up to 280 characters, "sessionShared"?: boolean }`, nothing else accepted. `Idempotency-Key` required; a replay with the same body answers the same report, another body under the same key is 422. Answer 201 `{ "id" }`, never the text.
2. Any signed-in person may report, except a wall screen and an anonymous link (404). The text goes to the protected store (U41), under the tenant.
3. The use case stores no page route, so the front end's `route` is not sent; the BFF maps `kind` to `category` (known issue W7A-K5).

DEC-772 A reload shows whether a support code is live, not the code (B5). This departs from the task's wording ("so a reload can show it").
1. `GET /support/codes/current?sessionId=` answers `{ "active": true, "expiresAt": ... }` or `{ "active": false }` for the caller's own code for that session. Only the person who shared it reads it; support, a wall screen and an anonymous link are refused (404); another tenant's code for the same session id is not seen.
2. The code is returned once, when it is made, and only its keyed hash is stored (O06). Storing it again so that it could be read back would put a recoverable live code in the graph for four hours, which the design chose not to do. W56 left this to the owner; this is the decision. The screen says "A code is live until HH:MM" and offers "Stop sharing", after which a new code can be made.

DEC-775 The acknowledged and closed alert lists (B6).
1. `GET /fhir/Task?code=acknowledge-alert&owner=me&status=acknowledged|closed` (also `new` and `escalated` as before). The caller's own alerts only, the latest raised first, at most 50. Executives and leads only (404 for others), an unlisted status is a 400.
2. An acknowledged alert carries the extension `https://diucs.example/CodeSystem/alert-acknowledged-at` (valueDateTime) for "acknowledged at 13:40". Who acknowledged is always the owner; no name is sent.
3. The statement `Q-ALERT-OWNER-BY-STATUS` is new. The `escalated` list is as it was (it filters the open list, which holds new alerts only, so it is empty): see W7A-K6.

DEC-776 The leadership list for the deputy picker (B7): `GET /fhir/Practitioner?role=leadership`.
1. The active practitioners of the tenant who hold an active shift-lead or clinical-lead role in effect now (the roles DEC-341 item 4 accepts as a deputy), as a Bundle of `Practitioner` with an `id` and `name[0].text` only. Not the caller (a user cannot be their own deputy), ordered by name then id. Executives and leads only.
2. No phone, email, role or period is sent. No new statement (it reads the active roles the clinical-lead lookup already reads).

DEC-777 The duty coordinator's number is on the board (B8): a `coordinationPhone` string part of `$board`, read from the tenant's configuration contact of kind coordination-phone (an organisational role number). A tenant with none sends no part: no number is made up (H-T15). Every board role reads it; the public profile already shows the same number before sign-in.

## Hazards

| id | hazard | source | control | tasks | verified by | status |
|---|---|---|---|---|---|---|
| H-410 | A planned case is shown as "Today" (the priority alone cannot say planned) | DEC-397; W11 H-321 | The urgency extension carries the real value and wins on write; a priority that disagrees is a 400; round trip tested | W7A-A4 | `test_case_mapping.py`, `test_routes_cases_w7a.py` (a planned case is stored and read back as planned) | mitigated; closes H-321 once the front end sends and reads the extension |
| H-411 | A referrer's score is shown as saved but lost after a reload (H-323), or a corrected score is refused after the first save | DEC-773; W12 | Scores are stored on the first recording and read back; a change after the first recording is a clear 400 | W7A-A5 | `test_routes_cases_w7a.py` (stored, read back, repeat accepted, change refused, out of range refused without the value) | mitigated; the 400 on a change is W7A-K2 |
| H-412 | A clinical advisor gives advice on a case they cannot see, or a case's details reach someone who should not see them (H-375, H-NEW-4) | DEC-774; W44, W45 | The Task carries the case number, age band, needs, urgency and NEWS2 only; the advisor who asked and clinicians read it, no one else; the other tenant's id is the same 404; no postcode or id of a person | W7A-B1, B2 | `test_routes_clinical_w7a.py` (no postcode, no practitioner id, refused roles, tenant B) | mitigated; the clinician's advice note is free text of at most 280 characters and is shown to the advisor who asked (the front end warns against patient details; the back end cannot check them) |
| H-413 | A reload loses a live support code, so a person cannot tell it is still shared | DEC-772; W56 | The state read says a code is live and until when, and the person can stop it | W7A-B5 | `test_routes_support_current.py` | mitigated; the code is not shown again by design |
| H-414 | Patient detail typed into a problem report is kept readably | DEC-778; W46 H-379 | Text goes to the protected store, is capped at 280 characters, is never in the answer or the audit; the front end warns | W7A-B4 | `test_routes_problems.py` | open: the back end cannot recognise patient detail in free text |

## Known issues

| ID | what | where | trigger |
|---|---|---|---|
| W7A-K1 | `$filter-options` sends no service phone (only a hash of a person's phone is stored), no coverage radius, no travel legs and no network organisation: the card shows "Phone to confirm", the map draws no coverage circle and no leg details | `case_mapping.py` `filter_result_to_fhir`; no domain field | a service phone, a coverage area and travel legs are modelled |
| W7A-K2 | A recorded score cannot change: the picker lets an advisor choose another NEWS2 after saving and the PUT answers 400 "recorded scores cannot change" | `open_case.py` `_scores`, `case_repository.py` (DEC-053 item 3) | an advisor corrects a score |
| W7A-K3 | The Pathways Dx value the picker offers (letters, digits, dot, dash, underscore, up to 32) is wider than the back end's `[A-Z0-9]{2,10}`: a code in the first form and not the second is a 400 | `domain/model/scores.py`, `frontend/lib/advisor/scores.ts` | the Pathways list holds such a code |
| W7A-K4 | The patient point and the map's centre are the postcode district's centre, not the postcode's | `filter_options.py` | W50 shows the point as "the postcode centre" |
| W7A-K5 | A problem report stores no page route; the front end's `route` is not sent | `safety_concern.py` `ReportProblem` | support wants the page of a report |
| W7A-K6 | `status=escalated` on the alert list is empty (the open list holds new alerts only; an escalated alert is a new alert that points back at the first) | `alert_repository.py` `open_for_owner` | an executive filters for escalated |
| W7A-K7 | The criteria history sends no reviewed date and no owner, so the dialog's "reviewed" and "owner" lines stay "not recorded" | `routes_criteria.py` | the criteria record holds them |
| W7A-K8 | The case routes admit advisor and clinical, the front end's guard admits advisor and lead (DEC-632 stays open): a lead's case call is a 404 | `routes_cases.py`, `frontend/lib/auth/access.ts` | a lead opens a call |
| W7A-K9 | `tests/integration/graph_store/test_person_repository.py::test_sixteen_racing_saves_of_one_new_practitioner_let_exactly_one_win` fails on integration/build 7d88ee6 without this bundle (14 saves win, not one) | `person_repository.py` | the merged-tip run |

## Contracts

- Routes and shapes: `W7A-routes.md`.
- `adapters/inbound/fhir_rest/case_mapping.py`: `CaseDetails`, `parse_case_details`, `case_to_fhir`, `filter_result_to_fhir`, `refuse_patient_details`, the extension URLs.
- `adapters/inbound/fhir_rest/clinical_mapping.py`: `clinical_task`, `input_url`.
- `application/use_cases/open_case.py`: `OpenCaseCommand.referrer_type` optional; `UpdateCaseCommand.referrer_type`; `missing_fields` names `referrer_type`.
- `application/use_cases/filter_options.py`: `Option.category`, `Option.position`; `FilterOptionsResult.patient`, `.not_found`, `.out_of_area`.
- `application/use_cases/clinical_advice.py`: `CaseGlance`, `ClinicalRequestView`, `ReadClinicalRequest`, `ListClinicalRequests` (`LIST_WAITING`, `LIST_MINE`, `LIST_DONE`, `DONE_LIMIT`), `PresenceView`, `ReadPresence`.
- `application/use_cases/support_access.py`: `SharingState`, `ReadSharingState`.
- `application/use_cases/subscribe_alert.py`: `Leader`, `ListLeaders`.
- `application/use_cases/coordination_contact.py`: `ReadCoordinationPhone`.
- `application/use_cases/criteria.py`: `CriteriaVersionView` gains `age_min`, `age_max`, `accepts`, `excludes`; the advisor reads the current version only.
- Ports: `ClinicalRequestRepository.advised_by`, `AlertRepository.for_owner_with_status`, `SupportRepository.live_code_expiry`, `PeopleRepository.active_roles_with_codes`.
- Registered statements (new): `Q-CLIN-ADVISED-BY`, `Q-ALERT-OWNER-BY-STATUS`, `Q-SUPPORT-CODE-LIVE`. Each has `tenantId: $tenant` on every node and a Scenario whose seed distinguishes the tenants (`Marked`).
- Test helper: `tests/support/route_unit.py` (`route_client`, `bearer`, `assert_role_matrix`).

## Tenant pending

- None. The three new statements are converted (registered with scenarios and run by `test_tenant_isolation.py`). Every read uses the unit of work's tenant; no route reads a tenant from the request.

## Assumed

- The Done list shows at most 50 requests (DEC-774) and an alert list at most 50 (DEC-775).
- `ReadCoordinationPhone` takes the first contact of kind coordination-phone.
- The urgency extension URL and the score extension URL are the ones W12 proposed (`StructureDefinition/score`) and the analogous `StructureDefinition/urgency`; the front end maps them in `frontend/lib/advisor/case-fhir.ts`.

## Tests

- Unit: `test_open_case_referrer.py`, `test_case_mapping.py`, `test_filter_options_mapping.py`, `test_board_coordination_mapping.py`, `test_routes_w7a_cases.py`, `test_routes_w7a_clinical.py` (role matrices of A1, A8, B1 to B7).
- Integration, run once on the shared Neo4j: `test_routes_cases_w7a.py`, `test_filter_options_w7a.py`, `test_routes_criteria_advisor.py`, `test_routes_clinical_w7a.py`, `test_routes_problems.py`, `test_routes_support_current.py`, `test_routes_alerts_lists.py`, `test_routes_leaders.py`, `test_routes_board_coordination.py`, each with a two-tenant test.
