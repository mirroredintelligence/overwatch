# Build wave 2: fragments folded

The per-task fragments in `docs/delivery/fragments/` (build-wave-rules.md) of build wave 2 (bundles W2A to W2G, with the integration notes of iA, iC, iE, iF and iG and the U17-1 fragment of fixD) were folded into `decisions.md`, `hazard-log.md`, `known-issues.md` and `docs/spec/contracts.md` on 2026-10-30, and the fragment files were deleted (they stay in git history, last present at the commit before the one that removes them). This file is the audit of what was numbered how. The first fold is `fragments-folded-wave1.md`.

Rules used. A number a fragment already held was kept when it was inside its bundle's block (decisions and hazards: W2A 250 to 269 and 110 to 119, W2B 270 to 289 and 120 to 129, W2C 290 to 299 and 130 to 134, W2D 300 to 309 and 135 to 139, W2E 310 to 329 and 140 to 149, W2F 330 to 339 and 150 to 154, W2G 340 to 349 and 155 to 164), free, and used by no other fragment. Every held number met those tests, so no held number changed. The W2F fragments (O03, O04 and its integration notes, O05, O08, R18) carried no decision number: they took the next free numbers of the W2F block (330 to 335), in fragment order, not numbers after the highest folded one, so the blocks stay as reserved. R08 used H-165 outside the W2G block (I14, U33, U31 and U38 use 155 to 164): 165 is the next free number after the highest folded hazard, so renumbering it as the brief asked gives the same number and the row is unchanged. If H-165 is wanted for something else, move R08's row; nothing else cites it. Nothing carried a placeholder (`DEC-NEW`, `H-NEW-n`). Highest before the fold: DEC-246 and H-105 (the W09 reservations DEC-210 and H-65 are folded). Highest after: DEC-344 and H-165. Numbers inside the blocks that no fragment used stay unused (decisions 253 to 269, 273 to 289, 291, 296 to 299, 308, 309, 316, 320, 325 to 329, 336 to 339, 345 to 349; hazards 115 to 119 and 129).

Collision check, run on the tree before and after: no decision or hazard number is defined twice, no fragment number collides with a number already in the shared files, and no migration number collides (`0055_tenant_config_records` of TEN-026 and `0070_safety_counter_id` of U41 are unique among the migration ids in `src`).

## Decisions

| Fragment | Old id | New id | Note |
|---|---|---|---|
| I14 | DEC-340 | DEC-340 | kept |
| O03 | (no number) | DEC-330 | unnumbered; next free number of the W2F block (330 to 339) |
| O04 | (no number) | DEC-331 | unnumbered; next free number of the W2F block (330 to 339) |
| O04 (integration) | (no number) | DEC-332 | unnumbered; next free number of the W2F block (330 to 339) |
| O05 | (no number) | DEC-333 | unnumbered; next free number of the W2F block (330 to 339) |
| O08 | (no number) | DEC-334 | unnumbered; next free number of the W2F block (330 to 339) |
| R08 | DEC-344 | DEC-344 | kept |
| R18 | (no number) | DEC-335 | unnumbered; next free number of the W2F block (330 to 339) |
| TEN-018 | DEC-250 | DEC-250 | kept |
| TEN-020 | DEC-251 | DEC-251 | kept |
| TEN-026 | DEC-271 | DEC-271 | kept |
| TEN-029 | DEC-272 | DEC-272 | kept |
| TEN-052 | DEC-270 | DEC-270 | kept |
| TEN-064 | DEC-252 | DEC-252 | kept |
| U12 | DEC-290 | DEC-290 | kept |
| U13 | DEC-292 | DEC-292 | kept |
| U13 | DEC-293 | DEC-293 | kept |
| U14 | DEC-294 | DEC-294 | kept |
| U14 | DEC-295 | DEC-295 | kept |
| U17-1 | DEC-307 | DEC-307 | kept |
| U18 | DEC-300 | DEC-300 | kept |
| U18 | DEC-305 | DEC-305 | kept |
| U18 | DEC-306 | DEC-306 | kept |
| U19 | DEC-301 | DEC-301 | kept |
| U20 | DEC-302 | DEC-302 | kept |
| U24 | DEC-310 | DEC-310 | kept |
| U24 | DEC-311 | DEC-311 | kept |
| U24 | DEC-312 | DEC-312 | kept |
| U27 | DEC-313 | DEC-313 | kept |
| U27 | DEC-314 | DEC-314 | kept |
| U27 | DEC-315 | DEC-315 | kept |
| U28 | DEC-317 | DEC-317 | kept |
| U28 | DEC-318 | DEC-318 | kept |
| U28 | DEC-319 | DEC-319 | kept |
| U31 | DEC-342 | DEC-342 | kept |
| U32 | DEC-321 | DEC-321 | kept |
| U32 | DEC-322 | DEC-322 | kept |
| U32 | DEC-323 | DEC-323 | kept |
| U32 | DEC-324 | DEC-324 | kept |
| U33 | DEC-341 | DEC-341 | kept |
| U36 | DEC-303 | DEC-303 | kept |
| U38 | DEC-343 | DEC-343 | kept |
| U41 | DEC-304 | DEC-304 | kept |

Notes.

- The decision text was copied with its wrapped lines joined, the fragment's own status line kept after "Folded from the fragment of ...", and "Tenant pending", "Assumed" and (for TEN-018, TEN-020 and TEN-064) the hand-run mutant lists added as bold paragraphs after the decision, as in the first fold. A fragment with several decisions (U13, U14, U18, U24, U27, U28, U32) has them once, under its first decision, with the decision numbers named in the label.
- O04 (DEC-331) item 3 is marked superseded by DEC-332 (the O04 integration notes removed `name` and `value` from the collector lists). The O04 integration notes carry a decision of their own, so they got a number of their own.
- DEC-305 item 2 (U17's request is not sealed) is marked closed by DEC-307 (U17-1). DEC-301 item 4 (U19's `SYSTEM_ACTOR`) has a note that TEN-018 replaced the constant by `timer_actor(tenant_id)`. DEC-344 item 8 (R08) and the tenant-pending paragraph of DEC-335 (R18) have a note that TEN-018 landed.
- `filter_options.py` named a second U12 decision (number 291) for "the warnings and reasons". U12's fragment has one decision, DEC-290, and puts the reason and warning texts in its Assumed list; the docstring now says that.
- Not folded: the one-line intro paragraphs of TEN-026, TEN-029 and TEN-052 (their number blocks).

## Hazards

| Fragment | Old id | New id | Note |
|---|---|---|---|
| TEN-018 | H-110 | H-110 | kept |
| TEN-018 | H-111 | H-111 | kept |
| TEN-020 | H-112 | H-112 | kept |
| TEN-020 | H-113 | H-113 | kept |
| TEN-064 | H-114 | H-114 | kept |
| TEN-052 | H-120 | H-120 | kept |
| TEN-052 | H-121 | H-121 | kept |
| TEN-052 | H-122 | H-122 | kept |
| TEN-052 | H-123 | H-123 | kept |
| TEN-026 | H-124 | H-124 | kept |
| TEN-026 | H-125 | H-125 | kept |
| TEN-026 | H-126 | H-126 | kept |
| TEN-026 | H-127 | H-127 | kept |
| TEN-029 | H-128 | H-128 | kept |
| U12 | H-130 | H-130 | kept |
| U13 | H-131 | H-131 | kept |
| U13 | H-132 | H-132 | kept |
| U14 | H-133 | H-133 | kept |
| U14 | H-134 | H-134 | kept |
| U18 | H-135 | H-135 | kept |
| U19 | H-136 | H-136 | U19 and U20 both carried it (U20 as a pointer to the U19 row): one row, tasks U18, U19, U20 |
| U20 | H-136 | H-136 | duplicate of the row above; merged |
| U36 | H-137 | H-137 | kept |
| U41 | H-138 | H-138 | kept |
| U18 | H-139 | H-139 | carried by U18 (about U17) and named by U17-1: one row, status closed by U17-1 |
| U24 | H-140 | H-140 | kept |
| U27 | H-141 | H-141 | kept |
| U27 | H-142 | H-142 | kept |
| U28 | H-143 | H-143 | kept |
| U28 | H-144 | H-144 | kept |
| U28 | H-145 | H-145 | kept |
| U32 | H-146 | H-146 | kept |
| U32 | H-147 | H-147 | kept |
| U32 | H-148 | H-148 | kept |
| U32 | H-149 | H-149 | kept |
| O03 | H-150 | H-150 | kept |
| O05 | H-151 | H-151 | kept |
| O04 | H-152 | H-152 | O04 and its integration notes carried it: one row, the integration result used |
| O04 (integration) | H-152 | H-152 | duplicate of the row above; merged |
| O08 | H-153 | H-153 | kept |
| R18 | H-154 | H-154 | kept |
| I14 | H-155 | H-155 | kept |
| I14 | H-156 | H-156 | kept |
| I14 | H-157 | H-157 | kept |
| I14 | H-158 | H-158 | kept |
| U33 | H-159 | H-159 | kept |
| U33 | H-160 | H-160 | kept |
| U31 | H-161 | H-161 | kept |
| U31 | H-162 | H-162 | kept |
| U38 | H-163 | H-163 | kept |
| U38 | H-164 | H-164 | kept |
| R08 | H-165 | H-165 | R08's number, outside the W2G block (H-155 to H-164 are used by I14, U33, U31, U38): H-165 is the next free number after the highest folded one, so it is unchanged |

Hazard rows folded in the existing 7-column format: the fragment's "verified by" and "status" cells became "Verified by ... Status: ...", the severity is `TBD`. Statuses were brought up to date from the integration notes: H-130, H-131, H-133 and H-134 name the W2C integration results (test_filter_options 10 passed, test_service_positions 3 passed, test_advisor_phoned_and_decline 8 passed, test_record_outcome 8 passed); H-152 uses the O04 integration result (unit 19 cases, integration 5 cases, pass); H-155, H-159 to H-165 say that the W2G integration run passed (iG-integration: 79 passed in the seven files); H-139 is closed (U17-1).

### Existing hazard rows amended

- H-09: TEN-052's tests were appended to "Verified by" (its fragment asked for it; the existing text is unchanged).
- H-02: U12 builds the options list and the not-suitable list; its tests were appended.
- H-T14: TEN-026 (the version store and the approvals) and TEN-064 (thirteen more rules take the policy) touched the control; their tests were appended.
- H-78 and H-80: TEN-018 makes connect bind the lead's tenant from the token; both rows named a test, `test_a_connect_with_no_tenant_bound_fails_closed`, that TEN-018 rewrote, and H-80 said connect fails closed with a 500 "until TEN-018". A note naming the replacement tests was appended; the existing text is unchanged.

## Known issues

Folded as one-line rows in the existing format, in task order, with the integration notes after their task. Counts: 118 rows added.

Not folded because a later fragment or the code closes them:

- I14 row 1: integration tests written, not run: the W2G integration run passed them (iG-integration, 79 passed).
- O04 row 1: validate and test-profile integration tests not run: run at integration (O04-integration: 5 cases pass on the pinned image).
- O04 row 2: name/value exact keys: superseded by DEC-332 (O04 integration removed both keys); replaced by the third integration row.
- R08 row 1: integration tests not run: the W2G integration run passed them (iG-integration).
- R08 row 2: writes need the tenant bound at the edge (TEN-018): closed, TEN-018 landed and the lead routes use require_role.
- R18 row 7: transitional tenancy rule until TEN-018: closed, TEN-018 landed and the support routes bind through current_actor and require_role.
- R18 integration row 1: the route tests token helper expiry: fixed at integration, nothing open.
- R18 integration row 2: duplicate of R18 row 1 (the session id in POST /support/codes); folded into that row.
- TEN-018 row 7: a statement of what the task resolved (R15, R04, TEN-003, TEN-019), not an open issue; it closes the existing rows listed in the folded file.
- U12 row 2: integration tests not run: ran at integration (W2C: test_filter_options 10 passed, test_service_positions 3 passed).
- U13 row 4: integration file not run: ran at integration (W2C: 8 passed).
- U14 row 1: integration file not run: ran at integration (W2C: 8 passed).
- U17-1 row 1: RespondToBooking and CancelBooking echo about_id=booking.id: closed by the W2D change that routes the echoes through booking_effects.queue_echo (about the service), commit 97f314c; checked in the code.
- U18 row 4: U17 plaintext booking request (U17-1): closed by DEC-307, RequestBooking queues through queue_message (commit 737adad).
- U31 row 1: integration tests not run: the W2G integration run passed them (iG-integration).
- U33 row 1: integration tests not run: the W2G integration run passed them (iG-integration).
- U36 row 1: FilterOptions (U12) not built: U12 is built (DEC-290) and its verdict puts a suspended service first.
- U38 row 1: integration tests not run: the W2G integration run passed them (iG-integration).
- iG-integration row 5: RecordingPushSender.gone_next: fixed in the integration run, nothing open.
- iG-integration row 6: criteria review jobs id prefix per call: fixed in the integration run, nothing open.
- iG-integration row 8: service move tests hasher: fixed in the integration run, nothing open.

Folded duplicates: TEN-018 integration row 2 (the lead and support route tests write only as the run tenant) and iG row 4 (two tenants cannot each hold an AuditHead) are one row labelled `R08 / TEN-018`; U24 row 2 and U27 row 3 (`ServiceRepository.save` rewrites the whole HealthcareService) are one row labelled `U24 / U27`; R18 integration row 2 repeats R18 row 1 and was folded into it.

Rows changed while folding (meaning otherwise kept): U19 row 2 now names `timer_actor(tenant_id)` instead of `SYSTEM_ACTOR`; U36 row 2 says `ReadTenantConfig` (TEN-026) exists but is not wired; U41 row 1 (K3 is a push template and no push sender exists) now says the push sender exists (I14, DEC-340) but sends only with a VAPID key and a subscription for the officer's role; TEN-018 row 6 and TEN-020 row 1 ("written, not run") were kept with a note that integration commits edited those tests and that no result is recorded (the W2A integration notes give none).

### Existing rows closed or changed

Deleted from `known-issues.md` (the fragments close them):

- R15, "The connect endpoint answers 500 (`TenantNotBound`) in production until TEN-018 binds the lead's tenant": closed by TEN-018 (DEC-250 item 12; `test_a_connect_binds_the_leads_tenant_from_the_token_with_nothing_else_bound`, `test_a_connect_runs_bound_to_the_leads_tenant_from_the_token`). The R08 fragment row of the same kind was not folded, see above.
- R04, "The R03 replay cache name carries no tenant": closed by TEN-018 (DEC-250 item 8, "This closes the R04 known issue").
- TEN-003, "The leak guard checks the binding in the test's own context only" (trigger: TEN-018, the reset-trap test through a request): TEN-018 lists TEN-003 as resolved and has the test (`test_edge_binding.py::test_nothing_is_left_bound_after_the_request`). The guard's own limit (a binding set from a thread is not seen by the guard) is not changed by that test; it was closed on the strength of the TEN-018 statement. Reopen it if that limit still matters.
- TEN-019, "Until TEN-018 binds the scope at the REST edge, any REST path that touches the cache fails closed": closed by TEN-018 (the edge binds; the replay key and the cache names are per tenant).
- U11-1, "UpdateCase with scores cannot persist them": closed in the code (commit d3a2e54, `CaseRepository.save` accepts the first recording of scores; `tests/integration/graph_store/test_case_repository.py::test_the_first_recording_of_scores_on_an_open_case_writes_them_and_reads_them_back` exists). The test was not run here.
- U17, "BookingRequested is written with session id None ... the prompt asked for the service id": decided by DEC-306 (booking events keep session id None; the decision and the domain test win).
- The plaintext-booking row (`U17-1` in the U18 fragment) was never in the shared file; it is closed by DEC-307 and not folded.

Changed: the U39 row ("`RecordAdvisorPhoned` (U13) is not built") now says U13 is built (DEC-292) and the phoned path of `ResolveReportFlag` still goes through `ReportCapacity`; the code confirms it (`resolve_report_flag.py`, its docstring still says U13 is not built).

No row about "TEN-010 REST-unbound" exists in `known-issues.md` (rows with the trigger TEN-010 are about the service and capacity statements and are older); none was changed. U25 row "The invitation lookup depends on U24's invitation shape ... U24 is not on this branch" has its trigger met (U24 is built) and was left: nothing here checked whether the shapes agree.

## Contracts

One section per task at the end of `docs/spec/contracts.md`, in decision order, 29 sections. Not added: the O04 integration notes ("none new"). U18 gained one bullet for `queue_echo` (added at integration, commit 97f314c, after the fragment). U19's bullet for `SYSTEM_ACTOR` now names `timer_actor(tenant_id)`. The two parentheticals that told the folder to add the new shape to `contracts.md` (TEN-018: ten roles; TEN-020: the wire form) were removed after doing it.

Existing contract text changed for the W2A renames (the old text kept where it still holds):

- `Actor` (section "Conventions"): `tenant_id` required, last; the factories `wall_actor`, `system_actor`, `anonymous_actor`, `timer_actor` replace the module constants `WALL_ACTOR`, `SYSTEM_ACTOR`, `text_code.ANONYMOUS`, `pin._ANONYMOUS`, `SCHEDULER_ACTOR`. The "names added by prompts" table row for `Actor` and `SYSTEM_ACTOR`, the `board_projector` row (`WALL_ACTOR`) and the I05 bullet (`SCHEDULER_ACTOR`, now `SCHEDULER_CHANNEL`) follow.
- `Role`: thirteen values (`tenant-admin`, `network-admin`, `platform-operator` added).
- `BusMessage`: the P08 line and the I07 `enqueue` line (`tenant_id` required, keyword-only, with `traceparent`) and the I08 line (`to_bus_message` builds the message with `from_wire`).
- `docs/spec/architecture.md`, the `capacity.events` row: the session id is `<tenant>:<service id>` on the wire (TEN-020 said the architecture rows needed it).

## Tenant pending and Assumed

As in the first fold: kept as bold paragraphs after the decision, omitted when the fragment said "None" alone (many say "None" with a reason, such as "No Cypher is added"; those were kept).

## Comments that named a fragment

Code and infrastructure comments that pointed at a fragment (which is now deleted) were re-pointed at the decision: `booking_effects.py` (H-135, DEC-300), `subscribe_alert.py` (DEC-341), `move_service.py` (DEC-343), `registration_submit.py`, `invite_reporter.py`, `pin.py` (the word "fragment" dropped), `safety_report_repository.py` (U41 known issue), `routes_lead.py` (DEC-344), `tests/support/relationship_matrix.py` (DEC-272), `infra/otel-allowlist.txt` (DEC-331 item 3, DEC-332). Comments of the first fold that still say "see the fragment" were not touched: `setup_service_by_lead.py` and `change_reporter_number.py` (U15, U16), `support_access.py` (O06), `alert_repository.py` (P17).

## Not verified

- No Neo4j, Docker or Service Bus test was run; every "passed" in the folded rows is copied from the integration notes of the fragments.
- The known-issue rows of W2A, W2D and W2E that say "not run" were kept as written; the fragments record no result for them.
- Whether the rows closed above are closed in the running product was checked in the code only for TEN-018's route binding, U11-1, the U17-1 and echo fixes and the U12 suspended check; nothing was executed.
