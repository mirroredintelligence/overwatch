# Evidence: F06-fix, derive the spring gap from the zone in the London test helper

Builder: build-F06fix · Branch: `task/F06-gap-helper-fix` · Corrects: `task/F06-clock-ids` (F06, delivered)
Decision: DEC-061 in `docs/delivery/decisions.md`.

## Honest note

This corrects a test helper in a delivered task (F06). It does not change any production code. The bug was in `is_spring_gap` in `backend/tests/unit/domain/rules/test_london_time.py`, which hard-coded the 2026 change day. The production `london_to_utc` was correct throughout. The ledger was not updated for this fix, and the F06 evidence file is unchanged.

## Commits

| Step | Commit | Message |
|---|---|---|
| Red | `36d59da` | `F06fix: failing regression test (red)` |
| Green | `88408b8` | `F06fix: derive the spring gap from the zone` |
| Lint fix | `e25b768` | `F06fix: shorten helper docstring to pass ruff` |

## Red: regression tests on the old helper (commit 36d59da)

Command, from `backend/`: `PYTHONIOENCODING=utf-8 python -m uv run pytest tests/unit/domain/rules/test_london_time.py -q -k "2020_change_day or derived_from_the_zone"`

```
FF                                                                       [100%]
____________ test_spring_gap_is_recognised_on_the_2020_change_day _____________
    def test_spring_gap_is_recognised_on_the_2020_change_day() -> None:
        day = date(2020, 3, 29)
>       assert is_spring_gap(day, time(1, 0))
E       assert False
E        +  where False = is_spring_gap(datetime.date(2020, 3, 29), datetime.time(1, 0))
tests\unit\domain\rules\test_london_time.py:223: AssertionError
___________ test_spring_gap_is_derived_from_the_zone_for_every_year ___________
>       assert is_spring_gap(spring, time(1, 0)), year
E       AssertionError: 2020
E       assert False
2 failed, 35 deselected in 1.86s
```

Both fail on the assertion, not on an import error.

Property on the old helper, seed 3 (the property is randomised, so seed 0 passed and was not a reproduction): `F06fix-red-property-seed3.txt` in the session scratchpad.

```
>       assert london_to_utc(day, a) < london_to_utc(day, b)
E       assert datetime(2030, 3, 31, 1, 0, UTC) < datetime(2030, 3, 31, 1, 0, UTC)
E           day=datetime.date(2030, 3, 31),
E           first=minute_to_time(60),
E           second=minute_to_time(120),
1 failed
```

Seeds 0 to 12 were probed. Seed 3 was the only one of them that failed on the old helper. The failing day is 2030-03-31, not 2020-03-29. It is the same class of failure: a spring change day the helper does not know.

## Green: the helper derives the gap (commit 88408b8)

`is_spring_gap` now returns False outside 01:00 to 01:59. Inside it, it returns True only when the UTC offset at 00:30 local is less than the offset at 02:30 local. The 2026 constant `SPRING_CHANGE` is kept for the existing examples and boundary tests. No existing assertion was changed.

`test_london_time.py`, all 37 tests, on seeds 0 to 5 and on seed 3: 37 passed each time.

## Checks (from `backend/`, PYTHONIOENCODING=utf-8, `python -m uv run`)

| Check | Result |
|---|---|
| `pytest tests/unit tests/architecture -q` | 2562 passed in 49.02s (run after the lint fix, commit e25b768) |
| `ruff check .` | All checks passed! (after the lint fix; the first run had one E501 in a docstring, fixed in e25b768) |
| `ruff format --check .` | 170 files already formatted |
| `mypy src` | Success: no issues found in 77 source files |
| `lint-imports` | Contracts: 4 kept, 0 broken |

The monotonic property `test_conversion_is_monotonic_within_a_day_outside_the_gap` passes on the new helper, including the 2020 and 2030 change days and the 2026 change day. Hypothesis ran with its default example count, not a fixed count. The test-file seed sweep is listed above. The integration tests were not run, because this change touches only a unit test file and the shared Neo4j stack is not needed for it.

## Spec trace

Not applicable. This is a test-helper correction and it does not add a requirement. The rule under test is the F06 rule that London wall-clock times in the gap are shifted forward by one hour (`docs/spec/domain-rules.md`, clock change). The helper is what the test uses to decide which local times are in the gap.
