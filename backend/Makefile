.PHONY: test test-unit up down lint format typecheck check

test:
	uv run pytest

test-unit:
	uv run pytest tests/unit

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
