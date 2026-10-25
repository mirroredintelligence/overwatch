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
`rules/tokens.py` (D26): `new_link_token(rng: secrets-like) -> str` (>=128 bits, urlsafe); `hash_token(token, secret: bytes) -> str` (HMAC-SHA256 hex); `LinkTokenRecord(token_hash, purpose: str, about_id: str, phone_hash: str | None, expires_at, used_at: datetime | None)`; `check_link(record, now) -> LinkCheck` (ok, expired, used); `new_pairing_code(rng) -> str` ("482913"), `format_pairing_code(code) -> "482 913"`; `new_support_code(rng) -> str` ("K7R4-92QX"). Also (D26): `pairing_code_expired(issued_at, now) -> bool`, `PAIRING_CODE_VALID_FOR` (10 minutes), `SUPPORT_CODE_ALPHABET` (31 characters), `LINK_TOKEN_BYTES` (16), `LinkCheck` (StrEnum: `ok`, `expired`, `used`). Pairing codes draw one digit per call with bound 10 (DEC-045).
`rules/identity_policy.py` (D27): `CODE_VALID_FOR = 10 min`, `CODE_MAX_TRIES = 5`, `CODE_RESEND_AFTER = 60 s`, `PIN_MAX_TRIES = 5`, `REVERIFY_EVERY = timedelta(days=30)`; `validate_pin_format(pin) -> None`; `code_attempt(state, entered_ok: bool, now) -> CodeState`; `pin_attempt(state, ok, now) -> PinState`; `needs_reverification(last_verified_at, now, device_known: bool) -> bool`.
`rules/multi_service.py` (D28): `GROUP_WINDOW = 10 min` [ASSUMED] (domain-rules 2.4, owner-pending), `MAX_SERVICES_PER_PHONE = 3`; `GroupedItem(service_id: str, name: str, due: datetime, letter: str | None)`; `PromptGroup(items: tuple[GroupedItem, ...], due: datetime, reply_by: datetime)`; `MAX_LETTERED_ITEMS = 26` (from the D28 prompt, not a rule-book value); `group_due(due: Sequence[tuple[str, str, datetime]]) -> list[PromptGroup]` (service_id, name, due; DEC-048 item 1); `letters_for(names: Sequence[str]) -> dict[str, str]`; `phone_overloaded(count: int) -> bool`.

## Application (created in S2 onward)

`application/work.py` (P08): `WorkKind` StrEnum: prompt-due, reminder, phone-task, escalate-to-lead, booking-phone-prompt, booking-expire, criteria-review-reminder, alert-escalate, clinical-return, reverify; `ScheduledWork(id, kind: WorkKind, due_at, about_id: str, sequence_number: int | None, status: str)`.

Outbound ports (file → Protocols):
- `repositories.py`: `ServiceRepository` (get, list_active, save), `CapacityRepository` (add, latest, latest_for_services, reports_since) [P01]; `BookingRepository` (add, get, get_by_reference, save, open_for_service, open_for_services, confirmed_since) and `CaseRepository` (add, get, get_by_reference, save) [P02]; `PersonRepository` (get_practitioner, find_by_phone_hash, roles_for_practitioner, services_for_phone_hash, reporter_roles_for_service, save_practitioner, save_role) [P03]; `CriteriaRepository` (current_for_service, current_for_services, get, add, save, history), `RegistrationRepository` (add, get, save, list_by_status), `ScopeListRepository` (entries, get_entry, save_entry), `FlagRepository` (add_report_flag, open_report_flags, save_report_flag, service_flags, set_service_flag) [P04].  P01 additions (DEC-054): `CapacityRepository.last_report_times() -> dict[str, datetime | None]`; `Neo4jServiceRepository(tx, store)` and `Neo4jCapacityRepository(tx, store)` take the G05 `ResourceStore`; `codeable_to_fhir(member)` and `codeable_from_fhir(concept, enum_cls, field)` in `service_repository.py` are the shared CodeableConcept helpers; extensions `measure`, `unitLabel`, `channel` are registered.
- `audit.py` (P05): `AuditEntry(action: str, use_case: str, actor: Actor, entity_ids: tuple[str, ...], snapshot: dict | None, at: datetime)`; `AuditRecord(id, entry, chain_hash, previous_hash)`; `AuditLog` (append, records, verify_chain). No update or delete methods.
- `outbox.py` + `unit_of_work.py` (P06): `OutboxMessage(id, topic: str, event_type: str, payload: dict, created_at, status="pending", attempts=0, session_id: str | None = None)`; `Outbox` (add, pending, mark_published, mark_failed); `UnitOfWork` async context manager with attributes `services, capacity, bookings, cases, people, criteria, registrations, scope, flags, communications, link_tokens, scheduled_work, audit, outbox` and `async commit()` / `async rollback()`; `UnitOfWorkFactory = Callable[[], UnitOfWork]`. Use cases write the change, the audit entry and outbox messages inside one `async with uow_factory() as uow: ...; await uow.commit()`.
- `messaging.py` (P07): `SmsSender.send(to: str, text: str, message_id: str) -> SendReceipt`; `EmailSender.send(to, subject, text, html) -> SendReceipt`; `PushSender.send(subscription: dict, title, body, url) -> SendReceipt`; `SendReceipt(provider_message_id, accepted: bool)`; `Communication(id, message_id: MessageId, channel, recipient_role_id, about_id, payload_text, sent_at, delivery_status, provider_message_id, in_response_to: str | None)`; `CommunicationRepository` (add, get, by_provider_id, set_delivery_status, latest_prompt_for_phone).
- `event_bus.py` (P08): `BusMessage(id, topic, event_type, payload, session_id=None)`; `EventBus.publish(message)`, `EventBus.schedule(queue: str, message, enqueue_at) -> int`, `EventBus.cancel(queue, sequence_number)`; `ScheduledWorkRepository` (add, get, for_about, save). Topic and queue names exactly as `docs/spec/architecture.md`: `inbound.replies`, `inbound.receipts`, `scheduled.work`, `capacity.events`, `booking.events`, `registration.events`, `criteria.events`, `alerts.events`, `messages.outbound`.
- `cache.py` (P09): `Cache` (get, set(key, value, ttl), delete, publish(channel, message), subscribe(channel) -> AsyncIterator, acquire_lock(name, ttl) -> Lock | None, release_lock(lock)); `Lock(name, fencing_token: int)`. Channel `board.updates`.
- `tokens.py` + `identity.py` (P10): `LinkTokenRepository` (add, get_by_hash, mark_used); `LinkTokenService(repo, secret_store, clock)` with `issue(purpose, about_id, phone_hash, expires_at) -> str`, `resolve(token) -> LinkTokenRecord | None`, `burn(token)`; `SecretStore.get(name) -> bytes`; `PhoneHasher.hash(number) -> str`; `ContactStore` (protected numbers/emails: put_phone, get_phone, put_email, get_email); `CodeSender.send_code(phone) -> None`, `CodeStore`; `PinStore` (set_pin, verify_pin, attempts, lock); `DeviceRegistry`.
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
- Session: `lib/auth/session.ts` exposes `getSession(): Promise<Session | null>`, `Session { role, services, sub, device? , backendToken }`; CSRF via `lib/auth/csrf.ts` `issueCsrf()`, `checkCsrf(request)` (W02).
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
| Events `PhoneTaskRaised` (`capacity.events`), `ReportEscalated` (`alerts.events`) | `domain/events.py` | U06 |
| Event `ReportFlagged` | `domain/events.py` | U07 |
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
| `Communication.message_id` is `str`; `latest_prompt_for_phone` takes role ids | `application/ports/outbound/messaging.py` | P07 |
| `IdempotencyStore` (`get`, `put`): command replay, backed by `Neo4jIdempotencyStore` | `application/idempotency.py`, `adapters/outbound/graph_store/idempotency_store.py` | P15 |
| `ReportCapacityCommand.flag` | `application/use_cases/report_capacity.py` | U01 |
| `schedule_work(uow, ids, *, kind, about_id, due_at, now)`, `cancel_work(uow, work, now)` | `application/scheduling.py` | U03 |
| Outbox event types `ScheduleWork` (payload `work_id, kind, about_id, enqueue_at`) and `CancelWork` (payload `work_id`) on topic `scheduled.work`; the relay delivers `ScheduledWorkDue` (payload `work_id, kind, about_id`) | `application/scheduling.py`, relay in I03 | U03, I03 |
| `ScheduledWork.status` values `scheduled`, `done`, `cancelled` | `application/work.py` | P08 |
| `WorkKind` value `not-updated-check` | `application/work.py` | U34 |
| `DeviceRegistry.get`, `DeviceRegistry.save`; `ClaimPairingResult.status` may be `expired` | `application/ports/outbound/identity.py`, `use_cases/pair_wall_screen.py` | U10, R15 |
| `DeviceRegistry.revoke_all`, device status `pending-callback` | `application/ports/outbound/identity.py` | U37 |
| `ServicePositions` port | `application/ports/outbound/geo.py` | U12 |
| `Terminology.search_pathways_dx(text, limit)` | `application/ports/outbound/terminology.py` | R16 |
| `ProcessedMessages` port and `UnitOfWork.processed`: consumer idempotency | `application/ports/outbound/idempotency.py` | G08 |
| `DeliveryUpdate` | `application/ports/outbound/messaging.py` | I06 (or P07) |
| `PushSubscriptionRepository` | `application/ports/outbound/messaging.py` | I14 |
| `AlertSubscriptionRepository` and `UnitOfWork.alert_subscriptions` | `application/ports/outbound/repositories.py` | U33 |
| `AlertRepository` | `application/ports/outbound/repositories.py` | U34 |
| `CaseRepository.opened_between` and other date-range reads | `application/ports/outbound/repositories.py` | U35 |
| `ServiceMove` store | `application/ports/outbound/repositories.py` | U38 |
| `ClinicalRequestRepository`, `ProtectedTextStore` | `application/ports/outbound/repositories.py` | U40 (U41 carries the same spec in case it runs first) |
| `AuditLog.records_for` | `application/ports/outbound/audit.py` | U42 |
| `SupportRepository` | `application/ports/outbound/support.py` | O06 |
| `SequentialIds` fake | `adapters/testing/` | F06 |

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

## Registration approval (DEC-032)
- The pure gate `domain/rules/registration.py` takes booleans; it does not know who the approver is.
- The use case that approves a registration (U29) must refuse when the approver is the requester. This is the only place that check lives. Any other caller that approves a registration must make the same check.

