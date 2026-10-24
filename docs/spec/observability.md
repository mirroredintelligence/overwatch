# DIUCS capacity: observability, session troubleshooting and product analytics
2026-10-23 · @Robert Smith
We instrument the product to answer three questions: is it fast and working, is it easy to use, and is it saving people phone calls. Every signal is a trace, a metric or an event in OpenTelemetry form, so one request can be followed from a button press in the browser to the Cypher it ran.
## What we measure and why
| Question | What we look at | Who uses it |
|---|---|---|
| Is it working and fast? | Latency, errors and freshness from the browser to the database. Time from a text reply to the board changing. | Engineering, on-call |
| Is it easy to use? | Funnels, navigation paths, rage clicks, dead clicks, form abandonment, hesitation. By screen and element. | Product and design |
| Is it saving calls and meetings? | Updates received by channel, on-time rate, time to a confirmed booking, calls avoided against the baseline | SPOA leads, COO and ICB |
| Can we help this person now? | One session's timeline, joined to its backend traces | Support, with consent |

## The rule that governs the rest
**This is not a staff performance monitor.** We promised advisors, reporters and clinical staff that the tool is not used to time or rank them. The telemetry is built so it cannot be.
- Analytics are by screen, element, role and service. There is no per-person league table and no per-advisor handling-time view.
- A person's own session can be opened only in support mode: when they share a session code from Report a problem, or with a support ticket and a lead's approval. Every open is logged and shown to the person.
- Nothing typed into a field, no text from the page and no patient data is ever captured. We record which element was used and what happened next, not what was entered.
- Events carry a pseudonymous session id. The link from that id to a person is held in a separate, access-controlled place and expires.
## Telemetry pipeline on Azure
[embed: telemetry pipeline - components, collector, Azure Monitor]
One trace id runs from a tap in the browser through the BFF and the Python use case to the named Cypher query. The collector scrubs and samples before anything is stored.
## Event taxonomy
Three families share one naming scheme and one trace id: UI events from the browser, spans from the services, and domain events from the core. Names are lower case with dots. I have not checked the current OpenTelemetry semantic-convention attribute names, so use the version current when the build starts.
### Attributes on every event and span
| Attribute | Value |
|---|---|
| `session.id` | Random per browser session. Not linked to a person in the telemetry store. |
| `user.role` | reporter, advisor, clinical, lead, owner, exec, wall, anonymous-link |
| `service.id` | The service a reporter is acting for, when relevant. Services are not personal data. |
| `page.route` | The route template, for example `/case/[ref]`, never the raw URL |
| `component.id`, `element.id` | The stable id from the traceability matrix, for example `ADV-OPT-REQUEST-BTN` |
| `release` | The build id |
| `device.type`, `app.mode` | phone, tablet, desktop. Browser or installed web app. |
| `net.effective_type` | The browser's connection class where available |
| `trace_id` | The W3C trace context, carried from the browser through every hop |

### UI events
| Event | When | Extra attributes |
|---|---|---|
| `ui.page_view` | A route is shown | `from.route`, `load.type`, `ttfb_ms`, `lcp_ms` |
| `ui.click` | A click or tap on an instrumented element | `element.id`, `dwell_ms`, `result` (navigation, network, dom, none) within 1 second |
| `ui.input` | A field changes | `element.id`, `valid`, `length_bucket`. Never the value. |
| `ui.toggle`, `ui.chip` | A switch or chip changes | `element.id`, `state` |
| `ui.submit` | A form is submitted | `form.id`, `error_count`, `time_to_submit_ms` |
| `ui.error_shown` | An error message appears | `error.code`, `element.id` |
| `ui.friction` | A friction rule fires (see next section) | `kind`, `element.id`, `count`, `window_ms` |
| `ui.web_vital` | A web vital is measured | `name`, `value`, `rating` |
| `ui.long_task` | A task blocks the main thread over 50 ms | `duration_ms` |
| `ui.sse` | The live stream connects, drops or recovers | `state`, `gap_ms` |
| `ui.push_permission` | The consent screen and the phone prompt | `state` (shown, allowed, blocked, skipped) |
| `ui.pwa` | The app is installed or opened from the home screen | `standalone` |
| `ui.help` | Help, Report a problem or the guide is opened | `kind`, `session_code_shared` |

### Backend spans
| Span name | Attributes |
|---|---|
| `HTTP {route template}` (browser fetch) | status, duration, size, retry count |
| `bff.{route}` | role, cache hit |
| `fhir.{interaction} {ResourceType}` | operation, resource type, outcome |
| `usecase.{Name}` | idempotent replay, domain outcome |
| `neo4j.query {QueryId}` | `db.system=neo4j`, named query id, access mode, row count, duration |
| `redis.{operation}` | key family (never the key), hit or miss |
| `servicebus.publish {topic}`, `servicebus.process {topic}/{subscription}` | message id, delivery count, lag |
| `sms.send`, `push.send`, `email.send` | provider, outcome, provider latency |

### Domain events (as span events)
CapacityReported, StatusChanged, BookingRequested, BookingResponded, BookingExpired, RegistrationSubmitted, RegistrationApproved, CriteriaApproved, AlertRaised, AlertAcknowledged. Each carries ids and counts. None carries a patient value.
### Rules
- Metrics are labelled by route template, role and outcome only. Ids go on spans and events, never on metric labels, so cardinality stays bounded.
- Every request carries a `traceparent` header from the browser, so a UI event and its backend trace share an id.
- A query is named. The Cypher text is never put in telemetry. The query id is, and the matrix maps the id to the text.
## Friction signals
The browser detects friction and sends one `ui.friction` event with the element id. Thresholds are my starting values **[assumed]**, to tune against real sessions. Rules run on interaction timing only, never on content.
| Signal | Rule | What it usually means |
|---|---|---|
| Rage click | 3 or more clicks or taps on the same element, or within 30 px, inside 1 second | The control looks live but does nothing, or answers too slowly |
| Dead click | A click on something that looks interactive, with no navigation, DOM change, network call or state change within 1 second | A label that looks like a button, or a broken handler |
| Error click | A click followed within 2 seconds by an error message, an HTTP 4xx or 5xx, or a script error | A button that fails |
| Impatient click | A second click on the same control while its first request is still in flight | The response is slower than the person will wait |
| U-turn | Route A, then B, then A again inside 5 seconds, with no interaction on B | A navigation label that misleads |
| Thrash | 3 or more switches between the same two routes inside 10 seconds | The person cannot find what they need in either place |
| Validation loop | The same field fails validation 3 or more times | Unclear wording, a format that is not explained |
| Form abandonment | A field was focused and the person left without submitting. The last field touched is recorded. | The step where people give up |
| Hesitation | No interaction for 20 seconds on a screen built for one quick action (respond, request, confirm) | Unsure what to do, or an unclear primary action |
| Missed tap | A tap within 24 px of a control that did not land on it | A touch target that is too small or too close to another |
| Scroll thrash | 4 or more reversals of scroll direction inside 3 seconds | The thing they want is not where they look |
| Stream gap | The live stream is down for more than 10 seconds while the page is open | A stale board that looks live |

### Rolling friction into a score
For each element, the friction rate is friction events divided by interactions, over the last 7 days, by role and device type. An element over 5% **[assumed]**, or one that rises more than 2 points after a release, is listed on the insights page with a link to example sessions. A person is never ranked.
### What the rules cannot tell you
A rage click says that something is wrong at that element, not what. The session timeline and the trace show the cause. The goal of this section is to point at the element, not to explain it.
## Funnels by role
Each funnel is a fixed list of steps, each defined by a UI or domain event, so a step has one meaning everywhere. For every funnel we report the conversion between steps, the median time between steps, the element where people leave, and the split by channel and device. A step that can be reached two ways (text link or app) is one step with a channel attribute.
| Funnel | Steps in order | Why it matters |
|---|---|---|
| Reporter set-up | Invitation delivered, link opened, welcome started, code requested, code verified, channel chosen, home-screen guide viewed, opened from home screen, notification prompt shown, notifications allowed, PIN created, PIN confirmed, first prompt answered | Set-up is where services drop out. Each step has its own element id, so the leak is visible. |
| Daily capacity loop | Prompt sent, delivered, opened, responded (confirm or update), recorded, echo delivered | The core loop. Tells us how many prompts become a fresh figure, by channel. |
| Booking, service side | Request sent, delivered, opened, decision made (confirmed or declined), echo delivered. Branch: expired. | Shows how many requests are answered in time, and how long that takes. |
| Advisor call | Case opened, needs captured, options viewed, criteria viewed, request sent, confirmed, outcome recorded, summary copied, case closed. Branches: phoned, clinical advice requested, no service fits. | Shows where a call slows down, and which branch is used most. |
| Registration | Invited, started, organisation done, location done, service done, capacity reporting done, submitted, checks complete, approved, test answered, live | Shows the effort of onboarding and where the reviewer waits. |
| Criteria review | Reminder sent, opened, confirmed or changed, submitted, second approval, current | Keeps criteria fresh, which is a safety control. |
| COO and ICB adoption | Invited, set up, alerts chosen, first alert received, first acknowledged, weekly use | Shows whether escalations are seen and acted on. |

### Measures reported on each funnel
- **Step conversion** and **median time between steps**, by week.
- **Exit element**: the last element used before leaving, so the answer is a button or a field, not a page.
- **Channel and device split**: text, link, email, app and push, and phone, tablet or desktop.
- **Time to first value**: for a new reporter, the time from invitation to the first recorded figure.
### Value measures, joined to the funnels
Updates received by channel, on-time rate, time to a confirmed booking and calls avoided are calculated from the same events. The value page shows the sum behind every estimate, and states which parts are measured and which are assumed.
## Performance and responsiveness
Performance is judged where the person is: a phone on a ward, a desktop in the call centre, a wall screen. The first three rows use the web performance "good" thresholds. The rest are my starting budgets **[assumed]**, to set with engineering once there is real load.
| Measure | Budget | Where measured |
|---|---|---|
| Largest contentful paint | 2.5 s or less at the 75th percentile, by device type | Browser |
| Interaction to next paint | 200 ms or less at the 75th percentile | Browser |
| Cumulative layout shift | 0.1 or less | Browser |
| Read route latency, BFF | p95 500 ms or less | BFF span |
| Write route latency, BFF | p95 800 ms or less | BFF span |
| Named Cypher query | p95 100 ms for board reads, 200 ms for options | Neo4j span |
| Text reply to board change | p95 3 s or less | Trace from webhook to event stream |
| Prompt due to sent | p95 30 s or less | Scheduler span to provider accepted |
| Booking request sent to delivered | p95 10 s or less, provider permitting | Provider receipt |
| Live stream gap | Under 10 s, and the board shows Last known beyond it | Browser |
| Pilot availability in service hours | 99.5% | Synthetic checks |

### Prompt to board, end to end
One trace follows a prompt from the scheduler to the board. The trace separates **system time** (due, sent, delivered, recorded, shown) from **human time** (delivered, opened, replied). It tells us whether a slow update is a slow system or a busy ward, so we never blame the wrong one.
### What else is watched
- **Neo4j:** query time by query id, transaction retries, connection pool wait.
- **Redis:** hit rate, latency, evictions, memory.
- **Service Bus:** queue depth, age of the oldest message, dead-letter count, scheduled-message lag.
- **Providers:** text and email delivery rate and latency, push failure reasons.
- **Front end:** script size per route, long tasks, service-worker errors, offline starts.
### How it is enforced
- **Synthetic checks** every few minutes: a scripted advisor journey, and a scripted reporter loop against a test service and number. A failure pages the on-call person.
- **Release gate:** a canary that makes a route more than 10% slower at p75, or raises an element's friction rate by more than 2 points, is held for review.
- **Burn alerts:** alert on the error budget burning, not on one slow request.
- **Real devices:** the slowest phone and the oldest browser in the pilot are tested each release.
## Privacy and governance
Session data about how staff use a clinical tool is sensitive, even without patient data. These rules are for IG and staff representatives to challenge before any of it is switched on.
| Area | Rule |
|---|---|
| What is captured | Element ids, route templates, timings, outcomes, device class. Never field values, page text, screenshots or DOM recordings. |
| Session replay | No pixel or DOM replay. The "replay" is an event timeline built from the events above. |
| Identity | A random session id. The link from session to person is held in the identity adapter, in Neo4j under the access-controlled identity label, and expires after [period]. The telemetry store never holds the link. |
| Staff notice | A plain statement on first use and in Help: what we record, why, who can see it, and that it is not used to time or rank people. |
| Consent for support | A person opens Report a problem and chooses Share my session. That creates a support code valid for [hours]. Without a code, support sees aggregates only. |
| Support access | A named support role. Opening a session needs a code or a ticket and a lead's approval. Each open is audited, time-limited, and shown to the person in their own Help screen. |
| Aggregates | Shown by screen, element, role, service and device. Groups under 10 sessions are hidden. |
| What is never built | A dashboard of one person's speed, errors or friction, or a view that ranks advisors or reporters. |
| Retention | Raw events [30 to 90 days]. Aggregates [period]. Set with IG. |
| Patient data | The telemetry store holds none. A test scans every event schema and fails the build if a field could carry free text. |
| Do not track and consent banner | Telemetry is operational, not marketing. IG decides whether notice is enough or consent is needed. |

**Where this sits against the promise to staff.** Product analytics would normally be used to find slow users. Here it only finds slow screens. If a manager asks for a per-person report, the answer is no, and the design makes the data unavailable to answer it.
## The support and insight console
One console, three roles. The screens are drawn on the design canvas in the board titled "Support and insight console". It is part of the same Next.js app, behind its own route group, and it reads through the same BFF and the same use cases as everything else.
| Screen | The question it answers | Who sees it |
|---|---|---|
| Find a session | Which session is this? Search by support code, session id, trace id, booking or case reference, service, role, release | Support |
| Session timeline | What did this person do, in order, and where did it go wrong? Page views, clicks by element, field events without values, API calls with durations and statuses, friction flags, errors. Each API call links to its trace. | Support, only with a code or an approved ticket |
| Trace view | Where did the time go? A waterfall from the browser to the BFF, the Python use case, each named Cypher query, Redis, Service Bus and the provider | Support, engineering |
| Funnels | Where do people drop out of set-up, the capacity loop, booking, a call, registration? | Product, leads |
| Navigation paths | How do people actually move around, which routes are u-turns, which controls are never used? | Product, design |
| Friction | Which elements cause rage clicks, dead clicks, error clicks, abandonment? By element, role and device. | Product, design |
| Performance | Web vitals by device, route and query latency, prompt-to-board latency split into system time and human time, stream gaps, SLO burn | Engineering, product |
| Release comparison | Did this release make anything slower or harder? | Engineering, product |
| Pipeline health | Service Bus depth and dead letters, provider delivery rates, scheduler lag | Engineering |

### Access
- **Product and design** see aggregates only, never one person's session.
- **Support** sees one session only through a support code the person shared, or an approved ticket. Each open is logged and shown to the person.
- **Engineering** sees traces and aggregates. A trace carries ids and timings and no values.
- Everything in the console is itself instrumented, so access to it can be audited the same way.
## Implementation on Azure and open decisions
### Where telemetry lives
Application data lives in Neo4j only, and Redis is a cache. Telemetry is a different kind of data, and I recommend it goes to Azure Monitor (a managed service, not a database we run), with aggregates copied into Neo4j. That keeps your rule for application data and avoids running Zipkin's own storage.
| Option | Verdict |
|---|---|
| **Raw traces, logs and events in Azure Monitor (Application Insights on a Log Analytics workspace). Funnel and friction aggregates written to Neo4j.** | Recommended. The console reads raw data through a telemetry query port and aggregates from Neo4j. Raw retention is short. Aggregates are kept longer. |
| Everything in Neo4j | Possible for aggregates only. Raw click streams are high volume and short-lived, which a graph store does not suit. |
| Zipkin with its own storage | Needs a second database, so it breaks the rule. The OpenTelemetry Collector can still export in Zipkin format for developers who want that view. |

### Instrumentation
- **Browser:** the OpenTelemetry JavaScript web SDK for page loads, fetch spans and web vitals, plus a small in-house module for the friction rules and the `ui.*` events. It sets `traceparent` on every request to the BFF.
- **Next.js server and BFF:** Next.js supports OpenTelemetry through an instrumentation file. Verify the current setup in the version you pin.
- **Python:** OpenTelemetry for FastAPI, Redis, the Azure SDK (Service Bus) and outbound HTTP, plus manual spans in the Neo4j adapter that carry the **named query id**, access mode and row count.
- **Collector:** the OpenTelemetry Collector runs as a container, receives OTLP, scrubs attributes, applies sampling and exports to Azure Monitor. A Zipkin exporter is optional.
- **Sampling [assumed]:** keep every UI event during the pilot. Tail-sample traces: always keep errors and slow ones, and a share of normal ones.
- **Scrubbing:** an allow-list of attribute keys. Anything else is dropped in the collector, so a mistake in code cannot leak a value.
### Services on Azure
| Need | Service | Note |
|---|---|---|
| Graph database | Neo4j, managed or self-managed on Azure | Confirm UK region and the edition's security features |
| Cache, locks, rate limits, live-event fan-out | Azure's managed Redis | Check the current lifecycle of Azure Cache for Redis against Azure Managed Redis before choosing |
| Messaging, scheduling, outbox relay | Azure Service Bus topics and queues | See the platform section of the architecture document |
| Staff sign-in | Microsoft Entra ID | The Trust staff account |
| Secrets and keys | Azure Key Vault |  |
| Telemetry | Azure Monitor and Application Insights |  |
| Front door | Azure Front Door or Application Gateway with a web application firewall |  |
| Hosting | Container Apps or Kubernetes, in a UK region | A decision for the Trust's platform team |

### Open decisions
- Raw telemetry retention, and what IG allows.
- Whether a notice to staff is enough, or consent is needed.
- Who holds the support role, and who approves a session open.
- Thresholds for friction rules and budgets, after the first two weeks of real data.
- Whether a text provider on Azure (for example Azure Communication Services) is acceptable, against Twilio or GOV.UK Notify. I have not checked its UK number and delivery terms.