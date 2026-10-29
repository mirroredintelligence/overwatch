# DIUCS capacity: architecture and data flows
2026-10-23 · @Robert Smith
## At a glance
[embed: hexagonal architecture - adapters, ports and core]
Every inbound adapter calls a use case through a driving port. Every outbound adapter implements a driven port. The Next.js app talks to the FHIR REST adapter only.
## Platform decisions: Azure, Neo4j only
These decisions come from you and **override anything earlier in this document that mentions PostgreSQL or a separate scheduler store**. Neo4j is the only database. Redis is a cache. Azure Service Bus carries messages and does the scheduling. Everything runs on Azure in a UK region.
| Concern | Where it lives now | How |
|---|---|---|
| System of record | Neo4j | FHIR resources as nodes and relationships, with the canonical JSON on each node |
| Audit and provenance | Neo4j | Append-only nodes with a hash chain. The repository exposes no update or delete. Where the Neo4j edition supports role-based write restrictions, enforce it there too. |
| Outbox | Neo4j | An `OutboxMessage` node written in the same transaction as the change. A relay publishes it to Service Bus, then marks it published. Delivery is at least once, so every consumer is idempotent on the message id. |
| Scheduling | Service Bus scheduled messages | Due prompts, reminders, the 5 and 10 minute booking timers, re-verification and criteria reviews are messages with a scheduled enqueue time. The sequence number is stored on the owning node so the message can be cancelled when it is no longer needed, for example when a booking is answered. Times are computed from London local rules and sent as UTC. |
| Link tokens | Neo4j, cached in Redis | A `LinkToken` node holds a hash, the prompt, the phone hash and the expiry. Redis caches the lookup. |
| Sessions, PIN attempt counters, rate limits | Redis | With a short time to live. Lost on restart means a person signs in again, which is acceptable. |
| Read-model cache | Redis | The board and exec views. Invalidated on `StatusChanged`, with a short time to live as a backstop. |
| Reference data | Redis | Code systems, value sets, service profiles |
| Idempotency keys | Redis, then Neo4j | A short-lived key stops webhook replays cheaply. A durable message-id check in Neo4j stops a second effect. |
| Live updates to open pages | Redis publish and subscribe | Ephemeral. A missed event is harmless because the page refetches. |
| Advisor and clinical presence | Redis | Heartbeat keys that expire |
| Distributed locks | Redis, with a fencing token | Only for single-flight jobs such as the outbox relay |
| Telemetry | Azure Monitor | See the observability document |

### Service Bus topics and queues
Service Bus earns its place for four things: durable scheduled messages without a scheduler database, retries and dead-lettering when a provider fails, duplicate detection on provider webhooks, and per-service ordering through sessions. Cost: one more service to run. A pilot could start with the queues only and add topics later.
| Name | Kind | Published by | Consumers | Notes |
|---|---|---|---|---|
| `inbound.replies` | Queue | Webhook adapter | Reply processor | The webhook acknowledges the provider at once and queues the text. Duplicate detection on the provider message id. |
| `inbound.receipts` | Queue | Webhook adapter | Delivery tracker | Delivery receipts update the Communication |
| `scheduled.work` | Queue | Use cases | Scheduler consumer | Scheduled messages: prompts, reminders, expiries, re-verification, reviews |
| `capacity.events` | Topic | Outbox relay | Board projector, alert evaluator, analytics aggregator | Session id is the service id, so one service's events arrive in order |
| `booking.events` | Topic | Outbox relay | Notifier, board projector, advisor stream, analytics | Filter on event type |
| `registration.events` | Topic | Outbox relay | Notifier, lead queue projector, analytics |  |
| `criteria.events` | Topic | Outbox relay | Notifier, flag maintainer |  |
| `alerts.events` | Topic | Alert evaluator | Notifier, escalation timer, analytics |  |
| `messages.outbound` | Topic | Use cases via the outbox | Text sender, email sender, push sender | Subscriptions filter on the channel. Each has a dead-letter queue and a retry policy. |

The dead-letter queues are watched, and a message there raises an alert. I have not checked the tier needed for private networking or the message size limits, so confirm with the platform team.
### Ports added by this decision
| Port | Purpose | Adapter | Test adapter |
|---|---|---|---|
| Cache | Get, set, expire, publish, subscribe, lock | Redis | In-memory dictionary |
| EventBus | Publish, subscribe, schedule, cancel | Service Bus | In-memory queue with a manual clock |
| TelemetryQuery | Read raw telemetry for the console | Azure Monitor | Fixed fixtures |

## Technology choices and versions
The front end is the Next.js 16 line with React 19.2. The back end is Python 3.14 in the pilot, behind a hexagonal core, speaking FHIR R4B. Versions below come from search results, not from the vendors' own pages, so confirm each with the package manager before pinning.
| Layer | Choice | Why and what to check |
|---|---|---|
| Front end | Next.js 16, App Router, React 19.2 | Next.js 16 shipped on 21 October 2025 and is the Active LTS line. Wikipedia lists 16.4.0 as stable on 7 October 2026. Next.js 15 reaches end of life on 21 October 2026, so do not start on 15. Next.js now publishes scheduled security releases, so plan a monthly upgrade slot. Minimum Node.js is 20.9, per the sources I found. |
| Language | TypeScript, strict | Types for FHIR R4B resources are generated or imported once and shared by the BFF and the pages. Verify which R4B types package is maintained. |
| Accessibility | React Aria Components or Radix primitives | Both give keyboard and screen-reader behaviour for dialogs, tabs and switches. My suggestion. |
| Back end language | Python 3.14 for the pilot | 3.14.8 is in bug-fix support. Python 3.15.0 was reported as released on 9 October 2026. Run 3.15 in CI, and move once every dependency ships wheels for it. |
| HTTP framework | FastAPI, as one inbound adapter | Async, typed, and it generates the OpenAPI document. It sits at the edge only. |
| FHIR models | fhir.resources, R4B sub-package | The package ships R4B 4.3.0 as a sub-package and is built on Pydantic v2. |
| Graph store | Neo4j, the only database, behind a port | Decided. Data, audit, outbox state, tokens and analytics aggregates are all Neo4j nodes. The port allows an in-memory fake for tests. Confirm the edition, the UK region on Azure, and the backup and security features. |
| Audit, outbox, scheduling | Neo4j nodes, and Service Bus scheduled messages | No PostgreSQL. Audit is append-only nodes with a hash chain. The outbox is nodes relayed to Service Bus. Prompts, reminders and expiries are scheduled messages. |
| SMS | Twilio, or GOV.UK Notify, behind one port | Same interface, so the choice is a configuration change. Ask each about data region and sub-processors. |
| Push | Web Push with VAPID keys | Works on iPhone only for an installed web app, on iOS 16.4 or later. |
| Email | SMTP or a transactional provider, behind a port | Role inboxes only. |
| Geocoding | OS Places API at registration, a local postcode centroid file for patients | Patient postcodes never leave the Trust's hosting. |
| Routing | A travel-time port. Engine to be chosen. | Open decision. Self-hosted routing on open map data, or a licensed service. |
| Observability | OpenTelemetry | Traces and metrics without patient data in attributes. |
| Hosting | UK region, containers | A hosting decision for the Trust. |

**Sources I searched, not opened:** Next.js on Wikipedia, Next.js 16 write-up, Next.js 15 end of life, Python 3.15 status, fhir.resources on PyPI.
## Hexagonal layout
The core has no I/O. Everything that touches the outside world is an adapter behind a port: HTTP, text messages, the clock, the id generator and the database alike. Dependencies point inwards only. Nothing imports an adapter except the composition root.
```
diucs/
  domain/                    pure Python, no framework imports
    model/                   entities and value objects (Service, Capacity, Window, Booking, Criteria)
    rules/                   status rules, freshness, booking state machine, reply parser
    events.py                domain events
  application/
    use_cases/               one class per use case, constructor-injected ports
    ports/
      inbound/               driving ports: the use case interfaces
      outbound/              driven ports: repositories, gateways, clock, ids
  adapters/
    inbound/
      fhir_rest/             FastAPI, FHIR R4B interactions and operations
      sms_webhook/           provider webhook for text replies
      link_pages/            token link pages for text and email
      scheduler/             due prompts, reminders, expiries
    outbound/
      graph_store/           graph database repositories
      audit_neo4j/        append-only audit, outbox
      sms_twilio/  sms_govuk_notify/
      email_smtp/
      push_webpush/
      cache_redis/  bus_servicebus/
      geocoder_os_places/  postcodes_local/
      travel_time/
      identity_otp/  pin_store/
      clock_system/  ids_uuid/  secrets/
      fhir_validator/  terminology/
    testing/                 in-memory fakes for every port
  bootstrap/                 settings and the composition root
```
### Driving ports (use cases)
ReportCapacity, ConfirmCapacity, RequestBooking, RespondToBooking, CancelBooking, WithdrawBooking, OpenCase, FilterOptions, RecordOutcome, RegisterService, ReviewRegistration, ChangeCriteria, ApproveCriteria, SubscribeAlert, AcknowledgeAlert, SuspendService, RemovePerson, ReportSafetyConcern, QueryBoard.
### Driven ports
| Port | Purpose | First adapter | Test adapter |
|---|---|---|---|
| ServiceRepository, CapacityRepository, BookingRepository, CaseRepository, PersonRepository | Read and write FHIR resources as graph nodes | Graph store | In-memory dictionaries |
| AuditLog | Append-only record of every decision and what was shown | Neo4j audit nodes with a hash chain | In-memory list |
| Outbox | Messages to send, written in the same transaction as the change | Neo4j outbox nodes, relayed to Service Bus | In-memory list |
| SmsSender, EmailSender, PushSender | Deliver a message, report delivery status | Twilio or GOV.UK Notify, SMTP, Web Push | Recording fakes |
| LinkTokenService | Make, check and burn single-use tokens | Signed, stored tokens | In-memory |
| IdentityVerifier, PinStore | Text code, PIN, device and session checks | OTP adapter, hashed PIN store | Fixed codes |
| Geocoder, TravelTime | Postcode to position, position to travel range | OS Places, local centroids, routing | Fixed tables |
| Terminology | Resolve codes and value sets | A terminology server or local files | Local files |
| FhirValidator | Validate resources against the profiles | A validator service or library | Pass-through |
| Scheduler | Run due work, exactly once | Service Bus scheduled messages | Manual tick |
| Clock, IdGenerator, SecretStore | Time, ids, secrets | System, UUID, secret manager | Fixed values |

### Rules the codebase enforces
- The domain imports nothing outside the standard library and the FHIR model types.
- A use case receives ports through its constructor. It never builds an adapter.
- An adapter implements a port and is the only code that knows its library.
- A test fails the build if an import crosses the arrows the wrong way.
- The same contract tests run against every adapter of a port, fake and real.
## Dependency injection and testing
Plain constructor injection and one composition root. No service locator, no global state, no framework container inside the core.
```
# bootstrap/container.py
@dataclass(frozen=True)
class Container:
    report_capacity: ReportCapacity
    request_booking: RequestBooking
    respond_to_booking: RespondToBooking
    # one field per driving port

def build(settings: Settings) -> Container:
    clock = SystemClock()
    ids = UuidGenerator()
    graph = GraphStore(settings.graph_url)
    audit = Neo4jAudit(graph)
    sms = TwilioSms(settings.sms) if settings.sms.provider == "twilio" else GovNotifySms(settings.sms)
    capacity = GraphCapacityRepository(graph, clock)
    return Container(
        report_capacity=ReportCapacity(capacity, audit, clock, ids),
        # ...
    )
```
- **Inbound adapters** receive a use case, for example the FHIR route gets `ReportCapacity`. They translate the request into a command and the result into a response.
- **FastAPI ****Depends** is used only in the inbound adapter, to hand it the use case from the container. It never reaches into the core.
- **Settings** come from the environment and a secret manager. A different settings file swaps Twilio for GOV.UK Notify without a code change.
- **Test pyramid:** the domain rules are pure and fast to test, including the status rules, freshness, reply parsing and the clock-change cases. Use cases run against the in-memory fakes. Each port has a contract suite that every adapter, fake and real, must pass. A small set of end-to-end tests drives the FHIR interface against real adapters.
- **Architecture tests** (an import-linter configuration) fail the build if the domain or a use case imports an adapter, or an adapter imports another adapter.
- **Idempotency:** every command carries an idempotency key. The outbox and the webhook adapters can be called twice without a second effect, because providers retry.
## Next.js front end
One Next.js application serves every role. Route groups keep the roles apart. The browser never calls the FHIR server directly. It calls route handlers in the same app (a back end for the front end), which hold the session and call the FHIR interface.
```
app/
  (wall)/screen/             wall board, device token, no sign-in
  (reporter)/                app home, respond, services, settings, set-up
  (advisor)/                 start, case, options, request, outcome, map
  (clinical)/                queue, case, advice
  (lead)/                    registrations, reporters, suspend, scope list
  (exec)/                    home, services, alerts, week, subscriptions
  (owner)/criteria/          review, change, history
  l/[token]/                 link pages for text and email: respond, booking
  api/bff/                   route handlers: session, FHIR calls, SSE relay
lib/
  fhir/                      typed R4B client, bundles, search helpers
  auth/                      session, PIN, device checks
  push/                      subscription, consent record
  a11y/                      focus, live regions, reduced motion
public/
  manifest.webmanifest   sw.js
```
- **Server Components by default.** The board and lists are rendered on the server from the FHIR read model. Client components are only for forms, steppers and live regions.
- **Live updates.** The board and the advisor options subscribe to a server-sent events stream relayed by a route handler. A change to a capacity figure, a pending booking or a status pushes a small event and the page refetches that resource. The wall board also polls every minute as a fallback, and shows Last known if both fail. Precisely (DEC-152): it shows Last known when the stream has been down for more than 10 seconds and the last refetch failed, when an answer cannot be read, or when the board's `generatedAt` is more than 3 minutes older than the back end's clock; the figures stay, labelled as last known with their age.
- **Sessions.** An HTTP-only, same-site cookie. Reporters sign in with a text code and a PIN. Advisors, clinical advisors and leads sign in with the Trust staff account. The wall board uses a paired device token and can see no patient data.
- **Link pages** read a token, show the page and change nothing until a button is pressed as a POST with a CSRF check.
- **PWA.** A web manifest, a service worker for notifications and a minimal offline shell. The offline shell shows a plain page that says capacity cannot be shown and to use the phone process. It does not cache capacity or case data.
- **Push.** The app asks for permission only after the consent screen, then stores the subscription with the date and device. Notifications carry no patient data. Tapping one opens the app.
- **Accessibility.** Status uses a shape and a word as well as colour. Focus order is tested on the advisor case screen. Reduced-motion is respected. All pages are tested at 200% zoom.
- **No patient data in the client logs, analytics or error reports.**
## FHIR R4B interface
The FHIR REST interface is the single transfer protocol between the front end, the BFF and any later integration. It is an inbound adapter over the use cases, not a database in front. The text, email and link adapters call the same use cases without going through it.
- **Version:** FHIR R4B (4.3.0). Requests and responses use `application/fhir+json; fhirVersion=4.3`. The server publishes a CapabilityStatement and the profiles below.
- **Errors:** an OperationOutcome with a stable issue code. Refusals never reveal whether a record exists to a caller who may not see it.
- **Concurrency:** ETag and `If-Match` on every update. A write without a version fails.
- **Idempotency:** an `Idempotency-Key` header on every create. Providers retry webhooks, and so do people on poor signal.
- **Authorisation:** a token with a role and the services the caller may act for. The same resource is returned in a different projection by role. For example a service sees a booking Task without the case it refers to. Fields are removed by the server and the response carries a security label.
### Resources and interactions
| Resource | Read | Search | Create | Update | Notes |
|---|---|---|---|---|---|
| Organization, Location, HealthcareService, Endpoint | Yes | Yes | Registration only | Yes, versioned | Search `Location?near=`, `HealthcareService?service-category=`, `HealthcareService?organization=` |
| Observation (capacity report) | Yes | Yes | Yes | No. Reports are not edited, a new one replaces it. | Search by `focus`, `date`, with `_sort=-date&_count=1` for the latest |
| Basic (service criteria version) | Yes | Yes | Yes | No. A new version is a new resource. | Status workflow runs through a Task |
| Task (booking, registration, criteria approval, safety concern) | Yes | Yes | Yes | Status changes only, through rules | `Task.status` plus `businessStatus` |
| Patient (case stub), ServiceRequest (case) | Advisor and clinical roles | By case reference | Yes | Yes until closed | No name, no NHS number. Cleared fields are removed at close. |
| Practitioner, PractitionerRole, Device, Consent | Lead and admin | Yes | Yes | Yes | The reporter's number is in a protected store, not in the readable resource |
| SubscriptionTopic, Subscription | Own | Own | Yes | Own | Alerts for COO and ICB users |
| AuditEvent, Provenance | Audit role | Yes | System only | Never | Append-only |
| Communication | Lead | Yes | System only | Never | One per message sent, with delivery status |

### Booking as a Task
| Domain state | Task.status | Task.businessStatus (local code) |
|---|---|---|
| Requested | requested | requested |
| Confirmed | accepted | confirmed |
| Declined | rejected | declined |
| Expired | cancelled, statusReason expired | expired |
| Cancelled before or after confirming | cancelled | cancelled-before, cancelled-after |
| Withdrawn by the service | cancelled, statusReason withdrawn | withdrawn |
| Not reached | failed | not-reached |
| Completed | completed | completed |

The `businessStatus` code keeps the finer state, so a reader does not need to know the mapping.
### Custom operations
| Operation | On | Purpose |
|---|---|---|
| `$filter-options` | HealthcareService | Given an age band, need codes, urgency, a position and scores, return the services that pass the hard criteria, each with its status, effective available, data age, criteria version, and a travel range. **Filter only, not a ranking.** |
| `$board` | HealthcareService | The wall board and exec view read model: one entry per service with status, number, age and pending count. No patient data. |
| `$confirm-capacity` | HealthcareService | Confirm the figure on record without changing it. Logged as a Y report. |
| `$respond` | Task | Confirm or decline a booking, with an optional reason. The route behind the link page and the app. |
| `$suspend`, `$resume` | HealthcareService | Shift lead only. |
| `$validate` | Any | The standard operation, against our profiles. |

### Subscriptions
Alerts use FHIR R4B subscriptions: a SubscriptionTopic per alert kind (service closes, over capacity, not updated, system pressure) and a Subscription per user. I have not verified the exact R4B subscription elements, so confirm the SubscriptionTopic and Subscription shapes against the 4.3.0 specification before implementing. Delivery to a phone is by Web Push from the notifier adapter. The Subscription resource records what the user chose.
### Profiles and validation
- Profiles constrain the base resources to our mandatory fields, code systems and value sets. They are published with the CapabilityStatement.
- Every write is validated against its profile before it reaches a use case.
- Where a UK profile already covers a resource, derive from it, not from the base. Check UK Core and the NHS Directory of Services model first.
## Data flows
Every flow has one rule in common: a change and its audit record are written in one transaction, and anything to be sent is written to the outbox in that same transaction. A relay sends it afterwards. A crash can delay a message but not lose or duplicate it.
### F1. Capacity prompt, reply and board
- The scheduler adapter finds services whose prompt is due and calls `SendPrompts`.
- The use case reads the service and its latest figure, makes a link token, and writes a Communication and an outbox row.
- The relay sends by the service's channel (text, push or email) and records delivery status from the provider callback.
- **A text reply** reaches the webhook adapter. The number called and the Twilio account pick the tenant's subaccount, the provider signature is checked with that subaccount's token (a request that does not verify, or names an unknown number, gets one fixed refusal), and only then are the allow-list and the idempotency key checked. Anything unknown is dropped without a reply, and the text is queued for the domain reply parser (DEC-131, DEC-149).
- **A link page** is opened with a GET that changes nothing. A button press is a POST through the BFF.
- **The app** calls the FHIR interface behind the PIN session.
- Each path ends in `ReportCapacity` or `ConfirmCapacity`. The use case writes an Observation with its source, a Provenance record and an audit row, then raises `CapacityReported`.
- The status rules recompute the status. The board read model updates and a server-sent event reaches open pages. An echo message goes to the outbox.
- Missed reports: the scheduler sends the reminder, then the advisor phone task, then the shift lead alert.
[embed: capacity prompt and reply - sequence]
One trace id follows the reply from the webhook, link page or app to the board refetch. The echo in step 10 goes back through the notifier.
### F2. Booking request and reply
- An advisor calls `RequestBooking`. A Task is created as requested, the pending count rises and the audit row stores what the advisor saw.
- The outbox sends B1, B2 or B3 to the service.
- The reply arrives by text, link or app and calls `RespondToBooking`. Confirmed raises effective available by -1 and sends the echo.
- The advisor's page receives the result by event.
- A 5-minute and a 10-minute job fire from the scheduler. They prompt the advisor, then expire the Task.
- Withdrawal, cancellation and not-reached are further use cases that move the same Task.
### F3. A call, from case to outcome
- `OpenCase` creates a Patient stub and a ServiceRequest. Age band, postcode, needs, urgency and scores are held until the case closes.
- `FilterOptions` reads services, latest figures and criteria, filters on hard exclusions, gets travel ranges, and returns the list. It writes a snapshot of every status, number, age and criteria version to the audit log.
- The advisor requests a booking (F2) or phones, and records the outcome.
- `RecordOutcome` closes the case and clears the postcode and needs. The audit row keeps the need category, age band, urgency, scores, destination, outcome and times.
### F4. Registration and approval
- The shift lead invites from the scope list. A token goes to the registered number.
- The applicant verifies with a text code and creates a PIN. Registration writes draft Organization, Location and HealthcareService resources in one transaction Bundle.
- The Geocoder sets the Location position. The Terminology adapter checks the ODS code.
- A registration Task goes to the reviewer. The call-back result, the scope decision and the second approval of the criteria are recorded as Provenance.
- Approval sets the service active and sends the test notification. When the test is answered, the service goes live.
### F5. Criteria change
- The owner creates a new criteria resource as a draft and a Task for second approval.
- The clinical lead approves or sends back. On approval the new version becomes current and the old one is marked superseded, not deleted.
- The next `FilterOptions` call uses the new version. Open cases keep the version they saw.
### F6. Alerts
- A `StatusChanged` event starts the alert evaluator. It finds matching subscriptions in the graph.
- The outbox sends the push. An acknowledgement calls a use case that stamps the alert.
- The scheduler escalates an unacknowledged alert to the deputy, then to the shift lead.
### F7. Wall board
The paired device token reads `$board` and subscribes to the event stream. No patient data is in the response. If the stream and the poll both fail, the page shows Last known.
### F8. Position and travel time
Site addresses are geocoded once at registration. A patient postcode is resolved from a local centroid file. The travel-time port returns a range for patient to site, and for a visiting service, site to patient, as two separate numbers with their source.
### F9. Audit
Every command writes an AuditEvent and a Provenance record with the actor, role, channel and the ids of what was shown. Audit rows are append-only and chained by hash.
## Security, IG and operations
These are design intentions for IG, cyber and the clinical safety officer to challenge. I have not checked them against current NHS standards, so treat the standards named here as prompts.
- **No patient data in any channel.** Texts, emails and notifications carry a reference, an age band, a need category and an urgency at most. A test fails the build if a message template contains a postcode, a name or a number that looks like an NHS number.
- **Allow-list.** Replies are accepted only from registered numbers. Unknown senders get no reply, and the answer to Twilio is the same as for an accepted text (DEC-149).
- **Link tokens.** At least 128 bits, single use, tied to one prompt and one number, expiring with the prompt. A state change needs a button press.
- **PIN.** Six digits, stored only as a keyed hash on the server and bound to the device. Five wrong tries lock it. A text code resets it. Re-verify by text code every 30 days, and on any new device. Ask cyber whether passkeys would be a better second factor.
- **Staff sign-in.** Advisors, clinical advisors, leads and owners use the Trust staff account. Reporters and COO or ICB viewers use text code and PIN.
- **Roles and scope.** Every call is checked against role and the services the caller may act for. Patient-level resources are visible to advisor and clinical roles only.
- **Retention.** Case data is cleared at close. Reports, bookings and audit follow a retention schedule IG sets. The audit log records what was shown and when.
- **Secrets and keys** live in a secret manager. Provider webhooks are signature-checked. Logs and traces carry no patient data.
- **Browser.** Strict content security policy, same-site cookies, CSRF checks on every state change, and no third-party scripts.
- **Hosting.** UK region. Ask the SMS and email providers for data location and sub-processors.
- **Assurance to plan for:** a DPIA, the Data Security and Protection Toolkit, clinical safety documents (DCB0129 and DCB0160), a digital technology assessment, and a penetration test before go-live. Confirm which apply and the current versions.
### Operations
- **Health checks and runbooks** for the scheduler, the outbox relay, the provider webhooks and the event stream.
- **Degradation:** if the back end is down the wall board shows Last known and the advisor screen shows the manual-process banner. The manual process is written and drilled before go-live.
- **Backups and recovery** tested, with the Neo4j backup restored and the cache rebuilt.
- **Release:** monthly slot for framework security updates, as Next.js now publishes scheduled security releases.
## Build order, risks and open questions
The order puts the rules and the capacity loop first, because they are the product. Weeks are a guide for a pilot of a few services, not a promise.
| Step | What ships | Weeks [assumed] |
|---|---|---|
| 1 | Domain rules and tests: status, freshness, reply parser, booking state machine. In-memory adapters. | 1 to 2 |
| 2 | Capacity loop by text and link. Scheduler, outbox, SMS adapter, link pages, the board read model and the wall board. | 2 to 3 |
| 3 | Advisor view: case, `$filter-options` as a filter only, criteria view, phoned and declined records. | 3 to 4 |
| 4 | Booking by text and link, with expiry and the exceptions. | 4 to 5 |
| 5 | Registration, approval and the scope list. | 5 to 6 |
| 6 | App, PIN and push. Alerts for COO and ICB. | 6 to 8 |
| 7 | Map and travel time. Planning view from the decision log. | Later |

A pilot in 2 to 4 weeks fits steps 1 to 3 with registration done by the shift lead on the services' behalf. Everything after that follows once IG and clinical safety sign-offs land.
**Risks**
- IG, cyber and clinical safety take longer than the build. Start them in week 1.
- A text sender number and the provider's UK terms can take time to arrange. Ask on day one.
- Push on iPhone depends on the installed web app. Text stays the guaranteed channel.
- The graph store is the least familiar part for most teams. The port lets us start with a simple adapter and move.
- FHIR profiles are easy to over-build. Start with the mandatory fields and grow.
**Open questions**
- Which Neo4j edition, and how is it hosted on Azure?
- Text provider: Twilio or GOV.UK Notify?
- Routing engine for travel time?
- Who owns the scope list and approves registrations?
- Is there an existing Directory of Services feed to reuse for services and locations?