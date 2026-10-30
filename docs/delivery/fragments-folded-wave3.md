# Build wave 3: fragments folded

The per-task fragments in `docs/delivery/fragments/` of build wave 3 (bundles W3A to W3E, with the fixG integration note of TEN-026 and the bullet-style items of R07, U40, U42 and U43) were folded into `decisions.md`, `hazard-log.md`, `known-issues.md` and `docs/spec/contracts.md`, and the fragment files were deleted (they stay in git history, last present at the commit before the one that removes them). This file is the audit of what was numbered how. Earlier folds: `fragments-folded-wave1.md`, `fragments-folded-wave2.md`.

This was a documentation fold. Nothing was run as part of it beyond the checks listed under "Not verified".

Rules used. Every decision a fragment numbered was kept, because no number was held by another entry: the shared files had DEC-344 and H-165 as their highest before the fold, and the fragments' blocks (DEC-350 to 353, 370 to 374, 390 to 416, 440 to 442, 450; H-170 to 175, 180 to 184, 190 to 221) were free. One decision had no number: R07's bullet "the `$filter-options`, `$advisor-phoned`, `$declined` and `$close` answers ... The routes hold no rule" took DEC-399, the next free number after DEC-398 (the R07 block). U34 had two placeholders, `H-NEW-1` and `H-NEW-2`; they took H-222 and H-223, the next free numbers after the highest folded hazard (H-221). Hazard numbers H-190 to H-194 (U40, U42, U43) and H-192 (R07) are written as bullets in their fragments; they are kept and written as table rows here.

Collision check, run on the tree before and after: no decision or hazard number is defined twice; no fragment number collides with a number already in the shared files. Highest before the fold: DEC-344 and H-165. Highest after: DEC-450 and H-223. Numbers left unused: decisions DEC-345 to 349, 354 to 369, 375 to 389, 409, 417 to 439, 443 to 449; hazards H-166 to H-169, H-176 to H-179, H-185 to H-189, H-209 to H-214.

## Decisions

Fragments with no decision: TEN-026 (integration, fixG). The decision text was copied with its status line and its items unchanged. "Tenant pending", "Assumed" and "Tenant isolation" sections are added as bold paragraphs after the first decision of their fragment (after the last decision for none), omitted where the fragment said "None" alone, as in the earlier folds.

| Fragment | Old id | New id | Note |
|---|---|---|---|
| R07 | DEC-397 | DEC-397 | kept (bullet form in the fragment; heading written as "POST /fhir/ServiceRequest opens a case in two units ...") |
| R07 | DEC-398 | DEC-398 | kept (bullet form) |
| R07 | (no number) | DEC-399 | unnumbered bullet, the next free number after DEC-398 |
| R11 | DEC-413 | DEC-413 | kept |
| R11 | DEC-414 | DEC-414 | kept |
| R11 | DEC-415 | DEC-415 | kept |
| R11 | DEC-416 | DEC-416 | kept |
| TEN-023 | DEC-350 | DEC-350 | kept |
| TEN-024 | DEC-351 | DEC-351 | kept |
| TEN-025 | DEC-352 | DEC-352 | kept |
| TEN-065 | DEC-353 | DEC-353 | kept |
| TEN-040 | DEC-370 | DEC-370 | kept |
| TEN-040 | DEC-371 | DEC-371 | kept |
| TEN-038 | DEC-372 | DEC-372 | kept |
| TEN-039 | DEC-373 | DEC-373 | kept |
| TEN-042 | DEC-374 | DEC-374 | kept |
| U42 | DEC-390 | DEC-390 | kept (bullet form) |
| U42 | DEC-391 | DEC-391 | kept (bullet form) |
| U43 | DEC-392 | DEC-392 | kept (bullet form) |
| U43 | DEC-393 | DEC-393 | kept (bullet form; "DEC-393 also" is its second bullet) |
| U40 | DEC-394 | DEC-394 | kept (bullet form) |
| U40 | DEC-395 | DEC-395 | kept (bullet form) |
| U40 | DEC-396 | DEC-396 | kept (bullet form) |
| U21 | DEC-400 | DEC-400 | kept |
| U21 | DEC-401 | DEC-401 | kept |
| U22 | DEC-402 | DEC-402 | kept |
| U22 | DEC-403 | DEC-403 | kept |
| U22 | DEC-404 | DEC-404 | kept |
| U29 | DEC-405 | DEC-405 | kept |
| U29 | DEC-406 | DEC-406 | kept |
| U29 | DEC-407 | DEC-407 | kept |
| U34 | DEC-408 | DEC-408 | kept |
| U37 | DEC-410 | DEC-410 | kept |
| U37 | DEC-411 | DEC-411 | kept |
| U37 | DEC-412 | DEC-412 | kept |
| TEN-030 | DEC-440 | DEC-440 | kept |
| TEN-031 | DEC-441 | DEC-441 | kept |
| TEN-031 | DEC-442 | DEC-442 | kept |
| TEN-032 | DEC-450 | DEC-450 | kept |

Headings of bullet-form decisions (R07, U40, U42, U43) are short titles written for this fold, since the fragment gave no title. The bullet text is the body, unchanged.

Notes. DEC-414 item 1 closes the U32 known issue (see the closed rows below). DEC-440 closes DEC-134 item 12 and DEC-146 items 2 and 3, as its own title says; the earlier text of DEC-134 and DEC-146 is not edited.

## Hazards

| Fragment | Old id | New id | Note |
|---|---|---|---|
| TEN-023 | H-170 | H-170 | kept |
| TEN-024 | H-171 | H-171 | kept |
| TEN-024 | H-172 | H-172 | kept |
| TEN-025 | H-173 | H-173 | kept |
| TEN-025 | H-174 | H-174 | kept |
| TEN-065 | H-175 | H-175 | kept; status partial, as the fragment says |
| TEN-040 | H-180 | H-180 | kept |
| TEN-040 | H-181 | H-181 | kept |
| TEN-038 | H-182 | H-182 | kept |
| TEN-039 | H-183 | H-183 | kept |
| TEN-042 | H-184 | H-184 | kept |
| U42 | H-190 | H-190 | kept; written from the fragment's bullet |
| U40 | H-191 | H-191 | kept; written from the fragment's bullet |
| R07 | H-192 | H-192 | kept; written from the fragment's bullet |
| U43 | H-193 | H-193 | kept; written from the fragment's bullet |
| U40 | H-194 | H-194 | kept; written from the fragment's bullet |
| U21 | H-195 | H-195 | kept |
| U22 | H-196 | H-196 | kept |
| U22 | H-197 | H-197 | kept |
| U29 | H-198 | H-198 | kept |
| U29 | H-199 | H-199 | kept |
| U37 | H-200 | H-200 | kept |
| U37 | H-201 | H-201 | kept |
| U37 | H-202 | H-202 | kept |
| U37 | H-203 | H-203 | kept |
| R11 | H-204 | H-204 | kept |
| R11 | H-205 | H-205 | kept |
| R11 | H-206 | H-206 | kept |
| R11 | H-207 | H-207 | kept |
| R11 | H-208 | H-208 | kept |
| TEN-030 | H-215 | H-215 | kept |
| TEN-030 | H-216 | H-216 | kept |
| TEN-031 | H-217 | H-217 | kept |
| TEN-031 | H-218 | H-218 | kept |
| TEN-031 | H-219 | H-219 | kept |
| TEN-032 | H-220 | H-220 | kept; status closed |
| TEN-032 | H-221 | H-221 | kept; status closed |
| U34 | H-NEW-1 | H-222 | placeholder; next free number after H-221 |
| U34 | H-NEW-2 | H-223 | placeholder; next free number after H-221 |

Hazard rows are in the existing 7-column format: the fragment's "verified by" and "status" cells became "Verified by ... Status: ...", and the severity is `TBD`, as the earlier folds did. Where a fragment's "status" was itself `TBD` (R11), only the severity is set. Statuses that name an integration run ("built; integration run recorded in the report" in TEN-024 to TEN-031) are copied as written: the report they name is not in this repository, and nothing here checked it.

### Existing hazard rows amended

- H-09 and H-120: TEN-038 asks that its tests be added to "Verified by" (its fragment says so). The TEN-038 test references are appended to the cell; the existing text is unchanged.
- H-T19 is cited by the TEN-031 decision header as "audit F H-T19", but it is not a row of `hazard-log.md`. Not added; see "Not closed".

## Known issues

Folded as one-line rows in the existing format, in fragment order, appended at the end of the table. Counts: 87 rows added, of which 83 are fragment rows (R07 2, R11 10, TEN-023 3, TEN-024 3, TEN-025 3, TEN-026 integration 1, TEN-030 4, TEN-031 4, TEN-032 4, TEN-038 3, TEN-039 4, TEN-040 5, TEN-042 5, TEN-065 3, U21 3, U22 3, U29 6, U34 5, U37 6, U40 2, U42 2, U43 2) and 4 are rows the fold added because a fragment says so in its text: the two-tenant tests of R07, U29 and U34 are "not written" (their own Tenant isolation or Tenant pending sections say so), and the alert consumer's tenant binding (U34) is a requirement of the fragment that this fold did not check.

Not folded: R11's four rows "(closed by R11)" for U25, U27, U28 and U32 are closures (below), not new rows.

Rows the fragment bullets had no trigger for were recorded as "none stated in the fragment" (U40, the presence TTL test). The rows of R07, U40, U42 and U43 were written from bullets: their "Where" is the module the fragment names; the R07 capability row points at `adapters/inbound/fhir_rest/capability.py`, which builds the CapabilityStatement.

Statements the Tenant pending sections name as "still unconverted" (U21 `bookings.get`, U22 the booking Task writes, U29 the Task and Practitioner reads, U34 the alert statements, each "TEN-009/010/011 pending") were **not** folded as known issues. TEN-030, folded in this same wave, states that every registered statement carries its tenant predicate and that none is unconverted (DEC-440 item 1, and the TEN-030 fragment's Tenant pending section). Those statements were therefore not left open as unconverted. Their two-tenant tests are a separate matter: U21 and U22 have one each (their Tenant isolation sections name the tests); U29, U34 and R07 do not, and their rows are added above.

### Existing rows closed

Deleted from `known-issues.md`, each because the fragment that fixes it says so (the reason in brackets):

- TEN-001, "`QueryRegistry.ratchet_ids` double-counts ..." (TEN-030: the ratchet is gone, DEC-440 item 1).
- TEN-001, "`test_the_ratchet_may_only_shrink` pins `<= 126` by hand ..." (TEN-030, DEC-440 item 1).
- TEN-002, "An unbound unit of work still opens and runs unconverted statements unscoped ..." (TEN-030 refuses an unbound open, DEC-440 item 4).
- TEN-004, "A second tenant that writes a device id, a message id or a processed key ..." (TEN-032 drops the single-property keys, DEC-450 item 1).
- TEN-004, "The ratchet cap in `test_queries.py` (`<= 118`) ..." (TEN-030, DEC-440 item 1).
- I03, "`Q-OUTBOX-LOCK`, `Q-OUTBOX-PUBLISHED`, ... are unconverted ..." (TEN-030: no statement is unconverted, DEC-440 item 1).
- TEN-005, "While the superseded single-property unique keys exist (until TEN-032) ..." (TEN-032, DEC-450).
- TEN-009, "On the production schema (the single-property keys `resource_id` ...)" (TEN-032, DEC-450).
- TEN-009, "Statements still on the ratchet that create or match `Resource`, `Concept` or `Identifier` nodes with no tenant (`Q-COMM-ADD` ...)" (TEN-030: no statement is unconverted).
- TEN-009, the second such row ("(`Q-ROLE-CHANNEL`, `Q-PROV-LINK` ...)") (TEN-030, as above).
- TEN-009, "The generated predicate-removal test removes every `tenantId: $tenant` of a statement at once ..." (TEN-030 item 8: the removal runs per statement, with no survivor over 211).
- TEN-014, "On the shared harness schema the single-property `device_id` key ..." (TEN-032 drops the key).
- TEN-017, "The shared harness schema keeps the single-property `audit_head_id`, ..." (TEN-032 drops the keys).
- R08, "Tenant B's seeded rows use other codes ... until TEN-032" (TEN-032 drops the single-property Concept key).
- U14, "Any two-tenant write that shares a Concept (the category codes) fails ..." (TEN-032, as above).
- U28, "The tenant has no stored area districts yet; `area_districts_for` must be given by the composition root ..." (R11, DEC-416 item 2: the area is the setting `tenant_areas`).
- U32, "The edge has to call `RecordTextCodeVerified` after every successful `VerifyTextCode` ..." (R11, DEC-414 item 1: `ConfirmDeviceByTextCode` verifies and records in one call).

Edited, not deleted: U27, "The write of `PersistRegistration` is not wired into the container or an HTTP route ..." now says it is not wired into an HTTP route, since the container composes it (R11, DEC-416 item 1). The route is R10's.

## Contracts

Merged into the existing task sections of `docs/spec/contracts.md`, not dumped at the end. Each fragment's contract bullets sit in a sub-section headed with the fragment's id and decision numbers, inside the section for the same work:

- R07 under "OpenCase and UpdateCase (U11, DEC-237)"; R11 under "Text codes (U25, DEC-242)"; TEN-023 under "Tenant directory, global statements and secret references (TEN-007, DEC-163)"; TEN-024 under "ConfirmCapacity (U02, DEC-112)"; TEN-025 under "Inbound queue consumers (I08, DEC-165)"; TEN-030 under "Tenancy seam, unit of work and scoped transaction (TEN-002, DEC-146)"; TEN-031 and TEN-032 under "Tenant schema: composite keys, the stamp and the migration runner (TEN-005, DEC-159)"; TEN-038 under "Network domain model and rules (TEN-036, DEC-235)"; TEN-039 under "Board cache and live update (U09)"; TEN-040 under "REST edge tenant binding (TEN-018, DEC-250)"; TEN-042 under "Outbound message senders (I10, DEC-199)"; TEN-065 under "Tenant policy in the rules (TEN-021, DEC-233)"; U21 under "Cancel booking (U20, DEC-302)"; U22 under "Respond to booking and decline reason (U18, DEC-300 and DEC-305)"; U29 under "Registration review (U28, DEC-317 to DEC-319)"; U34 under "Alert preferences (U33, DEC-341)"; U37 under "PIN set-up and sign-in (U32, DEC-321 to DEC-324)".
- U40 (clinical advice), and U42 and U43 (audit replay and planning analysis) had no existing section and are two new sections at the end of the file.

Seam statements the fold changed, because they described the API TEN-030 and TEN-031 removed or narrowed (the old text is otherwise kept):

- "Repository adapters" (the constructors take the `ScopedTx` the unit of work holds, not `AsyncManagedTransaction`).
- "Tenancy seam, step one (TEN-001 ...)": `QueryRegistry(unconverted=UNCONVERTED)` and the ratchet are marked as superseded by TEN-030 (`QueryRegistry()`, no ratchet, `unconverted.py` deleted); `run_query` takes a `ScopedTx` only.
- "Tenancy seam, unit of work and scoped transaction (TEN-002)": `type Tx = ScopedTx` since TEN-030, with the raw transaction refused by `RawTransactionRefused` and `run_global_query` taking `GlobalTx`.
- "Tenant schema": the `contracted_container()` entry says the shared schema has no superseded keys since TEN-032 and the function drops nothing that exists.
- "Link pages": "(off the ratchet)" now reads "registered statements; there is no ratchet since TEN-030".

`multi-tenancy.md` and `SKILL.md` are edited as step 2 asks (see the commit that carries them): the transitional rule is marked as history, superseded by DEC-440; the "once enforced" heading is "enforced since TEN-030"; the Neo4j lock rule text is untouched.

## Not closed (for the owner to look at)

These rows or hazards may now be stale, but the fragments do not say they are fixed, so they were not changed:

- TEN-005, "`test_tenant_isolation.py` starts a second Neo4j container ... delete `contracted_container`": the trigger (TEN-032) has landed, but TEN-032 kept `contracted_container()` (its known issues name TEN-034 for the cleanup).
- TEN-005, "The composite keys ignore a node whose `tenantId` is null ... nothing runs it yet": TEN-031 runs the check; the null limit remains, as H-217.
- TEN-005, the `Q-CASE-BY-REF` and `Q-CASE-SET-REFERENCE` row: TEN-030 scopes these statements; the open-only lookup is TEN-010's trigger and nothing here checked it.
- TEN-009, "`Q-PERSON-PHONE-FIND` (unconverted) finds a phone across tenants ...": it is now scoped, but the same-sender-two-tenants test it asks for is not written.
- U04 and U07 rows: the premise that nodes carry no `tenantId`, and the missing flag two-tenant test.
- I08, U06, W07 and U10 rows name unconverted statements or the audit chain; TEN-030 converts the statements, but the rows also name a test gap or a delivered decision (TEN-017), so they were left.
- TEN-009 row about the `IN_SYSTEM` edges that earlier puts duplicated (DEC-164 item 5): no fragment addresses it.
- H-105 (hazard log) says the flag statements "are on the ratchet": no ratchet exists after TEN-030.
- TEN-064 row listing seven use cases "without a policy": the ratchet allowlist it names is gone; the rule rows are unchanged.

## Not verified

- Nothing was run as part of the fold beyond these checks: `delivery.py check-messages` printed the clean line (no model name, no trailer on unpushed commits); the backend keyword run `uv run pytest tests/unit tests/architecture -k "doc or decision or hazard or ledger or fragment"` passed (68 selected); the skill's script tests (`.claude/skills/diucs-delivery/scripts`) passed (67). No Neo4j, Docker, Service Bus or two-tenant test was run.
- Every status, "passed" count and "integration run" in the folded hazard and known-issue rows is copied from the fragments. None was checked in this repository.
- The closures above rest on the fragments' own statements (TEN-030 says no statement is unconverted; TEN-032 says the single-property keys are dropped; R11 says the edge records a verified code). The code was not read to confirm them.
- The fragments' "Lessons" and "Evidence" sections (TEN-026, fixG) were not folded: there is no shared file for them. The lesson about the single-property audit head key is superseded by TEN-032.
- Severity is `TBD` for every new hazard, as the rules require (the clinical safety officer assigns it).
