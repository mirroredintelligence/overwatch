# DIUCS capacity: FHIR R4B data model, property graph and triples
2026-10-23 · @Robert Smith
This model keeps FHIR R4B as the meaning and the wire format, and hydrates every resource into a property graph and into RDF triples. One mapper does both, and a round-trip test proves nothing is lost: FHIR JSON to graph and back must give the same JSON.
## Approach
- **FHIR JSON is canonical.** Each node keeps the full resource as a `json` property for exact round trips. The properties and relationships below are the hydrated form, used for queries and for reasoning.
- **One node per resource, one relationship per reference.** Primitive values become properties. References become relationships. Coded values become shared concept nodes, so "all services that accept falls" is a relationship walk.
- **Semantics come from the FHIR element path.** Every relationship records the FHIR element it came from in `fhirPath`, for example `HealthcareService.providedBy`. The relationship catalogue gives each type its domain, range and cardinality.
- **The same mapper writes triples.** A node becomes `a fhir:ResourceType`. A property becomes `fhir:ResourceType.element`. A reference becomes a link between two IRIs.
### Mapping rules
| # | FHIR construct | Property graph | RDF |
|---|---|---|---|
| R1 | Resource | Node with labels `:Resource` and `:ResourceType`. Properties `id`, `versionId`, `lastUpdated`, `iri`, `json`. | `res:Type/id a fhir:Type` |
| R2 | Primitive element | Property with the element name. Dates as ISO 8601 with zone. Repeating primitives as a list. | `fhir:Type.element` with a typed literal |
| R3 | Reference | Relationship named after the element in upper snake case, with `fhirPath`, `order` if repeating, and `display` if given. | A link from the subject IRI to the target IRI |
| R4 | BackboneElement that repeats or has several parts | Child node `:Type_Element` with a `HAS_ELEMENT` relationship and `order`. | A blank node, or an IRI if it needs identity |
| R5 | CodeableConcept and Coding | Node `(:Concept {system, code, display, version})` shared by every resource of one tenant, never across tenants (DEC-134 item 1, DEC-162). Relationship carries `text` and `userSelected`. `(:Concept)-[:IN_SYSTEM]->(:CodeSystem)`. Hierarchy as `SUBSUMED_BY` where a terminology source provides it. | `skos:Concept` per code, `skos:inScheme`, `skos:broader` |
| R6 | Identifier | `(:Identifier {system, value, use})` unique by system and value within a tenant (DEC-162), `IDENTIFIED_BY` from the resource. Key identifiers are also copied to a property such as `odsCode`. | `fhir:Identifier` node with `system` and `value`, plus `dcterms:identifier` |
| R7 | Period, Quantity, Range | Flattened onto the node or relationship with a prefix: `periodStart`, `periodEnd`, `valueQuantity_value`, `valueQuantity_unit`. | `fhir:Period.start`, `fhir:Quantity.value` |
| R8 | Extension | Property `ext_<shortName>` from an extension registry. A complex extension becomes a child node. | `diucs:` predicate named in the registry |
| R9 | Provenance and AuditEvent | Nodes. `TARGET`, `AGENT` and `ENTITY` relationships. | `prov:wasGeneratedBy`, `prov:wasAssociatedWith`, `prov:used` alongside the FHIR triples |
| R10 | Versions | Current node plus an immutable `(:ResourceVersion)` snapshot per update, linked by `HAS_VERSION`. Observations are never updated. | `res:Type/id/_history/n` |
| R11 | Frequently filtered code | The node also stores `<element>Code` as a property, for example `measureCode`. | Not needed |

Property names use lower camel case. Labels are the FHIR resource names. Relationship types are upper snake case.
## Identifiers, namespaces and code systems
The base address below is a placeholder. Replace it with the real domain before any identifier is minted, because identifiers cannot change afterwards.
| Item | Value |
|---|---|
| Base for instances | `https://diucs.example/fhir/` |
| Resource IRI | `{base}{ResourceType}/{id}` |
| Version IRI | `{base}{ResourceType}/{id}/_history/{versionId}` |
| Ontology namespace (`diucs:`) | `https://diucs.example/def#` |
| Local code systems | `https://diucs.example/CodeSystem/{name}` |
| Resource ids | Random UUIDs. Never meaningful, never reused. |
| RDF prefixes | `fhir:` `http://hl7.org/fhir/`, `rdf:`, `rdfs:`, `xsd:`, `skos:`, `dcterms:`, `prov:` `http://www.w3.org/ns/prov#`, `res:` instances, `diucs:` ontology |

### Code systems
| Code system | URL | Used for | Note |
|---|---|---|---|
| SNOMED CT | `http://snomed.info/sct` | Needs, specialties, concepts with a SNOMED code | Licensing and the UK edition come through NHS England. Confirm access. |
| UCUM | `http://unitsofmeasure.org` | Units, with annotations such as `{referral}` and `{bed}` |  |
| ODS organisation and site codes | NHS ODS identifier systems | Organization and Location identifiers | **Verify the exact system URIs** against the NHS England FHIR documentation before use |
| service-category | local | Urgent community response, same day emergency care, inpatient beds, hospital at home or virtual ward, reablement | Map to SNOMED or the Directory of Services where a code exists |
| capacity-measure | local | free-slots, free-beds, referrals-acceptable, occupied-patients, packages-free | The measure an Observation reports |
| report-source | local | text, link, app, email, advisor-phoned, feed | `Observation.method` |
| status | local | accepting, limited, not-accepting, over-capacity, not-updated, out-of-hours | Derived value, stored as an interpretation at report time |
| need-category | local, mapped to SNOMED | Fall without injury, frailty, wound care, IV therapy, palliative, dementia | Criteria and cases use the same concepts |
| urgency | local | within-2-hrs, today, planned | Maps to `ServiceRequest.priority` |
| age-band | local | 0-15, 16-64, 65-79, 80+ |  |
| acuity-method | local | pathways-dx, ambulance-category, manchester, news2, cfs | Observation codes for the referrer's score. Map to SNOMED or LOINC where a code exists. |
| booking-business-status | local | requested, confirmed, declined, expired, cancelled-before, cancelled-after, withdrawn, not-reached, completed | `Task.businessStatus` |
| decline-reason, cancel-reason, withdraw-reason | local | Short fixed lists |  |
| registration-status | local | invited, draft, submitted, in-review, needs-changes, approved, live, not-approved, paused, reverify |  |
| criteria-status | local | draft, pending-approval, current, superseded, retired |  |
| channel | local | text, email, push |  |
| alert-kind | local | service-closed, over-capacity, not-updated, system-pressure |  |
| message-id | local | The catalogue ids C1 to K4 | `Communication.topic` |
| safety-concern-category | local | To be agreed with the clinical safety officer |  |

## Resource inventory
Nineteen resource types carry the product. Only the case resources can hold anything about a patient (the Patient stub, the ServiceRequest and the score Observations), and none holds a name or an NHS number.
| Resource | Use here | Patient data? | Why this resource |
|---|---|---|---|
| Organization | The provider and parent bodies | No | Standard home for an organisation and its ODS code |
| Location | A site, ward, or an area such as a postcode district | No | Has a position and opening hours |
| HealthcareService | A service that takes referrals | No | The thing advisors choose between |
| Endpoint | A technical API a service exposes | No | For later integration. Stored, not used in the pilot. |
| Practitioner | A person who reports or approves | Staff personal data | Keeps a person separate from the post they fill |
| PractitionerRole | A post at a service: duty manager, criteria owner, clinical lead | Staff personal data | Carries the link to the service, so a phone that covers several services has several roles |
| Device | A wall screen, or an installed app | No | A paired device with a hashed token |
| Consent | A staff member's consent to notifications | Staff personal data | Records date, device and wording shown |
| Observation | A capacity report, and a referrer's score for a case | Scores only, on the stub | Immutable measurements with time and source |
| Basic | Service criteria versions, and service flags such as suspended | No | No base resource fits a versioned criteria set. Basic is the extension point, with a profile. |
| Patient | A case stub | Age band and postcode, until closed | Needed because a request must have a subject |
| ServiceRequest | A case: need, urgency, and the destination chosen | Yes, on the stub | Holds what is being asked for |
| Task | A booking request, a registration, a criteria approval, an alert acknowledgement, a safety concern | Booking: reference to the case | A request to someone, with a status and an owner |
| Communication | One per message sent, with delivery status | No | The record of what we told whom |
| SubscriptionTopic, Subscription | What an exec user wants alerts about | No | Standard subscription model |
| List | The scope list | No | A curated list of services with a flag per entry |
| AuditEvent | Who did what | References only | Append-only record |
| Provenance | Where a resource came from and who approved it | No | Source channel and approvals |

Also used: CodeSystem, ValueSet and ConceptMap for terminology, StructureDefinition for our profiles, CapabilityStatement, and OperationDefinition for the custom operations.
**Subject limits worth knowing.** In R4B, Observation.subject cannot point at a HealthcareService, so a capacity report uses `focus` for the service and `subject` for the site. Flag cannot point at a HealthcareService either, so service flags use Basic. Verify both against the 4.3.0 specification.
## Services and places
The four registration resources, hydrated. "Required" is our profile, not base R4B.
### Organization
| Graph form | FHIR element | Required |
|---|---|---|
| Properties `id`, `active`, `name`, `alias[]`, `odsCode` | Organization.active, name, alias, identifier | name, ODS code |
| `-[:IDENTIFIED_BY]->(:Identifier)` | identifier | Yes |
| `-[:TYPE]->(:Concept)` | type | Yes |
| `-[:PART_OF]->(:Organization)` | partOf | No |
| `-[:HAS_TELECOM]->(:ContactPoint {system, value, use, rank})` | telecom | One of telecom or contact |
| `-[:HAS_ADDRESS]->(:Address)` | address | No |
| `-[:HAS_CONTACT]->(:Organization_Contact)` then `-[:PURPOSE]->(:Concept)`, `-[:HAS_TELECOM]->(:ContactPoint)` | contact | One contact for registration |
| `-[:HAS_ENDPOINT]->(:Endpoint)` | endpoint | No |

### Location
| Graph form | FHIR element | Required |
|---|---|---|
| Properties `id`, `status`, `name`, `alias[]`, `description`, `mode`, `positionLatitude`, `positionLongitude`, `position` (a spatial point) | status, name, description, mode, position | name, status. Position for a fixed site. |
| Extension properties `ext_geocodeSource`, `ext_geocodedAt`, `ext_uprn` | Extensions | Set by the geocoder |
| `-[:IDENTIFIED_BY]->(:Identifier)` | identifier | Site ODS code if any |
| `-[:TYPE]->(:Concept)`, `-[:PHYSICAL_TYPE]->(:Concept)` | type, physicalType | Yes |
| `-[:HAS_ADDRESS]->(:Address {line[], city, district, postalCode, country})` | address | Fixed site |
| `-[:MANAGING_ORGANIZATION]->(:Organization)` | managingOrganization | Yes |
| `-[:PART_OF]->(:Location)` | partOf | No |
| `-[:HAS_HOURS]->(:Location_HoursOfOperation {daysOfWeek[], allDay, openingTime, closingTime})` | hoursOfOperation | Yes, or all day |
| `-[:HAS_TELECOM]->(:ContactPoint)` | telecom | No |

An area such as a postcode district is a Location with `mode = kind` and a `type` of postcode-district. A visiting service points at these through `COVERAGE_AREA`.
### HealthcareService
| Graph form | FHIR element | Required |
|---|---|---|
| Properties `id`, `active`, `name`, `comment`, `extraDetails`, `appointmentRequired`, `availabilityExceptions` | Same names | name, active |
| Extension properties `ext_smsShortName`, `ext_establishedCapacity`, `ext_canExceedEstablished`, `ext_usualRangeMin`, `ext_usualRangeMax`, `ext_reportCadence`, `ext_limitedLevelPercent` | Local extensions | Yes, set at registration |
| `-[:PROVIDED_BY]->(:Organization)` | providedBy | Yes |
| `-[:CATEGORY]->(:Concept)`, `-[:TYPE]->`, `-[:SPECIALTY]->` | category, type, specialty | category |
| `-[:LOCATION]->(:Location)` | location | Unless area based |
| `-[:COVERAGE_AREA]->(:Location)` | coverageArea | If visiting |
| `-[:REFERRAL_METHOD]->(:Concept)` | referralMethod | Yes |
| `-[:HAS_TELECOM]->(:ContactPoint {system:'phone'})` | telecom | SPOA phone |
| `-[:HAS_AVAILABLE_TIME]->(:HealthcareService_AvailableTime {daysOfWeek[], allDay, availableStartTime, availableEndTime})` | availableTime | Yes |
| `-[:HAS_NOT_AVAILABLE]->(:HealthcareService_NotAvailable {description, periodStart, periodEnd})` | notAvailable | No |
| `-[:HAS_ELIGIBILITY]->(:HealthcareService_Eligibility {comment})` then `-[:CODE]->(:Concept)` | eligibility | Yes |
| `-[:HAS_ENDPOINT]->(:Endpoint)` | endpoint | No |
| `-[:CURRENT_CRITERIA]->(:Basic)` | Local extension, points at the current criteria version | Yes |
| `-[:CHARACTERISTIC]->(:Concept)`, `-[:PROGRAM]->`, `-[:COMMUNICATION]->`, `-[:SERVICE_PROVISION_CODE]->` | Same names | No |

### Endpoint
| Graph form | FHIR element | Required |
|---|---|---|
| Properties `id`, `status`, `name`, `address`, `payloadMimeType[]`, `header[]`, `periodStart`, `periodEnd` | Same names | status, address |
| `-[:CONNECTION_TYPE]->(:Concept)` | connectionType | Yes |
| `-[:PAYLOAD_TYPE]->(:Concept)` | payloadType | Yes |
| `-[:MANAGING_ORGANIZATION]->(:Organization)` | managingOrganization | No |
| `-[:HAS_CONTACT]->(:ContactPoint)` | contact | No |

## People, devices and consent
A person is separate from the post they fill. The post carries the service link, so a phone that looks after three services is one Practitioner with three PractitionerRoles. When the person leaves, the post stays and a new person fills it.
| Node | Graph form | Notes |
|---|---|---|
| Practitioner | Properties `id`, `active`, `name`, `phoneHash`, `emailDomain`. `-[:HAS_ROLE]` is the reverse of PractitionerRole `PRACTITIONER`. | The phone number itself is in the protected store. The graph holds a keyed hash to find the phone. Not a patient. |
| PractitionerRole | Properties `id`, `active`, `periodStart`, `periodEnd`. `-[:PRACTITIONER]->(:Practitioner)`, `-[:ORGANIZATION]->`, `-[:HEALTHCARE_SERVICE]->(:HealthcareService)`, `-[:CODE]->(:Concept)` (duty manager, coordinator, criteria owner, clinical lead, shift lead, reviewer), `-[:HAS_TELECOM]->` for a role phone or inbox | A role phone survives a change of person |
| Device | Properties `id`, `status`, `tokenHash`, `deviceName`. `-[:TYPE]->(:Concept)` (wall-display, mobile-app). `-[:LOCATION]->(:Location)`, `-[:OWNER]->(:Organization)` | A wall display holds no patient data. An installed app is linked to a Practitioner by the push subscription. |
| Consent | Properties `id`, `status`, `dateTime`, `wordingVersion`. `-[:PERFORMER]->(:Practitioner)`, `-[:CATEGORY]->(:Concept)` (notification) | Consent is patient-centred in R4B, so this uses `performer`, and the scope code may need a local value. Verify the binding. If it does not fit, use Basic with a profile. |

Sessions, PINs and one-time codes are not FHIR and are not in the graph. The identity adapter holds them.
## Capacity and criteria
### Capacity report (Observation)
| Graph form | FHIR element | Notes |
|---|---|---|
| Properties `id`, `status` (final), `effectiveDateTime`, `issued`, `valueQuantity_value`, `valueQuantity_unit`, `valueQuantity_system`, `valueQuantity_code`, `measureCode` | status, effective, issued, value | Value is whole number with UCUM annotation `{referral}`, `{bed}`, `{slot}`, `{patient}` |
| `-[:FOCUS]->(:HealthcareService)` | focus | The service reported on |
| `-[:SUBJECT]->(:Location)` | subject | The site, if there is one |
| `-[:PERFORMER]->(:PractitionerRole)` | performer | The post that reported |
| `-[:CODE]->(:Concept)` | code | From the capacity-measure code system |
| `-[:METHOD]->(:Concept)` | method | The report source: text, link, app, email, advisor-phoned |
| `-[:INTERPRETATION]->(:Concept)` | interpretation | The status at report time |
| `-[:DERIVED_FROM]->(:Observation)` | derivedFrom | The report this one confirms, for a Y |
| `-[:HAS_COMPONENT]->(:Observation_Component {valueQuantity_value})` then `-[:CODE]->(:Concept)` | component | Optional sub-type counts such as women only or side room |
| Property `ext_reportType` | Extension | number, confirmed |

Reports are never updated. A correction is a new report. The latest is found by `effectiveDateTime`.
### Criteria (Basic, profile ServiceCriteria)
| Graph form | Notes |
|---|---|
| Labels `:Basic:ServiceCriteria`. Properties `id`, `version`, `status`, `ageMin`, `ageMax`, `postcodeDistricts[]`, `reviewBy`, `createdAt`, `changeReason` | `status` from the criteria-status code system |
| `-[:SUBJECT]->(:HealthcareService)` | The service the criteria describe |
| `-[:ACCEPTS_NEED]->(:Concept)`, `-[:EXCLUDES_NEED]->(:Concept)` | The matching relationships. Each can carry `note`. |
| `-[:AUTHOR]->(:PractitionerRole)` | The owner |
| `-[:APPROVED_BY {role, at}]->(:PractitionerRole)` | The owner and the second approver |
| `-[:SUPERSEDES]->(:Basic)` | The previous version. Old versions are never deleted. |

The service points at the version advisors should use through `CURRENT_CRITERIA`. A case keeps the version it saw in its audit snapshot.
### Service flags (Basic, profile ServiceFlag)
`(:Basic:ServiceFlag {status, code})-[:SUBJECT]->(:HealthcareService)`, with codes `suspended` and `criteria-overdue`, a reason, and the actor. A suspended flag makes the status rules return Not updated.
### Status rules as data
The rule parameters sit on the HealthcareService as the extension properties above. The rules themselves are code in the domain, covered by tests, because a rule that changes must be released and reviewed like code.
## Scope list, registration and approvals
### Scope list (List)
| Graph form | Notes |
|---|---|
| `(:List {id, status, title, date})` with code scope-list | One list for the pilot |
| `-[:ENTRY {flag, date, reason}]->(:HealthcareService)` | `flag` is in-pilot, later or out-of-scope. An entry exists before the service registers, so the service starts as an inactive HealthcareService. |
| `-[:SOURCE]->(:PractitionerRole)` | Who owns the list |

Invitations can only be created for entries flagged in-pilot.
### Registration (Task, code register-service)
| Graph form | Notes |
|---|---|
| Properties `id`, `status`, `businessStatus` (registration-status), `authoredOn`, `lastModified`, `priority` | `status` follows the Task states. `businessStatus` carries invited, draft, submitted, in-review, needs-changes, approved, live, not-approved, paused, reverify. |
| `-[:FOCUS]->(:HealthcareService)` | What is being registered |
| `-[:REQUESTER]->(:PractitionerRole)` | The applicant |
| `-[:OWNER]->(:PractitionerRole)` | The reviewer |
| `-[:PART_OF]->(:Task)` | The checks are sub-Tasks: call-back, scope decision, criteria approval, go-live test |
| `-[:OUTPUT {type}]->(:Observation)` | The go-live test response |

### Checks as provenance
Each check is a Provenance record: `(:Provenance)-[:TARGET]->(:Task)`, `-[:AGENT {type:'verifier'}]->(:PractitionerRole)`, with `activity` (call-back, scope-decision, criteria-approval) and `recorded`. The call-back also records the number called and the role spoken to as properties on the Provenance, not as free text.
### Invitation
A Task with code invite-reporter: `-[:FOCUS]->(:HealthcareService)`, `-[:OWNER]->(:Practitioner)` (the invitee), `-[:REQUESTER]->(:PractitionerRole)` (the shift lead), `restriction.period` of 48 hours. The token is held by the link adapter, never in the graph.
### Criteria approval and change (Task, code approve-criteria)
`-[:FOCUS]->(:Basic)` (the new criteria), `-[:REQUESTER]->(:PractitionerRole)` (the owner), `-[:OWNER]->(:PractitionerRole)` (the clinical lead), `businessStatus` pending, approved or sent-back, and a `statusReason` code. On approval the service's `CURRENT_CRITERIA` moves to the new version and the old one gets `SUPERSEDES` from the new.
## Cases and bookings
A case is a pseudonymous stub. It exists so a request has a subject and so the options shown can be audited. It holds no name and no NHS number. The postcode and needs are cleared when the case closes.
### Patient stub
| Graph form | Notes |
|---|---|
| `(:Patient {id, active:true, ageBand, postalCode})` | `postalCode` is transient and removed at close. `ageBand` is a concept from the age-band code system. |
| Tag and security label | `meta.tag` pseudonymised-case-stub. `meta.security` restricted. |
| No `name`, `identifier`, `birthDate`, `telecom` | Enforced by the profile. The validator rejects them. |

### Case (ServiceRequest)
| Graph form | FHIR element | Notes |
|---|---|---|
| Properties `id`, `status`, `intent`, `priority`, `authoredOn`, `occurrenceDateTime`, `ext_referrerType` | status, intent, priority, authoredOn | `intent` is plan. `priority` is urgent for within 2 hrs and routine for today or planned. |
| `-[:SUBJECT]->(:Patient)` | subject | The stub |
| `-[:REQUESTER]->(:Practitioner)` | requester | The advisor |
| `-[:PERFORMER]->(:HealthcareService)` | performer | The destination, once chosen |
| `-[:REASON_CODE]->(:Concept)` | reasonCode | The needs, from need-category |
| `-[:CODE]->(:Concept)` | code | Primary need |
| `-[:SUPPORTING_INFO]->(:Observation)` | supportingInfo | The referrer's scores |
| `-[:CRITERIA_SEEN]->(:Basic)` | Local extension | The criteria versions shown to the advisor |

### Referrer score (Observation)
`(:Observation {status:'final', valueInteger or valueCodeableConcept})-[:SUBJECT]->(:Patient)` with `-[:CODE]->(:Concept)` from acuity-method (news2, cfs, ambulance-category, manchester, pathways-dx). The value is recorded as the referrer gave it. Nothing is calculated.
### Booking (Task, code booking-request)
| Graph form | FHIR element | Notes |
|---|---|---|
| Properties `id`, `status`, `businessStatus`, `intent` (order), `authoredOn`, `lastModified`, `reference` | status, businessStatus, identifier | `reference` is the booking reference in the message |
| `-[:FOCUS]->(:ServiceRequest)` | focus | Removed from the service's view |
| `-[:FOR]->(:Patient)` | for | Removed from the service's view |
| `-[:OWNER]->(:HealthcareService)` | owner | The service asked to act |
| `-[:REQUESTER]->(:Practitioner)` | requester | The advisor |
| Properties `restrictionPeriodEnd` | restriction.period | The reply-by time |
| `-[:STATUS_REASON]->(:Concept)` | statusReason | Expired, withdrawn, and reasons from the decline, cancel and withdraw code systems |
| `-[:OUTPUT {type}]->(:Concept)` | output | The decision and the reason digit |
| Properties `executionPeriodStart`, `executionPeriodEnd` | executionPeriod | Requested to resolved |

### Message record (Communication)
| Graph form | Notes |
|---|---|
| Properties `id`, `status`, `sent`, `received`, `payloadText`, `deliveryStatus`, `providerMessageId` | `payloadText` is the text sent, which contains no patient data |
| `-[:TOPIC]->(:Concept)` | Catalogue id, for example C1 |
| `-[:MEDIUM]->(:Concept)` | text, email or push |
| `-[:RECIPIENT]->(:PractitionerRole)`, `-[:SENDER]->(:Device)` |  |
| `-[:ABOUT]->(:Task)` or `(:Observation)` or `(:HealthcareService)` | What it concerned |
| `-[:IN_RESPONSE_TO]->(:Communication)` | Threads a reply to the prompt it answered |

## Alerts, audit and provenance
### Subscriptions
Use the R4B subscription resources for what a user wants to hear about. I have not verified the exact R4B element names, so check them against 4.3.0 before building.
| Graph form | Notes |
|---|---|
| `(:SubscriptionTopic {id, status, title, url})` with `-[:TRIGGER]->` a resource trigger description | One topic per alert kind. The `url` is a canonical for the topic. |
| `(:Subscription {id, status, channelType, end})-[:TOPIC]->(:SubscriptionTopic)` | One per user per alert kind |
| `-[:CONTACT]->(:Practitioner)` | The subscriber |
| Filter properties | Thresholds such as 2 or 4 hours for not updated, services followed, quiet hours |

### Alert and acknowledgement (Task, code acknowledge-alert)
| Graph form | Notes |
|---|---|
| Properties `id`, `status`, `businessStatus` (new, acknowledged, escalated, closed), `authoredOn`, `lastModified` |  |
| `-[:FOCUS]->(:HealthcareService)` or `(:Observation)` | The service or report that triggered it |
| `-[:OWNER]->(:PractitionerRole)` | The person alerted. An escalation is a new Task with `PART_OF` the first, owned by the deputy. |
| `-[:BASED_ON]->(:Subscription)` | Why they were alerted |

### Safety concern (Task, code safety-concern)
`-[:REQUESTER]->(:Practitioner)`, `-[:OWNER]->(:PractitionerRole)` (clinical safety officer), `-[:CODE]->(:Concept)` from safety-concern-category, `-[:FOCUS]->` the case or service if given, and a `reference`. No free text is stored in the graph. Any free text goes to a protected store the safety officer reads.
### AuditEvent
| Graph form | Notes |
|---|---|
| Properties `id`, `action` (C, R, U, D, E), `recorded`, `outcome`, `sourceObserver` | One per command |
| `-[:TYPE]->(:Concept)`, `-[:SUBTYPE]->(:Concept)` | The use case name, for example RequestBooking |
| `-[:AGENT {role, networkAddressHash, requestor}]->(:Practitioner or :Device)` | Who |
| `-[:ENTITY {role}]->(any resource)` | What was touched |
| `-[:SNAPSHOT]->(:Snapshot {hash})` | What was shown: every status, number, data age and criteria version at the moment of a decision. The body is a JSON property on the Snapshot node, split into one node per service if it grows large. |

### Provenance
| Graph form | Notes |
|---|---|
| Properties `id`, `recorded` |  |
| `-[:TARGET]->(resource version)` | What it describes |
| `-[:AGENT {type, role}]->(:Practitioner, :PractitionerRole or :Device)` | Who or what produced it. For a text reply, the Device is the provider gateway and the role is the reporter. |
| `-[:ENTITY {role:'source'}]->(:Communication)` | The inbound message the report came from |
| `-[:ACTIVITY]->(:Concept)` | create, confirm, approve, call-back |
| Property `chainHash` | Hash of this record and the previous one, for tamper evidence |

Audit and provenance records are append-only and never edited or deleted.
### Platform nodes (not FHIR)
Neo4j is the only database, so operational state that is not a FHIR resource is also nodes. They are kept apart by label, and no FHIR resource points at them except where shown.
| Node | Properties | Relationships | Purpose |
|---|---|---|---|
| `OutboxMessage` | `id`, `topic`, `eventType`, `payloadJson`, `status`, `attempts`, `createdAt`, `publishedAt` | `-[:FOR]->` the resource the event is about | The outbox. Written in the same transaction as the change. A relay publishes it to Service Bus. |
| `ScheduledWork` | `id`, `kind`, `dueAt`, `sequenceNumber`, `status` | `-[:ABOUT]->` a Task, HealthcareService or Practitioner | The handle to a scheduled Service Bus message, so it can be cancelled |
| `LinkToken` | `id`, `tokenHash`, `phoneHash`, `purpose`, `expiresAt`, `usedAt` | `-[:FOR_PROMPT]->` a Communication or Task | Single-use link tokens. The token itself is never stored. |
| `Processed` | `messageId`, `consumer`, `processedAt` | None | Idempotency for consumers. Cleared by a cleanup job. |
| `UiSession` | `id`, `role`, `deviceType`, `appMode`, `release`, `startedAt`, `endedAt` | `-[:SHARED_VIA]->(:SupportCode)` | A pseudonymous session. No person link. |
| `SupportCode` | `codeHash`, `createdAt`, `expiresAt` | `-[:SHARED_BY]->(:Practitioner)` | The only link from a session to a person, created by the person, and it expires |
| `SupportAccess` | `id`, `openedAt`, `reason`, `expiresAt` | `-[:OPENED_BY]->(:Practitioner)`, `-[:OPENED]->(:UiSession)` | Audit of every support open, shown to the person |
| `FunnelDaily` | `funnel`, `step`, `date`, `role`, `channel`, `device`, `entered`, `completed`, `medianMs` | None | Funnel aggregates. Groups under 10 are suppressed at read time. |
| `FrictionDaily` | `date`, `elementId`, `kind`, `role`, `device`, `interactions`, `events` | None | Friction aggregates by element |
| `ElementUsageDaily` | `date`, `elementId`, `role`, `device`, `interactions` | None | Which controls are used, and which never |
| `RouteDaily` | `date`, `route`, `role`, `device`, `p50`, `p75`, `p95`, `lcp75`, `inp75`, `cls75`, `errors` | None | Performance by route |
| `QueryStatDaily` | `date`, `queryId`, `calls`, `p50`, `p95`, `errors` | None | Performance by named Cypher query |

The daily aggregate nodes are written by a scheduled job from Azure Monitor. They hold no person and no free text.
**Added while tracing every control to its Cypher.** Two more platform nodes: `Credential` (`deviceId`, `pinHash`, `failed`, `lockedUntil`, `updatedAt`, reached by `-[:HAS_CREDENTIAL]` from a Practitioner) and `LessonProgress` (`lessonId`, `status`, `updatedAt`, reached by `-[:HAS_PROGRESS]`, visible to the person only). Six local relationships that are not FHIR elements: `USED_BY` (Device to Practitioner), `HAS_CREDENTIAL`, `HAS_PROGRESS`, `OUTCOME` (ServiceRequest to Concept, with `reasons`), `CHANNEL` (PractitionerRole to Concept) and `COVERED_BY` (PractitionerRole to Practitioner, with `until`).
A third platform node, `ReportFlag` (`id`, `reason`, `status`, `outcome`, `createdAt`, `resolvedAt`), reached by `-[:ON]->(:Observation)`. The domain creates one when a capacity report breaks a rule, for example an out-of-range number sent twice or many changes in a short time. The shift lead resolves it. It is a separate node because capacity reports are never edited.
## Relationship catalogue
Every relationship carries `fhirPath` (the element it came from). `order` is added where the element repeats. Cardinality is the FHIR cardinality unless marked local.
| Relationship | From to | FHIR element | Other properties |
|---|---|---|---|
| IDENTIFIED_BY | Any resource to Identifier | identifier | use, period |
| TYPE, CATEGORY, SPECIALTY, CODE, METHOD, INTERPRETATION, STATUS_REASON | Resource to Concept | element of the same name | text, userSelected |
| CONNECTION_TYPE, PAYLOAD_TYPE, REFERRAL_METHOD, PHYSICAL_TYPE, CHARACTERISTIC, PROGRAM, COMMUNICATION, SERVICE_PROVISION_CODE | Resource to Concept | element of the same name | text |
| IN_SYSTEM | Concept to CodeSystem | Coding.system |  |
| SUBSUMED_BY | Concept to Concept | Terminology hierarchy, derived | source |
| PART_OF | Organization to Organization. Location to Location. Task to Task. | partOf |  |
| PROVIDED_BY | HealthcareService to Organization | providedBy |  |
| MANAGING_ORGANIZATION | Location, Endpoint to Organization | managingOrganization |  |
| LOCATION | HealthcareService to Location. Device to Location. | location |  |
| COVERAGE_AREA | HealthcareService to Location (area) | coverageArea |  |
| HAS_ENDPOINT | Organization, Location, HealthcareService to Endpoint | endpoint |  |
| HAS_ADDRESS | Organization, Location to Address | address | use, type, period |
| HAS_TELECOM | Organization, Location, HealthcareService, PractitionerRole to ContactPoint | telecom | rank |
| HAS_CONTACT | Organization to Organization_Contact. Endpoint to ContactPoint. | contact | purpose |
| HAS_HOURS | Location to Location_HoursOfOperation | hoursOfOperation |  |
| HAS_AVAILABLE_TIME, HAS_NOT_AVAILABLE, HAS_ELIGIBILITY | HealthcareService to its backbone nodes | availableTime, notAvailable, eligibility |  |
| CURRENT_CRITERIA | HealthcareService to Basic | Local |  |
| PRACTITIONER, ORGANIZATION, HEALTHCARE_SERVICE | PractitionerRole to Practitioner, Organization, HealthcareService | same names |  |
| FOCUS | Observation to HealthcareService. Task to ServiceRequest, HealthcareService, Basic or Observation. | focus |  |
| SUBJECT | Observation to Location (capacity) or Patient (score). Basic to HealthcareService. ServiceRequest to Patient. | subject |  |
| PERFORMER | Observation to PractitionerRole. ServiceRequest to HealthcareService. Consent to Practitioner. | performer |  |
| DERIVED_FROM | Observation to Observation | derivedFrom |  |
| HAS_COMPONENT | Observation to Observation_Component | component |  |
| REQUESTER | ServiceRequest, Task to Practitioner or PractitionerRole | requester |  |
| OWNER | Task to HealthcareService, PractitionerRole or Practitioner | owner |  |
| FOR | Task to Patient | for |  |
| BASED_ON | Task to Subscription or Task | basedOn |  |
| REASON_CODE | ServiceRequest to Concept (need) | reasonCode |  |
| SUPPORTING_INFO | ServiceRequest to Observation | supportingInfo |  |
| CRITERIA_SEEN | ServiceRequest to Basic | Local | shownAt |
| OUTPUT | Task to Observation or Concept | output | type |
| ENTRY | List to HealthcareService | entry.item | flag, date, reason |
| ACCEPTS_NEED, EXCLUDES_NEED | Basic (criteria) to Concept (need) | Local | note |
| SUBJECT (criteria) | Basic to HealthcareService | subject |  |
| AUTHOR, APPROVED_BY | Basic to PractitionerRole | author, local | role, at |
| SUPERSEDES | Basic to Basic | Local |  |
| TOPIC | Communication to Concept. Subscription to SubscriptionTopic. | topic |  |
| MEDIUM | Communication to Concept | medium |  |
| RECIPIENT, SENDER | Communication to PractitionerRole, Device | recipient, sender |  |
| ABOUT | Communication to Task, Observation, HealthcareService | about |  |
| IN_RESPONSE_TO | Communication to Communication | inResponseTo |  |
| CONTACT | Subscription to Practitioner | contact |  |
| TARGET | Provenance to resource version | target |  |
| AGENT | Provenance, AuditEvent to Practitioner, PractitionerRole, Device | agent | type, role, requestor |
| ENTITY | Provenance, AuditEvent to any resource | entity | role |
| ACTIVITY | Provenance to Concept | activity |  |
| SNAPSHOT | AuditEvent to Snapshot | Local | hash |
| HAS_VERSION | Resource to ResourceVersion | History | versionId |
| ACCEPTED_BY (derived) | Concept (need) to HealthcareService | Derived from the current criteria | criteriaVersion |
| NEAR (derived cache) | Location to Location | Derived | travelLow, travelHigh, source, computedAt |

## RDF triples
The triples are produced by the same mapper as the graph. This section shows the **query projection**: primitives are direct literals, which is easy to read and to query. For exchange with other systems, serialise with the official FHIR RDF form, which wraps primitives in value nodes. I have not validated these examples against the FHIR ShEx schemas, so run them through a validator before relying on them.
### How a graph element becomes triples
| Graph | Triples |
|---|---|
| Node `(:HealthcareService {id, name})` | `res:HealthcareService/id a fhir:HealthcareService ; fhir:HealthcareService.name "..."` |
| Property of type date or time | A literal typed `xsd:dateTime`, `xsd:date` or `xsd:time` |
| Relationship `-[:PROVIDED_BY]->` | `fhir:HealthcareService.providedBy res:Organization/id` |
| Relationship to a `Concept` | `fhir:HealthcareService.category cs:service-category#urgent-community-response`. The concept is `a skos:Concept ; skos:inScheme cs:service-category ; skos:notation "code" ; skos:prefLabel "display"@en`. |
| Backbone child node | A blank node, or an IRI when it needs identity, linked with `fhir:HealthcareService.availableTime` |
| Relationship property such as `APPROVED_BY {role, at}` | A qualified relation: `prov:qualifiedAssociation [ a prov:Association ; prov:agent X ; prov:hadRole diucs:SecondApprover ; prov:atTime "..."^^xsd:dateTime ]`. Plain RDF cannot hold a property on a triple without this. |
| `ResourceVersion` snapshot | A named graph per version, so history can be queried |

### Ontology terms (diucs:)
```
@prefix diucs: <https://diucs.example/def#> .
@prefix fhir:  <http://hl7.org/fhir/> .
@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos:  <http://www.w3.org/2004/02/skos/core#> .

diucs:CapacityReport       a owl:Class ; rdfs:subClassOf fhir:Observation ;    rdfs:label "Capacity report" .
diucs:ServiceCriteria      a owl:Class ; rdfs:subClassOf fhir:Basic ;          rdfs:label "Service criteria version" .
diucs:ServiceFlag          a owl:Class ; rdfs:subClassOf fhir:Basic ;          rdfs:label "Service flag" .
diucs:BookingRequest       a owl:Class ; rdfs:subClassOf fhir:Task ;           rdfs:label "Booking request" .
diucs:Registration         a owl:Class ; rdfs:subClassOf fhir:Task ;           rdfs:label "Service registration" .
diucs:Case                 a owl:Class ; rdfs:subClassOf fhir:ServiceRequest ; rdfs:label "Case" .
diucs:AlertAcknowledgement a owl:Class ; rdfs:subClassOf fhir:Task .

diucs:StatusScheme a skos:ConceptScheme ; skos:prefLabel "Service status"@en .
diucs:Accepting    a skos:Concept ; skos:inScheme diucs:StatusScheme ; skos:prefLabel "Accepting"@en .
diucs:Limited      a skos:Concept ; skos:inScheme diucs:StatusScheme ; skos:prefLabel "Limited"@en .
diucs:NotAccepting a skos:Concept ; skos:inScheme diucs:StatusScheme ; skos:prefLabel "Not accepting"@en .
diucs:OverCapacity a skos:Concept ; skos:inScheme diucs:StatusScheme ; skos:prefLabel "Over capacity"@en .
diucs:NotUpdated   a skos:Concept ; skos:inScheme diucs:StatusScheme ; skos:prefLabel "Not updated"@en .
diucs:OutOfHours   a skos:Concept ; skos:inScheme diucs:StatusScheme ; skos:prefLabel "Out of hours"@en .

diucs:currentCriteria a owl:ObjectProperty ; rdfs:domain fhir:HealthcareService ; rdfs:range diucs:ServiceCriteria .
diucs:acceptsNeed     a owl:ObjectProperty ; rdfs:domain diucs:ServiceCriteria ;     rdfs:range skos:Concept .
diucs:excludesNeed    a owl:ObjectProperty ; rdfs:domain diucs:ServiceCriteria ;     rdfs:range skos:Concept .
diucs:supersedes      a owl:ObjectProperty ; rdfs:domain diucs:ServiceCriteria ;     rdfs:range diucs:ServiceCriteria .
diucs:reportType      a owl:DatatypeProperty ; rdfs:domain diucs:CapacityReport .
diucs:version         a owl:DatatypeProperty ; rdfs:domain diucs:ServiceCriteria .
```
### Worked example: a service
```
@prefix res:  <https://diucs.example/fhir/> .
@prefix cs:   <https://diucs.example/CodeSystem/> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

res:HealthcareService/a1 a fhir:HealthcareService ;
    fhir:HealthcareService.active true ;
    fhir:HealthcareService.name "UCR West" ;
    fhir:HealthcareService.providedBy res:Organization/o1 ;
    fhir:HealthcareService.category cs:service-category#urgent-community-response ;
    fhir:HealthcareService.coverageArea res:Location/d3, res:Location/d4 ;
    fhir:HealthcareService.referralMethod cs:referral-method#phone ;
    diucs:currentCriteria res:Basic/c3 .

res:Location/d3 a fhir:Location ;
    fhir:Location.name "DT3" ;
    fhir:Location.mode "kind" ;
    fhir:Location.type cs:location-type#postcode-district .
```
### Worked example: a capacity report and where it came from
```
@prefix prov: <http://www.w3.org/ns/prov#> .

res:Observation/r9 a fhir:Observation, diucs:CapacityReport ;
    fhir:Observation.status "final" ;
    fhir:Observation.focus res:HealthcareService/a1 ;
    fhir:Observation.performer res:PractitionerRole/pr7 ;
    fhir:Observation.code cs:capacity-measure#referrals-acceptable ;
    fhir:Observation.method cs:report-source#text ;
    fhir:Observation.effectiveDateTime "2026-10-23T13:12:00Z"^^xsd:dateTime ;
    fhir:Observation.valueQuantity [ a fhir:Quantity ;
        fhir:Quantity.value 3 ;
        fhir:Quantity.system <http://unitsofmeasure.org> ;
        fhir:Quantity.code "{referral}" ] ;
    diucs:reportType "number" ;
    prov:wasGeneratedBy res:Provenance/p9 .

res:Provenance/p9 a fhir:Provenance, prov:Activity ;
    fhir:Provenance.target res:Observation/r9 ;
    prov:wasAssociatedWith res:PractitionerRole/pr7 ;
    prov:used res:Communication/m3 .
```
### Worked example: criteria and a booking
```
res:Basic/c3 a fhir:Basic, diucs:ServiceCriteria ;
    fhir:Basic.subject res:HealthcareService/a1 ;
    diucs:version 3 ;
    diucs:acceptsNeed cs:need-category#fall-no-injury, cs:need-category#frailty ;
    diucs:excludesNeed cs:need-category#suspected-fracture ;
    diucs:supersedes res:Basic/c2 .

res:Task/b4821 a fhir:Task, diucs:BookingRequest ;
    fhir:Task.status "accepted" ;
    fhir:Task.businessStatus cs:booking-business-status#confirmed ;
    fhir:Task.intent "order" ;
    fhir:Task.owner res:HealthcareService/a1 ;
    fhir:Task.focus res:ServiceRequest/sr1 ;
    fhir:Task.for res:Patient/p1 ;
    fhir:Task.authoredOn "2026-10-23T13:16:00Z"^^xsd:dateTime .
```
### A derived triple
The relationship from a need to the services that accept it is not stored. A rule derives it from the current criteria:
```
CONSTRUCT { ?need diucs:acceptedBy ?svc . }
WHERE {
  ?svc diucs:currentCriteria ?c .
  ?c   diucs:acceptsNeed ?need .
}
```
## Graph constraints, indexes and queries
The syntax below is Cypher in the style of Neo4j 5. It is written to be read and ported, not pasted. If another property-graph store is chosen, the port hides the difference and these become that store's equivalents. Check scoped-subquery syntax against the version chosen.
### Constraints and indexes
```
CREATE CONSTRAINT resource_id FOR (n:Resource) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT identifier_key FOR (n:Identifier) REQUIRE (n.system, n.value) IS UNIQUE;
CREATE CONSTRAINT concept_key FOR (n:Concept) REQUIRE (n.system, n.code) IS UNIQUE;
CREATE INDEX obs_by_service FOR (o:Observation) ON (o.effectiveDateTime);
CREATE INDEX task_by_status FOR (t:Task) ON (t.status, t.businessStatus);
CREATE INDEX svc_active FOR (s:HealthcareService) ON (s.active);
CREATE INDEX phone_hash FOR (p:Practitioner) ON (p.phoneHash);
CREATE POINT INDEX location_position FOR (l:Location) ON (l.position);
```
### The queries the product needs
**1. Latest figure for every active service**
```
MATCH (s:HealthcareService {active: true})
CALL {
  WITH s
  MATCH (o:Observation)-[:FOCUS]->(s)
  RETURN o ORDER BY o.effectiveDateTime DESC LIMIT 1
}
RETURN s.id AS service, o.valueQuantity_value AS reported, o.effectiveDateTime AS reportedAt;
```
**2. Services that pass the hard criteria for a case** (a filter, not a ranking)
```
MATCH (s:HealthcareService {active: true})-[:CURRENT_CRITERIA]->(c:Basic {status: 'current'})
WHERE c.ageMin <= $age AND ($age <= c.ageMax OR c.ageMax IS NULL)
  AND $district IN c.postcodeDistricts
  AND NOT EXISTS { MATCH (c)-[:EXCLUDES_NEED]->(x:Concept) WHERE x.code IN $needs }
  AND ALL(n IN $needs WHERE EXISTS { MATCH (c)-[:ACCEPTS_NEED]->(a:Concept) WHERE a.code = n })
RETURN s;
```
The status, the effective available and the travel range are then worked out in the domain, because they depend on the clock and on rules that live in code.
**3. Services held by one phone**
```
MATCH (p:Practitioner {phoneHash: $hash})<-[:PRACTITIONER]-(r:PractitionerRole {active: true})
      -[:HEALTHCARE_SERVICE]->(s:HealthcareService)
RETURN s.id, s.name ORDER BY s.name;
```
**4. Pending bookings for a service**
```
MATCH (t:Task {businessStatus: 'requested'})-[:OWNER]->(:HealthcareService {id: $id})
RETURN count(t) AS pending;
```
**5. Services with no figure inside their window** (feeds the missed-report ladder)
```
MATCH (s:HealthcareService {active: true})
OPTIONAL MATCH (o:Observation)-[:FOCUS]->(s)
WITH s, max(o.effectiveDateTime) AS last
RETURN s.id, last;
```
The domain then applies the window and the opening hours to `last`.
**6. Criteria history for a service**
```
MATCH (c:Basic {status: 'current'})-[:SUBJECT]->(:HealthcareService {id: $id})
MATCH path = (c)-[:SUPERSEDES*0..]->(old:Basic)
RETURN old.version, old.status, old.createdAt ORDER BY old.version DESC;
```
**Planning analysis.** The question "where did patients go when the best fit was full" is answered from the audit snapshots, which hold what the advisor saw at the moment of each decision, joined to the case outcome. Those rows are Snapshot nodes in Neo4j. Run the analysis on a read replica, or in a separate database on the same server if the edition allows, and not on the live operational database.
## Open points and what to verify
**To verify against the sources before building**
- The ODS organisation and site identifier system URIs.
- Whether UK Core or the NHS Directory of Services already defines profiles for Organization, Location and HealthcareService.
- The R4B subscription element names, and the subject constraints on Observation and Flag.
- Whether Consent fits staff notification consent, or Basic is the safer profile.
- That the RDF examples validate against the FHIR RDF schemas.
- SNOMED CT licensing and the UK edition, and whether SNOMED or LOINC codes exist for NEWS2 and the Clinical Frailty Scale.
- Cypher syntax for the Neo4j edition and version chosen.
**To decide**
- Keep the canonical `json` property on every node, or hold only the decomposed graph. I recommend keeping it, for exact round trips and cheap reads.
- The Neo4j edition, and whether a read replica or a second database is available for the planning analysis.
- Retention and roll-up: after [period] old capacity reports are summarised and the detail archived. At 100 services reporting 12 times a day the store gains about 440,000 Observations a year, which Neo4j handles easily, but the retention rule is an IG decision.
- Concept nodes become very well connected. Index them by system and code and keep relationship directions consistent, so a walk from a need to the services that accept it stays fast.
- Whether criteria stay as Basic with a profile, or move to a purpose-built resource once the shape settles.