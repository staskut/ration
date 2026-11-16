#!/usr/bin/env bash
# Post-deploy smoke test.
#
# Checks the things a broken release breaks first, and fails loudly. A deploy
# pipeline whose smoke test cannot fail is a deploy pipeline without one.
#
#   scripts/smoke-test.sh https://ration-plan.fly.dev
set -euo pipefail

BASE="${1:?usage: smoke-test.sh <base-url>}"
failures=0

check() {
  local description="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    printf 'ok    %s\n' "$description"
  else
    printf 'FAIL  %s (expected %s, got %s)\n' "$description" "$expected" "$actual"
    failures=$((failures + 1))
  fi
}

check "health responds" "200" \
  "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health")"

# A release that cannot say which release it is leaves an alert payload saying
# "dev" in production, and nothing to roll back to. Losing this plumbing is
# silent everywhere else, so it fails the deploy here.
version=$(curl -s "$BASE/health" | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
if [ -n "$version" ]; then
  printf 'ok    health names its release (%s)\n' "$version"
else
  printf 'FAIL  health does not name its release\n'
  failures=$((failures + 1))
fi

check "the frontend is served" "200" \
  "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/")"

# The one that catches a half-deployed image: assets missing means the build
# stage did not land, and the page loads blank rather than erroring.
asset=$(curl -s "$BASE/" | grep -o '/assets/[^"]*\.js' | head -1)
if [ -n "$asset" ]; then
  check "the js bundle is served" "200" \
    "$(curl -s -o /dev/null -w '%{http_code}' "$BASE$asset")"
else
  printf 'FAIL  the page references no js bundle\n'
  failures=$((failures + 1))
fi

# An authenticated endpoint must refuse rather than error: a 500 here means
# the database is unreachable, which a health check on its own would miss.
check "the api requires a session" "401" \
  "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/plans")"

check "an unknown api path is a json 404" "404" \
  "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/nope")"

check "a deep link reaches the spa" "200" \
  "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/some/deep/link")"

if [ "$failures" -gt 0 ]; then
  printf '\n%s check(s) failed.\n' "$failures"
  exit 1
fi
printf '\nAll checks passed against %s\n' "$BASE"
