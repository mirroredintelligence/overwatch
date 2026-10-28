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
Verifier: `verify-F10fix` · Result: `pass` · Date: `2026-10-28`
Re-ran: unit suite, ruff, format, strict mypy, lint-imports at `d98385f` in a clean worktree; red and green runs; real Docker on both removal paths · Tried to break: three broken reapers against the edited FakeDocker · Findings: none that fail the fix; two notes below.

1. Red then green: pass. At `a85161b` two tests fail on `assert '-v' in ('rm', '-f', 'diucs-test-neo4j-old')` (2 failed, 1 passed; no import errors). The red commit holds one new test file and was committed 7 seconds before green. At `524101d` all 10 tests in tests/unit/support pass.
2. Diff `a85161b..524101d`: pass. Two one-line changes to `docker rm` in `stop_throwaway_neo4j` and `reap_stale_test_containers`, plus the one-line FakeDocker edit. Nothing else changed.
3. FakeDocker edit: pass. Only `removed()` changed; no assertion in test_reaper.py changed. Three deliberately broken reapers still fail the old reaper tests: removing the wrong container name (3 fail), ignoring the age cutoff (1 fails), never calling `rm` (3 fail).
4. Real Docker: pass for both paths. Dangling volumes at baseline 4. `start_throwaway_neo4j` then `stop_throwaway_neo4j`: 4 (no growth). A second throwaway container, reaped by `reap_stale_test_containers` with an injected clock five hours ahead and the docker runner narrowed to that one container: container gone, count 4. Control: `docker rm -f` (no `-v`) on a container from the same image took the count from 4 to 6; the two volumes were removed afterwards. This check exercised the reaper against real Docker, which the evidence section "Not done" says was only unit tested; the claim there is now stale but not untrue.
5. Checks at `d98385f`: 3248 unit tests passed; ruff check clean; format check 336 files; `mypy --strict src` no issues in 132 files; lint-imports 4 kept, 0 broken.
6. DEC-128 present in decisions.md and matches the evidence; no other task branch contains it. Lesson L149 exists and says the same. Not run: the integration suite.
