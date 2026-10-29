# Shared contracts: names, paths and signatures

Every prompt must use these names, paths and signatures exactly, so tasks written separately fit together. A prompt may add private helpers, but must not rename anything here. If a task needs a name that is not here, the task that creates it defines it in its prompt, and later prompts must reference it by the creating task's id ("created by D07").

## Repository layout

```
backend/                      Python 3.14, uv, package `diucs` (src layout)
  src/diucs/domain/           pure: stdlib + fhir.resources types only
    codes.py  errors.py  events.py
    model/  rules/  messages/
  src/diucs/application/
    ports/inbound/use_cases.py      one Protocol per driving port
    ports/outbound/*.py             Protocols for driven ports
    use_cases/<snake_name>.py       one use case class per file (some files hold 2-3 closely related ones, as the task list says)
    work.py                         WorkKind enum and ScheduledWork dataclass (created by P08)
  src/diucs/adapters/inbound/{fhir_rest,sms_webhook,link_pages,scheduler,workers}/
  src/diucs/adapters/outbound/{graph_store,audit_neo4j,cache_redis,bus_servicebus,sms_twilio,sms_govuk_notify,email_smtp,push_webpush,geocoder_os_places,postcodes_local,travel_time,terminology,fhir_validator,pin_store,clock_system,ids_uuid,telemetry}/
  src/diucs/adapters/testing/       fakes for external providers only (see "Testing and persistence")
  src/diucs/bootstrap/{settings.py,container.py}
  tests/unit/...      mirrors src paths (tests/unit/domain/rules/test_status.py)
  tests/contract/...  cache and event bus suites, run against the fake and the real adapter
  tests/integration/... marked @pytest.mark.integration, need docker compose
  tests/architecture/test_import_rules.py
frontend/                     Next.js 16 App Router, React 19.2, TypeScript strict, pnpm
  app/(wall)/screen  (reporter)/app + (reporter)/setup  (advisor)/advisor  (clinical)/clinical
  app/(lead)/lead  (exec)/exec  (owner)/criteria  (console)/console  (planning)/planning
      (route groups add no URL segment, so each group keeps its pages under its own folder; app/sign-in is shared)
  app/l/[token]/   app/register/   app/api/bff/
  components/{ui,board,advisor,lead,reporter,exec,forms}/
  lib/{fhir,auth,bff,board,push,a11y,telemetry}/
  test/msw/   e2e/
infra/docker-compose.yml      neo4j:5, redis:7, Azure Service Bus emulator
docs/spec/                    source specs; docs/spec/domain-rules.md is the rule book
```

Commands: `cd backend && uv run pytest`, `uv run pytest -m integration`, `uv run ruff check . && uv run ruff format --check .`, `uv run mypy src`, `uv run lint-imports`. Frontend: `cd frontend && pnpm test`, `pnpm lint`, `pnpm typecheck`, `pnpm e2e`.

## Testing and persistence (supersedes anything below that says otherwise)

Neo4j in Docker is the only implementation of everything Neo4j stores. There are no in-memory repositories, unit of work, audit log, outbox, idempotency store, link-token store, scheduled-work store, communication store, contact store or credential store. Tests that touch them run against the real Neo4j from `infra/docker-compose.yml`, so persistence and hydration are proven by every test.

**What still has a fake** (in `diucs/adapters/testing/`, because it is outside our control or not a store of record): `FixedClock`, `SequentialIds`, `RecordingSmsSender`, `RecordingEmailSender`, `RecordingPushSender`, `ManualEventBus` (Service Bus), `InMemoryCache` (Redis), `InMemoryCodeStore` (short-lived text codes, Redis in production), `FixedSecretStore`, `FixedGeocoder`, `FixedPostcodeLocator`, `FixedTravelTime`, `FixedTerminology`, `PassThroughValidator`. The cache and event bus fakes are kept honest by contract suites that also run against Redis and the Service Bus emulator (P12, I01, I02).

**Neo4j for tests.** Docker Compose service `neo4j` (image `neo4j:5`, Community edition), Bolt at `bolt://localhost:7687`, user `neo4j`, password `diucs-test-password`, overridable with `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`. Community edition has one database, so tests run serially (no pytest-xdist).

**Test layout.**
- `backend/tests/unit/`: pure tests (domain rules, templates, the mapper's pure functions). No Docker. `uv run pytest tests/unit`.
- `backend/tests/integration/`: everything that touches Neo4j, Redis or Service Bus, including every use-case test and every repository test. The conftest marks them `integration` automatically.
- `uv run pytest` runs both and needs `docker compose -f infra/docker-compose.yml up -d` (from the repo root). If Neo4j is unreachable the session fails at once with: "Neo4j is not running. Start it with: docker compose -f infra/docker-compose.yml up -d neo4j".

**Harness (F10), in `backend/tests/support/` and `backend/tests/conftest.py`.**
- `neo4j_driver` (session-scoped async fixture): an `AsyncDriver` connected with the settings above; applies the schema once with `apply_migrations(driver)` from G01.
- `clean_graph` (autouse for `tests/integration`): before each test deletes every node and relationship in batches (`MATCH (n) WITH n LIMIT 10000 DETACH DELETE n`, repeated), keeping constraints and indexes.
- `write_tx(driver, fn)` and `read_tx(driver, fn)`: run `fn(tx)` in a managed write or read transaction in a fresh session and return its result.
- `assert_round_trip(driver, save, load, expected)`: runs `save(tx)` in one committed write transaction, then `load(tx)` in a new read session, and asserts the loaded value equals `expected` (frozen dataclasses compare by value; datetimes must come back timezone-aware UTC).
- `count_nodes(driver, label) -> int` and `node_props(driver, label, **match) -> dict`: for asserting on what is really stored.
- `uow_factory` (fixture, added by P06 in `tests/support/uow.py`): returns a `UnitOfWorkFactory` that opens `Neo4jUnitOfWork` sessions on `neo4j_driver`.

**Repository adapters.** Live in `adapters/outbound/graph_store/` (audit and outbox in `adapters/outbound/audit_neo4j/`), are named `Neo4j<Port>` (for example `Neo4jServiceRepository`, `Neo4jAuditLog`, `Neo4jOutbox`), and are constructed with the open `AsyncManagedTransaction` the unit of work holds and the G05 `ResourceStore` for FHIR resources: `Neo4jServiceRepository(tx, store)` (DEC-054). FHIR-shaped aggregates are saved and loaded through the resource store from G05 (no `json` property: the decomposed properties and relationships are the only stored copy, DEC-001 and DEC-049; `from_graph(to_graph(r)) == r` holds whenever `to_graph` accepts `r`, and a resource it cannot hold exactly is refused, not stored); platform nodes (`OutboxMessage`, `ScheduledWork`, `LinkToken`, `Processed`, `Credential`, `IdempotencyRecord`, ...) are written with named queries registered in G01's query registry. Every repository task's tests include, for each aggregate: a save-then-load round trip with `assert_round_trip`; a check of the stored node labels and key properties; for FHIR-backed aggregates, that `from_graph(to_graph(r)) == r` holds for each resource `to_graph` accepts (DEC-049); and the "not found" case.

**Use-case tests.** Construct the use case with `uow_factory` plus the external fakes above. Assert outcomes by reading back through a fresh unit of work or the harness helpers, never by peeking into Python objects. Check rollback: when the use case raises, nothing it wrote is in the graph.

**Who builds what (the old graph tasks are folded into the port tasks).** G06 → P01 (services, capacity); G10 → P03 (people); G12 → P02 (bookings, cases); G07 → P05 (audit); G08 → P06 (outbox, unit of work) and P15 (idempotency store, processed markers); G09 → P07 (communications), P08 (scheduled work), P10 (link tokens). New: P13 registrations and scope list, P14 flags, P16 contact store and PIN credentials, P17 alert subscriptions and alerts, P18 clinical requests, P19 push subscriptions, P20 service moves and the protected text store. `IdempotencyStore` is created by P15 (not U01) and `ProcessedMessages` by P15 (not G08). G01 (driver, named queries, migrations) is in Stage 0; G02–G05 (mapper and resource store) are in Stage 1. G11 keeps the criteria hard-filter and history queries.

## Python conventions

- Value objects: `@dataclass(frozen=True, slots=True)`. Codes: `enum.StrEnum` whose values are the FHIR code strings.
- Datetimes are timezone-aware UTC everywhere. Domain functions take `now: datetime` as an argument; they never read the clock.
- Errors: `diucs.domain.errors.DomainError` base; subclasses `InvalidTransition`, `ValidationFailed(field, message)`, `NotFound`, `Conflict`, `NotAllowed`.
- Ports are `typing.Protocol` classes. Neo4j-backed ports have no fake; the external-provider fakes listed under "Testing and persistence" live in `diucs.adapters.testing`.
- Use cases: class named after the use case, constructor-injected ports, one public method `async def execute(self, command: <Name>Command) -> <Name>Result`. Commands carry `idempotency_key: str` and `actor: Actor`.
- `Actor` (in `application/actor.py`, created by P05): `Actor(role: Role, practitioner_id: str | None, device_id: str | None, channel: str, service_ids: frozenset[str])`.
- pytest with `asyncio_mode = "auto"`.

## Domain (created in S1)

`diucs/domain/codes.py` (F07): `BASE_URL = "https://diucs.example/"`; `code_system_url(name: str) -> str` returns `f"{BASE_URL}CodeSystem/{name}"`; `Coding(system: str, code: str, display: str)`.
StrEnums: `Status` (accepting, limited, not-accepting, over-capacity, not-updated, out-of-hours); `Measure` (free-slots, free-beds, referrals-acceptable, occupied-patients, packages-free); `ReportSource` (text, link, app, email, advisor-phoned, feed); `ReportType` (number, confirmed); `ServiceCategory` (urgent-community-response, same-day-emergency-care, inpatient-beds, hospital-at-home-or-virtual-ward, reablement, urgent-treatment, mental-health-crisis, other); `NeedCategory` (fall-no-injury, frailty, wound-care, iv-therapy, palliative, dementia, suspected-fracture, head-injury-anticoagulants, infection-isolation); `Urgency` (within-2-hrs, today, planned); `AgeBand` ("0-15", "16-64", "65-79", "80+"); `AcuityMethod` (pathways-dx, ambulance-category, manchester, news2, cfs); `BookingStatus` (requested, confirmed, declined, expired, cancelled-before, cancelled-after, withdrawn, not-reached, completed); `DeclineReason` (full, outside-criteria, staffing-or-transport, other); `WithdrawReason` (now-full, staffing, cannot-reach-patient, other); `NotReachedReason` (not-at-address, no-answer, gone-to-hospital, other); `CancelReason` (caller-declined, no-longer-needed, other-route-found, entered-in-error); `RegistrationStatus` (invited, draft, submitted, in-review, needs-changes, approved, live, not-approved, paused, reverify); `CriteriaStatus` (draft, pending-approval, current, superseded, retired); `Channel` (text, email, push); `AlertKind` (service-closed, over-capacity, not-updated, system-pressure); `Cadence` (every-2-hrs, twice-a-day, once-a-day); `Role` (reporter, advisor, clinical, lead, owner, exec, wall, anonymous-link, support, audit); `ScopeFlag` (in-pilot, later, out-of-scope); `ReportFlagReason` (out-of-range-twice, many-changes, differs-from-phoned); `Outcome` (accepted-and-booked, declined, redirected, caller-cancelled, no-service-fits, out-of-area); `BestFitNotUsedReason` (full, declined, data-too-old, caller-preference, clinical-override); `ReferrerType` (ambulance-crew, care-home, gp, nhs-111, other).

`model/service.py` (D01): `AvailableTime(days: frozenset[int] /*0=Mon*/, all_day: bool, start: time | None, end: time | None)`; `ServiceProfile(id, name, category: ServiceCategory, measure: Measure, unit_label: str, established_capacity: int, can_exceed_established: bool, usual_range: tuple[int, int], cadence: Cadence, available_times: tuple[AvailableTime, ...], channel: Channel, limited_level_percent: int = 80, active: bool = True, suspended: bool = False, comment: str = "")`.

`model/capacity.py` (D02): `CapacityReport(id, service_id, value: int, measure: Measure, effective_at: datetime, source: ReportSource, report_type: ReportType, performer_role_id: str | None = None, derived_from: str | None = None)`; `latest_report(reports) -> CapacityReport | None`. A "we are closed" report is `value=0`.

`rules/london_time.py` (F06): `LONDON = ZoneInfo("Europe/London")`; `to_london(dt) -> datetime`; `london_to_utc(d: date, t: time) -> datetime` (gap: shift forward; fold: first occurrence); `format_hhmm(dt) -> str` ("14:19" London).
`rules/opening_hours.py` (D03): `is_in_hours(times: Sequence[AvailableTime], now: datetime) -> bool`; `next_opening(times, now) -> datetime | None`.
`rules/schedule.py` (D04): constants `REPLY_WINDOW = timedelta(minutes=30)`, `REMINDER_AFTER = 30 min`, `PHONE_TASK_AFTER = 60 min`, `ESCALATE_AFTER = 90 min`, `TWICE_A_DAY_SECOND = time(14, 0)`; `due_times_on(profile, london_day: date) -> list[datetime]`; `next_due(profile, now) -> datetime | None`; `current_due(profile, now) -> datetime | None` (latest due time <= now that day); `reply_by(due) -> datetime`; `LadderStep` StrEnum (prompt, reminder, phone-task, escalate); `ladder_times(due) -> dict[LadderStep, datetime]`.
`rules/freshness.py` (D05): `STALE_WARNING_AFTER = timedelta(hours=2)`; `Freshness(overdue: bool, age: timedelta | None, stale_warning: bool, was_due: datetime | None)`; `assess_freshness(profile, last_report_at: datetime | None, now) -> Freshness`; `data_age_text(age: timedelta) -> str`.
`rules/availability.py` (D06): `effective_available(report: CapacityReport, confirmed_at: Sequence[datetime]) -> int`; `pending_count(statuses: Iterable[BookingStatus]) -> int`.
`rules/status.py` (D07): `ServiceState(status: Status, effective_available: int | None, used: int | None, over_by: int | None, freshness: Freshness)`; `compute_status(profile, latest: CapacityReport | None, confirmed_at: Sequence[datetime], now) -> ServiceState`.
`rules/pressure.py` (D08): `Pressure` StrEnum (normal, watch, high); `system_pressure(statuses: Iterable[Status]) -> Pressure`; `all_limited_or_worse(statuses) -> bool`.
`rules/reply_parser.py` (D09, D10): reply types `Confirm(letter: str | None = None)`, `Number(value: int, letter: str | None = None)`, `BookingConfirm(reference: str | None)`, `BookingDecline(reference: str | None)`, `Unrecognised(text: str)`; `ParsedReply = Confirm | Number | BookingConfirm | BookingDecline | Unrecognised`; `parse_reply(text: str) -> tuple[ParsedReply, ...]`.
`rules/reply_policy.py` (D11): `CORRECTION_WINDOW = 15 min`, `MAX_CONSECUTIVE_CONFIRMS = 2`; `PromptState(service_id, reply_by: datetime | None, recorded_value: int | None, consecutive_confirms: int, last_accepted_at: datetime | None, last_accepted_value: int | None, pending_out_of_range: int | None, usual_range: tuple[int, int], letter: str | None = None)` (`letter` is this prompt's service letter, None for one service); decisions `RecordNumber(value, is_correction: bool, flag: ReportFlagReason | None)`, `RecordConfirm()`, `RejectLate(new_reply_by: datetime)`, `RejectConfirmLimit()`, `AskRecheck(value: int)`; `decide_capacity_reply(reply: Confirm | Number, state: PromptState, now) -> Decision`. Caller contract (lesson L27, DEC-031): a use case loops over every item of `parse_reply`'s tuple and calls this once per item; a letter mismatch or a bare figure on a lettered prompt raises `ValidationFailed`.
`rules/report_flags.py` (D12): `MANY_CHANGES_WINDOW = 5 min`, `MANY_CHANGES_COUNT = 3`, `PHONED_WINDOW = 60 min`; `flags_for_report(new: CapacityReport, recent: Sequence[CapacityReport], profile) -> list[ReportFlagReason]`.
`rules/booking_state.py` (D13): `transition(current: BookingStatus, target: BookingStatus) -> BookingStatus` (raises `InvalidTransition`); `FhirTaskStatus(status: str, business_status: str, status_reason: str | None)`; `to_fhir(status: BookingStatus) -> FhirTaskStatus`; `from_fhir(business_status: str) -> BookingStatus`.
`rules/booking_rules.py` (D14): `BOOKING_REPLY_WINDOW = 10 min`, `PHONE_PROMPT_AFTER = 5 min`; `booking_reply_by(requested_at)`; `phone_prompt_at(requested_at)`; `can_request(open_statuses_for_service: Iterable[BookingStatus]) -> bool`; `new_reference(rng: random.Random, taken: set[str]) -> str`; `OpenBookingRef(booking_id, reference, service_id)`; `match_reply(open: Sequence[OpenBookingRef], reference: str | None) -> OpenBookingRef | AskWhichReference | NoOpenBooking`.
`messages/catalogue.py` (D15): `MessageId` StrEnum C1..C11, B1..B7, I1..I3, K1..K4 (meanings in docs/spec/domain-rules.md section 9). `messages/templates.py`: `RenderedMessage(message_id, channel: Channel, text: str, subject: str | None = None, html: str | None = None)`; `render(message_id: MessageId, channel: Channel, **fields) -> RenderedMessage`. Field names per id: C1 service, value, unit, as_of, link, reply_by; C2 service, unit, window, reply_by, link (window added by D15, DEC-034 item 8); C3 service, value, unit, recorded_at, next_due; C4 service, value, unit, recorded_at, replaced; C5 cutoff, rejected, service, value, unit, reply_by; C6 service; C7 service, value, low, high; C8 service, reply_by, link; C9 reply_by, items (list of (letter, service, value)); C10 updated (list of (letter, service, value)), waiting (list of (letter, service)); C11 (none); B1/B2 reference, service, age_band, need, urgency, link, reply_by; B3 reference, service, reply_by; B4 reference, service, confirmed_at; B5 reference; B6 reference, cancelled_at; B7 references; I1 service, link; I2 link; I3 service; K1 code; K2 service, review_by; K3 title, body; K4 service. All time fields are already-formatted "HH:MM" strings. `messages/sms_length.py`: `sms_segments(text) -> int` (GSM-7 160/153, UCS-2 70/67).
`messages/privacy_guard.py` (D17): `find_patient_data(text: str) -> list[str]`.
`model/scores.py` (D18): `News2(value)`, `ClinicalFrailty(value)`, `AmbulanceCategory(value)`, `ManchesterTriage(level: str)`, `PathwaysDx(code: str)`; `Score = ...union`. `model/case.py`: `Case(id, reference, referrer_type: ReferrerType, age_band: AgeBand | None, postcode: str | None, needs: tuple[NeedCategory, ...], urgency: Urgency | None, scores: tuple[Score, ...], opened_at, closed_at: datetime | None = None, outcome: Outcome | None = None, best_fit_not_used: BestFitNotUsedReason | None = None, destination_service_id: str | None = None)`; `Case.close(outcome, at, destination_service_id=None, best_fit_not_used=None) -> Case`; `priority_for(urgency) -> str` ("urgent"/"routine").
`rules/postcode.py` (D19): `normalise_postcode(text: str) -> str | None`; `postcode_district(postcode: str) -> str`.
`model/criteria.py` (D20): `ServiceCriteria(id, service_id, version: int, status: CriteriaStatus, age_min: int, age_max: int | None, districts: frozenset[str], accepts: frozenset[NeedCategory], excludes: frozenset[NeedCategory], review_by: date, owner_role_id: str, change_reason: str = "", supersedes_id: str | None = None)`. `rules/criteria_filter.py`: `FilterResult(passes: bool, reasons: tuple[str, ...], warnings: tuple[str, ...])`; `check_hard_criteria(criteria, age_band: AgeBand, district: str, needs: Iterable[NeedCategory]) -> FilterResult`. D20 also exports `AGE_OVERLAP_WARNING` (the age warning text) and returns the fixed reasons `Need not recognised` and `Age not recognised` for unknown codes (DEC-035).
`rules/criteria_workflow.py` (D21): `REVIEW_REMINDER_BEFORE = timedelta(days=14)`; `transition_criteria(current, target) -> CriteriaStatus`; `is_review_overdue(criteria, today: date) -> bool`; `review_reminder_due(criteria, today) -> bool`; `next_review_by(confirmed_on: date, months: int) -> date` (months 3, 6 or 12); `approve(current: ServiceCriteria | None, pending: ServiceCriteria) -> tuple[ServiceCriteria | None, ServiceCriteria]` (returns the old version superseded or None, and the new version current). `today` and `confirmed_on` are calendar dates (London day), never datetimes (DEC-038).
`rules/registration.py` (D22): `transition_registration(current, target) -> RegistrationStatus`; `ApprovalChecks(automatic_ok: bool, callback_confirmed: bool, scope: ScopeFlag | None, criteria_approved: bool)`; `missing_for_approval(checks) -> list[str]`; `INVITATION_VALID_FOR = timedelta(hours=48)`.
`rules/clinical_queue.py` (D23): `TAKE_TIMEOUT = 10 min`; `Presence` StrEnum (available, busy, away); `ClinicalRequest(id, case_id, urgency: str, requested_at, taken_by: str | None, taken_at: datetime | None, advised_at: datetime | None)`; `take(request, clinician_id, now)`, `return_if_idle(request, now)`, `available_count(presences)`, `advice_shown_as_available(available: int | None, queue_known: bool) -> bool` (D23; advice is shown only when both are known and the count is above zero).
`rules/alerts.py` (D24): `Alert(kind: AlertKind, service_id: str | None, raised_at: datetime, critical: bool)`; `alerts_for_change(service_id, before: Status | None, after: Status, in_hours: bool, now) -> list[Alert]`; `alert_for_pressure(before: Pressure, after: Pressure, now) -> Alert | None`; `AlertPreferences(kinds: frozenset[AlertKind], not_updated_hours: int, quiet_hours: tuple[time, time] | None, quiet_critical_only: bool, ack_minutes: int)`; `should_notify(prefs, alert, now) -> bool`; `escalation_at(alert_sent_at, prefs) -> datetime`.
`events.py` (D25): frozen dataclasses with `event_type: ClassVar[str]` and `to_payload() -> dict`: `CapacityReported(service_id, report_id, value, source, at)`, `StatusChanged(service_id, before, after, at)`, `BookingRequested(booking_id, service_id, reference, at)` (reference: 4-digit text, DEC-041 item 6), `BookingResponded(booking_id, service_id, status, at)`, `BookingExpired(booking_id, service_id, at)`, `RegistrationSubmitted(registration_id, at)`, `RegistrationApproved(registration_id, service_id, at)`, `CriteriaApproved(criteria_id, service_id, version, at)`, `AlertRaised(alert_id, kind, service_id, at)`, `AlertAcknowledged(alert_id, by, at)` (by: `Role`, DEC-041 item 6). None carries patient values.
`rules/tokens.py` (D26): `new_link_token(rng: secrets-like) -> str` (128 bits as 23 letters, `LINK_TOKEN_ALPHABET` A-Z a-z, `LINK_TOKEN_LENGTH` 23; DEC-154); `hash_token(token, secret: bytes) -> str` (HMAC-SHA256 hex); `LinkTokenRecord(token_hash, purpose: str, about_id: str, phone_hash: str | None, expires_at, used_at: datetime | None)`; `check_link(record, now) -> LinkCheck` (ok, expired, used); `new_pairing_code(rng) -> str` ("482913"), `format_pairing_code(code) -> "482 913"`; `new_support_code(rng) -> str` ("K7R4-92QX"). Also (D26): `pairing_code_expired(issued_at, now) -> bool`, `PAIRING_CODE_VALID_FOR` (10 minutes), `SUPPORT_CODE_ALPHABET` (31 characters), `LINK_TOKEN_BYTES` (16), `LinkCheck` (StrEnum: `ok`, `expired`, `used`). Pairing codes draw one digit per call with bound 10 (DEC-045).
`rules/identity_policy.py` (D27): `CODE_VALID_FOR = 10 min`, `CODE_MAX_TRIES = 5`, `CODE_RESEND_AFTER = 60 s`, `PIN_MAX_TRIES = 5`, `REVERIFY_EVERY = timedelta(days=30)`; `validate_pin_format(pin) -> None`; `code_attempt(state, entered_ok: bool, now) -> CodeState`; `pin_attempt(state, ok, now) -> PinState`; `needs_reverification(last_verified_at, now, device_known: bool) -> bool`.
`rules/multi_service.py` (D28): `GROUP_WINDOW = 10 min` [ASSUMED] (domain-rules 2.4, owner-pending), `MAX_SERVICES_PER_PHONE = 3`; `GroupedItem(service_id: str, name: str, due: datetime, letter: str | None)`; `PromptGroup(items: tuple[GroupedItem, ...], due: datetime, reply_by: datetime)`; `MAX_LETTERED_ITEMS = 26` (from the D28 prompt, not a rule-book value); `group_due(due: Sequence[tuple[str, str, datetime]]) -> list[PromptGroup]` (service_id, name, due; DEC-048 item 1); `letters_for(names: Sequence[str]) -> dict[str, str]`; `phone_overloaded(count: int) -> bool`.

## Application (created in S2 onward)

`application/work.py` (P08): `WorkKind` StrEnum: prompt-due, reminder, phone-task, escalate-to-lead, booking-phone-prompt, booking-expire, criteria-review-reminder, alert-escalate, clinical-return, reverify; `ScheduledWork(id, kind: WorkKind, due_at, about_id: str, sequence_number: int | None, status: str)`.

Outbound ports (file → Protocols):
- `repositories.py`: `ServiceRepository` (get, list_active, save), `CapacityRepository` (add, latest, latest_for_services, reports_since) [P01]; `BookingRepository` (add, get, get_by_reference, save, open_for_service, open_for_services, confirmed_since) and `CaseRepository` (add, get, get_by_reference, save) [P02]; `PersonRepository` (get_practitioner, find_by_phone_hash, roles_for_practitioner, services_for_phone_hash, reporter_roles_for_service, save_practitioner, save_role) [P03]; `CriteriaRepository` (current_for_service, current_for_services, get, add, save, history), `RegistrationRepository` (add, get, save, list_by_status), `ScopeListRepository` (entries, get_entry, save_entry), `FlagRepository` (add_report_flag, open_report_flags, save_report_flag, service_flags, set_service_flag) [P04].
  P01 additions (DEC-054): `CapacityRepository.last_report_times() -> dict[str, datetime | None]`; `Neo4jServiceRepository(tx, store)` and `Neo4jCapacityRepository(tx, store)` take the G05 `ResourceStore`; `codeable_to_fhir(member)` and `codeable_from_fhir(concept, enum_cls, field)` in `service_repository.py` are the shared CodeableConcept helpers; extensions `measure`, `unitLabel`, `channel` are registered.
- `audit.py` (P05): `AuditEntry(action: str, use_case: str, actor: Actor, entity_ids: tuple[str, ...], snapshot: dict | None, at: datetime)`; `AuditRecord(id, entry, chain_hash, previous_hash)`; `AuditLog` (append, records, verify_chain). No update or delete methods.
- `outbox.py` + `unit_of_work.py` (P06): `OutboxMessage(id, topic: str, event_type: str, payload: dict, created_at, status="pending", attempts=0, session_id: str | None = None)`; `Outbox` (add, pending, mark_published, mark_failed); `UnitOfWork` async context manager with attributes `services, capacity, bookings, cases, people, criteria, registrations, scope, flags, communications, link_tokens, scheduled_work, audit, outbox` and `async commit()` / `async rollback()`; `UnitOfWorkFactory = Callable[[], UnitOfWork]`. Use cases write the change, the audit entry and outbox messages inside one `async with uow_factory() as uow: ...; await uow.commit()`.
- `messaging.py` (P07): `SmsSender.send(to: str, text: str, message_id: str) -> SendReceipt`; `EmailSender.send(to, subject, text, html) -> SendReceipt`; `PushSender.send(subscription: dict, title, body, url) -> SendReceipt`; `SendReceipt(provider_message_id, accepted: bool)`; `Communication(id, message_id: MessageId, channel, recipient_role_id, about_id, payload_text, sent_at, delivery_status, provider_message_id, in_response_to: str | None)`; `CommunicationRepository` (add, get, by_provider_id, set_delivery_status, latest_prompt_for_phone).
- `event_bus.py` (P08): `BusMessage(id, topic, event_type, payload, session_id=None)`; `EventBus.publish(message)`, `EventBus.schedule(queue: str, message, enqueue_at) -> int`, `EventBus.cancel(queue, sequence_number)`; `ScheduledWorkRepository` (add, get, for_about, save). Topic and queue names exactly as `docs/spec/architecture.md`: `inbound.replies`, `inbound.receipts`, `scheduled.work`, `capacity.events`, `booking.events`, `registration.events`, `criteria.events`, `alerts.events`, `messages.outbound`.
- `cache.py` (P09): `Cache` (get, set(key, value, ttl), delete, publish(channel, message), `async` subscribe(channel) -> AsyncIterator (DEC-092: await it; it returns once the server confirms the subscription; DEC-058), acquire_lock(name, ttl) -> Lock | None, release_lock(lock)); `Lock(name, fencing_token: int)`. Channel `board.updates`.
- `tokens.py` + `identity.py` (P10): `LinkTokenRepository` (add, get_by_hash, mark_used); `LinkTokenService(repo, secret_store, clock)` with `issue(purpose, about_id, phone_hash, expires_at) -> str`, `resolve(token) -> LinkTokenRecord | None`, `burn(token)`; `SecretStore.get(name) -> bytes`; `PhoneHasher.hash(number) -> str`; `ContactStore` (protected numbers/emails: put_phone, get_phone, put_email, get_email); `CodeSender.send_code(phone) -> None`, `CodeStore`; `PinStore` (set_pin, verify_pin, attempts, lock); `DeviceRegistry`.
  P10 additions (DEC-060): `HmacPhoneHasher(secrets)` and `normalise_uk_mobile(number) -> str` (eleven digits from 07) in `identity.py`; secret names `link-token` and `phone-hash` (`LINK_TOKEN_SECRET`, `PHONE_HASH_SECRET`); `Neo4jLinkTokenRepository(tx)` (`adapters/outbound/graph_store/link_token_repository.py`, queries `Q-LINK-ADD`, `Q-LINK-GET`, `Q-LINK-MARK-USED`); `FixedSecretStore(secrets: dict[str, bytes])`; migration `0021_link_token_hash` (unique `LinkToken.tokenHash`).
- `geo.py` / `terminology.py` (P11): `Geocoder.find_addresses(postcode) -> list[AddressCandidate]`; `PostcodeLocator.centroid(postcode) -> LatLon | None`; `TravelTime.estimate(origin: LatLon, destination: LatLon) -> TravelRange(low_minutes, high_minutes, source)`; `Terminology.ods_lookup(code) -> OdsRecord | None`, `Terminology.display(system, code) -> str | None`; `FhirValidator.validate(resource: dict, profile: str) -> list[ValidationIssue]`.

Use case files and class names are the task titles in tasks.json (ReportCapacity, ConfirmCapacity, SendPrompts, HandleInboundText, MissedReportLadder, QueryBoard, BoardProjector, OpenCase, FilterOptions, RecordAdvisorPhoned, RecordDecline, RecordOutcome, SetupServiceByLead, ChangeReporterNumber, RequestBooking, RespondToBooking, BookingTimers, CancelBooking, WithdrawBooking, ReportNotReached, PairWallScreen, ...).

`QueryBoard` result: `BoardEntry(service_id, name, category: ServiceCategory, status: Status, effective_available: int | None, over_by: int | None, used: int | None, established: int, pending: int, unit_label: str, comment: str, reported_at: datetime | None, next_due_at: datetime | None, was_due_at: datetime | None)` and `Board(entries: tuple[BoardEntry, ...], pressure: Pressure, all_limited_or_worse: bool, generated_at: datetime)`.

## HTTP surface (backend)

- FHIR base path `/fhir`, media type `application/fhir+json; fhirVersion=4.3`. Errors are OperationOutcome.
- `GET /fhir/HealthcareService`, `GET /fhir/HealthcareService/{id}`, `POST /fhir/Observation`, `GET /fhir/Observation?focus=HealthcareService/{id}&_sort=-date&_count=1`.
- `GET /fhir/HealthcareService/$board` → `Parameters` with one `parameter` named `entry` per service, parts named exactly like the `BoardEntry` fields in camelCase, plus top-level parameters `pressure`, `allLimitedOrWorse`, `generatedAt`.
- `POST /fhir/HealthcareService/{id}/$confirm-capacity`, `$suspend`, `$resume`.
- `POST /fhir/ServiceRequest` (open case), `PATCH`-style update via `PUT /fhir/ServiceRequest/{id}` with If-Match, `POST /fhir/HealthcareService/$filter-options` (Parameters in, Parameters out).
- `POST /fhir/Task` (booking create), `POST /fhir/Task/{id}/$respond`, `POST /fhir/Task/{id}/$cancel`, `$withdraw`, `$not-reached`.
- Non-FHIR: `GET /links/{token}`, `POST /links/{token}` (JSON, CSRF header `X-CSRF-Token`), `POST /links/{token}/renew`; `POST /webhooks/sms/twilio`, `POST /webhooks/sms/twilio/status`; `GET /events` (text/event-stream); `POST /identity/code`, `POST /identity/code/verify`, `POST /identity/pin`, `POST /identity/pin/verify`; `GET /health`.
- Auth: bearer JWT from the BFF with claims `role`, `services` (list of ids), `sub`, `device`. Created by R02.

## Front end

- Browser → `/api/bff/*` route handlers only. Route handlers call the backend through `lib/fhir/client.ts`: `fhirFetch<T>(path: string, init: { method?, body?, token?, idempotencyKey?, ifMatch? }): Promise<{ data: T; etag?: string }>`, throwing `FhirError(status, outcome)`.
- Board types in `lib/board/types.ts`: `BoardEntry` (camelCase of the backend fields) and `Board`; `parseBoardParameters(p: Parameters): Board` (created by W05).
- Session: `lib/auth/session.ts` exposes `getSession(): Promise<Session | null>`, `Session { role, services, sub, device?, backendToken, expiresAt }` (`expiresAt` is an ISO instant); also `sealSession`, `unsealSession`, `sessionFromRequest(request)`, `createSession`, `destroySession`, `readRequestCookie`, `ROLES`, `Role`. CSRF via `lib/auth/csrf.ts` `issueCsrf()`, `checkCsrf(request)`, `clearCsrf()`, `CSRF_COOKIE`, `CSRF_HEADER`. `lib/bff/handler.ts` `withBff(handler, { roles?, csrf? })` (W02, DEC-125).
- Every interactive element carries `data-el="<AREA>-<SCREEN>-<THING>"`, upper-case with hyphens, for example `ADV-OPT-REQUEST-BTN`, `REP-LINK-CONFIRM-BTN`, `WALL-TILE`.
- Status display everywhere uses `components/ui/StatusBadge.tsx` (F09): `<StatusBadge status="limited" />` renders shape + word + colour.
- Styling: CSS Modules plus tokens from `app/tokens.css`: `--c-primary #0B5C8C`, `--c-primary-dark #0B3F61`, `--c-limited #A34700`, `--c-closed #3A4750`, `--c-surge #6B2C91`, `--c-unknown #6B7B83`, `--c-ink #14232B`, `--c-ink-2 #26343B`, `--c-muted #44555D`, `--c-line #DDE3E6`, `--c-bg #F4F6F5`, `--c-tint #E3F1F8`, `--c-amber-tint #FFF1DC`; font Atkinson Hyperlegible; buttons min height 52px, chips 48px, radius 14px.
- Tests: Vitest + Testing Library + `vitest-axe`; MSW handlers in `test/msw/handlers/<area>.ts`; Playwright specs in `e2e/`.
- Copy: use the wording in `docs/spec/ui-screens.md` exactly unless the task says otherwise.

## Additions made while writing the task prompts

These names were added by individual task prompts. They are as binding as the rest of this file. The task id is the one that creates the name; later tasks read the file before using it.

### Domain

| Name | File | Created by |
|---|---|---|
| `DomainError` and subclasses | `domain/errors.py` | F01 |
| `display`, `coding_for`, `parse_code`, `CODE_SYSTEM_NAMES` | `domain/codes.py` | F07 |
| `AvailableTime.weekdays`, `every_day`, `every_day_all_day` | `domain/model/service.py` | D01 |
| `CapacityReport.is_closed` | `domain/model/capacity.py` | D02 |
| `effective_occupied` | `domain/rules/availability.py` | D06 |
| `limited_or_worse_count`, `WATCH_FROM`, `HIGH_FROM`, `LIMITED_OR_WORSE` | `domain/rules/pressure.py` | D08 |
| `SERVICE_LETTERS` | `domain/rules/reply_parser.py` | D10 |
| `NeedNumber` decision | `domain/rules/reply_policy.py` | D11 |
| `allowed_targets`, `is_open`, `is_terminal`, `ALLOWED` | `domain/rules/booking_state.py` | D13 |
| `REFERENCE_ATTEMPTS` | `domain/rules/booking_rules.py` | D14 |
| `Booking` (with `with_status`) | `domain/model/booking.py` | P02 |
| `Practitioner`, `PractitionerRole` (incl. `covered_by_practitioner_id`, `covered_until`), `REPORTER_ROLE_CODES` | `domain/model/people.py` | P03 |
| `Registration` | `domain/model/registration.py` | P04 |
| `ReportFlag`, service flags | `domain/model/flags.py` | P04 |
| Events `PhoneTaskRaised` (`capacity.events`, session id the service) and `ReportEscalated` (`alerts.events`), fields `service_id`, `due_at`, `at` (all UTC; `due_at` is the prompt's due time) | `domain/events.py` | U06 (delivered with DEC-166) |
| Event `ReportFlagged` (`capacity.events`; fields `flag_id`, `service_id`, `report_id`, `reason: ReportFlagReason`, `at`) | `domain/events.py` | U07 (delivered) |
| Event `DeclinedDespiteCapacity` | `domain/events.py` | U13 |
| Event `ServiceActivated` (`registration.events`) | `domain/events.py` | U15 |
| Event `BookingPhonePrompt` | `domain/events.py` | U19 |
| Event `BookingCancelled` | `domain/events.py` | U20 |
| Events `BookingWithdrawn`, `BookingNotReached`, `WithdrawalEscalated` | `domain/events.py` | U21 |
| Event `ReporterInvited` | `domain/events.py` | U24 |
| `DomainEvent` union, `topic_for`, `session_id_for`, `from_payload`, `<Event>.decode(payload)`, topic constants `CAPACITY_EVENTS`, `BOOKING_EVENTS`, `REGISTRATION_EVENTS`, `CRITERIA_EVENTS`, `ALERTS_EVENTS` (rules in DEC-041) | `domain/events.py` | D25 |

### Application

| Name | File | Created by |
|---|---|---|
| `Actor` (moved from P06), `SYSTEM_ACTOR` (added by U19 if missing) | `application/actor.py` | P05 |
| `outbox_message_for(event, id, ...)` | `application/ports/outbound/outbox.py` | P06 |
| `UnitOfWork.scheduled_work` typed as `ScheduledWorkRepository` | `application/ports/outbound/unit_of_work.py` | P06, tightened by P08 |
| `UnitOfWork.contacts`, `UnitOfWork.pins`, `UnitOfWork.devices` (the P16 stores: `ContactStore`, `PinStore`, `DeviceRegistry`) | `application/ports/outbound/unit_of_work.py` | P06 (DEC-071 item 9, lesson L86) |
| `BookingRepository.confirmed_since_for_services(service_ids, since) -> dict[str, list[datetime]]` (one query, `Q-BOOK-CONFIRMED-FOR`; extends the P02 port) | `application/ports/outbound/repositories.py`, `adapters/outbound/graph_store/booking_repository.py` | U08 (DEC-088) |
| `Communication.message_id` is `str`; `latest_prompt_for_phone` takes role ids | `application/ports/outbound/messaging.py` | P07 |
| `IdempotencyStore` (`get`, `put`): command replay, backed by `Neo4jIdempotencyStore` | `application/idempotency.py`, `adapters/outbound/graph_store/idempotency_store.py` | P15 |
| `ReportCapacityCommand.flag` | `application/use_cases/report_capacity.py` | U01 |
| `schedule_work(uow, ids, *, kind, about_id, due_at, now)`, `cancel_work(uow, work, now)` | `application/scheduling.py` | U03 |
| Outbox event types `ScheduleWork` (payload `work_id, kind, about_id, enqueue_at`) and `CancelWork` (payload `work_id`) on topic `scheduled.work`; the relay delivers `ScheduledWorkDue` (payload `work_id, kind, about_id`) | `application/scheduling.py`, relay in I03 | U03, I03 |
| `ContentSealer` port (`seal(content, *, message_id, tenant_id, recipient_role_id)`, `unseal(sealed, *, ...)`): seals prompt content so no token text is at rest (DEC-116) | `application/ports/outbound/sealing.py` | U03 (DEC-116) |
| `AesGcmContentSealer(secrets)`, `derive_key(secret)`, `seal_content`, `unseal_content`: AES-256-GCM, associated data the outbox message id, tenant id and recipient role id, strict `v2.` base64url text (DEC-116) | `adapters/outbound/content_seal/aes_gcm.py` | U03 (DEC-116) |
| `SendMessage` outbox payload from `SendPrompts`: `communication_id, message_id, channel, recipient_role_id, sealed_content` (no `text`, `subject` or `html`; I10 opens `sealed_content` with the outbox message id, the tenant and `recipient_role_id`; a U01 echo still carries `text`) (DEC-115 item 10, DEC-116 item 8) | `application/use_cases/send_prompts.py` | U03 |
| `SendPrompts(uow_factory, clock, ids, idempotency, link_tokens: LinkTokenServiceFactory, link_base_url, sealer: ContentSealer, tenant_id)`, `SendPromptCommand`, `SendPromptResult`, the skip reasons `SKIP_*`, `split_unit_label` (DEC-115 items 1, 12, 13, 15; DEC-116 item 7) | `application/use_cases/send_prompts.py` | U03 |
| `ScheduledWork.status` values `scheduled`, `done`, `cancelled` | `application/work.py` | P08 |
| `WorkKind` value `not-updated-check` | `application/work.py` | U34 |
| `DeviceRegistry.get`, `DeviceRegistry.save`, `DeviceRegistry.find_by_token_hash` (wall screens of the bound tenant; `find_by_token_hash` returns only an active one); `ClaimPairingResult.status` may be `expired` | `application/ports/outbound/identity.py`, `use_cases/pair_wall_screen.py` | U10, R15 (DEC-160) |
| `Device(id, status, name, location, device_type, token_hash, board_scope)`, `DeviceStatus` (`paired-unclaimed`, `active`, `revoked`), `DeviceType` (`wall-display`), `BoardScope` (`tenant`, `network`), `check_screen_label`, `SCREEN_LABEL_MAX`; `DEVICE_TOKEN_SECRET` (`device-token`) | `domain/model/device.py`, `application/ports/outbound/identity.py` | U10 (DEC-160) |
| `StartPairing(uow_factory, clock, ids, rng, secret_store, cache).execute() -> StartPairingResult(pairing_id, code_display, screen_secret, expires_at)`; `ConfirmPairing(uow_factory, clock, secret_store, cache)` with `ConfirmPairingCommand(idempotency_key, actor, code, screen_name, location, board_scope=tenant) -> ConfirmPairingResult(device_id, screen_name, replayed)`; `ClaimPairing(uow_factory, clock, rng, secret_store)` with `ClaimPairingCommand(pairing_id, screen_secret) -> ClaimPairingResult(status: waiting, paired or expired; device_token)`; `PairingRateLimited` (R15 answers 429), `AttemptLimiter(cache)` (`take(name, limit, window) -> slot or None`, atomic; `release(slot)`), `normalise_code`, the constants `START_LIMIT`, `CONFIRM_FAILURE_LIMIT`, `LIMIT_WINDOW`, `REFUSED_MESSAGE`; link-token purposes `wall-pairing` and `wall-pairing-secret`; audit actions `wall-screen-paired`, `wall-screen-claimed` | `application/use_cases/pair_wall_screen.py` | U10 (DEC-160) |
| Statements `Q-SCREEN-GET` (a write: it takes the screen's lock), `Q-SCREEN-SAVE`, `Q-SCREEN-BY-TOKEN`; node `(:Device {id, tenantId, deviceType, status, deviceName, locationName, boardScope, tokenHash, updatedAt})` | `adapters/outbound/graph_store/credential_store.py` | U10 (DEC-160) |
| `DeviceRegistry.revoke_all`, device status `pending-callback` | `application/ports/outbound/identity.py` | U37 |
| Graph names for P13 (DEC-080 to DEC-082): label `RegistrationDraftField` (properties `step`, `field`, `value`) joined to its Task by `DRAFT_OF`; Task properties `businessStatus` and `submittedAt`; Task code `register-service` in CodeSystem `task-code`; ENTRY properties `flag`, `date`, `reason`; the scope list is `(:Resource:List {id: 'scope-list'})` | `adapters/outbound/graph_store/registration_repository.py`, `scope_list_repository.py` | P13 |
| Extensions `checkAutomatic`, `checkCallback`, `checkScope`, `checkCriteria` (the four approval checks, DEC-081) | `adapters/outbound/graph_store/extensions.py` | P13 |
| `registration_to_fhir`, `registration_from_fhir`, `draft_to_rows`, `draft_from_rows` (pure mapping) | `adapters/outbound/graph_store/registration_repository.py` | P13 |
| `ServicePositions` port | `application/ports/outbound/geo.py` | U12 |
| `Terminology.search_pathways_dx(text, limit)` | `application/ports/outbound/terminology.py` | R16 |
| `ProcessedMessages` port and `UnitOfWork.processed`: consumer idempotency | `application/ports/outbound/idempotency.py` | G08 |
| `DeliveryUpdate(provider_message_id, status, error_code)`, `TransientSendError`, `SendFailedError` (DEC-107) | `application/ports/outbound/messaging.py` | I06 (DEC-107) |
| `TwilioSms(client, account_sid, auth_token, from_number, status_callback_url)`, `to_e164_uk(number)`, `parse_status_callback(form)` (DEC-107) | `adapters/outbound/sms_twilio/twilio_sms.py` | I06 (DEC-107) |
| Settings `twilio_account_sid`, `twilio_auth_token`, `twilio_from` (DEC-107; the public base is the existing `base_url`) | `bootstrap/settings.py` | I06 (DEC-107) |
| `PushSubscriptionRepository` | `application/ports/outbound/messaging.py` | I14 |
| `AlertSubscriptionRepository` and `UnitOfWork.alert_subscriptions` | `application/ports/outbound/repositories.py` | U33 |
| `AlertRepository` | `application/ports/outbound/repositories.py` | U34 |
| `CaseRepository.opened_between` and other date-range reads | `application/ports/outbound/repositories.py` | U35 |
| `ServiceMove` store | `application/ports/outbound/repositories.py` | U38 |
| `ClinicalRequestRepository`, `ProtectedTextStore` | `application/ports/outbound/repositories.py` | U40 (U41 carries the same spec in case it runs first) |
| `AuditLog.records_for` | `application/ports/outbound/audit.py` | U42 |
| P05 names (DEC-055): `canonical_json`, `chain_hash_over`, `TIME_FORMAT`; `AuditLog` methods are `async`; `records(since=<record id>)`; `Neo4jAuditLog(tx, ids=None, clock=None)`; `append_provenance(..., extra=None, agent_type="Practitioner")`; `ensure_audit_head(driver)`, `AuditHeadMissing`; node label `AuditRef {id, kind}` for audit placeholders | `application/ports/outbound/audit.py`, `adapters/outbound/audit_neo4j/audit_log.py` | P05 |
| `SupportRepository` | `application/ports/outbound/support.py` | O06 |
| `SequentialIds` fake | `adapters/testing/` | F06 |
| P11 names (DEC-059): `Severity` (FHIR issue severities; `ValidationIssue` refuses others); `TravelRange` refuses `low > high`; `Geocoder`, `TravelTime`, `Terminology`, `FhirValidator` methods are `async`, `PostcodeLocator` is synchronous; `FixedGeocoder`, `FixedPostcodeLocator`, `FixedTravelTime` in `fixed_geo.py`, `FixedTerminology`, `PassThroughValidator`, `RecordingValidator` (with `calls`) in `fixed_terminology.py` | `application/ports/outbound/geo.py`, `application/ports/outbound/terminology.py`, `adapters/testing/fixed_geo.py`, `adapters/testing/fixed_terminology.py` | P11 |

### HTTP (back end)

| Route | Created by |
|---|---|
| `POST /screens/pairing`, `GET /screens/pairing/{id}` (header `X-Screen-Secret`), `POST /screens` | R15 |
| `GET /terminology/pathways-dx?q=` | R16 |
| `POST /fhir/Task/{id}/$acknowledge` | R17 |
| `POST /identity/new-phone`, `POST /identity/new-phone/verify`, `POST /fhir/Practitioner/{id}/$confirm-new-phone` | R13 |
| `/support/codes`, `/support/accesses`, `/support/sessions/...`, `/support/tickets/{id}/approve`, `/support/traces/{id}` | R18 |

### Front end

| Name | Created by |
|---|---|
| URLs: advisor `/advisor/...` (case pages `/advisor/case/[ref]`), lead `/lead/...`, reporter app `/app/...`, reporter set-up `/setup`, exec `/exec/...`, clinical `/clinical/...`, staff sign-in `/sign-in` | W09, W10, W17, W33, W35, W39, W44 |
| `contrastRatio` helper | F09 |
| `components/forms/ErrorSummary.tsx` (`errors: {field, message}[]`) | W18 (small), extended by W54 |
| `components/forms/CodeEntry.tsx` | W23 |
| `lib/forms/ukMobile.ts` (`isUkMobile`) | W37 |

### Adapters: graph mapper (G02)

| Name | Created by |
|---|---|
| `adapters/outbound/graph_store/mapper.py`: `NodeSpec(key, labels, properties)`, `RelSpec(type, start, end, properties)`, `GraphFragment(root_key, nodes, rels)`, `to_graph(resource) -> GraphFragment`, `from_graph(fragment) -> dict`, `upper_snake(name) -> str`, errors `UnsupportedElement(path)` and `InvalidReference(path)` | G02 |
| Node key `Type/id`; node labels `("Resource", Type)`; node properties `id`, `iri`, optional `versionId` and `lastUpdated`, plus primitives under their FHIR names. No `json` property (DEC-001). | G02 |

- P14: `FlagRepository` gains `services_with_flag(code) -> set[str]` (ids of services with an active service flag of that code). `ReportFlag` and `ServiceFlag` are in `domain/model/flags.py`; the service flag id is `<serviceId>.<code>`. `ReportFlag.id` has a unique key (migration 0027); a racing add raises `Conflict`, and the unit of work (P06) must roll back on any `Conflict` and never commit a failed write, for every write path (DEC-083 item 9). (DEC-083)

## Registration approval (DEC-032)
- The pure gate `domain/rules/registration.py` takes booleans; it does not know who the approver is.
- The use case that approves a registration (U29) must refuse when the approver is the requester. This is the only place that check lives. Any other caller that approves a registration must make the same check.

### Board cache and live update (U09)

| Name | Created by |
|---|---|
| `application/use_cases/board_projector.py`: `BOARD_CACHE_KEY = "board:v1"`, `BOARD_CACHE_TTL` (60 s, [ASSUMED]), `BOARD_CHANGED = "board-changed"`, `REBUILD_EVENTS` (the seven event names that rebuild the board), `WALL_ACTOR`, `board_to_dict(board) -> dict`, `board_from_dict(data) -> Board`, `BoardProjector(query_board, cache, clock)` with `async handle(event_type, payload) -> bool` and `async get_board(actor) -> Board`. Message on `board.updates`: `{"type": "board-changed", "service_id": str or null, "at": ISO 8601 UTC}`, no figures. The cache holds the board as JSON under `board:v1`. | U09 |

## Email adapter (I09, DEC-110)
- `adapters/outbound/email_smtp/smtp_email.py`: `SmtpEmail(settings)` implements `EmailSender`. `SmtpSettings` is the structural Protocol it reads (`smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_starttls`, `email_from`). `build_message(to, subject, text, html, from_addr, message_id) -> EmailMessage` and `text_to_html(text, link_label) -> str` are module functions. The settings are read by `bootstrap/settings.py` as `Settings` fields with the same names.

## ConfirmCapacity (U02, DEC-112)
- `application/use_cases/confirm_capacity.py`: `ConfirmCapacityCommand(idempotency_key, actor, service_id, source, performer_role_id=None)`, `ConfirmCapacityResult(report_id, status, status_changed, next_due, confirmed_value, replayed=False)`, `ConfirmCapacity(uow_factory, clock, ids, idempotency)`. Created by U02.
- `domain/errors.py`: `ConfirmLimitReached`, `NothingToConfirm` (both `DomainError`). Created by U02.
- `CapacityRepository.lock_service(service_id) -> None` (query `Q-CAP-LOCK-SERVICE`) and `CapacityRepository.trailing_confirmations(service_id) -> int` (query `Q-CAP-TRAILING-CONFIRMS`). Created by U02.
- `CapacityRepository.latest_confirmation_at(service_id) -> datetime | None` (query `Q-CAP-LATEST-CONFIRMED-AT`): the effective time of the newest confirmed report, None when there is none. Created by U02 round 3 (DEC-140).
- `domain/errors.py`: `EffectiveBeforeConfirmation(ValidationFailed)`, a number whose explicit effective time is before the latest confirmed figure. Created by U02 round 3 (DEC-140).
- `application/use_cases/report_capacity.py`: `record_report(..., use_case=, audit_snapshot=)` gains two optional keyword arguments, and `_check_may_report` is renamed to the public `check_may_report`. Changed by U02 (DEC-112 item 1).

## Tenancy seam, step one (TEN-001, DEC-142, DEC-144)
- `application/tenancy.py` (standard library only): `ScopeKind` (`TENANT = "tenant"`, `NETWORK = "network"`), `ScopeId(value, kind)` with `ScopeId.tenant(value)`, `ScopeId.network(value)` and `ScopeId.parse(value)` (the `net-` prefix decides the kind; an invalid value raises `ScopeInvalid`), `NETWORK_PREFIX`, `DEFAULT_TENANT_ID = "default"`, `TENANT_ID_PATTERN`, `NETWORK_ID_PATTERN`, `is_valid_tenant_id(text) -> bool`. Binding: `bind_scope(scope)` and `bind_tenant(tenant_id)` (context managers; the edge binds once per unit of work), `current_scope_or_none()`, `current_scope()` and `current_tenant()` (each raises `TenantNotBound` when nothing is bound; `current_tenant()` also when the bound scope is a network). Errors, all `TenancyError(RuntimeError)`, none a `DomainError`, no constructor argument, one fixed message each: `ScopeInvalid`, `TenantNotBound`, `TenantParameterRefused`, `QueryNotRegistered`, `GlobalStatementMisuse`. There is no mode.
- `adapters/outbound/graph_store/queries.py`: `NamedQuery(id, cypher, mode, scope="tenant", scenario=None)` and `QueryTemplate(...)` (same fields; one `{insert}` place), `QueryRegistry(unconverted=UNCONVERTED)` with `register`, `register_template`, `instance(template_id, insert="")`, `template(template_id)`, `get`, `ids`, `template_ids`, `is_registered(query)`, `is_tenant_pending(query)`, `needs_conversion(query)` and `ratchet_ids()`; `REGISTRY`, `GLOBAL_QUERY_IDS` (id to reason; only `Q-NEO4J-PING`), `TenantPredicateMissing` and `ScenarioMissing` (both `ValueError`). `adapters/outbound/graph_store/unconverted.py`: `UNCONVERTED`, the ratchet (ids of statements and templates that do not mention `$tenant` or have no scenario; it may only shrink).
- `adapters/outbound/graph_store/scenario.py` (TEN-004, DEC-150): `Scenario(description, seed=TenantSeed(), params={}, lookup=(), expect=Expect(), insert="")`, `TenantSeed(nodes, rels)`, `SeedNode(ref, labels, props)`, `SeedRel(start, type, end)`, `Expect(rows, after, gone, nodes, rels)`, `NodeSpec(labels, props)`, the per-tenant values `Marked(base)` and `Unique(base, constraint)`, `render(value, slot)`, `validate_scenario(query_id, scenario) -> list[str]`, `collision_blocked(scenario)`, `constraints_used(scenario)` and `SINGLE_PROPERTY_UNIQUE` (constraint name to label and property). A scenario is data; `Scenario("text")` alone builds but does not validate. The generated test is `tests/integration/graph_store/test_tenant_isolation.py` over `tests/support/query_probes.py` (`run_isolation`, `production_statements`, `scenario_gaps`, `ratchet_problems`, `INITIAL_UNCONVERTED`), `tenant_seed.py` and `predicate_removal.py`.
- `adapters/outbound/graph_store/driver.py`: `run_query(tx, query, /, *, registry=None, **params)` and `run_global_query(...)` take a registered `NamedQuery` and nothing else (no string); `run_query` binds the tenant, refuses the keywords `tenant` and `parameters`, and passes the parameters to `tx.run` as one dict. Callers write `run_query(tx, REGISTRY.get("Q-ID"), ...)`.
- Tests: `tests/architecture/test_single_execution_point.py` holds `BINDING_MODULES`, `TENANT_PARAMETER_MODULES` (dotted module names, empty) and `BUILT_CYPHER_RATCHET` (module and count of statements that splice a constant; it may only shrink).

## HandleInboundText (U05, DEC-148)
- `application/use_cases/handle_inbound_text.py`: `HandleInboundTextCommand(idempotency_key, from_phone_hash, text, received_at)` (no tenant field: the tenant is bound at the edge from the number called), `HandleInboundTextResult(outcome: str, service_ids: tuple[str, ...], replayed: bool = False)`, `HandleInboundText(uow_factory, clock, ids, idempotency, cache, report_capacity, confirm_capacity)` with `async execute(command)`. Outcomes (module constants): `RECORDED`, `CONFIRMED`, `LATE`, `CONFIRM_LIMIT`, `RECHECK`, `HELP`, `DROPPED`, `BOOKING_NOT_HANDLED`, `STALE_FIGURE` (`"stale-figure"`), `NEED_NUMBER` (`"need-number"`). Also `CONFIRMABLE_FIGURE_AGE` (= D05 `STALE_WARNING_AFTER`), `figure_is_out_of_date(figure_as_of, prompt_sent_at) -> bool` (the hazard H-31 test), `PROMPT_MESSAGES` and `recheck_key(phone_hash, service_id)`.
- Round 2 (H-32, DEC-148 items 17 to 19): `ConfirmCapacityCommand.expected_latest_id: str | None = None` (default None: confirm whatever is latest; when set, ConfirmCapacity reads the latest under its service lock and raises `LatestReportChanged` if it is another report, writing nothing); `domain/errors.py` `LatestReportChanged(Conflict)` with `latest_value` and `latest_at`; `handle_inbound_text.CONFIRM_PROCESSING_LIMIT` (10 minutes, [ASSUMED]).
- Round 3 (H-32, DEC-148 item 20): `CapacityReport.written_at: datetime | None = None` (not part of equality), the store's write time (`meta.lastUpdated`, whole seconds) that `capacity_repository.report_from_fhir` sets on a read and the mapping to FHIR never writes; `handle_inbound_text.recorded_since_prompt(report, prompt_sent_at) -> bool` (the record-order test: written at or after the whole second the prompt was sent in; a missing write time counts as since). No new Cypher statement.
- `ReportCapacityCommand.send_echo` and `ConfirmCapacityCommand.send_echo: bool = True`: False sends no echo (a caller that sends its own reply); part of the command fingerprint.
- `messages/catalogue.py` `MessageId.C12` and `messages/templates.py`: C12 (text only) fields `service`, `value`, `unit`, `as_of` (full date and time, `23 Oct 08:15`), `reply_with` (`a number` or `<A-H> and a number`; nothing else is accepted), `reply_by`. Text: `DIUCS: UCR West. The figure on record, 3 referrals in the next 2 hrs, is out of date (as of 22 Oct 08:15), so Y was not used. Send a number (0 = closed). By 12:35.`
- `domain/rules/london_time.py` `format_stamp(dt) -> str`: the London day, month and time, `23 Oct 08:15`.

## Inbound SMS webhook (I07, DEC-149)
- `adapters/inbound/sms_webhook/routes.py`: `router` with `POST /webhooks/sms/twilio` and `POST /webhooks/sms/twilio/status` (`REPLY_PATH`, `STATUS_PATH`), `SmsWebhookDeps(cache, event_bus, hasher, secrets, lines, public_base_url)` (set on `app.state.sms_webhook`), `twilio_signature(url, params, token) -> str`, `replay_key(message_sid) -> str`, `REPLAY_TTL` (24 h), `MAX_TEXT_CHARS` (1600), `MAX_FORM_BYTES`, `MAX_FORM_FIELDS`. Mounted by `create_app`.
- `application/ports/outbound/tenant_lines.py`: `InboundLine(tenant_id, token_secret)` and `InboundLineDirectory` (`for_number(to_number, account_sid)`, `for_account(account_sid)`), each `-> InboundLine | None`. Fake: `adapters/testing/fixed_inbound_lines.py` `FixedInboundLines(lines)`. The real directory is TEN-007 and TEN-041.
- `Cache.set_if_absent(key, value, ttl) -> bool` (`application/ports/outbound/cache.py`), on `RedisCache` and `InMemoryCache`.
- `EventBus.enqueue(queue, message) -> None` (`application/ports/outbound/event_bus.py`), on `ServiceBusEventBus` and `ManualEventBus` (which also has `enqueued_to(queue)` and `take_enqueued()`); `BusMessage.tenant_id: str | None = None`, sent as the application property `tenantId`.
- Queue messages: `inbound.replies` carries `SmsReceived` with `{phone_hash, text, received_at, provider_message_id}`; `inbound.receipts` carries `SmsDeliveryReceived` with `{provider_message_id, status, error_code}`, id `<MessageSid>:<MessageStatus>`. Both carry the tenant.
- Replay key: `idem:sms:<tenant>:<MessageSid>` through the cache's `cache:` family.


## Tenancy seam, unit of work and scoped transaction (TEN-002, DEC-146)
- `adapters/outbound/graph_store/driver.py`: `ScopedTx(tx, scope)` (frozen; a transaction and the `ScopeId | None` its unit of work opened under; it has no `run`), `type Tx = AsyncManagedTransaction | AsyncTransaction | ScopedTx` (transitional; TEN-030 narrows it to `ScopedTx`). `run_query` and `run_global_query` take a `Tx`: on a `ScopedTx` the scope is the one it carries and the ambient context is ignored; on a raw transaction it is the ambient scope, as before.
- `application/tenancy.py`: `UnitOfWorkAlreadyOpen`, `UNIT_OF_WORK_OPEN_MESSAGE`, `claim_unit(owner)`, `release_unit(owner)` (called only by the graph store's unit of work), `scope_for_new_unit() -> ScopeId | None` (the one place that reads the scope when a unit, or any code that opens its own transaction, opens).
- `application/ports/outbound/unit_of_work.py`: `UnitOfWork.unit_scope -> ScopeId | None` (read-only; raises `RuntimeError` before the unit is entered). `Neo4jUnitOfWork.unit_scope` implements it. (`uow.scope` stays the scope list repository.)
- `adapters/outbound/graph_store/connection.py`: `Neo4jConnection.run_scoped_read(work)` and `run_scoped_write(work)`, where `work` takes a `ScopedTx`: the supported way for a worker to run scoped work outside a unit of work.
- `tests/support/fake_neo4j.py`: `FakeDriver`, `FakeSession`, `FakeTx`, a recording stand-in for the driver in unit tests (not a store).

## Tenant per run in the test harness (TEN-003, DEC-147)
- `tests/support/tenancy.py`: `RunIdentity(pid, started, nonce)` with `token`, `tenant_id` (`tt-<token>`), `other_tenant_id` (`tt-<token>-b`) and `network_id` (`net-<token>`); `new_run_identity(*, pid=None, now=None, nonce=None)`, `parse_run_id(value) -> RunIdentity | None`; `TenantLeak`, `LEAK_MESSAGE`, `assert_bound_to`, `as_tenant`, `in_tenant`, `tenant_scope`, `guard_async_test`, `guard_sync_test`, `guard_test`.
- `tests/conftest.py`: session fixtures `run_identity`, `tenant_id`, `other_tenant_id`, `network_id`; function fixtures `bound_tenant`, `uow_factory_a`, `uow_factory_b`; the `no_tenant` marker (an integration test that runs with nothing bound). Environment variables `DIUCS_TEST_TENANT`, `DIUCS_TEST_OTHER_TENANT`, `DIUCS_TEST_NETWORK`.
- `tests/support/uow.py`: `tenant_uow_factory(driver, tenant, clock=None, *, factories=None)`.
- `adapters/testing/fixed_ids.py`: `SequentialIds.scoped(scope, prefix="id")` (ids `<scope>-<prefix>-<n>`); `SequentialIds()` is unchanged.

## $board and $confirm-capacity (R05, DEC-145)
- `adapters/inbound/fhir_rest/routes_board.py`: `router`, `BOARD_ROLES`, `CONFIRM_ROLES`. `GET /fhir/HealthcareService/$board` (roles wall, advisor, clinical, lead, exec, owner; `Cache-Control: no-store`) and `POST /fhir/HealthcareService/{id}/$confirm-capacity` (reporter for own service, or lead; `Idempotency-Key` required; 200 with the new Observation).
- `adapters/inbound/fhir_rest/mapping.py`: `board_to_parameters(board) -> dict`, `report_to_fhir(report) -> dict` (valid R4B). R04 adds its functions to this file.
- `CapacityRepository.get(report_id) -> CapacityReport | None`. Created by R05.
- `ApiContainer` (`fhir_rest/app.py`) gains `ids`.

## Wall board page (W05, DEC-151)
- `lib/board/types.ts`: `BoardStatus`, `BoardEntry`, `Board` (now with `organisation: string | null`), re-exports `parseBoardParameters` and `BoardParseError` from `lib/board/parse.ts`. `lib/board/format.ts`: `durationText`, `dataAgeText`, `londonTime`, `londonDate`, `nextDueText`, `ageLineText`, `categoryLabel`. `lib/board/read.ts`: `BOARD_ROLES`, `canReadBoard`, `readBoard(session)` (server only). `components/board/{Board,Tile,Legend,BoardUnavailable}.tsx`. `GET /api/bff/board` (roles wall, advisor, lead, exec; `Cache-Control: no-store`; takes no input).
- **API addition needed (not built):** `$board` gains an optional top-level parameter `organisation` (`valueString`), the display name of the tenant the token is bound to. The wall board header reads it. To be built by the API and sign-in tenancy bundle.

## Wall board live updates and Last known (W06, DEC-152, DEC-153)
- `lib/board/liveness.ts`: `POLL_INTERVAL_MS` (60 s), `STREAM_GAP_MS` (10 s), `STREAM_RETRY_MS` (5 s), `STALE_AFTER_MS` (3 min, [ASSUMED]), `MAX_FUTURE_SKEW_MS` (60 s), `FETCH_TIMEOUT_MS` (15 s), `assessBoard({ generatedAt, nowLocal, clockOffsetMs, health }) -> Assessment` (`{ mode: 'live', streamPaused }` or `{ mode: 'last-known', reason: 'offline' | 'unreadable' | 'old', since, asOf, now, ageMs }`).
- `lib/board/useBoardFeed.ts`: `useBoardFeed({ initialBoard, serverTime, fetchBoard?, createEventSource?, now?, onUnpaired? }) -> { board, assessment }`, `StreamSource`, `REFRESH_EVENTS`. `lib/board/client.ts`: `fetchBoardFromBff(signal?) -> { board, serverTime }`, `BoardFetchError(kind: 'unreachable' | 'refused' | 'unreadable', status)`. `lib/board/boardJson.ts`: `parseBoardJson(value) -> Board` (fails closed with `BoardParseError`). `lib/board/clock.ts`: `serverNow()`.
- `components/board/LiveBoard.tsx` (client; `initialBoard`, `serverTime`), `LastKnownBanner.tsx`; `Board` takes optional `lastKnown` and `streamPaused`; `Tile` takes optional `lastKnown`.
- `GET /api/bff/events` (roles wall, advisor, lead, exec; takes no input): relays the back end's `GET /events` as `text/event-stream`, forwarding only the events `board`, `board.updated` and `booking.updated` with only `serviceId`, `kind` and `changedAt` (`lib/bff/events.ts`: `RELAYED_EVENTS`, `relayEvents(upstream, { signal?, onCancel? })`). `lib/fhir/client.ts`: `fhirStream(path, { token?, traceparent?, signal? }) -> { body }`.
- R06's event is named `board` (DEC-111), not `board.updated`; both are listened to. Network scope: a stream for the network board is not built.

## Wall board variants (W07, DEC-169)
- `components/board/PressureBanner.tsx`: `PressureBanner({ board })` (`board.allLimitedOrWorse`, `board.entries`); `data-el="WALL-PRESSURE-BANNER"`; renders `null` when the flag is false or no service is in hours. `Board` shows it unless the board is last known.
- `lib/board/format.ts`: `reopensText(nextDueAt, now)` ("Reopens 08:00", "... tomorrow", "... Monday"); `ageLineText` returns "Closed overnight" for `out-of-hours`.
- `Tile` data attributes: `WALL-TILE-PENDING` (the "N pending" chip), `WALL-TILE-REOPENS` (the out-of-hours meta line).
- `lib/board/parse.ts` refuses an entry with `tenantId` or `sourceTenantId`, and an entry whose `organisation` is not the board's own.
- Test support: `test/fixtures/board.ts` (`PENDING_TILE`, `CONFIRMED_TILE`, `SURGE_ENTRIES`, `BOARD_SURGE`, `QUIET_ENTRIES`, `BOARD_QUIET`, `QUIET_AT`, `withForeignOrganisation`); `test/msw/handlers/board.ts` (`TOKEN_SURGE`, `TOKEN_QUIET`, `TOKEN_FOREIGN_ENTRY`); `e2e/support/tokens.ts` (the same three, and `LIVE_SURGE_PREFIX`).

## Tenant domain model, settings and lifecycle (TEN-006, DEC-155)
Pure domain, standard library and `diucs.domain` only. Names are the contract for TEN-007, TEN-021, TEN-022, TEN-026, TEN-028, TEN-036, TEN-064, TEN-065, TEN-073 and TEN-074.
- `domain/model/tenant_policy.py`: `TenantPolicy` (frozen; 24 fields in this order with today's defaults: `reply_window`, `reminder_after`, `phone_task_after`, `escalate_after`, `twice_a_day_second`, `stale_warning_after`, `pressure_watch_from`, `pressure_high_from`, `correction_window`, `max_consecutive_confirms`, `many_changes_window`, `many_changes_count`, `phoned_window`, `group_window`, `max_services_per_phone`, `booking_reply_window`, `booking_phone_prompt_after`, `withdrawal_escalate_after`, `criteria_reminder_before`, `clinical_take_timeout`, `reverify_every`, `critical_alert_kinds`, `alert_default_kinds`, `alert_default_not_updated_hours`) with `as_settings() -> dict[str, SettingValue]`; `DEFAULT_POLICY`; `FIELD_BOUNDS` (read-only, field name to inclusive `(minimum, maximum)` in native types; the three set-valued fields have none); `require_policy(value) -> TenantPolicy` (`TypeError("a TenantPolicy is required")` for anything but exactly a `TenantPolicy`); `POLICY_FIELDS`, `POLICY_FIELD_BY_KEY`, `PolicyField(name, key, shape, unit)`, `Shape`, `to_setting_value`, `from_setting_value`; `SettingValue = int | str | bool | time | frozenset[str]`. Every default and bound is a named `Final` constant (`REPLY_WINDOW_DEFAULT`, `REPLY_WINDOW_MIN`, `REPLY_WINDOW_MAX` and so on).
- `domain/rules/tenant_settings.py`: `SETTING_SPECS` (27 `SettingSpec` rows: the 24 policy settings in table order, then `systemName`, `referralSystemName`, `coordinationTeamName`), `SettingSpec(key, kind, policy_field, unit, default, minimum, maximum, choices, allowed, safety_class, scope, required_for_activation)`, `SettingKind`, `SafetyClass`, `SettingScope`; `spec_for(key)`, `validate_value(spec, value)`, `policy_from_settings(values)`, `validate_settings(values)`, `changed_keys(old, new)`, `clinical_keys(keys)`, `approvals_required(old, new)`, `check_approvals(old, new, author_ref, approver_refs)`, `is_named_ref(ref)`, `check_tenant_text(field, value)` (fields `system_name`, `referral_system_name`, `coordination_team_name`). A task that adds a setting adds a row here and to `POLICY_FIELDS` and `FIELD_BOUNDS`; a row that has no class entry is `clinical` on `tenant`.
- `domain/model/tenant.py`: `Tenant` (keyword-only; fields as in the TEN-006 prompt), `TenantContact(kind, label, value)`, `TenantWording(system_name, referral_system_name, coordination_team_name)`, `TenantConfig(version, status, values, created_at, created_by_ref, effective_from, approved_by_refs, reason_code)` with `policy` and `wording` properties; `OrganisationType`, `TenantStatus`, `SuspendMode`, `SuspendReason`, `RetentionClass`, `ContactKind` (`coordination-phone`, `support-email`, `shift-lead-escalation`, `clinical-safety-officer`), `ConfigStatus`, `NumberStatus`; `check_tenant_id(value)`, `check_time_zone(value)`, `TENANT_ID_PATTERN`, `RESERVED_TENANT_IDS`, `RESERVED_TENANT_PREFIX`, `DEFAULT_TIME_ZONE`, `ALLOWED_TIME_ZONES`, `REQUIRED_RETENTION_CLASSES`. `check_tenant_id` refuses `platform` (the application kernel accepts it); a parity test pins the pattern to `application/tenancy.py`.
- `domain/rules/tenant_lifecycle.py`: `transition_tenant(current, target)`, `transition_config(current, target)`, `suspend_tenant(tenant, mode, reason, now)`, `resume_tenant(tenant, now)`, `start_offboarding(tenant, now)`, `complete_offboarding(tenant, now, *, waived=False)`, `purge_tenant(tenant, now)`, `reopen_tenant(tenant)`, `activate_tenant(tenant, facts, now)`, `offboarding_may_complete_at(tenant)`, `number_quarantine_until(retired_at)`, `number_assignable(status, quarantine_until, now)` (`status=None` is a number never assigned), `purge_blockers(tenant, now, operator_refs, typed_slug)`, `activation_blockers(facts)`, `ActivationFacts` (16 required fields), `OFFBOARDING_NOTICE` (30 days), `NUMBER_QUARANTINE` (90 days), `PURGE_OPERATORS_REQUIRED` (2), `REQUIRED_REFERENCES`.

## Tenant directory, global statements and secret references (TEN-007, DEC-163)
- `application/ports/outbound/tenants.py`: `TenantDirectory` (Protocol; all async: `get(tenant_id) -> Tenant | None`, `by_inbound_number(to_number, account_sid) -> TenantLine | None`, `by_account_sid(account_sid) -> TenantLine | None`, `by_host(host) -> Tenant | None`, `by_entra_directory(directory_id) -> Tenant | None`, `list_active() -> Sequence[Tenant]`, `active_tenant_ids() -> Sequence[str]`; it satisfies the relay's `ActiveTenants`), `TenantLine(tenant, number, account_sid, secret_ref)` (frozen), `TenantRecordInvalid(RuntimeError)` (fixed message), `secret_ref(kind, tenant_id, name)`, `twilio_token_ref(tenant_id)` (`twilio/<tenant>/auth-token`), `check_secret_ref(value, tenant_id)` (the tenant's own reference or `ValidationFailed`), and `normalise_e164`, `normalise_account_sid`, `normalise_host`, `normalise_directory_id` (each returns the value in its lookup form or `None`).
- `adapters/outbound/graph_store/tenant_directory.py`: `Neo4jTenantDirectory(connection)`, `tenant_properties(tenant) -> dict` and `tenant_from_properties(props) -> Tenant` (the node mapping), and the seven global statements `Q-TENANT-GET`, `Q-TENANT-LIST-ACTIVE`, `Q-TENANT-ACTIVE-IDS`, `Q-TENANT-BY-NUMBER`, `Q-TENANT-BY-ACCOUNT`, `Q-TENANT-BY-HOST`, `Q-TENANT-BY-ENTRA` (parameters `id`, `number`, `accountSid`, `host`, `directoryId`; never `tenant`).
- `adapters/outbound/graph_store/queries.py`: `GLOBAL_QUERY_IDS` is eight ids (the ping and the seven above); `GLOBAL_STATEMENTS` maps each id to the SHA-256 hex digest of its exact text (`statement_digest(cypher)`: stripped of leading and trailing whitespace, nothing else), and a global statement registers only when its id is pinned and the digest matches (the guarantee); `GLOBAL_STATEMENT_LABELS = {Tenant, TenantNumber}`; as defence in depth a global statement must be `read`, free of write words, have a label on every node (a `(` after a clause keyword is a node pattern) and name only registry labels; a `QueryTemplate` cannot be global. Adding or changing a global statement is a deliberate edit of `GLOBAL_STATEMENTS`, `GLOBAL_QUERY_IDS` and the pin in `tests/unit/adapters/outbound/graph_store/test_global_allowlist.py`.
- Graph (registry nodes, no `tenantId`): `(:Tenant {id, displayName, legalName, organisationType, countryCode, timeZone, status, createdAt, activatedAt, suspendedAt, offboardingStartedAt, offboardedAt, purgedAt, suspendMode, suspendReason, retentionHoldUntil, odsCode, epoch, hashKeyVersion, currentConfigVersion, dsaRef, dpiaRef, dcb0160Ref, host, entraDirectoryId})-[:HAS_NUMBER]->(:TenantNumber {e164, accountSid, secretRef, status})`; constraints `tenant_id`, `tenant_host`, `tenant_entra_directory`, `tenant_number_e164`, index `tenant_number_account` (migration `0034_tenant_registry`); `0035_default_tenant_record` creates the `default` tenant when data is stamped with it. `secretRef` is a reference, never a value.
- `adapters/testing/fixed_secrets.py`: `FixedSecretStore(secrets)` records: `requested` (names in order), `read_count(name)`, `names`; shows no value in `repr` or `vars()`; refuses a non-bytes value and an empty or non-text name.
- `bootstrap/container.py`: `Container.tenants`, `Container.secrets`; `build(settings, *, secrets=None)` (`NoSecrets` when none: every name `NotFound`), `build_for_tests(clock, ids, *, neo4j, secrets=None)`; `startup()` opens, applies the migrations and ensures the audit head, and closes the connection if either fails. `Neo4jConnection.driver` (read-only property).
- Tests: `tests/support/directory_connection.py` (`RecordingConnection`: a stand-in connection that answers by statement id and records the calls).

## Tenant schema: composite keys, the stamp and the migration runner (TEN-005, DEC-159)
- `adapters/outbound/graph_store/migration_types.py`: `Migration(id, statements=(), loops=(), params={}, batch=10_000)` (frozen; `batch` at least 1; `params` read-only), `MigrationFailed(RuntimeError)` and `MAX_LOOP_ITERATIONS = 10_000`. A loop statement receives `$batch` and the migration's parameters and returns exactly one row with an integer `changed`. The message of a failure is `migration <id> failed at statement <n> | loop <n> | record: <ExceptionClass>`.
- `adapters/outbound/graph_store/migrations.py`: `CORE_MIGRATIONS` (the 26 entries of `0001` to `0030`, never edited; a unit test pins a digest), `assemble_migrations(*areas) -> list[Migration]` (sorted by id; a duplicate id is a `ValueError`), `MIGRATIONS` (core, tenant and network areas together) and `apply_migrations(driver, migrations=None) -> list[str]`. Each later task adds its migrations to its own area module and never edits the core list.
- `adapters/outbound/graph_store/migration_loop.py`: `run_loop(driver, statement, params, *, batch, max_iterations) -> int`, `LoopResultInvalid`, `LoopDidNotFinish`.
- `adapters/outbound/graph_store/migrations_tenant.py`: `REGISTRY_LABELS`, `CompositeConstraint`, `CompositeIndex`, `COMPOSITE_CONSTRAINTS` (20), `COMPOSITE_INDEXES` (6), `SUPERSEDED_CONSTRAINTS` (18) and `SUPERSEDED_INDEXES` (6) for TEN-032, `STAMP_DEFAULT_TENANT`, `OPEN_REFERENCE_BACKFILL`, `UNSTAMPED_NODES_QUERY`, `CROSS_SCOPE_RELATIONSHIPS_QUERY`, `ROLLBACK_0031`, `TENANT_MIGRATIONS` (`0031_tenant_composites`, `0032_backfill_default_tenant`, `0033_case_open_reference`), `backfill_default_tenant(driver, *, batch=10_000) -> int` and `invariant_violations(driver) -> {"unstamped_nodes": [...], "cross_scope_relationships": [...]}`. `migrations_network.py`: `NETWORK_MIGRATIONS` (empty; TEN-051 and TEN-053).
- Graph: `ServiceRequest.openReference` (the reference while the case is open, absent once it closes), constraint `tenant_case_open_reference`. Composite constraints are named `tenant_<...>`; the global constraint is `migration_id` on `Migration.id`; `link_token_hash` stays a single-property key.
- Tests: `tests/support/tenant_seed.py` holds `SUPERSEDED_CONSTRAINT_NAMES`, `SUPERSEDED_INDEX_NAMES`, `schema_names(driver)`, `contract_schema(driver)` and `contracted_container()` (a private container with the superseded keys dropped, which the generated two-tenant test runs on until TEN-032). `tests/architecture/test_single_execution_point.py` names `MIGRATION_RUNNER_FILES` (the files that may run Cypher beside `driver.py`).

## Outbox relay worker (I03, DEC-157)
- `adapters/inbound/workers/outbox_relay.py`: `OutboxRelay(uow_factory, bus, cache, clock, tenants, batch_size=100, *, poll_interval_s=1.0, backoff_start_s=1.0)` with `async run_once() -> RelayResult` and `async run_forever(stop: asyncio.Event)`; `RelayResult(published, failed, skipped_no_lock)`; `ActiveTenants` (Protocol, `async active_tenant_ids() -> Sequence[str]`; TEN-007's `TenantDirectory` satisfies it); `StaticTenants(ids)`; constants `LOCK_NAME = "outbox-relay"`, `LOCK_TTL` (30 s), `LOCK_MARGIN` (5 s), `BATCH_SIZE` (100), `BACKOFF_START_SECONDS` (1), `BACKOFF_CAP_SECONDS` (60), `POLL_INTERVAL_SECONDS` (1), `SCHEDULED_WORK_DUE = "ScheduledWorkDue"`. The relay binds one tenant per round, and every `BusMessage` it sends carries `tenant_id`.
- `bootstrap/outbox_relay_main.py`: `python -m diucs.bootstrap.outbox_relay_main`; `service_bus_connection(settings)`, `serve(settings, stop)` (the tenants are `container.tenants`, the tenant directory, TEN-007, DEC-163 item 11; `configured_tenants` and `DIUCS_RELAY_TENANTS` are gone), `RelayConfigError`.
- Tests: `tests/support/relay_rig.py` (`SpyBus`, `InstrumentedFactory`, `TenantPrefixedCache`, `ScriptedTokenCache`, `add_messages`, `add_scheduled`).

## Inbound queue consumers (I08, DEC-165)
- `adapters/inbound/workers/consumer.py`: `MessageConsumer` (Protocol, `async handle(message: BusMessage) -> Outcome`); `ServiceBusRunner` takes one. `servicebus_runner.to_bus_message` copies the `tenantId` application property into `BusMessage.tenant_id`; `ServiceBusRunner.serve` is an alias of `run` (the entry points call it).
- `adapters/inbound/workers/tenant_binding.py`: `TenantBoundConsumer(inner: MessageConsumer, tenants: ActiveTenants, observe=untraced)`, `NO_TENANT`, `BAD_TENANT`, `UNKNOWN_TENANT` (the fixed dead-letter reasons), `Observe`, `untraced`. Every consumer of a message that belongs to a tenant is wrapped in it: it dead-letters a message with no tenant, an invalid one, a network id or one the directory does not list as active, and binds the tenant while the inner consumer runs.
- `adapters/inbound/workers/reply_processor.py`: `ReplyProcessor(handle_inbound_text, uow_factory)` with `async handle(message) -> Outcome` (not an I04 handler: it holds no unit of work around the use case, DEC-165 item 3), `reply_consumer(handle_inbound_text, uow_factory, tenants, observe=untraced) -> TenantBoundConsumer`, `reply_key(provider_message_id)` (`sms-reply:<tenant>:<id>`, from the bound tenant), `CONSUMER_NAME = "reply-processor"`, `REPLY_EVENT = "SmsReceived"`, `HandlesInboundText` (Protocol).
- `adapters/inbound/workers/delivery_tracker.py`: `DeliveryTracker` (an I04 handler, `await tracker(message, uow)`), `receipt_consumer(uow_factory, tenants, observe=untraced) -> TenantBoundConsumer`, `CONSUMER_NAME = "delivery-tracker"`, `RECEIPT_EVENT = "SmsDeliveryReceived"`, `RECEIPT_STATUSES`.
- `application/ports/outbound/idempotency.py`: `ProcessedMessages.seen(message_id, consumer) -> bool` (read-only, in the bound scope; `Q-PROCESSED-SEEN`).
- `application/ports/outbound/messaging.py`: `statuses_before(status) -> tuple[str, ...]` (the statuses a Communication may move from to reach `status`: queued, then sent, then delivered or failed, which are final; `received` and `grouped` never move; an unknown status is a `ValueError`), and `CommunicationRepository.set_delivery_status` now returns True only when the record moved (an unknown provider id, a refused move and a repeat are False), decided under the record's write lock.
- `bootstrap/workers_main.py`: `python -m diucs.bootstrap.workers_main`; `configured_tenants(environ)` reads `DIUCS_WORKER_TENANTS` (a stand-in for the directory), `service_bus_connection(settings)`, `build_runners(client, handle_inbound_text, uow_factory, tenants)`, `run_workers(loops, stop)`, `serve(settings, tenants, stop)`, `WorkersConfigError`. `graph_store/connection.py`: `Neo4jConnection.driver` (read-only property).
- Tests: `tests/support/inbound_rig.py` (`reply_message`, `receipt_message`, `RecordingUseCase`, `UnitLog`, `logging_factory`, `Receiver`, `raw`).

## Grouped prompts (U04, DEC-158)
- `application/use_cases/send_prompts.py`: `prompt_key(service_id, due) -> str` (`prompt:<service_id>:<due in UTC, isoformat>`: the idempotency key of the prompt for a service at a due instant; the `prompt-due` job builds its `SendPromptCommand.idempotency_key` with it, because a grouped prompt stores the other services' results under these keys), and `SendPromptResult.grouped_service_ids: tuple[str, ...] = ()` (every service prompted in one C9 with this one, itself included, in letter order; empty when prompted alone). `SendPrompts`'s constructor and `SendPromptCommand` are unchanged.
- `application/ports/outbound/messaging.py`: `GROUPED_STATUS = "grouped"`, a member of `DELIVERY_STATUSES`: the delivery status of the Communications of a grouped prompt other than the one that is sent (letter A's is `queued`). Its FHIR `Communication.status` is `completed`.
- Stored form of a grouped prompt, which U05 reads (DEC-148 item 9, DEC-158 item 7): one `Communication` per grouped service, `message_id` C9, the same `sent_at` and `payload_text` (`A) <name> <figure>. B) <name> <figure>...`), `about_id` the service, `recipient_role_id` the role the phone holds for it; only letter A's has a `SendMessage` outbox message.

## Report flags (U07, DEC-161)
- `application/use_cases/report_flags.py`: `raise_report_flags(uow, ids, *, profile, report, extra: ReportFlagReason | None, now) -> list[str]` (the ids of the flags raised, in order) and `LOOKBACK` (the longer of D12's two windows). Called by `record_report`; a use case that writes a report does not call it itself.
- `application/use_cases/report_capacity.py`: `ReportCapacityResult.flag_ids: tuple[str, ...] = ()`; `record_report(..., flag: ReportFlagReason | None = None)`; `ReportCapacity` no longer refuses `ReportCapacityCommand.flag`. The audit entry's `entity_ids` are `(report id, service id, *flag ids)`.
- `domain/events.py`: `ReportFlagged` is in the `DomainEvent` union, on `capacity.events`, with the service id as session id.

## Mapper tenant names (TEN-008, DEC-162)
- `adapters/outbound/graph_store/extensions.py`: `TENANT_OWNED_NAMES = frozenset({"tenantId", "sourceTenantId"})`. `ExtensionDef` refuses a short name in it (`ValueError`). `mapper.py` imports it: `to_graph` refuses an element of either name (`ValidationFailed`, "reserved: the tenancy seam stamps this name") and refuses a fragment that would carry one, and `from_graph` drops both from every node it rebuilds from. TEN-009 adds both to the resource store's `RESERVED_PROPERTIES`; no other module writes the name `tenantId` on a node a resource owns except the writer's stamp.

## Resource store tenancy (TEN-009, DEC-164)
- `adapters/outbound/graph_store/resource_scenarios.py`: `SCENARIOS: dict[str, Scenario]`, one per `Q-RES-*` template, read by `resource_store.py` when it registers them.
- Templates: sixteen, all with `tenantId: $tenant` and a scenario. New: `Q-RES-LINK-SHARED` (insert `:IN_SYSTEM`; params `rows` of `{start, end}`; returns `linked`; a MERGE of the concept-to-code-system edge). Changed parameters: `Q-RES-LOAD-NODES` and `Q-RES-LOAD-RELS` take `resourceKey` (the resource's own key, also for a version), `key` and `prefix` and an insert of `:Resource` or `:ResourceVersion`; `Q-RES-CLEAR-OWNED` takes `key` and `prefix`; `Q-RES-SHARED-READ` takes no insert. Removed: `Q-RES-IDEM-GET`, `Q-RES-IDEM-RECORD`.
- `ResourceStore.put(resource, expected_version)`: the `idempotency_key` argument is gone. `RESERVED_PROPERTIES` also holds `tenantId` and `sourceTenantId`.
- Tests: `tests/support/predicate_removal.py::mutant_of` registers the copy of a template instance under the template's id.
- `ResourceStore.put` refuses (`ValidationFailed`, before any write) a reference target or a resource type that is not letters only with a capital or is a registry label (`REGISTRY_LABELS`, `GLOBAL_STATEMENT_LABELS`) or a store label (DEC-164 item 11). `Q-RES-LINK-SHARED` returns `count(DISTINCT [a.key, b.key]) AS linked`.

### Missed-report ladder (U06, DEC-166)

| Name | Where | Task |
|---|---|---|
| `application/use_cases/missed_report_ladder.py`: `LadderStepCommand(idempotency_key, actor, work_id)`, `LadderStepResult(action, communication_id=None, replayed=False)` with `action` one of `REMINDED`, `PHONE_TASK_RAISED`, `ESCALATED`, `STOPPED`, `IGNORED` (`"reminded"`, `"phone-task"`, `"escalated"`, `"stopped"`, `"ignored"`), `MissedReportLadder(uow_factory, clock, ids, link_tokens, link_base_url, sealer)` with `async execute(command)`, `LADDER_OFFSETS`, `LADDER_KINDS`, `REMINDER_REPLY_WINDOW` (30 min, [ASSUMED]), `ladder_due(work)`, `prompt_answered(effective_at, due)`, `async stop_answered_ladders(uow, service_id, *, answered_at, now) -> tuple[str, ...]`. The tenant is the unit of work's scope, not an argument. `record_report` calls `stop_answered_ladders`. | U06 |

### Services and capacity endpoints (R04, DEC-168)

- `GET /fhir/HealthcareService` (searchset Bundle; `active=true`, `service-category`, `organization`, `_count` 1 to 100, `_offset`), `GET /fhir/HealthcareService/{id}` (ETag), `POST /fhir/Observation` (201, `Location: /fhir/Observation/{id}`), `GET /fhir/Observation?focus=HealthcareService/{id}&_sort=-date&_count=1`, `GET /fhir/Observation/{id}`; `PUT`, `PATCH`, `DELETE` on `/fhir/Observation/{id}` are 405. Created by R04.
- `routes_services.register_capabilities`, `capability.is_registered`. `mapping.py`: `service_to_fhir`, `search_bundle`, `report_request_from_fhir` (returns `ReportRequest`), `validate_outbound`, `ucum_unit`, `API_SOURCES`, `FHIR_ID_PATTERN`. Created by R04.
- `ServiceRepository.get_versioned(service_id) -> tuple[ServiceProfile, int] | None` (no new query). Created by R04.
## Link pages (L01, DEC-167)
- `adapters/inbound/link_pages/capacity_links.py`: `router` (`GET /links/{token}`, `POST /links/{token}`, `POST /links/{token}/renew`), `LinkPagesDeps(cache, sealer)` (set on `app.state.link_pages` by the serving process; the container supplies `tenants` and `secrets`), `RedactLinkTokens` and `install_log_redaction()` (the access log shows `/links/[token]`), `LINK_PAGE_PATH = "/l"`, `LINK_SCHEME`, `SEND_THE_NUMBER_TEXT = "Please send the number"`. The tenant is the active tenant of the request host (`TenantDirectory.by_host`). Mounted by `fhir_rest/app.py`.
- `application/use_cases/link_access.py`: `ViewLink`, `RespondViaLink`, `RenewLink` (each `(uow_factory, clock, secrets, cache, link_tokens: LinkTokenServiceFactory, purposes: LinkPurposes)`, `async execute(query_or_command)`), `ViewLinkQuery(token, client)`, `RespondViaLinkCommand(token, csrf_token, action: LinkAction, client)`, `RenewLinkCommand(token, client, link_base_url)`, `LinkAction(action, value=None, confirm_out_of_range=False)`, `LinkView(purpose, body)`, `LinkResponse(body)`; errors `LinkGone(state)` (`expired` or `used`), `CsrfRejected`, `LinkOutOfRange(usual_min, usual_max)`, `SendTheNumber(reason)` (`no-figure`, `limit`, `stale`, `changed`), `LinkRateLimited(retry_after_seconds)`; the purpose registry `LinkPurposes = Mapping[str, LinkPurposeHandler]` (`view`, `respond`, `renew`) keyed by the stored purpose, with `CapacityLinkHandler` registered for `capacity-reply` (L02 registers `booking-request`); `csrf_token(token_hash, secret)`, `command_key(scope, record)` (`link:<tenant>:<hash>`), `LINK_CSRF_SECRET = "link-csrf"`, the rate-limit constants (`REQUESTS_PER_WINDOW` 60 a minute, `BAD_ATTEMPTS_PER_ADDRESS` 20 in 10 minutes, `RENEWALS_PER_WINDOW` 20 in 10 minutes), `UnitOfWorkIdempotency(uow_factory)`.
- JSON: `GET` 200 `{state: "ok", purpose, serviceName, unitLabel, recordedValue, asOf, usualMin, usualMax, replyBy, nextDue, csrfToken}`; 410 `{state: "expired" | "used"}`; `POST` 200 `{serviceName, value, unitLabel, recordedAt, nextDue}`, 400 `{state: "invalid"}`, 403 `{state: "forbidden"}`, 409 `{state: "send-number", reason, message}`, 410, 422 `{state: "out-of-range", usualMin, usualMax}`, 429 `{state: "rate-limited"}` with `Retry-After`; `renew` 202 `{state: "accepted"}`. Times are ISO 8601 UTC with a `Z`. W04's prompt describes another shape; it follows this one.
- `adapters/outbound/graph_store/link_token_repository.py`: `Q-LINK-ADD`, `-GET`, `-MARK-USED`, `-BURN-KEY` are tenant statements with scenarios (off the ratchet); a `LinkToken` node carries `tenantId`.
- `tests/support/link_rig.py`: `LinkRig`, `build_link_rig`, `ucr_west`, `token_hash_of`; `ladder_rig.build_rig(..., clock=)`.

## Capacity link pages (W04, DEC-172)
- `app/l/[token]/page.tsx` (server: checks the token's shape, renders `LinkLoader`, or `LinkExpired` for a token that cannot be a link; `metadata` sets `referrer: no-referrer` and `robots` noindex; `dynamic = 'force-dynamic'`). `app/l/[token]/thanks/page.tsx` (server: `searchParams` carry the answer, read by `parseThanks`).
- `app/api/bff/links/[token]/route.ts`: `GET` (no session: reads the link through `readLink`, sets the cookie `diucs_link_csrf` for this link's path, returns the view with `csrfToken`; 410 `{state: "expired"}`, 503 `{state: "unavailable"}`), `POST` (the CSRF header must equal the cookie, 403 otherwise; forwards only `action`, `value`, `confirmOutOfRange`; passes the back end's status and fields through `publicReply`). `app/api/bff/links/[token]/renew/route.ts`: `POST` (no CSRF; 202 `{state: "accepted"}`, 429 with `Retry-After`, 503).
- `lib/links/model.ts`: `LinkView`, `LinkAnswered`, `LinkAnswer`, `ThanksDetail`, `LinkShapeError`, `parseLinkView`, `parseLinkAnswered`, `splitUnitLabel(unitLabel) -> {noun, window}`, `londonHm(instant)`, `thanksQuery(answered)`, `parseThanks(params)`.
- `lib/links/server.ts` (server only): `backendRoot(value)` (the origin of `DIUCS_FHIR_BASE_URL`, which must end in `/fhir`), `hostOf(request)`, `callLinkApi({method, path, host, body?, csrf?}) -> {status, body, retryAfter?}` (node:http, the host sent as `Host`), `readLink(token, host) -> {kind: 'open', view} | {kind: 'gone'}`, `publicReply(status, body)`, `LinkApiError(kind: 'unavailable' | 'bad-answer')`.
- `lib/links/csrf.ts` (server only): `LINK_CSRF_COOKIE = 'diucs_link_csrf'`, `linkCsrfPath(token)`, `issueLinkCsrf(token, value)`, `checkLinkCsrf(request, token)`.
- `lib/links/browser.ts`: `readLinkView(token) -> {kind: 'open', view} | {kind: 'gone'} | {kind: 'unavailable'}`, `sendAnswer(token, csrf, answer) -> AnswerOutcome`, `requestRenew(token) -> 'accepted' | 'rate-limited' | 'failed'`.
- `components/reporter/`: `LinkLoader` (client; reads the link once and shows the page it says), `CapacityResponder` (client; `token`, `view`), `LinkExpired` (client; `token`), `LinkUnavailable`, `Reporter.module.css`. `components/ui/Button` takes `disabled`.
- Test support: `test/fixtures/links.ts` (`LINK`, the scenario tokens; `linkViewReply`, `linkAnswerReply`, `linkRenewReply`, the one table the MSW handlers and the browser stand-in share), `test/msw/handlers/links.ts` (`seenBffPosts`, `seenBffRenews`, `seenBackendRequests`), `e2e/support/links.ts` (`handleLinkRoute`, served by the stand-in back end).
## Scheduled work consumer (I05, DEC-190 to DEC-195)

- `adapters/inbound/scheduler/scheduled_work_consumer.py`: `CONSUMER_NAME = "scheduler"`, `EVENT_TYPE = "ScheduledWorkDue"`; `WorkHandler = Callable[[ScheduledWork], Awaitable[None]]`; `ScheduledWorkDispatcher(handlers: Mapping[WorkKind, WorkHandler])` with `kinds: frozenset[WorkKind]`, `handlers` (the table, read-only) and `async __call__(work: ScheduledWork) -> None` (raises `PermanentError("no handler for <kind>")` for a kind with none); `ScheduledWorkConsumer(dispatcher, uow_factory)` (a `MessageConsumer`, DEC-190); `build_scheduled_work_consumer(handlers, uow_factory, tenants, observe=untraced) -> TenantBoundConsumer`.
- `bootstrap/container.py`: `Container.scheduled_work: ScheduledWorkDispatcher` (the ladder kinds reminder, phone-task and escalate-to-lead, DEC-192); `SCHEDULER_ACTOR` (DEC-193); `build_for_tests(..., *, link_base_url=TEST_LINK_BASE_URL)`.
- `bootstrap/workers_main.py`: a third runner on `scheduled.work`, built by `build_runners(client, handle_inbound_text, uow_factory, tenants, dispatcher)` (DEC-194).

## Criteria pre-filter and history (G11, DEC-197)

- `Q-CRIT-FILTER` (NamedQuery, tenant, read, scenario): active unsuspended services' current criteria for a band, district and needs.
- `Q-CRIT-HISTORY` (NamedQuery, tenant, read, scenario): the SUPERSEDES walk from the current criteria.
- `CriteriaRepository.candidates(age_band: AgeBand, district: str, needs: Iterable[NeedCategory]) -> list[ServiceCriteria]` (port in application/ports/outbound/repositories.py, adapter Neo4jCriteriaRepository).

## RDF export (G13, DEC-198)

- `rdf_export.fragment_to_graph(fragment) -> rdflib.Graph` (tenant from the bound scope)
- `rdf_export.to_turtle(fragments) -> str` (tenant from the bound scope)
- `rdf_export.ontology_turtle() -> str`
- Module namespaces `FHIR`, `DIUCS`, `SKOS`, `PROV`.
- New dependency: `rdflib>=7.6.0` (backend/pyproject.toml, uv.lock). It is pinned by the lock file.

## Outbound message senders (I10, DEC-199)

- `SenderResolver` (port, `application/ports/outbound/sender_resolver.py`): `sms_for()` and `email_for()`, no tenant argument, each raising `ChannelUnavailable` when the bound tenant has no usable sender.
- `ChannelUnavailable(Exception)` (same module).
- `TenantDirectory.active_line(tenant_id) -> TenantLine | None` (port in `application/ports/outbound/tenants.py`; Neo4j in `graph_store/tenant_directory.py`; global statement `Q-TENANT-ACTIVE-LINE`, allowlisted in `queries.py` with its pinned hash and its text in `test_global_allowlist.py`).
- `TenantSenderResolver(directory, secrets, http, status_url)`, `status_callback_url(settings)` (`bootstrap/tenant_senders.py`).
- `CommunicationRepository.record_send_outcome(communication_id, *, status, provider_message_id, error_code) -> bool` (port in `application/ports/outbound/messaging.py`; Neo4j in `communication_repository.py`; query `Q-COMM-RECORD-OUTCOME` with a scenario).
- `OutboundMessage`, `parse_outbound(payload, *, message_id, tenant_id, sealer)`, `is_handled(communication)`, `SmsMessageSender(senders, sealer)`, `EmailMessageSender(senders, sealer)`, `sender_runners(client, uow_factory, tenants, senders, sealer, observe)` (`adapters/inbound/workers/message_senders.py`).
- `build_runners(..., *, senders=None, sealer=None)` (`bootstrap/workers_main.py`).
- Constants: `MESSAGES_TOPIC`, `SEND_MESSAGE_EVENT`, `CONSUMER_SMS`, `CONSUMER_EMAIL`, `SMS_SUBSCRIPTION`, `EMAIL_SUBSCRIPTION`, `PUSH_SUBSCRIPTION`; reason codes `NO_CONTACT`, `NO_CHANNEL`, `REFUSED`, `SEND_FAILED`.
- `FixedSenderResolver(sms=, email=)` (test fake; keyed by the bound tenant).
- Config: `text-sender`, `email-sender`, `push-sender` on `messages.outbound` carry SQL rules.

## Postcode centroids and straight-line travel (I11, DEC-200)

- `Located(lat_lon, approximate)` (port, `application/ports/outbound/geo.py`; re-exported by the centroid module).
- `PostcodeLocator.locate(postcode) -> Located | None` (added to the port; `FixedPostcodeLocator.locate` and `CsvPostcodeLocator.locate` implement it).
- `partial_district(text) -> str | None` (`domain/rules/postcode.py`).
- `CsvPostcodeLocator(path)`: `centroid`, `district_centroid`, `locate`. `adapters/outbound/postcodes_local/centroids.py`.
- `haversine_km(a, b)`, `StraightLineTravelTime.estimate(origin, destination)`, and the constants `EARTH_RADIUS_KM`, `ROAD_DISTANCE_FACTOR`, `FAST_SPEED_KMH`, `SLOW_SPEED_KMH`, `ROUND_TO_MINUTES`, `MINIMUM_MINUTES`, `SOURCE` (`adapters/outbound/travel_time/straight_line.py`).
- `Settings.postcode_centroids_path` (env `DIUCS_POSTCODE_CENTROIDS_PATH`).
- `Container.postcodes`, `Container.travel`; `NoPostcodes` (`bootstrap/container.py`).
- `FixedTravelTime` default range in the test profile: 10 to 20 minutes, source "test fixed".

## OS Places geocoder and local terminology (I12, DEC-201)

- `TransientLookupError`, `LookupRejected` (`application/ports/outbound/lookups.py`).
- `OsPlacesGeocoder(client, api_key)` (`adapters/outbound/geocoder_os_places/os_places.py`), `parse_os_places(payload)`, constants `OS_PLACES_URL`, `OUTPUT_SRS`, `DATASET`, `REQUEST_TIMEOUT_SECONDS`.
- `LocalTerminology(base_dir)` (`adapters/outbound/terminology/local_terminology.py`); `HttpOdsLookup` (`ods_http.py`).
- `export(out_dir) -> list[Path]` (`backend/scripts/export_codesystems.py`); the committed files in `backend/terminology/codesystems/` (26) and `backend/terminology/ods_sample.json`.
- `NoGeocoder` (`bootstrap/container.py`); `Container.geocoder`, `Container.terminology`, `Container.http`.
- `Settings.os_places_api_key` (env `DIUCS_OS_PLACES_API_KEY`), `Settings.terminology_dir` (env `DIUCS_TERMINOLOGY_DIR`).

## Redis sessions, text codes and rate limits (I13, DEC-202)

- `CodeResendRefused` (`application/ports/outbound/identity.py`)
- `check_purpose` (`domain/rules/identity_policy.py`)
- `ReporterSession`, `SessionStore`, `RateLimiter` (`application/ports/outbound/identity.py`)
- `RedisSessionStore`, `RedisRateLimiter`, `new_session_id`, `encode_session`, `decode_session`, `SESSION_TTL` (`adapters/outbound/cache_redis/sessions.py`)
- `RedisCodeStore`, `encode_code`, `decode_code` (`adapters/outbound/cache_redis/code_store.py`)
- `tenant_prefix`, `millis` (`adapters/outbound/cache_redis/tenant_keys.py`)
- `Container.redis`, `Container.sessions`, `Container.codes`, `Container.rate_limiter` (`bootstrap/container.py`)
- `CODE_STORE_FACTORIES`, `code_store_harness` (`tests/contract/factories.py`, `conftest.py`)

## Routing travel time (I15, DEC-203)

- `RoutingTravelTime` (`adapters/outbound/travel_time/routing.py`), `estimate(origin, destination)`
- `HttpxRouteClient`, `RouteHttpClient` (`get_json(url, timeout) -> (status, body)`)
- `RoutingFailed`, `RoutingReplyMalformed`
- `range_from_duration(seconds, extract_date)`, `route_url(base_url, origin, destination)`, `duration_seconds(body)`
- `ROUTING_TIMEOUT`, `TRAFFIC_SPREAD`, `ROUND_UP_TO_MINUTES`, `ROUTE_CACHE_TTL`
- `Settings.routing_base_url`, `Settings.routing_timeout_s`, `Settings.routing_extract_date` (`bootstrap/settings.py`)

## Back-end telemetry (O01, DEC-204)

- diucs.application.tracing: Span, Tracer, NoopTracer, AttrValue, USECASE_OUTCOME, set_tracer, get_tracer, annotate_usecase, traced_use_case, format_traceparent
- diucs.adapters.outbound.telemetry.attributes: the span names, attribute keys, ALLOWED_KEYS, ALLOWED_PREFIXES, DENIED_FRAGMENTS, is_allowed_key
- diucs.adapters.outbound.telemetry.redaction: REDACTED, redact_text, redact_value, clean_attributes, RedactingLogFilter, install_log_redaction
- diucs.adapters.outbound.telemetry.otel: TelemetrySettings, AllowListSpanProcessor, OtelTracer, neo4j_span, record_query, query_observer, build_provider, configure_telemetry, instrument_fastapi
- diucs.adapters.outbound.telemetry.consumer: Observe, parent_context, consumer_observer
- diucs.bootstrap.telemetry: start_telemetry
- diucs.application.ports.outbound.event_bus.BusMessage: field traceparent (str or None)
- Settings: release (str, default "dev"), otlp_endpoint (str, default "")

## Browser telemetry (O02, DEC-205)

- lib/telemetry/trace.ts: TRACEPARENT_PATTERN, newTraceparent, beginInteraction, currentTraceId, setRequestObserver, withTraceparent
- lib/telemetry/events.ts: TELEMETRY_ENDPOINT, BATCH_SIZE, FLUSH_MS, CLICK_WINDOW_MS, ALLOWED_EVENTS, ALLOWED_ATTRIBUTES, Attributes, TelemetryInit, lengthBucket, routeTemplate, initTelemetry, stopTelemetry, track, trackPageView, noteRouteChange, flush
- app/api/bff/telemetry/route.ts: POST (204, 400, 401, 403, 413)

## Support access (O06, DEC-206)

- domain/rules/support.py: SUPPORT_CODE_VALID_FOR, SUPPORT_ACCESS_VALID_FOR, SUPPORT_CODE_SECRET, LEAD_ROLE_CODES, normalise_support_code, hash_support_code, code_window, access_window, support_code_usable, is_lead, may_open_support
- application/ports/outbound/support.py: SupportCodeRecord, SupportAccessRecord, SupportRepository
- adapters/outbound/graph_store/support_repository.py: Neo4jSupportRepository; statements Q-SUPPORT-SESSION-ENSURE, Q-SUPPORT-SESSION-EXISTS, Q-SUPPORT-SESSION-SHARED-BY, Q-SUPPORT-CODE-ADD, Q-SUPPORT-CODE-GET, Q-SUPPORT-CODES-STOP, Q-SUPPORT-ACCESSES-END, Q-SUPPORT-ACCESS-ADD, Q-SUPPORT-ACCESS-LIST
- adapters/outbound/graph_store/migrations_support.py: SUPPORT_MIGRATIONS (0045_support_session_id, 0046_support_code_hash), assembled in migrations.py
- application/ports/outbound/unit_of_work.py: UnitOfWork.support; adapters/outbound/graph_store/unit_of_work.py: DEFAULT_FACTORIES["support"]
- application/use_cases/support_access.py: CreateSupportCode, StopSharing, OpenSessionForSupport, ListMyAccesses, with their commands, results and AccessView

## Telemetry query (O07, DEC-207)

- Port (application/ports/outbound/telemetry_query.py): `TelemetryQuery`, `TimelineEvent`, `SpanRecord`, `SessionSummary`, `SessionFilters`, `TimelineKind`, `TelemetryUnavailable`, `AttributeCleaner`, `AttributeValue`; helpers `as_utc`, `check_session_id`, `check_trace_id`, `check_limit`, `MAX_SESSION_RESULTS`.
- Outbound (adapters/outbound/telemetry): `AzureMonitorTelemetryQuery`, `LogsTable`, `LogsQueryClient`, `RAW_LOOKBACK`; `result_attributes`; `SdkLogsQueryClient`; `TIMELINE_QUERY`, `SPANS_QUERY`, `SESSIONS_QUERY`.
- Testing (adapters/testing/fixture_telemetry.py): `FixtureTelemetryQuery(fixture_path, attributes)`.
- Container (bootstrap/container.py): field `telemetry`; `NoTelemetry`; `build(settings, *, secrets=None, telemetry_client=None)`; `build_for_tests(..., telemetry=None)`; `TELEMETRY_FIXTURE`.
- Settings: `telemetry_workspace_id` (env DIUCS_TELEMETRY_WORKSPACE_ID).
- Dependency: `azure-monitor-query` 2.0.0 (backend/pyproject.toml, backend/uv.lock).

## Synthetic journey checks (O09, DEC-208)

- Backend route: `POST /test/synthetic/prompt` (adapters/inbound/fhir_rest/routes_synthetic.py); `SyntheticHook`, `SyntheticLinkIssuer`.
- `create_app(container, synthetic=None)` (adapters/inbound/fhir_rest/app.py) sets `app.state.synthetic`.
- Settings: `synthetic_enabled`, `synthetic_hook_token`, `synthetic_tenant_id` (env DIUCS_SYNTHETIC_*).
- Frontend: `syntheticTarget`, `sameOrigin`, `SyntheticTarget` (frontend/test/synthetic/guard.ts); Playwright project `synthetic`; spec frontend/e2e/synthetic/reporter-loop.spec.ts.
- Workflow: .github/workflows/synthetic.yml; variables SYNTHETIC_BASE_URL, SYNTHETIC_BACKEND_URL, SYNTHETIC_ALLOWED_HOSTS; secrets SYNTHETIC_HOOK_TOKEN, SYNTHETIC_STAFF_STORAGE_STATE.

## Alert repositories (P17, DEC-209)

- `AlertSubscriptionRepository`, `AlertRepository` (Protocols, `application/ports/outbound/repositories.py`)
- `UnitOfWork.alert_subscriptions`, `UnitOfWork.alerts` (`application/ports/outbound/unit_of_work.py`, factories in `graph_store/unit_of_work.py`)
- `AlertSubscription`, `AlertRecord`, `ALERT_STATUSES` (`domain/model/alerts.py`)
- `Neo4jAlertSubscriptionRepository(tx)`, `Neo4jAlertRepository(tx, store)`, `alert_to_fhir`, `alert_from_fhir`, `subscription_to_props`, `subscription_from_props` (`graph_store/alert_repository.py`)
- Statements `Q-ALERT-SUB-LOCK`, `Q-ALERT-SUB-SAVE`, `Q-ALERT-SUB-FOR`, `Q-ALERT-SUB-KIND`, `Q-ALERT-SET-STATUS`, `Q-ALERT-OPEN-FOR-OWNER`
- Extensions `alertKind`, `escalationDueAt`, `acknowledgedAt` (`graph_store/extensions.py`)

## Staff sign-in and role guard (W09, DEC-210)

- `lib/auth/access.ts`: `rolesFor(pathname) -> readonly Role[] | null` (null: not guarded; `[]`: guarded for nobody), `canAccess(role, pathname)`, `roleHome(role)`, `isSamePathOnly(value)`. The one route table the proxy and the sign-in share.
- `lib/auth/staff.ts`: `StaffRole`, `mapRoles(claim, { allowSupport? }) -> StaffRole | null`, `mintBackendToken({ oid, role, tenantId }, now?) -> Promise<string>` (HS256, claims `sub`, `role`, `services: []`, `tid` = the DIUCS tenant id, `iat`, `exp` +8 h; secret `BACKEND_JWT_SECRET`, base64, at least 32 bytes), `backendTokenExpiresAt(now)`, `BACKEND_TOKEN_LIFETIME_SECONDS`, `safeNext(next, role)`, `isTenantId`, `isGuid`.
- `lib/auth/oidc.ts`: `loadEntraConfig(env?) -> EntraConfig`, `Binding { directoryId, tenantId, platform }`, `bindingFor`, `newTransaction`, `authorizeUrl`, `exchangeCode`, `verifyIdToken(config, idToken, nonce, now?) -> Identity { oid, directoryId, roles, binding }`, `SignInRefused(reason)`, `REFUSALS`, `resetKeyCache`. `lib/auth/flow.ts`: `startSignIn(request)`, `completeSignIn(request)`, `TRANSACTION_COOKIE` (`diucs_oidc`). `lib/auth/session.ts` also exports `sessionSecretKey`.
- Routes: `POST /api/bff/auth/entra/start` (form field `next` only), `GET /api/bff/auth/entra/callback`. Pages: `/sign-in` (`?role=clinical` note, `?error=no-access|failed`, `?next=`), `/forbidden`. `proxy.ts` (not `middleware.ts`, Next 16) guards `/advisor`, `/clinical`, `/lead`, `/owner`, `/planning`, `/console`.
- Settings: `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, `ENTRA_AUTHORITY_HOST` (default `https://login.microsoftonline.com`; https in production), `DIUCS_PUBLIC_URL` (scheme and host), `DIUCS_ENTRA_BINDINGS` (JSON `[{ directoryId, tenantId, platform? }]`), `BACKEND_JWT_SECRET`, `SESSION_SECRET`. `ENTRA_TENANT_ID` is not used.
- Tests: `test/oidc/{fake-entra,constants,harness}.ts` (the recording fake of Entra; `FakeEntra.create`, `authorize`, `token`, `keys`, `recorded`, `Tamper`), `test/msw/handlers/entra.ts` (`entraHandlers(fake)`), `e2e/support/oidc.ts` (the fake as an HTTP server on port 4011; personas by the `fake_user` cookie).
- `lib/auth/oidc.ts`: `entraAuthorityOrigin(env?) -> string | null`. `lib/security/csp.ts`: `buildCsp(nonce, dev, { formActionOrigins? })`, `CspOptions`.

## Clinical request repository (P18, DEC-220)

- `ClinicalRequestRepository` (Protocol, `application/ports/outbound/repositories.py`)
- `UnitOfWork.clinical_requests` (`application/ports/outbound/unit_of_work.py`, factory in `graph_store/unit_of_work.py`)
- `ClinicalAdvice`, `ClinicalRequestRecord` (`domain/model/clinical.py`)
- `Neo4jClinicalRequestRepository(tx, store)`, `clinical_record_to_fhir`, `clinical_record_from_fhir`, `clinical_record_to_props` (`graph_store/clinical_request_repository.py`)
- Statements `Q-CLIN-WAITING`, `Q-CLIN-TAKEN-BY`, `Q-CLIN-SET-PROPS`, `Q-CLIN-PROPS`
- Extensions `why`, `snapshotRef`, `takenAt` (`graph_store/extensions.py`)

## Push subscription repository (P19, DEC-221)

- `PushSubscription`, `PushSubscriptionRepository` (`application/ports/outbound/messaging.py`)
- `UnitOfWork.push_subscriptions` (`application/ports/outbound/unit_of_work.py`, factory in `graph_store/unit_of_work.py`)
- `Neo4jPushSubscriptionRepository(tx)`, `checked_subscription`, `subscription_json`, `subscription_from_json` (`graph_store/push_subscription_repository.py`)
- Statements `Q-PUSH-SAVE`, `Q-PUSH-FOR`, `Q-PUSH-DELETE`

## Service move and protected text stores (P20, DEC-222)

- `ServiceMoveRepository` (`application/ports/outbound/repositories.py`)
- `ProtectedTextStore` (`application/ports/outbound/protected_text.py`)
- `UnitOfWork.service_moves`, `UnitOfWork.protected_text` (`application/ports/outbound/unit_of_work.py`; factories in `graph_store/unit_of_work.py`)
- `ServiceMove` (`domain/model/service_move.py`)
- `Neo4jServiceMoveRepository(tx)` (`graph_store/service_move_repository.py`)
- `Neo4jProtectedTextStore(tx)`, `new_handle`, `checked_text`, `KINDS`, `MAX_LENGTH` (`graph_store/protected_text_store.py`)
- Statements `Q-MOVE-LOCK-SERVICE`, `Q-MOVE-OPEN-FOR`, `Q-MOVE-GET`, `Q-MOVE-ADD`, `Q-MOVE-SAVE`, `Q-PROT-PUT`, `Q-PROT-GET`

## Profile validation and $validate (R14, DEC-223)

- `diucs.application.ports.outbound.terminology.profile_url(name) -> str`
- `diucs.adapters.outbound.fhir_validator.validator.ProfileValidator` (implements FhirValidator), `PROFILES`, `PROFILE_NAMES`
- `diucs.adapters.inbound.fhir_rest.validation`: `ProfileRejected`, `issue_outcome`, `json_body`, `validated_body(profile, element)`
- `diucs.adapters.inbound.fhir_rest.routes_validate`: route `POST /fhir/{resource_type}/$validate` (query `profile`), `register_profiles`
- `diucs.adapters.inbound.fhir_rest.capability.add_supported_profile(resource_type, url)`
- `ApiContainer.validator` (app.py) and `Container.validator` (bootstrap), set to ProfileValidator in build() and build_for_tests()

## Wall screen pairing endpoints (R15, DEC-224)

- `routes_screens.router`, the three routes of contracts.md line 235 (`POST /screens/pairing`, `GET /screens/pairing/{pairing_id}` with header `X-Screen-Secret`, `POST /screens`), registered in `fhir_rest/app.py` outside `/fhir`.
- `ConnectScreenBody` (pydantic, `extra="forbid"`): `code: str`, `name: str`, `location: str | None = None`, `boardScope: Literal["tenant", "network"] = "tenant"`, in `routes_screens.py`.
- Module constants in `routes_screens.py`: `START_PATH`, `SCREENS_PATH`, `SECRET_HEADER`, `REFUSED_TEXT`, `RATE_LIMITED_TEXT`, `UNAVAILABLE_TEXT`, `RETRY_AFTER_UNAVAILABLE_SECONDS`, `ADDRESS_STARTS`, `ADDRESS_REFUSED_CLAIMS`.
- `Container` fields `cache: Cache` and `rng: random.Random`; `build_for_tests(..., cache=, rng=)`; the constant `TEST_RNG_SEED` in `bootstrap/container.py`.
- `ClaimPairingResult` is unchanged (it already has `expired`).

## Pathways Dx lookup (R16, DEC-225)

- `diucs.domain.rules.code_search`: `MIN_SEARCH_LENGTH` (2), `search_codes(entries, text, limit)`
- `Terminology.search_pathways_dx(text, limit=20) -> list[tuple[str, str]]` (application/ports/outbound/terminology.py)
- `FixedTerminology(ods, displays, pathways_dx=())` and its `search_pathways_dx` (adapters/testing/fixed_terminology.py)
- `diucs.adapters.outbound.terminology.pathways_dx_file`: `load_pathways_dx(path)`, `PathwaysDxFile(path)`
- `diucs.adapters.inbound.fhir_rest.routes_terminology`: route `GET /terminology/pathways-dx` (query `q`), `RESULT_LIMIT`, `TOO_SHORT`
- `ApiContainer.terminology` (adapters/inbound/fhir_rest/app.py)
- `LocalTerminology(base_dir, pathways_dx_file)` gains `search_pathways_dx` (adapters/outbound/terminology/local_terminology.py); `build()` passes `settings.pathways_dx_file`
- Setting `pathways_dx_file` (bootstrap/settings.py), env `DIUCS_PATHWAYS_DX_FILE`
- `backend/data/pathways_dx_sample.json`

## Security headers and CSP (S01, DEC-226)

- `lib/security/csp.ts`: `buildCsp(nonce: string, dev: boolean): string`, `securityHeaders(): Record<string, string>`.
- `proxy.ts`: `proxy(request: NextRequest): NextResponse`, `config.matcher`.
- `app/layout.tsx`: `export const dynamic = 'force-dynamic'`.

## Criteria and flag statements (TEN-012, DEC-227)

- `diucs.adapters.outbound.graph_store.criteria_scenarios` (new module): `CRITERIA_SCENARIOS` and the scenarios it names.
- `diucs.adapters.outbound.graph_store.flag_scenarios` (new module): `FLAG_SCENARIOS` and the scenarios it names.

## Outbox, replay and processed statements (TEN-016, DEC-230)

- `Neo4jIdempotencyStore(tx: Tx)`: accepts the scoped transaction (`ScopedTx`) of a unit of work.
- `test_idempotency_queries.py`: the pinned shape of the eight converted statements.

## Audit chain per scope (TEN-017, DEC-231)

- `genesis_hash_for(scope: str) -> str` and `GENESIS_LABEL` in `application/ports/outbound/audit.py`.
- `Neo4jAuditLog(tx: Tx, ids, clock)`: takes the scoped transaction; `verify_chain` reads the bound scope.
- `Container.startup()`: binds each active tenant in turn for `ensure_audit_head`.

## Tenant-scoped cache names (TEN-019, DEC-232)

- `application/ports/outbound/cache.py`: `ScopedNames(segment)` with `key`, `lock`, `fence`, `channel`; `names_for(scope)`, `scoped_names()`, `scope_segment(scope)`; `Lock(name, fencing_token, scope)`; `CacheScopeMismatch`; `FAMILY_CACHE`, `FAMILY_LOCK`, `FAMILY_FENCE`, `FAMILY_CHANNEL`, `MAX_NAME_LENGTH`.
- `adapters/outbound/cache_redis/redis_cache.py`: `RedisCache(client)`, `RedisCache.from_url(url)`, `ROOT`.
- `adapters/testing/memory_cache.py`: `InMemoryCache.keys()`; `subscriber_count(channel)` reads the bound scope.
- `tests/support/redis.py`: `RUN_ID`, `RUN_PREFIX`, `run_tenant(label)`, `flush_tenant(client, tenant)`, `flush_run(client)`, `flush_prefix(client, prefix)` (the prefix must end with a colon).

## Tenant policy in the rules (TEN-021, DEC-233)

- `diucs.domain.rules.schedule`: `reply_by`, `ladder_times`, `due_times_on`, `next_due`, `current_due` gain an optional last parameter `policy: TenantPolicy = DEFAULT_POLICY`.
- `diucs.domain.rules.freshness.assess_freshness` and `diucs.domain.rules.status.compute_status` gain the same optional last parameter.
- `diucs.domain.rules.pressure.system_pressure` and `diucs.domain.rules.reply_policy.decide_capacity_reply` gain the same optional last parameter.
- the optional `policy` parameter on the nine functions above (DEC-133 item 4); no new names.

## Tenant wording in templates (TEN-022, DEC-234)

- `diucs.domain.messages.templates.render`: new fields `system_name` (I2), `referral_system_name` (B1, B2), `coordination_team_name` (K4) and `confirm_limit` (C6). Each is required and has no default.
- `diucs.domain.messages.catalogue`: `TENANT_TEXT_FIELD_NAMES`, `TENANT_TEXT_FIELDS`, `tenant_text_fields_for(message_id)`.
- `diucs.domain.messages.privacy_guard`: `DEPLOYMENT_TERMS`, `find_deployment_terms(text)`; `FORBIDDEN_FIELDS` extended by six names.
- one line each for the four template fields and `confirm_limit` (DEC-133 item 4).

## Network domain model and rules (TEN-036, DEC-235)

- `domain/model/network.py`: `NETWORK_ID_PREFIX`, `NETWORK_ID_PATTERN`, `RECORD_ID_PATTERN`, `ACCOUNT_REF_PATTERN`, `AGREEMENT_REFERENCE_PATTERN`, `NAME_MAX_LENGTH`
- `domain/model/network.py` enums: `GrantScope`, `GrantPurpose`, `GrantStatus`, `GrantApprover`, `GrantEndReason`, `NetworkStatus`, `MembershipStatus`, `MembershipRole`, `MembershipEndReason`, `ListingStatus`, `ListingReason`, `DirectorySource`
- `domain/model/network.py` records: `Agreement`, `Approval`, `Network`, `NetworkMembership`, `Grant`, `Listing`
- `domain/model/network.py` functions: `check_tenant_field(value, field)`, `check_network_id(value, field="network_id")`, `transition_network`, `activate_network`, `owner_membership`, `invite_member`, `accept_membership`, `end_membership`, `was_member_at`, `is_agreement_behind`
- `domain/rules/grant.py`: `transition_grant`, `propose_grant`, `approve_grant`, `decline_grant`, `end_grant`, `lapse_grant`, `lapse_grants_for_member`, `revise_grant`, `supersede_grant`, `is_effective`, `was_effective_at`, `effective_grant`, `may_project`, `end_reason`
- `domain/rules/listing.py`: `ListingPresentation`, `transition_listing`, `request_listing`, `admit_listing`, `decline_listing`, `suspend_listing`, `reinstate_listing`, `withdraw_listing`, `withdraw_for_leave`, `listing_presentation`, `visible_scopes`, `shows_on_board`, `may_project_listing`

## Network screens specification (TEN-063, DEC-236)

- Components named in the specification (built by TEN-069 to TEN-072, TEN-080 to TEN-082): `ScopeHeader`, `ScopeSwitch`, `OrgLabel`, `NetworkBoard`, `NetworkBoardList`, `NetworkServices`, `NetworkServiceDetail`, `NetworkHistory`, `NetworkWeek`, `NetworkNotAvailable`, `NetworkPaused`, `NetworkMembershipEnded`, `NetworkSourceStopped`, `NetworkSourceDelayed`, `NetworkOffline`, `NetworkWallFallback`, `ScreenList`, `ScreenBoardChoice`, `ScreenClaim`, `ScreenUnpair`, `WallNetwork`, `ScreenDisconnected`, `NetworkMembers`, `NetworkMemberAdd`, `NetworkMemberEnd`, `NetworkAgreement`, `NetworkGrants`, `NetworkListings`, `NetworkHealth`, `NetworkAdminHistory`, `SharingOverview`, `SharingFields`, `SharingEnd`, `SharingLeave`, `SharingAgreement`, `SharingHistory`, `AllowlistFields`.
- Routes named in the specification: `/network/board`, `/network/services`, `/network/services/[id]`, `/network/history`, `/network/week`, `/network-admin`, `/network-admin/grants`, `/network-admin/listings`, `/admin/sharing`, `/lead/screens`.
- Element ids: the 63 new ids and 5 reused ids of section 10.
- Test: `frontend/test/docs/network-ui-spec.test.ts` (12 tests, documentation consistency only).

## OpenCase and UpdateCase (U11, DEC-237)

- `diucs.application.use_cases.open_case`: `OpenCaseCommand`, `OpenCaseResult`, `OpenCase`, `UpdateCaseCommand`, `UpdateCaseResult`, `UpdateCase`, `OPEN_CASE`, `UPDATE_CASE`, `ALLOWED_ROLES`, `check_role`, `tenant_scope`, `district_for`, `new_open_case`, `missing_fields`, `apply_update`, `snapshot_of`, `free_reference`, `replay_key`, `open_fingerprint`, `update_fingerprint`.

## SetupServiceByLead (U15, DEC-238)

- `application/use_cases/setup_service_by_lead.py`: `SetupServiceCommand`, `SetupServiceResult`, `SetupServiceByLead(uow_factory, clock, ids, idempotency, phone_hasher)` with `execute`
- Helpers in the same module: `ReporterContact`, `check_may_set_up`, `check_role_name`, `reporter_contact`, `international`, `build_profile`, `build_criteria`, `first_prompt_at`, `command_fingerprint`, `setup_snapshot`
- `domain/events.py`: `ServiceActivated(service_id, at)` (`event_type` "ServiceActivated", topic `registration.events`, added to the `DomainEvent` union and the decoder map)
- Role codes used: reporter role `PractitionerRoleCode.DUTY_MANAGER`; owner role `PractitionerRoleCode.CRITERIA_OWNER`

## ChangeReporterNumber (U16, DEC-239)

- `diucs.application.use_cases.change_reporter_number`: `CoverDuration`, `ChangeReporterNumberCommand`, `ChangeReporterNumberResult`, `ChangeReporterNumber`, `cover_until`, `effective_reporter_practitioner_id`, `check_new_mobile`, `command_key`.

## RequestBooking (U17, DEC-240)

- `diucs.application.use_cases.request_booking`: `LinkBaseUrlFor = Callable[[ScopeId], str]`, `RequestBookingCommand`, `RequestBookingResult`, `RequestBooking(uow_factory, idempotency, link_tokens, clock, ids, rng, query_board, *, link_base_url_for: LinkBaseUrlFor)`, `urgency_wording`, `need_text`, `message_for_channel`, `command_key`, `BOOKING_PURPOSE` (`booking-request`).

## Scope list (U23, DEC-241)

- `diucs.application.use_cases.scope_list`: `ScopeRow`, `AddScopeEntryCommand`, `AddScopeEntryResult`, `AddScopeEntry(uow_factory, idempotency, ids, clock)`, `SetScopeFlagCommand`, `SetScopeFlagResult`, `SetScopeFlag(uow_factory, idempotency, clock)`, `ListScope(uow_factory).execute(actor)`, `require_lead`, `check_reason`, `same_name`, `london_date`, `scope_sort_key`.

## Text codes (U25, DEC-242)

- `diucs.application.use_cases.text_code`: `RequestTextCodeCommand`, `RequestTextCodeResult`, `VerifyTextCodeCommand`, `VerifyTextCodeResult`, `RequestTextCode(code_store, phone_hasher, uow_factory, secret_store, sealer, ids, clock, rng)` (the spec's `code_sender` is replaced by `sealer` and `ids`: the send is an outbox event), `VerifyTextCode(code_store, phone_hasher, uow_factory, secret_store, clock)`, `check_purpose`, `code_key`, `new_code`, `code_hash`, `cooldown_seconds`, `verify_fields`, `CODE_HMAC_SECRET` (`code-hmac`), `INVITATION_PURPOSE` (`invite`), `PURPOSES`, `CODES_TOPIC` (`codes.dispatch`), `SEND_CODE` (`SendCode`), `DISCARD_CODE` (`DiscardCode`).
- `LinkTokenRepository.open_for_phone(purpose, phone_hash, now) -> LinkTokenRecord | None` (tokens.py, Neo4jLinkTokenRepository).

## Registration drafting (U26, DEC-243)

- `OrganisationStep`, `LocationStep`, `ServiceStep`, `ReportingStep`, `ApiStep`, `RegistrationDraft`, `FieldError` (`application/use_cases/registration_draft.py`)
- `validate_step(step, *, fixed_site=None)`, `is_full_uk_phone(text)`, `encode_step(step)`, `decode_step(kind, values)`, `read_draft(registration)`
- `SaveRegistrationStep(uow_factory, ids, clock)`, `SaveRegistrationStepCommand(idempotency_key, actor, registration_id, step)`, `SaveStepResult(errors, status, replayed)`
- `SubmitRegistration(uow_factory, ids, clock)`, `SubmitRegistrationCommand(idempotency_key, actor, registration_id)`, `SubmitResult(status, errors, replayed)`

## Criteria change and approval (U30, DEC-244)

- `CriteriaValues`, `ChangeCriteria`, `ChangeCriteriaCommand`, `ChangeCriteriaResult`, `ApproveCriteria`, `ApproveCriteriaCommand`, `ApproveCriteriaResult`, `ConfirmCriteria`, `ConfirmCriteriaCommand`, `ConfirmCriteriaResult`, `CriteriaHistory`, `CriteriaHistoryQuery`, `CriteriaVersionView` (`application/use_cases/criteria.py`)
- `pending_version`, `check_may_change`, `check_may_approve`, `approved_versions`, `confirmed_review_by` (pure, same module)
- `ServiceCriteria.review_months` (`domain/model/criteria.py`); the `reviewMonths` element (`adapters/outbound/graph_store/criteria_repository.py`)

## Week summary (U35, DEC-245)

- `Measure(value, hidden, label)`, `WeekSummary`, `GetWeekSummary(uow_factory, settings, clock)`, `GetWeekSummaryCommand(actor, week_start)`, `WeekSummarySettings` (`application/use_cases/week_summary.py`)
- Pure: `london_week`, `count_measure`, `percent_measure`, `median_measure`, `on_time_updates`, `time_back_text`, `check_may_read`
- `PromptDue(service_id, due_at)` and `CommunicationRepository.prompts_due_between` (`application/ports/outbound/messaging.py`)
- `CaseRepository.opened_between`, `CapacityRepository.reports_between`, `BookingRepository.confirmed_between` (`application/ports/outbound/repositories.py`)
- Statements `Q-CASE-OPENED-BETWEEN`, `Q-CAP-BETWEEN`, `Q-BOOK-CONFIRMED-BETWEEN`, `Q-COMM-PROMPTS-DUE-BETWEEN`; scenarios in `adapters/outbound/graph_store/week_scenarios.py`
- `Settings.minutes_per_avoided_call` (`bootstrap/settings.py`)
- Test support: `tests/support/seed.py` (record builders for the week-summary tests)

## Resolving report flags (U39, DEC-246)

- `ReportFlagView`, `ListReportFlagsQuery`, `ListReportFlags`, `ResolveReportFlagCommand`, `ResolveReportFlagResult`, `ResolveReportFlag(uow_factory, report_capacity, clock)` (`application/use_cases/resolve_report_flag.py`)
- Pure: `check_lead`, `resolved_status`, `check_resolution`, `sequence_of`, `describe_flag`
- `FlagRepository.report_flag(flag_id)` (`application/ports/outbound/repositories.py`; adapter `flag_repository.py`, via `Q-FLAG-REPORT-GET`)
- `ReportFlag.resolved_by` (`domain/model/flags.py`)
