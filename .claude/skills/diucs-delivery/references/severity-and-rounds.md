# Severity, rounds and generated evidence (DEC-141)

Why this exists: in the first five days, whole tasks were failed three, four or eleven times over evidence wording, quote exactness and line numbers, while the code was right. Each failure restarted a builder-and-verifier cycle. Independent verification stays. What changes is what a verifier is allowed to fail a task for.

## Blocking findings (the verdict is FAIL)

Only these fail a task:

- A failing, missing or vacuous test for an acceptance criterion in the task prompt, or a test that passes for the wrong reason.
- Behaviour that is wrong or unsafe: a clinical or safety rule broken, a wrong figure shown as current, data loss or corruption, a security flaw.
- Any tenant-isolation leak: another tenant's data read, changed, deleted or detectable (existence), or a cross-scope query (DEC-130 to DEC-132, DEC-142).
- Patient data or a secret in code, tests, logs, fixtures or evidence.
- A claim in the evidence that the code contradicts, where a later reader would rely on the false claim for safety (for example "the lock is taken before the read" when it is not).
- A required check that fails or was not run (unit, architecture, lint, types, import contracts, the task's own integration tests).

## Non-blocking findings (the verdict is PASS, with notes)

Write them down, do not fail the task:

- Wording, quote exactness, paraphrase, line numbers, commit labels, table formatting, section order in the evidence.
- A surviving mutant that does not change behaviour, or an extra mutant the builder did not run.
- A residual limit that is already documented with a reason.
- Naming, style, docstring accuracy, a missing comment.
- A low-severity edge case with a stated fail-closed or documented outcome.

Each note goes in `docs/delivery/known-issues.md` as one line: task, what, where, and the trigger that should make someone fix it (a later task, or a date). The verifier may not hold a task for a note.

A builder may fix notes before delivery in the same delivery commit if the change touches no code (documentation or evidence only) and the diff shows that. Anything else waits in known-issues.

## Round cap

At most **two** verification rounds per task. After a second FAIL, the orchestrator reads the diff and the findings itself, then either delivers with the remaining findings recorded, sends one more targeted fix with a stated acceptance test, or splits the task. A third full verification round is not run. The orchestrator records the reason in the ledger note.

## Classifying a borderline finding

The verifier classifies each finding as BLOCKING or NOTE in its report and says why. If the builder disputes a classification, the orchestrator decides. When unsure about a tenant, safety or privacy question, classify it BLOCKING.

## Evidence is generated, not written

Check tables are produced by `scripts/record_checks.py`, which runs the commands, records each exit code and summary line, and writes the table with the commit sha and a dirty-tree flag. Do not hand-write a checks table, and do not paraphrase an exit code. The Neo4j runs go in as `--extra` commands under the machine-wide lock, so their exit codes are recorded the same way.

If a sentence in the evidence quotes an earlier commit, a guard line or a spec sentence, check it with `git show <commit>:<path>` and `grep -F` first. A quote that does not match is a NOTE, not a FAIL, unless a safety claim rests on it.

## Model use

Use the stronger model (Sonnet in a Sonnet-or-Haiku session, or Opus when it is the session model) for design, tenancy, security, concurrency and second-FAIL reviews. Use the default model for mechanical work. See `references/collective.md`, Models and consultation.
