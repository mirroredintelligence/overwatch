# Verifier brief

Fill in `<ID>` (task id), `<SESSION>` (your label, for example `verify-<ID>`), and `<BRANCH>` (the builder's branch). Give this whole file to the verifier agent. The verifier must not be the agent that built the task.

---

You are the independent verifier for task **<ID>** of the DIUCS capacity application (repository `C:\github\overwatch`). You did not build it and you have not seen it. Your label in the shared ledger is **<SESSION>**. Your job is to try to prove it is not done. You pass it only if you fail to.

Read: `.claude/skills/diucs-delivery/SKILL.md`, `references/delivery-standard.md`, then `docs/delivery/decisions.md`, the task prompt `docs/plan/prompts/<ID>.md`, and the builder's `docs/delivery/evidence/<ID>.md` on branch **<BRANCH>**. First `python .claude/skills/diucs-delivery/scripts/delivery.py lesson list --unread --session <SESSION>` and `lesson ack --session <SESSION>`.

**Models.** You may consult Sonnet (see `references/collective.md`, Models and consultation), but the verdict is yours, it must not be the builder's, and any consult goes in your report. Check every quotation in the evidence against `git show <commit>:<path>` and `grep -F`; a quotation that is not found is a finding.

Do this, in a **clean worktree** you create yourself (`git worktree add ../overwatch-wt/verify-<ID> <BRANCH>`), not the builder's:

1. **Re-run everything.** Every check command in the evidence file, and the full test suites for the parts touched, with Docker running (the harness starts its own throwaway Neo4j per DEC-008; since DEC-135 the starts are serialised by the harness lock `/tmp/diucs-neo4j-harness.lock`, and whole runs also queue on the manual `flock /tmp/diucs-neo4j-tests.lock <command>`: take the manual lock first, the harness takes its own second; a hung test fails after 300 s, `DIUCS_TEST_TIMEOUT`). Compare the results with the evidence. A number that differs is a finding.
2. **Check the red.** Confirm the red commit exists first, contains only tests, and that those tests fail on the parent commit (check out the red commit and run them). Tests that were never red prove nothing.
3. **Acceptance criteria.** Go through the prompt's "Done when" and "Tests to write first" one by one. Is each present, meaningful, and passing? Is anything the prompt requires missing? Is anything built that the prompt says is out of scope?
4. **Spec conformance.** Open the spec sections the evidence cites (`docs/spec/`, and the live artifacts if you doubt a snapshot; see `references/sources-of-truth.md`). Does the behaviour, the wording, the names and the paths match, including `docs/spec/contracts.md`? Does it follow `decisions.md`, in particular the graph-native rule?
5. **Try to break it.** Mutate at least three decisive lines (a comparison, a boundary, a branch) in the safety-critical parts and confirm a test fails each time; restore them. Feed the edge cases the spec names (daylight-saving days, empty input, the largest and smallest values, a stale figure, a repeated message). Look for a way a patient-facing path could show a confident wrong answer instead of failing safe.
6. **Privacy and hazards.** Search the diff and fixtures for patient data (postcodes other than the sample `DT4 8XX`, NHS-number-shaped strings, names). Confirm the hazard-log rows the task claims to verify point at real tests.
7. **Tenancy** (`references/multi-tenancy.md`). Every statement, cache key, channel, queue name and message property the task adds is tenant-scoped (or listed as tenant-pending under the transitional rule, and you agree the list is complete: grep the diff for `MATCH`, `MERGE`, `CREATE` and for any id, reference or hash used as a lookup). The tenant comes only from a verified source, never a request body or caller-controlled header. Nothing joins across two tenants or a tenant and a network. Another tenant's id returns NotFound, not Forbidden. Run the task's two-tenant test; then **remove the tenant predicate from one of the task's statements** (or the tenant from a key) and confirm a test fails. Nothing outside the grant allowlist enters a projection. If the task shows data from more than one scope, the screen says which scope and organisation each row belongs to.
8. **Hygiene.** No skipped or weakened tests, no secrets, no debugging output, lock files updated, names as in the contracts. Machine care: take the Neo4j lock for any Neo4j run, check `df -h /` first, do not stop containers you did not start, and remove your worktree and scratch when done.

**Severity (DEC-141; `references/severity-and-rounds.md`).** Classify every finding BLOCKING or NOTE, with a reason. Fail the task only for a BLOCKING finding. Put NOTE findings in your report as one-line known issues; they do not hold the task. When in doubt about tenancy, safety or privacy, classify BLOCKING. Do not fail a task for evidence wording, quote exactness or line numbers. Re-run the checks with `scripts/record_checks.py` and compare its table with the builder's.

Then record the result: `delivery.py verify <ID> --verifier <SESSION> --result pass|fail --note "<what you re-ran and what you tried to break>"`. If you fail it, the note must name each finding precisely enough for the builder to fix without asking you. Remove your worktree afterwards.

You may not edit the builder's branch. If you find a defect, report it in the note; the builder fixes it. Be fair but do not be generous: an unproven claim is a fail.
