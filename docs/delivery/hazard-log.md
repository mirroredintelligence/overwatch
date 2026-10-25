# Hazard log

A living record of what could go wrong clinically or for data protection, what controls the design puts in place, and the test that proves each control. It is the working draft for the clinical safety officer's DCB0129 hazard log. It is not a substitute for it.

Rules for sessions:
- A task that touches a hazard's control adds the test reference to **Verified by** in the same commit. A control with no test is an open finding.
- A new hazard found while building is added at once with the next `H-nn`, and a lesson is published.
- **Severity and likelihood are assigned by the clinical safety officer.** Leave them as `TBD`. Do not guess.
- Source ids `F1` to `F48` are the risk codes on the user-journey boards in the design canvas (`docs/spec/ui-screens.md`).

| Id | Hazard | Source | Control in the design | Where it is built | Verified by | Severity |
|---|---|---|---|---|---|---|
| H-01 | An old figure looks current, so an advisor offers a service that is full | F3, F2 | Status is Not updated when a report is overdue. Data age is always shown. A figure over 2 hours old carries a warning. | D05, D07, W05, W13 | Partial (D05): overdue, data age, the 2-hour warning and the data-age wording, `backend/tests/unit/domain/rules/test_freshness.py`. The Not updated status itself is D07. | TBD |
| H-02 | The advisor trusts the display without question | F1 | Options are a filter, never a ranking. Reasons for and against are shown. Clinical advisor is one tap away. | D20, U12, W13 | | TBD |
| H-03 | A wrong or misread figure is recorded | F16 | Range check on every number. Echo with the figure and time. A repeat Y is capped at two. Unknown senders get no reply. | D09 to D12, U05 | | TBD |
| H-04 | Two advisors book the same last place | F15 | Pending is shown apart from available. One open booking per service. Not booked until the service confirms. | D14, U17, U18 | `backend/tests/unit/domain/rules/test_booking_rules.py::test_a_service_with_a_requested_booking_cannot_take_another`, `::test_one_open_booking_blocks_a_request_among_closed_ones` (rule only; use-case enforcement is U17) | TBD |
| H-05 | A booking request is ignored and the caller waits | F15 | Phone prompt at 5 minutes. Expiry at 10 minutes. Silence is never acceptance. | D14, U19 | `backend/tests/unit/domain/rules/test_booking_rules.py::test_requested_at_1316_utc_has_reply_by_1326_and_phone_prompt_1321`, `::test_requested_at_1416_prompts_at_1421_and_expires_at_1426` (timer values only; scheduling and expiry action are U19) | TBD |
| H-06 | A service withdraws or cannot be reached after confirming | F10 | Withdrawal and not-reached are recorded at once and alert the advisor, then the shift lead after 10 minutes. | U21, W21, W22 | | TBD |
| H-07 | Out-of-date criteria send the wrong patient to a service | F7, F11 | Versioned criteria with an owner and review-by date. Overdue flag on the service and the advisor card. Two approvals for a change. | D20, D21, U30, U31 | | TBD |
| H-08 | Wrong criteria go live | F11, F40 | Second approval by a clinical lead. The old version stays live until approval. The cache is cleared on approval. Cases keep the version they saw. | U30, W30, W31 | | TBD |
| H-09 | Patient details appear in a message, log, trace or screen | F4, F36, F39 | No patient data in any channel. A build-time scan of every template. Telemetry allow-list and schema scan. Notifications carry urgency and age band only. | D17, O04, O05 | | TBD |
| H-10 | A fake service or spoofed reporter diverts patients | F18, F26 | Invitation only from the scope list. ODS check. Call-back to the register number. Test prompt must be answered. Allow-list on inbound texts. | D22, U24, U28, U29, I07 | | TBD |
| H-11 | A reporter's phone is lost or its SIM swapped | F23, F24 | Sign out everywhere. A new phone is not live until the lead calls the register number. | U37, W55 | | TBD |
| H-12 | The named reporter is away and nobody reports | F9 | Cover number with verification. Role phones. Prompts go to cover or the SPOA. | U16, U38 | | TBD |
| H-13 | No report is received and the board stays confident | F14 | Reminder at 30 minutes, phone task at 60, lead at 90. The board shows Not updated, never the old number as current. | D04, U06 | Partial (D04): ladder offsets and reply-by, `backend/tests/unit/domain/rules/test_schedule.py` (`test_ladder_times_from_a_due_time`, `test_reply_by_is_due_plus_30_minutes`). The board and the overdue display are built in D05, D07 and U06. | TBD |
| H-14 | Reports are gamed or flagged figures go unchecked | F5 | Rule-based flags only. The lead resolves them. No per-person league table. | D12, U07, U39 | D12: `backend/tests/unit/domain/rules/test_report_flags.py` (rule-based flags; lead resolution not yet built) | TBD |
| H-15 | A reporter replies yes by reflex | F12, F20 | Confirm is capped at two in a row. Corrections are easy. Prompts are only as frequent as the cadence. | D11 | | TBD |
| H-16 | A reply for one service is applied to another | F22 | The service name is repeated in every message. Partial replies never confirm other services. Booking replies are per service. | D10, D28, U04 | Parser part (D10): `tests/unit/domain/rules/test_reply_parser.py`: `Y A` and `A 4` each name one service, a bare figure is refused in a lettered message, a repeated letter is refused, and a bare `Y` is accepted only as the whole message. Partial-echo and accept/reject controls are not built here (D11, D28, U04). | TBD |
| H-17 | Alerts are ignored or too many | F41 | Few alerts on by default. Quiet hours. Escalation ladder with acknowledgement. | D24, U34 | | TBD |
| H-18 | An approver is absent and approvals stall | F47 | Deputy for the lead. Time targets. Unactioned clinical requests return to the queue after 10 minutes. | D22, D23 | | TBD |
| H-19 | There is no audit trail of what the advisor saw | F10 | Every decision stores a snapshot of statuses, numbers, data age and criteria versions. The audit log is append-only with a hash chain. | P05, U12, U42 | | TBD |
| H-20 | The tool is offline and staff do not know | n/a | The wall board shows Last known and says so. The advisor screen shows the manual-process banner. | W06, W07 | | TBD |
| H-21 | Unproven savings claims erode trust | F48 | Estimates are labelled and show their sum. Small groups are hidden. | U35, W41 | | TBD |
| H-22 | A stale installed app or cache shows old data | F40 | The offline shell never caches capacity or case data. | W32 | | TBD |
| H-23 | Staff analytics become a performance monitor | n/a | No per-person view. Support sessions only with a shared code. Groups under 10 hidden. | O02 to O08, W48 | | TBD |
| H-24 | The graph is changed without a trace, or two copies of a fact disagree | n/a | Graph-native storage with no duplicate copy (DEC-001). Audit and provenance append-only. | G02 to G05, P05 | | TBD |
| H-25 | A DST or timezone error makes a prompt or deadline wrong | n/a | All schedules computed in Europe/London and converted to UTC. Tests across 2026-03-29 and 2026-10-25. | F06, D03, D04 | `backend/tests/unit/domain/rules/test_london_time.py` (spring gap, autumn fold, round trip, monotonic property); `backend/tests/unit/domain/rules/test_schedule.py` (both clock changes, overnight across the spring gap, property tests) | TBD |
