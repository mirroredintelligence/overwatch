# DIUCS (overwatch)

Mission: get this product developed, verified and finished to a high quality. The lead developer works autonomously and is the only developer; there is one long-lived branch, `main`.

- **Start every session, and re-run after any context compaction or summary, by invoking the `diucs-delivery` skill** (`.claude/skills/diucs-delivery/SKILL.md`). It holds the rules: the ledger, evidence, independent verification, tenancy (DEC-130 to DEC-134), and the autonomy rules (DEC-133: no human gates; ask the owner only if genuinely stuck).
- Decisions are in `docs/delivery/decisions.md` and override the specs and the task prompts.
- `main` is the only long-lived branch. Task branches are short-lived; fast-forward into `main`, push `main` after each delivery, delete the task branch.
- Neo4j tests run one at a time: `flock /tmp/diucs-neo4j-tests.lock <command>`.
