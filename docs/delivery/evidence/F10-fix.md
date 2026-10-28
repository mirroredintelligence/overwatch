# Evidence: F10-fix Test harness leaks Docker volumes

Builder: build-F10fix · Branch: `task/F10-fix-volume-leak` · Prompt: none (defect fix, no ledger task; DEC-128)

## Summary
The harness removed its throwaway Neo4j containers with `docker rm -f`, which orphaned the image's two anonymous volumes on every run. Both removal paths now use `docker rm -f -v`.

## Commits
| Step | Commit | Message |
|---|---|---|
| Red | `a85161b` | `F10-fix: failing tests (red)` |
| Green | `524101d` | `F10-fix: implement` |
| Docs | the commit that adds this file | `F10-fix: evidence, DEC-128` |

## Red run (tests fail for the right reason)
Command: `uv run pytest tests/unit/support/test_container_removal.py -q`
```
>       assert "-v" in removals[0]
E       AssertionError: assert '-v' in ('rm', '-f', 'diucs-test-neo4j-old')
FAILED ...::test_stop_throwaway_neo4j_removes_the_container_and_its_anonymous_volumes
FAILED ...::test_reaper_removes_a_stale_container_and_its_anonymous_volumes
2 failed, 1 passed
```
The third test (reaper never removes a container outside the `diucs-test-neo4j-` prefix) passes before and after: it pins existing behaviour.

## Checks (run at `524101d`, Docker up)
| Command | Result |
|---|---|
| `uv run pytest tests/unit -q` | 3248 passed |
| `uv run ruff check .` / `ruff format --check .` | clean / 336 files formatted |
| `uv run mypy src` | no issues in 132 files |
| `uv run lint-imports` | 4 kept, 0 broken |
| Real Docker check (script starts and stops a throwaway Neo4j through `start_throwaway_neo4j` and `stop_throwaway_neo4j`) | `docker volume ls -qf dangling=true \| wc -l`: before 4, after 4 (no growth) |
| Coverage, mutation | not run (test-harness change only) |

## Requirement trace
| Requirement | Source | Proving test |
|---|---|---|
| Single-container removal passes `rm -f -v <name>` | DEC-128 | `tests/unit/support/test_container_removal.py::test_stop_throwaway_neo4j_removes_the_container_and_its_anonymous_volumes` |
| Reaper removal passes `rm -f -v <name>` | DEC-128 | `...::test_reaper_removes_a_stale_container_and_its_anonymous_volumes` |
| Reaper never touches names outside the prefix | DEC-013, DEC-108 | `...::test_reaper_sweep_never_removes_a_container_outside_the_throwaway_prefix` |

## Hazards
None changed. No new hazards.

## Privacy
No data or identifiers added.

## Decisions and assumptions
DEC-128 (checked no `task/*` branch uses that number). The existing helper `FakeDocker.removed()` in `tests/unit/support/test_reaper.py` matched `("rm", "-f")` exactly; it now matches `("rm", "-f", "-v")` so the existing reaper tests keep working. Nothing else in the harness changed. Lesson added for other builders. Existing leaks: `docker volume prune -f`.

## Not done / human-required
The full integration suite was not run. The one real Docker check covers the start and stop path only. The reaper's `-v` is proven by the unit test, not against real Docker.

## Verification (filled in by the verifier)
Pending an independent verifier.
Verifier: `<label>` · Result: `<pass|fail>` · Date: `<date>`
Re-ran: `<what>` · Tried to break: `<what>` · Findings: `<none or list>`
