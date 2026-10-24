# Verifier brief

Fill in `<ID>` (task id), `<SESSION>` (your label, for example `verify-<ID>`), and `<BRANCH>` (the builder's branch). Give this whole file to the verifier agent. The verifier must not be the agent that built the task.

---

You are the independent verifier for task **<ID>** of the DIUCS capacity application (repository `C:\github\overwatch`). You did not build it and you have not seen it. Your label in the shared ledger is **<SESSION>**. Your job is to try to prove it is not done. You pass it only if you fail to.

Read: `.claude/skills/diucs-delivery/SKILL.md`, `references/delivery-standard.md`, then `docs/delivery/decisions.md`, the task prompt `docs/plan/prompts/<ID>.md`, and the builder's `docs/delivery/evidence/<ID>.md` on branch **<BRANCH>**. First `python .claude/skills/diucs-delivery/scripts/delivery.py lesson list --unread --session <SESSION>` and `lesson ack --session <SESSION>`.

Do this, in a **clean worktree** you create yourself (`git worktree add ../overwatch-wt/verify-<ID> <BRANCH>`), not the builder's:

1. **Re-run everything.** Every check command in the evidence file, and the full test suites for the parts touched, with Docker running (the harness starts its own throwaway Neo4j per DEC-008). Compare the results with the evidence. A number that differs is a finding.
2. **Check the red.** Confirm the red commit exists first, contains only tests, and that those tests fail on the parent commit (check out the red commit and run them). Tests that were never red prove nothing.
3. **Acceptance criteria.** Go through the prompt's "Done when" and "Tests to write first" one by one. Is each present, meaningful, and passing? Is anything the prompt requires missing? Is anything built that the prompt says is out of scope?
4. **Spec conformance.** Open the spec sections the evidence cites (`docs/spec/`, and the live artifacts if you doubt a snapshot; see `references/sources-of-truth.md`). Does the behaviour, the wording, the names and the paths match, including `docs/spec/contracts.md`? Does it follow `decisions.md`, in particular the graph-native rule?
5. **Try to break it.** Mutate at least three decisive lines (a comparison, a boundary, a branch) in the safety-critical parts and confirm a test fails each time; restore them. Feed the edge cases the spec names (daylight-saving days, empty input, the largest and smallest values, a stale figure, a repeated message). Look for a way a patient-facing path could show a confident wrong answer instead of failing safe.
6. **Privacy and hazards.** Search the diff and fixtures for patient data (postcodes other than the sample `DT4 8XX`, NHS-number-shaped strings, names). Confirm the hazard-log rows the task claims to verify point at real tests.
7. **Hygiene.** No skipped or weakened tests, no secrets, no debugging output, lock files updated, names as in the contracts.

Then record the result: `delivery.py verify <ID> --verifier <SESSION> --result pass|fail --note "<what you re-ran and what you tried to break>"`. If you fail it, the note must name each finding precisely enough for the builder to fix without asking you. Remove your worktree afterwards.

You may not edit the builder's branch. If you find a defect, report it in the note; the builder fixes it. Be fair but do not be generous: an unproven claim is a fail.
