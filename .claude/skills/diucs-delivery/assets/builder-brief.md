# Builder brief

Fill in `<ID>` (task id), `<SESSION>` (your label, for example `build-<ID>`), `<SLUG>` (short name). Give this whole file to the builder agent.

---

You are the builder for task **<ID>** of the DIUCS capacity application (repository `C:\github\overwatch`). You have no memory of earlier work; everything you need is in the repository. Your label in the shared ledger is **<SESSION>**. Use it for every ledger command.

Read, in order: `.claude/skills/diucs-delivery/SKILL.md`, then `references/delivery-standard.md`, `references/autonomy-and-design-rules.md`, `references/multi-tenancy.md`, `references/collective.md` in the same skill. Then `docs/delivery/decisions.md` (it overrides the prompt and the specs) and your task prompt `docs/plan/prompts/<ID>.md`.

Do this:

1. **Orient.** From the repo root: `python .claude/skills/diucs-delivery/scripts/delivery.py lesson list --unread --session <SESSION>`, read them, then `lesson ack --session <SESSION>`.
2. **Claim.** `delivery.py claim <ID> --session <SESSION> --branch task/<ID>-<SLUG>`. If it refuses, stop and report why; do not work around it.
3. **Worktree.** `git worktree add ../overwatch-wt/<ID> -b task/<ID>-<SLUG> main`, and work only there.
4. **Red.** Write the tests the prompt lists, plus any the standard needs (property tests and 100% branch coverage for safety-critical code). Run them and confirm they fail for the right reason. Commit them alone: `<ID>: failing tests (red)`. Save the tail of the failing run for the evidence file.
5. **Green.** Write the least code that passes. Refactor. Commit: `<ID>: implement`. Heartbeat at least hourly: `delivery.py heartbeat <ID> --session <SESSION> --note "<where you are>"`.
6. **Checks.** Run every check in the standard for what you touched (Docker running for back-end tests; the harness starts its own throwaway Neo4j per DEC-008). All must pass. Fix the cause, never skip or weaken a test. Until the tenant-per-run harness exists (DEC-130 item 9), run Neo4j tests one at a time: take the machine-wide lock (`flock /tmp/diucs-neo4j-tests.lock <command>`), run your own tests plus unit and architecture first, and leave the full-suite run to the orchestrator. Parallel runs overloaded the machine and filled the disk. Check `df -h /` first and remove your own scratch.
   **Tenancy.** Follow `references/multi-tenancy.md`: tenant-scope every statement, key, channel, queue and message the task adds (or follow its transitional rule and list tenant-pending statements), take the tenant only from a verified source, never join across tenants, and write the two-tenant test. Add a "Tenant isolation" section to the evidence.
7. **Evidence.** Write `docs/delivery/evidence/<ID>.md` from `.claude/skills/diucs-delivery/assets/evidence-template.md`, commit it, and register each piece (for `tests-red` and `tests-green` the `--ref` starts with the commit sha; `review` checks the red commit is earlier than the green one): `delivery.py evidence <ID> --session <SESSION> --kind tests-red|tests-green|checks|spec-trace|privacy-scan|hazard-note|coverage ... --ref <where> --summary "<one line>"`. Update `docs/delivery/hazard-log.md` rows your task verifies.
8. **Review.** `delivery.py review <ID> --session <SESSION>`. Then report to whoever started you and wait: a different agent will verify. If they fail it, fix, redo the evidence, and review again.
9. **Deliver** (only after a pass): `git rebase main`, re-run the checks, then in the primary checkout `git merge --ff-only task/<ID>-<SLUG>`, then `delivery.py deliver <ID> --session <SESSION> --commit <sha>`. Remove your worktree.
10. **Learn.** If anything surprised you, publish a lesson and notify active sessions (see `collective.md`).

Rules that matter: no patient data anywhere; stay inside the task's scope (the prompt's "Out of scope" lists other tasks' work); if a name you need is not in `docs/spec/contracts.md`, add it there in your commit and publish a lesson; if you are blocked by something only a human can supply, run `delivery.py block <ID> --session <SESSION> --reason "..."` and stop; never claim a result you did not run. Do not push to a remote.

Finish with a short report: what you built, the evidence recorded, anything you assumed, anything you could not do.
