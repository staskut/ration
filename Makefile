.PHONY: help test lint format test-backend lint-backend test-frontend lint-frontend

help:
	@echo "make test    - run backend and frontend tests"
	@echo "make lint    - lint and check formatting for both"
	@echo "make format  - apply formatting"

test: test-backend test-frontend

lint: lint-backend lint-frontend

test-backend:
	cd backend && uv run pytest

lint-backend:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run lint-imports

format:
	cd backend && uv run ruff format .
	cd backend && uv run ruff check --fix .

test-frontend:
	@if [ -d frontend ]; then cd frontend && npm test -- --run; else echo "no frontend yet"; fi

lint-frontend:
	@if [ -d frontend ]; then cd frontend && npm run lint && npm run typecheck; else echo "no frontend yet"; fi
