# DIUCS capacity: consolidated domain rules

This file gathers every business rule the build needs in one place. It is derived from the four source documents in this folder (`architecture.md`, `fhir-data-model.md`, `observability.md`, `ui-screens.md`).

Rules marked **[ASSUMED]** are not stated exactly in the sources. They are a reasonable reading, chosen so work can start. Each one is a named constant in code so the product owner can change it without touching logic. Confirm them with the product owner and the clinical safety officer before go-live.

All times in the domain are timezone-aware UTC `datetime`s. Anything a person sees, and every schedule, is computed in `Europe/London` local time and converted to UTC.

---

## 1. Services and capacity

### 1.1 Service profile (set at registration)

| Field | Meaning | Example |
|---|---|---|
| `measure` | What is counted. One of `free-slots`, `free-beds`, `referrals-acceptable`, `occupied-patients`, `packages-free` | `referrals-acceptable` |
| `unit_label` | Words shown after the number | "referrals in the next 2 hrs" |
| `established_capacity` | The normal maximum | 8 |
| `can_exceed_established` | Whether the service can run over its established level (virtual wards, hospital at home) | false |
| `usual_range_min`, `usual_range_max` | Range check for reported numbers | 0, 8 |
| `report_cadence` | `every-2-hrs`, `twice-a-day`, `once-a-day` | `every-2-hrs` |
| `limited_level_percent` | Used share at or above which the service is Limited | 80 **[ASSUMED default]** |
| `available_time` | Days and hours the service accepts referrals (London local). May be all day. | Mon–Fri 08:00–20:00 |
| `channel` | `text`, `email` or `push` for prompts | `text` |

### 1.2 Status values

`accepting`, `limited`, `not-accepting`, `over-capacity`, `not-updated`, `out-of-hours`. The board labels are: Accepting; Limited: phone to confirm; Not accepting; Over capacity; Not updated: treat as unknown, phone; Out of hours.

Status is never shown by colour alone. Each has a shape and a word.

### 1.3 Status rule (evaluated in this order; first match wins)

1. The service has an active `suspended` flag → `not-updated`.
2. `now` is outside the service's `available_time` → `out-of-hours`.
3. The latest report is missing, or the service is **overdue** (see 1.5) → `not-updated`.
4. For `occupied-patients` measures: `occupied > established` → `over-capacity`; `occupied == established` → `not-accepting` (unless `can_exceed_established`, then `limited`); used share ≥ `limited_level_percent` → `limited`; else `accepting`.
5. For free-count measures (`free-slots`, `free-beds`, `referrals-acceptable`, `packages-free`): effective available (1.6) `== 0` → `not-accepting`; a reporter's "we are closed" → `not-accepting`; used share `(established − effective) / established ≥ limited_level_percent` → `limited` **[ASSUMED formula]**; else `accepting`.

Checks against the sample board: UCR East 1 of 8 free (used 88%) → Limited; Ward A 2 of 12 (used 83%) → Limited; Reablement used 70% → Accepting; Hospital at home 14 of 12 occupied → Over capacity, shown as "+2 over established capacity".

The status at report time is stored on the report as its interpretation. The board always recomputes with the current clock.

### 1.4 Report schedule (due times)

- `every-2-hrs`: due on each even hour from the start of `available_time` up to its end (for example 08:00, 10:00, …, 20:00 for 08:00–20:00). **[ASSUMED alignment]**
- `twice-a-day`: due at the opening time and at 14:00 **[ASSUMED]**; if the service opens after 14:00, only the opening time.
- `once-a-day`: due at the opening time.
- All-day services: as above from 00:00, so `every-2-hrs` is due every 2 hours round the clock.
- The **reply-by** time is due + 30 minutes.
- Times are London local. Across a clock change the local time is kept (10:00 stays 10:00 local), so the UTC time shifts by an hour.

### 1.5 Missed-report ladder and overdue

For each due time with no report received since the prompt was sent:

| Offset from due | Action |
|---|---|
| 0 | Prompt sent by the service's channel |
| +30 min (reply-by passes) | Reminder sent; the service is now **overdue** and shows Not updated |
| +60 min | Phone task created for the advisors |
| +90 min | Escalated to the shift lead |

A report received at any step stops the rest of the ladder (cancel the scheduled messages).

**Overdue, precisely:** a service is overdue when any due time since its last report has passed its reply-by (due + 30 minutes) while the service was in hours. A report clears it. This keeps the board from flipping back to fresh between the next due time and its reply-by: a service due at 12:00 that has not reported is still "Not updated · was due 12:00" at 14:05, even though the 14:00 reply-by has not passed yet.

The data age is always shown. A figure more than 2 hours old gets the advisor warning "Data is over 2 hrs old. Consider phoning." even when it is not overdue.

Data-age text: under 1 minute "just now"; under 60 minutes "N min ago"; otherwise "H hr(s) M min ago" (for example "2 hrs 10 min ago", "1 hr 5 min ago", "3 hrs ago" when minutes are 0).

### 1.6 Effective available and pending

- `effective_available = latest reported free figure − bookings confirmed since that report`, never below 0.
- `pending` = bookings for the service in `requested` state. Pending is shown apart from available ("4 · 1 pending") and does not reduce it.
- A new report resets the count: bookings confirmed before the new report's effective time are assumed to be included in it.

### 1.7 System pressure

Count services whose status is `limited`, `not-accepting` or `over-capacity` ("limited or worse"). Exclude `out-of-hours`.

- `normal`: fewer than 3 **[ASSUMED]**
- `watch`: 3 or 4
- `high`: 5 or more (this is also the alert threshold in the exec alert settings)

The wall board shows the banner "System under pressure" when every service that is in hours is limited or worse.

---

## 2. Text replies (reporter by SMS)

### 2.1 Grammar

Replies are matched after trimming whitespace and ignoring case.

| Reply | Meaning |
|---|---|
| `Y` (also `YES`) | Confirm the recorded figure |
| An integer `0`–`999` | A new figure. `0` means closed to referrals. |
| `A 4`, `B 2` (letter, space optional, number) | Multi-service: new figure for service A or B |
| `Y A`, `YA`, `Y B` | Multi-service: confirm service A or B |
| `Y` on a multi-service prompt | Confirm all services in the prompt |
| `CONFIRMED` (also `CONFIRM`) | Booking: confirm the open request |
| `DECLINE` (also `DECLINED`) | Booking: decline the open request |
| `1`, `2`, `3` straight after a decline | Booking decline reason: 1 full, 2 outside criteria, 3 other |
| Anything else | Unrecognised. Reply with a short help text naming the allowed words. |

There is no STOP, START or HELP keyword handling in the product. Messages from a number not on the allow-list get no reply at all.

### 2.2 Reply policy (capacity)

- A reply is accepted if a prompt is open for that phone (sent, and reply-by not passed).
- **Late reply** (after reply-by, no open prompt): the value is not used. Send "Too late" with a fresh question and a new reply-by of now + 30 minutes.
- **Correction**: a number sent within 15 minutes **[ASSUMED]** of an accepted report replaces it. Echo "Updated: … Replaces N."
- **Y limit**: `Y` is recorded as a `confirmed` report (derived from the latest number). At most 2 confirmations in a row. A third `Y` is refused: "Y was used twice already. Please send the number for <service>."
- **Range check**: a number outside the usual range is not recorded the first time. Reply asking the reporter to send it again to confirm. **[ASSUMED]** If the same number is sent again within the open window, record it and raise a `ReportFlag` (reason `out-of-range-twice`).
- Every accepted reply gets an echo with the figure, the time recorded and the next due time.
- **A Y never makes an old figure current** (hazard H-31, DEC-148): a Y confirms the figure on record only if that figure was no more than 2 hours old when the prompt was sent (D05's stale warning). Otherwise nothing is recorded and the reporter is told the figure is out of date (C12) and asked for a number.
- **A Y never confirms a figure the reporter was not shown** (hazard H-32, DEC-148 items 17 to 19): a Y is also refused, with C12 and nothing recorded, (a) when a number has been reported for the service later than the moment the prompt was sent (a confirmation after the prompt does not count: it repeats the figure), (b) when a report lands between the check and the write (ConfirmCapacity is told which report was judged and refuses if the latest is another), and (c) when the Y is processed more than `CONFIRM_PROCESSING_LIMIT` = 10 minutes **[ASSUMED]** after it was received, because a confirmation is stamped at the time it is processed and a Y that waited in a queue or an outage would make an old figure current now. Exactly 10 minutes is inside the limit. The reporter is asked for a number (fails closed).

### 2.3 Report flags (for the shift lead to check)

Raised by rules, never by a person's speed:

- `out-of-range-twice`: the same out-of-range number sent twice.
- `many-changes`: 3 or more reports for one service within 5 minutes **[ASSUMED window]**.
- `differs-from-phoned`: a reported figure differs from an advisor-phoned figure recorded in the previous 60 minutes **[ASSUMED window]**.

A flag is its own record. Capacity reports are never edited.

### 2.4 Multi-service phones

- When two or more of a phone's services are due within the same 10 minutes **[ASSUMED]**, send one grouped prompt that letters them A, B, C… in name order.
- A partial reply never confirms the other services. The echo names what is still waiting ("A) UCR West still needs a reply").
- A phone holding more than 3 services is flagged on the lead's phones list.

---

## 3. Bookings

### 3.1 States

| Domain state | Task.status | Task.businessStatus |
|---|---|---|
| Requested | requested | requested |
| Confirmed | accepted | confirmed |
| Declined | rejected | declined |
| Expired | cancelled (statusReason expired) | expired |
| Cancelled before confirming | cancelled | cancelled-before |
| Cancelled after confirming | cancelled | cancelled-after |
| Withdrawn by the service | cancelled (statusReason withdrawn) | withdrawn |
| Not reached | failed | not-reached |
| Completed | completed | completed |

Allowed transitions: requested → confirmed, declined, expired, cancelled-before. confirmed → cancelled-after, withdrawn, not-reached, completed. Every other transition is refused.

### 3.2 Rules

- One open (requested) booking per service at a time. A second request for the same service is refused until the first is answered, expires or is cancelled.
- The reply-by time is request time + 10 minutes. At +5 minutes with no answer the advisor is prompted to phone. At +10 minutes the request expires. Silence is never acceptance.
- A confirmation reduces effective available by 1 and clears pending.
- A decline or expiry clears pending. The available figure returns.
- The reply is matched by booking reference. A text `CONFIRMED` with no reference matches the phone's single open request; if the phone has open requests for more than one service, reply asking which reference.
- Decline reasons: full, outside criteria, staffing or transport, other. Withdraw reasons: now full, staffing, cannot reach the patient, other. Not-reached reasons: not at the address, no answer at the door, gone to hospital, other. Cancel reasons (advisor): caller declined, no longer needed, other route found, entered in error.
- After a withdrawal the advisor is alerted at once. If nobody acts within 10 minutes the shift lead is alerted.
- Booking references are short numbers unique among open bookings (for example 4821). **[ASSUMED: 4 digits, random, retry on collision]**

---

## 4. Cases (advisor calls)

- A case holds: referrer type, age band (`0-15`, `16-64`, `65-79`, `80+`), postcode, needs (need-category codes), urgency (`within-2-hrs`, `today`, `planned`), and optional referrer scores. No name, no NHS number, no free text.
- Scores are recorded as given. Allowed values: NEWS2 0–20; Clinical Frailty Scale 1–9; ambulance category 1–4; Manchester triage immediate, very urgent, urgent, standard, non-urgent; NHS Pathways Dx code chosen from a list. The tool never calculates or checks a score.
- Urgency maps to `ServiceRequest.priority`: within 2 hrs → `urgent`; today or planned → `routine`.
- On close, the postcode and needs are cleared. Kept for audit: need category, age band, urgency, scores, destination, outcome, times, and the snapshot of what the board showed.
- Outcomes: accepted and booked, declined, redirected, caller cancelled, no service fits, out of area. If the best fit was not used, why: full, declined, data too old, caller preference, clinical override.

### 4.1 Hard criteria filter (a filter, never a ranking)

A service passes when all of these hold:

- It is active, not suspended, and has a `current` criteria version.
- The patient's postcode district is in the criteria's districts.
- No case need is in the criteria's excluded needs.
- Every case need is in the criteria's accepted needs.
- Age: the case's age band lies fully inside `[age_min, age_max]` → pass. The band overlaps the range only partly → pass with the warning "Check age: band overlaps the service's age limits" **[ASSUMED]**. No overlap → excluded.

Band bounds: `0-15` = 0–15, `16-64` = 16–64, `65-79` = 65–79, `80+` = 80–no limit.

Services that fail are listed under "not suitable, and why" with one reason each (not accepting since…, not updated for…, outside criteria: <which>, out of hours). Passing services are sorted by travel time (low end of the range), then name. They are never scored or ranked.

Every options view writes an audit snapshot: for each service shown, its status, number, data age and criteria version.

### 4.2 Criteria

- Criteria versions move: `draft` → `pending-approval` → `current` → `superseded`. `pending-approval` can be sent back to `draft`. Any version can be `retired`.
- A change needs the owner and a second approver (a clinical lead). Until approval, advisors keep seeing the current version.
- On approval the new version becomes current, the old one is marked superseded (never deleted), and the read-model cache is cleared. Open cases keep the version they saw.
- Confirming criteria are still right sets a new review-by date of 3, 6 or 12 months.
- A reminder goes to the owner 14 days before review-by **[ASSUMED]**. After review-by passes, a `criteria-overdue` flag shows on the service and on advisor cards as "criteria not reviewed".

---

## 5. Clinical advice

- A clinical advisor sets presence: available, busy or away. Advisors see the count of available clinical advisors, never names.
- An advisor's request has urgency `now` or `within-15-min`, and carries the case summary and the options shown. Notifications carry urgency, age band and need only.
- Taking a request locks it to that clinical advisor. If they do not give advice within 10 minutes it returns to the queue.
- Advice choices: go ahead with the service, use another service, needs a clinical call to the referrer, send to the emergency route under local protocol. Optional reason: within criteria on my judgement, safer alternative, other. An optional short note (max 280 characters) carries a no-names warning.
- Going away returns that person's unfinished requests to the queue.

---

## 6. Registration and approval

### 6.1 States

`invited` → `draft` → `submitted` → `in-review` → (`needs-changes` → `submitted`) → `approved` → `live`. Also `not-approved`, `paused`, `reverify`.

| State | Moved on by |
|---|---|
| invited | Applicant registers within 48 hours |
| draft | Applicant submits |
| submitted | Shift lead starts checks → in-review |
| in-review | Shift lead and clinical lead: approve, send back (needs-changes) or not approve |
| needs-changes | Applicant resubmits → submitted |
| approved | Applicant answers the test notification; then shift lead sets live |
| live | Pause, or re-verification due |
| not-approved | Shift lead can reopen |
| paused | Service or shift lead resumes |
| reverify | Applicant confirms details; a changed reporting phone needs a lead call-back first |

### 6.2 Rules

- Invitations can only be created for scope-list entries flagged `in-pilot`. The invitation locks the service name, ODS code and mobile number. It is valid for 48 hours.
- Approve is unavailable until all of these are done, and the screen lists what is missing:
  1. Automatic checks passed or explained (ODS code found and active; name matches; address found and in area; reporting phone is the one invited; criteria owner email on an organisation domain).
  2. Call-back confirmed, to the number on the register (never the applicant's number), with the role spoken to.
  3. Scope decided as `in-scope: pilot`.
  4. Criteria second approval by the clinical lead.
- After approval a test prompt is sent. The service goes live only after the test is answered from the registered phone and the shift lead sets it live.
- Re-verification every N days **[N to be set; default 180, ASSUMED]**, and whenever the reporting phone changes.

---

## 7. Identity and access

- **Staff** (advisors, clinical advisors, shift leads, criteria owners, planning users): Trust staff account (Microsoft Entra ID).
- **Reporters and COO or ICB users**: text code then PIN.
- **Text code**: 6 digits, valid 10 minutes, 5 wrong tries then a new code is needed, resend allowed after 60 seconds **[ASSUMED cooldown]**.
- **PIN**: 6 digits, stored only as a keyed hash, bound to the device. 5 wrong tries lock it; a text code resets it. Re-verify by text code every 30 days and on any new device.
- **Link tokens**: at least 128 bits of randomness, single use, tied to one prompt and one phone, expiring with the prompt (the reply-by time). Only a hash is stored. Opening a link (GET) changes nothing; a button press (POST with a CSRF check) does.
- **Invitation links**: valid 48 hours.
- **Wall screen pairing code**: 6 digits shown as "482 913", valid 10 minutes. A paired screen holds a device token (hash stored) and can read only the board. It never sees patient data.
- **Support code**: 8 characters shown as `XXXX-XXXX` from an unambiguous alphabet, valid for a set period, created only by the person.
- **Roles**: reporter, advisor, clinical, lead, owner, exec, wall, anonymous-link, support, audit. Every call is checked against role and the services the caller may act for. Patient-level data is visible to advisor and clinical roles only.

---

## 8. Alerts (COO and ICB, shift lead)

| Alert kind | Fires when |
|---|---|
| `service-closed` | A service moves to `not-accepting` while in hours (planned out-of-hours closures do not count) |
| `over-capacity` | A service moves to `over-capacity` |
| `not-updated` | A service has been not updated for the subscriber's threshold: 2 or 4 hours |
| `system-pressure` | System pressure moves to `high` (5 or more limited or worse) |

- Each user chooses alert kinds, quiet hours (none, or 22:00–06:00), and what to receive during quiet hours (critical only, or everything). Critical kinds: `service-closed`, `system-pressure` **[ASSUMED]**.
- If not acknowledged within the user's choice of 10, 15 or 30 minutes, the alert goes to their deputy, then to the SPOA shift lead.
- Acknowledging tells others it is being handled. It does not change the board. Snooze defers for 1 hour.
- Defaults for a new user: service closes, over capacity, not updated (2 hrs), system pressure, daily summary on; weekly summary off.

---

## 9. Messages

No message (text, email or push) ever contains a patient name, a full postcode, an NHS number or free text. At most: a reference, an age band, a need category and an urgency. A build-time test scans every template.

Template examples (exact wording to be approved by IG):

- Capacity prompt: `DIUCS: UCR West. We have 3 referrals in the next 2 hrs (as of 23 Oct 08:15). Confirm or update: diucs.example/k3F9a Or reply Y, or a new number. By 10:30.`
- First prompt: `DIUCS: UCR West. How many referrals can you take in the next 2 hrs? Send a number (0 = closed). By 08:30.`
- Echo: `Thanks. UCR West: 4 referrals, as of 08:06. Next prompt 10:00.`
- Correction: `Updated: UCR West 3 referrals, as of 14:14. Replaces 4.`
- Too late: `Too late: the 12:30 cut-off had passed, so 5 was not used. New question: UCR West has 3 referrals recorded. Reply Y if right, or send the new number, by 13:11.`
- Y limit: `Y was used twice already. Please send the number for UCR West.`
- Multi-service prompt: `DIUCS: 2 services need an update by 10:30. A) UCR West 3. B) UCR East 1. Reply Y if both right, or A 4, or B 2.`
- Booking request: `DIUCS REQUEST 4821: UCR West. Age 80+, fall and frailty, within 2 hrs. Referral details follow in SystmOne. Reply CONFIRMED or DECLINE, or open diucs.example/b4821 by 14:26.`
- Booking confirmed echo: `Booked: 4821, UCR West, confirmed 14:19. Thank you.`
- Decline echo: `Noted: 4821 declined. Optional reason: reply 1 full, 2 outside criteria, 3 other.`
- Invitation: `DIUCS: You are invited to report capacity for UCR West. Set up takes about 3 minutes: diucs.example/i/Qx82 Valid for 48 hrs.`

Message catalogue ids (stored as `Communication.topic`) **[ASSUMED numbering; the source names "C1 to K4" without listing them]**:

| Id | Message |
|---|---|
| C1 | Capacity prompt with recorded figure |
| C2 | First capacity prompt (no figure yet) |
| C3 | Echo after a report |
| C4 | Correction echo |
| C5 | Too late, with new question |
| C6 | Y limit reached |
| C7 | Out-of-range, please send again |
| C8 | Reminder (+30 min) |
| C9 | Multi-service prompt |
| C10 | Multi-service partial echo |
| C11 | Unrecognised reply help |
| C12 | A Y was refused: the figure on record is out of date, please send a number (U05, DEC-148) |
| B1 | Booking request by text |
| B2 | Booking request by email |
| B3 | Booking request by push |
| B4 | Booking confirmed echo |
| B5 | Booking declined echo |
| B6 | Booking cancelled by the SPOA |
| B7 | Which reference? |
| I1 | Reporter invitation |
| I2 | Exec invitation |
| I3 | Test prompt after approval |
| K1 | Text code (verification) |
| K2 | Criteria review reminder |
| K3 | Alert notification |
| K4 | Suspended notice to the service |

---

## 10. Privacy and telemetry

- No patient data in any channel, log, trace, metric or analytics event.
- Telemetry records element ids and outcomes, never field values or page text.
- Aggregates hide groups under 10.
- There is no per-person speed, error or ranking view anywhere.
