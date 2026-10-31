# WB6 routes: the advisor and clinical routes of bundle B6 (for the front-end bundles that follow)

The back-end routes are under `/fhir` (the FHIR base) except where marked ROOT. The BFF routes are under `/api/bff`. Every back-end route answers the one 404 (an OperationOutcome) for another tenant's record, an unknown id and a role that may not call it; the platform operator is refused at the edge (401). Nothing takes a tenant, scope or network from a path, query, header or body field except the one `network` Parameters part below, which is a network id the session's token must list.

## Back end

### PUT /fhir/ServiceRequest/{id} (changed): the case version and the score correction
- Request headers: `If-Match: W/"<n>"` (required: the ETag of the read), `Idempotency-Key`.
- A case at another version: **412** `conflict`, nothing written. No `If-Match`: 428.
- Extensions on the ServiceRequest (base `https://diucs.example/StructureDefinition/`): `score` (one complex extension per score: `method` code and the value), `score-correction-reason` (`valueCode`: `typing-error`, `referrer-corrected` or `rescored`; sent only with a score whose method is recorded with another value; a reason with nothing corrected is a 400; a correction without a reason is a 400).
- Scores are merged by method: a method not yet recorded is added; a recorded method given another value is a correction; a recorded method not sent stays. A score is never removed. Two scores of one method in one write: 400. `pathways-dx` value: `[A-Za-z0-9]{2,12}` AND on the Pathways list (400 otherwise; the list's own text is never echoed).
- Answer: the ServiceRequest with `ETag: W/"<n+1>"`. Extension `score-corrections` (`valueInteger`, present only above zero) is how many times the scores were corrected.
- GET /fhir/ServiceRequest/{id} and POST /fhir/ServiceRequest answer the same `ETag`. POST with details is one unit of work. `$close` takes an optional `If-Match`.

### GET /fhir/ServiceRequest/{id}/$summary?destination={service id} (new)
Roles: advisor, clinical. `destination` optional. Answer `Cache-Control: no-store`, Parameters:
```json
{ "resourceType": "Parameters", "parameter": [
  { "name": "reference", "valueString": "4821" },
  { "name": "row", "part": [ { "name": "label", "valueString": "Referrer" }, { "name": "value", "valueString": "Ambulance crew" } ] },
  { "name": "row", "part": [ { "name": "label", "valueString": "Destination" }, { "name": "value", "valueString": "UCR West" } ] }
] }
```
Labels, in order, each present only with a value: `Referrer`, `Age band`, `Postcode` (the district), `Needs`, `Urgency`, `Scores`, `Destination`, `Booked`, `Data age`. Without `destination` the last three are left out. A closed case: **409**. An unknown or inactive destination: 404.

### POST /fhir/HealthcareService/$filter-options (changed)
Body: `case` (valueReference `ServiceRequest/{id}`) and, optionally, `network` (`valueString`, a network id of the token's claim): the other organisations' services of that network, view only. A network the token does not list is the one 404. Each `option` part gains, when present: `phone` (valueString, the service's work phone, Q5), `lat`/`lon` (a fixed site's place, or a visiting service's circle centre) with `coverageRadiusKm` (valueDecimal, whole km, only for a visiting service), `leg` parts after `travelLow`/`travelHigh`/`travelSource` (each: `label`, `low`, `high`, `how`, `source`), and for a network option `organisation` (name, never an id) and `organisationSource`. `patientLat`/`patientLon` (the postcode district's centre) are top-level parts. A network answer has `notSuitable` empty and no patient point.

### GET /networks (ROOT, existing) and the use here
`{ "networks": [ { "id": "net-...", "name": "...", "system_name": "...", "pathway_name": "...", "time_zone": "..." } ] }` for advisor, clinical, lead, owner and exec. The BFF reads the ids only.

### POST /fhir/Task (changed): the service under consideration
Optional input extension `https://diucs.example/CodeSystem/task-input/service` with `valueString` = a service id (`[A-Za-z0-9.-]{1,64}`; anything else is a 400). The Task read answers the same input name with the service's NAME (never the id). The advice is also `Task.output` (types under `https://diucs.example/CodeSystem/task-output`: `advice-choice` valueCode, `advice-reason` valueCode, `advice-note` valueString, `advised-at` valueDateTime); the `task-input/advice-*` extensions stay beside them.

### PUT /tenant/staff/{practitioner id}/work-phone (new, tenant administrator only)
Body `{ "phone": "07700 900123" }` (a full UK number; otherwise 400, never echoed). Answer 204 with no body. Stores the number under `work-<id>` for an active person of the tenant (another tenant's person, an unknown one and a person who has left: the one 404). The number is in no answer, log or audit entry. Needs `Idempotency-Key`. No way to clear it yet (known issue).

### CapabilityStatement
`HealthcareService` lists `filter-options`, `advisor-phoned` and `declined`; `ServiceRequest` lists `close` and `summary`.

## BFF (front end)

### GET /api/bff/cases/[ref] (changed)
The case view gains `scoreCorrections: number` (zero when never corrected). `etag` is the version to send back.

### PUT /api/bff/cases/[ref] (changed)
Body gains an optional `scoreCorrectionReason` (`typing-error`, `referrer-corrected`, `rescored`; any other value is a 400). The key is absent unless a recorded score is changed. A 412 from the back end is `{ code: "conflict" }` with status 412.

### GET /api/bff/cases/[ref]/options[?only=own] (changed)
```json
{ "shownAt": "...", "options": [ { "serviceId": "...", "name": "...", "phone": "01305 900100" | null, "network": null | { "organisation": "...", "source": "..." }, "position": {lat,lon} | null, "coverage": {lat,lon,radiusKm} | null, "travel": {low,high,source,legs:[{label,low,high,how,source}]} | null, ... } ],
  "notSuitable": [...], "patientArea": {lat,lon} | null, "notFound": false, "outOfArea": false, "districts": [],
  "network": "none" | "shown" | "unavailable" }
```
The own services come first, then the other organisations' (each with `network` set), at most three networks, a network row that names no organisation dropped. `phone` is null unless it is shaped like a phone number. `?only=own` skips the network read (`network` is then `none`). `network: "unavailable"` means the network read failed or was refused: the screen says so.

### GET /api/bff/cases/[ref]/summary[?destination=<service id>] (changed)
Answers the display strings `{ reference, referrer, ageBand, postcode, needs, urgency, scores, destination, booked, dataAge }`: the back end's rows. Without a destination (or a row missing for it) `destination`, `booked` and `dataAge` read "No destination chosen yet"; a destination with no holding booking reads "Not booked" for `booked`; a missing case field reads "Not recorded" and scores "None given". 400 for a destination that is not a service id; 409 `closed` for a closed case; 502 when the answer is not a summary.

### POST /api/bff/cases/[ref]/clinical-requests (changed)
Body `{ urgency, why, service? }` where `service` is a service id (`[A-Za-z0-9.-]{1,64}`, else 400). Answers `{ requestId }`.

### GET /api/bff/cases/[ref]/clinical-requests/[id] (changed)
Answers `{ state: "waiting" | "taken" | "advised", service?: "UCR West", ... }`: `service` (the NAME) is present on every state when the advisor asked about one.

### Clinical screens
`lib/clinical/task.ts ClinicalRequest.service` (name or null). `components/clinical/CaseView` takes `{ requestId, request, seen }` as before; with `seen` null or `unreadable` it offers no advice form (DEC-1179).
