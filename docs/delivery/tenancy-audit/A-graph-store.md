# Tenancy audit A: the graph store (Neo4j layer)

Read-only audit of everything that talks to Neo4j, for the multi-tenancy retrofit (DEC-130, DEC-131, DEC-132).
Code read at `main` code state `1ac81b9`; `main` is now `2cf069e` and the three commits since (DEC-130 only, DEC-131, DEC-132) change `docs/delivery/decisions.md` alone (checked with `git diff --stat 1ac81b9 2cf069e`), so every file:line below holds.
Unmerged work was read from the local branches `task/U02-confirm-capacity`, `task/U03-send-prompts`, `task/I04-consumer-framework`, `task/W02-bff-session-csrf`. They are local branches in worktrees under `/home/user/overwatch-wt/`; the `origin/task/...` names in the brief do not exist on the remote.
Nothing was run: no tests, no Docker, no app. Every count was made with grep or by reading.

Conventions used in the tables.
- Risk is judged in the target state: two or more scopes in one database, composite uniqueness in force, ids and keys that may repeat across scopes (tests already generate `id-1`, `id-2` in every run: `adapters/testing/fixed_ids.py:4`). HIGH = the statement returns, changes or deletes another scope's data with no key collision at all (label-wide scan, aggregate, singleton) or the failure is silent. MED = needs an id, key or hash to repeat in two scopes (anchored lookup). LOW = global by design.
- "Stamp" means: write `tenantId: $tenant` in the property map of every labelled node pattern in the statement (match, merge or create). Rule R-SET: after any `SET n = map` or `SET n += map`, add `n.tenantId = $tenant` in the same clause, because `SET n = map` replaces all properties and would drop the stamp.
- "Composite" means the unique constraint on `(tenantId, <current key>)` replaces the single-property one (section 3).

---

## 1. SUMMARY

| Item | Count | How verified |
|---|---|---|
| Registered query statements (distinct `Q-` ids in the code) | **124**: 123 tenant-scoped, 1 global (`Q-NEO4J-PING`) | `grep -rhoE '"Q-[A-Z0-9-]+"' graph_store audit_neo4j \| sort -u \| wc -l` gives 124; per-file counts add to 124 (section 2) |
| Of which written in `ResourceStore` as templates | 17 templates; 6 of them contain `{insert}` and register one extra id per label or relationship type at run time (`resource_store.py:572-582`), so the live registry grows with data | read |
| `NamedQuery(` call sites | 78 | `grep`; this is the "78" in DEC-130, and it is a count of constructor calls, not of statements. DEC-130's "78 statements" is wrong: dict-driven and tuple-driven modules build many statements from one call site |
| Statements with Cypher assembled from Python strings | 13: 4 f-strings (`scheduled_work_repository.py:30,66`, `capacity_repository.py:58,65`), 3 concatenations with `_READ` (`communication_repository.py:88,90,103`), 6 `{insert}` templates. DEC-130 says "two f-strings" | grep and read. All spliced text is constant or regex-checked (`_LABEL`, `resource_store.py:54`), so none is injectable |
| Unmerged-branch statements | 2 (`Q-CAP-LOCK-SERVICE`, `Q-CAP-TRAILING-CONFIRMS`, branch `task/U02-confirm-capacity`) | `git diff main...task/U02-confirm-capacity` |
| Migrations | **26** (ids `0001` to `0009` and `0014` to `0030`; `0010` to `0013` are unused, burned by a renumber, DEC-055 item 16). The brief's "30" is the highest id | `grep -cE '^\s+"[0-9]{4}_' migrations.py`; `EXPECTED_MIGRATION_COUNT = 26` in `tests/integration/graph_store/test_driver.py:22` |
| Unique constraints | **19** (all single-property except `identifier_key` and `concept_key`, which are two-property) | `grep -c 'CREATE CONSTRAINT'` |
| Indexes | **7**: 6 range (`obs_by_service`, `task_by_status` (two properties), `svc_active`, `phone_hash`, `communication_provider_id`, `protected_contact_role_id`) and 1 point (`location_position`) | `grep -cE 'CREATE (POINT )?INDEX'` |
| Node labels | **48**: 11 resource types incl. `Resource`; 2 profile labels set after put (`ServiceCriteria`, `ServiceFlag`); 2 platform nodes that also carry `Resource` (`List`, `Communication`); 10 backbone child labels; 2 version labels; 3 shared (`Concept`, `CodeSystem`, `Identifier`); 11 platform; 6 audit; 1 `Migration`. 37 of them are named literally in Cypher text; the rest come from `{insert}` | grep of Cypher text plus `mapper.py:128-152` |
| Singleton or global nodes today | 2 singletons (`AuditHead {id:'audit'}`, `List {id:'scope-list'}`); 26 `Migration` nodes (global by nature); 3 shared label families (`Concept`, `CodeSystem`, `Identifier`) merged by key; one global sequence (`ChainLink.seq`) | section 4 |
| Direct driver sessions outside `run_query` | `driver.py:72` (the one `tx.run`), `migrations.py` (`tx.run`), `audit_log.py:228` (`ensure_audit_head`), `idempotency_store.py:262,269` (`DriverIdempotencyStore`), `connection.py:139-150`, `unit_of_work.py:173-176` | grep for `.session()`, `.run(`, `execute_read`, `execute_write` |
| Code outside the graph layer that holds a `tx` or `ResourceStore` | none. Use cases go through `uow.<repo>`. `container.py:73` wires `neo4j_uow_factory`; `apply_migrations` and `ensure_audit_head` are not called by the composition root at all (only tests call `apply_migrations`) | grep |
| Test files that build their own transaction or call `run_query` or `tx.run` directly | 12 call `run_query`, 27 call `tx.run`; the wipe is `tests/support/neo4j.py:236-251` | grep |

**Overall difficulty.** Mechanically this is a moderate job: one execution point exists (`driver.py:72`), every statement is registered, and the mapper writes through only six `ResourceStore` templates, so the stamp has a short list of places to land (about 120 statements, most one-line edits). The difficulty is not the edit; it is that **today's isolation is an accident of global uniqueness** (`Resource.id` unique across the whole database, `0001`; `AuditHead` and `List` singletons). Nothing in the Cypher is tenant-aware, so the instant uniqueness becomes composite every unmodified statement is a leak, and the three worst (`Q-RES-CLEAR-OWNED`, `Q-RES-LOAD-NODES`, `Q-RES-MERGE-RELS`) are label-less matches that delete, merge or create across scopes on a single repeated key. That makes the cutover all-or-nothing for the graph layer: the seam, the converted statements, the new constraints and the generated test must land before any second tenant is created. Neo4j Community has no existence constraints, so the database cannot refuse an unstamped node; the registration-time lint and the generated test are the only guard, which is why the test is the centre of the plan. DEC-132 adds a second scope kind (the network) and a projector; that is a new write path in its own right (about 45 further hours) but it fits the same seam if the scope kind is designed into `run_query` from the start. I estimate 137 hours in 23 tasks (sections 9 and 10.7), of which 92 hours are tenancy proper (TEN-G01 to TEN-G15) and 45 are DEC-132 (TEN-G16 to TEN-G23).

---

## 2. EVERY REGISTERED QUERY

Columns: id, file:line of the registration, R/W, labels matched (M), merged (G), created (C), unique anchor today, change for tenancy, leak risk if unchanged. Line numbers are the `id=` or dictionary-key line.

### 2.1 `graph_store/resource_store.py` (17 templates, the mapper write and read path)

| Id | file:line | R/W | Labels | Anchor today | Change for tenancy | Risk if unchanged |
|---|---|---|---|---|---|---|
| Q-RES-LOCK | resource_store.py:69 | W | G `Resource` then `SET n:<Type>` | MERGE on `key`; no constraint or index on `key`; `id` is unique (0001) but is only set ON CREATE | `MERGE (n:Resource {key: $key, tenantId: $tenant}) ON CREATE SET n.id=$id, n.placeholder=true`; MERGE key stays `key`, plus `tenantId`; new unique `Resource (tenantId, key)` (also gives the missing index); `0001` becomes `Resource (tenantId, id)` | HIGH: would adopt another scope's node with the same key as its own and write `lockStamp` and a label on it |
| Q-RES-GET | :74 | R | M `Resource` | `key`, no unique | `MATCH (n:Resource {key:$key, tenantId:$tenant})` | HIGH: `_root_props` takes `rows[0]`, so a repeated key returns the other scope's props and version; the version check then runs against the wrong node |
| Q-RES-UPSERT-ROOT | :78 | W | G `Resource`+type | `key` | `MERGE (n{insert} {key: row.key, tenantId: $tenant}) SET n = row.props, n.tenantId = $tenant` (R-SET) | HIGH: `SET n = row.props` overwrites every property of the other scope's node |
| Q-RES-UPSERT-NODE | :83 | W | G backbone child labels (10), `ResourceVersion`, `ResourceVersionPart` | `key` | identical to UPSERT-ROOT | HIGH: same overwrite on children and on version copies |
| Q-RES-SHARED-READ | :88 | R | M label-less, filtered `Concept`/`Identifier`/`CodeSystem` | `key` | `MATCH (n {key:k, tenantId:$tenant})` | HIGH: `Identifier` is tenant-scoped (DEC-130 item 5); an unscoped read returns the other scope's identifier values (ODS codes, booking references, case references) and the `display` check below then refuses on their data |
| Q-RES-SHARED-CREATE | :93 | W | G `Concept`/`Identifier`/`CodeSystem` | `key`; real uniqueness is `(system, code)` (0003) and `(system, value)` (0002); `CodeSystem` has no constraint | stamp; if Concept and CodeSystem stay shared (section 4) they are the one exception to stamping and the lint needs a label allowlist; recommended: stamp all three | HIGH: shared `Identifier` joins scopes through `IDENTIFIED_BY` |
| Q-RES-SHARED-FILL | :98 | W | M label-less | `key` | `MATCH (n {key:$key, tenantId:$tenant}) SET n += $fill` | HIGH: fills or changes `display` and `version` on another scope's node; with shared concepts it is a covert channel (tenant A's display refuses tenant B's put, `resource_store.py:529`) |
| Q-RES-MERGE-NODES | :102 | W | G `Resource` placeholder, then `SET n:<Type>` | `key` | stamp the MERGE map | HIGH: adds a label to another scope's node and joins a placeholder across scopes |
| Q-RES-CLEAR-OWNED | :108 | W | M label-less, `DETACH DELETE` | `key STARTS WITH $prefix` | `MATCH (c {tenantId:$tenant}) WHERE c.key STARTS WITH $prefix AND NOT c:Resource AND NOT c:ResourceVersion DETACH DELETE c` | HIGH: the most dangerous statement; with a repeated resource id one scope's update deletes the other scope's children (`Type/id#...`) |
| Q-RES-CLEAR-ROOT-RELS | :113 | W | M `Resource` and an unlabelled target | `key` | `MATCH (r:Resource {key:$key, tenantId:$tenant})-[rel]->(t {tenantId:$tenant})` (valid only if Concept and CodeSystem are stamped) | HIGH: deletes the other scope's root relationships |
| Q-RES-MERGE-RELS | :118 | W | M label-less `a` and `b`, C relationship | `key` for both ends; checks `created == len(rows)` (`resource_store.py:567`) | `MATCH (a {key:row.start, tenantId:$tenant}) MATCH (b {key:row.end, tenantId:$tenant})`; if Concept stays shared, split into two statements (tenant to tenant, tenant to shared) chosen by `_SHARED_PREFIXES` | HIGH: creates relationships between scopes (DEC-130 item 1 forbids it), and a double match makes `created` wrong |
| Q-RES-SET-POSITION | :123 | W | M `Location` | `key` | stamp | MED |
| Q-RES-LOAD-NODES | :130 | R | M label-less | `key = $key OR STARTS WITH $prefix` | `MATCH (o {tenantId:$tenant}) WHERE ...` | HIGH: `_load` builds `nodes[stored_key]` (`resource_store.py:596-600`), so two scopes' nodes with one key overwrite each other and `from_graph` rebuilds a mixed resource silently |
| Q-RES-LOAD-RELS | :135 | R | M label-less `o` and `t` | `key` | `MATCH (o {tenantId:$tenant})-[r]->(t {tenantId:$tenant})` | HIGH: same, and returns `endProps` of the other scope's targets |
| Q-RES-IDEM-GET | :143 | R | M `IdempotencyRecord` (property `idemKey`) | `idemKey`; **no constraint** | stamp. Better: delete the pair. No code outside tests passes `idempotency_key` to `put` (grep), and DEC-053 item 15 says it moves to P15, which is built | MED: replay returns another scope's version id |
| Q-RES-IDEM-RECORD | :148 | W | G `IdempotencyRecord` | `idemKey`; no constraint | stamp, or delete with the pair | MED: shares the label with P15's records, which key on `key` (0029) |
| Q-RES-HISTORY | :154 | R | M `Resource`, `ResourceVersion` | `key` | stamp both | HIGH: lists another scope's version keys, then `_load` reads them; history holds old postcodes (DEC-053 item 17b) |

### 2.2 `graph_store/service_repository.py`, `capacity_repository.py`, `booking_repository.py`, `case_repository.py`

| Id | file:line | R/W | Labels | Anchor today | Change | Risk |
|---|---|---|---|---|---|---|
| Q-SVC-LIST-ACTIVE | service_repository.py:42 | R | M `HealthcareService` | none (property `active`, index `svc_active` 0006) | `{active:true, tenantId:$tenant}`; index becomes `(tenantId, active)` | HIGH: every scope's active services appear on every board |
| Q-CAP-LATEST | capacity_repository.py:57 (f-string, fragment `_LATEST_OF_SERVICE` :50-53) | R | M `HealthcareService`, `Observation` | `key` | stamp `s` and the inner `o` inside the fragment | MED |
| Q-CAP-LATEST-FOR | :62 (f-string) | R | same | `key` list | same | MED |
| Q-CAP-SINCE | :70 | R | M `Observation`, `HealthcareService` | `key` | stamp both | MED |
| Q-SVC-LAST-REPORT | :79 | R | M `HealthcareService`, `Observation` | none | stamp both | HIGH: all scopes' services and last-report times |
| Q-BOOK-PENDING | booking_repository.py:42 | R | M `Task`, `HealthcareService` | service `id` (unique today only globally) | stamp both; the pending count feeds board availability | MED |
| Q-BOOK-OPEN-FOR | :50 | R | M `Task`, `HealthcareService` | `s.id IN $ids` | stamp both | MED |
| Q-BOOK-CONFIRMED-SINCE | :59 | R | M `Task`, `HealthcareService` | `id` | stamp both | MED |
| Q-BOOK-CONFIRMED-FOR | :67 | R | M `Task`, `HealthcareService`, `Task_Output`, `Concept` | `s.id IN $ids` | stamp `t`, `s`, `o` (and `c` if Concept is stamped) | MED |
| Q-BOOK-BY-REF | :79 | R | M `Task` | `reference` (4 digits); no constraint, no index | stamp `t`; no schema change needed beyond a `(tenantId, reference)` index | HIGH: references are 1000 to 9999 (`booking_rules.py:22-23`), so two scopes hold the same reference routinely; an SMS reply "4821" would act on another scope's booking. DEC-131 item 3 makes tenant-scoped uniqueness the rule |
| Q-BOOK-SET-PROPS | :87 | W | M `Task` | `key` | stamp | MED |
| Q-CASE-BY-REF | case_repository.py:107 | R | M `ServiceRequest` | `reference` unique (0022) | stamp; 0022 becomes `(tenantId, reference)` | HIGH once 0022 is composite: 9000 values, collision is normal. Note the single global constraint already means 9,000 cases for all time (closed cases keep their reference) |
| Q-CASE-SET-POSTCODE | :112 | W | M `Patient` | `key` | stamp | MED (writes a postcode into another scope's patient stub) |
| Q-CASE-READ-POSTCODE | :117 | R | M `Patient` | `key` | stamp | MED (reads another scope's postcode) |
| Q-CASE-SET-REFERENCE | :122 | W | M `ServiceRequest` | `key` | stamp; `ConstraintError` to `Conflict` mapping (`case_repository.py:114`) relies on the composite constraint existing | MED |

### 2.3 `graph_store/criteria_repository.py`, `flag_repository.py`

| Id | file:line | R/W | Labels | Anchor | Change | Risk |
|---|---|---|---|---|---|---|
| Q-CRIT-LOCK-SERVICE | criteria_repository.py:65 | W | M `HealthcareService` | `id` | stamp; lock anchor unchanged (the service node) | MED: on a repeated id it locks both scopes' services and `locked` reads 2 |
| Q-CRIT-LABEL | :72 | W | M `Basic` | `key` | stamp | MED |
| Q-CRIT-SUBJECT | :77 | R | M `ServiceCriteria`, `HealthcareService` | `key` | stamp both | MED |
| Q-CRIT-CURRENT | :85 | R | same | service `id` | stamp both | MED |
| Q-CRIT-CURRENT-FOR | :94 | R | same | `s.id IN` | stamp both | MED |
| Q-CRIT-VERSIONS | :102 | R | same | `id` | stamp both | MED |
| Q-CRIT-SET-CURRENT | :110 | W | M `HealthcareService`, unlabelled link target, `Basic`; G `CURRENT_CRITERIA` rel | `id`, `key` | stamp `s`, the delete target, and `c`; `CURRENT_CRITERIA` is in `LOCAL_RELATIONSHIP_TYPES` (`resource_store.py:51`), no change | MED: would link scope A's service to scope B's criteria |
| Q-CRIT-CLEAR-CURRENT | :123 | W | M `HealthcareService`, `Basic` | `id`, `key` | stamp both | MED |
| Q-FLAG-OBS-LOCK | flag_repository.py:47 | W | M `Observation` | `key` | stamp | MED |
| Q-FLAG-OBS-SERVICE | :52 | R | M `Observation`, `HealthcareService` | `key` | stamp both | MED |
| Q-FLAG-REPORT-EXISTS | :60 | R | M `ReportFlag` | `id` unique (0027) | stamp; 0027 composite | MED: an existence oracle across scopes |
| Q-FLAG-REPORT-ADD | :65 | W | M `Observation`; C `ReportFlag` | `key`; the new flag is unique on `id` | `MATCH (o:Observation {key:$key, tenantId:$tenant}) CREATE (f:ReportFlag {tenantId:$tenant}) SET f += $props, f.tenantId = $tenant` | MED |
| Q-FLAG-REPORT-LOCK | :73 | W | M `ReportFlag` | `id` | stamp | MED |
| Q-FLAG-REPORT-GET | :78 | R | M `ReportFlag`, `Observation` | `id` | stamp both | MED |
| Q-FLAG-REPORT-SAVE | :86 | W | M `ReportFlag` | `id` | stamp | MED: could resolve another scope's flag |
| Q-FLAG-REPORT-OPEN | :94 | R | M `ReportFlag`, `Observation` | none (status filter; `serviceId` optional) | stamp both | HIGH: with `serviceId` null it returns every scope's open flags |
| Q-FLAG-SERVICE-LOCK | :104 | W | M `HealthcareService` | `id` | stamp | MED |
| Q-FLAG-BASIC-STATE | :111 | R | M `Basic` | `key` | stamp | MED |
| Q-FLAG-LABEL | :116 | W | M `Basic` | `key` | stamp | MED |
| Q-FLAG-SERVICE-ACTIVE | :121 | R | M `ServiceFlag`, `HealthcareService` | service `id` | stamp both | MED |
| Q-FLAG-SERVICES-WITH | :130 | R | M `ServiceFlag`, `HealthcareService` | none | stamp both | HIGH: returns every scope's suspended service ids; the board marks services Not updated by id match |

### 2.4 `graph_store/person_repository.py`, `registration_repository.py`, `scope_list_repository.py`

| Id | file:line | R/W | Labels | Anchor | Change | Risk |
|---|---|---|---|---|---|---|
| Q-PERSON-PHONE-FIND | person_repository.py:68 | R | M `Practitioner` | `phoneHash` (index `phone_hash` 0007, not unique) | stamp; index `(tenantId, phoneHash)` | HIGH: DEC-065 item 1 raises `Conflict` when two active practitioners share a phone, so a phone held in two scopes (DEC-131 item 3 says this happens) would fail every lookup in both |
| Q-PERSON-ROLES-OF | :75 | R | M `PractitionerRole`, `Practitioner` | `key` | stamp both | MED |
| Q-PHONE-SERVICES-HELD | :84 | R | M `Practitioner`, `PractitionerRole`, `HealthcareService`, inner `Practitioner` in `NOT EXISTS` | `phoneHash` | stamp all four patterns | HIGH: returns other scopes' service names to a phone |
| Q-PHONE-SERVICES-AT | :96 | R | same | `phoneHash` | stamp all | HIGH |
| Q-SERVICE-REPORTER-ROLES | :107 | R | M `PractitionerRole`, `HealthcareService` | `key` | stamp both | MED |
| Q-PERSON-SET-PROPS | :115 | W | M `Practitioner` | `key` | stamp | MED |
| Q-ROLE-CHANNEL | :124 | W | G `Concept`; M `PractitionerRole`; C `CHANNEL` rel | MERGE on `(system, code)` (0003) | stamp `r`; Concept per section 4 (stamp it) | HIGH if Concept stays shared: a tenant request writes the shared node (DEC-130 item 5 says never). It also leaves an orphan Concept when the role is missing (MERGE runs before the MATCH) |
| Q-ROLE-COVER | :134 | W | M `PractitionerRole`, `Practitioner`; C `COVERED_BY` | `key` | stamp both | MED: could cover a role with another scope's practitioner |
| Q-REG-BY-STATUS | registration_repository.py:64 | R | M `Task`, `Concept` | `businessStatus` (index 0005, composite with `status`) | stamp `t` (and `c` if stamped) | HIGH: the registration approval queue would list every scope's registrations |
| Q-REG-FOR-SERVICE | :72 | R | M `Task`, `HealthcareService`, `Concept` | service `id` | stamp all | MED |
| Q-REG-SET-PROPS | :81 | W | M `Task` | `key` | stamp | MED |
| Q-REG-DRAFT-CLEAR | :90 | W | M `RegistrationDraftField`, `Task`; `DETACH DELETE` | `key` | stamp both | MED: deletes draft rows of another scope's registration |
| Q-REG-DRAFT-ADD | :95 | W | M `Task`; C `RegistrationDraftField` | `key` | `CREATE (:RegistrationDraftField {tenantId:$tenant, step:..., field:..., value:...})` and stamp `t` | MED |
| Q-REG-DRAFT-FOR | :104 | R | M both | `key` | stamp both | MED |
| Q-SCOPE-ENSURE-LIST | scope_list_repository.py:39 | W | G `Resource:List` | `id:'scope-list'`, unique via `Resource.id` (0001): **one list for the whole database** | `MERGE (l:Resource:List {id:$id, tenantId:$tenant})`; one list per scope | HIGH: scope B's first save writes into scope A's list |
| Q-SCOPE-LOCK-LIST | :48 | W | M `List` | `id` | stamp; the lock anchor changes from the singleton to the per-tenant list | HIGH |
| Q-SCOPE-UPSERT-ENTRY | :53 | W | M `List`, `HealthcareService`; G `ENTRY` | `id` | stamp both | HIGH: `ENTRY` joins the shared list to every scope's services |
| Q-SCOPE-ENTRIES | :62 | R | M `List`, `HealthcareService` | `id` | stamp both | HIGH: one list, so every scope reads every entry |
| Q-SCOPE-ENTRY-FOR | :70 | R | same | `id` | stamp both | HIGH |

### 2.5 `graph_store`: platform stores

| Id | file:line | R/W | Labels | Anchor | Change | Risk |
|---|---|---|---|---|---|---|
| Q-WORK-GET | scheduled_work_repository.py:29 (f-string, `_FIELDS` :22) | R | M `ScheduledWork`, `Resource` | `id` unique (0009) | stamp both | MED |
| Q-WORK-ADD | :36 | W | G `ScheduledWork`, `Resource` placeholder (no `id` set, `:41`); G `ABOUT` | MERGE on `id`; MERGE on `key` | `MERGE (w:ScheduledWork {id:$id, tenantId:$tenant})`, `MERGE (s:Resource {key:$aboutId, tenantId:$tenant})`; 0009 composite | HIGH: attaches work to another scope's resource, or an equal `id` reads as "already stored" and raises `Conflict` |
| Q-WORK-SAVE | :50 | W | M `ScheduledWork` | `id` | stamp | MED: could re-time another scope's prompt |
| Q-WORK-FOR-ABOUT | :62 (f-string) | R | M `ScheduledWork`, `Resource` | `key` | stamp both | MED |
| Q-COMM-ADD | communication_repository.py:52 | W | G `Concept` x2 (by `key`); C `Resource:Communication`; C `TOPIC`, `MEDIUM` | Concept: `key` (constraint is on `(system, code)`); Communication `id` unique (0014) | stamp `c`; Concept per section 4; 0014 composite | MED (HIGH if Concept stays shared: a tenant request writes it) |
| Q-COMM-LINK-RECIPIENT | :65 | W | M `Communication`; G `Resource:PractitionerRole` placeholder | `id`; MERGE on `key` | stamp both | MED |
| Q-COMM-LINK-ABOUT | :72 | W | M `Communication`; G `Resource:HealthcareService` placeholder | same | stamp both | MED |
| Q-COMM-LINK-REPLY | :79 | W | M `Communication` x2 | `id` | stamp both | MED |
| Q-COMM-EXISTS | :84 | R | M `Communication` | `id` | stamp | MED |
| Q-COMM-GET | :88 (`+ _READ` :42-49) | R | M `Communication`, optional `Concept` x2, `PractitionerRole`, `HealthcareService` | `id` | stamp `c`, `role`, `subject` (+ Concept) in `_READ` | MED |
| Q-COMM-BY-PROVIDER | :89 | R | M `Communication` + `_READ` | `providerMessageId` (index 0015) | stamp; index `(tenantId, providerMessageId)`. DEC-131 item 2 resolves the tenant from `AccountSid` first, then this runs bound | MED: provider ids are globally unique, but this is webhook-driven input |
| Q-COMM-SET-STATUS | :93 | W | M `Communication` | `providerMessageId` | stamp | MED: a forged receipt could change another scope's message |
| Q-COMM-LATEST-PROMPT | :98 (`+ _READ`) | R | M `Communication`, `Concept`, `PractitionerRole` | `role.id IN` | stamp all | MED: decides how an inbound reply is read |
| Q-LINK-ADD | link_token_repository.py:20 | W | C `LinkToken` | `tokenHash` unique (0021) | `CREATE (t:LinkToken {tenantId:$tenant, ...})`; keep 0021 global (section 3) | LOW: an unstamped token could not be traced to a scope |
| Q-LINK-GET | :26 | R | M `LinkToken` | `tokenHash` | stamp; plus a new global resolver `Q-LINK-TENANT-OF` that returns only the scope id (DEC-131 item 5) | MED |
| Q-LINK-MARK-USED | :34 | W | M `LinkToken` | `tokenHash`; lock `SET t.tokenHash = t.tokenHash` | stamp | MED |
| Q-LINK-BURN-KEY | :41 | R | M `LinkToken` | `tokenHash` | stamp | LOW |
| Q-CONTACT-PUT | contact_store.py:24 | W | G `ProtectedContact` | `key` = `roleId|kind`, unique (0025) | `{key:$key, tenantId:$tenant}`; 0025 composite | HIGH: phone numbers and emails; a role id repeated across scopes overwrites or reads the other scope's contact |
| Q-CONTACT-GET | :31 | R | M `ProtectedContact` | `key` | stamp | HIGH (same data) |
| Q-CRED-PRACTITIONER-EXISTS | credential_store.py:35 | R | M `Practitioner` | `key` | stamp | MED |
| Q-CRED-SET | :39 | W | M `Practitioner`; G `Credential`, `HAS_CREDENTIAL` | `deviceId` unique (0026) | stamp `p` and the Credential map; 0026 composite | MED: overwrites a PIN hash |
| Q-CRED-GET | :49 | W | M `Practitioner`, `Credential` | lock `SET c.deviceId = c.deviceId` | stamp both | MED |
| Q-CRED-SAVE-STATE | :56 | W | same | `deviceId` | stamp both | MED |
| Q-CRED-CLEAR | :63 | W | M `Practitioner`, `Credential`; `DETACH DELETE` | `key` | stamp both | MED: clears another scope's PIN |
| Q-DEVICE-LOCK | :70 | W | M `Practitioner` | lock `SET p.key = p.key` | stamp | MED |
| Q-DEVICE-OWNER | :74 | R | M `Practitioner`, `Device` | `Device.id` unique (0023) | stamp both; 0023 composite | HIGH: the "device registered to another practitioner" check (`credential_store.py:186`) would refuse a device that two organisations' staff both use |
| Q-DEVICE-REGISTER | :78 | W | M `Practitioner`; C `Device` | `key` | `CREATE (p)-[:HAS_DEVICE]->(:Device {tenantId:$tenant, ...})` | MED |
| Q-DEVICE-KNOWN | :84 | R | M `Practitioner`, `Device` | `key`, `deviceId` | stamp both | MED |
| Q-DEVICE-REVOKE | :89 | W | M `Practitioner`, `Device` | `key` | stamp both | MED |
| Q-IDEM-HEAD | idempotency_store.py:42 | R | M `IdempotencyRecord` | `key` unique (0029) | stamp; 0029 composite | HIGH: command keys are client supplied; a repeat returns another scope's stored result (ids, values) |
| Q-IDEM-VALUES | :46 | R | M `IdempotencyRecord`, `IdempotencyValue` | `key` | stamp both | HIGH |
| Q-IDEM-EDGES | :52 | R | M record and two values | `key` | stamp all three | HIGH |
| Q-IDEM-CREATE | :58 | W | C record, C `IdempotencyValue` | `key` | stamp both creates | HIGH |
| Q-IDEM-LINK | :68 | W | M record, two values; C `MEMBER` | `key`, `seq` | stamp all three | HIGH |
| Q-PROCESSED-MARK | :77 | W | G `Processed` | `key` unique (0030); claim property trick | `{key:$key, tenantId:$tenant}`; 0030 composite | HIGH, silent: scope A having handled message id X for consumer C makes scope B's identical id report "duplicate" and drop the work with no error |

### 2.6 `audit_neo4j`

| Id | file:line | R/W | Labels | Anchor | Change | Risk |
|---|---|---|---|---|---|---|
| Q-AUDIT-ENSURE-HEAD | audit_log.py:95 | W | G `AuditHead` | `id:'audit'` unique (0017): **singleton** | `MERGE (h:AuditHead {id:'audit', tenantId:$tenant}) ON CREATE SET h.lastHash=$genesis, h.lastSeq=0`; 0017 composite; per-scope genesis | HIGH: one head for the platform |
| Q-AUDIT-LOCK-HEAD | :103 | W | M `AuditHead` | `id:'audit'`; lock `SET h._lock = coalesce(h._lock,0)+1` | stamp; lock anchor becomes per-scope head | HIGH: all scopes queue on one lock and share `lastHash` and `lastSeq`, so there is one chain |
| Q-AUDIT-APPEND | :111 | W | M `AuditHead`; C `AuditEvent:ChainLink`, `Snapshot`; C `SNAPSHOT` | `ChainLink.seq` unique (0020); `AuditEvent.id` unique (0016) | stamp `h`, `e`, `s`; 0016 and 0020 composite | HIGH |
| Q-AUDIT-LINK-AGENT | :127 | W | M `AuditEvent`; G `AuditRef`; C `AGENT` | `AuditRef.id` unique (0018) | stamp both; 0018 composite | HIGH: `AuditRef` is merged by id alone, so two scopes' events share one node: a traversal path between audit chains |
| Q-AUDIT-LINK-ENTITY | :136 | W | M `AuditEvent`; G `AuditRef`; G `ENTITY` | `AuditRef.id` | stamp both | HIGH (same) |
| Q-AUDIT-LIST | :146 | R | M `AuditEvent` | none | stamp | HIGH: `records()` returns every scope's events; `since` logic breaks |
| Q-AUDIT-HEAD | :156 | R | M `AuditHead` | `id` | stamp | HIGH |
| Q-AUDIT-CHAIN | :163 | R | M `ChainLink`, optional any `m`, `Snapshot`, `Concept` | none | stamp `n` and `m` | HIGH: `verify_chain` walks every scope's links; reads their `entryJson` |
| Q-PROV-APPEND | :177 | W | M `AuditHead`; C `Provenance:ChainLink` | `seq`, `Provenance.id` (0019) | stamp both; 0019, 0020 composite | HIGH |
| Q-PROV-LINK | :190 | W | M `Provenance`; G `AuditRef` x2, `Concept`; G `TARGET`, `AGENT`, `ACTIVITY` | `AuditRef.id`, Concept `(system, code)` | stamp all; Concept per section 4 | HIGH |
| Q-PROV-SOURCE | :204 | W | M `Provenance`; G `AuditRef` | `AuditRef.id` | stamp both | HIGH |
| Q-OUTBOX-ADD | outbox.py:37 | W | C `OutboxMessage` | `id` unique (0028) | `CREATE (m:OutboxMessage {tenantId:$tenant}) SET m += $props, m.tenantId = $tenant`; 0028 composite | MED |
| Q-OUTBOX-PENDING | :41 | R | M `OutboxMessage` | none (status, `LIMIT`) | stamp | HIGH: a relay would publish every scope's messages under one scope, and `LIMIT` lets one scope starve another |
| Q-OUTBOX-LOCK | :47 | W | M `OutboxMessage` | `id`; lock `SET m.id = m.id` | stamp | MED |
| Q-OUTBOX-PUBLISHED | :51 | W | M `OutboxMessage` | `id` | stamp | MED |
| Q-OUTBOX-FAILED | :56 | W | M `OutboxMessage` | `id`; lock | stamp | MED |

### 2.7 `graph_store/health.py`

| Id | file:line | R/W | Labels | Anchor | Change | Risk |
|---|---|---|---|---|---|---|
| Q-NEO4J-PING | health.py:13 | R | none (`RETURN 1`) | none | declare `scope="global"`; exempt from `$tenant` | LOW: global by design |

### 2.8 Unmerged branches (not on `main`), listed separately

| Branch | Id | file:line on branch | R/W | Labels | Anchor | Change | Risk |
|---|---|---|---|---|---|---|---|
| `task/U02-confirm-capacity` | Q-CAP-LOCK-SERVICE | capacity_repository.py:79 | W | M `HealthcareService` | `key`; lock `SET s.id = s.id` (DEC-112 item 8) | stamp | MED |
| `task/U02-confirm-capacity` | Q-CAP-TRAILING-CONFIRMS | capacity_repository.py:86 | R | M `Observation`, `HealthcareService` | `key`; reads `o.ext_reportType` | stamp both | MED: counts another scope's confirmations on a repeated service key |
| `task/U03-send-prompts` | none | | | | | the branch adds `application/scheduling.py` and `use_cases/send_prompts.py`, which call `uow.scheduled_work.add/get/save` and `uow.outbox.add` (existing statements). It derives message ids as `cancel-{work.id}` (scheduling.py), fine under composite ids | |
| `task/I04-consumer-framework` | none | | | | | `workers/consumer.py:56` calls `uow.processed.mark_if_new(message.id, name)` inside `self._uow_factory()`; the tenant must be bound before that call from the validated message property (section 7). `servicebus_runner.py` is the binding site | |
| `task/W02-bff-session-csrf` | none | | | | | front end only | |

Migrations on those branches: none. `migrations.py` on all four branches is identical to `main` (checked with `git show <ref>:...`). **No ref in the repository, local or remote, uses migration ids 0031 to 0035** (grep of `migrations.py` and of `docs` on every ref). The brief's note that unmerged branches already use 0031 to 0035 is not borne out; if some session holds those ids it has not committed them. Tasks planned but not yet built that will add Cypher: G11 (`Q-CRIT-FILTER`, `Q-CRIT-HISTORY` with `SUPERSEDES*0..`), P17 to P20, O06, O08. Per DEC-130 item 10 they are written tenant-aware from the start.

### 2.9 Observed defects found while reading (not tenancy, but they touch the same statements)

- Every put creates the `IN_SYSTEM` relationship again: the mapper emits `IN_SYSTEM` (Concept to CodeSystem) for each coding (`mapper.py:467`), `ResourceStore._put` passes all `rels` to `_write_rels` (`resource_store.py:435`), and `Q-RES-MERGE-RELS` is `CREATE`, not `MERGE`. Owned relationships are cleared first (`Q-RES-CLEAR-ROOT-RELS`), but `IN_SYSTEM` starts at a shared node, so it accumulates. Found by reading; not run. Under tenancy this is a tenant request mutating reference data on every write.
- `CodeSystem` has no unique constraint at all (only `Concept` and `Identifier` do), so a race can create two.
- `Migration.id` has no unique constraint (`migrations.py:137` MERGE only).
- `Q-ROLE-CHANNEL` creates the Concept before it checks the role exists (orphan Concept on a missing role).
- `ensure_audit_head` and `apply_migrations` are not wired into the composition root (`bootstrap/container.py` opens the connection only), so a production start today has no audit head and no schema.

---

## 3. SCHEMA

### 3.1 Every constraint and index, and what it becomes

| Migration | Name and definition today | Under tenancy |
|---|---|---|
| 0001_resource_id | `resource_id`: `Resource.id` unique | drop; create `Resource (tenantId, id)` unique. Also create `Resource (tenantId, key)` unique (new: gives the index `key` lookups never had, and makes `Q-RES-LOCK` race-safe). Nodes lacking `key` (`Communication`, `List`, written without it) or `id` (placeholders made by `Q-WORK-ADD`) are ignored by uniqueness, as today |
| 0002_identifier_key | `identifier_key`: `Identifier (system, value)` unique | drop; `Identifier (tenantId, system, value)` unique (DEC-130 item 5: tenant-scoped) |
| 0003_concept_key | `concept_key`: `Concept (system, code)` unique | recommended: `Concept (tenantId, system, code)` unique plus new `CodeSystem (tenantId, url)` unique. If the owner keeps Concept shared (DEC-130 item 5 as written), this stays as is, a seeded catalogue and a refusal of unknown codes are required, and the stamp lint needs a label allowlist (section 4) |
| 0004_obs_by_service | index `Observation (effectiveDateTime)` | `Observation (tenantId, effectiveDateTime)`. Name misleading (not by service); `Q-CAP-LATEST*` filter through `FOCUS`, so this index helps only the date sort |
| 0005_task_by_status | index `Task (status, businessStatus)` | `Task (tenantId, businessStatus)`; note the queries filter `businessStatus` alone, so the existing composite is not usable by them (pre-existing) |
| 0006_svc_active | index `HealthcareService (active)` | `(tenantId, active)` |
| 0007_phone_hash | index `Practitioner (phoneHash)` (not unique) | `(tenantId, phoneHash)` |
| 0008_location_position | point index `Location (position)` | unchanged: a point index is single-property. No registered query uses it (only `Q-RES-SET-POSITION` writes `position`); a spatial query must filter `tenantId` after the lookup |
| 0009_scheduled_work_id | `scheduled_work_id`: `ScheduledWork.id` | `(tenantId, id)` |
| 0014_communication_id | `Communication.id` | `(tenantId, id)` |
| 0015_communication_provider_id | index `Communication (providerMessageId)` | `(tenantId, providerMessageId)` |
| 0016_audit_event_id | `AuditEvent.id` | `(tenantId, id)` |
| 0017_audit_head_id | `AuditHead.id` | `(tenantId, id)`; one head per scope |
| 0018_audit_ref_id | `AuditRef.id` | `(tenantId, id)` |
| 0019_provenance_id | `Provenance.id` | `(tenantId, id)` |
| 0020_chain_seq | `ChainLink.seq` | `(tenantId, seq)`: one sequence per scope |
| 0021_link_token_hash | `LinkToken.tokenHash` | **keep as is (global)**: the token hash is an HMAC of a random token, and DEC-131 item 5 says the hash lookup yields the tenant, so it must be findable without a scope. Add `tenantId` as a property and an index `LinkToken (tenantId, tokenHash)` is unnecessary. Owner question 5 |
| 0022_case_reference_id | `ServiceRequest.reference` | `(tenantId, reference)` |
| 0023_device_id | `Device.id` | `(tenantId, id)` |
| 0024_protected_contact_role_id | index `ProtectedContact (roleId)` | `(tenantId, roleId)` (no registered query uses it) |
| 0025_protected_contact_key | `ProtectedContact.key` | `(tenantId, key)` |
| 0026_credential_device_id | `Credential.deviceId` | `(tenantId, deviceId)` |
| 0027_report_flag_id | `ReportFlag.id` | `(tenantId, id)` |
| 0028_outbox_message_id | `OutboxMessage.id` | `(tenantId, id)` |
| 0029_idempotency_key | `IdempotencyRecord.key` | `(tenantId, key)` |
| 0030_processed_key | `Processed.key` | `(tenantId, key)` |

Rules that make the swap safe.
1. Create the composite constraint first, then backfill, then drop the old one. Both can coexist (an unstamped node does not violate a composite constraint). Dropping first leaves a window with no uniqueness, and every `ConstraintError` to `Conflict` mapping in the repositories (about 12 sites) depends on the constraint existing.
2. A composite constraint ignores a node whose `tenantId` is null. Community has no `IS NOT NULL` constraint (Enterprise only), so an unstamped node is not caught by the database. Add an invariant query (below) to CI and to a health check.
3. A schema statement and a data write cannot share a transaction (lesson in `ledger.jsonl`, and the comment at `migrations.py:146`); the runner already uses one transaction per statement and one for the record.
4. Applied migrations are never edited (`migrations.py:4`). The old constraints are dropped by name in a later migration. A fresh database runs 0001 to 0030, then the swap.
5. `apply_migrations` takes a bare string per migration. The backfill needs a parameter (the default tenant id) and a loop, so the entry type becomes a small `Migration` object (statement, params, loop-until-zero) or a callable. `CALL {...} IN TRANSACTIONS` is not available inside `execute_write`, so loop with `LIMIT` in separate managed transactions, as `tests/support/neo4j.py:236` already does for the wipe.

### 3.2 Migration plan (ids start at 0031, in order)

No other ref uses these ids (section 2.8), so 0031 is free. If the owner has no data to keep (question 1), 0032 is a no-op; keep it anyway so the same code runs everywhere.

| Id | Content |
|---|---|
| 0031_tenant_registry | `Tenant.id` unique (global registry node: `Tenant {id, name, status}`); `TenantNumber.e164` unique for DEC-131 item 2 (inbound number to tenant). Registry labels carry no `tenantId` |
| 0032_tenant_composites | create every composite constraint and index in the table above (`IF NOT EXISTS`), including the new `Resource (tenantId, key)` and `CodeSystem (tenantId, url)` |
| 0033_backfill_default_tenant | create the default `Tenant`; stamp every node that is not `Migration`, `Tenant` or `TenantNumber` with the default tenant id, in batches of 10,000; create the default tenant's `AuditHead` if absent |
| 0034_drop_single_constraints | `DROP CONSTRAINT ... IF EXISTS` for the 18 replaced constraints (all of section 3.1 except `link_token_hash`, which stays) and `DROP INDEX` for the 6 replaced indexes |
| 0035_tenant_invariant_marker | records that the invariant query returned zero (a gate, optional) |

DEC-132 migrations continue at 0036 (section 10.1). The brief expected 0031 to 0035 might be taken; they are not, so no renumber is needed, but keep the L68 habit: each task checks `git for-each-ref` for the next free id before it commits.

Deployment order: stop writers, run 0031 to 0035, deploy the code. Old code running against stamped data writes unstamped nodes; there is no way to make old and new code coexist. A fresh Neo4j volume avoids all of it.

### 3.3 The invariant query (gate, CI, health check)

```
MATCH (n) WHERE n.tenantId IS NULL AND none(l IN labels(n) WHERE l IN $registryLabels) RETURN labels(n) AS labels, count(*) AS n
MATCH (a)-[r]->(b) WHERE a.tenantId <> b.tenantId RETURN type(r) AS type, count(*) AS n
```
`$registryLabels` is `Migration`, `Tenant`, `TenantNumber`, and the DEC-132 registry labels (section 10.1). Both must return no rows. Under DEC-132 `sourceTenantId` is not a stamp and the second query is unchanged because projections are stamped with the network scope id.

---

## 4. GLOBAL OR SINGLETON STATE

| State | Where | Today | Becomes |
|---|---|---|---|
| `AuditHead {id:'audit'}` | audit_log.py:56, :95, :103 | one per database, one lock, one chain | one per scope; `HEAD_ID` stays `'audit'`; provisioned explicitly when a scope is created (not lazily: lazy creation races, DEC-055 item 5) |
| `ChainLink.seq`, `AuditHead.lastSeq/lastHash` | 0020, audit_log.py:113-117 | one global sequence | `(tenantId, seq)`; genesis hash per scope (`GENESIS_HASH = "0"*64`, `application/ports/outbound/audit.py:21`). Recommend the hashed text stays unchanged so existing links verify, and new scopes get `sha256("diucs-genesis|"+scope)`; the default tenant keeps `"0"*64` |
| `Migration` nodes | migrations.py:136-137 | 26 global nodes, no unique constraint | stay global; excluded from the lint, the wipe and the invariant query |
| `IdempotencyRecord.key` (P15) | 0029; idempotency_store.py:42-86 | one key space | composite; client keys repeat across scopes |
| `IdempotencyRecord.idemKey` (ResourceStore) | resource_store.py:143-152 | second, unconstrained use of the same label | delete (dead code) or composite |
| `IdempotencyValue` | idempotency_store.py:46-76 | child tree; `seq` per record | stamp every node; no key of its own |
| `Processed.key` | 0030; idempotency_store.py:77 | `len:consumer:messageId` | composite; the dedup scope must be the tenant or silent drops occur (section 2.5) |
| `LinkToken.tokenHash` | 0021 | globally unique | keep global; add `tenantId`; a global resolver returns the scope id only (DEC-131 item 5) |
| `ScheduledWork.id` | 0009 | UUID in production | composite; U03 derives `cancel-{work.id}` |
| `OutboxMessage.id` | 0028 | UUID (production), `SequentialIds` (tests) | composite; the relay must iterate scopes (question 7) |
| Sequence counters | none stored | `ScheduledWork.sequenceNumber` is the Service Bus sequence number the relay writes back (broker-owned, not a counter) | no change |
| `SequentialIds` | adapters/testing/fixed_ids.py:4; `container.py:91` (`build_for_tests` only) | `id-1`, `id-2` from 1 in every test container | collides across test tenants; the harness passes a tenant-prefixed generator. Production uses `UuidGenerator` (`container.py:70`) |
| `List {id:'scope-list'}` | scope_list_repository.py:32, :41 | one list for the database | one per scope; composite `(tenantId, id)` on `Resource` fixes it |
| `Concept` | 0003; written at run time by `Q-RES-SHARED-CREATE`, `Q-ROLE-CHANNEL`, `Q-COMM-ADD`, `Q-PROV-LINK` | shared, written by ordinary requests | **recommend tenant-scoped** (below) |
| `CodeSystem` | `Q-RES-SHARED-CREATE` | shared, no constraint | tenant-scoped with `Concept` |
| `Identifier` | 0002 | shared by `(system, value)` | tenant-scoped (DEC-130 item 5, agreed): a shared `Identifier` joins scopes through `IDENTIFIED_BY`, and booking and case references are identifiers |
| Booking reference | `booking_rules.py:56` `new_reference(rng, taken)`, range 1000 to 9999 | **not enforced by the database anywhere** for bookings: `Task.reference` has no constraint; `taken` is built by the caller (U17, not built); `Q-BOOK-BY-REF` returns the latest match | uniqueness among open bookings per tenant, enforced by the use case under a lock (DEC-131 item 3). `Q-BOOK-BY-REF` becomes tenant-anchored, so `taken` is tenant-local with no further change |
| Case reference | 0022 | one global namespace of 9,000 values, kept after close | `(tenantId, reference)`; the 9,000-values-per-tenant ceiling remains (question 6) |

**Recommendation on `Concept`, `CodeSystem`, `Identifier`: tenant-scoped, all three.** DEC-130 item 5 says shared, read-only, and "never written by a tenant request", and allows an exception "unless a task finds it must differ". It must differ, for four reasons found in the code. (1) Four write paths create Concepts from tenant requests (`resource_store.py:93`, `person_repository.py:124`, `communication_repository.py:52`, `audit_log.py:190`), and the mapper accepts any coding from any resource, so "read-only" would need a seeded catalogue of every system and code the product uses plus a refusal of unknown codes, a new piece of work. (2) The `display` and `version` conflict rule (`resource_store.py:525-529`) makes one scope's text refuse another scope's write: a covert channel and a denial of service. (3) A shared node is the only node that can join two scopes, which DEC-130 item 1 forbids and the invariant query forbids. (4) Stamping all three keeps the lint rule simple: every labelled node pattern must carry `tenantId: $tenant`, with no label allowlist to maintain. The cost is a few hundred small nodes per tenant. If the owner prefers sharing later it is an optimisation: seed the catalogue, add the exception list, convert the six store templates.

---

## 5. THE MAPPER AND RESOURCESTORE

### 5.1 Where nodes and relationships are created, and where `tenantId` goes

The mapper (`mapper.py`) is pure and has no `tenantId`; it should stay that way. All writes go through six `ResourceStore` templates, so stamping lands in the queries, not in the mapper.

| What is created | Where | Statement | Stamp |
|---|---|---|---|
| Root node of a resource (`Resource:<Type>`) | `mapper.py:224`, written `resource_store.py:432` via `_write_nodes` | Q-RES-LOCK (`:409`) then Q-RES-UPSERT-ROOT | in both MERGE maps and `SET n = row.props, n.tenantId = $tenant` |
| Backbone child nodes (G04), keys `<parent>#<element>[i]`, 10 labels | `mapper.py:349-372` | Q-RES-UPSERT-NODE | same |
| Extensions (G04), `ext_<shortName>` and `extensionOrder` properties | `mapper.py:375-397` | no separate node: properties on root or child | none; but `ext_*` and `extensionOrder` must not collide with the new name, see 5.2 |
| Shared Concept, CodeSystem, Identifier (G03) | `mapper.py:462-466`, `:493`; `_apply_shared` `resource_store.py:536` | Q-RES-SHARED-CREATE, Q-RES-SHARED-FILL | stamp (section 4) |
| Placeholders for reference targets | `_write_placeholders` `:546` | Q-RES-MERGE-NODES | stamp. Same pattern in `Q-WORK-ADD` (`:41`), `Q-COMM-LINK-RECIPIENT`, `Q-COMM-LINK-ABOUT`, and the minimal service in `scope_list_repository.py:160` (via the store) |
| Version copies `ResourceVersion` and `ResourceVersionPart` (G05) | `_write_snapshot` `:478-500` | Q-RES-UPSERT-NODE (labels differ), Q-RES-MERGE-RELS | stamp; keys `Type/id@<v>` and `Type/id@<v>#child` |
| Relationships (owned, reference, concept, identifier, `IN_SYSTEM`, `HAS_VERSION`) | `_write_rels` `:555-568` | Q-RES-MERGE-RELS | no stamp on the relationship (DEC-130 item 1); both end nodes matched with `tenantId: $tenant` |
| Local relationships `CHANNEL`, `COVERED_BY`, `CURRENT_CRITERIA` (`LOCAL_RELATIONSHIP_TYPES`, `resource_store.py:51`) | `Q-ROLE-CHANNEL`, `Q-ROLE-COVER`, `Q-CRIT-SET-CURRENT` | repository statements | stamp the matched endpoints; the skip-list in `_load` (`:606`) is unaffected |
| Derived properties set after the put (`businessStatus`, `reference`, `postalCode`, `submittedAt`, `phoneHash`, `emailDomain`, `position`) and profile labels (`ServiceCriteria`, `ServiceFlag`) | `Q-BOOK-SET-PROPS`, `Q-CASE-SET-*`, `Q-REG-SET-PROPS`, `Q-PERSON-SET-PROPS`, `Q-RES-SET-POSITION`, `Q-CRIT-LABEL`, `Q-FLAG-LABEL` | stamp the MATCH. Important: a later put runs `SET n = row.props`, which erases these derived properties; the repositories re-set them after every put, and the stamp must survive the same way (R-SET) |

### 5.2 The property name `tenantId` leaks into the FHIR resource unless it is reserved

`from_graph` rebuilds every unknown node property as a FHIR element (`mapper.py:595-609` `_rebuild_property`; `:244-254` pops only `id`, `iri`, `meta` and known copies). `_load` hands it `_props_from_db`, which strips only `RESERVED_PROPERTIES` (`resource_store.py:48, :293-297`). A `tenantId` on every node would therefore appear as a `tenantId` element in every rebuilt resource and in every child. Required changes: add `tenantId` to `RESERVED_PROPERTIES` (so a FHIR element of that name is refused by `_node_props_to_db`, and the property is stripped on read), and to the mapper's refused names (`_MAPPER_NAMES`, `mapper.py:69`) so `to_graph` also refuses it. Under DEC-132 add `sourceTenantId` for the same reason, and the same two edits apply to `Concept`/`Identifier` properties read back through `endProps` (`resource_store.py:608-611`).

### 5.3 How `from_graph` rebuilds and whether it can read another scope's node

`get` calls `_root_props` (Q-RES-GET), then `_load` (Q-RES-LOAD-NODES, Q-RES-LOAD-RELS), then `from_graph`. It rebuilds from three label-less or label-light matches keyed only on `key` and `key STARTS WITH prefix`. Today these cannot cross because `Resource.id` is globally unique, so a key is globally unique. Once uniqueness is composite, a repeated resource id means: `_root_props` returns whichever row comes first; `_load` puts both scopes' nodes into one dict keyed by `key` (last one wins); relationships from both scopes are collected; `from_graph` builds one resource from a mixture. There is no error: `from_graph` raises only on a missing root or an unknown shape. History (`Q-RES-HISTORY`) behaves the same. Stamping every match fixes it; the generated test must include a mirror seed with identical ids to catch it.

### 5.4 Label-only and id-only matches that cross scopes

Beyond section 2: `:Concept` matches in `Q-BOOK-CONFIRMED-FOR`, `Q-REG-BY-STATUS`, `Q-REG-FOR-SERVICE`, `Q-COMM-ADD`, `Q-COMM-LATEST-PROMPT`, `Q-ROLE-CHANNEL`, `Q-PROV-LINK`, `Q-AUDIT-CHAIN` (if Concept stays shared these are the only statements that legitimately match an unstamped label; with the recommendation they all stamp). `:Identifier` is matched only through the mapper. `:Resource` by `key` appears in `Q-RES-*` and `Q-WORK-*`. `:Resource` / typed matches by `id` appear in `Q-CRIT-LOCK-SERVICE`, `Q-FLAG-SERVICE-LOCK`, `Q-BOOK-PENDING`, `Q-SCOPE-*`. The label-less matches are also the slow ones (no index applies); see risk 4.

---

## 6. CONCURRENCY LOCKS

The lessons L73, L85, L99, L142 and L126 are cited in decisions but are not in `docs/delivery/LESSONS.md` or `ledger.jsonl` on any worktree: both stop at L63. I used the decision text that quotes them (DEC-076 item 4, DEC-082 item 5, DEC-083 item 1, DEC-084 item 7, DEC-090 item 5, DEC-130 item 7).

| Trick | Statements | Anchor node | Does tenant scoping change the anchor? |
|---|---|---|---|
| MERGE the root then `SET lockStamp`, read the version after (L63) | Q-RES-LOCK | the resource root `(tenantId, key)` | No. The MERGE must carry `tenantId`, otherwise it locks, and writes a label and `lockStamp` on, another scope's node |
| Self-SET of an immutable property: `SET x.id = x.id` (L73, L99) | Q-CRIT-LOCK-SERVICE, Q-FLAG-OBS-LOCK, Q-FLAG-REPORT-LOCK, Q-FLAG-SERVICE-LOCK, Q-SCOPE-LOCK-LIST, Q-OUTBOX-LOCK, Q-OUTBOX-FAILED, and on the U02 branch Q-CAP-LOCK-SERVICE | the parent service, observation, flag, list or message | No for all but `Q-SCOPE-LOCK-LIST`. Without the stamp a repeated id makes `MATCH` return two nodes: both are locked (cross-scope blocking and a timing channel) and `count(...)` reads 2, which the callers treat as success (`criteria_repository.py:341`, `flag_repository.py:267`). **`Q-SCOPE-LOCK-LIST` moves from the one platform list to the per-scope list**, so scopes stop serialising on each other |
| Lock a property no write changes (L99: `status` was wrong, `id` is right) | Q-FLAG-REPORT-LOCK | the flag | No |
| Lock on `tokenHash` because a missing `usedAt` takes no lock (DEC-060 item 4) | Q-LINK-MARK-USED | the token | No (the hash stays globally unique) |
| Lock `deviceId` / practitioner `key` | Q-CRED-GET, Q-DEVICE-LOCK | credential, practitioner | No |
| Counter increment on the head: `SET h._lock = coalesce(h._lock,0)+1`, then read `lastHash` (L63) | Q-AUDIT-LOCK-HEAD | `AuditHead {id:'audit'}` | **Yes**: from one global head to one head per scope. Appends of different scopes stop queueing on each other (a throughput gain), and `_lock` is a per-head counter |
| Unique constraint as the lock (MERGE or CREATE, loser gets `ConstraintError` mapped to `Conflict`, L90/L106) | Q-SCOPE-ENSURE-LIST, Q-AUDIT-ENSURE-HEAD, Q-IDEM-CREATE, Q-PROCESSED-MARK, Q-CONTACT-PUT, Q-CRED-SET, Q-DEVICE-REGISTER, Q-LINK-ADD, Q-FLAG-REPORT-ADD, Q-OUTBOX-ADD, Q-COMM-ADD, Q-WORK-ADD, Q-RES-LOCK | the constraint | **Yes: the constraint itself changes** to the composite one. The MERGE or CREATE must carry `tenantId` or it does not match the new constraint's key. Do the constraint swap in the order of section 3.1 rule 1 |
| Claim token to detect the creator (`ON CREATE SET p.claim`, `REMOVE p.claim`) | Q-PROCESSED-MARK | the marker | No |
| Version check after the lock (`check_version`, DEC-084 context) | ResourceStore | root | No |

Net: only two anchors change (the audit head and the scope list), and 13 constraint-as-lock sites change their key. The recurring hazard is the same as everywhere else: an unstamped lock statement works in single-scope tests and fails silently with two scopes.

---

## 7. THE EXECUTION POINT

### 7.1 Context variable versus explicit parameter

DEC-130 item 2 says a context variable set at the edge. I agree, with one refinement, because a bare context variable read inside `run_query` fails open in three ways here: a background task created with `asyncio.create_task` copies the context at creation and keeps a stale tenant; a variable changed inside an open unit of work changes the tenant mid-transaction; and `DriverIdempotencyStore` (`idempotency_store.py:251-270`), `ensure_audit_head` and `neo4j_health` open their own sessions outside a unit of work.

Proposed shape (all in `diucs/application/tenancy.py` for the types, so the application layer can bind without importing Neo4j, and `graph_store/driver.py` for the execution):
1. `ScopeId`: a validated string with a kind (`tenant` or `network`, DEC-132) encoded in a fixed prefix, so a tenant id can never equal a network id. Validation on construction (non-empty, fixed pattern, length); `TenantNotBound` and `ScopeInvalid` errors with fixed messages.
2. `bound_scope(scope)`: a context manager over a `ContextVar[ScopeId | None]`. The **edge** sets it once: `adapters/inbound/fhir_rest/auth.py:82` `current_actor` (the signed BFF token gives the tenant claim), the Service Bus runner (`servicebus_runner.py` on the I04 branch, from the validated message property), the link-token resolver (global lookup, then bind), the Twilio webhook (number and `AccountSid`, DEC-131 item 2). Never a body, query or caller-controlled header (DEC-130 item 6).
3. `Neo4jUnitOfWork.__aenter__` (`unit_of_work.py:331`) reads the variable **once**, raises `TenantNotBound` if empty, stores the scope on the unit of work, and wraps the transaction: `self._tx = ScopedTx(tx, scope)`. A change of the variable afterwards is ignored. Opening a second unit of work while one is open in the same context raises (DEC-132: exactly one scope per unit of work; the projector's two units are sequential).
4. Every repository constructor changes from `AsyncManagedTransaction` to `ScopedTx` (about 20 classes, mechanical; `DEFAULT_FACTORIES` at `unit_of_work.py:240-260` passes it through). `ResourceStore(tx: ScopedTx, clock)`.
5. `run_query(tx: ScopedTx, query_id, /, *, registry=None, **params)`: raises `TypeError` for anything that is not a `ScopedTx` (so a raw transaction cannot run application Cypher: fail closed, and mypy strict catches it at type-check time too); raises if `"tenant"` is in `params` (fixed message; DEC-130 item 2: a caller cannot pass or override it); refuses a query whose `scope` is `global`; refuses a query whose declared scope kinds do not include the bound scope's kind (DEC-132); refuses a `write`-mode query on a read-only unit of work; then calls `tx.run(query.cypher, tenant=scope.value, **params)`.
6. `run_global_query(tx, query_id, /, **params)`: accepts a raw transaction, runs only `scope="global"` statements, and refuses any parameter named `tenant`. This is the only way to run the ping, the tenant resolvers and the registry statements (DEC-132).
7. `Neo4jConnection.run_read/run_write` (`connection.py:144-150`) keep passing a raw transaction (used only by `neo4j_health`, which runs a global statement). A scoped variant `run_scoped_read/write(scope, work)` wraps the transaction for `DriverIdempotencyStore`.
8. The existing `registry=` parameter of `run_query` (`driver.py:49`, used by `scheduled_work_repository.py:107`) stays, because the lint lives in `QueryRegistry.register` and so applies to every registry instance, not only the module one.
9. The query observer (`driver.py:34-35`, `set_query_observer`) keeps emitting only id, mode, rows, duration; add the scope kind, never the scope id or text.

**Exceptions that must bypass the binding, and how**:
- Migrations: `migrations.py` runs raw `tx.run` and records `Migration` nodes. It is not application Cypher and is not registered. An architecture test asserts that `.run(` on a transaction appears only in `driver.py` and `migrations.py` (proposed `tests/architecture/test_single_execution_point.py`: parse `src/diucs/adapters/outbound/**` with `ast`, fail on any `tx.run`, `_tx.run` or `session.run` elsewhere). The backfill (0033) lives in the migration runner and stamps with an explicit parameter, not `$tenant`.
- Health ping: `Q-NEO4J-PING` registered with `scope="global"`, run by `run_global_query`.
- Test wipe: `tests/support/neo4j.py:236` becomes `MATCH (n {tenantId: $t}) ... DETACH DELETE` for the run's tenants (DEC-130 item 9); the whole-database wipe stays available only to schema-changing tests, which run alone.
- Pre-scope resolvers (DEC-131): link token hash to scope, inbound number to scope. Each is a named `scope="global"` statement that returns the scope id and nothing else.
- Worker enumeration: a global `Q-TENANT-LIST` returns scope ids; the worker then binds each scope in turn (section 7.6). No cross-scope read of node data exists.
- `ensure_audit_head(driver)` (`audit_log.py:222`) becomes part of tenant provisioning, running in a bound unit of work.

Fail closed: no scope bound means `TenantNotBound` before any Cypher is sent (test: a recording transaction sees zero `run` calls); an unknown or malformed id raises on construction; a statement without a declared scope cannot be registered; there is no default tenant at run time (the default tenant exists only in the backfill migration).

### 7.2 Registration-time check (exact rules)

In `QueryRegistry.register` (`queries.py:30`), after the id and mode checks, for a `NamedQuery` with `scope == "tenant"` (default) or a scope set of `{tenant}`, `{network}`, or both:
1. The text must contain `\$tenant\b` (DEC-130 item 3, the minimum).
2. Node-pattern scan: find every parenthesised pattern that has a label or a property map, using `\(\s*(?P<var>\w*)\s*(?P<labels>(?::\w+)*)\s*(?P<props>\{[^}]*\})?\s*\)` (balanced-brace aware; relationship brackets are not node patterns). A pattern that is a bare variable (`(s)`, `(c)`) is a reuse of a bound node and is skipped. Every other pattern must satisfy one of: its map contains `tenantId:\s*\$tenant`; or the statement has a `WHERE`/`AND` clause `var.tenantId = $tenant` on that variable; or the variable is bound earlier by an `UNWIND`/`WITH` of a stamped variable. Otherwise registration fails, naming the query id and the pattern (never the parameter values).
3. For every `SET v = ...` or `SET v += ...` the same clause must also set `v.tenantId = $tenant` (rule R-SET), unless `v` is a relationship.
4. A statement must not contain `tenantId:` with any parameter other than `$tenant`, nor reference `sourceTenantId` outside a `scopes={'network'}` statement.
5. The `{insert}` templates are registered once with the placeholder filled by a neutral label so the scan passes; run-time variants (`_run` at `resource_store.py:572-582`) inherit from the checked template and do not re-register through a different path.
6. Label partition (DEC-132): each statement declares `scopes`; its labels must lie in the partition for those kinds (section 10.2). A tenant statement naming a `Projected*` label, or a network statement naming `HealthcareService`, fails registration.
7. `scope="global"` statements must contain no `$tenant`, must not match any non-registry label, and must be listed in a short constant `GLOBAL_QUERY_IDS` that the test pins (currently: ping, tenant list, tenant of link token, tenant of inbound number, and the DEC-132 registry statements).
The lint is a guard, not a proof (a regex cannot parse Cypher, and a pattern like `MATCH (a)--(b)` is stamped by inheritance). The behavioural test is the proof.

### 7.3 The generated two-tenant test (DEC-130 item 4), specified for a task prompt

File `tests/integration/graph_store/test_tenant_isolation.py`, one parametrised test per `REGISTRY.ids()` (plus the lazily registered `{insert}` variants, which the test forces by running the seed through `ResourceStore` first).
1. Each registered query carries a `probe`: the parameters that make it return or touch something in the mirror seed (for example `{"key": "HealthcareService/svc-1"}`). A tenant-scoped query with no probe fails with "no probe for Q-X", so a new query cannot be added without one. A probe may declare `expects_rows=False` for lock-only or empty-by-design statements.
2. Mirror seed `seed(scope, marker)`: builds, through the real repositories, one of everything with **identical ids and keys in both tenants** (services, a location and organisation, practitioners and roles sharing a phone hash, reports, a booking and a case with the same reference, criteria versions, flags, scope list, link token, communication, scheduled work, outbox message, audit events and provenance, idempotency record, processed marker, contact, credential, device), plus a few rows that exist only in B. Every node of B carries a poison property `marker='B'` where the schema allows, and B's text values are distinct strings.
3. For each query and probe: (a) baseline: seed A alone, run the query bound to A, record the normalised rows; (b) seed B on top; run the same query bound to A; assert rows equal the baseline (reads) and assert B's subgraph digest unchanged (writes: canonical sorted dump of every node with `tenantId = B` and every relationship among them, hashed before and after); (c) run bound to B and assert it equals B's own baseline; (d) after every probe assert the invariants of section 3.3 (no unstamped node, no relationship across scopes) and that every node the query created carries A's `tenantId`.
4. Writes run in their own committed unit of work; the graph is reseeded between probes (small seed, milliseconds).
5. Fail-closed cases in the same file: unbound scope raises before any Cypher for every id; a `tenant` parameter raises; a raw transaction raises; a `global` statement cannot run through `run_query`.
6. Proof of the test: a test-only registry holds `Q-TEST-LEAKY` variants (a label-only `MATCH`, an unstamped `MERGE`, a `SET n = map` without re-stamp) and the test asserts the harness catches each; plus one reviewed mutant per converted repository (remove one `tenantId` from one pattern) that must turn the generated test red (lesson L92 style).
7. Ratchet: land the test first with an `UNCONVERTED` set listing every id not yet converted; each repository task removes its ids; the last task asserts the set is empty. This lets the repository tasks run in parallel.

---

## 8. RISKS AND OPEN QUESTIONS FOR THE OWNER (ranked)

1. **All-or-nothing cutover with no database enforcement.** Isolation today exists only because ids are globally unique. Composite uniqueness makes every unconverted statement a leak, and one missed `tenantId` in one of ~124 statements is silent. Community cannot require `tenantId` to exist (existence constraints are Enterprise). Mitigation: the seam, the lint and the generated test land first; the invariant query is a CI gate and a health check. Question: is the Enterprise edition (open in `architecture.md`) worth deciding now, for existence constraints and role-based write restriction on the audit labels?
2. **`Concept` shared or tenant-scoped (section 4).** DEC-130 item 5 conflicts with four existing write paths and with the `display` refusal rule. I recommend tenant-scoped. Needs a ruling before TEN-G04.
3. **Pre-scope lookups.** Link token hash, inbound number and `AccountSid` (DEC-131), delivery receipts, the outbox relay, the scheduler and every DEC-132 registry read run without a scope. They form the `GLOBAL_QUERY_IDS` allowlist, and it is where the next leak will hide. Each must return a scope id or registry data only; each needs review. Question: does the outbox relay and the scheduled-work worker iterate tenants (my recommendation: `Q-TENANT-LIST` then one bound loop each) or run as one privileged worker? DEC-130 item 8 says no role holds cross-tenant access.
4. **Performance regression.** `key` has no index today (DEC-053 item 14a); label-less matches (`Q-RES-LOAD-NODES`, `Q-RES-LOAD-RELS`, `Q-RES-MERGE-RELS`, `Q-RES-CLEAR-OWNED`, `Q-RES-SHARED-*`) scan the whole graph and cannot use any index, about 10 per put. "Acceptable at pilot size" no longer holds when graph size is the sum of all tenants. Not measured here. Mitigation: `Resource (tenantId, key)` and typed patterns; task TEN-G13.
5. **Audit chain per scope.** The head is created by `ensure_audit_head`, which nothing calls in production. Genesis per scope; whether `tenantId` enters the hashed text (breaks verification of the existing chain if it does). My recommendation: leave the text, vary the genesis for new scopes. Question 4 below. Tenant erasure versus an append-only chain is also open.
6. **Test blast radius.** 12 files call `run_query`, 27 call `tx.run`, and every repository test builds a unit of work on a raw driver. The fixture can bind a tenant for most; direct `ResourceStore(tx)` users change. `SequentialIds` collides across parallel test tenants.
7. **Backfill and legacy data.** Question 1: is there any data beyond developer and test databases? If not, the backfill and the old-constraint window disappear.
8. **Reference exhaustion.** Case references are four digits, unique for all time in one namespace (9,000 values). Per-tenant scoping multiplies it, but a tenant that closes 9,000 cases cannot open another. Decide a reuse policy.
9. **Existing defects in the same statements** (section 2.9), notably the growing `IN_SYSTEM` edges.
10. **DEC-130 counts need correcting** (124 statements, not 78; 4 f-strings, not 2) and the DEC-053 item 15 idempotency copy should be removed.

Other questions: (a) tenant id format and immutability (it becomes the Redis prefix and a Service Bus property); (b) should `LinkToken.tokenHash` stay globally unique with a global resolver (recommended) and is the `link-token` HMAC secret global or per tenant (DEC-131 item 4); (c) tenant offboarding: deletion of a tenant's nodes in batches versus the audit chain's append-only rule and DEC-132 item 6 (history stays in the network); (d) does a bound tenant need an existence check at unit-of-work open (a cost per request) or only at the edge; (e) are registry changes (grants, membership) done in one registry unit of work plus outbox-driven audit entries, as I propose in section 10.5.

---

## 9. PROPOSED TASK BREAKDOWN

Hours are builder hours at the plan's granularity. Tasks TEN-G01 to TEN-G15 are DEC-130 and DEC-131; TEN-G16 to TEN-G23 are DEC-132 (section 10.7). Files are under `backend/src/diucs/adapters/outbound/` unless stated.

| Id | Title | Files | Hours | Depends on |
|---|---|---|---|---|
| TEN-G01 | The seam: `ScopeId`, `bound_scope`, `NamedQuery.scope`/`scopes`/`probe`, registration lint (7.2), `ScopedTx`, `run_query`/`run_global_query`, fail-closed errors, single-execution-point architecture test | `application/tenancy.py` (new), `graph_store/queries.py`, `graph_store/driver.py`, `tests/unit/...`, `tests/architecture/...` | 7 | none |
| TEN-G02 | Unit of work, connection, bootstrap and health on the scoped transaction: snapshot at open, one open unit per context, read-only mode, repository constructors take `ScopedTx`, `DriverIdempotencyStore` scoped, ping global | `graph_store/unit_of_work.py`, `connection.py`, `health.py`, `bootstrap/container.py`, every repository constructor (type change only) | 6 | G01 |
| TEN-G03 | Migration runner for parametrised and looped steps; migrations 0031 to 0035 (registry, composites, backfill, drops, gate); migration tests; update `EXPECTED_MIGRATION_COUNT` | `graph_store/migrations.py`, `tests/integration/graph_store/test_driver.py`, `tests/unit/.../test_migration_ids.py` | 6 | G01 |
| TEN-G04 | ResourceStore and mapper: stamp the six write templates and the read templates, reserve `tenantId`, per-label variants, drop `Q-RES-IDEM-*`, fix duplicate `IN_SYSTEM` | `graph_store/resource_store.py`, `mapper.py`, `tests/.../test_resource_store.py`, `test_mapper.py` | 9 | G01, G02, G03, owner ruling on Concept |
| TEN-G05 | Service, capacity, booking and case repositories (15 statements) | `service_repository.py`, `capacity_repository.py`, `booking_repository.py`, `case_repository.py` | 5 | G04 |
| TEN-G06 | Person, criteria, flag, registration and scope-list repositories (40 statements), one scope list per scope | `person_repository.py`, `criteria_repository.py`, `flag_repository.py`, `registration_repository.py`, `scope_list_repository.py` | 8 | G04 |
| TEN-G07 | Link tokens (with global resolver), contacts, credentials and devices, communications (25 statements) | `link_token_repository.py`, `contact_store.py`, `credential_store.py`, `communication_repository.py` | 7 | G04 |
| TEN-G08 | Scheduled work, idempotency store, processed markers, outbox (17 statements) | `scheduled_work_repository.py`, `idempotency_store.py`, `audit_neo4j/outbox.py` | 5 | G02 |
| TEN-G09 | Audit chain per scope: head provisioning, genesis, `Q-AUDIT-*`, `Q-PROV-*`, `_AUDIT_PROPERTIES` and `_RESERVED` gain `tenantId`, `verify_chain` per scope | `audit_neo4j/audit_log.py`, `.importlinter` if needed | 6 | G02, G03 |
| TEN-G10 | Tenant registry: `Tenant`, `TenantNumber`, global resolvers (`Q-TENANT-LIST`, `Q-LINK-TENANT-OF`, number to tenant), `provision_tenant` (audit head, scope list, optional seed) | `graph_store/tenant_registry.py` (new), tests | 5 | G03, G09 |
| TEN-G11 | Test harness: per-test tenant fixture, tenant-prefixed `SequentialIds`, wipe per tenant, convert the tests that build `ResourceStore(tx)` or call `run_query` or `tx.run` directly | `tests/conftest.py`, `tests/support/*.py`, about 15 test files | 8 | G01, G02 |
| TEN-G12 | Generated isolation test: probe table, mirror seed, digest and invariant checks, fail-closed cases, leaky-query proof, `UNCONVERTED` ratchet | `tests/integration/graph_store/test_tenant_isolation.py`, `tests/support/tenant_seed.py` | 14 | G01, G02, G11; finished after G04 to G09 |
| TEN-G13 | Indexes and a measurement: `Resource (tenantId, key)` use, typed patterns in the label-less statements, before and after timing at 1, 10, 50 tenants | `migrations.py`, `resource_store.py` | 4 | G04 |
| TEN-G14 | Concept recommendation implemented (or the seeded-catalogue alternative: seed, refuse unknown codes, label allowlist, split `Q-RES-MERGE-RELS`) | `resource_store.py`, `person_repository.py`, `communication_repository.py`, `audit_log.py` | 0 (in G04) or +8 if shared | owner ruling |
| TEN-G15 | Operational invariant check: the section 3.3 queries as a health check and a CI gate | `graph_store/health.py`, CI | 2 | G03 |
| | **Subtotal DEC-130 and DEC-131** | | **92** | |

Suggested order: G01, then G02, G03, G11 in parallel; G12 skeleton (all ids in `UNCONVERTED`); G04; then G05, G06, G07, G08, G09, G10 in parallel (different files); G13, G14, G15; G12 completion. Everything on `main` that touches the graph after G01 lands is written tenant-aware (DEC-130 item 10); U02, U03, I04 finish on the current model and are swept in G05 and G08.

---

## 10. DEC-132: NETWORK, GRANTS AND PROJECTIONS

Read: DEC-132 on `main` (commit `2cf069e`). Tenant is the legal entity; a Network groups member tenants; sharing happens only through `Grant` records and read-only projections written into a separate network scope; each projected node records `sourceTenantId`; a unit of work binds exactly one scope; no Cypher spans scopes.

### 10.1 (a) New node types and exact constraints

Registry nodes (global: no `tenantId`, reached only by `scope="global"` statements; the property names `memberTenantId` and `grantorTenantId` are used on purpose so no registry node looks like a stamped node):

| Label | Properties | Constraint or index |
|---|---|---|
| `Tenant` (0031) | `id`, `name`, `status`, `createdAt` | `tenant_id`: `Tenant.id` unique |
| `Network` | `id`, `name`, `ownerTenantId`, `status`, `agreementRef`, `agreementVersion` (the reference and version only, never the content, DEC-132 item 2), `scopeId` (the id the network scope binds) | `network_id`: `Network.id` unique; `network_scope`: `Network.scopeId` unique |
| `NetworkMembership` | `id`, `networkId`, `memberTenantId`, `status` (`active`/`left`), `joinedAt`, `leftAt` | `network_membership`: `(networkId, memberTenantId)` unique (one row per member; a rejoin reopens it and keeps history in the audit entries); index `(memberTenantId)` |
| `Grant` | `id`, `networkId`, `grantorTenantId`, `scope` (`capacity`/`directory`/`criteria`), `purpose` (`network capacity view`), `effectiveFrom`, `effectiveTo`, `approvedByGrantor`, `approvedByOwner` (administrator ids as text), `version`, `status` | `grant_id`: `Grant.id` unique; `grant_version`: `(networkId, grantorTenantId, scope, version)` unique (a change is a new version, never an edit); index `(grantorTenantId, scope)` |

Network-scope nodes (stamped with the network scope id in `tenantId`, so DEC-130 treats the network like a tenant; each also carries `sourceTenantId`, `sourceKey`, `projectedAt`, `endedAt`, `endReason`, and the grant id and version it was written under):

| Label | Holds | Constraint |
|---|---|---|
| `ProjectionSource` | per member: `status` (`active`/`ended`), `endedAt`, `endReason`, `grantId`; also the lock anchor for the projector and for ending a source | `projection_source`: `(tenantId, sourceTenantId)` unique |
| `ProjectedService` | the directory projection of one service | `projected_service`: `(tenantId, sourceTenantId, sourceId)` unique |
| `ProjectedOpeningHour` | one opening window (child node, since DEC-001 forbids a list of maps) | `projected_opening_hour`: `(tenantId, sourceTenantId, sourceId, position)` unique |
| `ProjectedLocation` | location and district coverage | `(tenantId, sourceTenantId, sourceId)` unique |
| `ProjectedCapacity` | one capacity report as of a time (append-only, keyed by the source report id) | `projected_capacity`: `(tenantId, sourceTenantId, sourceReportId)` unique; index `(tenantId, sourceTenantId, sourceServiceId, effectiveDateTime)` |
| `ProjectedCriteria` | one criteria version (immutable) | `projected_criteria`: `(tenantId, sourceTenantId, sourceCriteriaId)` unique |
| `ProjectionCursor` | the projector's watermark per source and kind | `(tenantId, sourceTenantId, kind)` unique |

The network scope also holds its own `AuditHead`, `AuditEvent`, `ChainLink`, `AuditRef`, `Snapshot`, `OutboxMessage`, `IdempotencyRecord`, `IdempotencyValue` and `Processed`, which use the composite constraints of section 3 unchanged (they are scope-stamped).

All projected ids and keys are qualified by the source: `key = <sourceTenantId>|<sourceKey>`, and network `AuditRef.id` is `<sourceTenantId>/<id>`. Tenants' ids repeat, so an unqualified id in the network scope would merge two members' services.

Migrations (continue after 0035): 0036 registry constraints (`tenant_id` is in 0031; `network_id`, `network_scope`, `network_membership`, `grant_id`, `grant_version` and the two indexes), 0037 projection constraints and the capacity index, 0038 `ProjectionSource` and `ProjectionCursor`. Everything is `IF NOT EXISTS`.

### 10.2 (b) How `run_query` binds a tenant scope versus a network scope, and the `$tenant` check

One bound value, one parameter. `ScopedTx` holds a `ScopeId` whose kind is `tenant` or `network`; `run_query` passes its value as `$tenant` for both. Every existing statement and the DEC-130 rule "mentions `$tenant` and stamps every node" therefore apply to the network scope unchanged: a network statement stamps `tenantId: $tenant` and `$tenant` is the network scope id. What changes is a second, declared dimension: `NamedQuery(scopes=frozenset({"tenant"}))` by default; network statements declare `{"network"}`; statements that are valid in both (audit chain, outbox, idempotency, processed: scope-stamped and label-generic) declare both.

Checks added to registration (7.2 rules 6 and 4) and to `run_query`:
- Label partition. Tenant labels: the 48-label list minus the registry and network labels. Network labels: the `Projected*` family, `ProjectionSource`, `ProjectionCursor`, plus the scope-generic platform labels. A `{"tenant"}` statement may not name a network label, and a `{"network"}` statement may not name a tenant data label (`HealthcareService`, `Observation`, `Task`, `Practitioner`, `PractitionerRole`, `Basic`, `Patient`, `ServiceRequest`, `Communication`, `LinkToken`, `ProtectedContact`, `Credential`, `Device`, `ReportFlag`, `ScheduledWork`, `RegistrationDraftField`, `List`). This makes a tenant statement incapable of writing a projection and a network statement incapable of reading private data even if a scope is mis-bound.
- `run_query` refuses a statement whose `scopes` do not include the bound kind (fixed message), so the same statement text cannot be run in the wrong scope.
- `sourceTenantId` is a data parameter, never a predicate on a tenant-label pattern: only `{"network"}` statements may reference `$sourceTenant`, `run_query` accepts the `sourceTenant` parameter only for them, and the value must come from a verified grant (10.3). The caller still cannot pass `tenant`.
- A network unit of work opened by a read-only use case is flagged read-only: `run_query` refuses `write` statements and `commit()` is a no-op rollback.
- The registry (`Tenant`, `Network`, `NetworkMembership`, `Grant`) is reached only by `scope="global"` statements through `run_global_query`, each pinned in `GLOBAL_QUERY_IDS`, each returning registry rows only.

The generated test (7.3) becomes a three-scope test: tenants A and B and network N. Each statement runs in each scope kind it declares; the digest of the other scopes must not change; the invariants add: every node carrying `sourceTenantId` has a `tenantId` that is a network scope id and a `sourceTenantId` that is a tenant id; no relationship joins two scopes; deleting a tenant's nodes by `tenantId` leaves the network untouched (the network rows carry the member only in `sourceTenantId`).

### 10.3 (c) The projector worker: read from the tenant, then write to the network, in two units of work

Trigger: an outbox message emitted by the tenant's own write path (capacity reported or confirmed, service saved, criteria version made current), consumed by `IdempotentConsumer` (I04 branch). The runner binds the tenant from the validated message property before anything else. A periodic sweep (per tenant, per kind, from `ProjectionCursor`) covers a lost message.
0. Registry read, no scope: `run_global_query("Q-GRANT-ACTIVE-FOR", grantorTenantId=<bound tenant>, scope=<kind>)` returns `(networkId, networkScopeId, grantId, grantVersion)` rows for active, in-effect grants whose network membership is active. None means acknowledge and stop. The tenant id is the bound scope, not a message field.
1. Unit of work 1, bound to the tenant scope, read-only. Use the existing repositories (`services.get`, `capacity.latest`, `criteria.current_for_service`, `flags` for the suspended flag) and the pure domain functions (`compute_status`, freshness) to build immutable projection value objects. The value objects are plain frozen dataclasses with exactly the allowlisted fields (10.4); no node, transaction or property bag leaves the unit. It closes (rolls back).
2. Unit of work 2, bound to the network scope, read-write. First `processed.mark_if_new(message.id, consumer)` (a network-scope marker), then in one statement per label: take the `ProjectionSource {tenantId, sourceTenantId}` lock (`SET src.id = src.id`) and require `src.status = 'active'` inside the upsert statement itself (the statement matches the source and writes nothing if it has ended, so a projection that races a leave is a no-op), then upsert the nodes by their composite key, set `sourceTenantId` from the verified grant, `projectedAt`, `grantId`, `grantVersion`, then `audit.append` (network chain, 10.6), then commit.
3. Ordering and replay. Capacity is append-only keyed by the source report id, so a redelivered or out-of-order message writes the same row. Directory and criteria upserts carry `sourceVersion` (the source `meta.versionId`) and update only when the stored version is lower. The marker makes the whole message idempotent; a crash between 1 and 2 re-reads and re-projects with the same result.
4. A grant that ends between 0 and 2 may let one projection through; DEC-132 item 3 says an ended grant stops future sharing only, so this is acceptable. The `ProjectionSource` row closes it fully when the end-of-membership handler runs.
5. The worker holds both capabilities but never two scopes at once: the nesting refusal (7.1 item 3) enforces it. It is a privileged worker role like any other; it is not the cross-tenant operator of DEC-132 item 8.

The read side: a use case checks the actor's membership and the grant through a global registry read (`Q-MEMBERSHIP-ACTIVE`, keyed by the actor's verified tenant, never request input), then opens a read-only unit of work bound to the network scope and reads `Projected*`. The tenant's own board is a separate unit of work; the two results are combined in the use case. The DEC-132 item 5 wall-screen choice does not change the graph layer.

### 10.4 (d) Allowlist of fields that may enter a projection, mapped to the real node properties

Allowlist constants live in one module (proposed `application/projection.py`) as the frozen dataclasses' fields, so the dataclass is the allowlist. Stored property names below are from `mapper.py`, `service_repository.py`, `capacity_repository.py`, `criteria_repository.py`.

Capacity (`ProjectedCapacity`, source `Observation` plus the service profile):

| Projected field | Source |
|---|---|
| `sourceReportId` | `Observation.id` |
| `sourceServiceId` | the `FOCUS` target `HealthcareService.id` |
| `measureCode` | `Observation.measureCode` (R11 copy of `code`) |
| `value`, `unit` | `Observation.valueQuantity_value`, `valueQuantity_unit` |
| `effectiveDateTime` (as-of) | `Observation.effectiveDateTime` |
| `status`, `effectiveAvailable` | computed by `compute_status` (D07) from the profile, the latest report and flags; not stored on any node |
| `notUpdated` | computed from freshness (D05) and the active `suspended` service flag (`ServiceFlag.code`, `status`); the flag's reason, actor and time are never read |
| `establishedCapacity`, `unitLabel` | `HealthcareService.ext_establishedCapacity`, `ext_unitLabel` |

Not copied: the `PERFORMER` and `DERIVED_FROM` relationships (role and report ids), `Observation.ext_reportType`, `lastUpdated`, `versionId`, `iri`, `key`, `ReportFlag.*` (free-text `reason`), `ext_usualRangeMin/Max`, `ext_limitedLevelPercent`, `ext_reportCadence`, `ext_canExceedEstablished`, `ext_channel`, `ext_measure` (use the report's `measureCode`).

Directory (`ProjectedService`, `ProjectedOpeningHour`, `ProjectedLocation`):

| Projected field | Source |
|---|---|
| `sourceId`, `name`, `active` | `HealthcareService.id`, `name`, `active` |
| `categoryCode` | the `CATEGORY` Concept's `code` |
| opening hours (`ProjectedOpeningHour`: `days`, `allDay`, `start`, `end`) | `HealthcareService_AvailableTime` children: the day codes, `allDay`, `availableStartTime`, `availableEndTime` |
| location: `name`, `postalDistrict`, `city`, `latitude`, `longitude` | the service's `Location` node (`Location.name`, `Address` child, `positionLatitude`, `positionLongitude`). **No repository writes a Location or links `HealthcareService.location` today** (only the mapper and store tests do), so this part of the directory is unbuilt on the source side. Take the outward code (district) from the postcode, not the full postcode or address line; owner to confirm whether the street address is shared |
| service-level contact: `system`, `value`, `use` | a `ContactPoint` child (`HAS_TELECOM`) of the service only. Also not written by any repository today. `ProtectedContact` nodes (role phones and emails) are never read by the projector; the test asserts it |
| `source` | constant `manual` today (a per-tenant directory-source setting later, `dos` when the Directory of Services is integrated) |

Not copied: `HealthcareService.comment` (free text), `ext_smsShortName`, `ext_uprn`, `ext_geocodeSource`, `ext_geocodedAt`, `iri`, `meta`, the scope-list `ENTRY` (`flag`, `date`, `reason`), registrations.

Criteria (`ProjectedCriteria`, source the current `ServiceCriteria` `Basic`, only when `status = 'current'`):

| Projected field | Source |
|---|---|
| `sourceCriteriaId`, `sourceServiceId`, `version` | `Basic.id`, the `SUBJECT` target, `Basic.version` |
| `ageMin`, `ageMax` | `Basic.ageMin`, `ageMax` |
| `postcodeDistricts` (list of text) | `Basic.postcodeDistricts` |
| `acceptsNeedCodes`, `excludesNeedCodes` (lists of text) | the codes of the `ACCEPTS_NEED` and `EXCLUDES_NEED` Concepts, copied as text (no relationship into the network scope) |
| `reviewBy` | `Basic.reviewBy` (a date) |

Not copied: `changeReason` (free text), `author` (role id), `supersedes`, `lastUpdated`.

Never projected (DEC-132 item 4): `Practitioner*` names, `phoneHash`, `emailDomain`, `ProtectedContact`, `Device`, `Credential`, `LinkToken`, `Communication`, `Task` (bookings, registrations), `ServiceRequest`, `Patient`, `AuditEvent`, `Provenance`.

Enforcement, in three layers: (1) the frozen dataclasses (a field not in them cannot be written, and `to_props()` is the only source of the `$props` of a network write); (2) a unit test that compares the dataclass fields to a constant allowlist and to the D17 privacy guard (`domain/messages`), failing on any addition; (3) the poison test: seed a tenant with distinctive strings in every excluded property (a phone number in `comment`, a name in `ReportFlag.reason`, a role id in `performer`, a postcode in `Patient`), run the projector, then scan every property value of every node in the network scope and fail if any poison string appears.

### 10.5 (e) The audit chain for the network scope

One chain per scope (DEC-055 and DEC-130 item 7), so the network has its own `AuditHead {tenantId: <networkScopeId>, id: 'audit'}`, its own `ChainLink.seq`, its own genesis hash, and provisioning that creates the head when the network is created (`provision_scope`, TEN-G21). Appends run in network-scope units of work only. `Neo4jAuditLog` itself needs no change beyond TEN-G09, since the scope is bound by the unit of work.

Entries written in the network chain: `ProjectionWritten` (source tenant, kind, grant id and version, the source ids written, counts; ids only, never values), `ProjectionEnded` (source tenant, reason, date), `NetworkViewRead` (optional, the viewer's role and tenant), and `GrantRecorded` / `MembershipChanged` (owner-side governance). `AuditEntry` has no tenant field today (`application/ports/outbound/audit.py`); add an optional `source_tenant` and `viewer_tenant` to the snapshot, or put them in the snapshot dictionary, so the chain records which member an entry concerns. `AuditRef` ids in the network chain are source-qualified (10.1).

Grant and membership decisions need two audit trails, one in the grantor's tenant chain (their administrator approved) and one in the network chain (the owner approved). They cannot be one transaction because a unit of work binds one scope. Proposal: a registry unit of work (global statements) writes the `Grant` or `NetworkMembership` row last, as `status='active'`, after both audit entries exist; the two entries are written by two scoped units of work driven by an outbox message, so a crash leaves an unapproved grant that no projector will use (the projector reads only active grants). Owner confirmation needed (question e in section 8).

Verification: `verify_chain` runs per scope. A scheduled job verifies each tenant chain and the network chain; the audit tables of members are never copied into the network.

### 10.6 (f) History stays: leave date on projections

- Registry: leaving sets `NetworkMembership.status = 'left'` and `leftAt`; the member's grants get `effectiveTo` and `status = 'ended'`. Nothing is deleted.
- Network scope: the handler for a membership end or a grant end runs in a network-scope unit of work and, per projection label, one statement `MATCH (p:Projected... {tenantId:$tenant, sourceTenantId:$sourceTenant}) WHERE p.endedAt IS NULL SET p.endedAt = $at, p.endReason = $reason` (reason `left` or `grant-ended`), and sets the same on the `ProjectionSource` row, which flips its `status` to `ended`. No projection is removed.
- New data: every upsert statement requires an active `ProjectionSource` for the source (10.3 step 2), so nothing new is projected after the end, even by a racing message.
- Reads: the live network view filters `endedAt IS NULL`; the history view returns everything with the leave date. Whether an ended grant (member still in the network) hides its stale projections from the live view is not stated in DEC-132 item 3; the safe default is to treat a grant end like a leave for that scope only (the `ProjectionSource` is per member, so the grant scope needs `ProjectionSource` per `(sourceTenantId, kind)`; I propose that key, adjusting the constraint above). Owner question.
- A leaving tenant's own data deletion follows its own retention and never touches the network scope: a tenant delete is `MATCH (n {tenantId:$tenant})`, and projection rows carry the member only as `sourceTenantId`. The retention of already-projected copies is an information-governance decision (DEC-132 item 9, human-only), not a graph one.

### 10.7 Tasks for DEC-132

| Id | Title | Files | Hours | Depends on |
|---|---|---|---|---|
| TEN-G16 | Scope kinds: `ScopeId` kinds, `NamedQuery.scopes`, label partition lint, kind check in `run_query`, read-only unit of work, nested-unit refusal | `application/tenancy.py`, `graph_store/queries.py`, `driver.py`, `unit_of_work.py` | 5 | G01, G02 |
| TEN-G17 | Registry: `Network`, `NetworkMembership`, `Grant` nodes and constraints (0036), global statements (`Q-GRANT-ACTIVE-FOR`, `Q-MEMBERSHIP-ACTIVE`, membership and grant writes), registry repository, pinned `GLOBAL_QUERY_IDS` | `graph_store/network_registry.py` (new), `migrations.py` | 6 | G03, G10, G16 |
| TEN-G18 | Network-scope projection repository: `Projected*`, `ProjectionSource`, `ProjectionCursor`, constraints (0037, 0038), upsert, read and end statements, each with a probe | `graph_store/projection_repository.py` (new), `migrations.py` | 8 | G16, G17 |
| TEN-G19 | Projection value objects and allowlist, `to_props()`, D17 guard extension, unit test against the allowlist constant, the poison test | `application/projection.py` (new), `domain/messages/` guard, tests | 5 | G05, G06 |
| TEN-G20 | Projector: two units of work, grant check, ordering and replay rules, `IdempotentConsumer` handler, sweep from cursors | `application/use_cases/project_network.py` (new), `adapters/inbound/workers/` | 7 | G18, G19, G08, I04 |
| TEN-G21 | Network scope provisioning and audit: head and genesis, `provision_scope`, `ProjectionWritten`/`ProjectionEnded` entries, governance saga for grant and membership (registry write last, two scoped audit entries) | `graph_store/tenant_registry.py`, `audit_neo4j/audit_log.py`, `application/audit.py` | 5 | G09, G10, G17 |
| TEN-G22 | Leave and grant-end semantics: end statements, source marker, live and history reads, race test (late projection after leave writes nothing) | `projection_repository.py`, `application/use_cases/` | 4 | G18, G20 |
| TEN-G23 | Three-scope generated test: extend TEN-G12 with a network scope, per-kind runs, the new invariants, and the tenant-delete-leaves-network test | `tests/integration/graph_store/test_tenant_isolation.py` | 5 | G12, G18 |
| | **Subtotal DEC-132** | | **45** | |

Total with section 9: 137 hours in 23 tasks (G14 is folded into G04).
