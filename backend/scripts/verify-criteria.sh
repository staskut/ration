#!/usr/bin/env bash
# Verify the acceptance criteria of closed issues, not just that tests pass.
# A green suite proves the tests agree with the code; this checks the code
# against what the issues actually asked for.
#
#   bash backend/scripts/verify-criteria.sh
#   cd backend && uv run python scripts/verify-behaviour.py
#   cd backend && uv run python scripts/verify-api.py

set -u
pass=0; fail=0
check() { # check "<id>" "<description>" "<command>"
  if ( eval "$3" ) >/dev/null 2>&1; then printf "PASS  %-6s %s\n" "$1" "$2"; pass=$((pass+1))
  else printf "FAIL  %-6s %s\n" "$1" "$2"; fail=$((fail+1)); fi
}
cd /Users/stankutnyk/Projects/ration

echo "--- #1 backend project ---"
check "#1.1" "uv sync completes"            "cd backend && uv sync"
check "#1.2" "pytest passes"                "cd backend && uv run pytest"
check "#1.3" "ruff check exits zero"        "cd backend && uv run ruff check ."
check "#1.4" "ruff format --check zero"     "cd backend && uv run ruff format --check ."
check "#1.5" "requires python 3.12"         "grep -q 'requires-python = \">=3.12\"' backend/pyproject.toml"
check "#1.6" "package named ration"         "grep -q 'name = \"ration\"' backend/pyproject.toml"
check "#1.7" "a test imports ration"        "grep -rq '^import ration' backend/tests/"
check "#1.8" "make test / make lint exist"  "grep -q '^test:' Makefile && grep -q '^lint:' Makefile"

echo "--- #2 frontend scaffold ---"
check "#2.1" "npm install works"            "cd frontend && npm install"
check "#2.2" "npm run build succeeds"       "cd frontend && npm run build"
check "#2.3" "npm test passes"              "cd frontend && npm test -- --run"
check "#2.4" "typecheck passes, strict on"  "cd frontend && npm run typecheck && grep -q '\"strict\": true' tsconfig.app.json"
check "#2.5" "make test runs frontend"      "grep -q 'test-frontend' Makefile"
check "#2.6" "no router/network in src"     "! grep -rqE 'react-router|fetch\\(' frontend/src/"

echo "--- #3 CI ---"
check "#3.1" "runs on PR and main push"     "grep -q 'pull_request' .github/workflows/ci.yml && grep -q 'branches: \\[main\\]' .github/workflows/ci.yml"
check "#3.2" "has ruff/pytest/tsc/vitest"   "grep -q 'ruff check' .github/workflows/ci.yml && grep -q 'pytest' .github/workflows/ci.yml && grep -q 'typecheck' .github/workflows/ci.yml && grep -q 'npm test' .github/workflows/ci.yml"
check "#3.4" "caches deps"                  "grep -q 'enable-cache' .github/workflows/ci.yml && grep -q 'cache: npm' .github/workflows/ci.yml"
check "#3.6" "no deploy steps"              "! grep -qiE 'deploy|flyctl|publish' .github/workflows/ci.yml"

echo "--- #4 domain purity ---"
check "#4.1" "contract forbids frameworks"  "grep -q 'forbidden_modules' backend/pyproject.toml && grep -q 'fastapi' backend/pyproject.toml"
check "#4.2" "lint-imports exits zero"      "cd backend && uv run lint-imports"
check "#4.4" "CI runs lint-imports"         "grep -q 'lint-imports' .github/workflows/ci.yml"
check "#4.5" "domain/__init__.py exists"    "test -f backend/src/ration/domain/__init__.py"

echo "--- #19/#21 persistence commands ---"
check "#19.2" "migration runs clean"        "cd backend && rm -f /tmp/v.db && RATION_DATABASE_URL=sqlite:////tmp/v.db uv run alembic upgrade head"
check "#19.3" "downgrade leaves nothing"    "cd backend && RATION_DATABASE_URL=sqlite:////tmp/v.db uv run alembic downgrade base"
check "#21.1" "ration-seed runs"            "cd backend && rm -f /tmp/s.db && RATION_DATABASE_URL=sqlite:////tmp/s.db uv run alembic upgrade head && RATION_DATABASE_URL=sqlite:////tmp/s.db uv run ration-seed"
check "#21.2" "seed is idempotent"          "cd backend && RATION_DATABASE_URL=sqlite:////tmp/s.db uv run ration-seed"
check "#21.3" "--reset works"               "cd backend && RATION_DATABASE_URL=sqlite:////tmp/s.db uv run ration-seed --reset"
check "#21.6" "refuses production"          "cd backend && ! (RATION_ENV=production RATION_SESSION_SECRET=x RATION_DATABASE_URL=sqlite:////tmp/s.db uv run ration-seed)"

echo "--- #17/#18 contract ---"
check "#17.11" "spec validates"             "cd backend && uv run openapi-spec-validator ../openapi.yaml"
check "#17.12" "no FastAPI schema served"   "grep -q 'openapi_url=None' backend/src/ration/api/app.py"

echo
echo "PASS=$pass FAIL=$fail"
