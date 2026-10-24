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

## Decisions and assumptions
Deviations from the prompt or spec (with the `DEC-n` that authorises each), assumptions made, `[ASSUMED]` values used.

## Not done / human-required
Anything left out and why. Anything that needs a human.

## Verification (filled in by the verifier)
Verifier: `<label>` · Result: `<pass|fail>` · Date: `<date>`
Re-ran: `<what>` · Tried to break: `<what>` · Findings: `<none or list>`
