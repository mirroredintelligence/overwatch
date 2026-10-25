# Delivery status

Generated 2026-10-25T16:03:56.879531+00:00. Source of truth: the shared ledger (python delivery.py status). Delivered 48/215 tasks.

## S0 Foundations

| Task | Title | Status | Owner | Commit | Evidence |
|---|---|---|---|---|---|
| F01 | Backend project scaffold | delivered | build-F01 | b6a7cb6 | checks, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-F01b |
| F02 | Architecture import rules enforced by tests | delivered | build-F02 | 5e29a46 | checks, spec-trace, tests-green, tests-red; verified by verify-F02c |
| F03 | Front-end project scaffold | delivered | build-F03 | 7eed47c6048a639704fa6436af40e03dfa9111ca | checks, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-F03c |
| F04 | Local infrastructure with Docker Compose | delivered | build-F04 | 219ea97 | checks, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-F04c |
| F05 | CI pipeline | delivered | build-orchestrator | 7234615 | checks, spec-trace, tests-green, tests-red; verified by verify-F05b |
| F06 | Clock and id ports, London time helpers | delivered | build-F06 | ce74a30baf62b762704ea6eccb6bf6d45c009b5f | checks, hazard-note, mutation, spec-trace, tests-green, tests-red; verified by verify-F06b |
| X01 | Fix London wall-clock property test on other UK change days | delivered | build-X01 | a2a71ed | checks, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-X01 |
| F07 | Local code systems and Coding value object | delivered | build-F07 | a2adacc0f3aa473610c6865c2f265ca9616c973e | checks, coverage, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-F07b |
| F08 | Settings and composition root skeleton | delivered | build-F08 | 8efb67520550d03f4218f6ae1bbfb4025d39fd0a | checks, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-F08b |
| G01 | Neo4j adapter base: driver, named queries, migrations | delivered | build-G01 | 1e2060a | checks, spec-trace, tests-green, tests-red; verified by verify-G01d |
| G14 | Neo4j connection lifecycle, health and recovery | delivered | build-G14 | 7edb1ebaccef75af0f1239a03153079e8c5c0c87 | checks, other, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-G14f |
| F09 | Design tokens, font and StatusBadge | delivered | build-F09 | 259734a | checks, coverage, other, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-F09c |
| X02 | Add motion, spacing and type tokens from the design system | delivered | build-X02 | e24b8d0e826250fe41cbe67335145a0644a40d44 | checks, spec-trace, tests-green, tests-red; verified by verify-X02 |
| X03 | Apply DEC-019 design-system values (sheet 280 ms, caption 16 px, reduced-motion opacity) | delivered | build-X03 | 1e7ce93 | checks, spec-trace, tests-green, tests-red; verified by verify-X03 |
| F10 | Neo4j test harness | delivered | build-F10 | bd41c96 | checks, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-F10b |
| F11 | Restartable Neo4j mode in the test harness | delivered | build-F11 | cb920f4 | checks, other, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-F11b |

## S1 Domain rules

| Task | Title | Status | Owner | Commit | Evidence |
|---|---|---|---|---|---|
| D01 | Service profile value objects | delivered | build-D01 | cffe75e | checks, mutation, spec-trace, tests-green, tests-red; verified by verify-D01c |
| D02 | Capacity report value object and latest report | delivered | build-D02 | 455f068 | checks, spec-trace, tests-green, tests-red; verified by verify-D02b |
| D03 | Opening hours rule | delivered | build-D03 | a80cca20cdf4e2c7ad2cdcac068cff35a6f24864 | checks, coverage, mutation, spec-trace, tests-green, tests-red; verified by verify-D03 |
| D04 | Report schedule and missed-report ladder times | delivered | build-D04 | 9116b055188ffddab9cfc7c5d4a737a7114a2e17 | checks, hazard-note, spec-trace, tests-green, tests-red; verified by verify-D04b |
| D05 | Freshness and data-age text | delivered | build-D05 | c48df3dc73973d3e9e98e2665d84e6cbf7903620 | checks, coverage, hazard-note, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-D05 |
| D06 | Effective available and pending count | delivered | build-D06 | 97c1fd4 | checks, spec-trace, tests-green, tests-red; verified by verify-D06 |
| D07 | Service status rule | delivered | build-D07 | b1510be2f0fc72c0cdbdcd1802fb5fee965327ea | checks, coverage, hazard-note, mutation, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-D07 |
| D08 | System pressure rule | delivered | build-D08 | 14fe09a4db8f437fdb0db842cb499915fc028462 | checks, mutation, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-D08 |
| D09 | Reply parser: capacity and booking words | delivered | build-D09 | e3ed49f26e363184790dcae1330fbe3ce3bb083b | checks, mutation, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-D09 |
| D10 | Reply parser: multi-service lettered replies | delivered | build-D10 | c87b9380830e460a2263f11781e7cfef727d8d72 | checks, hazard-note, spec-trace, tests-green, tests-red; verified by verify-D10 |
| D11 | Capacity reply policy | delivered | build-D11 | 81ca04dd50dc13a13de419db00a363ac16d166d8 | checks, hazard-note, spec-trace, tests-green, tests-red; verified by verify-D11b |
| D12 | Report flag rules | delivered | build-D12 | 4d59f752026cb6687eb4f47ad2bac9f1eff99258 | checks, hazard-note, mutation, spec-trace, tests-green, tests-red; verified by verify-D12b |
| D13 | Booking state machine and FHIR status mapping | delivered | build-D13 | aa700150c102cad7da07a5f9d792550bf521e128 | checks, spec-trace, tests-green, tests-red; verified by verify-D13b |
| D14 | Booking rules: timers, one open request, references | delivered | build-D14 | 2318c8852968ed6a7729ca3fd4c949c7eb18177c | checks, spec-trace, tests-green, tests-red; verified by verify-D14c |
| D15 | Message templates: capacity (C1 to C11) | delivered | build-D15 | ef3383f7bd4ea6599cffcee93613d4b2c877579c | checks, spec-trace, tests-green, tests-red; verified by verify-D15b |
| D16 | Message templates: booking, invitations, codes, alerts | delivered | build-D16 | 3697401e6d01dae64baff5eee52fc49ce6e71b5f | checks, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-D16c |
| D17 | No-patient-data guard for every template | delivered | build-D17 | f3d4fb543891eae40ff0beca180cae92426e5234 | checks, spec-trace, tests-green, tests-red; verified by verify-D17d |
| D18 | Case model, referrer scores and outcomes | delivered | build-D18 | 2849e29bce68d3af261b9023ab1af09e1f80cb68 | checks, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-D18 |
| D19 | Postcode normalisation and district | delivered | build-D19 | f7a9941 | checks, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-D19 |
| D20 | Criteria model and hard filter | delivered | build-D20 | 98d6e4dbbe1b0e20552ab17aea069f58a3fa6cfa | checks, hazard-note, spec-trace, tests-green, tests-red; verified by verify-D20b |
| D21 | Criteria workflow and review-overdue rule | delivered | build-D21 | b2100a3 | checks, hazard-note, spec-trace, tests-green, tests-red; verified by verify-D21 |
| D22 | Registration state machine and approval gate | delivered | build-D22 | bf031a3e69d8881b23d85f30818ac54729b941eb | checks, coverage, hazard-note, spec-trace, tests-green, tests-red; verified by verify-D22 |
| D23 | Clinical advice queue and presence rules | delivered | build-D23 | dc6541be49b4ad842d40d775700e60c60bb0d54a | checks, hazard-note, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-D23b |
| D24 | Alert rules: triggers, subscriptions, quiet hours, escalation | delivered | build-D24 | 04ce1aef07ce14c42b2d42cc9ae057004d327367 | checks, spec-trace, tests-green, tests-red; verified by verify-D24b |
| D25 | Domain events | delivered | build-D25 | d46f2fd46b5deea95a3c96f802ed6e11bb51e23a | checks, privacy-scan, spec-trace, tests-green, tests-red; verified by verify-D25c |
| D26 | Link tokens, pairing codes and support codes | delivered | build-D26 | 85dbcd7f13f61f5f5190d4eb663f54dba6dde186 | checks, spec-trace, tests-green, tests-red; verified by verify-D26b |
| D27 | Identity policy: text codes, PINs, re-verification | delivered | build-D27 | 75af9a5eca56ce9f84e060c87a7eca0b7cdc87f5 | checks, spec-trace, tests-green, tests-red; verified by verify-D27b |
| D28 | Multi-service rules: grouped prompts and phone load | delivered | build-D28 | c98bf538b761c09bd1a49ecb77ee1fa7a7e40c34 | checks, spec-trace, tests-green, tests-red; verified by verify-D28b |
| G02 | FHIR-to-graph mapper: resources, primitives, references | delivered | build-G02 | 80c2d949a36a4843420d0cd2edc44142962bb53c | checks, spec-trace, tests-green, tests-red; verified by verify-G02c |
| G03 | Mapper: concepts, identifiers, periods and quantities | delivered | build-G03 | fee0d2c529b948dbce5bc7326e46b1005c62d243 | checks, spec-trace, tests-green, tests-red; verified by verify-G03c |
| G04 | Mapper: backbone elements and extension registry | delivered | build-G04 | 343870a8b6ea5ed32a2c1745248fe261fe71c17d | checks, spec-trace, tests-green, tests-red; verified by verify-G04c |
| G05 | Graph writer and reader with versions | delivered | build-G05 | 9e64636a1e5c05d1cb69a24d0c3eb66b9a23538f | checks, spec-trace, tests-green, tests-red; verified by verify-G05b |

## S2 Capacity loop: core and storage

| Task | Title | Status | Owner | Commit | Evidence |
|---|---|---|---|---|---|
| P01 | Service and capacity ports with Neo4j repositories | not-started | - | - | - |
| P02 | Booking port with Neo4j repository | not-started | - | - | - |
| P21 | Case port with Neo4j repository | not-started | - | - | - |
| P03 | Person, role and practitioner ports with Neo4j repository | not-started | - | - | - |
| P04 | Criteria port with Neo4j repository | not-started | - | - | - |
| P13 | Registration and scope list ports with Neo4j repositories | not-started | - | - | - |
| P14 | Report and service flag ports with Neo4j repository | not-started | - | - | - |
| P05 | Audit log port with Neo4j hash chain and provenance | not-started | - | - | - |
| P06 | Outbox and unit of work on Neo4j | not-started | - | - | - |
| P15 | Idempotency store and processed-message markers on Neo4j | not-started | - | - | - |
| P07 | Messaging ports, recording senders and Neo4j communication records | not-started | - | - | - |
| P08 | Event bus port, manual-clock fake and Neo4j scheduled-work records | not-started | - | - | - |
| P09 | Cache port with in-memory fake | not-started | - | - | - |
| P10 | Link token, secret and phone-hash ports with Neo4j token store | not-started | - | - | - |
| P16 | Contact store and PIN credentials on Neo4j, text-code store port | not-started | - | - | - |
| P11 | Geocoder, travel-time, terminology and validator ports with fakes | not-started | - | - | - |
| P12 | Contract tests for the cache and event bus fakes | not-started | - | - | - |
| U01 | ReportCapacity use case | not-started | - | - | - |
| U02 | ConfirmCapacity use case | not-started | - | - | - |
| U03 | SendPrompts use case (one service) | not-started | - | - | - |
| U04 | Grouped prompts for multi-service phones | not-started | - | - | - |
| U05 | HandleInboundText use case: capacity replies | not-started | - | - | - |
| U06 | Missed-report ladder handlers | not-started | - | - | - |
| U07 | Raise report flags when reports break rules | not-started | - | - | - |
| U08 | QueryBoard read model | not-started | - | - | - |
| U09 | Board projector: cache and live updates | not-started | - | - | - |
| I01 | Redis cache adapter | not-started | - | - | - |
| I02 | Service Bus event bus adapter | not-started | - | - | - |
| I03 | Outbox relay worker | not-started | - | - | - |
| I04 | Idempotent message consumer framework | not-started | - | - | - |
| I05 | Scheduled work consumer | not-started | - | - | - |

## S3 Capacity loop: channels, API and wall board

| Task | Title | Status | Owner | Commit | Evidence |
|---|---|---|---|---|---|
| R01 | FHIR REST app skeleton | not-started | - | - | - |
| R02 | Authentication, roles and service scope | not-started | - | - | - |
| R03 | ETag, If-Match and Idempotency-Key handling | not-started | - | - | - |
| R04 | HealthcareService and capacity Observation endpoints | not-started | - | - | - |
| R05 | $board and $confirm-capacity operations | not-started | - | - | - |
| R06 | Server-sent events stream | not-started | - | - | - |
| L01 | Capacity link API | not-started | - | - | - |
| I06 | Twilio SMS adapter | not-started | - | - | - |
| I07 | SMS inbound webhook | not-started | - | - | - |
| I08 | Reply processor and delivery receipt consumers | not-started | - | - | - |
| I09 | Email adapter (SMTP) with HTML and text bodies | not-started | - | - | - |
| I10 | Outbound message senders (messages.outbound consumers) | not-started | - | - | - |
| U10 | PairWallScreen use case | not-started | - | - | - |
| R15 | Wall screen pairing endpoints | not-started | - | - | - |
| W01 | BFF foundations: typed FHIR client and MSW test setup | not-started | - | - | - |
| W02 | BFF session cookie and CSRF | not-started | - | - | - |
| W03 | Base UI components | not-started | - | - | - |
| W04 | Capacity link pages | not-started | - | - | - |
| W05 | Wall board page | not-started | - | - | - |
| W06 | Wall board live updates and Last known | not-started | - | - | - |
| W07 | Wall board variants: pressure, out of hours, pending | not-started | - | - | - |
| W08 | Wall screen pairing pages | not-started | - | - | - |
| O01 | Backend OpenTelemetry baseline | not-started | - | - | - |

## S4 Advisor call

| Task | Title | Status | Owner | Commit | Evidence |
|---|---|---|---|---|---|
| U11 | OpenCase use case | not-started | - | - | - |
| U12 | FilterOptions use case with audit snapshot | not-started | - | - | - |
| U13 | Advisor phoned and declined-despite-capacity | not-started | - | - | - |
| U14 | RecordOutcome and close case | not-started | - | - | - |
| U15 | Lead-assisted service set-up (pilot) | not-started | - | - | - |
| U16 | Change reporter number and cover | not-started | - | - | - |
| G11 | Criteria hard-filter and history queries | not-started | - | - | - |
| I11 | Local postcode centroids and interim travel-time adapter | not-started | - | - | - |
| R07 | Case endpoints and $filter-options | not-started | - | - | - |
| R08 | Lead endpoints: service set-up and reporter numbers | not-started | - | - | - |
| R16 | Pathways Dx code lookup endpoint | not-started | - | - | - |
| W09 | Staff sign-in with Entra ID and role guard | not-started | - | - | - |
| W10 | Advisor home and call step header | not-started | - | - | - |
| W11 | Patient needs form | not-started | - | - | - |
| W12 | Referrer score pickers | not-started | - | - | - |
| W13 | Options list | not-started | - | - | - |
| W14 | Criteria, I phoned and They declined dialogs | not-started | - | - | - |
| W15 | Record outcome, SystmOne summary and call closed | not-started | - | - | - |
| W16 | No service fits state | not-started | - | - | - |
| W17 | Shift lead page: chasing, system now, covering | not-started | - | - | - |
| W18 | Shift lead: add service and change number forms (pilot) | not-started | - | - | - |
| S01 | Browser security headers and CSP | not-started | - | - | - |

## S5 Booking by text and link

| Task | Title | Status | Owner | Commit | Evidence |
|---|---|---|---|---|---|
| U17 | RequestBooking use case | not-started | - | - | - |
| U18 | RespondToBooking use case | not-started | - | - | - |
| U19 | Booking timers: phone prompt and expiry | not-started | - | - | - |
| U20 | CancelBooking use case | not-started | - | - | - |
| U21 | WithdrawBooking and NotReached use cases | not-started | - | - | - |
| U22 | Booking replies by text | not-started | - | - | - |
| R09 | Booking Task endpoints, $respond and service projection | not-started | - | - | - |
| R17 | Advisor acknowledgement of a withdrawn booking | not-started | - | - | - |
| L02 | Booking link API | not-started | - | - | - |
| W19 | Booking link page for services | not-started | - | - | - |
| W20 | Advisor booking card states, live | not-started | - | - | - |
| W21 | Advisor cancel booking and withdrawal alert | not-started | - | - | - |
| W22 | Service booking exceptions: withdraw, not reached, cancelled | not-started | - | - | - |

## S6 Registration and approval

| Task | Title | Status | Owner | Commit | Evidence |
|---|---|---|---|---|---|
| U23 | Scope list management | not-started | - | - | - |
| U24 | Invite a service reporter | not-started | - | - | - |
| U25 | Text code request and verification | not-started | - | - | - |
| U26 | Registration draft and submit | not-started | - | - | - |
| I12 | OS Places geocoder and ODS terminology check adapters | not-started | - | - | - |
| U27 | Registration persistence as one FHIR transaction | not-started | - | - | - |
| U28 | Review registration: automatic checks, call-back, scope | not-started | - | - | - |
| U29 | Approve, send back, test prompt and go live | not-started | - | - | - |
| U30 | ChangeCriteria, ApproveCriteria and ConfirmCriteria | not-started | - | - | - |
| U31 | Criteria review reminders and overdue flag | not-started | - | - | - |
| R10 | Registration, scope and criteria endpoints | not-started | - | - | - |
| W23 | Registration: sign in and start | not-started | - | - | - |
| W54 | Registration: organisation step and error summary | not-started | - | - | - |
| W24 | Registration: location step with address lookup | not-started | - | - | - |
| W25 | Registration: service and criteria step | not-started | - | - | - |
| W26 | Registration: capacity reporting, review, submitted, my services | not-started | - | - | - |
| W27 | Applicant status pages | not-started | - | - | - |
| W28 | Reviewer: scope list, queue and overview | not-started | - | - | - |
| W29 | Reviewer: call-back, scope, decide and go live | not-started | - | - | - |
| W30 | Criteria owner: review, confirm, change, preview, send | not-started | - | - | - |
| W31 | Criteria second approval, history and overdue | not-started | - | - | - |

## S7 Reporter app, PIN, push and alerts

| Task | Title | Status | Owner | Commit | Evidence |
|---|---|---|---|---|---|
| P17 | Alert subscription and alert repositories on Neo4j | not-started | - | - | - |
| P19 | Push subscription repository on Neo4j | not-started | - | - | - |
| U32 | PIN set, sign-in, lock, reset and 30-day check | not-started | - | - | - |
| I13 | Redis sessions, attempt counters and rate limits | not-started | - | - | - |
| I14 | Web Push adapter and notification consent | not-started | - | - | - |
| R11 | Reporter identity and push endpoints | not-started | - | - | - |
| W32 | PWA manifest, service worker and offline shell | not-started | - | - | - |
| W33 | Reporter set-up: welcome, number check, channel | not-started | - | - | - |
| W34 | Reporter set-up: home screen, notifications, PIN | not-started | - | - | - |
| W35 | Reporter app: PIN entry, respond, confirmation | not-started | - | - | - |
| W36 | Reporter app: booking decision | not-started | - | - | - |
| W37 | Reporter app: recovery and settings | not-started | - | - | - |
| W38 | Reporter app: several services on one phone | not-started | - | - | - |
| U33 | SubscribeAlert use case | not-started | - | - | - |
| U34 | Alert evaluator, acknowledge, snooze and escalation | not-started | - | - | - |
| U35 | Week summary for COO and ICB | not-started | - | - | - |
| R12 | Subscription and alert endpoints | not-started | - | - | - |
| W39 | Exec set-up: alerts, quiet hours, escalation | not-started | - | - | - |
| W40 | Exec home, service detail and alerts | not-started | - | - | - |
| W41 | Exec week summary | not-started | - | - | - |

## S8 Shift lead tools, clinical advice and safety

| Task | Title | Status | Owner | Commit | Evidence |
|---|---|---|---|---|---|
| P18 | Clinical request repository on Neo4j | not-started | - | - | - |
| P20 | Service move and protected text stores on Neo4j | not-started | - | - | - |
| U36 | SuspendService and ResumeService | not-started | - | - | - |
| U37 | RemovePerson, sign out everywhere and lost phone | not-started | - | - | - |
| U38 | Move a service between phones | not-started | - | - | - |
| U39 | Resolve report flags | not-started | - | - | - |
| U40 | Clinical advice requests | not-started | - | - | - |
| U41 | Safety concern and problem report | not-started | - | - | - |
| U42 | Audit replay of what the advisor saw | not-started | - | - | - |
| R13 | Lead, clinical and safety endpoints | not-started | - | - | - |
| R14 | Profiles, $validate and the validator adapter | not-started | - | - | - |
| W42 | Lead: suspend, resume, remove, reports to check | not-started | - | - | - |
| W43 | Lead: phones and services, invite and track set-up | not-started | - | - | - |
| W44 | Clinical advisor screens | not-started | - | - | - |
| W45 | Advisor: ask a clinical advisor, wired | not-started | - | - | - |
| W46 | Help: safety concern, problem report, share session | not-started | - | - | - |
| W47 | Lead: audit replay screen | not-started | - | - | - |
| W55 | Reporter: lost phone and sign out everywhere | not-started | - | - | - |

## S9 Observability and support console

| Task | Title | Status | Owner | Commit | Evidence |
|---|---|---|---|---|---|
| O02 | Browser telemetry module and element ids | not-started | - | - | - |
| O03 | Friction rules engine | not-started | - | - | - |
| O04 | OpenTelemetry Collector with attribute allow-list | not-started | - | - | - |
| O05 | Telemetry schema scan for free text | not-started | - | - | - |
| O06 | Support codes and support access audit | not-started | - | - | - |
| O07 | TelemetryQuery port and Azure Monitor adapter | not-started | - | - | - |
| O08 | Daily telemetry aggregates job | not-started | - | - | - |
| R18 | Support code and console endpoints | not-started | - | - | - |
| W48 | Console: find session, timeline and trace | not-started | - | - | - |
| W49 | Console: funnels, paths, friction, performance, releases | not-started | - | - | - |
| W56 | Help: share my session (support code) | not-started | - | - | - |
| O09 | Synthetic journey checks | not-started | - | - | - |

## S10 Later

| Task | Title | Status | Owner | Commit | Evidence |
|---|---|---|---|---|---|
| I15 | Routing travel-time adapter (once the engine is chosen) | not-started | - | - | - |
| W50 | Map view and travel details | not-started | - | - | - |
| U43 | Planning analysis from decision snapshots | not-started | - | - | - |
| W51 | Planning view | not-started | - | - | - |
| W52 | Product tour by role | not-started | - | - | - |
| W53 | Training lessons and practice mode | not-started | - | - | - |
| G13 | RDF (Turtle) export from the mapper | not-started | - | - | - |
