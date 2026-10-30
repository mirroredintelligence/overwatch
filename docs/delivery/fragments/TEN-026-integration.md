# TEN-026 integration run (fixG)

## Lessons
- A two-tenant test needs `contracted_container()` (DEC-159); a fixture that creates the audit head of a second tenant on the shared harness schema fails with `ConstraintError: Merge did not find a matching node h` (the single-property audit head key until TEN-032). The default `heads` fixture now creates the run tenant's head only.
- A clinical-safety-officer contact is an email kind (`_PHONE_KINDS` holds the coordination phone and shift-lead escalation only); a phone value is refused.

## Known issues
- `mypy` run on `tests/` reports pre-existing errors (26 in 6 files, for example an unused `type: ignore` at test_tenant_config.py:278); the delivery check is `mypy src`. Trigger: a task that puts tests under mypy.

## Evidence
- `tests/integration/application/test_tenant_config.py`, `graph_store/test_cross_tenant_references.py` and `graph_store/test_tenant_config_repository.py`: 62 passed. `tests/unit` and `tests/architecture`: 10289 passed. ruff check and format, `mypy src`, lint-imports clean.
- Both causes were test or fixture faults. No product change, no cross-tenant leak: the two-tenant test now runs on the contracted schema and passes.
