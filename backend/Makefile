.PHONY: test test-unit test-integration test-parallel neo4j-shared-up neo4j-shared-down up down lint format typecheck check

# Parallel runs (TEN-035). Neo4j tests share one Neo4j and each worker has its own tenants, so the
# parallel phase needs no lock. Tests marked `exclusive` (the Service Bus emulator, the compose
# stack) cannot share the machine: they run afterwards in a session of their own, and the second
# phase runs even when the first fails, so both results are reported. WORKERS sets the number of
# workers (4 fits a 4-core machine).
WORKERS ?= 4
PARALLEL = -n $(WORKERS) --dist loadfile -m "not exclusive"

test:
	uv run pytest

test-unit:
	uv run pytest tests/unit

# The integration and contract suites: the parallel phase, then the exclusive phase.
test-integration:
	status=0; \
	uv run pytest $(PARALLEL) tests/integration tests/contract || status=$$?; \
	uv run pytest -m exclusive tests/integration tests/contract || status=$$?; \
	exit $$status

# Everything: unit, architecture, integration and contract, in the same two phases.
test-parallel:
	status=0; \
	uv run pytest $(PARALLEL) tests/unit tests/architecture tests/integration tests/contract || status=$$?; \
	uv run pytest -m exclusive tests/integration tests/contract || status=$$?; \
	exit $$status

# The machine's shared Neo4j for the tests (started on demand by any run; these two are for people).
neo4j-shared-up:
	uv run python -m tests.support.harness_mode up

neo4j-shared-down:
	uv run python -m tests.support.harness_mode down

up:
	docker compose -f ../infra/docker-compose.yml up -d --wait

down:
	docker compose -f ../infra/docker-compose.yml down

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run lint-imports

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy src

check: lint typecheck test-unit
