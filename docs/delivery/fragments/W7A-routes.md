# W7A routes: what the front end can call now

The exact paths and shapes the back end answers after W7A, for the front-end bundles to drop their stubs. Every route reads the tenant from the verified token only; none reads a tenant from the path, query, header or body. A refused role, another tenant's id and an unknown id all answer the same 404. Reasons are in `W7A.md`.

Extension URLs: `STRUCT` is `https://diucs.example/StructureDefinition/` and `CODES` is `https://diucs.example/CodeSystem/`. The Task inputs and outputs are extensions under `CODES + "task-input/<name>"`.

## A. Advisor call flow (roles advisor and clinical unless stated)

| Route | Answer |
|---|---|
| `POST /fhir/ServiceRequest` (Idempotency-Key) | 201 the case (below), `Location`, `ETag: W/"1"`. The body may be only `{ "resourceType": "ServiceRequest" }`; every detail is optional. A referrer or age band that is not a listed code is 400. |
| `GET /fhir/ServiceRequest/{id}` | 200 the case, `ETag: W/"1"`, `Cache-Control: no-store`. 404 for an unknown id, another tenant's id and any other role. |
| `PUT /fhir/ServiceRequest/{id}` (Idempotency-Key, If-Match) | 200 the case. Saves referrer, age band, postcode (kept as its district), needs, urgency and scores; a part left out is unchanged. A priority that disagrees with the urgency extension is 400; changed scores are 400. |
| `POST /fhir/ServiceRequest/{id}/$close` | 200 the case, closed (below). |
| `POST /fhir/HealthcareService/$filter-options` | 200 Parameters (below). 400 names the missing field, now including `referrer_type`. |
| `GET /fhir/Basic?subject=HealthcareService/{id}` (roles owner, advisor, clinical, lead) | 200 a Bundle of versions, newest first. An advisor gets the current version only. |

The case (a `ServiceRequest`): `id`, `identifier[0].value` (the four-digit case number, system `https://diucs.example/case-reference`), `status` (`active` or `completed`), `intent: plan`, `authoredOn` (UTC), `subject: #p`, `contained[0]` Patient with `address[0].postalCode` (the district) and the extension `STRUCT + "age-band"` (valueCode: `0-15`, `16-64`, `65-79`, `80+`), `reasonCode[].coding[]` (system `CODES + "need-category"`), `priority` (`urgent` or `routine`), and `extension[]`:

- `STRUCT + "referrer-type"` valueCode (`ambulance-crew`, `care-home`, `gp`, `nhs-111`, `other`), absent until set;
- `STRUCT + "urgency"` valueCode (`within-2-hrs`, `today`, `planned`). Send it on a write, and read it for the urgency: `priority: routine` is both today and planned;
- one `STRUCT + "score"` per score: `{ url, extension: [{ url: "method", valueCode }, { url: "value", valueInteger | valueString }] }`. Methods: `news2`, `cfs`, `ambulance-category` (valueInteger), `manchester`, `pathways-dx` (valueString);
- once closed: `STRUCT + "closed-at"` valueDateTime (UTC) and `STRUCT + "outcome"` valueCode. A closed case has no postal code and no `reasonCode`.

`$filter-options` Parameters: `option` parts with `serviceId`, `name`, `status`, `criteriaVersion`, `unitLabel`, `category` (valueCode), `effectiveAvailable`, `overBy` (over capacity only), `lat` and `lon` (valueDecimal, a fixed site's place), `travelLow`, `travelHigh`, `travelSource`, `dataAgeSeconds`, repeated `fits` and `checks`; `notSuitable` parts with `serviceId`, `name`, `reason`; then top-level `patientLat` and `patientLon` (the postcode district's centre), `notFound` (valueBoolean true) and `outOfArea` (valueBoolean true), the last two only when true. Not sent (no domain data): `phone`, `coverageRadiusKm`, `leg`, `organisation`, `organisationSource`.

Criteria history version (a `Basic`): `id`, `meta.versionId`, `status`, `subject`, `reviewBy`, `ageMin`, `ageMax` (when set), `accepts[]` and `excludes[]` (need codes).

## B. Clinical advice, help and exec

| Route | Roles | Answer |
|---|---|---|
| `GET /fhir/Task/{id}` | advisor (the one who asked), clinical | 200 the clinical advice request as a Task (below). Any other caller reads 404. The same path still reads a booking. |
| `GET /fhir/Task?code=clinical-advice&status=requested` | clinical | the queue, as a searchset Bundle of Tasks with the case glance |
| `GET /fhir/Task?code=clinical-advice&status=in-progress` | clinical | Mine: the requests the caller holds (a lapsed lock is not held) |
| `GET /fhir/Task?code=clinical-advice&status=completed` | clinical | Done: the requests the caller advised on, latest first, at most 50 |
| `GET /clinical/presence` | clinical | 200 `{ "presence": "available" \| "busy" \| "away" \| null, "available": n }` |
| `GET /clinical/available` | advisor, clinical, lead | 200 `{ "available": n }` (as before) |
| `POST /help/problems` (Idempotency-Key) | any signed-in role except wall and anonymous link | 201 `{ "id" }` for `{ "category", "text"?, "sessionShared"? }` |
| `GET /support/codes/current?sessionId=` | any signed-in person except support, wall, anonymous link | 200 `{ "active": true, "expiresAt" }` or `{ "active": false }`; never the code |
| `GET /fhir/Task?code=acknowledge-alert&owner=me&status=acknowledged` or `closed` | exec, lead | the caller's alerts in that status, latest first, at most 50 |
| `GET /fhir/Practitioner?role=leadership` | exec, lead | a Bundle of `Practitioner` (`id`, `name[0].text`) of the active leads and deputies, never the caller |
| `GET /fhir/HealthcareService/$board` | wall, advisor, clinical, lead, exec, owner | as before, plus a `coordinationPhone` valueString part when the tenant holds one |

The clinical Task: `id`, `status` (`requested`, `in-progress`, `completed`), `code`, `focus` (`ServiceRequest/<case id>`), `authoredOn`, and `extension[]` under `CODES + "task-input/"`:

- `urgency` (valueCode `now` or `within-15-min`), `why` (valueCode);
- the case glance: `case-reference` (valueString, four digits), `age-band` (valueCode), `need` (valueCode, repeated), `case-urgency` (valueCode), `news2` (valueInteger). No postcode, no district, no id of a person;
- `returns-at` (valueDateTime) while a clinician holds it;
- once advised: `advice-choice` (valueCode: `go-ahead`, `use-another-service`, `clinical-call-to-referrer`, `emergency-route`), `advice-reason` (valueCode), `advice-note` (valueString, `GET /fhir/Task/{id}` only), `advised-at` (valueDateTime).

An alert Task (open or finished) is as before, and an acknowledged one adds `CODES + "alert-acknowledged-at"` valueDateTime.

## What the front end can now drop

- W10: the empty open works; W11: the case read works (`readCase`), age band, referrer and urgency persist, planned reads back as planned (send and read the `urgency` extension); W12: scores persist (the shape is the one `case-fhir.ts` already writes); W13 and W50: category, unit, over-by, place, the patient point and the two flags (not phone, legs, coverage, organisation); W14: the advisor reads the criteria history with accepts and excludes; W15: the close answers its time and outcome, and the case read feeds the summary.
- W44 and W45: the request read, Mine, Done, the case glance on the queue, the clinician's presence; W46: the problem report is mounted at `POST /help/problems`; W56: the reload reads the state of the code, not the code; W39 and W40: the acknowledged and closed alerts and the deputy list; W44: the coordinator's number on the board.
