.PHONY: help test lint format test-backend test-unit test-integration \
        lint-backend test-frontend lint-frontend check-client

help:
	@echo "make test             - everything"
	@echo "make test-unit        - domain tests, no database"
	@echo "make test-integration - repository and API tests, real database"
	@echo "make lint    - lint and check formatting for both"
	@echo "make format  - apply formatting"

test: test-backend test-frontend

lint: lint-backend lint-frontend check-client

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

check-client:
	@# The generated client must match openapi.yaml exactly. A drift here means
	@# the frontend is typed against an API the backend no longer serves, which
	@# is the failure the contract-first rule exists to prevent (HLD AD-2).
	@cp frontend/src/api/types.ts /tmp/ration-client-before.ts
	@cd frontend && npm run --silent gen:client
	@if ! diff -q /tmp/ration-client-before.ts frontend/src/api/types.ts >/dev/null; then \
		echo "ERROR: the committed API client does not match openapi.yaml."; \
		echo "Run 'cd frontend && npm run gen:client' and commit the result."; \
		diff -u /tmp/ration-client-before.ts frontend/src/api/types.ts | head -40; \
		cp /tmp/ration-client-before.ts frontend/src/api/types.ts; \
		exit 1; \
	fi
	@echo "API client matches openapi.yaml"
