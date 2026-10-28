# Evidence: <ID> <task title>

Builder: <SESSION> · Branch: `task/<ID>-<slug>` · Prompt: `docs/plan/prompts/<ID>.md`

## Summary
One or two sentences: what now works that did not.

## Commits
| Step | Commit | Message |
|---|---|---|
| Red | `<sha>` | `<ID>: failing tests (red)` |
| Green | `<sha>` | `<ID>: implement` |

## Red run (tests fail for the right reason)
Command: `<command>`
```
<last lines of the failing output, showing the assertion failures>
```

## Checks (all run at `<sha>`, Docker up)
| Command | Result |
|---|---|
| `uv run pytest` | `<n passed>` |
| `uv run ruff check . && uv run ruff format --check .` | clean |
| `uv run mypy src` | clean |
| `uv run lint-imports` | clean |
| Coverage, safety-critical modules | `<line %> / <branch %>` |
| Mutation check | `<tool and score, or the three lines mutated and the test that failed each>` |

## Requirement trace
| Requirement | Source | Proving test |
|---|---|---|
| `<for example: status is Not updated when overdue>` | `domain-rules.md` 1.3 step 3 | `tests/unit/domain/rules/test_status.py::test_overdue_is_not_updated` |

## Hazards
Rows of `docs/delivery/hazard-log.md` this task verifies or changes, and the test references added. New hazards found: `<none or ids>`.

## Privacy
Scan result and what was searched: `<result>`.

## Tenant isolation
Say which applies. **Tenant-scoped statements, keys, channels, queues and messages this task adds:** `<list, with query ids>`. **Where the tenant comes from** (token, session, inbound number, link token, pairing, message property): `<source>`. **Two-tenant test:** `<test path>` and what it shows (tenant A cannot read, change, delete or detect tenant B; same key in both tenants does not collide). **Predicate-removal mutant:** `<statement changed and the test that failed>`. **Tenant-pending statements** (transitional rule, until tenancy is enforced): `<query ids and why>`. **Cross-scope reads this task would need under DEC-132:** `<none or list>`. Mark `n/a` with a reason only if the task touches no data, messages, caches, queues or sign-in.

## Decisions and assumptions
Deviations from the prompt or spec (with the `DEC-n` that authorises each), assumptions made, `[ASSUMED]` values used.

## Not done
Anything left out and why. Anything you are stuck on (a real credential, account or spend) and what you used instead.

## Verification (filled in by the verifier)
Verifier: `<label>` · Result: `<pass|fail>` · Date: `<date>`
Re-ran: `<what>` · Tried to break: `<what>` · Findings: `<none or list>`
