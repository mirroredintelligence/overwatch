# F6B fragment: the racing-save flake and the cover address of the text sender

Two back-end defects found by the build waves. No decision number is taken (no shared doc edited);
no migration; no new statement.

## 1. `test_sixteen_racing_saves_of_one_new_practitioner_let_exactly_one_win` (flaky)

**Cause: a test that did not race, plus a product weakness it hid.**

- The test did not make its 16 saves concurrent. `save_practitioner` is "insert or replace": it reads
  the stored practitioner, then writes with the version it read. A save whose transaction opens after
  an earlier one committed reads that practitioner and replaces it, which is a legitimate save, so
  the number of winners depended on how fast the driver opened 16 sessions (3 to 14 of 16 "won").
  `write_tx` also runs a managed transaction, which the driver re-runs after a deadlock; a refused
  racer came back as a fresh save over the winner. The harness schema was fine: `tenant_resource_key`
  `(tenantId, key)` and `tenant_resource_id` `(tenantId, id)` are present and no duplicate node was
  ever made (the node count was 1 in every run). **The product cannot create a duplicate node under a
  race**; this is not a data-integrity defect.
- The product weakness: concurrent writers of one *stored* resource deadlocked (Neo4j
  `DeadlockDetected`, 15 victims of 16 on the old code). `Q-RES-UPSERT-ROOT` wrote the root with
  `SET n = row.props`, which rewrites the root's unique-constrained properties (`key`, `id`,
  `tenantId`) and so needs their index entries exclusively, while every writer waiting at `Q-RES-LOCK`
  holds them shared (the locking unique-key lookup). The unit of work never retries, so the victim
  surfaced as an unhandled `TransientError` (a 500) instead of the `Conflict` a stale write is meant
  to get (412 on a PUT).

**Fix.**

- `Q-RES-UPSERT-ROOT` now ends `SET n += row.props` (`resource_store.py`). A property the new version
  lacks, and the lock marks (`placeholder`, `lockStamp`), are sent as null, which `+=` removes
  (`_gone_from`, `_stored_root`), so the root keeps exactly the new properties, as `=` did. With
  `+=` the unique-key properties are not rewritten and the 16 racing replacers give 1 save and 15
  `Conflict`, no deadlock (probe, 16 of 16 runs).
- Tests: `tests/support/races.py` (`ReadBarrier`: every racer waits after its first read until all
  have read; `write_once`: an explicit transaction that is never re-run, as the unit of work is).
  `test_person_repository.py`: the original test uses them (a true race of 16 creates), and a new
  `test_sixteen_racing_saves_over_one_stored_practitioner_let_exactly_one_win` (red before the fix:
  `DeadlockDetected`). `test_resource_store.py`: a replacement leaves the root with exactly the new
  properties. The generated tenant-isolation test (`test_tenant_isolation.py`, 44) passes for the
  changed statement.

**Other racing tests**: every integration test with `racing` in its name, and the three named
`concurrent`, was run 10 times each (results in the report of the task). None other is flaky: the
create-only `add` repositories (cases, bookings, flags, link tokens, idempotency, contacts,
credentials) raise `Conflict` for an existing id whatever the timing, so a late racer cannot win.

Known issue (F6B-1): two tests that race an *insert-or-replace* save must use `ReadBarrier` and
`write_once` or they are flaky by construction. Trigger: a new "N racing saves" test over a repository
whose save reads before it writes.

## 2. The text sender addressed the post's own number during a cover (W7C-K2, W7B C)

**Cause (product).** `SmsMessageSender._address` read `contacts.get_phone(recipient_role_id)`, the
post's own number, whoever held the post; the prompt's link and the reply routing already use the
cover (`role_holder`, `services_for_phone_hash`). During any cover (U16's lead cover, W7C's own cover
of a reporter, DEC-820) the prompt text went to the original holder's number.

**Fix.**

- `domain/model/people.py`: `COVER_CONTACT_PREFIX` (`cover-`, one definition; `change_reporter_number`
  and `reporter_app` now use it), `cover_in_force(role, now)` and `phone_contact_key(role, now)`.
- `message_senders.py`: the sender takes a clock (required; `sender_runners(..., clock, observe)`,
  `workers_main` passes the container clock). The text sender reads the post and then the contact
  `phone_contact_key` names: `cover-<role id>` while a cover runs (cover ends at the instant
  `covered_until`, UTC comparison), the post's own number otherwise. A recipient that is not a post
  (a text code's contact key) is addressed by the key as before. A cover with no number kept sends
  nothing and records `no-contact`; the original holder, who has handed the post on, is not texted.
- The email sender follows the same rule: a cover is known by a number only, so while a cover runs the
  original holder's address is not used (`no-contact`). This goes beyond the text sender the task
  named; it is the same defect for the email channel.
- The push sender already read `role_holder` (the cover's devices), so it was right.
- The lead's test prompt (W7B C, `SendLeadTestPrompt`) checked and showed the post's own number; it now
  checks the cover's number while a cover runs and shows its ending, and an email test prompt for a
  covered post is refused. The reminder, the ladder steps and every other prompt queue a
  Communication for `role.id` and go through the same sender, so the sender fix covers them (the link
  hash already used `role_holder`).
- Tests: unit `test_message_senders_cover.py` (10) and `test_people_cover_contact.py` (6), route tests
  for the test prompt in `test_routes_lead_views.py` (3); two-tenant integration
  `tests/integration/adapters/inbound/workers/test_message_senders_cover_tenants.py` (3: each tenant's
  cover through its own recording sender and no other number, the cover ending, and a cover with no
  number kept never reading the other tenant's `cover-role-1`). The real `ChangeReporterNumber` makes
  the covers. Recording fake senders only, sample numbers `07700 900xxx`. Mutant: the sender reading
  the post's own number again fails 5 of these.

Known issues:

| ID | what | where | trigger |
|---|---|---|---|
| F6B-2 | A cover made by a service move (U37, `CompleteServiceMove`) keeps no number (a move keeps only the hash, P20), so the text for that post now records `no-contact` instead of going to the old holder's number; the same already held for a post made by an until-changed move. The ladder shows the lead | `move_service.py`, `message_senders.py` | a U37 cover or until-changed move |
| F6B-3 | While a cover runs the post's email channel reaches no one (a cover has a number, no address); the cover is not sent a text instead | `message_senders.py` | a covered post on the email channel |

W7C-K2 and the W7B C line "the sender does not read it" are closed by this task.
