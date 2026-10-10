.PHONY: help test lint format test-backend test-unit test-integration \
        lint-backend test-frontend lint-frontend

help:
	@echo "make test             - everything"
	@echo "make test-unit        - domain tests, no database"
	@echo "make test-integration - repository and API tests, real database"
	@echo "make lint    - lint and check formatting for both"
	@echo "make format  - apply formatting"

test: test-backend test-frontend

lint: lint-backend lint-frontend

test-backend: test-unit test-integration

test-unit:
	cd backend && uv run pytest tests/unit

test-integration:
	cd backend && uv run pytest tests/integration

lint-backend:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run lint-imports

format:
	cd backend && uv run ruff format .
	cd backend && uv run ruff check --fix .

test-frontend:
	@if [ -d frontend ]; then cd frontend && npm test -- --run; else echo "no frontend yet"; fi

lint-frontend:
	@if [ -d frontend ]; then cd frontend && npm run lint && npm run typecheck; else echo "no frontend yet"; fi
