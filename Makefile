.PHONY: help test lint format test-backend test-unit test-integration \
        test-integration-postgres test-e2e lint-backend test-frontend lint-frontend \
        check-client

help:
	@echo "make test             - everything"
	@echo "make test-unit        - domain tests, no database"
	@echo "make test-integration - repository and API tests, real database"
	@echo "make test-integration-postgres - the same suite, on Postgres"
	@echo "make test-e2e         - two browsers against the compose stack"
	@echo "make lint             - ruff, import contract, oxlint, tsc, client drift"
	@echo "make format           - apply formatting"

test: test-backend test-frontend

lint: lint-backend lint-frontend check-client

test-backend: test-unit test-integration

test-unit:
	cd backend && uv run pytest tests/unit

test-integration:
	cd backend && uv run pytest tests/integration

test-integration-postgres:
	@# The same suite against the database production uses. SQLite differs in
	@# ways that matter, so a green SQLite run says nothing about Postgres.
	cd backend && RATION_TEST_DATABASE_URL=$${RATION_TEST_DATABASE_URL:-postgresql+psycopg://ration:test@localhost:55432/ration_test} uv run pytest tests/integration

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

# 8000 is a popular port. Override to publish elsewhere; the health check and
# the browsers both follow this, so one variable moves the whole target.
RATION_PORT ?= 8000

test-e2e:
	@# Two browser contexts against the compose stack. The stack is reset
	@# first: these write to a real database, and one of them fills the plan's
	@# last unplanned day, so a second run has nothing left to fill.
	RATION_PORT=$(RATION_PORT) docker compose down -v
	RATION_PORT=$(RATION_PORT) docker compose up -d --build
	@# Wait for OUR app, not for whatever else is on the port. This loop used to
	@# accept any 200 on /health, and an unrelated service holding 127.0.0.1:8000
	@# answered it: Docker had *:8000, curl resolved loopback first, and the whole
	@# suite ran against somebody else's application. Eight failures that read as
	@# our regression and were not. `version` is in our payload and not in theirs.
	@until curl -sf http://localhost:$(RATION_PORT)/health 2>/dev/null | grep -q '"version"'; do \
		sleep 2; \
	done
	cd e2e && RATION_BASE_URL=http://localhost:$(RATION_PORT) npm test
